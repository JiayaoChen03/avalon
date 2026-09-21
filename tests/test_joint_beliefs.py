"""Exact Bayesian role reasoning and its legal observation/decision boundaries."""
from collections import Counter
from copy import deepcopy
import json
import math
import unittest

from avalon.agents import Agent
from avalon.chronicle import record_id
from avalon.cognition import BeliefEngine
from avalon.engine import Game, Player
from avalon.evidence import EvidenceExtractor, EvidenceType, LikelihoodConfig, Observation
from avalon.joint_beliefs import (BeliefContradiction, JointBeliefState, JointHypothesis,
                                 enumerate_hypotheses, P_conditional, marginal_role_probability)
from avalon.llm import LLMError
from test_agents import SequenceClient, valid_plan
from test_cognition import envelope, update
from test_engine import fixed_game


def speech(seq=30, actor="P2", target="P4", card="HEDGE"):
    return {"seq": seq, "round": 1, "attempt": 1, "kind": "SOCIAL", "actor": actor,
            "target": target, "card": card, "public_writing": f"I am certain about {target}, despite my earlier doubt."}


def semantic(event, target="P4", signal="increase_suspicion", strength="medium", confidence="medium", reason="contradiction"):
    return {"origin_event_id": record_id(event), "target": target, "signal": signal,
            "strength": strength, "reason_type": reason, "confidence": confidence}


def mission(seq=50, round_no=1, fails=1, team=("P3", "P4")):
    return {"seq": seq, "round": round_no, "attempt": 1, "kind": "MISSION", "team": list(team),
            "fail_count": fails, "success": fails == 0, "fail_threshold": 1}


def six_game():
    players = list(fixed_game().players.values()) + [Player("P6", "Six", "GOOD")]
    return Game(players, seed=0, direction="clockwise")


class JointGenerationTests(unittest.TestCase):
    def test_multiset_counts_and_role_composition(self):
        for game, expected in ((fixed_game(), 60), (six_game(), 120)):
            counts = game.view("P1")["rules"]["role_counts"]
            hypotheses = enumerate_hypotheses(game.ids, counts)
            self.assertEqual(len(hypotheses), expected)
            self.assertEqual(len({h.key for h in hypotheses}), expected)
            self.assertAlmostEqual(math.fsum(h.probability for h in hypotheses), 1)
            self.assertTrue(all(Counter(h.roles.values()) == Counter(counts) for h in hypotheses))

    def test_enumerator_uses_supplied_composition_without_new_gameplay_roles(self):
        roles = {r: 1 for r in ("Merlin", "Percival", "Morgana", "Assassin", "Servant")}
        self.assertEqual(len(enumerate_hypotheses(list("ABCDE"), roles)), 120)
        for counts in ({"GOOD": 4}, {"GOOD": True, "EVIL": 4}, {"GOOD": -1, "EVIL": 6}):
            with self.assertRaises(ValueError):
                enumerate_hypotheses(list("ABCDE"), counts)

    def test_self_and_private_constraints_for_every_role(self):
        for game, expected in ((fixed_game(), {"P1": 24, "P2": 2, "P3": 3, "P4": 3}),
                               (six_game(), {"P1": 60, "P2": 2, "P3": 4, "P4": 4})):
            for pid, count in expected.items():
                engine = BeliefEngine(game.view(pid))
                self.assertEqual(len(engine.beliefs.hypotheses), count)
                self.assertEqual(engine.P_role(pid, game.players[pid].role), 1)
                if pid != "P1":
                    self.assertEqual(engine.P_joint({"P3": "EVIL", "P4": "EVIL"}), 1)
                self.assertAlmostEqual(sum(h.probability for h in engine.beliefs.hypotheses), 1)

    def test_identity_swap_invisible_to_observer_and_no_cross_agent_state(self):
        game = fixed_game()
        moved = [Player(p.id, p.name, "MERLIN" if p.id == "P5" else "GOOD" if p.id == "P2" else p.role)
                 for p in game.players.values()]
        other = Game(moved, seed=0, direction="clockwise")
        for pid in ("P1", "P3"):
            self.assertEqual(BeliefEngine(game.view(pid)).debug_snapshot(), BeliefEngine(other.view(pid)).debug_snapshot())
        servant, merlin = BeliefEngine(game.view("P1")), BeliefEngine(game.view("P2"))
        before = servant.debug_snapshot()
        merlin.observe(speech(card="DEFEND"))
        self.assertEqual(servant.debug_snapshot(), before)
        self.assertIsNot(servant.beliefs.hypotheses, merlin.beliefs.hypotheses)


