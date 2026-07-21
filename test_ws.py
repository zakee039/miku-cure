import asyncio
import websockets

async def main():
    async with websockets.connect('ws://127.0.0.1:13939') as ws:
        print('Connected!')
        await ws.send('{"type":"change_model", "model_type":"mock"}')
        for _ in range(5):
            print(await ws.recv())

asyncio.run(main())
