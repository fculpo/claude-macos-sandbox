#!/usr/bin/env python3
"""Out-of-sandbox subprocess helper for macOS GUI applications."""

import argparse
import json
import os
import select
import signal
import socket
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional


MAX_FRAME = 32 * 1024 * 1024


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


def _write_frame(sock: socket.socket, payload: dict) -> None:
    data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    sock.sendall(struct.pack("!I", len(data)) + data)


def _is_allowed_electron(path: str) -> bool:
    real = os.path.realpath(path)
    suffix = "/node_modules/electron/dist/Electron.app/Contents/MacOS/Electron"
    return real.endswith(suffix) and real.startswith(str(Path.home()))


def _stream_output(sock: socket.socket, stream, name: str) -> None:
    fd = stream.fileno()
    while True:
        chunk = os.read(fd, 65536)
        if not chunk:
            return
        try:
            _write_frame(sock, {"type": name, "data": chunk.decode("latin1")})
        except OSError:
            return


def _watch_client(sock: socket.socket, proc: subprocess.Popen) -> None:
    try:
        while proc.poll() is None:
            ready, _, _ = select.select([sock], [], [], 0.25)
            if not ready:
                continue
            message = _read_frame(sock)
            if message is None:
                proc.terminate()
                return
            if message.get("type") == "signal":
                sig = int(message.get("signal", signal.SIGTERM))
                proc.send_signal(sig)
    except OSError:
        if proc.poll() is None:
            proc.terminate()


def _handle_client(sock: socket.socket) -> None:
    with sock:
        request = _read_frame(sock)
        if not request or request.get("type") != "spawn":
            _write_frame(sock, {"type": "exit", "code": 64})
            return
        command = request.get("command")
        if not isinstance(command, str) or not _is_allowed_electron(command):
            _write_frame(sock, {"type": "stderr", "data": "electron GUI helper rejected command\n"})
            _write_frame(sock, {"type": "exit", "code": 126})
            return
        args = request.get("args")
        cwd = request.get("cwd")
        env = request.get("env")
        if not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
            _write_frame(sock, {"type": "exit", "code": 64})
            return
        if not isinstance(cwd, str) or not isinstance(env, dict):
            _write_frame(sock, {"type": "exit", "code": 64})
            return
        proc = subprocess.Popen(
            [command, *args],
            cwd=cwd,
            env={str(k): str(v) for k, v in env.items()},
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        threads = [
            threading.Thread(target=_stream_output, args=(sock, proc.stdout, "stdout"), daemon=True),
            threading.Thread(target=_stream_output, args=(sock, proc.stderr, "stderr"), daemon=True),
            threading.Thread(target=_watch_client, args=(sock, proc), daemon=True),
        ]
        for thread in threads:
            thread.start()
        code = proc.wait()
        for thread in threads[:2]:
            thread.join(timeout=1)
        try:
            _write_frame(sock, {"type": "exit", "code": code})
        except OSError:
            pass


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _lifecycle_alive(lifecycle_fd: Optional[int], parent_pid: Optional[int]) -> bool:
    if lifecycle_fd is not None:
        try:
            ready, _, _ = select.select([lifecycle_fd], [], [], 0)
        except OSError:
            return False
        if not ready:
            return True
        try:
            return os.read(lifecycle_fd, 1) != b""
        except OSError:
            return False
    if parent_pid is not None:
        return _pid_exists(parent_pid)
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--parent-pid", type=int, default=None)
    parser.add_argument("--lifecycle-fd", type=int, default=None)
    args = parser.parse_args()
    if args.lifecycle_fd is None and args.parent_pid is None:
        parser.error("--lifecycle-fd or --parent-pid is required")

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", args.port))
        server.listen()
        server.settimeout(1)
        while _lifecycle_alive(args.lifecycle_fd, args.parent_pid):
            try:
                client, _ = server.accept()
            except TimeoutError:
                continue
            threading.Thread(target=_handle_client, args=(client,), daemon=True).start()
            time.sleep(0.01)
    return 0


if __name__ == "__main__":
    sys.exit(main())
