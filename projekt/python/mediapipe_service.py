import asyncio
import os
import sys
import threading
import logging

import websockets
import json
import cv2
import base64

import mediapipe as mp

# Suppress noisy "opening handshake failed" logs caused by Electron's
# waitForPort() probing the TCP port before the WebSocket client connects.
logging.getLogger("websockets").setLevel(logging.CRITICAL)


### CONSTANTS
DEFAULT_MODEL_PATH = "pose_landmarker_full.task"

# New Tasks API aliases
BaseOptions           = mp.tasks.BaseOptions
PoseLandmarker        = mp.tasks.vision.PoseLandmarker
PoseLandmarkerOptions = mp.tasks.vision.PoseLandmarkerOptions
VisionRunningMode     = mp.tasks.vision.RunningMode

# Skeleton connections for the 33-landmark pose model
POSE_CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 7),
    (0, 4), (4, 5), (5, 6), (6, 8),
    (9, 10),
    (11, 12),
    (11, 13), (13, 15), (15, 17), (15, 19), (15, 21), (17, 19),
    (12, 14), (14, 16), (16, 18), (16, 20), (16, 22), (18, 20),
    (11, 23), (12, 24), (23, 24),
    (23, 25), (25, 27), (27, 29), (27, 31), (29, 31),
    (24, 26), (26, 28), (28, 30), (28, 32), (30, 32),
]


# ---------------------------------------------------------------------------
# Live config — updated by handle_config(), read by camera/inference threads
# ---------------------------------------------------------------------------

class Config:
    def __init__(self):
        self._lock = threading.Lock()
        # camera
        self.camera_index   = 0
        self.camera_enabled = True
        self.camera_fps     = 10
        self.ar_overlay     = True
        self.width          = 1280
        self.height         = 720
        # inference
        self.points_fps     = 10
        # exercise
        self.exercise_name       = None
        self.exercise_difficulty = None
        self.exercise_duration   = None
        self.exercise_reps       = None
        # calibration
        self.auto_calibrate = True
        # signals
        self.camera_restart_requested = False

    def apply(self, payload: dict):
        cameras     = payload.get("cameras", {})
        front       = cameras.get("front", {})
        exercise    = payload.get("exercise", {})
        calibration = payload.get("calibration", {})

        with self._lock:
            # --- camera ---
            if "enabled" in front:
                self.camera_enabled = bool(front["enabled"])

            if "ar_overlay" in front:
                self.ar_overlay = bool(front["ar_overlay"])

            if "fps" in front:
                fps = int(front["fps"])
                if fps != self.camera_fps:
                    self.camera_fps = fps
                    self.points_fps = fps

            if "resolution" in front:
                try:
                    w, h = front["resolution"].split("x")
                    new_w, new_h = int(w), int(h)
                    if new_w != self.width or new_h != self.height:
                        self.width  = new_w
                        self.height = new_h
                        self.camera_restart_requested = True
                except (ValueError, AttributeError):
                    pass

            if front.get("deviceId"):
                try:
                    new_index = int(front["deviceId"])
                    if new_index != self.camera_index:
                        self.camera_index = new_index
                        self.camera_restart_requested = True
                except (ValueError, TypeError):
                    pass  # browser hash deviceId — cannot map to OpenCV index

            # --- exercise ---
            if "name" in exercise:
                self.exercise_name = exercise["name"]
            if "difficulty" in exercise:
                self.exercise_difficulty = exercise["difficulty"]
            if "duration" in exercise:
                self.exercise_duration = int(exercise["duration"])
            if "repetitions" in exercise:
                self.exercise_reps = int(exercise["repetitions"])

            # --- calibration ---
            if "auto_calibrate" in calibration:
                self.auto_calibrate = bool(calibration["auto_calibrate"])

        print(
            f"Config updated — "
            f"cam={self.camera_index} enabled={self.camera_enabled} "
            f"res={self.width}x{self.height} fps={self.camera_fps} "
            f"ar_overlay={self.ar_overlay} | "
            f"exercise={self.exercise_name} difficulty={self.exercise_difficulty} "
            f"reps={self.exercise_reps} duration={self.exercise_duration}s | "
            f"auto_calibrate={self.auto_calibrate}",
            flush=True,
        )

    def snapshot(self):
        with self._lock:
            return {
                "camera_index":   self.camera_index,
                "camera_enabled": self.camera_enabled,
                "camera_fps":     self.camera_fps,
                "ar_overlay":     self.ar_overlay,
                "width":          self.width,
                "height":         self.height,
                "points_fps":     self.points_fps,
                "exercise_name":       self.exercise_name,
                "exercise_difficulty": self.exercise_difficulty,
                "exercise_duration":   self.exercise_duration,
                "exercise_reps":       self.exercise_reps,
                "auto_calibrate":      self.auto_calibrate,
                "camera_restart_requested": self.camera_restart_requested,
            }

    def clear_restart(self):
        with self._lock:
            self.camera_restart_requested = False


