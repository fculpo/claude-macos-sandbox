#!/usr/bin/env python3
"""Electron executable wrapper that delegates GUI startup to the sandbox helper."""

import json
import os
import signal
import socket
import struct
import sys
from pathlib import Path
from typing import Optional


MAX_FRAME = 32 * 1024 * 1024


def _write_frame(sock: socket.socket, payload: dict) -> None:
    data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    sock.sendall(struct.pack("!I", len(data)) + data)


def _read_frame(sock: socket.socket) -> Optional[dict]:
    header = sock.recv(4)
    if not header:
        return None
    while len(header) < 4:
        chunk = sock.recv(4 - len(header))
        if not chunk:
            return None
        header += chunk
    size = struct.unpack("!I", header)[0]
    if size > MAX_FRAME:
        raise ValueError(f"frame too large: {size}")
    data = b""
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            return None
        data += chunk
    return json.loads(data.decode("utf-8"))


def _find_real_electron() -> Optional[str]:
    suffix = Path("node_modules/electron/dist/Electron.app/Contents/MacOS/Electron")
    cwd = Path.cwd().resolve()
    candidates = [cwd, *cwd.parents]
    for base in candidates:
        candidate = base / suffix
        if candidate.exists() and candidate.resolve() != Path(__file__).resolve():
            return str(candidate)
    return None


def _send_signal(sock: socket.socket, sig: int) -> None:
    try:
        _write_frame(sock, {"type": "signal", "signal": sig})
    except OSError:
        pass


def main() -> int:
    endpoint = os.environ.get("CLAUDE_SANDBOX_GUI_HELPER")
    command = os.environ.get("CLAUDE_SANDBOX_GUI_ELECTRON_REAL") or _find_real_electron()
    if not endpoint or not command:
        print("electron GUI wrapper is not configured", file=sys.stderr)
        return 127
    host, raw_port = endpoint.rsplit(":", 1)
    with socket.create_connection((host, int(raw_port)), timeout=10) as sock:
        sock.settimeout(None)
        signal.signal(signal.SIGINT, lambda _sig, _frame: _send_signal(sock, signal.SIGINT))
        signal.signal(signal.SIGTERM, lambda _sig, _frame: _send_signal(sock, signal.SIGTERM))
        _write_frame(sock, {
            "type": "spawn",
            "command": command,
            "args": sys.argv[1:],
            "cwd": os.getcwd(),
            "env": dict(os.environ),
        })
        while True:
            frame = _read_frame(sock)
            if frame is None:
                return 1
            kind = frame.get("type")
            if kind == "stdout":
                sys.stdout.write(frame.get("data", ""))
                sys.stdout.flush()
            elif kind == "stderr":
                sys.stderr.write(frame.get("data", ""))
                sys.stderr.flush()
            elif kind == "exit":
                return int(frame.get("code", 1))


if __name__ == "__main__":
    sys.exit(main())
