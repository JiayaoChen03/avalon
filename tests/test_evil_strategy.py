"""Acceptance checks for the real, private, code-owned evil coordinator."""

from copy import deepcopy
import importlib.util
import json
import unittest

from avalon.engine import CARDS, Game, Player


def game_for(count=5):
    roles = ["GOOD", "MERLIN", "ASSASSIN", "EVIL", "GOOD", "GOOD"][:count]
    return Game([Player(f"P{i+1}", f"Player {i+1}", role)
                 for i, role in enumerate(roles)], seed=7, direction="clockwise")


class EvilStrategyTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec("avalon.evil_strategy"),
                             "The private evil strategy coordinator is missing")
        from avalon.evil_strategy import EvilStrategyManager
        self.Manager = EvilStrategyManager
        self.game = game_for()
        self.manager = self.make_manager()

    def make_manager(self, seed=7, count=5, controlled=None):
        return self.Manager([f"P{i+1}" for i in range(count)], {"P3", "P4"},
                            seed=seed, controlled_evil_ids=controlled)

    def view(self, pid="P3", phase="discussion", **changes):
        view = self.game.view(pid)
        view.update(phase=phase, **changes)
        return view

    def social(self, seq, actor, target, card="ACCUSE", **changes):
        return {"seq": seq, "kind": "SOCIAL", "round": 1, "attempt": 1,
                "actor": actor, "target": target, "card": card, "reason": "observe",
                **changes}

    def vote_event(self, seq, team, votes, **changes):
        return {"seq": seq, "kind": "TEAM_VOTE", "round": 1, "attempt": 1,
                "team": team, "votes": votes, "approved": sum(votes.values()) > 2,
                **changes}

    def observed_discussion(self, game, manager, team, actions):
        game.propose(game.leader, team)
        for pid in game.speaking_order:
            card, target = actions[pid]
            game.social(pid, {"card": card, "target": target, "reason": "observe"})
        for event in game.events:
            manager.observe(event)

    def observed_vote(self, game, manager, votes):
        game.vote(votes)
        for event in game.events:
            manager.observe(event)

    def sacrifice(self, manager=None):
        manager = manager or self.manager
        manager.state.public_suspicion.update(P3=.82, P4=.23)
        manager.state.public_trust.update(P3=.20, P4=.74)

    def test_initial_estimates_are_hypotheses_without_fictional_history(self):
        state = self.manager.state
        self.assertEqual(state.active_narratives, [])
        self.assertEqual(state.mission_history, [])
        self.assertEqual(state.partner_defense_history, [])
        self.assertEqual(state.public_tags, {p: [] for p in self.game.ids})
        self.assertEqual(state.merlin_probabilities["P3"], 0)
        self.assertEqual(state.merlin_probabilities["P4"], 0)
        self.assertAlmostEqual(sum(state.merlin_probabilities.values()), 1)
        self.assertAlmostEqual(state.merlin_probabilities["P2"], 1/3)

    def test_every_entry_point_rejects_good_and_merlin_even_with_evil_knowledge(self):
        for pid in ("P1", "P2"):
            view = self.game.view(pid)
            for action in (self.manager.tactical_context, self.manager.choose_team,
                           self.manager.vote, self.manager.mission_cards,
                           self.manager.assassinate):
                with self.subTest(pid=pid, action=action.__name__):
                    with self.assertRaises(ValueError):
                        action(view)

    def test_constructor_validates_distinct_ids_and_controlled_membership(self):
        for ids, evil, controlled in ((["P1"]*5, {"P1", "P3"}, None),
                                     (self.game.ids, {"P3"}, None),
                                     (self.game.ids, {"P3", "P9"}, None),
                                     (self.game.ids, {"P3", "P4"}, {"P1"})):
            with self.assertRaises(ValueError):
                self.Manager(ids, evil, controlled_evil_ids=controlled)

    def test_duplicate_public_events_and_reveal_do_not_change_state(self):
        event = self.social(5, "P1", "P3")
        self.manager.observe(event)
        before = self.manager.debug_snapshot()
        self.manager.observe(deepcopy(event))
        self.manager.observe({"seq": 99, "kind": "REVEAL", "roles": {"P2": "MERLIN"}})
        self.assertEqual(self.manager.debug_snapshot(), before)

    def test_social_changes_suspicion_trust_profiles_and_normalized_merlin_hypotheses(self):
        before = deepcopy(self.manager.state)
        self.manager.observe(self.social(1, "P1", "P3"))
        after = self.manager.state
        self.assertGreater(after.public_suspicion["P3"], before.public_suspicion["P3"])
        self.assertLess(after.public_trust["P3"], before.public_trust["P3"])
        self.assertGreater(after.profiles["P1"]["aggression"], .5)
        self.assertGreater(after.merlin_probabilities["P1"], 1/3)
        self.assertLess(max(after.merlin_probabilities.values()), .6)
        self.assertAlmostEqual(sum(after.merlin_probabilities.values()), 1)
        self.assertEqual(after.merlin_probabilities["P3"], 0)

    def test_consistently_rejecting_dirty_teams_builds_merlin_likelihood(self):
        for seq in range(1, 5):
            self.manager.observe(self.vote_event(seq, ["P3", "P5"],
                                 {"P1": True, "P2": False, "P3": True,
                                  "P4": True, "P5": True}, attempt=seq))
        self.assertGreater(self.manager.state.merlin_probabilities["P2"], .4)
        self.assertLess(self.manager.state.merlin_probabilities["P2"], .95)
        self.assertIn("follows_consensus", self.manager.state.public_tags["P1"])
        self.assertGreater(self.manager.state.pair_suspicion, .1)

    def test_mission_outcomes_update_suspicion_trust_and_competing_narratives(self):
        self.manager.observe({"seq": 1, "kind": "MISSION", "round": 1, "attempt": 1,
                              "team": ["P1", "P3"], "success": False, "fail_count": 1,
                              "successes": 0, "failures": 1})
        state = self.manager.state
        self.assertGreater(state.public_suspicion["P1"], .4)
        self.assertLess(state.public_trust["P1"], .5)
        self.assertEqual(len(state.mission_history), 1)
        self.assertGreaterEqual(len(state.active_narratives), 2)
        self.assertLessEqual(len(state.active_narratives), 4)
        self.assertTrue(all(n["evidence"] == [1] for n in state.active_narratives))
        self.assertNotEqual(state.active_narratives[0]["targets"],
                            state.active_narratives[1]["targets"])

    def test_seed_controls_initial_role_variation_and_repeatability(self):
        assignments = set()
        for seed in range(12):
            first, second = self.make_manager(seed), self.make_manager(seed)
            first_context = first.tactical_context(self.view()).to_dict()
            self.assertEqual(first_context, second.tactical_context(self.view()).to_dict())
            assignments.add(first.state.roles["P3"])
        self.assertEqual(assignments, {"Aggressor", "Sleeper"})

    def test_roles_exchange_when_the_former_sleeper_becomes_exposed(self):
        state = self.manager.state
        old_sleeper = next(p for p, role in state.roles.items() if role == "Sleeper")
        old_aggressor = next(p for p, role in state.roles.items() if role == "Aggressor")
        state.public_suspicion[old_sleeper] = .75
        state.public_trust[old_sleeper] = .25
        state.public_suspicion[old_aggressor] = .2
        state.public_trust[old_aggressor] = .8
        self.manager.tactical_context(self.view())
        self.assertEqual(state.roles[old_sleeper], "Aggressor")
        self.assertEqual(state.roles[old_aggressor], "Sleeper")

    def test_high_pair_suspicion_selects_asymmetric_fake_conflict(self):
        self.manager.state.pair_suspicion = .92
        first = self.manager.tactical_context(self.view("P3")).to_dict()
        second = self.manager.tactical_context(self.view("P4")).to_dict()
        self.assertEqual(first["strategy_mode"], "FAKE_CONFLICT")
        self.assertEqual(second["strategy_mode"], "FAKE_CONFLICT")
        by_role = {c["role"]: c for c in (first, second)}
        self.assertEqual(by_role["Aggressor"]["primary_objective"], "CREATE_DISTANCE_FROM_PARTNER")
        self.assertEqual(by_role["Sleeper"]["primary_objective"], "MAINTAIN_INDEPENDENCE")
        self.assertEqual(by_role["Aggressor"]["primary_target"], by_role["Aggressor"]["evil_partner"])
        self.assertNotIn(by_role["Sleeper"]["primary_target"], {"P3", "P4"})

    def test_distance_responds_to_round_exposure_trust_pairing_and_agreement(self):
        baseline = self.make_manager().tactical_context(self.view()).distance_strength
        for change in ("pair", "suspicion", "trust", "agreement", "round"):
            manager, view = self.make_manager(), self.view()
            if change == "pair":
                manager.state.pair_suspicion = .9
            elif change == "suspicion":
                manager.state.public_suspicion.update(P3=.7, P4=.7)
            elif change == "trust":
                manager.state.public_trust.update(P3=.1, P4=.1)
            elif change == "agreement":
                manager.state.partner_agreement_streak = 4
            else:
                view.update(round=4, team_size=3)
            with self.subTest(change=change):
                distance = manager.tactical_context(view).distance_strength
                self.assertGreater(distance, baseline)
                self.assertLessEqual(distance, 1)

    def test_literal_sacrifice_works_in_first_round_without_role_disclosure(self):
        self.sacrifice()
        exposed = self.manager.tactical_context(self.view("P3")).to_dict()
        safe = self.manager.tactical_context(self.view("P4")).to_dict()
        self.assertEqual(exposed["strategy_mode"], "SACRIFICE")
        self.assertEqual(self.manager.state.sacrifice_target, "P3")
        self.assertEqual(exposed["primary_objective"], "SACRIFICE_SELF")
        self.assertEqual(exposed["secondary_objective"], "CAUSE_UNCERTAINTY")
        self.assertNotIn(exposed["primary_target"], {"P3", "P4"})
        self.assertEqual(safe["primary_objective"], "SACRIFICE_PARTNER")
        self.assertEqual(safe["primary_target"], "P3")

    def test_high_suspicion_without_a_safe_partner_causes_crisis_not_sacrifice(self):
        self.manager.state.public_suspicion.update(P3=.85, P4=.79)
        self.manager.state.public_trust.update(P3=.18, P4=.24)
        self.assertEqual(self.manager.tactical_context(self.view()).strategy_mode, "CRISIS_RECOVERY")
        self.assertIsNone(self.manager.state.sacrifice_target)

    def test_merlin_hunt_uses_probability_concentration(self):
        self.manager.state.merlin_probabilities.update(P1=.1, P2=.8, P5=.1)
        context = self.manager.tactical_context(self.view()).to_dict()
        self.assertEqual(context["strategy_mode"], "MERLIN_HUNT")
        self.assertEqual(context["primary_target"], "P2")
        self.assertIn(context["primary_objective"], {"PROBE_MERLIN", "OBSERVE_MERLIN_REACTION"})

    def test_consensus_needs_real_partner_seed_and_intervening_other_speaker(self):
        self.manager.observe(self.social(1, "P3", "P1"))
        self.manager.observe(self.social(2, "P5", "P2", "HEDGE"))
        context = self.manager.tactical_context(self.view("P4")).to_dict()
        self.assertEqual(context["strategy_mode"], "CONSENSUS_SEEDING")
        self.assertEqual(context["primary_objective"], "REINFORCE_NARRATIVE")
        self.assertEqual(context["primary_target"], "P1")

    def test_adjacent_partner_speech_cannot_mechanically_reinforce_the_seed(self):
        self.manager.observe(self.social(1, "P3", "P1"))
        context = self.manager.tactical_context(self.view("P4")).to_dict()
        self.assertNotEqual(context["primary_objective"], "REINFORCE_NARRATIVE")
        self.assertNotEqual(context["primary_target"], "P1")

    def test_agenda_capture_is_selected_from_public_polarization(self):
        for seq, actor in enumerate(("P1", "P2", "P5"), 1):
            self.manager.observe(self.social(seq, actor, "P3", "PRESSURE"))
        context = self.manager.tactical_context(self.view()).to_dict()
        self.assertEqual(context["strategy_mode"], "AGENDA_CAPTURE")
        self.assertEqual(context["primary_objective"], "CONTROL_AGENDA")
        self.assertTrue(context["agenda_topic"])

    def test_public_tags_are_soft_target_modifiers(self):
        chosen = set()
        for target in ("P1", "P2", "P5"):
            manager = self.make_manager()
            manager.state.public_tags[target] = ["emotional", "follows_consensus"]
            chosen.add(manager.tactical_context(self.view()).primary_target)
        self.assertEqual(chosen, {"P1", "P2", "P5"})

    def test_repeated_partner_defense_raises_pairing_and_blocks_more_defense(self):
        for seq in range(1, 4):
            self.manager.observe(self.social(seq, "P3", "P4", "DEFEND", attempt=seq))
        state = self.manager.state
        self.assertGreater(state.pair_suspicion, .2)
        self.assertEqual(len(state.partner_defense_history), 3)
        context = self.manager.tactical_context(self.view("P3", attempt=4)).to_dict()
        if context["primary_target"] == "P4":
            self.assertNotIn("DEFEND", context["allowed_cards"])

    def test_phase_selection_and_retry_context_are_stable_but_scores_refresh(self):
        view = self.view()
        context = self.manager.tactical_context(view).to_dict()
        scores = deepcopy(self.manager.state.mode_scores)
        for seq in range(1, 7):
            self.manager.observe(self.social(seq, "P1", "P3", "PRESSURE"))
        self.assertEqual(self.manager.tactical_context(view).to_dict(), context)
        self.assertNotEqual(self.manager.state.mode_scores, scores)
        partner = self.manager.tactical_context(self.view("P4")).to_dict()
        self.assertEqual(partner["strategy_mode"], context["strategy_mode"])
        self.manager.tactical_context(self.view("P3"), phase="vote")
        self.assertNotEqual(self.manager.state.mode_scores, scores)

    def test_tactical_projection_and_debug_output_are_detached_and_bounded(self):
        for seq in range(1, 25):
            self.manager.observe(self.social(seq, "P1", "P3", "ACCUSE"))
        context = self.manager.tactical_context(self.view())
        first = context.to_dict()
        self.assertEqual(set(first), {"strategy_mode", "role", "primary_objective",
            "secondary_objective", "primary_target", "evil_partner", "distance_strength",
            "active_narratives", "agenda_topic", "constraints", "relevant_public_events", "allowed_cards"})
        self.assertTrue(set(first["allowed_cards"]) <= set(CARDS))
        self.assertTrue(first["allowed_cards"])
        self.assertLessEqual(len(first["active_narratives"]), 4)
        self.assertLessEqual(len(first["relevant_public_events"]), 8)
        self.assertTrue(all(type(e) is dict and e["seq"] in range(1, 25)
                            for e in first["relevant_public_events"]))
        self.assertLess(len(json.dumps(first)), 7000)
        first["allowed_cards"].clear()
        self.assertTrue(context.to_dict()["allowed_cards"])
        snapshot = self.manager.debug_snapshot()
        snapshot["public_suspicion"]["P3"] = -50
        self.assertGreaterEqual(self.manager.state.public_suspicion["P3"], 0)

    def test_team_choices_are_legal_stable_and_preserve_safe_sacrifice_partner(self):
        for count in (5, 6):
            manager, game = self.make_manager(count=count), game_for(count)
            self.sacrifice(manager)
            for round_no, size in enumerate((2, 3, 2, 3, 3) if count == 5 else (2, 3, 4, 3, 4), 1):
                view = game.view("P4")
                view.update(round=round_no, team_size=size)
                team = manager.choose_team(view)
                self.assertEqual(len(team), size)
                self.assertEqual(len(set(team)), size)
                self.assertTrue(set(team) <= set(game.ids))
                self.assertIn("P4", team)
                self.assertNotIn("P3", team)
                self.assertEqual(manager.choose_team(view), team)
                team.clear()
                self.assertEqual(len(manager.choose_team(view)), size)

    def test_fake_conflict_votes_diverge_without_throwing_decisive_dirty_mission(self):
        self.manager.state.pair_suspicion = .95
        views = [self.view(p, team=["P3", "P4"]) for p in ("P3", "P4")]
        votes = [self.manager.vote(view) for view in views]
        self.assertEqual(set(votes), {False, True})
        decisive = self.make_manager()
        decisive.state.pair_suspicion = .95
        self.assertTrue(all(decisive.vote(dict(view, failures=2)) for view in views))

    def test_sacrifice_partner_rejects_the_exposed_members_team(self):
        self.sacrifice()
        self.assertFalse(self.manager.vote(self.view("P4", team=["P1", "P3"])))
        self.assertTrue(self.manager.vote(self.view("P3", team=["P1", "P3"])))

    def test_fifth_rejection_is_an_evil_win_and_clean_decisive_team_is_rejected(self):
        for pid in ("P3", "P4"):
            self.assertFalse(self.manager.vote(self.view(pid, attempt=5, team=["P3", "P4"])))
        manager = self.make_manager()
        for pid in ("P3", "P4"):
            self.assertFalse(manager.vote(self.view(pid, successes=2, team=["P1", "P2"])))

    def test_mission_assignment_is_stable_single_fail_and_varies_across_seeds(self):
        owners = set()
        for seed in range(16):
            manager = self.make_manager(seed)
            view = self.view(phase="mission", team=["P3", "P4"], failures=2)
            cards = manager.mission_cards(view)
            self.assertEqual(set(cards), {"P3", "P4"})
            self.assertEqual(list(cards.values()).count("FAIL"), 1)
            owners.add(next(p for p, card in cards.items() if card == "FAIL"))
            self.assertEqual(manager.mission_cards(view), cards)
            cards.clear()
            self.assertEqual(len(manager.mission_cards(view)), 2)
        self.assertEqual(owners, {"P3", "P4"})

    def test_exposure_and_ownership_history_affect_sabotage_owner(self):
        self.sacrifice()
        cards = self.manager.mission_cards(self.view(phase="mission", team=["P3", "P4"], failures=2))
        self.assertEqual(cards, {"P3": "FAIL", "P4": "SUCCESS"})
        manager = self.make_manager()
        owners = []
        for round_no in range(1, 6):
            cards = manager.mission_cards(self.view(phase="mission", round=round_no,
                   team_size=(2, 3, 2, 3, 3)[round_no-1], team=["P3", "P4"], failures=2))
            owners.append(next(p for p, card in cards.items() if card == "FAIL"))
        self.assertEqual(set(owners), {"P3", "P4"})

    def test_external_human_fail_is_authoritative_and_not_exposed(self):
        manager = self.make_manager(controlled={"P4"})
        view = self.view("P4", phase="mission", team=["P3", "P4"])
        cards = manager.mission_cards(view, {"P3": "FAIL"})
        self.assertEqual(cards, {"P4": "SUCCESS"})
        self.assertIsNone(manager.state.mission_fail_owner)
        self.assertNotIn("external_cards", manager.debug_snapshot())
        self.assertNotIn("P3", [d.agent_id for d in manager.decisions])

    def test_external_human_evil_success_allows_decisive_ai_fail(self):
        manager = self.make_manager(controlled={"P4"})
        view = self.view("P4", phase="mission", team=["P1", "P3", "P4"], failures=2)
        self.assertEqual(manager.mission_cards(view, {"P3": "SUCCESS"}),
                         {"P4": "FAIL"})

    def test_external_good_cards_are_rejected_even_when_the_card_is_success(self):
        for card in ("SUCCESS", "FAIL"):
            with self.subTest(card=card):
                manager = self.make_manager(controlled={"P4"})
                view = self.view("P4", phase="mission", team=["P1", "P3", "P4"], failures=2)
                with self.assertRaises(ValueError):
                    manager.mission_cards(view, {"P1": card, "P3": "SUCCESS"})
                self.assertEqual(manager.mission_cards(view, {"P3": "SUCCESS"}), {"P4": "FAIL"})

    def test_external_cards_validate_membership_legality_and_incompatible_repeats(self):
        manager = self.make_manager(controlled={"P4"})
        view = self.view("P4", phase="mission", team=["P1", "P3", "P4"])
        for external in ({"P2": "SUCCESS"}, {"P1": "FAIL"}, {"P3": "BAD"},
                         {"P4": "SUCCESS"}, {"P9": "FAIL"}):
            with self.assertRaises(ValueError):
                manager.mission_cards(view, external)
        manager.mission_cards(view, {"P3": "SUCCESS"})
        with self.assertRaises(ValueError):
            manager.mission_cards(view, {"P3": "FAIL"})

    def test_mission_assignments_exclude_absent_or_uncontrolled_members(self):
        self.assertEqual(self.manager.mission_cards(self.view(phase="mission", team=["P1", "P2"])), {})
        manager = self.make_manager(controlled={"P4"})
        self.assertEqual(manager.mission_cards(self.view(phase="mission", team=["P1", "P3"])), {})
        manager = self.make_manager()
        self.assertEqual(manager.mission_cards(self.view(phase="mission", team=["P1", "P4"], successes=2)),
                         {"P4": "FAIL"})

    def test_assassination_uses_code_likelihood_and_never_true_merlin_identity(self):
        self.manager.state.merlin_probabilities.update(P1=.8, P2=.1, P5=.1)
        view = self.view(phase="assassination", successes=3)
        view["merlin_probabilities"] = {"P2": 1}
        view["true_merlin"] = "P2"
        self.assertEqual(self.manager.assassinate(view), "P1")
        self.assertEqual(self.manager.assassinate(view), "P1")
        self.assertNotIn("true_merlin", json.dumps(self.manager.debug_snapshot()))

    def test_decisions_are_structured_and_repeated_actions_do_not_duplicate_them(self):
        from dataclasses import asdict, is_dataclass
        view = self.view(team=["P1", "P3"])
        vote = self.manager.vote(view)
        count = len(self.manager.decisions)
        self.assertEqual(self.manager.vote(view), vote)
        self.assertEqual(len(self.manager.decisions), count)
        self.assertGreater(count, 0)
        for decision in self.manager.decisions:
            self.assertTrue(is_dataclass(decision))
            record = asdict(decision)
            self.assertTrue({"round", "attempt", "phase", "agent_id", "strategy_mode",
                "primary_objective", "secondary_objective", "target", "confidence"} <= record.keys())
            self.assertNotIn("reasoning", record)
            json.dumps(record)

    def test_public_joint_allegation_increases_pair_suspicion_without_storing_prose(self):
        before = self.manager.state.pair_suspicion
        event = self.social(1, "P1", "P3", statement="P3 and P4 may both be evil.")
        self.manager.observe(event)
        self.assertGreater(self.manager.state.pair_suspicion, before)
        history = self.manager.state.pair_allegation_history
        self.assertEqual(history, [{"seq": 1, "targets": ["P3", "P4"]}])
        self.assertNotIn("may both", json.dumps(self.manager.debug_snapshot()))
        self.manager.observe(self.social(2, "P2", "P4", statement="P3 和 P4 可能是一伙坏人。"))
        self.assertEqual(self.manager.tactical_context(self.view()).strategy_mode, "FAKE_CONFLICT")

    def test_joint_suspicion_itself_increases_fake_conflict_score(self):
        self.manager.tactical_context(self.view())
        old_score = self.manager.state.mode_scores["FAKE_CONFLICT"]
        self.manager.state.public_suspicion.update(P3=.62, P4=.62)
        self.manager.tactical_context(self.view(attempt=2))
        self.assertGreater(self.manager.state.mode_scores["FAKE_CONFLICT"], old_score)

    def test_sacrifice_records_the_non_evil_player_being_framed(self):
        self.sacrifice()
        context = self.manager.tactical_context(self.view("P3"))
        self.assertIn(context.primary_target, getattr(self.manager.state, "framed_players", []))
        self.assertTrue(set(self.manager.state.framed_players) <= {"P1", "P2", "P5"})

    def test_profile_tags_distinguish_caution_grounded_reasoning_and_leadership(self):
        self.manager.observe({"seq": 1, "kind": "MISSION", "round": 1, "attempt": 1,
            "team": ["P1", "P3"], "success": False, "fail_count": 1, "successes": 0, "failures": 1})
        for seq in (2, 3, 4):
            self.manager.observe(self.social(seq, "P2", "P3", "HEDGE",
                reason="mission_record", evidence=[1]))
        self.assertIn("cautious", self.manager.state.public_tags["P2"])
        self.assertIn("logic_driven", self.manager.state.public_tags["P2"])
        self.manager.observe(self.social(5, "P1", "P4"))
        self.manager.observe(self.social(6, "P2", "P4"))
        self.manager.observe(self.social(7, "P1", "P4"))
        self.manager.observe(self.social(8, "P5", "P4"))
        self.assertIn("leader", self.manager.state.public_tags["P1"])

    def test_merlin_likelihood_changes_after_mission_verifies_prior_vote_accuracy(self):
        self.manager.observe(self.vote_event(1, ["P3", "P5"],
            {"P1": True, "P2": False, "P3": True, "P4": True, "P5": True}))
        before = self.manager.state.merlin_probabilities["P2"]
        self.manager.observe({"seq": 2, "kind": "MISSION", "round": 1, "attempt": 1,
            "team": ["P3", "P5"], "success": False, "fail_count": 1, "successes": 0, "failures": 1})
        self.assertGreater(self.manager.state.merlin_probabilities["P2"], before)
        self.assertAlmostEqual(sum(self.manager.state.merlin_probabilities.values()), 1)

    def test_consensus_carries_a_grounded_seed_to_the_next_real_proposal(self):
        game, manager = self.game, self.manager
        for event in game.events:
            manager.observe(event)
        game.propose(game.leader, ["P1", "P3"])
        manager.observe(game.events[-1])
        for pid in game.speaking_order:
            if pid in manager.evil_ids:
                context = manager.tactical_context(game.view(pid))
                action = {"card": "BAIT", "target": "P5", "reason": "observe"}
            else:
                action = {"card": "HEDGE", "target": "P2", "reason": "observe"}
            game.social(pid, action)
            manager.observe(game.events[-1])
        game.vote({p: False for p in game.ids})
        for event in game.events:
            manager.observe(event)
        game.propose(game.leader, ["P2", "P4"])
        manager.observe(game.events[-1])
        mode = manager.tactical_context(game.view("P3")).strategy_mode
        self.assertEqual(mode, "CONSENSUS_SEEDING")
        self.assertTrue(all(n["evidence"] for n in manager.state.active_narratives))

    def test_assassination_action_matches_its_recorded_tactical_target_even_on_ties(self):
        for seed in range(10):
            manager = self.make_manager(seed)
            view = self.view(phase="assassination", successes=3)
            context = manager.tactical_context(view)
            target = manager.assassinate(view)
            self.assertEqual(target, context.primary_target)
            decision = manager.decisions[-1]
            self.assertEqual(decision.target, target)
            self.assertEqual(decision.action["target"], target)

    def test_human_evil_card_must_arrive_before_assigning_ai_sabotage(self):
        manager = self.make_manager(controlled={"P4"})
        with self.assertRaisesRegex(ValueError, "External"):
            manager.mission_cards(self.view("P4", phase="mission", team=["P3", "P4"]))

    def test_normal_roles_can_build_trust_and_increase_a_public_targets_suspicion(self):
        state = self.manager.state
        aggressor = next(p for p, role in state.roles.items() if role == "Aggressor")
        sleeper = next(p for p, role in state.roles.items() if role == "Sleeper")
        state.public_suspicion["P1"] = .7
        attack = self.manager.tactical_context(self.view(aggressor))
        support = self.manager.tactical_context(self.view(sleeper))
        self.assertEqual(attack.primary_objective, "INCREASE_TARGET_SUSPICION")
        self.assertEqual(attack.primary_target, "P1")
        self.assertEqual(support.primary_objective, "BUILD_TRUST")
        self.assertIn("DEFEND", support.allowed_cards)

    def test_normal_partner_support_is_available_once_then_limited(self):
        state = self.manager.state
        sleeper = next(p for p, role in state.roles.items() if role == "Sleeper")
        aggressor = next(p for p, role in state.roles.items() if role == "Aggressor")
        self.manager.observe(self.social(1, "P1", aggressor, "PRESSURE"))
        support = self.manager.tactical_context(self.view(sleeper))
        self.assertEqual(support.primary_objective, "REDUCE_PARTNER_SUSPICION")
        self.assertEqual(support.primary_target, aggressor)
        self.assertIn("DEFEND", support.allowed_cards)
        self.manager.observe(self.social(2, sleeper, aggressor, "DEFEND"))
        later = self.manager.tactical_context(self.view(sleeper, attempt=2))
        self.assertNotEqual(later.primary_objective, "REDUCE_PARTNER_SUSPICION")

    def test_target_tags_do_not_override_strong_public_evidence(self):
        self.manager.state.public_tags["P1"] = ["emotional", "follows_consensus"]
        self.manager.state.public_suspicion["P2"] = .95
        self.manager.state.public_trust["P2"] = .05
        self.assertEqual(self.manager.tactical_context(self.view()).primary_target, "P2")

    def test_denial_of_a_pair_allegation_is_not_counted_as_an_accusation(self):
        self.manager.observe(self.social(1, "P1", "P3", "DEFEND", statement="P3 and P4 are not evil."))
        self.assertEqual(self.manager.state.pair_suspicion, 0)

    def test_unanimous_vote_narratives_do_not_invent_nonexistent_voters(self):
        self.manager.observe(self.vote_event(1, ["P1", "P3"], {p: True for p in self.game.ids}))
        narratives = self.manager.state.active_narratives
        self.assertGreaterEqual(len(narratives), 2)
        self.assertTrue(all(n["targets"] for n in narratives))
        self.assertTrue(all(n["evidence"] == [1] for n in narratives))

    def test_non_assassin_cannot_mutate_strategy_by_requesting_assassination(self):
        before = self.manager.debug_snapshot()
        with self.assertRaises(ValueError):
            self.manager.assassinate(self.view("P4", phase="assassination", successes=3))
        self.assertEqual(self.manager.debug_snapshot(), before)

    def test_tactical_preparation_does_not_record_an_unaccepted_social_action(self):
        context = self.manager.tactical_context(self.view())
        self.assertEqual(self.manager.decisions, [])
        self.assertEqual(self.manager.state.primary_objectives["P3"], context.primary_objective)
        self.assertEqual(self.manager.tactical_context(self.view()).to_dict(), context.to_dict())
        self.assertEqual(self.manager.decisions, [])

    def test_accepted_social_action_is_recorded_once_with_actual_structured_fields(self):
        game, manager = self.game, self.manager
        game.propose(game.leader, ["P1", "P3"])
        for event in game.events:
            manager.observe(event)
        team_seq = game.events[-1]["seq"]
        for pid in game.speaking_order:
            if pid == "P3":
                break
            game.social(pid, {"card": "HEDGE", "target": "P2", "reason": "observe"})
            manager.observe(game.events[-1])
        context = manager.tactical_context(game.view("P3"))
        action = {"card": context.allowed_cards[-1], "target": context.primary_target,
                  "reason": "observe", "statement": "我想核验目前的公开依据。",
                  "rationale": "提案中的安排还需要结合后续表现来判断。", "evidence": [team_seq]}
        game.social("P3", action)
        event = game.events[-1]
        manager.observe(event)
        self.assertEqual(len(manager.decisions), 1)
        decision = manager.decisions[0]
        self.assertEqual(decision.phase, "discussion")
        self.assertEqual(decision.agent_id, "P3")
        self.assertEqual(decision.primary_objective, context.primary_objective)
        self.assertEqual(decision.action, {"kind": "social", "seq": event["seq"],
            "card": action["card"], "target": action["target"], "reason": "observe", "evidence": [team_seq]})
        manager.observe(deepcopy(event))
        manager.tactical_context(game.view("P3"))
        self.assertEqual(len(manager.decisions), 1)
        record = json.dumps(manager.debug_snapshot()["decisions"])
        self.assertNotIn("statement", record)
        self.assertNotIn("rationale", record)

    def test_historical_or_uncontrolled_social_events_do_not_invent_strategy_actions(self):
        manager = self.make_manager(controlled={"P4"})
        manager.tactical_context(self.view("P3"))
        manager.observe(self.social(1, "P3", "P1"))
        manager.observe(self.social(2, "P4", "P2"))
        self.assertEqual(manager.decisions, [])

    def test_exhausted_model_retries_leave_no_social_strategy_decision(self):
        from avalon.agents import Agent
        from avalon.llm import LLMError

        class RejectingClient:
            def complete(self, context):
                raise LLMError("invalid_plan")

        self.game.propose(self.game.leader, ["P1", "P3"])
        view = self.game.view("P3")
        agent = Agent(view, RejectingClient(), evil_strategy=self.manager,
                      max_retries=1, retry_delay=0)
        with self.assertRaises(LLMError):
            agent.prepare(view)
        self.assertEqual(agent.calls, {1: 2})
        self.assertEqual(self.manager.decisions, [])
        self.assertFalse(any(e["kind"] == "SOCIAL" for e in self.game.events))

    def test_public_accusations_and_independent_support_can_reach_sacrifice(self):
        game, manager = self.game, self.manager
        actions = {"P1": ("ACCUSE", "P3"), "P2": ("ACCUSE", "P3"),
                   "P3": ("HEDGE", "P1"), "P4": ("HEDGE", "P2"), "P5": ("DEFEND", "P4")}
        for attempt in range(1, 5):
            self.observed_discussion(game, manager, ["P1", "P2"], actions)
            if attempt < 4:
                self.observed_vote(game, manager, {p: False for p in game.ids})
        context = manager.tactical_context(game.view("P3"), phase="vote")
        self.assertEqual(game.attempt, 4)
        self.assertEqual(context.strategy_mode, "SACRIFICE")
        self.assertEqual(manager.state.sacrifice_target, "P3")
        self.assertGreaterEqual(manager.state.public_suspicion["P3"], .78)
        self.assertLessEqual(manager.state.public_suspicion["P4"], .4)
        self.assertGreaterEqual(manager.state.public_trust["P4"], .60)
        self.assertEqual(context.primary_objective, "SACRIFICE_SELF")

    def test_public_pressure_on_both_evil_seats_can_reach_crisis_recovery(self):
        game, manager = self.game, self.manager
        for attempt in range(1, 4):
            actions = {"P1": ("ACCUSE", "P3"), "P2": ("ACCUSE", "P4"),
                       "P3": ("HEDGE", "P1"), "P4": ("HEDGE", "P2"),
                       "P5": ("ACCUSE", "P3" if attempt % 2 else "P4")}
            self.observed_discussion(game, manager, ["P1", "P2"], actions)
            if attempt < 3:
                self.observed_vote(game, manager, {p: p == "P3" for p in game.ids})
        context = manager.tactical_context(game.view("P3"), phase="vote")
        self.assertEqual(context.strategy_mode, "CRISIS_RECOVERY")
        self.assertTrue(all(manager.state.public_suspicion[p] >= .65 for p in ("P3", "P4")))
        self.assertIsNone(manager.state.sacrifice_target)

    def test_repeated_public_accurate_reads_can_reach_merlin_hunt(self):
        game, manager = game_for(6), self.make_manager(count=6)
        actions = {p: ("HEDGE", "P1") for p in game.ids}
        actions["P2"] = ("ACCUSE", "P3")
        for attempt in range(4):
            self.observed_discussion(game, manager, ["P1", "P3"], actions)
            supporters = {"P1", "P3", "P5"} if attempt < 3 else {"P1", "P3", "P5", "P6"}
            self.observed_vote(game, manager, {p: p in supporters for p in game.ids})
        game.resolve_mission({"P1": "SUCCESS", "P3": "FAIL"})
        for event in game.events:
            manager.observe(event)
        context = manager.tactical_context(game.view("P3"))
        self.assertEqual((game.round, game.failures), (2, 1))
        self.assertEqual(context.strategy_mode, "MERLIN_HUNT")
        self.assertEqual(context.primary_objective, "PROBE_MERLIN")
        self.assertEqual(context.primary_target, "P2")
        self.assertGreater(manager.state.merlin_probabilities["P2"], .45)
        self.assertLess(manager.state.merlin_probabilities["P2"], .95)


if __name__ == "__main__":
    unittest.main()
