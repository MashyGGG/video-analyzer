"""CONNECT-only HTTPS gateway. No secrets, media volume, or arbitrary forward proxy."""

import select
import socketserver
import threading
import time

from app.services.sources.security import connect_public

SLOTS = threading.BoundedSemaphore(4)


class Tunnel(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        if not SLOTS.acquire(blocking=False):
            return
        try:
            self.connection.settimeout(8)
            request = self.rfile.readline(4097).decode("ascii")
            method, authority, version = request.strip().split(" ")
            if method != "CONNECT" or version not in ("HTTP/1.0", "HTTP/1.1"):
                raise ValueError("CONNECT only")
            host, port = authority.split(":")
            total = 0
            while True:
                line = self.rfile.readline(4097)
                total += len(line)
                if len(line) > 4096 or total > 8192 or not line:
                    raise ValueError("headers")
                if line == b"\r\n":
                    break
            with connect_public(host, int(port)) as target:
                self.connection.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
                deadline, transferred = time.monotonic() + 180, 0
                while time.monotonic() < deadline:
                    ready, _, _ = select.select([self.connection, target], [], [], 2)
                    for source in ready:
                        data = source.recv(65536)
                        transferred += len(data)
                        if not data or transferred > 220 * 1024 * 1024:
                            return
                        (target if source is self.connection else self.connection).sendall(data)
        except Exception:
            # No URL, TLS payload, credentials or exception body is logged.
            try:
                self.connection.sendall(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
            except OSError:
                pass
        finally:
            SLOTS.release()


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    with Server(("0.0.0.0", 8080), Tunnel) as server:
        server.serve_forever()
