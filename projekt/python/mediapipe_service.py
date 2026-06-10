import asyncio, os, sys, threading, logging, time, json, base64
import cv2
import websockets
import mediapipe as mp

logging.getLogger("websockets").setLevel(logging.CRITICAL)

# ---------------------------------------------------------------------------
# CONSTANTS & SETUP
# ---------------------------------------------------------------------------
ARGS = sys.argv
PORT = int(ARGS[ARGS.index('-p') + 1]) if '-p' in ARGS else int(
    ARGS[ARGS.index('--port') + 1]) if '--port' in ARGS else int(os.getenv('MEDIAPIPE_WS_PORT', 8765))
MODEL_PATH = ARGS[ARGS.index('-m') + 1] if '-m' in ARGS else ARGS[
    ARGS.index('--model') + 1] if '--model' in ARGS else os.getenv('MEDIAPIPE_MODEL_PATH', "pose_landmarker_full.task")

POSE_CONNECTIONS = [(0, 1), (1, 2), (2, 3), (3, 7), (0, 4), (4, 5), (5, 6), (6, 8), (9, 10), (11, 12), (11, 13),
                    (13, 15), (15, 17), (15, 19), (15, 21), (17, 19), (12, 14), (14, 16), (16, 18), (16, 20), (16, 22),
                    (18, 20), (11, 23), (12, 24), (23, 24), (23, 25), (25, 27), (27, 29), (27, 31), (29, 31), (24, 26),
                    (26, 28), (28, 30), (28, 32), (30, 32)]

# ---------------------------------------------------------------------------
# SHARED STATE & CONFIG
# ---------------------------------------------------------------------------
state = {
    "frame_front": None,
    "frame_side": None,
    "points_front": None,
    "points_side": None,
    "ts_ms_front": 0,
    "ts_ms_side": 0,
}
locks = {
    "frame_front": threading.Lock(),
    "frame_side": threading.Lock(),
    "points_front": threading.Lock(),
    "points_side": threading.Lock(),
}

# ---------------------------------------------------------------------------
# EXERCISE DETECTION (Bulgarian split squat) — state machine + hysteresis
# ---------------------------------------------------------------------------
# States: IDLE -> DESCENDING -> BOTTOM -> ASCENDING -> (rep++) IDLE
# Tracking starts only after a valid starting pose is held (back foot elevated).

ANGLE_TOP_STANDING = 158.0       # knee extended at start / finish
ANGLE_DESCEND_ENTER = 142.0      # must drop below to start descent (deadzone above)
ANGLE_BOTTOM_ENTER = 105.0       # sufficient depth
ANGLE_BOTTOM_EXIT = 118.0        # hysteresis: leave bottom only above this
ANGLE_REP_COMPLETE = 154.0       # must extend above this to count rep (below standing)

ELEVATION_MIN = 0.06             # back ankle must be higher than front (normalized y)
BACK_KNEE_MIN = 130.0            # back leg relatively extended on bench

START_HOLD_FRAMES = 10           # valid start must be held before arming
CONFIRM_FRAMES = 5               # frames required for each transition
ABORT_FRAMES = 8                 # invalid pose frames before aborting active rep

exercise_state = {
    "enabled": True,
    "name": "bulgarian_squat",
    "repCount": 0,
    "phase": "IDLE",
    "armed": False,
    "lastKneeAngle": None,
    "lastLeg": None,
    "lastSource": None,
    "lastElevation": None,
    "sm_state": "IDLE",
    "start_hold_frames": 0,
    "confirm_frames": 0,
    "abort_frames": 0,
    "reached_bottom": False,
    "lastMetrics": None,
}


def _angle_deg(a, b, c) -> float:
    import math
    bax = a[0] - b[0]
    bay = a[1] - b[1]
    bcx = c[0] - b[0]
    bcy = c[1] - b[1]
    dot = bax * bcx + bay * bcy
    n1 = math.hypot(bax, bay)
    n2 = math.hypot(bcx, bcy)
    if n1 == 0.0 or n2 == 0.0:
        return float("nan")
    cosv = max(-1.0, min(1.0, dot / (n1 * n2)))
    return math.degrees(math.acos(cosv))


