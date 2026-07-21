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
import os
import socket

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


def save_port(port: int, host: str = '127.0.0.1') -> str:
    path = port_file_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = {'host': host, 'port': port, 'preferred': PREFERRED_PORT}
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f)
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
