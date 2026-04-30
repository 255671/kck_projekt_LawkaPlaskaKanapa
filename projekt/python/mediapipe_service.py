import asyncio
import websockets
import json
import cv2
import base64


### CONSTANTS
camera_refresh_rate = 10
points_refresh_rate = 10


# global cache variables
frame = None # last captured camera image
points = None # last calculated landmarks by mediapipe

async def send_camera_data(websocket):
    global frame
    frame = cv2.VideoCapture(0)

    while True:
        ret, frame = frame.read()
        if not ret:
            continue

        # Encode frame to JPEG
        _, buffer = cv2.imencode('.jpg', frame)
        jpg_as_text = base64.b64encode(buffer).decode('utf-8')

        data = {
            "image": jpg_as_text
        }

        await websocket.send(json.dumps(data))
        await asyncio.sleep(1 / camera_refresh_rate)


async def handler(websocket):
    print("Electron connected")
    await send_camera_data(websocket)

async def main():
    start_server = websockets.serve(handler, "localhost", 8765)
    await start_server
    await asyncio.Future()  # run forever

if __name__ == "__main__":
    asyncio.run(main())