def _lm_xy(lm):
    if hasattr(lm, "x") and hasattr(lm, "y"):
        return lm.x, lm.y
    if isinstance(lm, dict):
        return lm.get("x"), lm.get("y")
    return None, None


def _lm_visible(lm, min_visibility: float = 0.25) -> bool:
    visibility = getattr(lm, "visibility", None)
    if visibility is None and isinstance(lm, dict):
        visibility = lm.get("v", lm.get("visibility"))
    if visibility is None:
        return True
    return visibility >= min_visibility


def _leg_metrics(pts, hip_i, knee_i, ankle_i, side_name):
    if not pts or len(pts) <= ankle_i:
        return None
    hip, knee, ankle = pts[hip_i], pts[knee_i], pts[ankle_i]
    if not (_lm_visible(hip) and _lm_visible(knee) and _lm_visible(ankle)):
        return None
    hx, hy = _lm_xy(hip)
    kx, ky = _lm_xy(knee)
    ax, ay = _lm_xy(ankle)
    if None in (hx, hy, kx, ky, ax, ay):
        return None
    knee_angle = _angle_deg((hx, hy), (kx, ky), (ax, ay))
    if knee_angle != knee_angle:
        return None
    return {
        "side": side_name,
        "knee_angle": knee_angle,
        "ankle_y": ay,
        "ankle_x": ax,
        "hip_y": hy,
        "knee_y": ky,
    }


def _analyze_bulgarian_pose(pts):
    """
  Side-view pose: identify front (working) and back (elevated) leg.
  Returns dict with front_knee_angle, elevation, etc. or None.
    """
    left = _leg_metrics(pts, 23, 25, 27, "left")
    right = _leg_metrics(pts, 24, 26, 28, "right")
    legs = [l for l in (left, right) if l is not None]
    if len(legs) < 2:
        return None

    # Front leg: ankle lower in frame (larger y). Back leg: elevated (smaller y).
    front = max(legs, key=lambda l: l["ankle_y"])
    back = min(legs, key=lambda l: l["ankle_y"])
    elevation = front["ankle_y"] - back["ankle_y"]

    return {
        "front": front,
        "back": back,
        "elevation": elevation,
        "front_knee_angle": front["knee_angle"],
        "back_knee_angle": back["knee_angle"],
        "front_leg": front["side"],
    }


def _is_valid_start_pose(pose):
    """Strict starting position before tracking is armed."""
    return (
        pose["elevation"] >= ELEVATION_MIN
        and pose["front_knee_angle"] >= ANGLE_TOP_STANDING
        and pose["back_knee_angle"] >= BACK_KNEE_MIN
    )


def _is_pose_trackable(pose):
    """Looser check during an active rep — back foot still elevated."""
    return pose["elevation"] >= (ELEVATION_MIN * 0.6)


def _reset_rep_tracking():
    exercise_state["sm_state"] = "IDLE"
    exercise_state["armed"] = False
    exercise_state["start_hold_frames"] = 0
    exercise_state["confirm_frames"] = 0
    exercise_state["abort_frames"] = 0
    exercise_state["reached_bottom"] = False
    exercise_state["phase"] = "IDLE"


def _bump_confirm(current: int, target: int) -> int:
    return current + 1 if current < target else target


