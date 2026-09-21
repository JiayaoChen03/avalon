"""Rule/knowledge invariants and full agent wiring; no external model calls."""

from copy import deepcopy
import json
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from avalon.agents import Agent
from avalon.chronicle import record_id
from avalon.cognition import BeliefContradiction, BeliefEngine, Observation
from avalon.engine import Game, Player, build_agent_view, filter_worlds_by_mission_result, mission_rules
from avalon.evil_strategy import EvilStrategyManager
from avalon.gui import GameSession
from avalon.gui_server import make_server
from avalon.llm import LLMError
from avalon.terminal import run_game
from test_agents import FixedClient, SequenceClient, valid_plan, model_response
from test_engine import fixed_game, approve


def social_event(seq=20, actor="P2", target="P4", card="DEFEND"):
    return {"seq": seq, "round": 1, "attempt": 1, "kind": "SOCIAL", "actor": actor,
            "target": target, "card": card, "reason": "observe", "public_writing": f"I am certain about {target}, despite my earlier doubt."}


def update(event, targets=("P4",), direction="MORE_SUSPICIOUS", strength="WEAK"):
    return {"targets": list(targets), "direction": direction, "strength": strength,
            "evidence": [record_id(event)], "alternative_explanations": [
                "They may be cooperating as teammates.", "They may sincerely agree about this proposal."]}


def envelope(plan, updates=(), stance=None):
    action = {k: deepcopy(v) for k, v in plan.items() if k not in {"beliefs", "profiles"}}
    return {"belief_updates": list(updates), "interpretation": [], "public_stance_change": stance,
            "recommended_action": action, "short_rationale": "Available evidence remains ambiguous."}


def language_update(event, target="P4", signal="increase_suspicion", strength="medium"):
    return {"origin_event_id": record_id(event), "target": target, "signal": signal,
            "strength": strength, "reason_type": "contradiction", "confidence": "medium"}