config = Config()


# ---------------------------------------------------------------------------
# Shared state (written by background threads, read by async tasks)
# ---------------------------------------------------------------------------

latest_frame = None
points       = None
_frame_lock  = threading.Lock()
_points_lock = threading.Lock()
_frame_ts_ms = 0


# ---------------------------------------------------------------------------
# MediaPipe landmarker
# ---------------------------------------------------------------------------

def get_model_path() -> str:
    for i, arg in enumerate(sys.argv):
        if arg in ('--model', '-m') and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    env = os.getenv('MEDIAPIPE_MODEL_PATH')
    if env:
        return env
    return DEFAULT_MODEL_PATH


_landmarker = None

def get_landmarker():
    global _landmarker
    if _landmarker is None:
        model_path = get_model_path()
        if not os.path.exists(model_path):
            raise FileNotFoundError(
                f"MediaPipe model not found at '{model_path}'.\n"
                "Download it with:\n"
                "  wget -O pose_landmarker_full.task "
                "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
                "pose_landmarker_full/float16/latest/pose_landmarker_full.task"
            )
        options = PoseLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=model_path),
            running_mode=VisionRunningMode.VIDEO,
            num_poses=1,
            min_pose_detection_confidence=0.5,
            min_pose_presence_confidence=0.5,
            min_tracking_confidence=0.5,
        )
        _landmarker = PoseLandmarker.create_from_options(options)
    return _landmarker


# ---------------------------------------------------------------------------
# Drawing — pure OpenCV
# ---------------------------------------------------------------------------

def draw_landmarks_on_frame(frame, current_points):
    if not current_points:
        return frame

    annotated = frame.copy()
    h, w = annotated.shape[:2]
    pts = [(int(lm.x * w), int(lm.y * h)) for lm in current_points]

    for start_idx, end_idx in POSE_CONNECTIONS:
        if start_idx < len(pts) and end_idx < len(pts):
            cv2.line(annotated, pts[start_idx], pts[end_idx],
                     color=(255, 0, 0), thickness=2, lineType=cv2.LINE_AA)

    for x, y in pts:
        cv2.circle(annotated, (x, y), radius=4,
                   color=(0, 255, 0), thickness=-1, lineType=cv2.LINE_AA)

    return annotated


# ---------------------------------------------------------------------------
# Background thread: camera capture
# ---------------------------------------------------------------------------

def camera_thread_fn():
    global latest_frame

    cap = None

    while True:
        cfg = config.snapshot()

        # Open camera on first start or when a restart was explicitly requested
        if cap is None or cfg["camera_restart_requested"]:
            if cap is not None:
                cap.release()
            idx = cfg["camera_index"]
            cap = cv2.VideoCapture(idx)
            if not cap.isOpened():
                print(f"ERROR: could not open camera {idx}", flush=True)
                cap = None
                threading.Event().wait(2.0)
                continue
            cap.set(cv2.CAP_PROP_FRAME_WIDTH,  cfg["width"])
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, cfg["height"])
            cap.set(cv2.CAP_PROP_FPS,          cfg["camera_fps"])
            config.clear_restart()
            print(f"Camera {idx} opened ({cfg['width']}x{cfg['height']} @ {cfg['camera_fps']}fps)", flush=True)

        ret, frame = cap.read()
        if not ret:
            continue
        with _frame_lock:
            latest_frame = frame


