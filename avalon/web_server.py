"""Loopback browser transport for the Assets PixiJS client.

The browser talks to the same GameSession used by the Godot GUI. Offline mode
is the default and never calls a provider; live mode is explicit.
"""
import argparse
import json
import mimetypes
import os
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

from .gui import GameSession
from .llm import Settings
from .offline_client import OfflineClient


MAX_BODY = 16384


def _local_ai_diagnostic_sink(path):
    """Append redacted AI decision metadata to an owner-only local journal."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    try:
        os.fchmod(fd, 0o600)
    finally:
        os.close(fd)
    lock = threading.Lock()

    def append(record):
        line = (json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
        if len(line) > 4096:
            raise ValueError("AI diagnostic record is too large")
        with lock:
            fd = os.open(path, flags, 0o600)
            try:
                os.fchmod(fd, 0o600)
                os.write(fd, line)
            finally:
                os.close(fd)

    return append


def _session_for_mode(mode, merlin_vote_policy, ai_diagnostic_sink=None):
    if mode == "offline":
        if merlin_vote_policy != "baseline":
            raise ValueError("V5 requires live mode")
        return GameSession(lambda: OfflineClient())
    if mode == "live":
        return GameSession(merlin_vote_policy=merlin_vote_policy,
                           ai_diagnostic_sink=ai_diagnostic_sink)
    raise ValueError("Unknown mode")


def make_server(*, mode="offline", merlin_vote_policy="baseline", assets_dir=None,
                host="127.0.0.1", port=8765, ai_diagnostic_path=None):
    token = secrets.token_urlsafe(32)
    diagnostic_path = None
    if mode == "live":
        diagnostic_path = (Path(ai_diagnostic_path) if ai_diagnostic_path is not None else
                           Path.home() / ".avalon" / "diagnostics" /
                           ("live-ai-%s.jsonl" % secrets.token_hex(8)))
    session = _session_for_mode(
        mode, merlin_vote_policy,
        _local_ai_diagnostic_sink(diagnostic_path) if diagnostic_path is not None else None,
    )
    assets = Path(assets_dir).resolve() if assets_dir else None
    server_port = int(port)

    class Handler(BaseHTTPRequestHandler):
        server_version = "AvalonWeb/1"

        def log_message(self, *_args):
            pass

        def _origin(self):
            return self.headers.get("Origin")

        def _allowed_origin(self):
            origin = self._origin()
            if origin is None:
                return True
            allowed = {
                "http://127.0.0.1:%d" % self.server.server_port,
                "http://localhost:%d" % self.server.server_port,
            }
            if origin in allowed:
                return True
            # Vite moves from 5173 when another dev server is already open.
            # Keep the allowance loopback-only and limited to its dev range.
            for host in ("http://127.0.0.1:", "http://localhost:"):
                if origin.startswith(host):
                    try:
                        return 5173 <= int(origin[len(host):]) <= 5199
                    except ValueError:
                        return False
            return False

        def _security_ok(self, require_token=False):
            host_header = (self.headers.get("Host") or "").split(":", 1)[0].lower()
            if host_header not in {"127.0.0.1", "localhost"}:
                return False
            fetch_site = self.headers.get("Sec-Fetch-Site")
            if fetch_site == "cross-site" or not self._allowed_origin():
                return False
            if require_token:
                supplied = self.headers.get("X-Avalon-Token", "")
                if not secrets.compare_digest(supplied, token):
                    return False
            return True

        def _send_json(self, status, value):
            body = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
            origin = self._origin()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            if origin and self._allowed_origin():
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def _send_error(self, status, message):
            self._send_json(status, {"ok": False, "error": message})

        def do_OPTIONS(self):
            if not self._security_ok():
                return self._send_error(403, "浏览器来源未获允许。")
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", self._origin() or "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Avalon-Token")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Max-Age", "300")
            self.end_headers()

        def do_GET(self):
            if self.path == "/api/session":
                if not self._security_ok():
                    return self._send_error(403, "浏览器来源未获允许。")
                return self._send_json(200, {
                    "ok": True, "mode": mode, "merlin_vote_policy": merlin_vote_policy,
                    "csrf_token": token, "state": session.snapshot(),
                })
            if self.path == "/api/state":
                if not self._security_ok(require_token=True):
                    return self._send_error(403, "本地会话授权无效。")
                return self._send_json(200, {"ok": True, "state": session.snapshot()})
            if self.path.startswith("/api/"):
                return self._send_error(404, "未知后端接口。")
            if assets is not None:
                return self._static()
            self._send_error(404, "未找到页面。")

        def _static(self):
            request_path = unquote(self.path.split("?", 1)[0]).lstrip("/")
            if request_path in {"", "/"}:
                request_path = "index.html"
            candidate = (assets / request_path).resolve()
            try:
                candidate.relative_to(assets)
            except ValueError:
                return self._send_error(404, "未找到页面。")
            if not candidate.is_file():
                candidate = assets / "index.html"
            if not candidate.is_file():
                return self._send_error(404, "未找到页面。")
            data = candidate.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(str(candidate))[0] or "application/octet-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            if self.path != "/api/command":
                return self._send_error(404, "未知后端接口。")
            if not self._security_ok(require_token=True):
                return self._send_error(403, "本地会话授权无效。")
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= MAX_BODY:
                    raise ValueError
                request = json.loads(self.rfile.read(length))
                if not isinstance(request, dict):
                    raise ValueError
            except (ValueError, TypeError, json.JSONDecodeError):
                return self._send_error(400, "操作请求格式无效。")
            return self._send_json(200, session.dispatch(request))

    server = ThreadingHTTPServer((host, server_port), Handler)
    server.ai_diagnostic_path = diagnostic_path
    return server


def main(argv=None):
    parser = argparse.ArgumentParser(description="Avalon browser server")
    parser.add_argument("--mode", choices=("offline", "live"), default="offline")
    parser.add_argument("--merlin-policy", choices=("baseline", "v5"), default="baseline")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--assets-dir", type=Path)
    args = parser.parse_args(argv)
    if args.mode == "live":
        try:
            settings = Settings.load()
        except ValueError as error:
            parser.error(str(error))
        if not settings.ready:
            parser.error("Live mode requires a configured API key and model in this project's .env.")
    try:
        server = make_server(mode=args.mode, merlin_vote_policy=args.merlin_policy,
                             assets_dir=args.assets_dir, host=args.host, port=args.port)
    except ValueError as error:
        parser.error(str(error))
    print("Avalon browser server listening on http://%s:%d (%s, Merlin vote: %s)" %
          (args.host, server.server_port, args.mode, args.merlin_policy), flush=True)
    if server.ai_diagnostic_path is not None:
        print("Local AI failure diagnostics: %s" % server.ai_diagnostic_path, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
