import asyncio
import json
import websockets
import threading

from ws_config import choose_port, save_port


class MikuWebSocketServer:
    def __init__(self, host='127.0.0.1', port=None):
        # Bind IPv4 127.0.0.1. Avoid host='localhost' (IPv6 ::1) on Windows.
        # Port 8765 is often inside Hyper-V excluded ranges → WinError 10013.
        self.host = host
        self.port = port  # None → auto-select free port
        self.clients = set()
        self.message_callback = None
        self.connect_callback = None
        self.loop = None
        self.thread = None
        self._server = None
        self._stop_event = None
        self.bind_ok = False
        self.bind_error = None

    def start(self, message_callback, on_connect=None):
        """
        Starts the WebSocket server in a separate background thread with its own asyncio loop.
        """
        self.message_callback = message_callback
        self.connect_callback = on_connect
        if self.port is None:
            self.port = choose_port(self.host)
        self.thread = threading.Thread(target=self._run_server_thread, daemon=True)
        self.thread.start()
        print(f"WebSocket: Server thread starting on ws://{self.host}:{self.port}")

    def _run_server_thread(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self._stop_event = asyncio.Event()

        async def main():
            # Re-probe if the chosen port races with another process
            ports = [self.port]
            for p in (13939, 13940, 13941, 14492, 18765, 18766, 27654, 9876):
                if p not in ports:
                    ports.append(p)

            last_err = None
            for port in ports:
                try:
                    self._server = await websockets.serve(
                        self._handler, self.host, port, max_size=50_000_000,
                    )
                    self.port = port
                    self.bind_ok = True
                    path = save_port(port, self.host)
                    print(f"WebSocket: Listening on ws://{self.host}:{port}")
                    print(f"WebSocket: Port written to {path}")
                    break
                except OSError as e:
                    last_err = e
                    print(f"WebSocket: bind failed on {self.host}:{port} → {e}")

            if not self.bind_ok:
                self.bind_error = last_err
                print(f"WebSocket: FATAL — no free port available: {last_err}")
                return

            await self._stop_event.wait()
            self._server.close()
            await self._server.wait_closed()

        try:
            self.loop.run_until_complete(main())
        except Exception as e:
            self.bind_error = e
            print(f"WebSocket: server loop ended: {e}")
        finally:
            try:
                if not self.loop.is_closed():
                    pending = asyncio.all_tasks(self.loop)
                    for t in pending:
                        t.cancel()
                    self.loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                    self.loop.close()
            except Exception:
                pass

    async def _handler(self, websocket):
        print(f"WebSocket: Client connected: {websocket.remote_address}")
        self.clients.add(websocket)
        try:
            try:
                await websocket.send(json.dumps({
                    "type": "backend_ready",
                    "version": "1.1.2",
                }))
            except Exception:
                pass
            if self.connect_callback:
                try:
                    self.connect_callback()
                except Exception as e:
                    print(f"WebSocket: on_connect error: {e}")

            async for message in websocket:
                try:
                    data = json.loads(message)
                    if self.message_callback:
                        self.message_callback(data)
                except Exception as e:
                    print(f"WebSocket: Error parsing incoming message: {e}")
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self.clients.discard(websocket)
            print(f"WebSocket: Client disconnected: {websocket.remote_address}")

    def send_to_all(self, payload):
        """
        Thread-safe method to send JSON payload to all connected clients.
        """
        if not self.loop or not self.clients:
            return

        message = json.dumps(payload)

        async def _send_async():
            dead = []
            for client in list(self.clients):
                try:
                    await client.send(message)
                except Exception:
                    dead.append(client)
            for c in dead:
                self.clients.discard(c)

        try:
            asyncio.run_coroutine_threadsafe(_send_async(), self.loop)
        except Exception as e:
            print(f"WebSocket: send_to_all failed: {e}")

    def stop(self):
        if self.loop and self._stop_event is not None:
            def _request_stop():
                if self._stop_event and not self._stop_event.is_set():
                    self._stop_event.set()
            try:
                self.loop.call_soon_threadsafe(_request_stop)
            except Exception:
                pass
        if self.thread:
            self.thread.join(timeout=3.0)
            self.thread = None
        self.clients.clear()
        print("WebSocket: Server stopped.")


if __name__ == '__main__':
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
