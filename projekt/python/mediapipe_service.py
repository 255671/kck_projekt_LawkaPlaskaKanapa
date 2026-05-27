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
state = {"frame": None, "frame_side": None, "points": None, "points_side": None, "ts_ms": 0}
locks = {"frame": threading.Lock(), "frame_side": threading.Lock(), "points": threading.Lock(), "points_side": threading.Lock()}


class Config:
    def __init__(self):
        self.lock = threading.Lock()
        self.cam_idx, self.cam_en, self.cam_fps, self.ar = 0, False, 10, True
        self.cam_idx_side, self.cam_en_side, self.cam_fps_side = 1, False, 10
        self.w, self.h, self.w_side, self.h_side, self.pts_fps = 1920, 1080, 1920, 1080, 10
        self.restart, self.restart_side = False, False


    
    def _resolve_device_id(self, device_id):
        if isinstance(device_id, int):
            return device_id
        if isinstance(device_id, str) and device_id.isdigit():
            return int(device_id)
        return None

    def apply(self, p: dict):
        cameras = p.get("cameras", {})
        front = cameras.get("front", {})
        side = cameras.get("side", {})
        with self.lock:
            self.cam_en = bool(cameras.get("enabled", self.cam_en))
            self.cam_en_side = bool(cameras.get("enabled", self.cam_en_side))
            self.ar = bool(cameras.get("ar_overlay", self.ar))

            if "fps" in front:
                self.cam_fps = int(front["fps"])
            if "fps" in side:
                self.cam_fps_side = int(side["fps"])

            try:
                if "resolution" in front:
                    nw, nh = map(int, front["resolution"].split("x"))
                    if (nw, nh) != (self.w, self.h):
                        self.w, self.h, self.restart = nw, nh, True

                if "deviceId" in front:
                    new_idx = self._resolve_device_id(front["deviceId"])
                    if new_idx is not None and new_idx != self.cam_idx:
                        self.cam_idx, self.restart = new_idx, True

                if "resolution" in side:
                    nw, nh = map(int, side["resolution"].split("x"))
                    if (nw, nh) != (self.w_side, self.h_side):
                        self.w_side, self.h_side, self.restart_side = nw, nh, True

                if "deviceId" in side:
                    new_idx = self._resolve_device_id(side["deviceId"])
                    if new_idx is not None and new_idx != self.cam_idx_side:
                        self.cam_idx_side, self.restart_side = new_idx, True
            except (ValueError, TypeError):
                pass

            self.pts_fps = max(self.cam_fps, self.cam_fps_side, 1)

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
def camera_thread_fn(camera_key='front'):
    cap = None
    state_key = 'frame' if camera_key == 'front' else 'frame_side'
    restart_key = 'restart' if camera_key == 'front' else 'restart_side'
    idx_key = 'cam_idx' if camera_key == 'front' else 'cam_idx_side'
    w_key = 'w' if camera_key == 'front' else 'w_side'
    h_key = 'h' if camera_key == 'front' else 'h_side'

    while True:
        cfg = config.snapshot()
        should_restart = cfg.get(restart_key, False)
        if cap is None or should_restart:
            if cap:
                cap.release()
                time.sleep(0.3)
            cap = cv2.VideoCapture(cfg[idx_key], cv2.CAP_MSMF)
            if not cap.isOpened():
                cap = None
                time.sleep(2.0)
                continue
            with config.lock:
                if camera_key == 'front':
                    config.restart = False
                else:
                    config.restart_side = False
            print(f"Kamera {camera_key} {cfg[idx_key]} start -> Cel: {cfg[w_key]}x{cfg[h_key]}", flush=True)

        ret, frame = cap.read()
        if not ret:
            time.sleep(0.01)
            continue

        if frame.shape[:2] != (cfg[h_key], cfg[w_key]):
            frame = cv2.resize(frame, (cfg[w_key], cfg[h_key]), interpolation=cv2.INTER_LINEAR)

        with locks[state_key]:
            state[state_key] = frame


