"""Tiny localhost-only HTTP bridge used by the Godot frontend."""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock
from urllib.parse import urlparse

from .ui_resilient_session import ResilientUISession
from .ui_session import UIError


class SessionStore:
    def __init__(self):
        self.session: ResilientUISession | None = None
        self.lock = Lock()


STORE = SessionStore()


class Handler(BaseHTTPRequestHandler):
    server_version = "AvalonUI/0.1"

    def log_message(self, format, *args):  # noqa: A003 - stdlib signature
        return

    def _json(self, status: int, payload: dict):
        raw = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def _body(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length else b"{}"
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeError, json.JSONDecodeError):
            raise UIError("Request body must be valid JSON.") from None
        if not isinstance(data, dict):
            raise UIError("Request body must be a JSON object.")
        return data

    def do_GET(self):
        if urlparse(self.path).path == "/health":
            self._json(200, {"ok": True, "service": "avalon-ui"})
            return
        if urlparse(self.path).path == "/state":
            with STORE.lock:
                if STORE.session is None:
                    self._json(200, {"ok": True, "phase": "START"})
                else:
                    self._json(200, STORE.session.state())
            return
        self._json(404, {"ok": False, "error": "Not found."})

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            payload = self._body()
            with STORE.lock:
                if path == "/start":
                    count = payload.get("player_count", 5)
                    seed = payload.get("seed")
                    name = payload.get("human_name", "YOU")
                    if type(count) is not int or count not in (5, 6):
                        raise UIError("Player count must be 5 or 6.")
                    if seed in ("", None):
                        seed = None
                    elif type(seed) is not int:
                        raise UIError("Seed must be an integer or empty.")
                    STORE.session = ResilientUISession(player_count=count, seed=seed, human_name=str(name))
                    self._json(200, STORE.session.state())
                    return
                if path == "/action":
                    if STORE.session is None:
                        raise UIError("Start a game first.")
                    self._json(200, STORE.session.handle(payload))
                    return
        except UIError as exc:
            state = STORE.session.state() if STORE.session is not None else None
            payload = {"ok": False, "error": str(exc)}
            if state is not None:
                payload["state"] = state
            self._json(400, payload)
            return
        except Exception:
            # Never expose raw provider responses, API keys, stack traces, or hidden state to Godot.
            state = STORE.session.state() if STORE.session is not None else None
            payload = {"ok": False, "error": "Backend error. Check the local Python console/log."}
            if state is not None:
                payload["state"] = state
            self._json(500, payload)
            return
        self._json(404, {"ok": False, "error": "Not found."})


def main(argv=None):
    parser = argparse.ArgumentParser(description="Local localhost bridge for the Avalon Godot UI.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    if args.host not in {"127.0.0.1", "localhost"}:
        raise SystemExit("The UI bridge is intentionally localhost-only.")
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    try:
        print(f"Avalon UI backend listening on http://{args.host}:{args.port}", flush=True)
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
