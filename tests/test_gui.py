"""UI boundary tests use real rules/agents; only the model provider is replaced."""

from copy import deepcopy
import json
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from avalon.engine import Player
from avalon.gui import GameSession
from avalon.gui_server import make_server
from avalon.llm import LLMError
from test_agents import model_response, valid_plan
from test_evil_integration import performance


class UIModelClient:
    def __init__(self):
        self.error = None
        self.contexts = []

    def complete(self, context):
        self.contexts.append(deepcopy(context))
        if self.error:
            raise self.error
        if context.get("decision") in {"exile_nomination", "exile_vote"}:
            return model_response(context)
        if context.get("decision") == "window":
            allowed = context["game"]["legal_actions"]
            return {"action": {"kind": "DECLINE" if "DECLINE" in allowed else "SKIP"}}
        return performance(context) if "tactical" in context else valid_plan(context["game"])


class GUITests(unittest.TestCase):
    def setUp(self):
        self.client = UIModelClient()
        self.session = GameSession(lambda: self.client)
        self.counter = 0

    def request(self, command, payload=None, *, ok=True):
        self.counter += 1
        result = self.session.dispatch({"command": command, "payload": payload or {},
                                       "revision": self.session.revision, "request_id": str(self.counter)})
        self.assertEqual(result["ok"], ok, result["error"])
        return result["state"]

    def start(self, role="GOOD", count=5):
        roles = ["GOOD", "MERLIN", "ASSASSIN", "EVIL", "GOOD", "GOOD"][:count]
        index = roles.index(role)
        roles[0], roles[index] = roles[index], roles[0]
        players = [Player(f"P{i+1}", "YOU" if i == 0 else f"AI{i}", r) for i, r in enumerate(roles)]
        with patch("avalon.gui.make_players", return_value=players):
            state = self.request("start", {"players": count, "seed": 0})
        self.assertEqual(state["phase"], "ROLE_REVEAL")
        self.request("continue")
        return self.session.game

    def draft(self, team=None):
        return self.request("team", {"team": team or ["P1", "P2"]})

    def action(self, kind, **fields):
        return self.request("action", {"action": dict(kind=kind, **fields)})

    def to_revision(self):
        while self.session.game.phase != "revision":
            state = self.session.snapshot()
            if state["can_advance"]:
                self.request("advance")
            elif state["phase"] == "REACTION":
                self.action("SKIP")
            elif state["phase"] == "CHALLENGE_RESPONSE":
                self.action("DECLINE")
            else:
                self.action("PASS")

    def finish_ballots(self):
        while self.session.snapshot()["can_advance"]:
            self.request("advance")
        self.assertEqual(self.session.snapshot()["phase"], "VOTE_RESULT")

    def finish_council(self, choice="ABSTAIN", target=None):
        while self.session.snapshot()["phase"] != "EXILE_RESULT":
            state = self.session.snapshot()
            if state["can_advance"]:
                self.request("advance")
            elif state["phase"] == "COUNCIL_DISCUSSION":
                self.action("PASS")
            elif state["phase"] == "EXILE_NOMINATION":
                self.request("nominate_exile", {"target": target or state["selection_targets"][0]})
            elif state["phase"] == "EXILE_VOTE":
                self.request("exile_vote", {"choice": choice})
            else:
                self.fail(f"Unexpected council phase: {state['phase']}")

    def test_start_role_privacy_and_six_player_support(self):
        for count in (5, 6):
            for role in ("GOOD", "MERLIN", "EVIL", "ASSASSIN"):
                game = self.start(role, count)
                state = self.session.snapshot()
                self.assertEqual(len(state["players"]), count)
                self.assertEqual(state["private"]["role"], role)
                self.assertEqual(len(state["private"]["known_evil"]), 0 if role == "GOOD" else 2)
                self.assertTrue(all("role" not in p for p in state["players"]))
                self.assertNotIn("roles", json.dumps(state["public_events"]))
                self.assertEqual(game.leader, "P1")

    def test_team_selection_validates_and_ai_leader_acts(self):
        game = self.start()
        before = deepcopy(game.events)
        self.request("team", {"team": ["P1", "P1"]}, ok=False)
        self.assertEqual(game.events, before)
        state = self.draft()
        self.assertEqual(state["proposed_team"], ["P1", "P2"])
        self.assertEqual(state["phase"], "DISCUSSION")
        self.start()
        self.session.game.leader_index = 1
        state = self.request("advance")
        self.assertEqual(state["phase"], "DISCUSSION")
        self.assertEqual(len(state["proposed_team"]), 2)
        self.assertFalse(state["human_turn"])

    def test_costs_and_invalid_action_are_atomic(self):
        social = {"card": "ACCUSE", "target": "P3", "reason": "human_choice"}
        for kind, cost in (("SOCIAL", 1), ("COMMITTED_SOCIAL", 2), ("PASS", 0)):
            game = self.start()
            self.draft()
            self.action(kind, **({"social": social} if cost else {}))
            self.assertEqual(game.resolve["P1"], 3 - cost)
            self.assertEqual(self.session.snapshot()["players"][0]["resolve"], 3 - cost)
        game = self.start()
        self.draft()
        before = deepcopy(game.events)
        self.request("action", {"action": {"kind": "SOCIAL", "social": dict(social, target="P99")}}, ok=False)
        self.assertEqual(game.resolve["P1"], 3)
        self.assertEqual(game.events, before)

    def test_zero_resolve_pass_normal_vote_and_good_mission(self):
        game = self.start()
        self.draft()
        game.resolve["P1"] = 0
        self.assertEqual(self.session.snapshot()["legal_actions"], ["PASS"])
        self.action("PASS")
        self.to_revision()
        self.action("LOCK")
        self.request("vote", {"approve": True, "strong": True}, ok=False)
        self.assertNotIn("P1", self.session.ballots)
        self.request("vote", {"approve": True})
        self.finish_ballots()
        self.request("continue")
        self.assertEqual(self.session.snapshot()["legal_actions"], ["SUCCESS"])
        self.request("mission", {"card": "FAIL"}, ok=False)
        self.request("mission", {"card": "SUCCESS"})
        state = self.request("advance")
        self.assertEqual(state["phase"], "ROUND_RESULT")
        self.assertTrue(state["result"]["success"])
        self.assertEqual(state["mission_round"], 1)
        self.assertEqual(state["leader"], "P1")
        self.assertEqual(state["proposed_team"], ["P1", "P2"])
        state = self.request("continue")
        self.assertEqual(state["phase"], "COUNCIL_DISCUSSION")
        self.assertEqual(game.resolve["P1"], 0)
        self.finish_council()
        state = self.request("continue")
        self.assertIn("决心已恢复", state["notice"])
        self.assertTrue(state["safe_round"])
        self.assertEqual(state["mission_round"], 2)
        self.assertTrue(all(p["discussion_status"] == "waiting" for p in state["players"]))

    def test_challenge_uses_target_eligible_public_evidence(self):
        game = self.start()
        self.draft()
        seq = game.events[-1]["seq"]
        state = self.session.snapshot()
        self.assertIn(seq, state["challenge_evidence"]["P2"])
        self.assertNotIn("P1", state["challenge_evidence"])
        self.request("action", {"action": {"kind": "CHALLENGE", "target": "P3", "evidence": seq}}, ok=False)
        state = self.action("CHALLENGE", target="P2", evidence=seq)
        self.assertEqual(state["phase"], "CHALLENGE_RESPONSE")
        self.assertEqual(game.resolve["P1"], 2)
        self.assertEqual(state["challenge"]["evidence"], seq)
        self.request("advance")
        self.assertIsNone(game.challenge_window)

    def test_human_response_decline_and_no_recursive_challenge(self):
        for respond in (True, False):
            game = self.start()
            self.draft()
            seq = game.events[-1]["seq"]
            self.action("PASS")
            game.act("P2", {"kind": "CHALLENGE", "target": "P1", "evidence": seq})
            self.session._flush()
            self.assertEqual(self.session.snapshot()["legal_actions"], ["DECLINE", "RESPOND"])
            self.request("action", {"action": {"kind": "CHALLENGE", "target": "P2", "evidence": seq}}, ok=False)
            if respond:
                self.action("RESPOND", social={"card": "DEFEND", "target": "P1", "reason": "human_choice"})
                self.assertEqual(game.resolve["P1"], 2)
            else:
                game.resolve["P1"] = 0
                self.assertEqual(self.session.snapshot()["legal_actions"], ["DECLINE"])
                self.action("DECLINE")
            self.assertIsNone(game.challenge_window)

    def test_cite_preserves_original_event(self):
        game = self.start()
        self.draft()
        original = deepcopy(game.events[-1])
        state = self.action("CITE", evidence=original["seq"])
        self.assertEqual(game.events[original["seq"]-1], original)
        self.assertEqual(game.events[-1]["kind"], "CITE")
        self.assertEqual(state["players"][0]["resolve"], 2)

    def test_hold_skip_react_once_and_expiration(self):
        game = self.start()
        self.draft()
        self.action("HOLD")
        self.assertTrue(self.session.snapshot()["players"][0]["reaction_ready"])
        self.request("advance")
        self.assertEqual(self.session.snapshot()["phase"], "REACTION")
        self.action("SKIP")
        self.request("advance")
        self.action("REACT", social={"card": "HEDGE", "target": "P2", "reason": "human_choice"})
        self.assertEqual(game.resolve["P1"], 2)
        self.assertFalse(self.session.snapshot()["players"][0]["reaction_ready"])
        self.to_revision()
        self.assertEqual(sum(e["kind"] == "REACT" for e in game.events), 1)
        game = self.start()
        self.draft()
        self.action("HOLD")
        self.to_revision()
        self.assertFalse(game.pending_reactions)
        self.assertIn("已到期", self.session.snapshot()["notice"])

    def test_revision_replaces_exactly_one_and_proceeds_to_vote(self):
        game = self.start()
        self.draft()
        self.to_revision()
        self.request("action", {"action": {"kind": "REVISE", "removed": "P1", "added": "P2"}}, ok=False)
        state = self.action("REVISE", removed="P2", added="P5")
        self.assertEqual(state["phase"], "VOTE")
        self.assertEqual(game.team, ["P1", "P5"])
        self.assertEqual(game.resolve["P1"], 2)

    def test_ballots_are_sealed_strong_vote_counts_once_and_replay_is_safe(self):
        game = self.start()
        self.draft()
        self.to_revision()
        self.action("LOCK")
        old_public = self.session.snapshot()["public_events"]
        old_resolve = dict(game.resolve)
        request = {"request_id": "sealed", "revision": self.session.revision, "command": "vote",
                   "payload": {"approve": True, "strong": True}}
        self.assertTrue(self.session.dispatch(request)["ok"])
        self.assertTrue(self.session.dispatch(request)["ok"])
        self.assertEqual(game.resolve, old_resolve)
        self.assertEqual(self.session.snapshot()["public_events"], old_public)
        self.assertNotIn("ballots", self.session.snapshot())
        for _ in range(3):
            self.request("advance")
            self.assertEqual(self.session.snapshot()["public_events"], old_public)
        state = self.request("advance")
        self.assertEqual(state["phase"], "VOTE_RESULT")
        self.assertEqual(len(state["result"]["ballots"]), 5)
        self.assertEqual(game.resolve["P1"], old_resolve["P1"] - 1)
        self.assertTrue(state["result"]["approved"])
        self.assertEqual(len(state["result"]["votes"]), 5)

    def test_rejection_keeps_resolve_and_next_leader(self):
        game = self.start()
        self.draft()
        self.action("SOCIAL", social={"card": "ACCUSE", "target": "P3", "reason": "human_choice"})
        self.to_revision()
        self.action("LOCK")
        self.request("vote", {"approve": False, "strong": True})
        # The ballots are private adapter storage until the engine accepts all five.
        self.session.ballots.update({p: {"approve": False, "strong": False} for p in game.ids[1:]})
        self.session._finish_vote()
        self.session._flush()
        self.assertEqual(game.resolve["P1"], 1)
        state = self.request("continue")
        self.assertEqual(state["proposal_attempt"], 2)
        self.assertEqual(state["leader"], "P2")
        self.assertEqual(sum(e["kind"] == "RESOLVE_REFRESH" for e in game.events), 1)

    def test_evil_mission_and_private_author_never_serialized(self):
        game = self.start("EVIL")
        self.draft(["P1", "P3"])
        self.to_revision()
        self.action("LOCK")
        self.request("vote", {"approve": True})
        self.finish_ballots()
        self.request("continue")
        self.assertEqual(self.session.snapshot()["legal_actions"], ["SUCCESS", "FAIL"])
        self.request("mission", {"card": "FAIL"})
        waiting = json.dumps(self.session.snapshot())
        self.assertNotIn('"mission_card"', waiting)
        state = self.request("advance")
        self.assertEqual(state["result"]["fail_count"], 1)
        self.assertNotIn("actor", state["result"])
        text = json.dumps(state)
        for secret in ("MISSION_SUBMIT", "mission_fail_owner", "beliefs", "merlin_probabilities", "tactical", "rationale"):
            self.assertNotIn(secret, text)

    def test_assassination_permissions_and_public_end(self):
        game = self.start("ASSASSIN")
        game.phase = "assassination"
        state = self.session.snapshot()
        self.assertEqual(state["legal_actions"], ["ASSASSINATE"])
        self.assertNotIn("P4", state["selection_targets"])
        self.request("assassinate", {"target": "P4"}, ok=False)
        state = self.request("assassinate", {"target": "P2"})
        self.assertEqual(state["winner"], "EVIL")
        self.assertEqual(state["phase"], "GAME_OVER")
        self.assertNotIn("REVEAL", json.dumps(state["public_events"]))
        game = self.start()
        game.phase = "assassination"
        self.assertIsNone(self.session.snapshot()["current_actor"])
        self.request("assassinate", {"target": "P2"}, ok=False)
        self.assertEqual(self.request("advance")["phase"], "GAME_OVER")

    def test_ai_error_is_recoverable_and_never_fabricates_an_action(self):
        game = self.start()
        self.draft()
        self.action("PASS")
        before = deepcopy(game.events)
        dialogue_before = self.session.snapshot()["dialogue"]
        self.client.error = LLMError("connection_error")
        state = self.request("advance", ok=False)
        self.assertEqual(game.events, before)
        self.assertEqual(state["dialogue"], dialogue_before)
        self.assertTrue(state["retry_ai"])
        self.assertFalse(state["can_advance"])
        self.client.error = None
        state = self.request("retry")
        self.assertFalse(state["retry_ai"])
        self.assertGreater(len(game.events), len(before))

    def test_dialogue_publishes_accepted_ai_speech_once_without_private_fields(self):
        game = self.start()
        self.draft()
        self.action("SOCIAL", social={"card": "DEFEND", "target": "P2", "reason": "human_choice"})
        self.assertEqual(self.session.snapshot()["dialogue"], [])
        state = self.request("advance")
        event = next(e for e in reversed(game.events) if e["kind"] == "SOCIAL")
        self.assertEqual(state["dialogue"], [{
            "seq": event["seq"], "actor": "P2", "round": 1, "attempt": 1,
            "kind": "SOCIAL", "card": event["card"], "target": event["target"],
            "committed": False, "statement": event["statement"], "discussion_stage": "proposal",
            "record_id": event["record_id"], "citations": [], "citation_records": [],
        }])
        self.assertIn("请解释", state["dialogue"][0]["statement"])
        self.assertNotIn("rationale", json.dumps(state))
        self.assertNotIn("statement", json.dumps(state["public_events"]))
        # Refresh and duplicate command delivery must not manufacture another line.
        replay = self.session.dispatch({"request_id": str(self.counter)})
        self.assertEqual(replay["state"]["dialogue"], state["dialogue"])
        self.assertEqual(self.session.snapshot()["dialogue"], state["dialogue"])
        game.act("P3", {"kind": "CITE", "evidence": event["seq"]})
        self.session._flush()
        self.assertEqual(self.session.snapshot()["dialogue"], state["dialogue"])
        self.start()
        self.assertEqual(self.session.snapshot()["dialogue"], [])

    def test_dialogue_includes_response_reaction_and_commitment(self):
        speech = {"card": "DEFEND", "target": "P2", "reason": "support",
                  "statement": "请先看公开记录，我支持这支队伍。", "rationale": "公开理由摘要。", "evidence": []}
        for kind in ("RESPOND", "REACT", "COMMITTED_SOCIAL"):
            with self.subTest(kind=kind):
                game = self.start()
                self.draft()
                if kind == "RESPOND":
                    self.action("CHALLENGE", target="P2", evidence=game.events[-1]["seq"])
                else:
                    self.action("PASS")
                    if kind == "REACT":
                        game.act("P2", {"kind": "HOLD"})
                        game.act("P3", {"kind": "PASS"})
                game.act("P2", {"kind": kind, "social": speech})
                self.session._flush()
                message, = self.session.snapshot()["dialogue"]
                self.assertEqual(message["actor"], "P2")
                self.assertEqual(message["statement"], speech["statement"])
                self.assertEqual(message["kind"], {"RESPOND": "CHALLENGE_RESPONSE", "REACT": "REACT",
                                                   "COMMITTED_SOCIAL": "SOCIAL"}[kind])
                self.assertEqual(message["committed"], kind == "COMMITTED_SOCIAL")
                self.assertNotIn("rationale", message)
                if kind in {"RESPOND", "REACT"}:
                    source_kind = "CHALLENGE" if kind == "RESPOND" else "PASS"
                    source = game.chronicle.reader().get_record(message["reply_to"])
                    self.assertEqual(source["kind"], source_kind)
                    self.assertLess(source["seq"], message["seq"])
                    self.assertIn(source["record_id"], [e["record_id"] for e in self.session.snapshot()["public_events"]])
                else:
                    self.assertNotIn("reply_to", message)

    def test_stale_and_wrong_phase_commands_do_not_mutate(self):
        game = self.start()
        before = deepcopy(game.events)
        self.assertFalse(self.session.dispatch({"request_id": "stale", "revision": -1,
                                              "command": "team", "payload": {"team": ["P1", "P2"]}})["ok"])
        self.request("mission", {"card": "SUCCESS"}, ok=False)
        self.request("action", {"action": {"kind": "VOTE"}}, ok=False)
        self.assertEqual(before, game.events)

    def test_full_matches_and_restart_through_only_boundary_commands(self):
        phases = set()
        for count in (5, 6):
            for seed in range(8):
                self.request("start", {"players": count, "seed": seed})
                for _ in range(400):
                    state = self.session.snapshot()
                    phases.add(state["phase"])
                    if state["phase"] == "GAME_OVER":
                        break
                    if "CONTINUE" in state["legal_actions"]:
                        self.request("continue")
                    elif state["can_advance"]:
                        self.request("advance")
                    elif state["phase"] == "TEAM_DRAFT":
                        self.request("team", {"team": [p["id"] for p in state["players"]][:state["team_size"]]})
                    elif state["phase"] in {"DISCUSSION", "COUNCIL_DISCUSSION"}:
                        self.action("PASS")
                    elif state["phase"] == "CHALLENGE_RESPONSE":
                        self.action("DECLINE")
                    elif state["phase"] == "REACTION":
                        self.action("SKIP")
                    elif state["phase"] == "TEAM_CONFIRM":
                        self.action("LOCK")
                    elif state["phase"] == "VOTE":
                        self.request("vote", {"approve": True})
                    elif state["phase"] == "MISSION":
                        self.request("mission", {"card": "SUCCESS"})
                    elif state["phase"] == "ASSASSINATION":
                        self.request("assassinate", {"target": state["selection_targets"][0]})
                    elif state["phase"] == "EXILE_NOMINATION":
                        self.request("nominate_exile", {"target": state["selection_targets"][0]})
                    elif state["phase"] == "EXILE_VOTE":
                        self.request("exile_vote", {"choice": "ABSTAIN"})
                    else:
                        self.fail(state)
                self.assertIsNotNone(self.session.game.winner)
        self.assertTrue({"ROLE_REVEAL", "TEAM_DRAFT", "DISCUSSION", "TEAM_CONFIRM", "VOTE",
                         "VOTE_RESULT", "MISSION", "ROUND_RESULT", "ASSASSINATION", "GAME_OVER",
                         "COUNCIL_DISCUSSION", "EXILE_NOMINATION", "EXILE_VOTE", "EXILE_RESULT"} <= phases)

    def test_http_auth_origin_invalid_body_and_commands(self):
        server = make_server(self.session, "test-token")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            for headers in ({}, {"Authorization": "Bearer test-token", "Origin": "https://example.com"}):
                with self.assertRaises(HTTPError) as error:
                    urlopen(Request(base + "/state", headers=headers), timeout=2)
                self.assertEqual(error.exception.code, 403)
            headers = {"Authorization": "Bearer test-token"}
            with urlopen(Request(base + "/state", headers=headers), timeout=2) as response:
                self.assertEqual(json.load(response)["state"]["phase"], "START")
            data = json.dumps({"command": "start", "payload": {"seed": 0}, "revision": 0, "request_id": "http"}).encode()
            with urlopen(Request(base + "/command", data=data, headers=headers), timeout=2) as response:
                self.assertEqual(json.load(response)["state"]["phase"], "ROLE_REVEAL")
            with self.assertRaises(HTTPError) as error:
                urlopen(Request(base + "/command", data=b"invalid", headers=headers), timeout=2)
            self.assertEqual(error.exception.code, 400)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)


if __name__ == "__main__":
    unittest.main()