def inference_thread_fn():
    try:
        lm = get_landmarker()
    except Exception as e:
        print(e)
        return

    while True:
        cfg = config.snapshot()
        fps = max(1, cfg["pts_fps"])
        time.sleep(1.0 / fps)

        state["ts_ms"] = max(state["ts_ms"] + int(1000 / fps), int(time.time() * 1000))

        for offset, (frame_key, points_key) in enumerate((("frame", "points"), ("frame_side", "points_side"))):
            with locks[frame_key]:
                f = state[frame_key]
            if f is None:
                continue

            try:
                mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(f.copy(), cv2.COLOR_BGR2RGB))
                timestamp_ms = state["ts_ms"] + offset
                res = lm.detect_for_video(mp_img, timestamp_ms)
                with locks[points_key]:
                    state[points_key] = res.pose_landmarks[0] if res.pose_landmarks else None
            except Exception as e:
                print(f"Inference err ({frame_key}): {e}")


# ---------------------------------------------------------------------------
# WEBSOCKET SERVER
# ---------------------------------------------------------------------------

def enumerate_cameras(max_check=6):
    """Zwraca listę kamer z indeksami OpenCV i nazwą użytkową."""
    available = []
    for i in range(max_check):
        cap = cv2.VideoCapture(i, cv2.CAP_MSMF)
        if cap.isOpened():
            label = f"Kamera {i + 1}"
            available.append({
                "index": i,
                "name": label,
                "label": label,
                "deviceId": str(i)
            })
            cap.release()
    print(f"[Cameras] Dostępne: {available}", flush=True)
    return available

async def ws_handler(ws):
    print("Electron connected", flush=True)


    cameras = enumerate_cameras()
    await ws.send(json.dumps({
        "type": "cameras_list",
        "payload": cameras
    }))

    async def sender():
        while True:
            cfg = config.snapshot()
            await asyncio.sleep(1.0 / max(1, max(cfg.get("cam_fps", 1), cfg.get("cam_fps_side", 1))))

            with locks["frame"]:
                f = state["frame"]
            with locks["points"]:
                pts = state["points"]
            with locks["frame_side"]:
                f_side = state["frame_side"]
            with locks["points_side"]:
                pts_side = state["points_side"]

            front_enabled = bool(cfg.get("cam_en", False))
            side_enabled = bool(cfg.get("cam_en_side", False))

            img = draw_landmarks(f, pts) if (cfg["ar"] and f is not None and front_enabled) else (f if front_enabled else None)
            img_side = draw_landmarks(f_side, pts_side) if (cfg["ar"] and f_side is not None and side_enabled) else (f_side if side_enabled else None)

            b64_img = base64.b64encode(cv2.imencode('.jpg', img)[1]).decode('utf-8') if img is not None else None
            b64_img_side = base64.b64encode(cv2.imencode('.jpg', img_side)[1]).decode('utf-8') if img_side is not None else None
            pts_data = [{"x": p.x, "y": p.y, "z": p.z, "v": getattr(p, 'visibility', 0)} for p in pts] if pts else None
            pts_side_data = [{"x": p.x, "y": p.y, "z": p.z, "v": getattr(p, 'visibility', 0)} for p in pts_side] if pts_side else None

            try:
                await ws.send(json.dumps({
                    "image": b64_img,
                    "imageSide": b64_img_side,
                    "points": pts_data,
                    "pointsSide": pts_side_data
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
    threading.Thread(target=camera_thread_fn, args=('front',), daemon=True).start()
    threading.Thread(target=camera_thread_fn, args=('side',), daemon=True).start()
    threading.Thread(target=inference_thread_fn, daemon=True).start()
    print(f"WS Server: 127.0.0.1:{PORT}", flush=True)
    async with websockets.serve(ws_handler, "127.0.0.1", PORT):
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())