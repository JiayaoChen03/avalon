"""Private loopback transport, launched and owned by the Godot process."""

import argparse
import hmac
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import secrets
import threading
import time

from .gui import GameSession


def make_server(session, token, port=0):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass  # No credentials, model responses, or private plans in HTTP logs.

        def _authorized(self):
            origin = self.headers.get("Origin")
            return (origin is None and hmac.compare_digest(
                self.headers.get("Authorization", ""), "Bearer " + token))

        def _reply(self, status, value):
            data = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass  # The versioned command can be replayed after a lost response.

        def do_GET(self):
            if not self._authorized():
                return self._reply(403, {"error": "Local session authorization required"})
            if self.path == "/debug/cognition" and session.developer_mode:
                return self._reply(200, session.cognition_debug_view())
            if self.path != "/state":
                return self._reply(404, {"error": "Unknown endpoint"})
            self._reply(200, {"ok": True, "state": session.snapshot()})

        def do_POST(self):
            if not self._authorized():
                return self._reply(403, {"error": "Local session authorization required"})
            if self.path != "/command":
                return self._reply(404, {"error": "Unknown endpoint"})
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 16384:
                    raise ValueError
                request = json.loads(self.rfile.read(size))
            except (ValueError, UnicodeDecodeError):
                return self._reply(400, {"error": "Invalid request"})
            self._reply(200, session.dispatch(request))

    server = HTTPServer(("127.0.0.1", port), Handler)
    server.timeout = 1
    return server


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--connection-file", type=Path, required=True)
    parser.add_argument("--parent-pid", type=int, required=True)
    parser.add_argument("--debug-cognition", action="store_true")
    args = parser.parse_args(argv)
    token = secrets.token_urlsafe(32)
    server = make_server(GameSession(developer_mode=args.debug_cognition), token)
    connection = args.connection_file
    connection.parent.mkdir(parents=True, exist_ok=True)
    temporary = connection.with_suffix(".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump({"url": f"http://127.0.0.1:{server.server_port}", "token": token}, stream)
    os.replace(temporary, connection)

    def watch_parent():
        while True:
            time.sleep(2)
            try:
                if os.name == "nt":
                    # Unlike POSIX, os.kill(pid, 0) can terminate a Windows process.
                    import ctypes
                    from ctypes import wintypes
                    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
                    kernel.OpenProcess.restype = wintypes.HANDLE
                    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
                    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
                    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
                    handle = kernel.OpenProcess(0x1000, False, args.parent_pid)
                    if not handle:
                        raise OSError("Parent exited")
                    code = wintypes.DWORD()
                    try:
                        if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value != 259:
                            raise OSError("Parent exited")
                    finally:
                        kernel.CloseHandle(handle)
                else:
                    os.kill(args.parent_pid, 0)
            except OSError:
                server.shutdown()
                return

    threading.Thread(target=watch_parent, daemon=True).start()
    try:
        server.serve_forever(poll_interval=0.25)
    finally:
        server.server_close()
        connection.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
