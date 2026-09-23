"""Offline structural tests for the new V5 full-game harness.

These tests deliberately parse files and synthetic event rows only.  They do
not import the legacy adapter, call a provider, create an engine object, or run
an Avalon game.
"""

from __future__ import annotations

import csv
import json
from dataclasses import replace
from pathlib import Path

import pytest

from avalon.eval.v2 import v232_full_game_v5 as harness


ROOT = Path(__file__).resolve().parents[2]
R2 = ROOT / "results/joint_belief_v2_3_2/20260922-v232-camouflage-v5-full-game-prereg-r2"
WORLD_MANIFEST = R2 / "v5_full_game_world_manifest.json"
SCHEDULE = R2 / "v5_full_game_execution_order.csv"


def _config() -> harness.ExperimentConfig:
    archive_manifest = json.loads((R2 / "prompt_archive_manifest.json").read_text(encoding="utf-8"))
    prompt_hashes = {
        entry["canonical_text_path"].removeprefix("archived_prompts/"): entry["sha256"]
        for entry in archive_manifest["entries"]
    }
    return harness.ExperimentConfig.from_mapping({
        "run_id": "20260922-v232-camouflage-v5-full-game-harness-r1",
        "world_manifest_path": str(WORLD_MANIFEST),
        "execution_order_path": str(SCHEDULE),
        "model_id": "deepseek-v4-flash",
        "candidate_id": harness.V5_CANDIDATE_ID,
        "candidate_path": str(ROOT / "avalon/eval/v2/v232_candidate_v5.py"),
        "baseline_policy_id": "DeepSeekFocalMerlinActionPolicy",
        "prompt_archive_dir": str(R2 / "archived_prompts"),
        "prompt_hashes": prompt_hashes,
        "prompt_builder_hashes": {"runtime_assembly": "externally-frozen"},
        "inference_config": {"model": "deepseek-v4-flash", "temperature": 0.0},
        "shared_parameters": {
            "engine": "joint_v2", "rules": "frozen-r2", "non_merlin_policy": "frozen-population",
            "assassin_policy": "frozen-population", "belief": "joint_v2", "memory": "frozen",
            "retry": "frozen-r2", "telemetry": "v5-full-game-telemetry-v1",
        },
    }, base_dir=ROOT)


def test_a_fifty_frozen_worlds_parse():
    worlds = harness.load_world_manifest(WORLD_MANIFEST)
    assert len(worlds) == 50
    assert set(worlds) == {f"FG-W{i:03d}" for i in range(1, 51)}


def test_b_one_hundred_external_schedule_rows_parse():
    worlds = harness.load_world_manifest(WORLD_MANIFEST)
    schedule = harness.load_execution_schedule(SCHEDULE, worlds)
    assert len(schedule) == 100


def test_c_every_world_has_exactly_two_required_arms():
    worlds = harness.load_world_manifest(WORLD_MANIFEST)
    schedule = harness.load_execution_schedule(SCHEDULE, worlds)
    grouped = {world_id: {row.arm for row in schedule if row.world_id == world_id} for world_id in worlds}
    assert all(arms == set(harness.ARMS) for arms in grouped.values())


def test_d_external_counterbalanced_order_is_preserved():
    worlds = harness.load_world_manifest(WORLD_MANIFEST)
    schedule = harness.load_execution_schedule(SCHEDULE, worlds)
    for ordinal in range(1, 51):
        rows = [row for row in schedule if row.world_id == f"FG-W{ordinal:03d}"]
        assert [row.arm for row in sorted(rows, key=lambda row: row.arm_order_within_pair)] == (
            [harness.ARM_BASELINE, harness.ARM_V5] if ordinal % 2 else [harness.ARM_V5, harness.ARM_BASELINE]
        )


def test_e_v5_resolves_to_external_v5_source():
    config = _config()
    module = harness.resolve_v5_candidate(config)
    assert module.CANDIDATE == harness.V5_CANDIDATE_ID
    assert Path(module.__file__).name == "v232_candidate_v5.py"


def test_f_baseline_resolves_to_external_baseline_descriptor():
    descriptor = harness.resolve_baseline_candidate(_config())
    assert descriptor["candidate_id"] == "DeepSeekFocalMerlinActionPolicy"
    assert descriptor["merlin_vote_override"] == "none"


def test_g_v5_resolution_never_selects_the_legacy_candidate():
    module = harness.resolve_v5_candidate(_config())
    assert Path(module.__file__).name != "v232_candidate_v3.py"
    assert module.CANDIDATE == harness.V5_CANDIDATE_ID


def test_h_treatment_isolation_has_only_merlin_policy_difference():
    assert harness.assert_treatment_isolation(_config()) == {"merlin_voting_policy"}


def test_i_required_telemetry_schema_is_complete():
    schema = harness.telemetry_schema()
    assert set(schema["required_fields"]) == set(harness.REQUIRED_TELEMETRY_FIELDS)
    assert all(field in schema["field_types"] for field in harness.REQUIRED_TELEMETRY_FIELDS)


def _policy():
    return {
        "known_evil_on_team": [], "mission_safety_vote": True,
        "public_consensus_vote": True, "public_warning_count": 0,
        "critical": False, "guard_triggered": True, "symmetric_guard_triggered": False,
    }


