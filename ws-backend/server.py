import asyncio
import websockets
from datetime import datetime


async def handler(websocket):
    await websocket.send(f"Server time: {datetime.now().isoformat()}")
    async for message in websocket:
        reply = f"Echo: {message}"
        print(f"[{datetime.now().isoformat()}] {message} -> {reply}")
        await websocket.send(reply)


async def main():
    async with websockets.serve(handler, "0.0.0.0", 8765):
        print("WebSocket server running on ws://0.0.0.0:8765")
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
