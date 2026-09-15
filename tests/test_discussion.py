from copy import deepcopy
import io
import json
import unittest
from unittest.mock import patch

from avalon.agents import Agent, validate_plan
from avalon.engine import Game, make_players
from avalon.llm import LLMError
from avalon.terminal import Human, run_game
from test_agents import FixedClient, valid_plan
from test_engine import fixed_game, discuss


class DiscussionTests(unittest.TestCase):
    def test_first_model_context_has_no_invented_player_history(self):
        view = fixed_game().view("P1")
        client = FixedClient(valid_plan(view))
        agent = Agent(view, client)
        agent.prepare(view)
        context = client.contexts[0]
        self.assertEqual(context["memory"], {"beliefs": {}, "profiles": {}})
        self.assertEqual(context["memory_status"], "no_previous_model")
        self.assertEqual(context["evidence"], [])
        self.assertEqual(context["game"]["missions"], [])

    def test_later_speakers_receive_actual_earlier_statements(self):
        game = fixed_game()
        human = Human(game.view("P1"), input_fn=lambda _: "", write=lambda _: None)
        clients = {p: FixedClient(valid_plan(game.view(p))) for p in game.ids if p != "P1"}
        agents = {p: Agent(game.view(p), client) for p, client in clients.items()}
        run_game(game, agents, human, write=lambda _: None)
        context = clients["P3"].contexts[0]
        earlier = [e["actor"] for e in context["game"]["recent_events"] if e["kind"] == "SOCIAL"]
        self.assertEqual(earlier, ["P1", "P2"])
        self.assertEqual(context["game"]["team"], ["P1", "P2"])

    def test_live_plan_never_uses_mock_as_a_starting_plan(self):
        view = fixed_game().view("P1")
        plan = valid_plan(view)
        plan["social"].update(statement="开局先打个招呼，我想听听大家准备怎么组队。",
                              rationale="目前没有任务或投票记录，我先观察。", evidence=[])
        agent = Agent(view, FixedClient(plan))
        with patch.object(agent, "_mock_plan", side_effect=AssertionError("Unexpected mock plan")):
            self.assertEqual(agent.prepare(view), "llm")
        self.assertEqual(agent.social_action()["statement"], plan["social"]["statement"])

    def test_fallback_estimates_are_not_presented_as_model_history(self):
        view = fixed_game().view("P1")
        client = FixedClient(error=LLMError("timeout"))
        agent = Agent(view, client)
        self.assertEqual(agent.prepare(view), "fallback:timeout")
        client.error, client.response = None, valid_plan(view)
        view["round"] = 2
        self.assertEqual(agent.prepare(view), "llm")
        self.assertEqual(client.contexts[-1]["memory"], {"beliefs": {}, "profiles": {}})

    def test_public_summary_drops_private_role_disclosures_without_another_call(self):
        view = fixed_game().view("P3")
        for field, disclosure in (("rationale", "作为邪恶方，先保持中立并收集信息。"),
                                  ("statement", "我是刺客，P4 是我的同伴。"),
                                  ("rationale", "As an evil player, I want to hide my role."),
                                  ("rationale", "我的角色是刺客，P3 是我的同伴。"),
                                  ("rationale", "I am on the evil team with P3.")):
            plan = valid_plan(view)
            plan["social"][field] = disclosure
            agent = Agent(view, FixedClient(plan))
            self.assertEqual(agent.prepare(view), "llm")
            self.assertNotIn(disclosure, json.dumps(agent.social_action(), ensure_ascii=False))
            self.assertTrue(agent.social_action()[field])
            self.assertEqual(agent.plan["team_rank"], plan["team_rank"])
            self.assertEqual(agent.calls, {1: 1})

    def test_direction_is_announced_before_round_and_fixes_speaking_order(self):
        for direction, expected in (("clockwise", ["P1", "P2", "P3", "P4", "P5"]),
                                    ("counterclockwise", ["P1", "P5", "P4", "P3", "P2"])):
            game = Game(make_players(5, 7), seed=0, direction=direction)
            self.assertEqual(game.speaking_order, expected)
            kinds = [e["kind"] for e in game.events]
            self.assertLess(kinds.index("DIRECTION"), kinds.index("ROUND"))
            self.assertEqual(game.view("P3")["speaking_direction"], direction)
            game.propose(game.leader, ["P1", "P2"])
            discuss(game)
            self.assertEqual([e["actor"] for e in game.events if e["kind"] == "SOCIAL"], expected)
            game.vote({p: False for p in game.ids})
            self.assertEqual(game.leader, "P2")
            self.assertEqual(game.speaking_order, expected[1:] + expected[:1] if direction == "clockwise"
                             else ["P2", "P1", "P5", "P4", "P3"])
            self.assertEqual(game.direction, direction)

    def test_engine_rejects_out_of_order_speech_without_partial_state(self):
        game = fixed_game()
        game.propose(game.leader, ["P1", "P2"])
        events = deepcopy(game.events)
        with self.assertRaises(ValueError):
            game.social("P2", {"card": "BAIT", "target": "P1", "reason": "test_reaction"})
        self.assertEqual(game.events, events)
        self.assertEqual(game.spoken, set())

    def test_seeded_direction_is_reproducible_and_separate_from_roles(self):
        for count in (5, 6):
            roles_by_direction = {"clockwise": set(), "counterclockwise": set()}
            for seed in range(100):
                players = make_players(count, seed)
                game = Game(players, seed=seed)
                self.assertEqual(game.direction, Game(players, seed=seed).direction)
                roles_by_direction[game.direction].add(players[-1].role)
            for roles in roles_by_direction.values():
                self.assertEqual(roles, {"GOOD", "MERLIN", "ASSASSIN", "EVIL"})

    def test_statement_validation_rejects_controls_and_fabricated_evidence(self):
        game = fixed_game()
        game.propose(game.leader, ["P1", "P2"])
        view = game.view("P1")
        valid = valid_plan(view)
        valid["social"].update(statement="先观察本次队伍。", rationale="目前只有组队信息。",
                              evidence=[game.events[-1]["seq"]])
        self.assertEqual(validate_plan(valid, game.ids, game.events), valid)
        for key, value in (("statement", "\x1b[2J"), ("rationale", "隐藏\n[REVEAL]"),
                           ("statement", "x" * 241), ("rationale", ""),
                           ("evidence", [99999]), ("evidence", [True])):
            bad = deepcopy(valid)
            bad["social"][key] = value
            with self.assertRaises(ValueError, msg=key):
                validate_plan(bad, game.ids, game.events)
        valid["social"]["reason"] = "vote_pattern"
        with self.assertRaises(ValueError):
            validate_plan(valid, game.ids, game.events)

    def test_repeated_or_long_valid_citation_lists_do_not_replace_live_decisions(self):
        game = fixed_game()
        game.propose(game.leader, ["P1", "P2"])
        discuss(game)
        plan = valid_plan(game.view("P1"))
        refs = [e["seq"] for e in game.events if e["kind"] in {"TEAM", "SOCIAL"}]
        plan["social"]["evidence"] = refs + refs
        agent = Agent(game.view("P1"), FixedClient(plan))
        self.assertEqual(agent.prepare(game.view("P1")), "llm")
        self.assertEqual(agent.social_action()["evidence"], refs[:3])
        self.assertEqual(agent.social_action()["statement"], plan["social"]["statement"])
        self.assertEqual(agent.calls, {1: 1})

    def test_history_reason_must_cite_a_record_of_that_kind(self):
        game = fixed_game()
        game.propose(game.leader, ["P1", "P2"])
        team_seq = game.events[-1]["seq"]
        discuss(game)
        game.vote({p: True for p in game.ids})
        game.resolve_mission({"P1": "SUCCESS", "P2": "SUCCESS"})
        plan = valid_plan(game.view("P1"))
        plan["social"].update(reason="mission_record", evidence=[team_seq])
        with self.assertRaises(ValueError):
            validate_plan(plan, game.ids, game.events)
        mission_seq = next(e["seq"] for e in game.events if e["kind"] == "MISSION")
        plan["social"]["evidence"] = [mission_seq]
        self.assertEqual(validate_plan(plan, game.ids, game.events)["social"]["evidence"], [mission_seq])

    def test_all_proposals_print_statements_and_keep_one_call_per_mission(self):
        game = Game(make_players(6, 12), seed=12, direction="counterclockwise")
        clients = {p: FixedClient(valid_plan(game.view(p))) for p in game.ids}
        agents = {p: Agent(game.view(p), client) for p, client in clients.items()}
        output, log = [], io.StringIO()
        run_game(game, agents, write=output.append, log=log)
        text = "\n".join(output)
        self.assertIn("逆时针", text)
        self.assertIn("表态：", text)
        self.assertIn("理由摘要：", text)
        for event in game.events:
            if event["kind"] in {"SOCIAL", "TEAM", "VOTE", "MISSION"}:
                self.assertIn(f"[#{event['seq']}] [{event['kind']}]", text)
        self.assertNotIn("chain_of_thought", text)
        for proposal in (e for e in game.events if e["kind"] == "TEAM"):
            same = [e for e in game.events if e["round"] == proposal["round"]
                    and e["attempt"] == proposal["attempt"] and e["kind"] == "SOCIAL"]
            start = game.ids.index(proposal["actor"])
            self.assertEqual([e["actor"] for e in same],
                             [game.ids[(start - n) % 6] for n in range(6)])
            self.assertTrue(all(e["statement"] and e["rationale"] for e in same))
        self.assertTrue(all(set(a.calls.values()) == {1} for a in agents.values()))
        self.assertEqual(json.loads(log.getvalue().splitlines()[-2])["kind"], "RESULT")