def test_j_consistency_record_requires_individual_engine_event_id():
    recorder = harness.V5TelemetryRecorder()
    recorder.record_policy_decision(
        world_id="FG-W001", arm="V5", game_id="FG-W001-V5", decision_id="D1",
        after_seq=5, proposed_team=["P1", "P2"], policy=_policy(), policy_output=True,
    )
    row = recorder.resolve_engine_vote(
        game_id="FG-W001-V5", decision_id="D1", actor_id="P1",
        events=[{"kind": "VOTE", "actor": "P1", "seq": 6, "team": ["P1", "P2"],
                 "approve": True, "record_id": "R1-006"}],
    )
    assert row["engine_vote_event_id"] == "R1-006"
    assert row["executed_engine_vote"] is True
    assert row["policy_engine_consistent"] is True

    mismatch = harness.V5TelemetryRecorder()
    mismatch.record_policy_decision(
        world_id="FG-W001", arm="V5", game_id="FG-W001-V5", decision_id="D1-mismatch",
        after_seq=5, proposed_team=["P1", "P2"], policy=_policy(), policy_output=True,
    )
    mismatch_row = mismatch.resolve_engine_vote(
        game_id="FG-W001-V5", decision_id="D1-mismatch", actor_id="P1",
        events=[{"kind": "VOTE", "actor": "P1", "seq": 6, "team": ["P1", "P2"],
                 "approve": False, "record_id": "R1-006-mismatch"}],
    )
    assert mismatch_row["executed_engine_vote"] is False
    assert mismatch_row["policy_engine_consistent"] is False


def test_j_exact_after_seq_is_reconciled_from_host_decision_archive():
    recorder = harness.V5TelemetryRecorder()
    recorder.record_policy_decision(
        world_id="FG-W001", arm="V5", game_id="FG-W001-V5", decision_id="D1-exact",
        after_seq=5, proposed_team=["P1", "P2"], policy=_policy(), policy_output=True,
        actor_id="P1", round_number=1, attempt_number=1,
    )
    recorder.reconcile_after_seq(
        game_id="FG-W001-V5",
        decision_archive=[{"observer_id": "P1", "phase": "vote", "round": 1, "attempt": 1,
                           "after_seq": 9, "view": {"team": ["P1", "P2"]},
                           "action": {"approve": True}}],
    )
    row = recorder.resolve_engine_vote(
        game_id="FG-W001-V5", decision_id="D1-exact", actor_id="P1",
        events=[{"kind": "VOTE", "actor": "P1", "seq": 10, "team": ["P1", "P2"],
                 "approve": True, "record_id": "R1-010"}],
    )
    assert row["after_seq"] == 9
    assert row["engine_vote_event_id"] == "R1-010"


def test_k_missing_engine_event_id_fails_closed():
    recorder = harness.V5TelemetryRecorder()
    recorder.record_policy_decision(
        world_id="FG-W001", arm="V5", game_id="FG-W001-V5", decision_id="D2",
        after_seq=5, proposed_team=["P1", "P2"], policy=_policy(), policy_output=True,
    )
    with pytest.raises(harness.TelemetryConsistencyError):
        recorder.resolve_engine_vote(
            game_id="FG-W001-V5", decision_id="D2", actor_id="P1",
            events=[{"kind": "VOTE", "actor": "P1", "seq": 6, "team": ["P1", "P2"],
                     "approve": True}],
        )


def test_l_unknown_world_fails_closed(tmp_path):
    worlds = harness.load_world_manifest(WORLD_MANIFEST)
    path = tmp_path / "unknown.csv"
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=[
            "execution_index", "world_id", "pair_id", "seed", "profile", "arm",
            "arm_order_within_pair", "expected_game_id",
        ])
        writer.writeheader()
        writer.writerow({"execution_index": 1, "world_id": "FG-W999", "pair_id": "FG-W999-PAIR",
                         "seed": 979999, "profile": "heldout_blend", "arm": "BASELINE",
                         "arm_order_within_pair": 1, "expected_game_id": "FG-W999-BASELINE"})
    with pytest.raises(harness.HarnessValidationError):
        harness.load_execution_schedule(path, worlds, expected_count=1)


def test_m_unknown_arm_fails_closed():
    with pytest.raises(harness.HarnessValidationError):
        harness.ExecutionRow.from_mapping({
            "execution_index": 1, "world_id": "FG-W001", "pair_id": "FG-W001-PAIR",
            "seed": 970001, "profile": "heldout_blend", "arm": "UNKNOWN",
            "arm_order_within_pair": 1, "expected_game_id": "FG-W001-UNKNOWN",
        })


def test_n_candidate_config_mismatch_fails_closed():
    with pytest.raises(harness.HarnessValidationError):
        harness.resolve_v5_candidate(replace(_config(), candidate_id="WrongCandidate"))


def test_o_retired_six_seed_schedule_is_rejected():
    with pytest.raises(harness.HarnessValidationError):
        harness.ExecutionRow.from_mapping({
            "execution_index": 1, "world_id": "FG-W001", "pair_id": "FG-W001-PAIR",
            "seed": int("96" + "0001"), "profile": "heldout_blend", "arm": "BASELINE",
            "arm_order_within_pair": 1, "expected_game_id": "FG-W001-BASELINE",
        })


def test_plan_validation_resolves_everything_before_execution():
    plan = harness.validate_execution_plan(_config())
    assert len(plan.worlds) == 50
    assert len(plan.schedule) == 100
    assert plan.v5_module.CANDIDATE == harness.V5_CANDIDATE_ID
    assert plan.baseline_descriptor["candidate_id"] == "DeepSeekFocalMerlinActionPolicy"


def test_legitimate_loss_is_valid_and_technical_failure_is_separate():
    assert harness.classify_game_result(completed=True) == harness.VALID_COMPLETED_GAME
    assert harness.classify_game_result(completed=False, technical_failure=True, retryable=True) == harness.RETRYABLE_TECHNICAL_FAILURE
    assert harness.classify_game_result(completed=False, technical_failure=True, retryable=False) == harness.NONRETRYABLE_TECHNICAL_FAILURE
