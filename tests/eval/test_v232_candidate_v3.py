"""Targeted tests for the accepted MerlinVoteCamouflageV3 evaluator."""

import json

from avalon.eval.v2 import v232_candidate_v2 as v2
from avalon.eval.v2 import v232_candidate_v3 as candidate


class _PublicState(v2.PublicVoteState):
    pass


def test_public_consensus_uses_only_frozen_warning_classes():
    state = _PublicState(
        team=["P1", "P2"],
        events=[
            {"kind": "SOCIAL", "card": "ACCUSE", "target": "P2"},
            {"kind": "TEAM_VOTE", "team": ["P1", "P3"], "approved": False},
            {"kind": "MISSION", "team": ["P2", "P4"], "success": False},
        ],
        failures=0,
        attempt=1,
    )
    vote, policy = candidate.candidate_vote_decision(state, {"known_evil": []})
    assert vote is False
    assert policy["public_warning_count"] == 3
    assert policy["public_warning_components"] == {
        "public_accuse_on_team": 1,
        "rejected_overlap": 1,
        "failed_mission_overlap": 1,
    }
    assert policy["mode"] == "PUBLIC_CONSENSUS"
    assert policy["truth_used_by_agent"] == 0


def test_critical_state_uses_mission_safety_over_public_consensus():
    state = _PublicState(
        team=["P1", "P2"],
        events=[
            {"kind": "SOCIAL", "card": "ACCUSE", "target": "P2"},
            {"kind": "TEAM_VOTE", "team": ["P1"], "approved": False},
            {"kind": "TEAM_VOTE", "team": ["P1"], "approved": False},
            {"kind": "TEAM_VOTE", "team": ["P1"], "approved": False},
            {"kind": "TEAM_VOTE", "team": ["P1"], "approved": False},
        ],
        failures=0,
        attempt=5,
    )
    vote, policy = candidate.candidate_vote_decision(state, {"known_evil": ["P2"]})
    assert vote is False
    assert policy["critical"] == 1
    assert policy["mode"] == "CRITICAL_MISSION_SAFETY"


def test_candidate_rejects_full_game_and_hidden_inputs():
    class _FakeGame:
        team = ["P1", "P2"]
        events = []
        failures = 0
        attempt = 1
        roles = {"P1": "MERLIN", "P2": "ASSASSIN"}

    try:
        candidate.candidate_vote_decision(_FakeGame(), {"known_evil": []})
    except TypeError as exc:
        assert "PublicVoteState" in str(exc)
    else:
        raise AssertionError("candidate accepted a full Game-like object")


def test_offline_run_uses_six_frozen_pairs_and_writes_required_outputs(tmp_path):
    result = candidate.run(tmp_path / "candidate-v3")
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
    assert required <= {path.name for path in (tmp_path / "candidate-v3").iterdir()}
    gate = json.loads((tmp_path / "candidate-v3" / "candidate_safety_gate.json").read_text())
    assert gate["candidate"] == candidate.CANDIDATE
    assert gate["future_events_injected"] == 0


def test_preregistered_case_order_and_role_binding_are_frozen():
    cases = candidate._load_cases()
    assert len(cases) == 6
    assert all(row["intervention_actor_id"] != row["measurement_observer_id"] for row in cases)
    assert all(row["intervention_actor_role"] == "MERLIN" for row in cases)
    assert all(row["measurement_observer_role"] == "ASSASSIN" for row in cases)
