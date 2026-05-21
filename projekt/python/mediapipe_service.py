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
state = {"frame": None, "points": None, "ts_ms": 0}
locks = {"frame": threading.Lock(), "points": threading.Lock()}


class Config:
    def __init__(self):
        self.lock = threading.Lock()
        self.cam_idx, self.cam_en, self.cam_fps, self.ar = 0, False, 10, True
        self.w, self.h, self.pts_fps = 1280, 720, 10
        self.restart = False

    def apply(self, p: dict):
        cameras = p.get("cameras", {})
        f = cameras.get("front", {})
        with self.lock:
            self.cam_en = bool(cameras.get("enabled", self.cam_en))
            self.ar = bool(cameras.get("ar_overlay", self.ar))
            if "fps" in f:
                self.cam_fps = self.pts_fps = int(f["fps"])
            try:
                if "resolution" in f:
                    nw, nh = map(int, f["resolution"].split("x"))
                    if (nw, nh) != (self.w, self.h):
                        self.w, self.h, self.restart = nw, nh, True

                if "deviceId" in f:
                    device_id = f["deviceId"]
                    if isinstance(device_id, int):
                        new_idx = device_id
                    elif isinstance(device_id, str) and device_id.isdigit():
                        new_idx = int(device_id)
                    else:
                        new_idx = None

                    if new_idx is not None and new_idx != self.cam_idx:
                        self.cam_idx, self.restart = new_idx, True
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
    cap = None
    while True:
        cfg = config.snapshot()
        if cap is None or cfg["restart"]:
            if cap: cap.release(); time.sleep(0.3)
            cap = cv2.VideoCapture(cfg["cam_idx"], cv2.CAP_MSMF)
            if not cap.isOpened(): cap = None; time.sleep(2.0); continue
            with config.lock:
                config.restart = False
            print(f"Kamera {cfg['cam_idx']} start -> Cel: {cfg['w']}x{cfg['h']}", flush=True)

        ret, frame = cap.read()
        if not ret: time.sleep(0.01); continue

        if frame.shape[:2] != (cfg["h"], cfg["w"]):
            frame = cv2.resize(frame, (cfg["w"], cfg["h"]), interpolation=cv2.INTER_LINEAR)

        with locks["frame"]:
            state["frame"] = frame


def inference_thread_fn():
    try:
        lm = get_landmarker()
    except Exception as e:
        print(e); return

    while True:
        cfg = config.snapshot()
        time.sleep(1.0 / max(1, cfg["pts_fps"]))

        with locks["frame"]:
            f = state["frame"]
        if f is None: continue

        mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(f.copy(), cv2.COLOR_BGR2RGB))
        state["ts_ms"] += int(1000 / max(1, cfg["pts_fps"]))

        try:
            res = lm.detect_for_video(mp_img, state["ts_ms"])
            with locks["points"]:
                state["points"] = res.pose_landmarks[0] if res.pose_landmarks else None
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
            await asyncio.sleep(1.0 / max(1, cfg["cam_fps"]))
            if not cfg["cam_en"]:
                try:
                    await ws.send(json.dumps({"image": None, "points": None})); continue
                except:
                    break

            with locks["frame"]:
                f = state["frame"]
            with locks["points"]:
                pts = state["points"]
            if f is None: continue

            img = draw_landmarks(f, pts) if cfg["ar"] else f
            b64_img = base64.b64encode(cv2.imencode('.jpg', img)[1]).decode('utf-8')
            pts_data = [{"x": p.x, "y": p.y, "z": p.z, "v": getattr(p, 'visibility', 0)} for p in pts] if pts else None

            try:
                await ws.send(json.dumps({"image": b64_img, "points": pts_data}))
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