class ProbabilityTests(unittest.TestCase):
    def setUp(self):
        self.engine = BeliefEngine(fixed_game().view("P1"))

    def test_marginals_and_conditionals_equal_manual_sums(self):
        b = self.engine.beliefs
        for pid in b.player_ids:
            for role in b.role_counts:
                manual = sum(h.probability for h in b.hypotheses if h.roles[pid] == role)
                self.assertAlmostEqual(marginal_role_probability(b, pid, role), manual)
            self.assertAlmostEqual(sum(b.marginals()[pid]["roles"].values()), 1)
        self.assertAlmostEqual(self.engine.P_alignment("P3", "EVIL"), .5)
        self.assertAlmostEqual(self.engine.P_role("P3", "MERLIN"), .25)
        self.assertAlmostEqual(self.engine.P_joint({"P3": "EVIL", "P4": "EVIL"}), 1/6)
        self.assertAlmostEqual(P_conditional(b, {"P4": "EVIL"}, {"P3": "GOOD"}), 2/3)
        self.assertIsNone(b.P_conditional({"P4": "EVIL"}, {"P1": "EVIL"}))
        self.assertEqual(b.P_conditional({"P3": "EVIL"}, {"P3": "GOOD"}), 0)
        self.assertAlmostEqual(sum(b.P_alignment(p, "EVIL") for p in b.player_ids), 2)
        self.assertAlmostEqual(sum(b.P_role(p, "MERLIN") for p in b.player_ids), 1)
        self.assertGreater(b.P_alignment("P3", "GOOD"), b.P_role("P3", "GOOD"))

    def test_query_validation(self):
        for query in ({"P99": "EVIL"}, {"P3": "UNKNOWN"}, {"P3": {"role": "GOOD", "alignment": "GOOD"}}):
            with self.assertRaises(ValueError):
                self.engine.P_joint(query)

    def test_zero_mass_and_nan_infinity_are_errors_without_reset(self):
        for value in (float("nan"), float("inf"), -1, True):
            with self.assertRaises(ValueError):
                JointHypothesis({"P1": "GOOD"}, value)
        for value in (-math.inf, math.inf, math.nan):
            trial = deepcopy(self.engine.beliefs)
            for h in trial.hypotheses:
                h.log_probability = value
            with self.assertRaises(ValueError):
                trial.normalize()
        self.assertEqual(len(self.engine.beliefs.hypotheses), 24)

    def test_soft_underflow_stays_positive_and_zero_cannot_revive(self):
        b = deepcopy(self.engine.beliefs)
        dead = deepcopy(b.hypotheses.pop())
        dead.probability = 0
        b.hypotheses.append(dead)
        b.normalize()
        self.assertIn(dead.key, b.eliminated_keys)
        dead.probability = 1
        b.hypotheses.append(dead)
        b.hypotheses[0].log_probability = -1e300
        b.normalize()
        self.assertNotIn(dead.key, [h.key for h in b.hypotheses])
        self.assertTrue(all(math.isfinite(h.probability) and h.probability > 0 for h in b.hypotheses))
        self.assertAlmostEqual(sum(h.probability for h in b.hypotheses), 1)

    def test_duplicate_or_wrong_composition_cannot_normalize(self):
        for defect in ("duplicate", "composition"):
            b = deepcopy(self.engine.beliefs)
            if defect == "duplicate":
                b.hypotheses.append(deepcopy(b.hypotheses[0]))
            else:
                b.hypotheses[0].roles["P1"] = "EVIL"
            with self.assertRaises(ValueError):
                b.normalize()

    def test_compact_summary_is_derived_not_renormalized_top_k(self):
        prompt = self.engine.prompt_state()["private_beliefs"]
        self.assertEqual(prompt["hypotheses_remaining"], 24)
        self.assertEqual(len(prompt["top_role_hypotheses"]), 3)
        self.assertEqual(len(prompt["possible_worlds"]), 5)
        self.assertLess(prompt["shown_evil_team_mass"], 1)
        self.assertAlmostEqual(sum(h["probability"] for h in prompt["top_role_hypotheses"]), 3/24)
        self.assertTrue(prompt["conditional_relationships"])
        self.assertEqual(prompt["marginals"], self.engine.beliefs.marginals())


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.engine = BeliefEngine(fixed_game().view("P1"))

    def test_failed_quest_eliminates_exactly_inconsistent_roles_and_records_deltas(self):
        b = self.engine.beliefs
        before = deepcopy(b.marginals())
        expected = {h.key for h in b.hypotheses if any(b.role_alignments[h.roles[p]] == "EVIL" for p in ("P3", "P4"))}
        self.engine.observe(mission())
        self.assertEqual({h.key for h in b.hypotheses}, expected)
        record = b.update_records[-1]
        self.assertEqual(record.eliminated_count, 4)
        self.assertEqual(record.observation_id, record_id(mission()))
        self.assertEqual(record.evidence[0].evidence_type, EvidenceType.HARD)
        delta = record.marginal_changes["P3"]["alignment"]["EVIL"]
        self.assertEqual(delta["before"], before["P3"]["alignment"]["EVIL"])
        self.assertEqual(delta["after"], b.P_alignment("P3", "EVIL"))
        self.assertAlmostEqual(delta["delta"], .1)
        self.assertTrue(record.prior_top_hypotheses and record.posterior_top_hypotheses and record.largest_marginal_change)

    def test_success_does_not_clear_team_and_hard_zero_never_revives(self):
        self.engine.observe(mission(fails=0))
        self.assertEqual(len(self.engine.beliefs.hypotheses), 24)
        self.engine.observe(mission(seq=51, round_no=2, fails=2))
        survivors = {h.key for h in self.engine.beliefs.hypotheses}
        for seq in range(100, 120):
            event = speech(seq)
            self.engine.apply_soft_updates([semantic(event, signal="decrease_suspicion", strength="strong")], [event], 2)
        self.assertEqual({h.key for h in self.engine.beliefs.hypotheses}, survivors)
        self.assertEqual(self.engine.P_alignment("P4", "EVIL"), 1)

    def test_ambiguous_mission_rule_variants_use_engine_constraints(self):
        for good_may_fail, evil_may_succeed, fails, expected in ((True, True, 1, 24), (False, False, 0, 4)):
            view = fixed_game().view("P1")
            view["rules"].update(good_may_fail=good_may_fail, evil_may_succeed=evil_may_succeed)
            engine = BeliefEngine(view)
            engine.observe(mission(fails=fails))
            self.assertEqual(len(engine.beliefs.hypotheses), expected)

    def test_impossible_hard_update_is_atomic(self):
        before = self.engine.debug_snapshot()
        with self.assertRaises(BeliefContradiction):
            self.engine.observe(mission(team=("P1",)))
        self.assertEqual(before, self.engine.debug_snapshot())

    def test_weak_medium_strong_and_confidence_are_monotonic(self):
        for signal in ("increase_suspicion", "decrease_suspicion"):
            values = []
            for strength in ("weak", "medium", "strong"):
                engine = BeliefEngine(fixed_game().view("P1"))
                e = speech()
                engine.apply_soft_updates([semantic(e, strength=strength, signal=signal)], [e], 1)
                values.append(engine.P_alignment("P4", "EVIL"))
                self.assertEqual(len(engine.beliefs.hypotheses), 24)
                self.assertAlmostEqual(sum(h.probability for h in engine.beliefs.hypotheses), 1)
            self.assertEqual(sorted(values, reverse=signal == "decrease_suspicion"), values)
            self.assertEqual(len(set(values)), 3)
        low, high = [BeliefEngine(fixed_game().view("P1")) for _ in range(2)]
        for engine, confidence in ((low, "low"), (high, "high")):
            engine.apply_soft_updates([semantic(speech(), confidence=confidence)], [speech()], 1)
        self.assertLess(low.P_alignment("P4", "EVIL"), high.P_alignment("P4", "EVIL"))

    def test_language_multiplier_is_configured_in_code(self):
        config = LikelihoodConfig(language={"weak": 1.0, "medium": 1.0, "strong": 1.0})
        engine = BeliefEngine(fixed_game().view("P1"), likelihood_config=config)
        engine.apply_soft_updates([semantic(speech())], [speech()], 1)
        self.assertAlmostEqual(engine.P_alignment("P4", "EVIL"), .5)
        with self.assertRaises(ValueError):
            LikelihoodConfig(language={"weak": 2, "medium": 1, "strong": 1.6})

    def test_privileged_signal_changes_merlin_without_claiming_alignment_proof(self):
        engine = BeliefEngine(fixed_game().view("P3"))
        event = speech(target="P2")
        engine.apply_soft_updates([semantic(event, target="P2", reason="privileged_information_signal")], [event], 1)
        self.assertGreater(engine.P_role("P2", "MERLIN"), 1/3)
        self.assertEqual(engine.P_alignment("P2", "GOOD"), 1)
        self.assertEqual(engine.P_role("P4", "MERLIN"), 0)

    def test_vote_and_aggregate_deduplicate_in_both_orders(self):
        vote = {"seq": 41, "round": 1, "attempt": 1, "kind": "VOTE", "actor": "P2",
                "approve": False, "team": ["P3", "P4"]}
        aggregate = {"seq": 42, "round": 1, "attempt": 1, "kind": "TEAM_VOTE",
                     "team": ["P3", "P4"], "votes": {"P2": False}, "approved": False}
        outcomes = []
        for first, second in ((vote, aggregate), (aggregate, vote)):
            engine = BeliefEngine(fixed_game().view("P1"))
            engine.observe(first)
            before = deepcopy(engine.beliefs.hypotheses)
            count = len(engine.beliefs.update_records)
            engine.observe(second)
            engine.observe(second)
            self.assertEqual(engine.beliefs.hypotheses, before)
            self.assertEqual(len(engine.beliefs.update_records), count)
            outcomes.append(engine.marginals())
        self.assertEqual(*outcomes)

    def test_full_aggregate_matches_individual_votes(self):
        votes = {p: p != "P2" for p in fixed_game().ids}
        first, second = [BeliefEngine(fixed_game().view("P1")) for _ in range(2)]
        for seq, (pid, approve) in enumerate(votes.items(), 20):
            first.observe({"seq": seq, "round": 1, "attempt": 1, "kind": "VOTE", "actor": pid,
                           "approve": approve, "team": ["P3", "P4"]})
        second.observe({"seq": 30, "round": 1, "attempt": 1, "kind": "TEAM_VOTE", "votes": votes,
                        "team": ["P3", "P4"], "approved": True})
        for pid in first.ids:
            self.assertAlmostEqual(first.P_role(pid, "MERLIN"), second.P_role(pid, "MERLIN"))

    def test_mechanical_fact_cannot_be_reweighted_as_language(self):
        e = mission()
        self.engine.observe(e)
        before = deepcopy(self.engine.beliefs.hypotheses)
        self.engine.apply_soft_updates([update(e)], [e], 1)
        self.assertEqual(self.engine.beliefs.hypotheses, before)
        with self.assertRaises(ValueError):
            self.engine.apply_soft_updates([semantic(e)], [dict(e, public_writing="P4 is evil")], 1)
        snapshot = dict(e, record_id=record_id(e))
        self.engine._process(Observation.from_mission(snapshot), remember=False)
        self.assertEqual(self.engine.beliefs.hypotheses, before)

    def test_social_action_and_its_semantic_restatement_share_a_signal(self):
        e = speech(card="DEFEND")
        self.engine.observe(e)
        before = deepcopy(self.engine.beliefs.hypotheses)
        self.engine.apply_soft_updates([semantic(e, reason="defense")], [e], 1)
        self.assertEqual(self.engine.beliefs.hypotheses, before)
        self.engine.apply_soft_updates([semantic(e, reason="contradiction")], [e], 1)
        changed = deepcopy(self.engine.beliefs.hypotheses)
        self.engine.apply_soft_updates([semantic(e, target="P2", strength="strong", reason="deception_signal")], [e], 1)
        self.assertEqual(self.engine.beliefs.hypotheses, changed)

    def test_own_actions_are_policy_outputs_not_evidence(self):
        e = speech(actor="P1", card="DEFEND")
        before = deepcopy(self.engine.beliefs.hypotheses)
        self.engine.observe(e)
        self.assertEqual(self.engine.beliefs.hypotheses, before)
        self.assertEqual(self.engine.state.public_stances["P4"]["stance"], "TRUST")
        with self.assertRaises(ValueError):
            self.engine.apply_soft_updates([semantic(e)], [e], 1)

    def test_invalid_language_batch_changes_nothing(self):
        for defect in ({"strength": .8}, {"signal": "evil"}, {"target": "P99"}, {"target": "P5"},
                       {"reason_type": "quest_failed"}, {"confidence": "certain"},
                       {"probability": .99}, {"origin_event_id": "R1-999"}):
            before = self.engine.debug_snapshot()
            with self.assertRaises(ValueError):
                self.engine.apply_soft_updates([semantic(speech()), {**semantic(speech()), **defect}], [speech()], 1)
            self.assertEqual(self.engine.debug_snapshot(), before)

    def test_hidden_events_and_nested_role_metadata_are_not_observations(self):
        self.assertIsNone(Observation.from_event({"seq": 90, "round": 1, "kind": "REVEAL", "roles": {"P4": "EVIL"}}))
        safe = Observation.from_event(dict(speech(), true_roles={"P4": "SECRET"}, private_beliefs="SECRET"))
        self.assertNotIn("SECRET", json.dumps(safe.payload))
        with self.assertRaises(TypeError):
            self.engine.extractor.extract(speech())


