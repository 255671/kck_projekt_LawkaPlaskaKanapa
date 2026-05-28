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
state = {"frame_front": None, "frame_side": None, "points_front": None, "ts_ms": 0}
locks = {"frame_front": threading.Lock(), "frame_side": threading.Lock(), "points_front": threading.Lock()}


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
        lm = get_landmarker()
    except Exception as e:
        print(e); return

    while True:
        cfg = config.snapshot()
        time.sleep(1.0 / max(1, cfg["pts_fps"]))

        with locks["frame_front"]:
            f = state["frame_front"]
        if f is None: continue

        mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(f.copy(), cv2.COLOR_BGR2RGB))
        state["ts_ms"] += int(1000 / max(1, cfg["pts_fps"]))

        try:
            res = lm.detect_for_video(mp_img, state["ts_ms"])
            with locks["points_front"]:
                state["points_front"] = res.pose_landmarks[0] if res.pose_landmarks else None
        except Exception as e:
            print(f"Inference err: {e}")


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
                    await ws.send(json.dumps({"image": None, "imageSide": None, "points": None})); continue
                except:
                    break

            with locks["frame_front"]:
                f_front = state["frame_front"]
            with locks["frame_side"]:
                f_side = state["frame_side"]
            with locks["points_front"]:
                pts = state["points_front"]
            if f_front is None and f_side is None:
                continue

            b64_front = None
            pts_data = None
            if f_front is not None:
                img = draw_landmarks(f_front, pts) if cfg["ar"] else f_front
                b64_front = base64.b64encode(cv2.imencode('.jpg', img)[1]).decode('utf-8')
                pts_data = [{"x": p.x, "y": p.y, "z": p.z, "v": getattr(p, 'visibility', 0)} for p in pts] if pts else None

            b64_side = None
            if f_side is not None:
                b64_side = base64.b64encode(cv2.imencode('.jpg', f_side)[1]).decode('utf-8')

            try:
                await ws.send(json.dumps({"image": b64_front, "imageSide": b64_side, "points": pts_data}))
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