def update_bulgarian_squat(pts_prefer_side, pts_fallback_front):
    """
    Bulgarian split squat rep counter with state machine and hysteresis.
    Prefer side camera — front view is too unreliable for split squat geometry.
    """
    pts = pts_prefer_side if pts_prefer_side else pts_fallback_front
    source = "side" if pts_prefer_side else "front"

    pose = _analyze_bulgarian_pose(pts)
    if pose is None:
        if exercise_state["sm_state"] != "IDLE":
            exercise_state["abort_frames"] += 1
            if exercise_state["abort_frames"] >= ABORT_FRAMES:
                _reset_rep_tracking()
        else:
            exercise_state["phase"] = "IDLE"
        exercise_state["lastKneeAngle"] = None
        exercise_state["lastLeg"] = None
        exercise_state["lastSource"] = source
        exercise_state["lastElevation"] = None
        return None

    angle = pose["front_knee_angle"]
    sm = exercise_state["sm_state"]

    exercise_state["lastKneeAngle"] = angle
    exercise_state["lastLeg"] = pose["front_leg"]
    exercise_state["lastSource"] = source
    exercise_state["lastElevation"] = round(pose["elevation"], 3)
    exercise_state["abort_frames"] = 0

    valid_start = _is_valid_start_pose(pose)
    trackable = _is_pose_trackable(pose)

    # --- IDLE: validate starting position before arming ---
    if sm == "IDLE":
        if valid_start:
            exercise_state["start_hold_frames"] = _bump_confirm(
                exercise_state["start_hold_frames"], START_HOLD_FRAMES
            )
        else:
            exercise_state["start_hold_frames"] = 0
            exercise_state["armed"] = False

        if exercise_state["start_hold_frames"] >= START_HOLD_FRAMES:
            exercise_state["armed"] = True

        if exercise_state["armed"] and angle < ANGLE_DESCEND_ENTER:
            exercise_state["confirm_frames"] = _bump_confirm(
                exercise_state["confirm_frames"], CONFIRM_FRAMES
            )
            if exercise_state["confirm_frames"] >= CONFIRM_FRAMES:
                exercise_state["sm_state"] = "DESCENDING"
                exercise_state["confirm_frames"] = 0
                exercise_state["reached_bottom"] = False
        else:
            if sm == "IDLE":
                exercise_state["confirm_frames"] = 0

    # --- DESCENDING: moving down, wait for sufficient depth ---
    elif sm == "DESCENDING":
        if not trackable:
            exercise_state["abort_frames"] += 1
            if exercise_state["abort_frames"] >= ABORT_FRAMES:
                _reset_rep_tracking()
                return _metrics(pose, source)
        elif angle < ANGLE_BOTTOM_ENTER:
            exercise_state["confirm_frames"] = _bump_confirm(
                exercise_state["confirm_frames"], CONFIRM_FRAMES
            )
            if exercise_state["confirm_frames"] >= CONFIRM_FRAMES:
                exercise_state["sm_state"] = "BOTTOM"
                exercise_state["confirm_frames"] = 0
                exercise_state["reached_bottom"] = True
        elif angle > ANGLE_TOP_STANDING:
            # False start — returned to standing without depth
            _reset_rep_tracking()

    # --- BOTTOM: at depth, wait for ascent (hysteresis exit) ---
    elif sm == "BOTTOM":
        if not trackable:
            exercise_state["abort_frames"] += 1
            if exercise_state["abort_frames"] >= ABORT_FRAMES:
                _reset_rep_tracking()
                return _metrics(pose, source)
        elif angle > ANGLE_BOTTOM_EXIT:
            exercise_state["confirm_frames"] = _bump_confirm(
                exercise_state["confirm_frames"], CONFIRM_FRAMES
            )
            if exercise_state["confirm_frames"] >= CONFIRM_FRAMES:
                exercise_state["sm_state"] = "ASCENDING"
                exercise_state["confirm_frames"] = 0

    # --- ASCENDING: coming back up, count rep only after full extension ---
    elif sm == "ASCENDING":
        if not trackable:
            exercise_state["abort_frames"] += 1
            if exercise_state["abort_frames"] >= ABORT_FRAMES:
                _reset_rep_tracking()
                return _metrics(pose, source)
        elif angle < ANGLE_BOTTOM_ENTER:
            # Dropped back down without finishing — return to bottom
            exercise_state["sm_state"] = "BOTTOM"
            exercise_state["confirm_frames"] = 0
        elif angle > ANGLE_REP_COMPLETE and exercise_state["reached_bottom"]:
            exercise_state["confirm_frames"] = _bump_confirm(
                exercise_state["confirm_frames"], CONFIRM_FRAMES
            )
            if exercise_state["confirm_frames"] >= CONFIRM_FRAMES:
                exercise_state["repCount"] += 1
                _reset_rep_tracking()
                exercise_state["start_hold_frames"] = 0
        else:
            exercise_state["confirm_frames"] = 0

    exercise_state["phase"] = exercise_state["sm_state"]
    exercise_state["lastMetrics"] = _metrics(pose, source)
    return exercise_state["lastMetrics"]


