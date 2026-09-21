"""Offline acceptance tests for the V2.3.2-r2 P1 repair layer."""

import csv
import json
from pathlib import Path

from avalon.engine import Game, Player
from avalon.eval.v2 import v232_p1


def test_vote_is_sealed_and_team_vote_is_single_commit():
    game = Game([
        Player("P1", "P1", "MERLIN"), Player("P2", "P2", "ASSASSIN"),
        Player("P3", "P3", "EVIL"), Player("P4", "P4", "GOOD"), Player("P5", "P5", "GOOD"),
    ], seed=777, direction="clockwise")
    game.phase = "vote"
    game.team = ["P1", "P4"]
    before = len(game.events)
    game.vote({p: p in {"P1", "P2", "P3"} for p in game.ids},
              reasons={p: "team_risk" for p in game.ids},
              strong={p: False for p in game.ids})
    new = game.events[before:]
    assert [e["kind"] for e in new] == ["VOTE"] * 5 + ["TEAM_VOTE"]
    assert game.phase == "mission"
    # No host callback or observer decision can occur between the sealed votes.
    assert new[-1]["kind"] == "TEAM_VOTE"


def test_exact_top_does_not_use_epsilon():
    values = {"P1": 0.3333333333333332, "P4": 0.3333333333333333, "P5": 0.3333333333333333}
    top = sorted(pid for pid, value in values.items() if value == max(values.values()))
    near = sorted(pid for pid, value in values.items() if max(values.values()) - value <= v232_p1.EPSILON_DIAGNOSTIC)
    assert top == ["P4", "P5"]
    assert near == ["P1", "P4", "P5"]


def test_missing_arm_is_classified_before_invalid(tmp_path):
    _, result = v232_p1._classification(tmp_path)
    assert result["status_counts"]["MISSING_ARM"] == 3
    rows = {row["decision_id"]: row for row in csv.DictReader((tmp_path / "comparison_inventory.csv").open())}
    for fixture in v232_p1.REQUIRED_MISSING_FIXTURES:
        assert rows[fixture]["comparison_status"] == "MISSING_ARM"
        assert rows[fixture]["action_delta"] == "NOT_COMPARABLE"
        assert rows[fixture]["reference_valid"] == ""
        assert rows[fixture]["candidate_valid"] == "True"


def test_constant_factor_counterexamples_are_source_bound(tmp_path):
    timeline = v232_p1._read_csv(v232_p1.HIST_RUN / "assassin_exposure_timeline.csv")
    # Keep only the two bound source rows; the factor file is still read from
    # the immutable historical source, and no expected number is hardcoded.
    rows = [r for r in timeline if (r.get("game_id"), r.get("observer_id"), r.get("event_id")) in {
        ("A-main-single_seat-940004-joint_v1", "P4", "R3-123"),
        ("v23_source-1131002-joint_v2", "P5", "R2-078"),
    }]
    examples = v232_p1._numeric(tmp_path, rows)
    assert len(examples) == 2
    assert all(item["constant_on_live_support"] for item in examples)
    assert all(item["raw_probability_changed"] == 1 for item in examples)
    assert all(item["posterior_hash_changed"] == 0 for item in examples)
    assert all(item["internal_exact_top_changed"] == 1 for item in examples)
    assert all(item["shadow_noop_posterior_equal"] for item in examples)


