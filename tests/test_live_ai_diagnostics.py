"""Local live diagnostics record safe failure and accepted-action metadata."""

from copy import deepcopy
import json
from pathlib import Path
import stat
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from avalon.engine import Player
from avalon.gui import GameSession
from avalon.web_server import _local_ai_diagnostic_sink, make_server
from test_agents import valid_plan


class ExtraDiscussionKindClient:
    def __init__(self):
        self.calls = 0
        self.last_call = {}

    def complete(self, context):
        self.calls += 1
        self.last_call = {
            "id": f"response-{self.calls}",
            "response_sha256": "a" * 64,
            "finish_reason": "stop",
            "usage": {"prompt_tokens": 100, "completion_tokens": 20,
                      "private_tokens": "DO_NOT_LOG"},
            "response_content": "RAW_SECRET_CANARY discussion_kind",
            "Authorization": "SECRET_KEY_CANARY",
        }
        action = deepcopy(valid_plan(context["game"]))
        action.pop("beliefs")
        action.pop("profiles")
        action["discussion_kind"] = "PASS"
        return {
            "belief_updates": [], "interpretation": [], "public_stance_change": None,
            "recommended_action": action, "short_rationale": "公开信息仍有限。",
        }


class PassWithDraftAfterRetryClient:
    def __init__(self):
        self.calls = 0
        self.last_call = {}

    def complete(self, context):
        self.calls += 1
        self.last_call = {
            "id": f"response-{self.calls}", "response_sha256": "b" * 64,
            "finish_reason": "stop", "usage": {"prompt_tokens": 120,
                                                 "completion_tokens": 30,
                                                 "private_tokens": "DO_NOT_LOG"},
            "response_content": "RAW_SECRET_CANARY",
        }
        action = deepcopy(valid_plan(context["game"]))
        action.pop("beliefs")
        action.pop("profiles")
        action.update(mission="SUCCESS", discussion={"kind": "PASS"},
                      revision={"kind": "LOCK"}, strong_vote=False)
        action["social"]["statement"] = "DRAFT_SPEECH_SECRET_CANARY"
        if self.calls == 1:
            action["discussion_kind"] = "PASS"
        return {
            "belief_updates": [], "interpretation": [], "public_stance_change": None,
            "recommended_action": action, "short_rationale": "公开信息仍有限。",
        }


