"""Causal controls, replay boundaries, statistics, failure gates and exports."""

from copy import deepcopy
import csv
import json
import socket

import pytest

from avalon.eval.beliefs import BaselineBeliefs, JointBeliefs
from avalon.eval.joint_belief import CSVOutput, build_parser, execute, validate_args
from avalon.eval.simulation import (ControlledClient, canonical, load_replays, play_game, policy_context,
                                    replay_game, run_pair, validate_replay)
from avalon.eval.statistics import Metric, final_replay_rows, paired_comparisons, trajectories
from test_eval_correctness import game_for_test


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def reject(*args, **kwargs):
        raise AssertionError("Evaluation must run offline")
    monkeypatch.setattr(socket.socket, "connect", reject)
    monkeypatch.setattr(socket, "create_connection", reject)


def without_timing(rows):
    return [{k: v for k, v in row.items() if k not in {"belief_update_ms", "game_seconds"}} for row in rows]


@pytest.fixture(scope="module")
def completed_reference():
    row, _, record = play_game(113, "reference", phase="replay_source")
    assert row["status"] == "completed"
    return record


@pytest.mark.parametrize("count", [5, 6])
def test_paired_tournament_matches_every_control_and_completes(count):
    result = run_pair((117, "smoke", {"variants": ["baseline", "joint_belief"], "players": count}))
    a, b = [r[0] for r in result]
    assert a["pair_signature"] == b["pair_signature"]
    assert a["roles"] == b["roles"]
    assert a["seed"] == b["seed"]
    assert a["focal_role"] == b["focal_role"]
    for row, trace in result:
        assert row["status"] == "completed", row["error"]
        assert row["quest_count"] <= 5
        assert row["invalid_actions"] == row["belief_engine_failures"] == 0
        assert row["successful_quests"] + row["failed_quests"] == row["quest_count"]
        assert row["good_win"] + row["evil_win"] == 1
        assert {r["observer_id"] for r in trace} == {"P1"}
        assert row["external_model_calls"] == 0


def test_same_variant_and_seed_replays_deterministically():
    a, ta, ea = play_game(23, "joint_belief")
    b, tb, eb = play_game(23, "joint_belief")
    assert ea == eb
    assert without_timing([a]) == without_timing([b])
    assert without_timing(ta) == without_timing(tb)


def test_fixed_replay_observations_identical_and_no_policies_called(completed_reference, monkeypatch):
    def reject(*args, **kwargs):
        raise AssertionError("A replay must not ask a policy for an action")
    monkeypatch.setattr(ControlledClient, "complete", reject)
    frozen = deepcopy(completed_reference)
    traces, audits = replay_game(frozen, ["baseline", "joint_belief"])
    assert frozen == completed_reference
    assert len({a["observation_digest"] for a in audits}) == 1
    keys = lambda v: [(r["observer_id"], r["round"], r["event_id"]) for r in traces if r["variant"] == v]
    assert keys("baseline") == keys("joint_belief")
    assert len(final_replay_rows(traces)) == 2
    assert len({a["initial_view_digest"] for a in audits}) == 5
    assert not {"REVEAL", "MISSION_SUBMIT"} & {r["event_kind"] for r in traces}


def test_replay_is_deterministic_across_order_and_ground_truth_never_supplied(completed_reference, monkeypatch):
    observed = []
    original = JointBeliefs.observe
    def spy(self, event):
        observed.append(deepcopy(event))
        assert "roles" not in event and "true_roles" not in event
        return original(self, event)
    monkeypatch.setattr(JointBeliefs, "observe", spy)
    a, _ = replay_game(completed_reference, ["baseline", "joint_belief"])
    b, _ = replay_game(completed_reference, ["joint_belief", "baseline"])
    key = lambda r: (r["game_id"], r["observer_id"], r["event_id"], r["variant"])
    assert sorted(without_timing(a), key=key) == sorted(without_timing(b), key=key)
    assert observed


@pytest.mark.parametrize("defect", ["incomplete", "roles", "duplicate", "reorder"])
def test_replay_rejects_invalid_or_future_contaminated_archives(completed_reference, defect):
    record = deepcopy(completed_reference)
    if defect == "incomplete":
        record["events"] = record["events"][:-2]
    elif defect == "roles":
        record["events"][-1]["roles"]["P1"] = "FAKE"
    elif defect == "duplicate":
        record["events"].append(record["events"][5])
    else:
        record["events"][5], record["events"][6] = record["events"][6], record["events"][5]
    with pytest.raises(ValueError):
        validate_replay(record)


def test_replay_jsonl_load_roundtrip(tmp_path, completed_reference):
    path = tmp_path / "games.jsonl"
    path.write_text(canonical(completed_reference) + "\n")
    assert load_replays(path) == [completed_reference]