class DecisionPipelineTests(unittest.TestCase):
    def test_interpret_then_select_action_from_updated_posterior(self):
        game = fixed_game()
        event = game._emit("SOCIAL", actor="P2", target="P4", card="HEDGE", public_writing="I know P4 is evil.")
        client = SequenceClient([{"language_evidence": [semantic(event)]}, envelope(valid_plan(game.view("P1")))])
        agent = Agent(game.view("P1"), client, chronicle=game.chronicle.reader(), max_retries=0)
        agent.prepare(game.view("P1"))
        self.assertEqual(len(client.contexts), 2)
        before, after = client.contexts
        self.assertFalse(before["language_interpretation_complete"])
        self.assertTrue(after["language_interpretation_complete"])
        self.assertGreater(after["private_beliefs"]["marginals"]["P4"]["alignment"]["EVIL"],
                           before["private_beliefs"]["marginals"]["P4"]["alignment"]["EVIL"])
        self.assertEqual(after["private_beliefs"]["marginals"], agent.cognition.beliefs.marginals())
        self.assertEqual(after["memory"]["beliefs"], agent.memory["beliefs"])
        self.assertEqual(agent.state.public_stances["P4"]["stance"], "UNCERTAIN")

    def test_fresh_semantic_updates_cannot_hide_inside_an_action(self):
        game = fixed_game()
        event = game._emit("SOCIAL", actor="P2", target="P4", card="HEDGE", public_writing="P4 is evil.")
        client = SequenceClient([envelope(valid_plan(game.view("P1")), updates=[semantic(event)])])
        agent = Agent(game.view("P1"), client, max_retries=0)
        with self.assertRaises(LLMError):
            agent.prepare(game.view("P1"))
        self.assertAlmostEqual(agent.cognition.P_alignment("P4", "EVIL"), .5)

    def test_good_evidence_survives_a_later_invalid_action_but_no_stance_is_published(self):
        game = fixed_game()
        event = game._emit("SOCIAL", actor="P2", target="P4", card="HEDGE", public_writing="P4 is evil.")
        client = SequenceClient([{"language_evidence": [semantic(event)]}, {"nonsense": True}])
        agent = Agent(game.view("P1"), client, max_retries=0)
        with self.assertRaises(LLMError):
            agent.prepare(game.view("P1"))
        self.assertGreater(agent.cognition.P_alignment("P4", "EVIL"), .5)
        self.assertIsNone(agent.plan)
        self.assertEqual(agent.state.public_stances["P4"]["stance"], "UNCERTAIN")

    def test_assassin_uses_own_joint_posterior_not_shared_or_model_numbers(self):
        from avalon.evil_strategy import EvilStrategyManager
        game = fixed_game()
        manager = EvilStrategyManager(game.ids, {"P3", "P4"}, seed=1)
        agent = Agent(game.view("P3"), evil_strategy=manager)
        event = speech(target="P1")
        for seq in range(30, 38):
            e = dict(event, seq=seq)
            agent.cognition.apply_soft_updates([semantic(e, target="P1", strength="strong", reason="privileged_information_signal")], [e], 1)
        self.assertEqual(agent.assassinate(), "P1")
        self.assertAlmostEqual(manager.decisions[-1].confidence, agent.cognition.P_role("P1", "MERLIN"))
        self.assertFalse(any(value is agent.cognition.beliefs for value in vars(manager).values()))
        self.assertAlmostEqual(manager.state.merlin_probabilities["P1"], 1/3)