class KnowledgeBoundaryTests(unittest.TestCase):
    def test_a_good_and_assassin_receive_only_role_authorized_information(self):
        game = fixed_game()
        good = build_agent_view("P1", game)
        assassin = build_agent_view("P3", game)
        self.assertEqual(good["private_knowledge"]["known_evil_players"], [])
        self.assertEqual(assassin["private_knowledge"]["known_evil_players"], ["P3", "P4"])
        self.assertEqual(assassin["private_knowledge"]["known_special_roles"], [])
        # Exchanging Merlin and a good seat is observationally identical to Assassin.
        players = [Player(p.id, p.name, "GOOD" if p.id == "P2" else "MERLIN" if p.id == "P5" else p.role)
                   for p in game.players.values()]
        other = Game(players, seed=0, direction="clockwise")
        self.assertEqual(game.view("P1"), other.view("P1"))
        self.assertEqual(game.view("P3"), other.view("P3"))
        moved_evil = [Player(p.id, p.name, "GOOD" if p.id == "P3" else "ASSASSIN" if p.id == "P5" else p.role)
                      for p in game.players.values()]
        self.assertEqual(game.view("P1"), Game(moved_evil, seed=0, direction="clockwise").view("P1"))
        self.assertEqual(len(Agent(good).state.private_beliefs.possible_worlds), 6)
        self.assertEqual(Agent(assassin).state.private_beliefs.possible_worlds[0]["evil_team"], ["P3", "P4"])

    def test_g_debug_and_post_game_reveals_never_enter_prompt(self):
        game = fixed_game()
        game.true_roles = {pid: "DEBUG_SECRET" for pid in game.ids}
        game.debug = {"other_agent_beliefs": "OTHER_SECRET"}
        game._emit("REVEAL", roles=game.true_roles)
        game._emit("MISSION_SUBMIT", actor="P3", card="FAIL", debug="CARD_SECRET")
        view = game.view("P1")
        # Defense in depth even when a custom controller appends extra debug keys.
        view["true_roles"] = game.true_roles
        view["objective_state"]["debug_metadata"] = game.debug
        view["players"][1]["role"] = "PLAYER_SECRET"
        client = FixedClient(envelope(valid_plan(view)))
        agent = Agent(view, client, chronicle=game.chronicle.reader())
        before = agent.cognition_debug_view()
        before["private_knowledge"]["known_evil_players"].append("P99")
        agent.prepare(view)
        serialized = json.dumps(client.contexts)
        for forbidden in ("true_roles", "debug_metadata", "DEBUG_SECRET", "OTHER_SECRET", "CARD_SECRET",
                          "PLAYER_SECRET", "MISSION_SUBMIT", "REVEAL", "P99"):
            self.assertNotIn(forbidden, serialized)
        self.assertNotIn("role", json.dumps(client.contexts[0]["game"]["players"]))

    def test_sealed_cards_indistinguishable_and_no_other_agent_private_state(self):
        contexts = []
        for saboteur in ("P3", "P4"):
            game = fixed_game()
            approve(game, ["P3", "P4"])
            game.resolve_mission({p: "FAIL" if p == saboteur else "SUCCESS" for p in game.team})
            agent = Agent(game.view("P1"), chronicle=game.chronicle.reader())
            contexts.append(agent._context(game.view("P1")))
        self.assertEqual(*contexts)

    def test_full_vote_facts_survive_recent_context_window(self):
        game = fixed_game()
        approve(game, ["P1", "P2"])
        for _ in range(30):
            game._emit("PASS", actor="P4")
        agent = Agent(game.view("P1"), chronicle=game.chronicle.reader())
        context = agent._context(game.view("P1"))
        objective = context["objective_state"]
        self.assertEqual(objective["public_votes"][0]["votes"], dict.fromkeys(game.ids, True))
        self.assertEqual(objective["mission_round"], game.round)
        self.assertEqual(objective["proposal_number"], game.attempt)
        self.assertEqual(objective["resolve"], game.resolve)
        self.assertEqual(context["legal_actions"], [{"kind": "MISSION", "cards": ["SUCCESS"]}])