def _metrics(pose, source):
    return {
        "kneeAngle": round(pose["front_knee_angle"], 1),
        "backKneeAngle": round(pose["back_knee_angle"], 1),
        "leg": pose["front_leg"],
        "source": source,
        "elevation": round(pose["elevation"], 3),
        "armed": exercise_state["armed"],
        "reachedBottom": exercise_state["reached_bottom"],
    }

class Config:
    def __init__(self):
        self.lock = threading.Lock()
        self.cam_en, self.ar = False, True
        self.front_idx, self.side_idx = 0, 0
        self.front_w, self.front_h, self.front_fps = 1280, 720, 10
        self.side_w, self.side_h, self.side_fps = 1280, 720, 10
        self.pts_fps = 10
        self.restart_front = False
        self.restart_side = False

    def apply(self, p: dict):
        cameras = p.get("cameras", {})
        f = cameras.get("front", {}) or {}
        s = cameras.get("side", {}) or {}
        with self.lock:
            self.cam_en = bool(cameras.get("enabled", self.cam_en))
            self.ar = bool(cameras.get("ar_overlay", self.ar))
            if "fps" in f:
                self.front_fps = int(f["fps"])
                self.pts_fps = int(f["fps"])
            if "fps" in s:
                self.side_fps = int(s["fps"])
            try:
                if "resolution" in f:
                    nw, nh = map(int, f["resolution"].split("x"))
                    if (nw, nh) != (self.front_w, self.front_h):
                        self.front_w, self.front_h, self.restart_front = nw, nh, True

                if "deviceId" in f:
                    device_id = f["deviceId"]
                    if isinstance(device_id, int):
                        new_idx = device_id
                    elif isinstance(device_id, str) and device_id.isdigit():
                        new_idx = int(device_id)
                    else:
                        new_idx = None

                    if new_idx is not None and new_idx != self.front_idx:
                        self.front_idx, self.restart_front = new_idx, True

                if "resolution" in s:
                    nw, nh = map(int, s["resolution"].split("x"))
                    if (nw, nh) != (self.side_w, self.side_h):
                        self.side_w, self.side_h, self.restart_side = nw, nh, True

                if "deviceId" in s:
                    device_id = s["deviceId"]
                    if isinstance(device_id, int):
                        new_idx = device_id
                    elif isinstance(device_id, str) and device_id.isdigit():
                        new_idx = int(device_id)
                    else:
                        new_idx = None

                    if new_idx is not None and new_idx != self.side_idx:
                        self.side_idx, self.restart_side = new_idx, True
            except (ValueError, TypeError):
                pass

    def snapshot(self):
        with self.lock: return dict(self.__dict__)


config = Config()


# ---------------------------------------------------------------------------
# MEDIAPIPE CORE
# ---------------------------------------------------------------------------
def get_landmarker():
    if not os.path.exists(MODEL_PATH): raise FileNotFoundError(f"Missing model: {MODEL_PATH}")
    opts = mp.tasks.vision.PoseLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(model_asset_path=MODEL_PATH),
        running_mode=mp.tasks.vision.RunningMode.VIDEO,
        num_poses=1, min_pose_detection_confidence=0.5, min_pose_presence_confidence=0.5, min_tracking_confidence=0.5
    )
    return mp.tasks.vision.PoseLandmarker.create_from_options(opts)


def draw_landmarks(frame, pts):
    if not pts: return frame
    img, (h, w) = frame.copy(), frame.shape[:2]
    p_px = [(int(lm.x * w), int(lm.y * h)) for lm in pts]
    for s, e in POSE_CONNECTIONS:
        if s < len(p_px) and e < len(p_px): cv2.line(img, p_px[s], p_px[e], (255, 0, 0), 2, cv2.LINE_AA)
    for x, y in p_px: cv2.circle(img, (x, y), 4, (0, 255, 0), -1, cv2.LINE_AA)
    return img


