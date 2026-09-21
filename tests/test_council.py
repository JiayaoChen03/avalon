"""Safety, post-mission councils, sealed three-way ballots and life continuity."""

from copy import deepcopy
import json
import unittest

from avalon.agents import Agent
from avalon.engine import EXILE_CHOICES, public_evidence, validate_social
from avalon.evil_strategy import EvilStrategyManager
from avalon.llm import LLMError
from avalon.terminal import Human
from test_agents import SequenceClient
from test_engine import approve, finish_council, fixed_game
import test_gui


def mission(game, fail=False):
    team = ["P3"] + [p for p in game.ids if p != "P3"][:game.team_size - 1]
    approve(game, team)
    game.resolve_mission({p: "FAIL" if p == "P3" and fail else "SUCCESS" for p in team})


def nominate(game, target=None):
    while game.phase == "council_discussion":
        game.act(game.next_actor, {"kind": "PASS"})
    game.nominate_exile(game.leader, target or game.exile_candidates()[0])


class CouncilRulesTests(unittest.TestCase):
    def test_mission_enters_separate_discussion_without_rotating_or_refreshing(self):
        game = fixed_game()
        self.assertFalse(game.safe_round)
        mission(game)
        self.assertEqual((game.phase, game.round, game.leader), ("council_discussion", 1, "P1"))
        self.assertEqual(game.resolve, dict.fromkeys(game.ids, 2))
        self.assertFalse(game.spoken)
        self.assertEqual(game.view("P1")["focused_events"][0]["kind"], "MISSION")
        before = deepcopy(vars(game))
        with self.assertRaises(ValueError):
            game.nominate_exile("P1", "P2")
        self.assertEqual(vars(game), before)
        nominate(game, "P2")
        self.assertEqual(game.phase, "exile_vote")
        self.assertEqual(game.resolve, dict.fromkeys(game.ids, 2))

    def test_council_response_and_hold_windows_return_to_council(self):
        game = fixed_game()
        mission(game)
        ref = next(e["record_id"] for e in game.events if e["kind"] == "MISSION")
        game.act("P1", {"kind": "HOLD"})
        game.act("P2", {"kind": "CHALLENGE", "target": "P3", "evidence": ref})
        game.act("P3", {"kind": "DECLINE"})
        self.assertEqual((game.phase, game.next_actor), ("reaction", "P1"))
        game.act("P1", {"kind": "REACT", "social": {"card": "HEDGE", "target": "P2", "reason": "observe"}})
        self.assertEqual((game.phase, game.next_actor), ("council_discussion", "P3"))
        nominate(game)
        self.assertEqual(game.phase, "exile_vote")
        self.assertEqual(game.pending_reactions, set())

    def test_unsafe_deaths_retain_council_rights_but_cannot_be_nominated(self):
        game = fixed_game()
        mission(game, fail=True)
        self.assertFalse(game.lives["P1"]["alive"])
        self.assertEqual(game.next_actor, "P1")
        self.assertNotIn("P1", game.exile_candidates())
        while game.phase == "council_discussion":
            game.act(game.next_actor, {"kind": "PASS"})
        before = deepcopy(vars(game))
        for actor, target in (("P2", "P2"), ("P1", "P1"), ("P1", "P9")):
            with self.assertRaises(ValueError):
                game.nominate_exile(actor, target)
            self.assertEqual(vars(game), before)
        game.nominate_exile("P1", "P2")
        game.vote_exile(dict.fromkeys(game.ids, "ABSTAIN"))
        self.assertEqual(sum(e["kind"] == "EXILE_VOTE" for e in game.events), 5)

    def test_majority_uses_all_seats_even_with_abstentions_and_ties(self):
        for count, yes, no, passed in ((5, 2, 0, False), (5, 3, 0, True), (5, 0, 0, False),
                                       (6, 3, 3, False), (6, 3, 0, False), (6, 4, 0, True)):
            with self.subTest(count=count, yes=yes, no=no):
                game = fixed_game(count)
                mission(game)
                nominate(game, "P2")
                values = ["APPROVE"] * yes + ["REJECT"] * no + ["ABSTAIN"] * (count - yes - no)
                game.vote_exile(dict(zip(game.ids, values)))
                result = next(e for e in reversed(game.events) if e["kind"] == "EXILE_RESULT")
                self.assertEqual(result["exiled"], passed)
                self.assertEqual(result["required_approvals"], count // 2 + 1)
                self.assertEqual(result["counts"], dict(APPROVE=yes, REJECT=no, ABSTAIN=count - yes - no))
                self.assertEqual(game.lives["P2"]["alive"], not passed)
                self.assertEqual(game.phase, "council_result")

    def test_invalid_or_repeated_ballots_never_partially_publish_or_kill(self):
        game = fixed_game()
        mission(game)
        nominate(game)
        before = deepcopy(vars(game))
        for votes in (None, {}, {"P1": "APPROVE"}, dict.fromkeys(game.ids, True),
                      dict.fromkeys(game.ids, "approve"), {**dict.fromkeys(game.ids, "APPROVE"), "P5": []}):
            with self.assertRaises(ValueError):
                game.vote_exile(votes)
            self.assertEqual(vars(game), before)
        game.vote_exile(dict.fromkeys(game.ids, "APPROVE"))
        completed = deepcopy(vars(game))
        with self.assertRaises(ValueError):
            game.vote_exile(dict.fromkeys(game.ids, "REJECT"))
        self.assertEqual(vars(game), completed)

    def test_every_vote_grants_next_round_safety_and_safe_failure_still_scores(self):
        for exiled in (False, True):
            game = fixed_game()
            mission(game)
            roles = {p: game.players[p].role for p in game.ids}
            finish_council(game, target="P2", votes=dict.fromkeys(game.ids, "APPROVE" if exiled else "ABSTAIN"))
            self.assertTrue(game.safe_round)
            self.assertEqual((game.round, game.leader), (2, "P2"))
            self.assertEqual(game.lives["P2"], {"life": 2 if exiled else 1, "alive": True})
            self.assertEqual(roles, {p: game.players[p].role for p in game.ids})
            start = len(game.events)
            mission(game, fail=True)
            self.assertEqual(game.failures, 1)
            self.assertFalse(any(e["kind"] == "DEATH" for e in game.events[start:]))
            self.assertTrue(game.missions[-1]["safe_round"])
            finish_council(game)
            self.assertTrue(game.safe_round)
            self.assertEqual(game.resolve, dict.fromkeys(game.ids, 3))

    def test_safe_round_does_not_prevent_exile_and_memory_survives_rebirth(self):
        game = fixed_game()
        mission(game)
        finish_council(game)
        agent = Agent(game.view("P5"), chronicle=game.chronicle.reader())
        mission(game, fail=True)
        nominate(game, "P5")
        votes = {"P1": "APPROVE", "P2": "APPROVE", "P3": "APPROVE", "P4": "REJECT", "P5": "ABSTAIN"}
        game.vote_exile(votes)
        for event in game.events:
            agent.observe(event)
        self.assertFalse(agent.long_term.alive)
        self.assertIn("exile", agent.long_term.lives[-1]["summary"])
        self.assertLess(agent.long_term.relationships["P1"]["trust"], 0)
        self.assertGreater(agent.long_term.relationships["P4"]["trust"], 0)
        event = next(e for e in game.events if e["kind"] == "EXILE_VOTE" and e["target"] == "P5")
        self.assertEqual(public_evidence(game.chronicle.reader(), event["record_id"]), event)
        validate_social({"card": "ACCUSE", "target": "P1", "reason": "vote_pattern",
                         "public_writing": "这张出局票需要解释。", "citations": [event["record_id"]]},
                        game.ids, game.chronicle.reader())
        game.finish_council()
        for event in game.events:
            agent.observe(event)
        self.assertTrue(agent.long_term.alive)
        self.assertEqual(agent.long_term.life, 2)
        self.assertTrue(any(s["type"] == "voted_to_exile" for s in agent.long_term.scars))

    def test_decisive_mission_also_has_council_before_victory_or_assassination(self):
        for fail in (False, True):
            game = fixed_game()
            for _ in range(2):
                mission(game, fail=fail)
                finish_council(game)
            mission(game, fail=fail)
            self.assertIsNone(game.winner)
            self.assertEqual(game.phase, "council_discussion")
            finish_council(game, target="P2", votes=dict.fromkeys(game.ids, "APPROVE"))
            if fail:
                self.assertEqual(game.winner, "EVIL")
            else:
                self.assertEqual(game.phase, "assassination")
                game.assassinate("P3", "P2")
                self.assertEqual(game.winner, "EVIL")
                self.assertEqual(sum(e["kind"] == "DEATH" and e["target"] == "P2" for e in game.events), 1)
            self.assertEqual(sum(e["kind"] == "EXILE_RESULT" for e in game.events), 3)


class CouncilAgentTests(unittest.TestCase):
    def test_tiny_schemas_retry_in_place_and_keep_bounded_private_context(self):
        game = fixed_game()
        mission(game)
        while game.phase == "council_discussion":
            game.act(game.next_actor, {"kind": "PASS"})
        client = SequenceClient([{"target": "P99"}, {"target": "P2"}])
        agent = Agent(game.view("P1"), client, max_retries=1, retry_delay=0, chronicle=game.chronicle.reader())
        before = deepcopy(game.events)
        self.assertEqual(agent.council_decision(), {"target": "P2"})
        self.assertEqual(agent.council_decision(), {"target": "P2"})
        self.assertEqual(len(client.contexts), 2)
        self.assertEqual(game.events, before)
        self.assertEqual(client.contexts[-1]["decision"], "exile_nomination")
        self.assertIn("validation_feedback", client.contexts[-1])
        game.nominate_exile("P1", "P2")
        for choice in EXILE_CHOICES:
            seat = Agent(game.view("P5"), SequenceClient([{"choice": choice}]), max_retries=0)
            self.assertEqual(seat.council_decision(), {"choice": choice})
            self.assertEqual(seat.client.contexts[0]["game"]["known_evil"], [])
        invalid = Agent(game.view("P5"), SequenceClient([{"approve": True}]), max_retries=0)
        with self.assertRaisesRegex(LLMError, "invalid_plan"):
            invalid.council_decision()

    def test_managed_evil_can_cast_three_way_vote_without_exposing_tactics(self):
        game = fixed_game()
        mission(game)
        nominate(game)
        manager = EvilStrategyManager(game.ids, {"P3", "P4"}, seed=0)
        agent = Agent(game.view("P3"), SequenceClient([{"choice": "REJECT"}]), evil_strategy=manager)
        self.assertEqual(agent.council_decision(), {"choice": "REJECT"})
        self.assertIn("tactical", agent.client.contexts[0])
        self.assertNotIn("tactical", json.dumps(game.events))

    def test_terminal_uses_three_choices_and_empty_input_abstains(self):
        game = fixed_game()
        mission(game)
        nominate(game)
        for answer, expected in (("a", "APPROVE"), ("r", "REJECT"), ("b", "ABSTAIN"), ("", "ABSTAIN")):
            human = Human(game.view("P1"), input_fn=lambda _: answer, write=lambda _: None)
            self.assertEqual(human.council_decision(), {"choice": expected})


class CouncilBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.h = test_gui.GUITests()
        self.h.setUp()
        self.game = self.h.start()
        mission(self.game)
        self.h.session._flush()

    def to_ballot(self):
        while self.game.phase == "council_discussion":
            self.game.act(self.game.next_actor, {"kind": "PASS"})
        self.h.session._flush()
        self.h.request("nominate_exile", {"target": "P2"})

    def test_ballots_are_sealed_until_complete_and_abstention_is_visible_afterwards(self):
        self.to_ballot()
        state = self.h.request("exile_vote", {"choice": "ABSTAIN"})
        self.assertTrue(state["vote_submitted"])
        self.assertFalse(any(e["kind"] == "EXILE_VOTE" for e in state["public_events"]))
        self.assertIsNone(state["result"])
        self.h.request("exile_vote", {"choice": "APPROVE"}, ok=False)
        self.assertEqual(self.h.session.exile_ballots["P1"], "ABSTAIN")
        self.h.finish_council()
        state = self.h.session.snapshot()
        self.assertEqual(state["phase"], "EXILE_RESULT")
        self.assertEqual(state["result"]["counts"]["ABSTAIN"], 5)
        state = self.h.request("continue")
        self.assertTrue(state["safe_round"])
        self.assertEqual(state["phase"], "TEAM_DRAFT")

    def test_exile_result_shows_death_before_continue_rebirth_and_ai_retry_keeps_ballots(self):
        self.to_ballot()
        self.h.request("exile_vote", {"choice": "APPROVE"})
        self.h.client.error = LLMError("timeout")
        state = self.h.request("advance", ok=False)
        self.assertTrue(state["retry_ai"])
        self.assertEqual(self.h.session.exile_ballots, {"P1": "APPROVE"})
        self.h.client.error = None
        self.h.request("retry")
        self.h.session.exile_ballots.update(dict.fromkeys(self.game.ids[1:], "APPROVE"))
        self.h.session._finish_exile_vote()
        self.h.session._flush()
        state = self.h.session.snapshot()
        self.assertFalse(next(p for p in state["players"] if p["id"] == "P2")["alive"])
        self.assertEqual(state["result"]["counts"]["APPROVE"], 5)
        state = self.h.request("continue")
        player = next(p for p in state["players"] if p["id"] == "P2")
        self.assertTrue(player["alive"])
        self.assertEqual(player["life"], 2)
