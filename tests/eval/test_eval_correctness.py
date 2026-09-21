"""Deterministic mathematical/epistemic oracles. No model or network calls."""

from collections import Counter
from copy import deepcopy
from itertools import permutations
import math
import socket

import pytest

from avalon.cognition import BeliefEngine
from avalon.engine import EVIL_ROLES, Game, Player
from avalon.evidence import Observation
from avalon.joint_beliefs import BeliefContradiction, JointBeliefState, JointHypothesis, enumerate_hypotheses
from avalon.eval.beliefs import BaselineBeliefs, JointBeliefs, authorized_worlds, score_beliefs


@pytest.fixture(autouse=True)
def no_external_calls(monkeypatch):
    def reject(*args, **kwargs):
        raise AssertionError("Correctness tests must not use a network")
    monkeypatch.setattr(socket.socket, "connect", reject)
    monkeypatch.setattr(socket, "create_connection", reject)


def game_for_test(count=5):
    roles = ["GOOD", "MERLIN", "ASSASSIN", "EVIL", "GOOD"] + (["GOOD"] if count == 6 else [])
    return Game([Player(f"P{i + 1}", f"Seat {i + 1}", role) for i, role in enumerate(roles)], seed=17)


def mission(seq=40, round_no=1, team=("P3", "P4"), fails=1):
    return {"seq": seq, "round": round_no, "attempt": 1, "kind": "MISSION", "team": list(team),
            "fail_count": fails, "success": fails == 0, "fail_threshold": 1}


def truth_of(game):
    return {pid: p.role for pid, p in game.players.items()}


@pytest.mark.parametrize("count,expected", [(5, 60), (6, 120)])
def test_legal_hypotheses_equal_independent_permutation_oracle(count, expected):
    game = game_for_test(count)
    counts = dict(Counter(truth_of(game).values()))
    generated = enumerate_hypotheses(game.ids, counts)
    oracle = {tuple(zip(game.ids, roles)) for roles in permutations(truth_of(game).values())}
    assert {h.key for h in generated} == oracle
    assert len(generated) == len(oracle) == expected
    assert all(Counter(h.roles.values()) == Counter(counts) for h in generated)
    assert math.fsum(h.probability for h in generated) == pytest.approx(1)


@pytest.mark.parametrize("count", [5, 6])
@pytest.mark.parametrize("pid", ["P1", "P2", "P3", "P4", "P5"])
def test_role_count_and_private_information_constraints(count, pid):
    game = game_for_test(count)
    view = game.view(pid)
    engine = BeliefEngine(view)
    knowledge = view["private_knowledge"]
    for h in engine.beliefs.hypotheses:
        assert Counter(h.roles.values()) == Counter(view["rules"]["role_counts"])
        assert h.roles[pid] == game.players[pid].role
        assert all(h.roles[p] in EVIL_ROLES for p in knowledge["known_evil_players"])
        assert all(h.roles[p] not in EVIL_ROLES for p in knowledge["known_good_players"])
    assert {h.key for h in engine.beliefs.hypotheses} == set(authorized_worlds(view))
    assert tuple(sorted(truth_of(game).items())) in authorized_worlds(view)


def test_hard_evidence_eliminates_exactly_impossible_hypotheses_and_never_revives():
    engine = BeliefEngine(game_for_test().view("P1"))
    prior = {h.key for h in engine.beliefs.hypotheses}
    expected = {key for key in prior if all(dict(key)[p] in EVIL_ROLES for p in ("P3", "P4"))}
    engine.observe(mission(fails=2))
    assert {h.key for h in engine.beliefs.hypotheses} == expected
    dead = prior - expected
    for seq in range(41, 85):
        engine.observe({"seq": seq, "round": 2, "attempt": 1, "kind": "SOCIAL", "actor": "P3",
                        "target": "P4", "card": "DEFEND", "public_writing": "P4 has my support."})
    engine.observe(mission(seq=85, round_no=3, fails=0))
    engine.beliefs.normalize()
    assert not dead & {h.key for h in engine.beliefs.hypotheses}
    assert dead <= engine.beliefs.eliminated_keys
    assert engine.P_joint({"P3": "GOOD"}) == 0
    assert engine.P_joint({"P4": "GOOD"}) == 0


def test_successful_quest_does_not_prove_an_all_good_team():
    engine = BeliefEngine(game_for_test().view("P1"))
    before = {h.key for h in engine.beliefs.hypotheses}
    engine.observe(mission(fails=0))
    assert {h.key for h in engine.beliefs.hypotheses} == before


