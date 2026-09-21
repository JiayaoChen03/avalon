"""Resolve rules, lifecycle, controller parity and sealed public information."""

from copy import deepcopy
import io
import json
import unittest

from avalon.agents import Agent
from avalon.engine import MAX_RESOLVE, RESOLVE_COSTS, Game, make_players
from avalon.evil_strategy import EvilStrategyManager
from avalon.llm import LLMError, RESOLVE_PROTOCOL
from avalon.terminal import Human, format_event, run_game
from test_agents import FixedClient, SequenceClient, model_response, valid_plan
from test_engine import fixed_game, finish_council


def social(target="P2"):
    return {"card": "PRESSURE", "target": target, "reason": "observe"}


def finish_discussion(game, lock=True):
    while game.phase in {"discussion", "challenge", "reaction"}:
        kind = {"discussion": "PASS", "challenge": "DECLINE", "reaction": "SKIP"}[game.phase]
        game.act(game.next_actor, {"kind": kind})
    if lock:
        game.act(game.leader, {"kind": "LOCK"})


def resource_plan(view, kind="PASS", **fields):
    return {**valid_plan(view), "discussion": {"kind": kind, **fields},
            "revision": {"kind": "LOCK"}, "strong_vote": False}


class ResolveRulesTests(unittest.TestCase):
    def setUp(self):
        self.game = fixed_game()
        self.game.propose("P1", ["P1", "P2"])

    def assertAtomic(self, call):
        before = deepcopy(vars(self.game))
        with self.assertRaises(ValueError):
            call()
        self.assertEqual(vars(self.game), before)

    def test_initialization_public_balances_and_costs_are_copies(self):
        self.assertEqual(MAX_RESOLVE, 3)
        self.assertEqual(self.game.resolve, dict.fromkeys(self.game.ids, 3))
        for pid in self.game.ids:
            view = self.game.view(pid)
            self.assertEqual(view["resolve"], self.game.resolve)
            self.assertEqual(view["max_resolve"], 3)
            view["resolve"]["P1"] = 99
            view["resolve_costs"]["SOCIAL"] = 0
            self.assertEqual(self.game.resolve["P1"], 3)
            self.assertEqual(RESOLVE_COSTS["SOCIAL"], 1)
            self.assertNotIn("role", json.dumps(view["players"]))

    def test_social_and_commit_use_exact_costs_and_public_metadata(self):
        for committed, remaining, cost in ((False, 2, 1), (True, 1, 2)):
            game = fixed_game()
            game.propose("P1", ["P1", "P2"])
            game.social("P1", social(), committed=committed)
            self.assertEqual(game.resolve["P1"], remaining)
            event = game.events[-1]
            self.assertEqual((event["kind"], event["committed"], event["resolve_cost"], event["resolve_after"]),
                             ("SOCIAL", committed, cost, remaining))

    def test_pass_is_free_completes_turn_and_works_at_zero(self):
        self.game.resolve["P1"] = 0
        self.assertEqual(self.game.view("P1")["legal_actions"], ["PASS"])
        self.game.act("P1", {"kind": "PASS"})
        self.assertIn("P1", self.game.spoken)
        self.assertEqual(self.game.next_actor, "P2")
        self.assertEqual(self.game.resolve["P1"], 0)
        self.assertEqual(self.game.events[-1]["resolve_cost"], 0)

    def test_rejected_proposals_keep_balances_missions_refresh_without_carryover(self):
        game = self.game
        game.social("P1", social(), committed=True)
        finish_discussion(game)
        game.vote(dict.fromkeys(game.ids, False))
        self.assertEqual((game.round, game.attempt, game.resolve["P1"]), (1, 2, 1))
        self.assertEqual(sum(e["kind"] == "RESOLVE_REFRESH" for e in game.events), 1)
        game.propose(game.leader, ["P1", "P2"])
        while game.next_actor != "P1":
            game.act(game.next_actor, {"kind": "PASS"})
        game.social("P1", social())
        finish_discussion(game)
        self.assertEqual(game.resolve["P1"], 0)
        game.vote(dict.fromkeys(game.ids, True))
        game.resolve_mission(dict.fromkeys(game.team, "SUCCESS"))
        finish_council(game)
        self.assertEqual(game.round, 2)
        self.assertEqual(game.resolve, dict.fromkeys(game.ids, 3))
        self.assertEqual(game.events[-1]["kind"], "RESOLVE_REFRESH")

    def test_overspend_and_invalid_actions_are_fully_atomic(self):
        for action in ({"kind": "SOCIAL", "social": social("P99")},
                       {"kind": "SOCIAL", "social": {**social(), "card": "OTHER"}},
                       {"kind": "CITE", "evidence": 99999},
                       {"kind": "CITE", "evidence": True},
                       {"kind": "CITE", "evidence": 1},
                       {"kind": "HOLD", "resolve_cost": 0},
                       {"kind": "COMMIT"}, {"kind": "REACT", "social": social()},
                       {"kind": "CHALLENGE", "target": "P1", "evidence": self.game.events[-1]["seq"]}):
            self.assertAtomic(lambda: self.game.act("P1", action))
        self.assertAtomic(lambda: self.game.act("P2", {"kind": "PASS"}))
        self.game.resolve["P1"] = 0
        for kind in ("SOCIAL", "COMMITTED_SOCIAL"):
            self.assertAtomic(lambda: self.game.act("P1", {"kind": kind, "social": social()}))

    def test_spending_api_rejects_invalid_amounts_players_and_balances(self):
        for amount in (-1, 1.5, True, "1", 4):
            self.assertAtomic(lambda: self.game._spend_resolve("P1", amount))
        self.assertAtomic(lambda: self.game._spend_resolve("P99", 0))
        self.assertAtomic(lambda: self.game._spend_resolve([], 0))
        for balance in (-1, 4, True):
            self.game.resolve["P1"] = balance
            self.assertAtomic(lambda: self.game._spend_resolve("P1", 0))

    def test_challenge_validates_target_and_public_evidence_before_payment(self):
        game = self.game
        team_seq = game.events[-1]["seq"]
        self.assertAtomic(lambda: game.act("P1", {"kind": "CHALLENGE", "target": "P5", "evidence": team_seq}))
        for kind in ("MISSION_SUBMIT", "REVEAL", "PRIVATE_STRATEGY"):
            game._emit(kind, actor="P2", cards={"P2": "FAIL"}, role="MERLIN")
            self.assertAtomic(lambda: game.act("P1", {"kind": "CHALLENGE", "target": "P2", "evidence": game.events[-1]["seq"]}))
        game.act("P1", {"kind": "CHALLENGE", "target": "P2", "evidence": team_seq})
        self.assertEqual((game.phase, game.next_actor, game.resolve["P1"]), ("challenge", "P2", 2))
        self.assertAtomic(lambda: game.social("P2", social()))
        self.assertAtomic(lambda: game.act("P1", {"kind": "DECLINE"}))
        self.assertAtomic(lambda: game.act("P2", {"kind": "CHALLENGE", "target": "P1", "evidence": team_seq}))
        game.act("P2", {"kind": "RESPOND", "social": social("P1")})
        self.assertEqual(game.resolve["P2"], 2)
        self.assertEqual((game.phase, game.next_actor), ("discussion", "P2"))
        self.assertFalse(game.events[-1]["declined"])
        self.assertEqual(game.events[-1]["challenger"], "P1")
        self.assertNotIn("P2", game.spoken)

    def test_decline_is_public_free_and_available_at_zero(self):
        game = self.game
        game.act("P1", {"kind": "CHALLENGE", "target": "P2", "evidence": game.events[-1]["seq"]})
        game.resolve["P2"] = 0
        self.assertEqual(game.view("P2")["legal_actions"], ["DECLINE"])
        self.assertAtomic(lambda: game.act("P2", {"kind": "RESPOND", "social": social()}))
        game.act("P2", {"kind": "DECLINE"})
        self.assertTrue(game.events[-1]["declined"])
        self.assertEqual(game.events[-1]["resolve_after"], 0)

    def test_hold_react_is_prepaid_once_and_cannot_open_a_chain(self):
        game = self.game
        game.act("P1", {"kind": "HOLD"})
        self.assertEqual(game.resolve["P1"], 2)
        self.assertEqual(game.next_actor, "P2")
        self.assertAtomic(lambda: game.act("P1", {"kind": "REACT", "social": social()}))
        game.act("P2", {"kind": "HOLD"})
        self.assertEqual(game.reaction_queue, ["P1"])
        self.assertAtomic(lambda: game.act("P2", {"kind": "REACT", "social": social()}))
        game.act("P1", {"kind": "REACT", "social": social()})
        self.assertEqual(game.resolve["P1"], 2)
        self.assertEqual(game.events[-1]["resolve_cost"], 0)
        self.assertEqual((game.phase, game.next_actor), ("discussion", "P3"))
        self.assertEqual(game.pending_reactions, {"P2"})
        self.assertAtomic(lambda: game.act("P1", {"kind": "REACT", "social": social()}))

    def test_skip_retains_hold_and_multiple_holders_follow_speaking_order(self):
        for direction in ("clockwise", "counterclockwise"):
            game = Game(make_players(5, 0), seed=0, direction=direction)
            game.propose(game.leader, game.ids[:2])
            first, second, third = game.speaking_order[:3]
            game.act(first, {"kind": "HOLD"})
            game.act(second, {"kind": "HOLD"})
            game.act(first, {"kind": "SKIP"})
            game.act(third, {"kind": "PASS"})
            self.assertEqual(game.reaction_queue, [first, second])
            game.resolve[first] = 0  # A prepaid reaction needs no further balance.
            game.act(first, {"kind": "REACT", "social": social()})
            self.assertEqual(game.next_actor, second)
            game.act(second, {"kind": "REACT", "social": social()})
            self.assertEqual(game.phase, "discussion")

    def test_challenge_response_precedes_holds_without_triggering_new_windows(self):
        game = self.game
        seq = game.events[-1]["seq"]
        game.act("P1", {"kind": "HOLD"})
        game.act("P2", {"kind": "CHALLENGE", "target": "P1", "evidence": seq})
        self.assertEqual((game.phase, game.next_actor), ("challenge", "P1"))
        game.act("P1", {"kind": "RESPOND", "social": social()})
        self.assertEqual((game.phase, game.reaction_queue), ("reaction", ["P1"]))
        game.act("P1", {"kind": "REACT", "social": social()})
        self.assertEqual(game.resolve["P1"], 1)
        self.assertEqual((game.phase, game.next_actor), ("discussion", "P3"))

    def test_unused_holds_expire_and_voting_requires_resolved_windows_and_lock(self):
        game = self.game
        game.act("P1", {"kind": "HOLD"})
        game.act("P2", {"kind": "PASS"})
        self.assertAtomic(lambda: game.vote(dict.fromkeys(game.ids, True)))
        finish_discussion(game, lock=False)
        self.assertEqual(game.pending_reactions, set())
        self.assertEqual(game.resolve["P1"], 2)
        self.assertEqual(game.events[-1]["expired_reactions"], ["P1"])
        self.assertAtomic(lambda: game.vote(dict.fromkeys(game.ids, True)))
        self.assertAtomic(lambda: game.act("P1", {"kind": "REACT", "social": social()}))
        game.act("P1", {"kind": "LOCK"})
        game.vote(dict.fromkeys(game.ids, False))
        game.propose(game.leader, ["P1", "P2"])
        self.assertEqual(game.pending_reactions, set())

    def test_last_speaker_hold_expires_without_ever_reacting(self):
        game = self.game
        for pid in game.speaking_order[:-1]:
            game.act(pid, {"kind": "PASS"})
        game.act("P5", {"kind": "HOLD"})
        self.assertEqual(game.phase, "revision")
        self.assertEqual(game.resolve["P5"], 2)
        self.assertEqual(game.events[-1]["expired_reactions"], ["P5"])

    def test_revision_is_leader_only_one_swap_once_after_discussion(self):
        game = self.game
        revision = {"kind": "REVISE", "removed": "P2", "added": "P3"}
        self.assertAtomic(lambda: game.act("P1", revision))
        finish_discussion(game, lock=False)
        self.assertAtomic(lambda: game.act("P2", revision))
        self.assertAtomic(lambda: game.act("P1", {**revision, "added": "P1"}))
        self.assertAtomic(lambda: game.act("P1", {**revision, "removed": "P5"}))
        game.resolve["P1"] = 0
        self.assertAtomic(lambda: game.act("P1", revision))
        game.resolve["P1"] = 1
        game.act("P1", revision)
        self.assertEqual((game.team, game.phase, game.resolve["P1"]), (["P1", "P3"], "vote", 0))
        self.assertEqual(game.events[-1]["kind"], "TEAM_REVISE")
        self.assertAtomic(lambda: game.act("P1", {"kind": "REVISE", "removed": "P3", "added": "P2"}))
        self.assertAtomic(lambda: game.social("P2", social()))

    def test_strong_ballots_pay_once_and_still_have_one_vote_each(self):
        game = self.game
        finish_discussion(game)
        votes = {p: p in {"P1", "P2"} for p in game.ids}
        strong = {p: votes[p] for p in game.ids}
        game.vote(votes, strong=strong)
        self.assertEqual(game.phase, "team")  # Two strong approvals cannot beat three rejects.
        self.assertEqual(game.resolve["P1"], 2)
        self.assertEqual(game.resolve["P3"], 3)
        revealed = [e for e in game.events if e["kind"] == "VOTE"]
        self.assertEqual(len(revealed), 5)
        self.assertEqual(sum(e["approve"] for e in revealed), 2)
        self.assertTrue(revealed[0]["strong"])

    def test_invalid_batch_ballots_never_spend_or_reveal_partial_votes(self):
        game = self.game
        finish_discussion(game)
        votes = dict.fromkeys(game.ids, True)
        game.resolve["P5"] = 0
        self.assertAtomic(lambda: game.vote(votes, strong=dict.fromkeys(game.ids, True)))
        self.assertAtomic(lambda: game.vote(votes, strong={"P1": True}))
        self.assertAtomic(lambda: game.vote(votes, strong=dict.fromkeys(game.ids, 1)))
        self.assertAtomic(lambda: game.vote(votes, reasons=dict.fromkeys(game.ids, "bad")))

    def test_cite_old_evidence_focuses_original_without_mutating_history(self):
        game = self.game
        original = deepcopy(game.events[-1])
        finish_discussion(game)
        game.vote(dict.fromkeys(game.ids, False))
        game.propose(game.leader, ["P1", "P2"])
        finish_discussion(game)
        game.vote(dict.fromkeys(game.ids, False))
        game.propose(game.leader, ["P1", "P2"])
        self.assertNotIn(original, game.view(game.leader)["recent_events"])
        game.act(game.leader, {"kind": "CITE", "evidence": original["seq"]})
        self.assertEqual(game.view("P4")["focused_events"], [original])
        self.assertEqual(game.events[original["seq"]-1], original)
        self.assertEqual(sum(e["seq"] == original["seq"] for e in game.events), 1)
        self.assertEqual(game.resolve[game.leader], 2)

    def test_zero_resolve_preserves_all_core_actions_through_game_end(self):
        game = fixed_game()
        for _ in range(3):
            game.resolve = dict.fromkeys(game.ids, 0)
            team = ["P1", "P2", "P5"][:game.team_size]
            game.propose(game.leader, team)
            finish_discussion(game)
            game.vote(dict.fromkeys(game.ids, True))
            game.resolve_mission(dict.fromkeys(game.team, "SUCCESS"))
            finish_council(game)
        self.assertEqual(game.phase, "assassination")
        game.assassinate("P3", "P1")
        self.assertEqual(game.winner, "GOOD")


