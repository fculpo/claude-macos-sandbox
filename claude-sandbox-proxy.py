#!/usr/bin/env python3
"""HTTPS CONNECT proxy with domain whitelisting for claude-sandbox."""

import json
import select
import socket
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn


def load_allowed_domains(path):
    with open(path) as f:
        return set(json.load(f))


ALLOWED = set()


class ConnectProxy(BaseHTTPRequestHandler):
    def do_CONNECT(self):
        host, _, port = self.path.partition(":")
        port = int(port) if port else 443

        if host not in ALLOWED:
            print(f"BLOCKED {host}:{port}", file=sys.stderr, flush=True)
            self.send_error(403, f"Domain not allowed: {host}")
            return

        try:
            upstream = socket.create_connection((host, port), timeout=10)
        except OSError as e:
            self.send_error(502, f"Cannot reach {host}:{port}: {e}")
            return

        self.send_response(200, "Connection Established")
        self.end_headers()

        self._tunnel(self.connection, upstream)

    def _tunnel(self, client, upstream):
        socks = [client, upstream]
        try:
            while True:
                readable, _, err = select.select(socks, [], socks, 30)
                if err:
                    break
                for s in readable:
                    data = s.recv(65536)
                    if not data:
                        return
                    target = upstream if s is client else client
                    target.sendall(data)
        except OSError:
            pass
        finally:
            upstream.close()

    def log_message(self, format, *args):
        pass

    # Reject all non-CONNECT methods
    def do_GET(self):
        self.send_error(405, "Only CONNECT is supported")

    do_POST = do_PUT = do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = do_GET


def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <allowed-domains.json>", file=sys.stderr)
        sys.exit(1)

    global ALLOWED
    ALLOWED = load_allowed_domains(sys.argv[1])

    class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
        daemon_threads = True

    server = ThreadedHTTPServer(("127.0.0.1", 0), ConnectProxy)
    port = server.server_address[1]

    # Signal the port to the parent process
    print(port, flush=True)

    print(f"claude-sandbox-proxy: listening on 127.0.0.1:{port} "
          f"({len(ALLOWED)} domains allowed)", file=sys.stderr, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
