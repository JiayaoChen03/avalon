"""Tests for the accepted MerlinVoteCamouflageV2 offline evaluator."""

import json
from pathlib import Path

from avalon.eval.v2 import v232_candidate_v2 as candidate


class _Game:
    team = ["P1", "P2"]
    events = []
    failures = 0
    attempt = 1


def test_clean_team_guard_is_unconditional_and_uses_no_scorer_truth():
    vote, policy = candidate.candidate_vote_decision(_Game(), {"known_evil": []})
    assert vote is True
    assert policy["mode"] == "CLEAN_TEAM_APPROVE_GUARD"
    assert policy["guard_triggered"] == 1
    assert policy["truth_used_by_agent"] == 0
    assert policy["assassin_state_used"] == 0
    assert policy["current_sealed_ballots_used"] == 0


def test_policy_receives_restricted_public_projection_only():
    class _GameWithPrivateRoles(_Game):
        players = {"P1": {"role": "MERLIN"}, "P2": {"role": "ASSASSIN"}}

    public = candidate._public_vote_state(_GameWithPrivateRoles())
    assert not hasattr(public, "players")
    assert not hasattr(public, "roles")
    vote, _ = candidate.candidate_vote_decision(public, {"known_evil": []})
    assert vote is True


def test_dirty_team_uses_only_public_ambiguity_branch():
    game = _Game()
    game.events = [{"kind": "SOCIAL", "card": "ACCUSE", "target": "P2"}]
    vote, policy = candidate.candidate_vote_decision(game, {"known_evil": ["P2"]})
    assert vote is True
    assert policy["mode"] == "AMBIGUOUS_EVIL_PUBLIC_PROXY"
    assert policy["guard_triggered"] == 0
    assert policy["known_evil_on_team"] == ["P2"]


def test_offline_run_uses_six_frozen_pairs_and_writes_required_outputs(tmp_path):
    result = candidate.run(tmp_path / "candidate-v2")
    assert result["network_calls"] == 0
    assert result["cases"] == 6
    assert result["valid_pairs"] == 6
    assert result["invalid_pairs"] == 0
    assert result["branches"] == 12
    assert result["candidate_enabled"] is False
    assert result["production_promotion"] is False
    assert result["gate"] in candidate.TERMINAL_GATES
    required = {
        "candidate_implementation_audit.md",
        "candidate_vote_interventions.csv",
        "candidate_assassin_effect.csv",
        "candidate_safety_tradeoff.csv",
        "candidate_safety_sensitivity.csv",
        "candidate_safety_gate.json",
        "source_manifest.json",
        "config.json",
        "report.md",
        "summary.json",
    }
    assert required <= {path.name for path in (tmp_path / "candidate-v2").iterdir()}
    gate = json.loads((tmp_path / "candidate-v2" / "candidate_safety_gate.json").read_text())
    assert gate["candidate"] == candidate.CANDIDATE
    assert gate["future_events_injected"] == 0


def test_preregistered_case_order_is_frozen():
    cases = candidate._load_cases()
    assert len(cases) == 6
    assert all(row["intervention_actor_id"] != row["measurement_observer_id"] for row in cases)
    assert all(row["intervention_actor_role"] == "MERLIN" for row in cases)
    assert all(row["measurement_observer_role"] == "ASSASSIN" for row in cases)
