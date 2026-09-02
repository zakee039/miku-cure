import asyncio
import hmac
import json
import os
import secrets
import websockets
import threading

from ws_config import choose_port, save_port


class MikuWebSocketServer:
    AUTH_TIMEOUT_SEC = 5.0

    def __init__(self, host='127.0.0.1', port=None, auth_token=None, launch_session=None):
        # Bind IPv4 127.0.0.1. Avoid host='localhost' (IPv6 ::1) on Windows.
        # Port 8765 is often inside Hyper-V excluded ranges → WinError 10013.
        if host != '127.0.0.1':
            raise ValueError('Miku WebSocket server may only bind to 127.0.0.1')
        self.host = host
        self.port = port  # None → auto-select free port
        configured_token = auth_token or os.environ.get('MIKU_WS_TOKEN')
        if configured_token is not None and (
            not isinstance(configured_token, str) or len(configured_token) < 16
        ):
            raise ValueError('MIKU_WS_TOKEN must contain at least 16 characters')
        self.auth_token = configured_token or secrets.token_urlsafe(32)
        self.launch_session = str(
            launch_session
            if launch_session is not None
            else os.environ.get('MIKU_LAUNCH_SESSION', '')
        )
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
        if self.thread is not None and self.thread.is_alive():
            raise RuntimeError('WebSocket server is already running')
        self.message_callback = message_callback
        self.connect_callback = on_connect
        self.bind_ok = False
        self.bind_error = None
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
                    server = await websockets.serve(
                        self._handler,
                        self.host,
                        port,
                        max_size=25_000_000,
                        max_queue=4,
                        ping_interval=20,
                        ping_timeout=20,
                    )
                except OSError as e:
                    last_err = e
                    print(f"WebSocket: bind failed on {self.host}:{port} → {e}")
                    continue

                self._server = server
                self.port = port
                try:
                    path = save_port(
                        port,
                        self.host,
                        token=self.auth_token,
                        launch_session=self.launch_session,
                    )
                except OSError as e:
                    server.close()
                    await server.wait_closed()
                    self._server = None
                    self.bind_error = e
                    print(f"WebSocket: Failed to write connection metadata: {e}")
                    return
                self.bind_ok = True
                print(f"WebSocket: Listening on ws://{self.host}:{port}")
                print(f"WebSocket: Port written to {path}")
                break

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

    async def _close_unauthorized(self, websocket, reason):
        try:
            await websocket.close(code=4401, reason=reason)
        except Exception:
            pass

    async def _authenticate(self, websocket):
        try:
            raw = await asyncio.wait_for(websocket.recv(), timeout=self.AUTH_TIMEOUT_SEC)
        except (asyncio.TimeoutError, websockets.exceptions.ConnectionClosed):
            await self._close_unauthorized(websocket, 'authentication required')
            return False

        if not isinstance(raw, str) or len(raw) > 4096:
            await self._close_unauthorized(websocket, 'invalid authentication frame')
            return False
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            await self._close_unauthorized(websocket, 'invalid authentication frame')
            return False

        msg_type = data.get('type') if isinstance(data, dict) else None
        supplied = data.get('token', '') if isinstance(data, dict) else ''
        if (
            msg_type not in ('authenticate', 'auth')
            or not isinstance(supplied, str)
            or not hmac.compare_digest(supplied, self.auth_token)
        ):
            await self._close_unauthorized(websocket, 'authentication failed')
            return False

        await websocket.send(json.dumps({'type': 'authenticated', 'ok': True}))
        return True

    async def _handler(self, websocket, path=None):
        remote = getattr(websocket, 'remote_address', None)
        if not await self._authenticate(websocket):
            print(f"WebSocket: Rejected unauthenticated client: {remote}")
            return

        print(f"WebSocket: Authenticated client connected: {remote}")
        self.clients.add(websocket)
        try:
            try:
                await websocket.send(json.dumps({
                    "type": "backend_ready",
                    "version": "1.2.3",
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
                    if not isinstance(data, dict):
                        raise ValueError('message must be a JSON object')
                    if self.message_callback:
                        self.message_callback(data)
                except Exception as e:
                    print(f"WebSocket: Error parsing incoming message: {e}")
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self.clients.discard(websocket)
            print(f"WebSocket: Client disconnected: {remote}")

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

    def stop(self, timeout=3.0):
        if self.loop and self._stop_event is not None:
            def _request_stop():
                if self._stop_event and not self._stop_event.is_set():
                    self._stop_event.set()
            try:
                self.loop.call_soon_threadsafe(_request_stop)
            except Exception:
                pass
        if self.thread:
            self.thread.join(timeout=max(0.0, float(timeout)))
            if not self.thread.is_alive():
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
