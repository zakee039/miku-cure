"""Shared WebSocket port selection.

Default preferred port: 13939 (not 8000/8080/8765).
If busy or reserved by Windows, probe fallbacks then ephemeral.

Strategy:
  1. Prefer MIKU_WS_PORT env if set
  2. Prefer 13939
  3. Probe candidate ports on 127.0.0.1
  4. Persist chosen port to user/ws_port.json for the Electron frontend
"""
from __future__ import annotations

import json
import hashlib
import hmac
import os
import socket
import tempfile
import time

# Preferred + fallbacks (avoid Hyper-V reserved 8xxx ranges like 8702-8801)
PREFERRED_PORT = 13939
DEFAULT_CANDIDATES = (
    PREFERRED_PORT,
    13940,
    13941,
    14492,
    18765,
    18766,
    27654,
    37654,
    9876,
)


def _user_dir() -> str:
    return os.environ.get('MIKU_USER_DIR') or os.path.join(
        os.path.dirname(__file__), '..', 'user'
    )


def port_file_path() -> str:
    return os.path.join(_user_dir(), 'ws_port.json')


def is_port_free(host: str, port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def choose_port(host: str = '127.0.0.1') -> int:
    env = os.environ.get('MIKU_WS_PORT')
    if env:
        try:
            p = int(env)
            if is_port_free(host, p):
                return p
            print(f"WS: MIKU_WS_PORT={p} is not free, probing candidates...")
        except ValueError:
            pass

    for port in DEFAULT_CANDIDATES:
        if is_port_free(host, port):
            return port

    # Last resort: ephemeral bind
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind((host, 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _signature_payload(host: str, port: int, ts: int, launch_session: str) -> str:
    return f"{host}:{int(port)}:{int(ts)}:{launch_session}"


def sign_port_data(
    token: str,
    host: str,
    port: int,
    ts: int,
    launch_session: str,
) -> str:
    """Sign connection metadata shared with the launcher/Electron process."""
    return hmac.new(
        token.encode('utf-8'),
        _signature_payload(host, port, ts, launch_session).encode('utf-8'),
        hashlib.sha256,
    ).hexdigest()


def verify_port_data(data: dict, token: str, max_age_ms: int | None = None) -> bool:
    try:
        host = str(data['host'])
        port = int(data['port'])
        ts = int(data['ts'])
        launch_session = str(data['launch_session'])
        signature = str(data['signature'])
    except (KeyError, TypeError, ValueError):
        return False
    if host != '127.0.0.1' or not (1 <= port <= 65535) or not token:
        return False
    if max_age_ms is not None and abs(int(time.time() * 1000) - ts) > max_age_ms:
        return False
    expected = sign_port_data(token, host, port, ts, launch_session)
    return hmac.compare_digest(signature, expected)


def sign_shutdown_command(token: str, launch_session: str, ts: int) -> str:
    return hmac.new(
        token.encode('utf-8'),
        f"shutdown:{launch_session}:{int(ts)}".encode('utf-8'),
        hashlib.sha256,
    ).hexdigest()


def sign_launcher_heartbeat(token: str, launch_session: str, ts: int) -> str:
    """Sign a launcher liveness proof for one launch session."""
    return hmac.new(
        token.encode('utf-8'),
        f"heartbeat:{launch_session}:{int(ts)}".encode('utf-8'),
        hashlib.sha256,
    ).hexdigest()


def verify_launcher_heartbeat(
    data: dict,
    token: str,
    launch_session: str,
    *,
    max_age_ms: int = 6_000,
    now_ms: int | None = None,
) -> int | None:
    """Return the signed heartbeat timestamp, or None when invalid."""
    try:
        if data.get('action') != 'heartbeat':
            return None
        supplied_session = str(data['launch_session'])
        ts = int(data['ts'])
        signature = str(data['signature'])
    except (AttributeError, KeyError, TypeError, ValueError):
        return None
    if not token or not launch_session or supplied_session != launch_session:
        return None
    current_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    if ts <= 0 or ts > current_ms or current_ms - ts > max_age_ms:
        return None
    expected = sign_launcher_heartbeat(token, launch_session, ts)
    if not hmac.compare_digest(signature, expected):
        return None
    return ts


def verify_shutdown_command(
    data: dict,
    token: str,
    launch_session: str,
    max_age_ms: int = 30_000,
) -> bool:
    try:
        if data.get('action') != 'shutdown':
            return False
        command_session = str(data['launch_session'])
        ts = int(data['ts'])
        signature = str(data['signature'])
    except (AttributeError, KeyError, TypeError, ValueError):
        return False
    if not token or not launch_session or command_session != launch_session:
        return False
    if abs(int(time.time() * 1000) - ts) > max_age_ms:
        return False
    expected = sign_shutdown_command(token, launch_session, ts)
    return hmac.compare_digest(signature, expected)


def save_port(
    port: int,
    host: str = '127.0.0.1',
    *,
    token: str,
    launch_session: str = '',
) -> str:
    if host != '127.0.0.1':
        raise ValueError('WebSocket host must be the IPv4 loopback address')
    if not token:
        raise ValueError('A non-empty WebSocket authentication token is required')
    path = port_file_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    ts = int(time.time() * 1000)
    data = {
        'host': host,
        'port': int(port),
        'ts': ts,
        'launch_session': launch_session,
        'signature': sign_port_data(token, host, port, ts, launch_session),
    }

    # Replace atomically so readers never observe a partially-written JSON file.
    fd, tmp_path = tempfile.mkstemp(
        prefix='.ws_port-', suffix='.tmp', dir=os.path.dirname(path), text=True
    )
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=True, separators=(',', ':'))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    finally:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
    return path


def load_port() -> dict | None:
    path = port_file_path()
    if not os.path.exists(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None