def test_controller_context_has_no_variant_or_other_private_state():
    game = game_for_test()
    view = game.view("P1")
    for cls in (BaselineBeliefs, JointBeliefs):
        context = policy_context(view, cls(view))
        assert "variant" not in context
        assert "truth" not in context
        assert "roles" not in context
        assert all("role" not in p for p in context["view"]["players"])
    # Shared keyed noise, including nonzero temperature, is repeatable.
    context = policy_context(view, BaselineBeliefs(view))
    assert ControlledClient(4, .3).complete(context) == ControlledClient(4, .3).complete(context)


def test_fixture_client_uses_controlled_responses_and_invalid_actions_are_counted():
    response = {"team": ["P99", "P99"]}
    client = ControlledClient(1, model="fixture-v1", responses={"team": response})
    view = game_for_test().view("P1")
    assert client.complete(policy_context(view, BaselineBeliefs(view))) == response
    row, _, _ = play_game(1, "baseline", model="fixture-v1", responses={"team": response})
    assert row["status"] == "failed"
    assert row["invalid_actions"] == 1
    assert row["belief_engine_failures"] == 0
    assert "valid players" in row["error"]
    assert row["focal_win"] is None  # A broken game is not an observed loss.


def test_belief_failure_is_recorded_without_resetting_or_replacing_engine(monkeypatch):
    def contradiction(*args, **kwargs):
        raise ValueError("injected belief contradiction")
    monkeypatch.setattr(JointBeliefs, "observe", contradiction)
    row, _, _ = play_game(1, "joint_belief")
    assert row["status"] == "failed"
    assert row["belief_engine_failures"] == 1
    assert row["invalid_actions"] == 0
    assert "injected belief contradiction" in row["error"]


def test_csv_preserves_earlier_rows_when_marginal_player_columns_expand(tmp_path):
    output = CSVOutput(tmp_path / "trace.csv", ["game_id"])
    output.append([{"game_id": "five", "evil_probability_P5": .5}])
    output.append([{"game_id": "six", "evil_probability_P5": .4, "evil_probability_P6": .4}])
    output.close()
    rows = list(csv.DictReader((tmp_path / "trace.csv").open()))
    assert rows[0]["game_id"] == "five" and rows[0]["evil_probability_P5"] == "0.5"
    assert rows[0]["evil_probability_P6"] == ""
    assert rows[1]["evil_probability_P6"] == "0.4"


def pairs(values):
    return [{"pair_id": str(i), "variant": variant, "x": value, "pair_signature": str(i)}
            for i, pair in enumerate(values) for variant, value in zip(("baseline", "joint_belief"), pair)]


def test_paired_bootstrap_resamples_pairs_not_unrelated_games():
    # Large between-pair variation; exact within-pair delta remains one.
    metrics = paired_comparisons(pairs([(0, 1), (100, 101), (-100, -99)]), {"x": Metric("x", direction="higher")},
                                 resamples=500, seed=9)["x"]
    assert metrics["absolute_delta"] == pytest.approx(1)
    assert metrics["delta_ci95"] == pytest.approx([1, 1])
    assert metrics["interpretation"] == "improvement_supported"
    assert metrics["relative_delta"] is None  # Baseline zero.


def test_paired_bootstrap_is_reproducible_and_raw_mean_is_not_enough():
    rows = pairs([(0, 1), (1, 0), (0, 1), (1, 1)])
    a = paired_comparisons(rows, {"x": Metric("x", direction="higher")}, resamples=1000)
    b = paired_comparisons(list(reversed(rows)), {"x": Metric("x", direction="higher")}, resamples=1000)
    assert a == b
    assert a["x"]["absolute_delta"] > 0
    assert a["x"]["delta_ci95"][0] <= 0
    assert a["x"]["interpretation"] == "inconclusive"


def test_undefined_rates_and_single_pair_have_no_invented_confidence():
    rows = pairs([(0, 0)])
    for row in rows:
        row["denom"] = 0
    comparison = paired_comparisons(rows, {"rate": Metric("x", "denom"), "x": Metric("x")}, resamples=20)
    assert comparison["rate"]["baseline"] is None
    assert comparison["rate"]["delta_ci95"] is None
    assert comparison["x"]["delta_ci95"] is None


def test_missing_scores_use_common_pairs_and_conditional_rates_keep_denominators():
    rows = pairs([(None, .5), (.4, .2), (.6, .3)])
    m = paired_comparisons(rows, {"x": Metric("x")}, resamples=100)["x"]
    assert m["baseline"] == pytest.approx(.5)
    assert m["joint_belief"] == pytest.approx(.25)
    assert m["eligible_clusters"] == 2
    rows = pairs([(1, 0), (0, 1)])
    for row in rows:
        row["denom"] = 1 if row["x"] else 0
    m = paired_comparisons(rows, {"x": Metric("x", "denom")}, resamples=100)["x"]
    assert m["baseline"] == m["joint_belief"] == 1
    assert m["baseline_denominator"] == m["joint_belief_denominator"] == 1