class ResolveControllerTests(unittest.TestCase):
    def test_complete_games_with_every_resource_action_replay_from_public_log(self):
        class ResourceClient:
            def __init__(self):
                self.contexts = []

            def complete(self, context):
                self.contexts.append(deepcopy(context))
                view = context["game"]
                plan = model_response(context)
                if context.get("decision") in {"exile_nomination", "exile_vote"}:
                    return plan
                if context.get("decision") == "window":
                    kind = "RESPOND" if view["phase"] == "challenge" else "REACT"
                    return {"action": {"kind": kind, "social": plan["social"]}}
                index = view["speaking_order"].index(view["self"])
                descriptor = {"kind": "PASS"}
                if view["phase"] == "discussion":
                    kinds = ("HOLD", "CHALLENGE", "COMMITTED_SOCIAL", "CITE", "PASS", "SOCIAL")
                    kind = kinds[index]
                    if kind in view["legal_actions"]:
                        descriptor = {"kind": kind}
                        if kind in {"CHALLENGE", "CITE"}:
                            team_event = next(e for e in reversed(view["recent_events"]) if e["kind"] == "TEAM")
                            descriptor["evidence"] = team_event["seq"]
                            if kind == "CHALLENGE":
                                descriptor["target"] = view["leader"]
                revision = {"kind": "LOCK"}
                if view["phase"] == "discussion" and view["self"] == view["leader"]:
                    revision = {"kind": "REVISE", "removed": view["team"][0],
                                "added": next(p["id"] for p in view["players"] if p["id"] not in view["team"])}
                return {**plan, "discussion": descriptor, "revision": revision, "strong_vote": True}

        kinds_seen = set()
        for count in (5, 6):
            for direction in ("clockwise", "counterclockwise"):
                logs = []
                for _ in range(2):
                    game = Game(make_players(count, 7), seed=0, direction=direction)
                    clients = {p: ResourceClient() for p in game.ids}
                    agents = {p: Agent(game.view(p), clients[p], max_retries=0) for p in game.ids}
                    log = io.StringIO()
                    run_game(game, agents, write=lambda _: None, log=log, strategy_seed=7)
                    self.assertIsNotNone(game.winner)
                    events = [json.loads(line) for line in log.getvalue().splitlines()]
                    self.assertEqual(events, game.events)
                    balances = {}
                    for seq, event in enumerate(events, 1):
                        kinds_seen.add(event["kind"])
                        self.assertEqual(event["seq"], seq)
                        format_event(event, game.players)
                        if event["kind"] == "RESOLVE_REFRESH":
                            balances = deepcopy(event["resolve"])
                        elif "resolve_cost" in event:
                            balances[event["actor"]] -= event["resolve_cost"]
                            self.assertEqual(balances[event["actor"]], event["resolve_after"])
                        self.assertTrue(all(0 <= balance <= 3 for balance in balances.values()))
                    self.assertEqual(balances, game.resolve)
                    self.assertTrue(any(e["kind"] == "PASS" and e["resolve_after"] > 0 for e in events))
                    self.assertTrue(any(e.get("strong") for e in events))
                    for pid, client in clients.items():
                        self.assertEqual(sum(agents[pid].calls.values()), len(client.contexts))
                        if game.players[pid].role in {"GOOD", "MERLIN"}:
                            self.assertTrue(all("tactical" not in c for c in client.contexts))
                    for event in events:
                        if event["kind"] != "REVEAL":
                            self.assertNotIn("known_evil", json.dumps(event))
                            self.assertNotIn("strategy_mode", json.dumps(event))
                    logs.append(log.getvalue())
                self.assertEqual(logs[0], logs[1])
        self.assertTrue({"PASS", "SOCIAL", "CITE", "HOLD", "REACT", "CHALLENGE", "CHALLENGE_RESPONSE",
                         "TEAM_REVISE", "VOTE", "RESOLVE_REFRESH"} <= kinds_seen)

    def test_managed_evil_can_pass_despite_tactic_and_cannot_overspend(self):
        game = fixed_game()
        game.propose("P1", ["P1", "P3"])
        game.act("P1", {"kind": "PASS"})
        game.act("P2", {"kind": "PASS"})
        manager = EvilStrategyManager(game.ids, {"P3", "P4"}, seed=0)

        class EvilClient:
            kind = "PASS"
            def complete(self, context):
                return {**model_response(context), "discussion": {"kind": self.kind},
                        "revision": {"kind": "LOCK"}, "strong_vote": True}

        client = EvilClient()
        agent = Agent(game.view("P3"), client, evil_strategy=manager, max_retries=0)
        agent.prepare(game.view("P3"))
        game.act("P3", agent.discussion_action())
        self.assertEqual(game.resolve["P3"], 3)
        finish_discussion(game)
        game.vote(dict.fromkeys(game.ids, False))
        game.propose(game.leader, ["P1", "P3"])
        game.act(game.next_actor, {"kind": "PASS"})
        game.resolve["P3"] = 0
        client.kind = "SOCIAL"
        before = deepcopy(vars(game))
        with self.assertRaises(LLMError):
            agent.prepare(game.view("P3"))
        self.assertEqual(vars(game), before)

    def test_model_can_save_with_points_available_and_spend_later(self):
        game = fixed_game()
        game.propose("P1", ["P1", "P2"])
        plan = resource_plan(game.view("P1"))
        later = resource_plan(game.view("P1"), "COMMITTED_SOCIAL")
        client = SequenceClient([plan, later])
        agent = Agent(game.view("P1"), client)
        agent.prepare(game.view("P1"))
        game.act("P1", agent.discussion_action())
        self.assertEqual(game.resolve["P1"], 3)
        finish_discussion(game)
        game.vote(dict.fromkeys(game.ids, False))
        game.propose(game.leader, ["P1", "P2"])
        while game.next_actor != "P1":
            game.act(game.next_actor, {"kind": "PASS"})
        agent.prepare(game.view("P1"))
        game.act("P1", agent.discussion_action())
        self.assertEqual(game.resolve["P1"], 1)
        self.assertEqual(agent.calls, {1: 2})
        self.assertEqual(client.contexts[-1]["game"]["resolve"]["P1"], 3)
        self.assertIn("Rejected proposals DO NOT restore", RESOLVE_PROTOCOL)
        self.assertIn("No fixed spending quota", RESOLVE_PROTOCOL)

    def test_model_overspend_retries_without_changing_memory_or_game(self):
        game = fixed_game()
        game.propose("P1", ["P1", "P2"])
        game.resolve["P1"] = 1
        agent = Agent(game.view("P1"), FixedClient(resource_plan(game.view("P1"), "COMMITTED_SOCIAL")), max_retries=0)
        before, memory = deepcopy(vars(game)), deepcopy(agent.memory)
        with self.assertRaises(LLMError):
            agent.prepare(game.view("P1"))
        self.assertEqual(vars(game), before)
        self.assertEqual(agent.memory, memory)
        self.assertIsNone(agent.plan)

    def test_focused_citation_reaches_good_and_managed_evil_contexts(self):
        game = fixed_game()
        game.propose("P1", ["P1", "P2"])
        original = deepcopy(game.events[-1])
        for _ in range(2):
            finish_discussion(game)
            game.vote(dict.fromkeys(game.ids, False))
            game.propose(game.leader, ["P1", "P2"])
        game.act(game.leader, {"kind": "CITE", "evidence": original["seq"]})
        manager = EvilStrategyManager(game.ids, {"P3", "P4"}, seed=0)
        for pid in ("P4", "P5"):
            client = FixedClient(valid_plan(game.view(pid)))
            agent = Agent(game.view(pid), client, evil_strategy=manager if pid == "P4" else None)
            agent.prepare(game.view(pid))
            self.assertEqual(client.contexts[0]["game"]["focused_events"], [original])

    def test_spending_commitment_and_cites_add_no_numerical_belief_bonus(self):
        game = fixed_game()
        a, b = Agent(game.view("P1")), Agent(game.view("P1"))
        base = {"seq": 1, "round": 1, "kind": "SOCIAL", "actor": "P3", **social()}
        a.observe({**base, "committed": False, "resolve_cost": 1})
        b.observe({**base, "committed": True, "resolve_cost": 2})
        self.assertEqual(a.memory, b.memory)
        before = deepcopy(b.memory)
        for seq, kind in enumerate(("CITE", "PASS", "HOLD"), 2):
            b.observe({"seq": seq, "round": 1, "kind": kind, "actor": "P2", "strong": True, "resolve_cost": 1})
        self.assertEqual(b.memory, before)
        # Real challenge/vote behavior has a conservative likelihood, but an
        # extra Resolve point/commitment cannot amplify the same behavior.
        for event in ({"seq": 5, "round": 1, "kind": "CHALLENGE", "actor": "P2", "target": "P4", "evidence": 1},
                      {"seq": 6, "round": 1, "kind": "VOTE", "actor": "P2", "team": ["P3", "P4"], "approve": False}):
            a.observe({**event, "strong": False, "resolve_cost": 0})
            b.observe({**event, "strong": True, "resolve_cost": 1})
        self.assertEqual(a.memory["beliefs"], b.memory["beliefs"])

    def test_window_requests_are_fresh_cached_per_trigger_and_preserve_main_policy(self):
        game = fixed_game()
        game.propose("P1", ["P1", "P2"])
        plan = resource_plan(game.view("P1"), "HOLD")
        client = SequenceClient([plan, {"action": {"kind": "SKIP"}},
                                 {"action": {"kind": "REACT", "social": plan["social"]}}])
        agent = Agent(game.view("P1"), client)
        agent.prepare(game.view("P1"))
        game.act("P1", agent.discussion_action())
        game.act("P2", {"kind": "PASS"})
        agent.update_view(game.view("P1"))
        skipped = agent.window_action()
        self.assertEqual(agent.window_action(), skipped)
        game.act("P1", skipped)
        game.act("P3", {"kind": "PASS"})
        agent.update_view(game.view("P1"))
        game.act("P1", agent.window_action())
        self.assertEqual(agent.plan, plan)
        self.assertEqual(agent.calls, {1: 3})
        self.assertEqual(game.resolve["P1"], 2)
        self.assertNotEqual(client.contexts[1]["game"]["reaction_trigger"], client.contexts[2]["game"]["reaction_trigger"])

    def test_zero_resolve_challenge_declines_without_call_and_illegal_window_retries(self):
        game = fixed_game()
        game.propose("P1", ["P1", "P2"])
        game.act("P1", {"kind": "CHALLENGE", "target": "P2", "evidence": game.events[-1]["seq"]})
        game.resolve["P2"] = 0
        agent = Agent(game.view("P2"))
        self.assertEqual(agent.window_action(), {"kind": "DECLINE"})
        self.assertEqual(agent.calls, {})
        game.resolve["P2"] = 1
        client = SequenceClient([{"action": {"kind": "HOLD"}}, {"action": {"kind": "DECLINE"}}])
        agent = Agent(game.view("P2"), client, retry_delay=0)
        self.assertEqual(agent.window_action(), {"kind": "DECLINE"})
        self.assertEqual(agent.calls, {1: 2})

    def test_first_call_can_be_a_response_without_fictional_memory_or_private_speech(self):
        game = fixed_game()
        game.propose("P1", ["P1", "P2"])
        game.act("P1", {"kind": "CHALLENGE", "target": "P2", "evidence": game.events[-1]["seq"]})
        action = {"kind": "RESPOND", "social": valid_plan(game.view("P2"))["social"]}
        bad = deepcopy(action)
        bad["social"]["statement"] = "我是梅林，我知道谁是邪恶方。"
        client = SequenceClient([{"action": bad}, {"action": action}])
        agent = Agent(game.view("P2"), client, retry_delay=0)
        before = deepcopy(vars(game))
        self.assertEqual(agent.window_action(), action)
        self.assertEqual(vars(game), before)
        self.assertEqual(client.contexts[0]["memory"], {"beliefs": {}, "profiles": {}})
        self.assertEqual(client.contexts[0]["memory_status"], "no_previous_model")
        self.assertNotIn(bad["social"]["statement"], json.dumps(client.contexts[1]))
        game.act("P2", action)
        self.assertEqual(game.resolve["P2"], 2)

    def test_human_empty_input_never_spends_and_zero_menus_hide_paid_actions(self):
        game = fixed_game()
        prompts = []
        human = Human(game.view("P1"), input_fn=lambda p: prompts.append(p) or "", write=lambda _: None)
        game.propose("P1", ["P1", "P2"])
        for balance in (3, 0):
            game.resolve["P1"] = balance
            human.update_view(game.view("P1"))
            self.assertEqual(human.discussion_action(), {"kind": "PASS"})
            self.assertEqual(human.ballot(game.team, 1), {"approve": True, "strong": False})
            self.assertEqual(human.social_action(), None)
            if balance == 0:
                self.assertNotIn("COMMIT", prompts[-3])
                self.assertNotIn("SOCIAL", prompts[-3])
                self.assertNotIn("SA", prompts[-2])
        finish_discussion(game, lock=False)
        human.update_view(game.view("P1"))
        self.assertEqual(human.revise_team(), {"kind": "LOCK"})
        self.assertNotIn("REVISE", prompts[-1])

    def test_human_controls_parse_every_new_action(self):
        game = fixed_game()
        game.propose("P1", ["P1", "P2"])
        human = Human(game.view("P1"), write=lambda _: None)
        for text, expected in (("", {"kind": "PASS"}), ("HOLD", {"kind": "HOLD"}),
                               ("COMMIT PRESSURE P2", {"kind": "COMMITTED_SOCIAL", "social": {**social(), "reason": "human_choice"}}),
                               ("CHALLENGE 2 #6", {"kind": "CHALLENGE", "target": "P2", "evidence": 6}),
                               ("CITE #6", {"kind": "CITE", "evidence": 6})):
            human.input_fn = lambda _, text=text: text
            self.assertEqual(human.discussion_action(), expected)
        for text, approve in (("SA", True), ("SR", False)):
            human.input_fn = lambda _, text=text: text
            self.assertEqual(human.ballot(game.team, 1), {"approve": approve, "strong": True})

    def test_controller_cannot_bypass_engine_and_human_invalid_target_costs_nothing(self):
        game = fixed_game()
        game.propose("P1", ["P1", "P2"])
        human = Human(game.view("P1"), input_fn=lambda _: "COMMIT PRESSURE P2", write=lambda _: None)
        action = human.discussion_action()
        game.resolve["P1"] = 0  # Controller's view is stale.
        before = deepcopy(vars(game))
        with self.assertRaises(ValueError):
            game.act("P1", action)
        self.assertEqual(vars(game), before)
        agent = Agent(game.view("P1"), FixedClient(resource_plan(game.view("P1"))))
        agent.prepare(game.view("P1"))
        with self.assertRaises(ValueError):
            game.social("P1", agent.social_action())
        game.act("P1", agent.discussion_action())
        self.assertEqual(game.events[-1]["kind"], "PASS")

    def test_all_ballots_collected_before_resolve_or_votes_are_revealed(self):
        game = fixed_game()
        snapshots = []

        class BallotObserver(Agent):
            def ballot(self, team, attempt):
                snapshots.append((game.round, attempt, deepcopy(game.resolve), deepcopy(game.events)))
                return {"approve": True, "strong": self._view["resolve"][self.id] > 0}

        agents = {p: BallotObserver(game.view(p), FixedClient(valid_plan(game.view(p)))) for p in game.ids}
        run_game(game, agents, write=lambda _: None, strategy_seed=0)
        for start in range(0, len(snapshots), 5):
            batch = snapshots[start:start+5]
            self.assertTrue(all(item == batch[0] for item in batch))
            round_no, attempt, _, events = batch[0]
            self.assertFalse(any(e["kind"] == "VOTE" and (e["round"], e["attempt"]) == (round_no, attempt) for e in events))


if __name__ == "__main__":
    unittest.main()
