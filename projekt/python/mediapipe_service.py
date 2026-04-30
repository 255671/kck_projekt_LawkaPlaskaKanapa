import asyncio
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

async def handler(websocket):
    print("Electron connected")
    await send_camera_data(websocket)

async def start_server():
    # Use websockets.serve as a context manager or await it
    async with websockets.serve(handler, "localhost", 8765):
        await asyncio.Future()  # This keeps the server running forever

async def main():
    await asyncio.gather(start_server(), recalc_points())
    await asyncio.Future()  # run forever

if __name__ == "__main__":
    asyncio.run(main())