def test_unpaired_duplicate_or_mismatched_controls_are_rejected():
    for rows in (pairs([(0, 1)])[:1], pairs([(0, 1)]) * 2,
                 [dict(r, pair_signature=r["variant"]) for r in pairs([(0, 1)])]):
        with pytest.raises(ValueError):
            paired_comparisons(rows, {"x": Metric("x")}, resamples=10)


def test_final_scores_exclude_terminal_knowledge_and_curves_do_not_forward_fill(completed_reference):
    traces, _ = replay_game(completed_reference, ["baseline", "joint_belief"])
    before = final_replay_rows(traces)
    fake = {**traces[-1], "decision_available": 0, "true_hypothesis_probability": 1, "brier_score": 0, "round": 99}
    assert final_replay_rows(traces + [fake]) == before
    assert 99 not in {r["round"] for r in trajectories(traces + [fake])}


def args_for(tmp_path, extra=()):
    parser = build_parser()
    args = parser.parse_args(["--games", "1", "--smoke-games", "1", "--replay-games", "1",
                              "--bootstrap-resamples", "20", "--output-dir", str(tmp_path), *extra])
    validate_args(args, parser)
    return args


def mock_tests(output, failures=0):
    (output / "unit_tests.xml").write_text(f'<testsuite tests="1" failures="{failures}"/>')
    return {"tests": 1, "passed": 1 - failures, "failures": failures, "errors": 0, "skipped": 0, "exit_code": failures}


def test_complete_pipeline_exports_all_artifacts_and_runs_phases_in_order(tmp_path, monkeypatch):
    monkeypatch.setattr("avalon.eval.joint_belief.run_correctness", mock_tests)
    output, summary = execute(args_for(tmp_path))
    assert summary["status"] == "completed", summary["error"]
    assert [p["name"] for p in summary["phases"]] == ["correctness", "replay", "smoke", "tournament"]
    for name in ("config.json", "unit_tests.xml", "games.csv", "belief_trace.csv", "summary.json", "report.md", "replays.jsonl"):
        assert (output / name).stat().st_size > 0
    assert len(list((output / "plots").glob("*.png"))) == 6
    rows = list(csv.DictReader((output / "games.csv").open()))
    assert len(rows) == 5  # 1 reference + 2 smoke + 2 main physical games.
    traces = list(csv.DictReader((output / "belief_trace.csv").open()))
    assert all("evil_probability_P5" in row for row in traces)
    config = json.loads((output / "config.json").read_text())
    assert not set(config["seeds"]) & set(config["smoke_seeds"])
    assert not set(config["seeds"]) & set(config["replay_seeds"])
    assert config["source_sha256"]["avalon/cognition.py"]
    assert config["likelihood_parameters"]["behavioral"]["vote_merlin"] == 1.06


def test_correctness_failure_blocks_all_later_phases_and_still_exports_report(tmp_path, monkeypatch):
    monkeypatch.setattr("avalon.eval.joint_belief.run_correctness", lambda output: mock_tests(output, 1))
    def forbidden(*args, **kwargs):
        raise AssertionError("Later phases must not run after correctness failure")
    monkeypatch.setattr("avalon.eval.joint_belief.play_game", forbidden)
    output, summary = execute(args_for(tmp_path))
    assert summary["status"] == "failed"
    assert [p["name"] for p in summary["phases"]] == ["correctness"]
    assert (output / "report.md").exists()
    assert (output / "unit_tests.xml").exists()
    assert len(list(csv.DictReader((output / "games.csv").open()))) == 0


def test_smoke_failure_blocks_larger_tournament_and_preserves_failed_games(tmp_path, monkeypatch):
    monkeypatch.setattr("avalon.eval.joint_belief.run_correctness", mock_tests)
    original = run_pair
    def fail_smoke(task):
        assert task[1] == "smoke", "Must not reach the larger tournament"
        result = original(task)
        result[0][0].update(status="failed", invalid_actions=1, error="injected invalid action")
        return result
    monkeypatch.setattr("avalon.eval.joint_belief.run_pair", fail_smoke)
    output, summary = execute(args_for(tmp_path))
    assert summary["status"] == "failed"
    assert summary["failed_games"] == 1
    assert summary["phases"][-1]["name"] == "smoke"
    assert summary["game_counts"]["tournament"]["baseline"] == 0
    assert "injected invalid action" in (output / "report.md").read_text()
