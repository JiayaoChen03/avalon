import json
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from avalon.gui import GameSession
from avalon.offline_client import OfflineClient
from avalon.web_server import make_server


class WebServerTests(unittest.TestCase):
    def setUp(self):
        self.server = make_server(port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = "http://127.0.0.1:%d" % self.server.server_port

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def get(self, path, headers=None):
        request = Request(self.base + path, headers=headers or {})
        with urlopen(request) as response:
            return response.status, json.load(response)

    def post(self, path, body, headers):
        request = Request(self.base + path, data=json.dumps(body).encode(),
                          headers={"Content-Type": "application/json", **headers}, method="POST")
        with urlopen(request) as response:
            return response.status, json.load(response)

    def test_session_is_offline_and_start_is_authoritative(self):
        _, session = self.get("/api/session")
        self.assertEqual(session["mode"], "offline")
        self.assertEqual(session["state"]["phase"], "START")
        command = {
            "request_id": "browser-test-1", "revision": 0, "command": "start",
            "payload": {"players": 5, "seed": 13},
        }
        _, started = self.post("/api/command", command,
                               {"X-Avalon-Token": session["csrf_token"]})
        self.assertTrue(started["ok"])
        self.assertEqual(started["state"]["phase"], "ROLE_REVEAL")
        _, replay = self.post("/api/command", command,
                              {"X-Avalon-Token": session["csrf_token"]})
        self.assertEqual(replay["state"]["phase"], "ROLE_REVEAL")

    def test_state_and_command_require_session_token(self):
        with self.assertRaises(HTTPError) as state_error:
            self.get("/api/state")
        self.assertEqual(state_error.exception.code, 403)
        with self.assertRaises(HTTPError) as command_error:
            self.post("/api/command", {}, {})
        self.assertEqual(command_error.exception.code, 403)

    def test_cross_site_origin_is_rejected(self):
        with self.assertRaises(HTTPError) as error:
            self.get("/api/session", {"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"})
        self.assertEqual(error.exception.code, 403)

    def test_revision_error_returns_safe_state(self):
        _, session = self.get("/api/session")
        command = {
            "request_id": "browser-test-revision", "revision": 99, "command": "start",
            "payload": {"players": 5},
        }
        _, result = self.post("/api/command", command,
                              {"X-Avalon-Token": session["csrf_token"]})
        self.assertFalse(result["ok"])
        self.assertTrue(result["state"])
        self.assertIn("error", result)

    def test_reset_game_starts_a_fresh_session(self):
        _, session = self.get("/api/session")
        start_request = {
            "request_id": "browser-test-reset-start", "revision": 0, "command": "start",
            "payload": {"players": 5, "seed": 13},
        }
        _, started = self.post("/api/command", start_request,
                               {"X-Avalon-Token": session["csrf_token"]})
        reset_request = {
            "request_id": "browser-test-reset-game", "revision": started["state"]["revision"],
            "command": "reset_game", "payload": {"players": 6, "seed": 17},
        }
        _, reset = self.post("/api/command", reset_request,
                             {"X-Avalon-Token": session["csrf_token"]})
        self.assertTrue(reset["ok"])
        self.assertEqual(reset["state"]["phase"], "ROLE_REVEAL")
        self.assertEqual(len(reset["state"]["players"]), 6)
        self.assertFalse(reset["state"]["retry_ai"])

    def test_restart_round_clears_ai_pause_without_changing_public_phase(self):
        session = GameSession(lambda: OfflineClient())
        session.start(5, 13)
        session.dispatch({"request_id": "dismiss-reveal", "revision": session.revision,
                          "command": "continue", "payload": {}})
        phase_before = session.snapshot()["phase"]
        session.ai_error = True
        session.error = "AI paused"
        result = session.dispatch({"request_id": "restart-ai-round", "revision": session.revision,
                                   "command": "restart_round", "payload": {}})
        self.assertTrue(result["ok"])
        self.assertEqual(result["state"]["phase"], phase_before)
        self.assertFalse(result["state"]["retry_ai"])
        self.assertEqual(result["state"]["error"], "")


if __name__ == "__main__":
    unittest.main()