class JointBeliefTests(unittest.TestCase):
    def test_d_success_retains_worlds_where_evil_passed(self):
        game = fixed_game()
        cognition = BeliefEngine(game.view("P1"))
        original = deepcopy(cognition.worlds)
        cognition.observe({"seq": 20, "round": 1, "attempt": 1, "kind": "MISSION",
                           "team": ["P3", "P4"], "fail_count": 0, "success": True})
        self.assertEqual(cognition.worlds, original)
        self.assertTrue(any(w["evil_team"] == ["P3", "P4"] for w in cognition.worlds))

    def test_one_fail_is_lower_bound_not_exact_evil_count(self):
        cognition = BeliefEngine(fixed_game().view("P1"))
        event = {"seq": 20, "round": 1, "kind": "MISSION", "team": ["P3", "P4"],
                 "fail_count": 1, "success": False}
        cognition.observe(event)
        self.assertEqual(len(cognition.worlds), 5)
        self.assertTrue(all(set(w["evil_team"]) & {"P3", "P4"} for w in cognition.worlds))
        self.assertTrue(any(w["evil_team"] == ["P3", "P4"] for w in cognition.worlds))
        self.assertIn(record_id(event), json.dumps(cognition.debug_snapshot()["eliminated_worlds"]))

    def test_two_fails_identify_pair_and_preserve_certain_provenance(self):
        cognition = BeliefEngine(fixed_game().view("P1"))
        event = {"seq": 20, "round": 1, "kind": "MISSION", "team": ["P3", "P4"],
                 "fail_count": 2, "success": False}
        cognition.observe(event)
        self.assertEqual([w["evil_team"] for w in cognition.worlds], [["P3", "P4"]])
        self.assertEqual(cognition.summary()["P3"]["assessment"], "KNOWN_EVIL")
        self.assertTrue(any(record_id(event) in h["cause"] for h in cognition.state.belief_history))
        for seq in range(21, 65):
            soft = social_event(seq)
            cognition.apply_soft_updates([update(soft)], [soft], 1)
        self.assertIn(record_id(event), cognition.summary()["P3"]["evidence"])

    def test_threshold_is_distinct_from_fail_card_capacity(self):
        worlds = [{"evil_team": ["P2", "P3"]}, {"evil_team": ["P4", "P5"]}]
        rules = dict(mission_rules(5, 1), fail_threshold=2)
        allowed = filter_worlds_by_mission_result(worlds, ["P1", "P2"], 1, rules, success=True)
        self.assertEqual(allowed, worlds[:1])
        with self.assertRaisesRegex(ValueError, "Inconsistent"):
            filter_worlds_by_mission_result(worlds, ["P1", "P2"], 1, rules, success=False)
        rules["evil_may_succeed"] = False
        self.assertEqual(filter_worlds_by_mission_result(worlds, ["P1", "P2"], 0, rules), worlds[1:])

    def test_e_known_evil_removes_every_conflicting_world(self):
        cognition = BeliefEngine(fixed_game().view("P1"))
        cognition.apply_known_alignments(evil=["P3"])
        self.assertTrue(all("P3" in w["evil_team"] for w in cognition.worlds))
        self.assertTrue(all(w["weight"] > 0 for w in cognition.worlds))
        self.assertAlmostEqual(sum(w["weight"] for w in cognition.worlds), 1)

    def test_f_defense_changes_only_soft_joint_weights(self):
        cognition = BeliefEngine(fixed_game().view("P1"))
        event = social_event()
        before = deepcopy(cognition.worlds)
        cognition.observe(event)
        after_observation = deepcopy(cognition.worlds)
        cognition.apply_soft_updates([update(event, targets=("P2", "P4"))], [event], 1)
        self.assertEqual(cognition.worlds, after_observation)  # Same card, not a second signal.
        self.assertEqual(len(cognition.worlds), len(before))
        self.assertNotEqual([w["weight"] for w in cognition.worlds], [w["weight"] for w in before])
        self.assertTrue(all(w["weight"] > 0 for w in cognition.worlds))
        self.assertNotIn("KNOWN_EVIL", {v["assessment"] for v in cognition.summary().values()})
        self.assertEqual(cognition.state.private_beliefs.updates[-1]["reason"], "defense")
        self.assertNotIn("suspicious", json.dumps(cognition.state.objective_state))

    def test_contradictory_soft_evidence_preserves_worlds_and_old_explanations(self):
        cognition = BeliefEngine(fixed_game().view("P1"))
        one, two = social_event(20), social_event(21, card="ACCUSE")
        cognition.apply_soft_updates([language_update(one, strength="strong")], [one], 1)
        prior = cognition.marginals()["P4"]["evil"]
        cognition.apply_soft_updates([language_update(two, signal="decrease_suspicion")], [two], 1)
        self.assertLess(cognition.marginals()["P4"]["evil"], prior)
        self.assertEqual(len(cognition.worlds), 6)
        self.assertEqual([u["direction"] for u in cognition.state.private_beliefs.updates if u["kind"] == "SOFT"],
                         ["MORE_SUSPICIOUS", "LESS_SUSPICIOUS"])

    def test_hard_contradiction_is_atomic_and_never_resets_to_uniform(self):
        cognition = BeliefEngine(fixed_game().view("P1"))
        before = cognition.debug_snapshot()
        with self.assertRaises(BeliefContradiction):
            cognition.observe({"seq": 20, "round": 1, "kind": "MISSION", "team": ["P1"],
                               "fail_count": 1, "success": False})
        self.assertEqual(cognition.debug_snapshot(), before)

    def test_repeated_evidence_cannot_amplify_weights(self):
        cognition = BeliefEngine(fixed_game().view("P1"))
        event = social_event()
        cognition.apply_soft_updates([update(event)], [event], 1)
        before = cognition.debug_snapshot()
        cognition.apply_soft_updates([update(event, strength="STRONG")], [event], 2)
        self.assertEqual(cognition.debug_snapshot(), before)

    def test_old_evidence_cannot_be_rebundled_to_amplify_a_hypothesis(self):
        cognition = BeliefEngine(fixed_game().view("P1"))
        first, second = social_event(20), social_event(21)
        for event in (first, second):
            cognition.apply_soft_updates([update(event)], [event], 1)
        before = cognition.debug_snapshot()
        combined = update(first, strength="STRONG")
        combined["evidence"].append(record_id(second))
        cognition.apply_soft_updates([combined], [first, second], 1)
        self.assertEqual(cognition.debug_snapshot(), before)

    def test_joint_team_risk_used_in_actual_vote(self):
        game = fixed_game()
        agent = Agent(game.view("P1"), FixedClient(envelope(valid_plan(game.view("P1")))))
        agent.prepare(game.view("P1"))
        agent.plan["vote_threshold"] = .6
        # Both players have marginal .5; joint probability of at least one evil is 5/6.
        self.assertFalse(agent.vote(["P3", "P4"], 1))