class LiveAIDiagnosticTests(unittest.TestCase):
    def test_extra_action_key_is_rejected_three_times_without_leaking_response(self):
        records = []
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "diagnostics" / "attempts.jsonl"
        append = _local_ai_diagnostic_sink(path)

        def record(item):
            records.append(item)
            append(item)

        client = ExtraDiscussionKindClient()
        session = GameSession(lambda: client, ai_diagnostic_sink=record)
        players = [Player(f"P{i+1}", f"Seat{i+1}", role) for i, role in enumerate(
            ["GOOD", "GOOD", "MERLIN", "ASSASSIN", "EVIL"])]
        with patch("avalon.gui.make_players", return_value=players):
            session.start(5, 0)

        def command(name, payload=None):
            return session.dispatch({"request_id": f"test-{name}-{session.revision}",
                                     "revision": session.revision, "command": name,
                                     "payload": payload or {}})

        self.assertTrue(command("continue")["ok"])
        self.assertTrue(command("team", {"team": ["P1", "P2"]})["ok"])
        self.assertTrue(command("action", {"action": {"kind": "PASS"}})["ok"])
        self.assertEqual(session.snapshot()["current_actor"], "P2")
        session.agents["P2"].max_retries = 2
        session.agents["P2"].retry_delay = 0
        before_events = deepcopy(session.game.events)
        before_revision = session.revision
        result = command("advance")

        self.assertFalse(result["ok"])
        self.assertEqual(client.calls, 3)
        self.assertEqual(session.revision, before_revision)
        self.assertEqual(session.game.events, before_events)
        self.assertEqual(session.game.phase, "discussion")
        self.assertTrue(result["state"]["retry_ai"])
        self.assertEqual([r["attempt_index"] for r in records], [1, 2, 3])
        self.assertEqual([r["will_retry"] for r in records], [True, True, False])
        self.assertEqual([r["response_id"] for r in records],
                         ["response-1", "response-2", "response-3"])
        self.assertEqual([json.loads(line) for line in path.read_text().splitlines()], records)
        self.assertTrue(all(r["phase"] == "discussion" and r["actor_id"] == "P2"
                            and r["decision_kind"] is None and r["mock_response_id"] is None
                            and r["public_code"] == "invalid_plan"
                            and r["validation_reason"] == "Invalid plan keys"
                            and "PASS" in r["legal_actions"] for r in records))
        saved = path.read_text()
        wire = json.dumps(result, ensure_ascii=False)
        for secret in ("RAW_SECRET_CANARY", "SECRET_KEY_CANARY", "private_tokens",
                       "discussion_kind", "recommended_action"):
            self.assertNotIn(secret, saved)
            self.assertNotIn(secret, wire)

    def test_committed_pass_with_unused_draft_logs_only_safe_decision_metadata(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "diagnostics" / "actions.jsonl"
            append = _local_ai_diagnostic_sink(path)
            records = []

            def record(item):
                records.append(item)
                append(item)

            client = PassWithDraftAfterRetryClient()
            session = GameSession(lambda: client, ai_diagnostic_sink=record)
            players = [Player(f"P{i+1}", f"Seat{i+1}", role) for i, role in enumerate(
                ["GOOD", "GOOD", "MERLIN", "ASSASSIN", "EVIL"])]
            with patch("avalon.gui.make_players", return_value=players):
                session.start(5, 0)

            def command(name, payload=None):
                return session.dispatch({"request_id": f"accepted-{name}-{session.revision}",
                                         "revision": session.revision, "command": name,
                                         "payload": payload or {}})

            self.assertTrue(command("continue")["ok"])
            self.assertTrue(command("team", {"team": ["P1", "P2"]})["ok"])
            self.assertTrue(command("action", {"action": {"kind": "PASS"}})["ok"])
            session.agents["P2"].max_retries = 1
            session.agents["P2"].retry_delay = 0
            result = command("advance")

            self.assertTrue(result["ok"], result["error"])
            self.assertEqual(client.calls, 2)
            self.assertEqual([record.get("event_type") for record in records],
                             [None, "accepted_discussion_action"])
            accepted = records[1]
            event = next(e for e in session.game.events
                         if e["kind"] == "PASS" and e.get("actor") == "P2")
            self.assertEqual(accepted["action_seq"], event["seq"])
            self.assertEqual((accepted["phase"], accepted["actor_id"],
                              accepted["action_kind"], accepted["retry_count"]),
                             ("discussion", "P2", "PASS", 1))
            self.assertIsNone(accepted["decision_kind"])
            self.assertIsNone(accepted["mock_response_id"])
            self.assertTrue(accepted["plan_social_present"])
            self.assertIn("SOCIAL", accepted["legal_actions"])
            self.assertEqual(accepted["response_id"], "response-2")
            self.assertEqual(accepted["response_sha256"], "b" * 64)
            self.assertEqual(accepted["usage"],
                             {"prompt_tokens": 120, "completion_tokens": 30})
            self.assertEqual([json.loads(line) for line in path.read_text().splitlines()],
                             records)
            saved = path.read_text()
            wire = json.dumps(result, ensure_ascii=False)
            for secret in ("RAW_SECRET_CANARY", "DRAFT_SPEECH_SECRET_CANARY",
                           "private_tokens", "recommended_action", "discussion_kind"):
                self.assertNotIn(secret, saved)
                self.assertNotIn(secret, wire)

    def test_local_jsonl_journal_is_owner_only(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "diagnostics" / "failure.jsonl"
            sink = _local_ai_diagnostic_sink(path)
            sink({"phase": "discussion", "public_code": "invalid_plan"})
            self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual([json.loads(line) for line in path.read_text().splitlines()],
                             [{"phase": "discussion", "public_code": "invalid_plan"}])

    def test_web_diagnostics_are_live_only(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "diagnostics" / "live.jsonl"
            offline = make_server(mode="offline", port=0, ai_diagnostic_path=path)
            try:
                self.assertIsNone(offline.ai_diagnostic_path)
                self.assertFalse(path.exists())
            finally:
                offline.server_close()
            live = make_server(mode="live", port=0, ai_diagnostic_path=path)
            try:
                self.assertEqual(live.ai_diagnostic_path, path)
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            finally:
                live.server_close()


if __name__ == "__main__":
    unittest.main()
