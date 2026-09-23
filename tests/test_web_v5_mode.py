"""The browser session reports its explicit local AI policy selection."""

import json
import threading
import unittest
from urllib.request import urlopen

from avalon.web_server import make_server


class WebV5ModeTests(unittest.TestCase):
    def session(self, **server_options):
        server = make_server(port=0, **server_options)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with urlopen("http://127.0.0.1:%d/api/session" % server.server_port) as response:
                return json.load(response)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_default_session_reports_offline_baseline(self):
        payload = self.session()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["mode"], "offline")
        self.assertEqual(payload["merlin_vote_policy"], "baseline")
        self.assertEqual(payload["discussion_policy"], "baseline")
        self.assertEqual(payload["state"]["phase"], "START")

    def test_explicit_live_v5_session_reports_selected_policy(self):
        payload = self.session(mode="live", merlin_vote_policy="v5")
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["mode"], "live")
        self.assertEqual(payload["merlin_vote_policy"], "v5")
        self.assertEqual(payload["discussion_policy"], "engaged_v1")
        self.assertEqual(payload["state"]["phase"], "START")

    def test_offline_v5_combination_is_rejected(self):
        with self.assertRaises(ValueError):
            make_server(mode="offline", merlin_vote_policy="v5", port=0)

    def test_live_can_explicitly_select_legacy_discussion(self):
        payload = self.session(mode="live", discussion_policy="baseline")
        self.assertEqual(payload["discussion_policy"], "baseline")

    def test_offline_engaged_discussion_is_rejected(self):
        with self.assertRaises(ValueError):
            make_server(mode="offline", discussion_policy="engaged_v1", port=0)


if __name__ == "__main__":
    unittest.main()