class TheoryOfMindInterfaceTests(unittest.TestCase):
    def test_interface_is_bounded_detached_and_does_not_change_first_order(self):
        from avalon.theory_of_mind import ModeledBelief, ToMRequest, ToMTrigger, MAX_MODELED_DEPTH
        engine = BeliefEngine(fixed_game().view("P1"))
        before = engine.debug_snapshot()
        source = {"P4": {"EVIL": .6, "GOOD": .4}}
        estimate = ModeledBelief("P1", "P2", source, 5)
        source["P4"]["EVIL"] = 0
        self.assertEqual(estimate.estimated_marginals["P4"]["EVIL"], .6)
        self.assertEqual(MAX_MODELED_DEPTH, 1)
        ToMRequest("P1", "P2", ToMTrigger.HIGH_IMPACT_ACCUSATION)
        with self.assertRaises(ValueError):
            ToMRequest("P1", "P1", ToMTrigger.MERLIN_SEARCH)
        with self.assertRaises(ValueError):
            ModeledBelief("P1", "P2", {"nested": {"P3": {"EVIL": .5}}}, 5)
        self.assertEqual(engine.debug_snapshot(), before)


class AdditionalBoundaryTests(unittest.TestCase):
    def test_partial_public_projection_does_not_erase_speech(self):
        engine = BeliefEngine(fixed_game().view("P1"))
        event = speech()
        partial = {k: v for k, v in event.items() if k != "public_writing"}
        self.assertEqual(len(engine.pending_language([event, partial])), 1)
        engine.apply_soft_updates([semantic(event)], [event, partial], 1)
        self.assertGreater(engine.P_alignment("P4", "EVIL"), .5)

    def test_strategy_cannot_use_the_other_evil_agents_private_posterior(self):
        from avalon.evil_strategy import EvilStrategyManager
        game = fixed_game()
        manager = EvilStrategyManager(game.ids, {"P3", "P4"})
        with self.assertRaises(ValueError):
            manager.tactical_context(game.view("P3"), joint_beliefs=BeliefEngine(game.view("P4")).beliefs)

    def test_retrieval_semantic_pass_and_action_are_three_bounded_calls(self):
        game = fixed_game()
        event = game._emit("SOCIAL", actor="P2", target="P4", card="HEDGE", public_writing="P4 is suspicious.")
        responses = [{"memory_query": ["P4"]}, {"language_evidence": [semantic(event)]}, envelope(valid_plan(game.view("P1")))]
        client = SequenceClient(responses)
        agent = Agent(game.view("P1"), client, chronicle=game.chronicle.reader(), max_retries=0)
        agent.prepare(game.view("P1"))
        self.assertEqual(len(client.contexts), 3)
        self.assertTrue(client.contexts[-1]["retrieval_complete"])
        self.assertTrue(client.contexts[-1]["semantic_pass_complete"])
        self.assertGreater(agent.cognition.P_alignment("P4", "EVIL"), .5)

    def test_invalid_semantic_retry_does_not_consume_evidence(self):
        game = fixed_game()
        event = game._emit("SOCIAL", actor="P2", target="P4", card="HEDGE", public_writing="P4 is suspicious.")
        invalid = {**semantic(event), "strength": .95}
        client = SequenceClient([{"language_evidence": [invalid]}, {"language_evidence": [semantic(event)]},
                                 envelope(valid_plan(game.view("P1")))])
        agent = Agent(game.view("P1"), client, max_retries=1, retry_delay=0)
        agent.prepare(game.view("P1"))
        records = [r for r in agent.cognition.beliefs.update_records if any(e.evidence_type == EvidenceType.LANGUAGE for e in r.evidence)]
        self.assertEqual(len(records), 1)
        self.assertEqual(client.contexts[0]["private_beliefs"], client.contexts[1]["private_beliefs"])

    def test_full_games_exercise_separate_semantic_and_action_stages(self):
        from avalon.terminal import run_game
        from test_agents import model_response
        class Client:
            def __init__(self):
                self.semantic_calls = 0
                self.action_calls = 0
            def complete(self, context):
                if not context["language_interpretation_complete"]:
                    self.semantic_calls += 1
                    o = context["pending_language_observations"][0]
                    return {"language_evidence": [{"origin_event_id": o["event_id"], "target": o["actor"],
                        "signal": "neutral", "strength": "weak", "confidence": "low", "reason_type": "unsupported_certainty"}]}
                self.action_calls += 1
                return envelope(model_response(context))
        for game in (fixed_game(), six_game()):
            clients = {p: Client() for p in game.ids}
            agents = {p: Agent(game.view(p), clients[p], max_retries=0) for p in game.ids}
            run_game(game, agents, write=lambda _: None, strategy_seed=1)
            self.assertEqual(game.phase, "ended")
            self.assertGreater(sum(c.semantic_calls for c in clients.values()), 0)
            self.assertTrue(all(c.action_calls for c in clients.values()))
            for agent in agents.values():
                self.assertAlmostEqual(sum(h.probability for h in agent.cognition.beliefs.hypotheses), 1)

    def test_ids_in_chinese_prose_are_grounded_without_matching_longer_ids(self):
        engine = BeliefEngine(fixed_game().view("P1"))
        event = dict(speech(target="P3"), public_writing="我认为P4前后说法不一致。")
        engine.apply_soft_updates([semantic(event)], [event], 1)
        self.assertGreater(engine.P_alignment("P4", "EVIL"), .5)
        with self.assertRaises(ValueError):
            engine.apply_soft_updates([semantic(dict(event, seq=31))], [dict(event, seq=31, public_writing="P41可疑。")], 1)
