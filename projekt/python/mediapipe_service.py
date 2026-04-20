import asyncio
import websockets
import json
import cv2
import base64

async def send_camera_data(websocket):
    cap = cv2.VideoCapture(0)

    while True:
        ret, frame = cap.read()
        if not ret:
            continue

        # Encode frame to JPEG
        _, buffer = cv2.imencode('.jpg', frame)
        jpg_as_text = base64.b64encode(buffer).decode('utf-8')

        # MOCK PROCESSING
        data = {
            "status": "frame_processed",
            "dummy_metric": 123,
            "image": jpg_as_text
        }

        await websocket.send(json.dumps(data))
        await asyncio.sleep(0.1)

async def handler(websocket):
    print("Electron connected")
    await send_camera_data(websocket)

async def main():
    start_server = websockets.serve(handler, "localhost", 8765)
    await start_server
    await asyncio.Future()  # run forever

if __name__ == "__main__":
    asyncio.run(main())