def test_normalization_and_marginals_match_manual_weighted_oracle():
    engine = BeliefEngine(game_for_test().view("P1"))
    for index, h in enumerate(engine.beliefs.hypotheses, 1):
        h.probability = index
    total = sum(range(1, len(engine.beliefs.hypotheses) + 1))
    expected = {h.key: index / total for index, h in enumerate(engine.beliefs.hypotheses, 1)}
    engine.beliefs.normalize()
    assert sum(h.probability for h in engine.beliefs.hypotheses) == pytest.approx(1)
    for pid in engine.ids:
        for role in engine.beliefs.role_counts:
            manual = sum(p for key, p in expected.items() if dict(key)[pid] == role)
            assert engine.P_role(pid, role) == pytest.approx(manual)
        evil = sum(p for key, p in expected.items() if dict(key)[pid] in EVIL_ROLES)
        assert engine.P_alignment(pid, "EVIL") == pytest.approx(evil)
    assert sum(engine.P_alignment(p, "EVIL") for p in engine.ids) == pytest.approx(2)


def test_numerical_underflow_and_explicit_zero_have_different_semantics():
    engine = BeliefEngine(game_for_test().view("P1"))
    dead = deepcopy(engine.beliefs.hypotheses[-1])
    engine.beliefs.hypotheses[-1].probability = 0
    engine.beliefs.hypotheses[0].log_probability = -1e200
    engine.beliefs.normalize()
    assert engine.beliefs.hypotheses[0].probability > 0
    assert dead.key in engine.beliefs.eliminated_keys
    dead.probability = .9
    engine.beliefs.hypotheses.append(dead)
    engine.beliefs.normalize()
    assert dead.key not in {h.key for h in engine.beliefs.hypotheses}


def test_contradictory_hard_evidence_is_atomic():
    engine = BeliefEngine(game_for_test().view("P1"))
    before = engine.debug_snapshot()
    with pytest.raises(BeliefContradiction):
        engine.observe(mission(team=("P1",), fails=1))
    assert engine.debug_snapshot() == before


def test_duplicate_event_vote_receipt_and_mission_snapshot_do_not_amplify_evidence():
    game = game_for_test()
    engine = BeliefEngine(game.view("P1"))
    team = {"seq": 20, "round": 1, "attempt": 1, "kind": "TEAM", "actor": "P2", "team": ["P3", "P4"]}
    votes = {p: p != "P2" for p in game.ids}
    engine.observe(team)
    for seq, (pid, approve) in enumerate(votes.items(), 21):
        engine.observe({"seq": seq, "round": 1, "attempt": 1, "kind": "VOTE", "actor": pid,
                        "team": team["team"], "approve": approve})
    before = deepcopy(engine.beliefs.hypotheses)
    engine.observe({"seq": 26, "round": 1, "attempt": 1, "kind": "TEAM_VOTE", "team": team["team"], "votes": votes})
    assert engine.beliefs.hypotheses == before
    event = mission()
    engine.observe(event)
    before = deepcopy(engine.beliefs.hypotheses)
    engine.observe(deepcopy(event))
    engine._process(Observation.from_mission(event), remember=False)
    assert engine.beliefs.hypotheses == before


@pytest.mark.parametrize("adapter", [BaselineBeliefs, JointBeliefs])
def test_private_state_isolation_and_hidden_role_swap_invariance(adapter):
    game = game_for_test()
    swapped = [Player(p.id, p.name, "MERLIN" if p.id == "P5" else "GOOD" if p.id == "P2" else p.role)
               for p in game.players.values()]
    other = Game(swapped, seed=17, direction=game.direction)
    for pid in ("P1", "P3"):
        a, b = adapter(game.view(pid)), adapter(other.view(pid))
        assert a.marginals() == b.marginals()
        assert a.distribution() == b.distribution()
        before = (a.marginals(), a.distribution())
        b.observe(mission(fails=2))
        assert (a.marginals(), a.distribution()) == before
    servant, merlin = adapter(game.view("P1")), adapter(game.view("P2"))
    assert servant.marginals()["P3"]["evil"] < 1
    assert merlin.marginals()["P3"]["evil"] == 1


@pytest.mark.parametrize("adapter", [BaselineBeliefs, JointBeliefs])
def test_hidden_reveals_and_cards_never_update_an_observer(adapter):
    observer = adapter(game_for_test().view("P1"))
    before = (observer.marginals(), observer.distribution())
    for kind in ("REVEAL", "MISSION_SUBMIT"):
        observer.observe({"seq": 90, "round": 2, "kind": kind, "roles": {"P3": "EVIL"}, "card": "FAIL"})
    assert (observer.marginals(), observer.distribution()) == before


