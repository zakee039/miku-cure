import asyncio
import json
import websockets
import threading

class MikuWebSocketServer:
    def __init__(self, host='localhost', port=8765):
        self.host = host
        self.port = port
        self.clients = set()
        self.message_callback = None
        self.loop = None
        self.thread = None

    def start(self, message_callback):
        """
        Starts the WebSocket server in a separate background thread with its own asyncio loop.
        """
        self.message_callback = message_callback
        self.thread = threading.Thread(target=self._run_server_thread, daemon=True)
        self.thread.start()
        print(f"WebSocket: Server thread started on ws://{self.host}:{self.port}")

    def _run_server_thread(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        
        async def main():
            async with websockets.serve(self._handler, self.host, self.port):
                await asyncio.Future()  # run forever
                
        self.loop.run_until_complete(main())

    async def _handler(self, websocket):
        print(f"WebSocket: Client connected: {websocket.remote_address}")
        self.clients.add(websocket)
        try:
            async for message in websocket:
                try:
                    data = json.loads(message)
                    if self.message_callback:
                        # Invoke callback (potentially from another thread, handled carefully)
                        self.message_callback(data)
                except Exception as e:
                    print(f"WebSocket: Error parsing incoming message: {e}")
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self.clients.remove(websocket)
            print(f"WebSocket: Client disconnected: {websocket.remote_address}")

    def send_to_all(self, payload):
        """
        Thread-safe method to send JSON payload to all connected clients.
        """
        if not self.loop or not self.clients:
            return
            
        message = json.dumps(payload)
        
        async def _send_async():
            # Gather all send operations
            if self.clients:
                await asyncio.gather(*[client.send(message) for client in self.clients], return_exceptions=True)
                
        # Schedule the coroutine in the server's loop from any thread
        asyncio.run_coroutine_threadsafe(_send_async(), self.loop)

    def stop(self):
        if self.loop:
            self.loop.call_soon_threadsafe(self.loop.stop)
        if self.thread:
            self.thread.join(timeout=2.0)
        print("WebSocket: Server stopped.")

if __name__ == '__main__':
    # Test WebSocket server
    import time
    
    def on_msg(data):
        print("Received:", data)
        
    server = MikuWebSocketServer()
    server.start(on_msg)
    
    try:
        while True:
            server.send_to_all({"type": "ping"})
            time.sleep(2)
    except KeyboardInterrupt:
        server.stop()