# ---------------------------------------------------------------------------
# Background thread: MediaPipe inference
# ---------------------------------------------------------------------------

def inference_thread_fn():
    global points, _frame_ts_ms

    try:
        get_landmarker()
    except FileNotFoundError as e:
        print(str(e), flush=True)
        return

    while True:
        cfg = config.snapshot()
        interval = 1.0 / cfg["points_fps"]
        threading.Event().wait(interval)

        with _frame_lock:
            frame = latest_frame
        if frame is None:
            continue

        frame = frame.copy()
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        _frame_ts_ms += int(1000 / cfg["points_fps"])

        try:
            result = get_landmarker().detect_for_video(mp_image, _frame_ts_ms)
            with _points_lock:
                if result.pose_landmarks:
                    points = result.pose_landmarks[0]
        except Exception as e:
            print(f"Inference error: {e}", flush=True)


# ---------------------------------------------------------------------------
# Async: receive config messages from Electron
# ---------------------------------------------------------------------------

async def receive_config(websocket):
    async for raw in websocket:
        try:
            msg = json.loads(raw)
            if msg.get("type") == "config":
                config.apply(msg.get("payload", {}))
                try:
                    await websocket.send(json.dumps({"type": "config_ack", "status": "success"}))
                except websockets.exceptions.ConnectionClosed:
                    break
        except Exception as e:
            print(f"Config parse error: {e}", flush=True)


# ---------------------------------------------------------------------------
# Async sender: streams annotated frames to Electron
# ---------------------------------------------------------------------------

async def send_camera_data(websocket):
    while True:
        cfg = config.snapshot()
        await asyncio.sleep(1.0 / cfg["camera_fps"])

        # If camera is disabled, send a signal with no image so Electron can blank the view
        if not cfg["camera_enabled"]:
            try:
                await websocket.send(json.dumps({"image": None, "points": None}))
            except websockets.exceptions.ConnectionClosed:
                print("Client disconnected", flush=True)
                break
            continue

        with _frame_lock:
            frame = latest_frame
        if frame is None:
            continue

        with _points_lock:
            current_points = points

        if cfg["ar_overlay"]:
            annotated = draw_landmarks_on_frame(frame, current_points)
        else:
            annotated = frame

        _, buffer = cv2.imencode('.jpg', annotated)
        jpg_as_text = base64.b64encode(buffer).decode('utf-8')

        landmark_list = None
        if current_points:
            landmark_list = [
                {"x": lm.x, "y": lm.y, "z": lm.z, "visibility": lm.visibility}
                for lm in current_points
            ]

        data = {"image": jpg_as_text, "points": landmark_list}
        try:
            await websocket.send(json.dumps(data))
        except websockets.exceptions.ConnectionClosed:
            print("Client disconnected", flush=True)
            break


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

def get_port() -> int:
    default_port = 8765
    for i, arg in enumerate(sys.argv):
        if arg in ('--port', '-p') and i + 1 < len(sys.argv):
            try:
                return int(sys.argv[i + 1])
            except ValueError:
                break
    env_port = os.getenv('MEDIAPIPE_WS_PORT')
    if env_port:
        try:
            return int(env_port)
        except ValueError:
            pass
    return default_port


async def handler(websocket):
    print("Electron connected", flush=True)
    # Run sender and config receiver concurrently on the same connection
    await asyncio.gather(
        send_camera_data(websocket),
        receive_config(websocket),
    )


async def start_server():
    port = get_port()
    print(f"Starting websocket server on 127.0.0.1:{port}", flush=True)
    async with websockets.serve(handler, "127.0.0.1", port):
        await asyncio.Future()


async def main():
    threading.Thread(target=camera_thread_fn,    daemon=True).start()
    threading.Thread(target=inference_thread_fn, daemon=True).start()
    await start_server()


if __name__ == "__main__":
    asyncio.run(main())