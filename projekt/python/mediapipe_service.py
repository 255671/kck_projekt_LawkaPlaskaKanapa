import asyncio
import os
import sys

import websockets
import json
import cv2
import base64

import mediapipe as mp


### CONSTANTS
camera_refresh_rate = 10
points_refresh_rate = 10

mp_pose = mp.solutions.pose
mp_drawing = mp.solutions.drawing_utils

pose = mp_pose.Pose(
    model_complexity=2,
    smooth_landmarks=True,
    min_detection_confidence=0.7,
    min_tracking_confidence=0.7
)

# global cache variables
cap = None # last captured camera image
points = None # last calculated landmarks by mediapipe

async def send_camera_data(websocket):
    global cap
    cap = cv2.VideoCapture(0)

    while True:
        ret, frame = cap.read()
        if not ret:
            continue

        # Encode frame to JPEG
        _, buffer = cv2.imencode('.jpg', frame)
        jpg_as_text = base64.b64encode(buffer).decode('utf-8')

        data = {
            "image": jpg_as_text,
            "points": points
        }

        await websocket.send(json.dumps(data))
        await asyncio.sleep(1 / camera_refresh_rate)

def generate_points():
    global cap, points

    # rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    # results = pose.process(rgb)
    return

async def recalc_points():
    while True:
        generate_points()
        await asyncio.sleep(1 / points_refresh_rate)

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
    print("Electron connected")
    await send_camera_data(websocket)

async def start_server():
    port = get_port()
    print(f"[MediaPipe] Starting websocket server on 127.0.0.1:{port}")
    # Use websockets.serve as a context manager or await it
    # Bind explicitly to IPv4 localhost to avoid ::1/IPv6 binding issues on Windows.
    async with websockets.serve(handler, "127.0.0.1", port):
        await asyncio.Future()  # This keeps the server running forever

async def main():
    await asyncio.gather(start_server(), recalc_points())
    await asyncio.Future()  # run forever

if __name__ == "__main__":
    asyncio.run(main())