@pytest.mark.parametrize("adapter", [BaselineBeliefs, JointBeliefs])
def test_identical_observation_replay_is_deterministic(adapter):
    a, b = [adapter(game_for_test().view("P1")) for _ in range(2)]
    events = [mission(), mission(seq=50, round_no=2, fails=0),
              {"seq": 60, "round": 3, "kind": "SOCIAL", "actor": "P2", "target": "P4", "card": "ACCUSE"}]
    for event in events:
        a.observe(deepcopy(event))
        b.observe(deepcopy(event))
        assert a.marginals() == b.marginals()
        assert a.distribution() == b.distribution()


def test_baseline_matches_historical_numeric_golden_sequence():
    baseline = BaselineBeliefs(game_for_test().view("P1"))
    baseline.observe(mission(fails=2))
    baseline.observe(mission(seq=50, round_no=2, team=("P2", "P5"), fails=0))
    baseline.observe({"seq": 51, "round": 2, "kind": "SOCIAL", "actor": "P3", "target": "P5", "card": "DEFEND"})
    baseline.observe({"seq": 52, "round": 2, "kind": "TEAM_VOTE", "team": ["P3", "P4"],
                      "votes": {"P1": True, "P2": False, "P3": True, "P4": False, "P5": True}})
    assert [baseline.marginals()[p]["evil"] for p in baseline.ids] == pytest.approx([0, .41, .645, .625, .416875])
    assert [baseline.marginals()[p]["merlin"] for p in baseline.ids] == [0, .1, .1, .1, .1]


def test_scoring_prior_has_known_brier_logloss_entropy_probability_and_midrank():
    game = game_for_test()
    joint = JointBeliefs(game.view("P1"))
    score = score_beliefs(joint, truth_of(game))
    assert score["brier_score"] == pytest.approx(.25)
    assert score["log_loss"] == pytest.approx(math.log(2))
    assert score["true_hypothesis_probability"] == pytest.approx(1 / 24)
    assert score["true_hypothesis_rank"] == 12.5
    assert score["entropy"] == pytest.approx(math.log(24))
    assert score["joint_log_loss"] == pytest.approx(math.log(24))


def test_scoring_zeros_and_projection_collapse_are_never_concealed():
    game = game_for_test()
    baseline = BaselineBeliefs(game.view("P1"))
    # A clamped wrong marginal can rule out truth without ruling out all worlds.
    baseline.estimates["P3"] = {"evil": 0, "merlin": .1}
    metrics = score_beliefs(baseline, truth_of(game))
    assert metrics["true_hypothesis_probability"] == 0
    assert metrics["true_hypothesis_rank"] == len(baseline.universe) + 1
    assert math.isfinite(metrics["log_loss"]) and metrics["log_loss"] > 8
    for p in baseline.ids:
        baseline.estimates[p] = {"evil": 0, "merlin": 0}
    before = baseline.marginals()
    metrics = score_beliefs(baseline, truth_of(game))
    assert metrics["distribution_collapsed"] == 1
    assert metrics["true_hypothesis_probability"] is None
    assert metrics["entropy"] is None
    assert baseline.marginals() == before


def test_correlated_team_risk_is_not_an_average_of_marginals():
    game = game_for_test()
    joint, baseline = JointBeliefs(game.view("P1")), BaselineBeliefs(game.view("P1"))
    assert joint.team_risk(["P3", "P4"]) == pytest.approx(5 / 6)
    assert baseline.team_risk(["P3", "P4"]) == pytest.approx(.75)
    assert joint.team_risk(["P1", "P3"]) == pytest.approx(.5)


def test_entropy_drop_with_truth_drop_is_flagged_as_pathology():
    game = game_for_test()
    joint = JointBeliefs(game.view("P1"))
    before = score_beliefs(joint, truth_of(game))
    truth_key = tuple(sorted(truth_of(game).items()))
    wrong = next(h for h in joint.engine.beliefs.hypotheses if h.key != truth_key)
    for h in joint.engine.beliefs.hypotheses:
        h.probability = .99 if h is wrong else .01 / 23
    joint.engine.beliefs.normalize()
    score = score_beliefs(joint, truth_of(game), before)
    assert score["entropy_down_truth_down"] == 1
    assert score["overconfident_wrong_world"] == 1