class PublicPrivateTests(unittest.TestCase):
    def test_b_strong_private_suspicion_leaves_public_stance_unchanged(self):
        cognition = BeliefEngine(fixed_game().view("P1"))
        initial = deepcopy(cognition.state.public_stances)
        for seq in range(20, 26):
            event = social_event(seq)
            cognition.apply_soft_updates([language_update(event, strength="strong")], [event], 1)
        self.assertEqual(cognition.summary()["P4"]["assessment"], "STRONGLY_SUSPICIOUS")
        self.assertEqual(cognition.state.public_stances, initial)
        counter = social_event(30, card="ACCUSE")
        cognition.apply_soft_updates([language_update(counter, signal="decrease_suspicion")], [counter], 1)
        self.assertEqual(cognition.state.public_stances, initial)

    def test_c_only_accepted_public_accuse_updates_stance(self):
        game = fixed_game()
        game.propose(game.leader, ["P1", "P2"])
        plan = valid_plan(game.view("P1"))
        plan["social"].update(card="ACCUSE", target="P4")
        agent = Agent(game.view("P1"), FixedClient(envelope(plan, stance={"target": "P4", "stance": "SUSPICIOUS"})))
        agent.prepare(game.view("P1"))
        self.assertEqual(agent.state.public_stances["P4"]["stance"], "UNCERTAIN")
        with self.assertRaises(ValueError):
            game.act("P5", agent.discussion_action())
        self.assertEqual(agent.state.public_stances["P4"]["stance"], "UNCERTAIN")
        game.act("P1", agent.discussion_action())
        agent.observe(game.events[-1])
        self.assertEqual(agent.state.public_stances["P4"]["stance"], "SUSPICIOUS")
        self.assertEqual(agent.state.public_stances["P4"]["event_id"], game.events[-1]["record_id"])

    def test_pass_and_other_players_expression_do_not_change_my_stances(self):
        cognition = BeliefEngine(fixed_game().view("P1"))
        initial = deepcopy(cognition.state.public_stances)
        cognition.observe(social_event(card="ACCUSE"))
        cognition.observe({"seq": 21, "round": 1, "kind": "PASS", "actor": "P1"})
        self.assertEqual(cognition.state.public_stances, initial)
        self.assertEqual(cognition.state.observations[-1].type, "PASS")

    def test_strong_rejection_is_a_team_stance_not_an_accusation(self):
        cognition = BeliefEngine(fixed_game().view("P1"))
        cognition.observe({"seq": 20, "round": 1, "kind": "VOTE", "actor": "P1",
                           "team": ["P3", "P4"], "approve": False, "strong": True})
        self.assertEqual(cognition.state.public_stances["TEAM:P3,P4"]["stance"], "OPPOSE_TEAM")
        self.assertEqual(cognition.state.public_stances["P4"]["stance"], "UNCERTAIN")

    def test_challenge_response_cite_and_hard_updates_keep_boundaries(self):
        cognition = BeliefEngine(fixed_game().view("P1"))
        cognition.observe({"seq": 20, "round": 1, "kind": "CHALLENGE", "actor": "P1", "target": "P4", "evidence": 6})
        self.assertEqual(cognition.state.public_stances["P4"]["stance"], "QUESTIONING")
        cognition.observe({**social_event(21, actor="P1"), "kind": "CHALLENGE_RESPONSE"})
        self.assertEqual(cognition.state.public_stances["P4"]["stance"], "TRUST")
        cognition.observe({"seq": 22, "round": 1, "kind": "CITE", "actor": "P1", "evidence": 6})
        self.assertEqual(cognition.state.public_stances["EVIDENCE:6"]["stance"], "REFERENCED")
        cognition.apply_known_alignments(evil=["P4"])
        self.assertEqual(cognition.state.public_stances["P4"]["stance"], "TRUST")


