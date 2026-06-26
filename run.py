"""Boot the bKash QueueStorm Investigator service.

Smart-launch helper that:

  1. Loads the cached settings (so env vars + .env are honoured).
  2. Tries the configured port. If it's busy (WinError 10013 / EADDRINUSE),
     increments to the next free port when `server_auto_port=True`.
  3. Starts uvicorn with sensible defaults for local development.

Usage:

    python run.py

Or override via environment:

    SERVER_PORT=9000 SERVER_HOST=0.0.0.0 python run.py
"""
from __future__ import annotations

import socket
import sys

import uvicorn

from app.config import get_settings


def _is_port_free(host: str, port: int) -> bool:
    """Return True if we can bind (host, port) without conflict.

    On Windows, attempting `socket.bind` on a busy port raises
    PermissionError (WinError 10013) — different from POSIX EADDRINUSE.
    We treat ANY bind failure as "not free" so we walk forward safely.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except (OSError, PermissionError):
            return False
    return True


def _pick_port(host: str, preferred: int, auto: bool) -> int:
    """Pick a usable port.

    If `preferred` is free, return it. Otherwise, when `auto=True`,
    walk forward (preferred+1, preferred+2, ...) up to 50 attempts
    until one binds or we give up. When `auto=False`, raise.
    """
    if _is_port_free(host, preferred):
        return preferred
    if not auto:
        raise RuntimeError(
            f"port {preferred} on {host} is already in use. "
            "Set SERVER_PORT or pass --port."
        )
    for delta in range(1, 51):
        candidate = preferred + delta
        if candidate > 65535:
            break
        if _is_port_free(host, candidate):
            print(
                f"[run.py] port {preferred} busy on {host}; "
                f"falling back to {candidate}",
                file=sys.stderr,
            )
            return candidate
    raise RuntimeError(
        f"no free port found in range {preferred}-{preferred + 50} on {host}"
    )


def main() -> None:
    settings = get_settings()
    port = _pick_port(
        settings.server_host,
        settings.server_port,
        settings.server_auto_port,
    )
    print(
        f"[run.py] starting bKash QueueStorm Investigator "
        f"on http://{settings.server_host}:{port}",
        file=sys.stderr,
    )
    uvicorn.run(
        "app.main:app",
        host=settings.server_host,
        port=port,
        log_level=settings.log_level.lower(),
        reload=False,
    )


if __name__ == "__main__":
    main()