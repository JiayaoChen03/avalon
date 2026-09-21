import copy
import json
from pathlib import Path

from avalon.eval.v2.v232_channel import (
    EPSILON_DIAGNOSTIC,
    _stats,
    r7_assassin_requests,
    replay_record,
    text_ablate,
    tie_audit,
)
from avalon.eval.v2.adapters import make_version
from avalon.eval.simulation import validate_replay


ROOT = Path(__file__).resolve().parents[2]
R7 = ROOT / "results/joint_belief_v2_1/20260918-v21-r7-live-75"
V23 = ROOT / "results/joint_belief_v2_3/20260918-v23-r2-live20"


def _first_valid_record():
    for path in sorted((R7 / "active_replays").glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        try:
            validate_replay(record)
        except ValueError:
            continue
        return record
    raise AssertionError("no valid frozen replay")


def test_exact_top_uses_production_equality_and_keeps_diagnostic_near_set():
    record = _first_valid_record()
    game, truth = validate_replay(record)
    assassin = next(p for p, role in truth.items() if role == "ASSASSIN")
    observer = make_version("joint_v2", game.view(assassin))
    stats = _stats(observer, [p for p in observer.ids if p != assassin])
    assert isinstance(stats["native_top"], list)
    assert set(stats["native_top"]).issubset(set(observer.ids) - {assassin})
    assert EPSILON_DIAGNOSTIC == 1e-10


def test_replay_keeps_full_stream_and_duplicate_delivery_is_idempotent():
    record = _first_valid_record()
    before = copy.deepcopy(record)
    result = replay_record(record, variant="joint_v2", source_run_id="r7", cohort_role="test")
    assert result["events"] > 0
    assert any(row["duplicate_suppressed"] for row in result["timeline"])
    assert record == before


def test_joint_v1_frozen_observation_path_is_supported():
    record = _first_valid_record()
    result = replay_record(record, variant="joint_v1", source_run_id="r7", cohort_role="test")
    assert result["events"] > 0
    assert all(row["variant"] == "joint_v1" for row in result["timeline"])


def test_text_display_ablation_removes_only_free_text_fields():
    value = {"game": {"recent_events": [{"record_id": "R1", "public_writing": "claim",
                                           "target": "P2", "citations": ["R0"]}]},
             "private_beliefs": {"marginals": {"P2": {"merlin": 0.5}}}}
    ablated = text_ablate(value)
    event = ablated["game"]["recent_events"][0]
    assert "public_writing" not in event
    assert event["target"] == "P2" and event["citations"] == ["R0"]
    assert ablated["private_beliefs"] == value["private_beliefs"]


def test_historical_assassin_requests_preserve_full_ranking_arrays():
    rows = r7_assassin_requests(R7)
    assert rows
    ranked = [row for row in rows if isinstance(row["submitted_ranking"], list)]
    assert ranked
    assert all(len(row["submitted_ranking"]) == 5 for row in ranked)
    assert all(set(row["submitted_ranking"]) == {"P1", "P2", "P3", "P4", "P5"}
               for row in ranked)


def test_tie_audit_separates_historical_and_controlled_paths():
    rows, eligible, _ = tie_audit(R7, V23)
    assert rows
    assert {row["dataset_role"] for row in rows} >= {"historical_r7_diagnostic", "v23_active_diagnostic"}
    assert eligible
    assert all("submitted_assassin_ranking" in row for row in rows)