def test_vote_intervention_uses_real_menu_and_two_legal_branches(tmp_path):
    # This is a small source-bound smoke using the first preregistered P0 case.
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    config = {"network_access": False, "budget_cny": None,
              "p0_gate_snapshot": {"contract_smoke": "FAIL_REQUEST_PROTOCOL_CONFLICT"}}
    (run_dir / "p1_config.json").write_text(json.dumps(config), encoding="utf-8")
    case = v232_p1._select_cases()[0]
    (run_dir / "p1_preregistered_cases.json").write_text(json.dumps({"cases": [case]}), encoding="utf-8")
    rows, safety, meta = v232_p1._vote_interventions(run_dir)
    assert meta["valid_pairs"] == 1
    assert {row["branch"] for row in rows} == {"reference", "candidate"}
    assert all(row["legal_action_valid"] == 1 for row in rows)
    assert all(row["future_events_injected"] == 0 for row in rows)
    assert all(row["intervention_actor_role"] == "MERLIN" for row in rows)
    assert all(row["measurement_observer_role"] == "ASSASSIN" for row in rows)
    assert all(row["intervention_actor_id"] != row["measurement_observer_id"] for row in rows)
    assert all(row["factor_consumed"] == 1 for row in rows)
    assert all(row["duplicate_suppressed"] >= 1 for row in rows)
    assert all("vote:1:1:P2" in row["factor_signal_id"] for row in rows)
    assert meta["invalid_pairs"] == 0
    assert len(safety) == 2


def test_wrong_lock_episode_counts_contiguous_unique_top_once():
    rows = [
        {"decision_index": 1, "native_exact_top_after": '["P3"]'},
        {"decision_index": 2, "native_exact_top_after": '["P3"]'},
        {"decision_index": 3, "native_exact_top_after": '["P3"]'},
    ]
    segments = v232_p1._wrong_lock_segments(rows, "P2")
    assert len(segments) == 1
    assert segments[0]["wrong_player"] == "P3"
    assert segments[0]["rows"] == 3


def test_wrong_lock_episode_tie_and_target_change_split_episodes():
    rows = [
        {"decision_index": 1, "native_exact_top_after": '["P3"]'},
        {"decision_index": 2, "native_exact_top_after": '["P3", "P4"]'},
        {"decision_index": 3, "native_exact_top_after": '["P4"]'},
        {"decision_index": 4, "native_exact_top_after": '["P2"]'},
        {"decision_index": 5, "native_exact_top_after": '["P4"]'},
    ]
    segments = v232_p1._wrong_lock_segments(rows, "P2")
    assert [(row["wrong_player"], row["start_decision_index"], row["end_decision_index"]) for row in segments] == [
        ("P3", 1, 1), ("P4", 3, 3), ("P4", 5, 5)
    ]


def test_candidate_vote_uses_frozen_public_proxy_without_assassin_state():
    cases = v232_p1._select_cases()
    records, _ = v232_p1._source_records()
    first = cases[0]
    game, _ = v232_p1._replay_to_cutoff(records[(first["source_run_id"], first["game_id"])], first["cutoff_seq"])
    vote, policy = v232_p1._candidate_vote_decision(game, v232_p1._public_view(game, first["intervention_actor_id"]))
    assert vote is True
    assert policy["mode"] == "MISSION_SAFETY_DEFAULT"
    assert policy["truth_used_by_agent"] == 0
    assert policy["assassin_state_used"] == 0
    assert policy["evaluator_labels_used"] == 0

    ambiguous = cases[1]
    game, _ = v232_p1._replay_to_cutoff(records[(ambiguous["source_run_id"], ambiguous["game_id"])], ambiguous["cutoff_seq"])
    vote, policy = v232_p1._candidate_vote_decision(game, v232_p1._public_view(game, ambiguous["intervention_actor_id"]))
    assert vote is False
    assert policy["mode"] == "AMBIGUOUS_SAFE_PUBLIC_PROXY"
    assert policy["public_suspicion_score"] >= v232_p1.CANDIDATE_PUBLIC_SUSPICION_THRESHOLD


def test_report_only_is_offline_guarded(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "p1_config.json").write_text(json.dumps({"network_access": False, "budget_cny": None}), encoding="utf-8")
    (run_dir / "p1_gates.json").write_text(json.dumps({"status": "DONE"}), encoding="utf-8")
    (run_dir / "summary.json").write_text(json.dumps({"network_calls": 99}), encoding="utf-8")
    result = v232_p1.report(run_dir)
    assert result["network_calls"] == 0
    assert json.loads((run_dir / "summary.json").read_text())["network_calls"] == 0