class ProtocolIntegrationTests(unittest.TestCase):
    def test_new_envelope_commits_updates_once_and_does_not_publish_them(self):
        game = fixed_game()
        game.propose(game.leader, ["P1", "P2"])
        event = game._emit("SOCIAL", actor="P2", target="P4", card="DEFEND", reason="observe")
        plan = valid_plan(game.view("P1"))
        plan.update(social=None, discussion={"kind": "PASS"}, revision={"kind": "LOCK"}, strong_vote=False)
        raw = envelope(plan, updates=[update(event)])
        agent = Agent(game.view("P1"), FixedClient(raw), chronicle=game.chronicle.reader(), max_retries=0)
        agent.prepare(game.view("P1"))
        after = agent.cognition_debug_view()
        agent.prepare(game.view("P1"))
        self.assertEqual(agent.cognition_debug_view(), after)
        self.assertGreater(agent.memory["beliefs"]["P4"]["evil"], .5)
        game.act("P1", agent.discussion_action())
        self.assertNotIn("belief_updates", json.dumps(game.events))
        self.assertEqual(agent.state.public_stances["P4"]["stance"], "UNCERTAIN")

    def test_invalid_later_update_or_action_leaves_entire_batch_uncommitted(self):
        game = fixed_game()
        event = social_event()
        plan = valid_plan(game.view("P1"))
        for defect in ("citation", "action", "stance", "probability", "alternatives", "numeric_beliefs"):
            with self.subTest(defect=defect):
                raw = envelope(plan, updates=[update(event), update(event, targets=("P2",))])
                if defect == "citation":
                    raw["belief_updates"][1]["evidence"] = ["R99-999"]
                elif defect == "action":
                    raw["recommended_action"]["team_rank"] = ["P99"]
                elif defect == "stance":
                    raw["public_stance_change"] = {"target": "P4", "stance": "TRUST"}
                elif defect == "probability":
                    raw["belief_updates"][1]["strength"] = .734
                elif defect == "numeric_beliefs":
                    raw["recommended_action"]["beliefs"] = plan["beliefs"]
                else:
                    raw["belief_updates"][1]["alternative_explanations"] = []
                agent = Agent(game.view("P1"), FixedClient(raw), max_retries=0)
                agent.observe(event)
                before = agent.cognition_debug_view()
                with self.assertRaises(LLMError):
                    agent.prepare(game.view("P1"))
                self.assertEqual(agent.cognition_debug_view(), before)

    def test_legacy_numeric_beliefs_are_ignored(self):
        game = fixed_game()
        plan = valid_plan(game.view("P1"))
        plan["beliefs"]["P4"] = {"evil": .99, "merlin": .01}
        agent = Agent(game.view("P1"), FixedClient(plan))
        agent.prepare(game.view("P1"))
        self.assertEqual(agent.memory["beliefs"]["P4"]["evil"], .5)

    def test_window_uses_new_envelope_and_waits_for_accepted_event(self):
        game = fixed_game()
        game.propose("P1", ["P1", "P2"])
        team = game.events[-1]
        game.act("P1", {"kind": "CHALLENGE", "target": "P2", "evidence": team["seq"]})
        social = valid_plan(game.view("P2"))["social"]
        social.update(card="DEFEND", target="P4")
        raw = envelope({"action": {"kind": "RESPOND", "social": social}}, stance={"target": "P4", "stance": "TRUST"})
        agent = Agent(game.view("P2"), FixedClient(raw), chronicle=game.chronicle.reader())
        action = agent.window_action()
        self.assertEqual(agent.state.public_stances["P4"]["stance"], "UNCERTAIN")
        game.act("P2", action)
        agent.observe(game.events[-1])
        self.assertEqual(agent.state.public_stances["P4"]["stance"], "TRUST")
        # Merlin can publicly defend known evil without corrupting private knowledge.
        self.assertEqual(agent.cognition.summary()["P4"]["assessment"], "KNOWN_EVIL")

    def test_full_five_and_six_player_games_with_debug_and_modern_protocol(self):
        class ModernClient:
            def __init__(self):
                self.contexts = []

            def complete(self, context):
                self.contexts.append(deepcopy(context))
                response = model_response(context)
                if "vote_threshold" in response:
                    response["vote_threshold"] = 1
                return envelope(response)

        for count in (5, 6):
            with self.subTest(count=count):
                game, client = fixed_game(count), ModernClient()
                agents = {p: Agent(game.view(p), client, max_retries=0) for p in game.ids}
                public, debug = [], []
                run_game(game, agents, write=public.append, strategy_seed=1, cognition_write=debug.append)
                self.assertIn(game.winner, {"GOOD", "EVIL"})
                self.assertTrue(any("eliminated_worlds" in line for line in debug))
                self.assertNotIn("eliminated_worlds", json.dumps(client.contexts))
                self.assertNotIn("belief_updates", "\n".join(public))
                for context in client.contexts:
                    self.assertTrue({"objective_state", "private_knowledge", "private_beliefs",
                                     "public_stances", "observations", "legal_actions", "current_resolve"} <= context.keys())
                    self.assertNotIn("true_roles", json.dumps(context))
                    self.assertEqual(context["private_knowledge"]["self_role"], context["game"]["role"])

    def test_gui_developer_view_is_separate_from_player_snapshot(self):
        session = GameSession(lambda: FixedClient(), developer_mode=True)
        session.start(5, 0)
        self.assertTrue(session.cognition_debug_view()["agents"])
        serialized = json.dumps(session.snapshot())
        for key in ("possible_worlds", "private_beliefs", "public_stances", "eliminated_worlds"):
            self.assertNotIn(key, serialized)
        session.developer_mode = False
        with self.assertRaises(ValueError):
            session.cognition_debug_view()

    def test_debug_http_requires_both_developer_mode_and_existing_auth(self):
        session = GameSession(lambda: FixedClient())
        session.start(5, 0)
        server = make_server(session, "test-token")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f"http://127.0.0.1:{server.server_port}/debug/cognition"
        headers = {"Authorization": "Bearer test-token"}
        try:
            with self.assertRaises(HTTPError) as error:
                urlopen(Request(url, headers=headers), timeout=2)
            self.assertEqual(error.exception.code, 404)
            session.developer_mode = True
            for unsafe in ({}, {**headers, "Origin": "https://example.com"}):
                with self.assertRaises(HTTPError) as error:
                    urlopen(Request(url, headers=unsafe), timeout=2)
                self.assertEqual(error.exception.code, 403)
            with urlopen(Request(url, headers=headers), timeout=2) as response:
                self.assertEqual(set(json.load(response)["agents"]), set(session.agents))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)


if __name__ == "__main__":
    unittest.main()