def is_full_body_visible(pts, margin: float = 0.05, min_visibility: float = 0.5) -> bool:
    """
    Heurystyka: uznajemy 'cała sylwetka w kadrze', jeśli kluczowe punkty (głowa/tułów/stopy)
    są wykryte, mają visibility oraz nie wypadają poza kadr (z marginesem).
    """
    if not pts:
        return False

    # MediaPipe Pose landmarks indices
    required = [
        0,   # nose (głowa)
        11,  # left_shoulder
        12,  # right_shoulder
        23,  # left_hip
        24,  # right_hip
        27,  # left_ankle
        28,  # right_ankle
    ]

    for idx in required:
        if idx >= len(pts):
            return False
        lm = pts[idx]
        v = getattr(lm, "visibility", 0.0) or 0.0
        if v < min_visibility:
            return False
        if not (margin <= lm.x <= 1.0 - margin and margin <= lm.y <= 1.0 - margin):
            return False

    return True


# ---------------------------------------------------------------------------
# BACKGROUND THREADS
# ---------------------------------------------------------------------------
def camera_thread_fn():
    cap_front = None
    cap_side = None
    while True:
        cfg = config.snapshot()
        if not cfg["cam_en"]:
            time.sleep(0.05)
            continue

        if cap_front is None or cfg["restart_front"]:
            if cap_front:
                cap_front.release()
                time.sleep(0.3)
            cap_front = cv2.VideoCapture(cfg["front_idx"], cv2.CAP_MSMF)
            if not cap_front.isOpened():
                cap_front = None
                time.sleep(1.0)
            else:
                with config.lock:
                    config.restart_front = False
                print(f"Kamera FRONT {cfg['front_idx']} start -> Cel: {cfg['front_w']}x{cfg['front_h']}", flush=True)

        if cap_side is None or cfg["restart_side"]:
            if cap_side:
                cap_side.release()
                time.sleep(0.3)
            cap_side = cv2.VideoCapture(cfg["side_idx"], cv2.CAP_MSMF)
            if not cap_side.isOpened():
                cap_side = None
                time.sleep(1.0)
            else:
                with config.lock:
                    config.restart_side = False
                print(f"Kamera SIDE {cfg['side_idx']} start -> Cel: {cfg['side_w']}x{cfg['side_h']}", flush=True)

        if cap_front:
            ret, frame = cap_front.read()
            if ret:
                if frame.shape[:2] != (cfg["front_h"], cfg["front_w"]):
                    frame = cv2.resize(frame, (cfg["front_w"], cfg["front_h"]), interpolation=cv2.INTER_LINEAR)
                with locks["frame_front"]:
                    state["frame_front"] = frame

        if cap_side:
            ret, frame = cap_side.read()
            if ret:
                if frame.shape[:2] != (cfg["side_h"], cfg["side_w"]):
                    frame = cv2.resize(frame, (cfg["side_w"], cfg["side_h"]), interpolation=cv2.INTER_LINEAR)
                with locks["frame_side"]:
                    state["frame_side"] = frame

        time.sleep(0.001)


