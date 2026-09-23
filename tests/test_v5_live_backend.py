"""Local V5 vote opt-in checks; every model response is supplied in process."""

from copy import deepcopy
import unittest
from unittest.mock import patch

from avalon.engine import Player
from avalon.eval.v2 import v232_candidate_v5 as v5
from avalon.gui import GameSession
from test_agents import model_response, valid_plan
from test_evil_integration import performance


class FakeModelClient:
    def __init__(self):
        self.contexts = []

    def complete(self, context):
        self.contexts.append(deepcopy(context))
        if context.get("decision") in {"exile_nomination", "exile_vote"}:
            return model_response(context)
        if context.get("decision") == "window":
            allowed = context["game"]["legal_actions"]
            return {"action": {"kind": "DECLINE" if "DECLINE" in allowed else "SKIP"}}
        return performance(context) if "tactical" in context else valid_plan(context["game"])


class V5LiveBackendTests(unittest.TestCase):
    def _command(self, session, command, payload=None, *, ok=True):
        result = session.dispatch({
            "request_id": f"v5-test-{session.revision}-{command}",
            "revision": session.revision,
            "command": command,
            "payload": payload or {},
        })
        self.assertEqual(result["ok"], ok, result["error"])
        return result

    def _to_vote(self, team, *, policy=None):
        client = FakeModelClient()
        options = {} if policy is None else {"merlin_vote_policy": policy}
        session = GameSession(lambda: client, **options)
        players = [
            Player("P1", "YOU", "GOOD"),
            Player("P2", "MERLIN_AI", "MERLIN"),
            Player("P3", "ASSASSIN_AI", "ASSASSIN"),
            Player("P4", "EVIL_AI", "EVIL"),
            Player("P5", "GOOD_AI", "GOOD"),
        ]
        with patch("avalon.gui.make_players", return_value=players):
            self._command(session, "start", {"players": 5, "seed": 0})
        self._command(session, "continue")
        self._command(session, "team", {"team": team})
        while session.game.phase != "revision":
            state = session.snapshot()
            if state["can_advance"]:
                self._command(session, "advance")
            elif state["phase"] == "REACTION":
                self._command(session, "action", {"action": {"kind": "SKIP"}})
            elif state["phase"] == "CHALLENGE_RESPONSE":
                self._command(session, "action", {"action": {"kind": "DECLINE"}})
            else:
                self._command(session, "action", {"action": {"kind": "PASS"}})
        self._command(session, "action", {"action": {"kind": "LOCK"}})
        self.assertEqual(session.game.phase, "vote")
        self.assertEqual(session._decision_actor(), "P1")
        self.assertEqual(session.game.view("P2")["known_evil"], ["P3", "P4"])
        return session, client

    def test_v5_ai_merlin_approves_clean_and_rejects_dirty_team_without_strong_vote(self):
        for team, expected_vote in ((["P1", "P2"], True), (["P2", "P3"], False)):
            with self.subTest(team=team):
                session, _ = self._to_vote(team, policy="v5")
                # The model's cached modifier cannot change the V5 ballot.
                session.agents["P2"].plan["strong_vote"] = True
                self._command(session, "vote", {"approve": True})
                self._command(session, "advance")
                self.assertEqual(session.ballots["P2"], {
                    "approve": expected_vote, "strong": False,
                })
                self.assertEqual(session.game.phase, "vote")
                self.assertFalse(any(e["kind"] in {"VOTE", "TEAM_VOTE"}
                                     for e in session.game.events))
                while session.snapshot()["can_advance"]:
                    self._command(session, "advance")
                recorded = [e for e in session.game.events
                            if e["kind"] == "VOTE" and e["actor"] == "P2"]
                self.assertEqual(len(recorded), 1)
                self.assertIs(recorded[0]["approve"], expected_vote)
                self.assertIs(recorded[0]["strong"], False)

    def test_default_policy_uses_the_existing_agent_ballot(self):
        session, _ = self._to_vote(["P2", "P3"])
        expected = {"approve": True, "strong": True}
        self._command(session, "vote", {"approve": False})
        with patch.object(session.agents["P2"], "ballot", return_value=expected) as ballot:
            self._command(session, "advance")
        ballot.assert_called_once_with(["P2", "P3"], 1)
        self.assertEqual(session.ballots["P2"], expected)

    def test_v5_reads_only_merlin_legal_public_history_and_keeps_ballots_sealed(self):
        session, _ = self._to_vote(["P2", "P3"], policy="v5")
        public_before = session.snapshot()["public_events"]
        self._command(session, "vote", {"approve": False})
        self.assertEqual(session.snapshot()["public_events"], public_before)
        original = v5.candidate_vote_decision
        captured = []

        def inspect_input(public_state, actor_view):
            captured.append((public_state, deepcopy(actor_view)))
            return original(public_state, actor_view)

        with patch.object(v5, "candidate_vote_decision", side_effect=inspect_input):
            self._command(session, "advance")
        self.assertEqual(len(captured), 1)
        public_state, actor_view = captured[0]
        self.assertEqual(actor_view["self"], "P2")
        self.assertEqual(actor_view["role"], "MERLIN")
        self.assertEqual(set(actor_view["known_evil"]), {"P3", "P4"})
        self.assertEqual(public_state.team, ["P2", "P3"])
        self.assertEqual(public_state.events,
                         session.game.chronicle.reader().observations_since(0))
        self.assertEqual(session.snapshot()["public_events"], public_before)
        self.assertNotIn("ballots", session.snapshot())
        self.assertEqual(set(session.ballots), {"P1", "P2"})
        self.assertFalse(any(e["kind"] in {"VOTE", "TEAM_VOTE"}
                             for e in session.game.events))

    def test_v5_policy_failure_does_not_commit_a_vote_or_advance_state(self):
        session, _ = self._to_vote(["P2", "P3"], policy="v5")
        self._command(session, "vote", {"approve": True})
        revision_before = session.revision
        events_before = deepcopy(session.game.events)
        ballots_before = deepcopy(session.ballots)
        with patch.object(v5, "candidate_vote_decision", side_effect=ValueError("invalid V5 input")):
            failed = self._command(session, "advance", ok=False)
        self.assertTrue(failed["state"]["retry_ai"])
        self.assertEqual(session.revision, revision_before)
        self.assertEqual(session.game.phase, "vote")
        self.assertEqual(session.game.events, events_before)
        self.assertEqual(session.ballots, ballots_before)


if __name__ == "__main__":
    unittest.main()