def inference_thread_fn():
    try:
        lm_front = get_landmarker()
        lm_side = get_landmarker()
    except Exception as e:
        print(e); return

    while True:
        cfg = config.snapshot()
        time.sleep(1.0 / max(1, cfg["pts_fps"]))

        with locks["frame_front"]:
            f_front = state["frame_front"]
        with locks["frame_side"]:
            f_side = state["frame_side"]

        if f_front is None and f_side is None:
            continue

        if f_front is not None:
            try:
                mp_img_front = mp.Image(
                    image_format=mp.ImageFormat.SRGB,
                    data=cv2.cvtColor(f_front.copy(), cv2.COLOR_BGR2RGB),
                )
                state["ts_ms_front"] += int(1000 / max(1, cfg["pts_fps"]))
                res_front = lm_front.detect_for_video(mp_img_front, state["ts_ms_front"])
                with locks["points_front"]:
                    state["points_front"] = res_front.pose_landmarks[0] if res_front.pose_landmarks else None
            except Exception as e:
                print(f"Inference err (front): {e}")

        if f_side is not None:
            try:
                mp_img_side = mp.Image(
                    image_format=mp.ImageFormat.SRGB,
                    data=cv2.cvtColor(f_side.copy(), cv2.COLOR_BGR2RGB),
                )
                state["ts_ms_side"] += int(1000 / max(1, cfg["pts_fps"]))
                res_side = lm_side.detect_for_video(mp_img_side, state["ts_ms_side"])
                with locks["points_side"]:
                    state["points_side"] = res_side.pose_landmarks[0] if res_side.pose_landmarks else None
            except Exception as e:
                print(f"Inference err (side): {e}")

        with locks["points_front"]:
            pts_front = state["points_front"]
        with locks["points_side"]:
            pts_side = state["points_side"]
        update_bulgarian_squat(pts_side, pts_front)


# ---------------------------------------------------------------------------
# WEBSOCKET SERVER
# ---------------------------------------------------------------------------
async def ws_handler(ws):
    print("Electron connected", flush=True)

    async def sender():
        while True:
            cfg = config.snapshot()
            await asyncio.sleep(1.0 / max(1, cfg["front_fps"]))
            if not cfg["cam_en"]:
                try:
                    await ws.send(json.dumps({
                        "image": None,
                        "imageSide": None,
                        "points": None,
                        "exercise": {
                            "name": exercise_state["name"],
                            "repCount": exercise_state["repCount"],
                            "phase": exercise_state["phase"],
                            "metrics": None,
                        },
                    }))
                    continue
                except:
                    break

            with locks["frame_front"]:
                f_front = state["frame_front"]
            with locks["frame_side"]:
                f_side = state["frame_side"]
            with locks["points_front"]:
                pts_front = state["points_front"]
            with locks["points_side"]:
                pts_side = state["points_side"]
            if f_front is None and f_side is None:
                continue

            full_front = is_full_body_visible(pts_front) if f_front is not None else False
            full_side = is_full_body_visible(pts_side) if f_side is not None else False
            ex_metrics = exercise_state.get("lastMetrics")

            b64_front = None
            pts_data = None
            if f_front is not None:
                img = draw_landmarks(f_front, pts_front) if cfg["ar"] else f_front
                b64_front = base64.b64encode(cv2.imencode('.jpg', img)[1]).decode('utf-8')
                pts_data = [{"x": p.x, "y": p.y, "z": p.z, "v": getattr(p, 'visibility', 0)} for p in pts_front] if pts_front else None

            b64_side = None
            if f_side is not None:
                img_side = draw_landmarks(f_side, pts_side) if cfg["ar"] else f_side
                b64_side = base64.b64encode(cv2.imencode('.jpg', img_side)[1]).decode('utf-8')

            try:
                await ws.send(json.dumps({
                    "image": b64_front,
                    "imageSide": b64_side,
                    "points": pts_data,
                    "fullBodyVisibleFront": full_front,
                    "fullBodyVisibleSide": full_side,
                    "exercise": {
                        "name": exercise_state["name"],
                        "repCount": exercise_state["repCount"],
                        "phase": exercise_state["phase"],
                        "metrics": ex_metrics,
                    },
                }))
            except:
                break

    async def receiver():
        async for raw in ws:
            try:
                msg = json.loads(raw)
                if msg.get("type") == "config":
                    config.apply(msg.get("payload", {}))
                    print(f"Updated config: {config.snapshot()}", flush=True)
                    await ws.send(json.dumps({"type": "config_ack", "status": "success"}))
            except:
                pass

    await asyncio.gather(sender(), receiver())


async def main():
    threading.Thread(target=camera_thread_fn, daemon=True).start()
    threading.Thread(target=inference_thread_fn, daemon=True).start()
    print(f"WS Server: 127.0.0.1:{PORT}", flush=True)
    async with websockets.serve(ws_handler, "127.0.0.1", PORT):
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())