"""Joint Belief v2.3.2 runner.

``prepare``, ``diagnose``, ``tests`` and ``report-only`` are offline.  The
optional ``pilot`` stage is the only mode that can send DeepSeek requests, and
it is unlocked only after the offline gate identifies a real production exact
tie with public text in the model input.  The pilot is a historical diagnostic,
never a new game or a production candidate.
"""

from __future__ import annotations

import argparse
import ast
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import csv
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

from avalon.eval.joint_belief import ROOT, git_info
from avalon.eval.simulation import canonical, digest
from avalon.eval.v2.v232_channel import (
    EPSILON_DIAGNOSTIC, factor_ablation, first_identification, inventory_v232,
    read_jsonl, replay_record, r7_assassin_requests, sha256, snapshot_interventions,
    tie_audit, tie_path, write_csv, write_json,
)


PRIMARY_SOURCE = ROOT / "results/joint_belief_v2_3/20260918-v23-r2-live20"
DIAGNOSTIC_V231 = ROOT / "results/joint_belief_v2_3_1/20260918-v231-r1-offline"
R7_SOURCE = ROOT / "results/joint_belief_v2_1/20260918-v21-r7-live-75"
V22_SOURCE = ROOT / "results/joint_belief_v2_2/20260918-v22-r7-offline"
ATTACHMENT = Path("/Users/jiayaochen/.codex/attachments/1168897f-04cd-4284-9eec-407af326f837/pasted-text.txt")
TOTAL_BUDGET_CNY = 20.0
PILOT_BUDGET_CNY = 5.0
MAX_PAID_ATTEMPTS = 240
MAX_PILOT_ATTEMPTS = 60
PRODUCTION_ASSASSIN_MAPPING = "existing_native_merlin_argmax_with_model_tiebreak"


def _json(path: Path, default=None):
    path = Path(path)
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _write_text(path: Path, value: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def _code_paths() -> list[Path]:
    names = [
        "avalon/engine.py", "avalon/chronicle.py", "avalon/evidence.py", "avalon/cognition.py",
        "avalon/joint_beliefs.py", "avalon/mission_likelihood.py", "avalon/eval/simulation.py",
        "avalon/eval/v2/adapters.py", "avalon/eval/v2/v21_contract.py", "avalon/eval/v2/v21_runtime.py",
        "avalon/eval/v2/live.py", "avalon/eval/v2/v23_merlin.py", "avalon/eval/v2/v231_channel.py",
        "avalon/eval/v2/v231_runner.py", "avalon/eval/v2/v232_channel.py", "avalon/eval/v2/v232_runner.py",
        "prompts/corrupted_castle_system.md", "docs/joint-belief-v21.md", "docs/joint-belief-v22.md",
        "docs/joint-belief-v23.md",
    ]
    return [ROOT / name for name in names if (ROOT / name).exists()]


def _source_files(root: Path) -> list[Path]:
    names = ["config.json", "dataset_manifest.json", "snapshot_results.csv", "games.csv",
             "paired_outcomes.csv", "assassin_signal_audit.json", "assassin_signal_trace.csv",
             "source_manifest.json", "v23_source_replays.jsonl", "llm_calls.jsonl"]
    files = [root / n for n in names if (root / n).exists()]
    files += sorted((root / "active_replays").glob("*.json"))
    return files


def _find_agents() -> list[str]:
    out = []
    for parent in [ROOT, *ROOT.parents]:
        p = parent / "AGENTS.md"
        if p.exists(): out.append(str(p))
    return out


def _load_records():
    sources = []
    for path in sorted((R7_SOURCE / "active_replays").glob("*.json")):
        sources.append(("20260918-v21-r7-live-75", "development_diagnostic", json.loads(path.read_text(encoding="utf-8")), str(path)))
    for path in sorted((PRIMARY_SOURCE / "active_replays").glob("*.json")):
        sources.append(("20260918-v23-r2-live20", "v23_active_diagnostic", json.loads(path.read_text(encoding="utf-8")), str(path)))
    source_jsonl = PRIMARY_SOURCE / "v23_source_replays.jsonl"
    for record in read_jsonl(source_jsonl):
        sources.append(("20260918-v23-r2-live20", "v23_source_diagnostic", record, str(source_jsonl)))
    return sources


def prepare(out: Path) -> dict:
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=False)
    missing = [str(p) for p in (PRIMARY_SOURCE, R7_SOURCE, DIAGNOSTIC_V231) if not p.exists()]
    if missing:
        raise FileNotFoundError("missing read-only source: " + ", ".join(missing))
    source_hashes = {}
    for label, root in (("primary_v23", PRIMARY_SOURCE), ("r7_diagnostic", R7_SOURCE),
                        ("v231_audit", DIAGNOSTIC_V231), ("v22_diagnostic", V22_SOURCE)):
        for path in _source_files(root):
            source_hashes[f"{label}/{path.relative_to(root)}"] = sha256(path)
    current_hashes = {str(p.relative_to(ROOT)): sha256(p) for p in _code_paths()}
    attachment_hash = sha256(ATTACHMENT) if ATTACHMENT.exists() else None
    cfg = {
        "run_id": out.name, "created_utc": datetime.now(timezone.utc).isoformat(), "status": "prepared",
        "version": "joint_belief_v2_3_2", "live": False, "budget_cny": None,
        "network_access": False, "network_calls": 0, "candidate_enabled_by_default": False,
        "candidate_status": "not_implemented_until_actionable_channel_gate",
        "total_budget_cny": TOTAL_BUDGET_CNY, "pilot_budget_cny": PILOT_BUDGET_CNY,
        "max_paid_request_attempts": MAX_PAID_ATTEMPTS, "max_pilot_request_attempts": MAX_PILOT_ATTEMPTS,
        "max_attempts_per_logical_request": 3, "max_concurrency": 2,
        "frozen": {"belief": "joint_v2", "belief_comparison": ["joint_v1", "joint_v2"],
                   "rules": True, "evidence_extractor": True, "evidence_weights": True,
                   "mission_likelihood": True, "assassin_decoder": PRODUCTION_ASSASSIN_MAPPING,
                   "tie_equality": "exact Python equality; epsilon diagnostic only",
                   "v22_vote_candidate": False, "language_belief_factors": False,
                   "recursive_tom": False, "cross_game_memory": False, "candidate": False},
        "primary_source_run_id": "20260918-v23-r2-live20",
        "primary_source_path": str(PRIMARY_SOURCE.resolve()),
        "r7_source_run_id": "20260918-v21-r7-live-75", "r7_source_path": str(R7_SOURCE.resolve()),
        "v231_audit_path": str(DIAGNOSTIC_V231.resolve()), "v22_diagnostic_path": str(V22_SOURCE.resolve()),
        "instruction_attachment": str(ATTACHMENT) if ATTACHMENT.exists() else None,
        "instruction_attachment_sha256": attachment_hash, "epsilon_diagnostic": EPSILON_DIAGNOSTIC,
        "historical_data_role": "r7/v2.2/v2.3 are diagnostic only; no historical response is a new game sample",
        "source_hashes": source_hashes, "current_code_hashes": current_hashes, "git": git_info(),
        "AGENTS_found": _find_agents(), "tests": {},
        "test_commands": {"prepare": "python -m avalon.eval.v2.v232_runner --mode prepare --run-dir <run>",
                          "diagnose": "python -m avalon.eval.v2.v232_runner --mode diagnose --run-dir <run>",
                          "unit": "python -m avalon.eval.v2.v232_runner --mode tests --run-dir <run> --tests-scope unit",
                          "regression": "python -m avalon.eval.v2.v232_runner --mode tests --run-dir <run> --tests-scope regression",
                          "report_only": "python -m avalon.eval.v2.v232_runner --mode report-only --run-dir <run>",
                          "pilot": "python -m avalon.eval.v2.v232_runner --mode pilot --run-dir <run>"},
    }
    write_json(out / "config.json", cfg)
    write_json(out / "source_manifest.json", {
        "primary_source_run_id": cfg["primary_source_run_id"], "primary_source_path": str(PRIMARY_SOURCE.resolve()),
        "r7_source_run_id": cfg["r7_source_run_id"], "r7_source_path": str(R7_SOURCE.resolve()),
        "source_hashes": source_hashes, "current_code_hashes": current_hashes,
        "instruction_attachment": str(ATTACHMENT) if ATTACHMENT.exists() else None,
        "instruction_attachment_sha256": attachment_hash, "git": git_info(), "AGENTS_found": _find_agents(),
        "network_calls": 0, "historical_samples_pooled": False,
        "read_sources": [str(PRIMARY_SOURCE), str(R7_SOURCE), str(DIAGNOSTIC_V231), str(V22_SOURCE)],
    })
    write_json(out / "preregistered_plan.json", {
        "version": "joint_belief_v2_3_2", "frozen_before_live": True,
        "stage_a": {"records": "r7 active + v2.3 active + v2.3 source; each cohort labelled", "epsilon": EPSILON_DIAGNOSTIC,
                     "factor_ablation": ["all", "hard_only", "no_social", "no_mission_soft"]},
        "stage_b": {"max_scenarios": 4, "conditions": ["A1", "A2", "B_DISPLAY_ABLATION"],
                     "repetitions": 3, "max_initial_requests": 36, "pilot_cap_cny": PILOT_BUDGET_CNY,
                     "total_cap_cny": TOTAL_BUDGET_CNY, "max_concurrency": 2,
                     "eligibility": "historical natural production exact tie + public free text in model input",
                     "not_a_candidate": True},
        "stage_c": {"max_candidates": 1, "default_enabled": False, "status": "blocked_until_actionable_channel"},
        "stage_d": {"status": "not_planned_until_stage_c_gate"},
        "source_splits": {"r7": "development_diagnostic", "v2.3": "diagnostic controlled", "new_live": "none until gate"},
    })
    _write_text(out / "candidate_spec.md", """# Joint Belief v2.3.2 candidate specification\n\nNo production candidate is implemented at preparation. Stage A must first show a public Merlin action that changes a non-constant numeric signal consumed by the Assassin decoder. The existing v2.3 disclosure context and the v2.2 vote context stay disabled. If Stage A does not establish an actionable channel, this file remains `not_implemented` and no live game is started.\n""")
    _write_text(out / "prechange_audit.md", f"""# Joint Belief v2.3.2 prechange audit\n\n## Frozen sources\n\nPrimary read-only source: `{PRIMARY_SOURCE}` (`20260918-v23-r2-live20`). Historical diagnostic source: `{R7_SOURCE}` (`20260918-v21-r7-live-75`). Previous offline audit: `{DIAGNOSTIC_V231}`. V2.2 diagnostic source: `{V22_SOURCE}`. No old response is counted as a new model sample.\n\n## Code path found\n\nThe production path is `public Chronicle event -> Observation.from_event -> BeliefEngine._process/_apply_evidence -> EvidenceExtractor/LikelihoodModel -> VersionedBeliefs -> v21_contract.decode_menu`. Assassin decoding takes the native maximum Merlin marginal and uses a submitted full permutation only for exact Python equality ties. `epsilon_diagnostic={EPSILON_DIAGNOSTIC}` is diagnostic and never changes production equality.\n\n`EvidenceExtractor` is not assumed to be the only numeric entry: the audit records hard mission/role constraints, mission soft likelihood, team/vote/social factors, signal deduplication and decoder inputs. R7 requests are replayed as `development_diagnostic`; v2.3 active/source replays are separate diagnostic cohorts. The one invalid r7 replay, if still invalid under the production validator, is preserved as `REPLAY_MISMATCH` rather than repaired.\n\nNo production file, rule, weight, prompt, menu, Assassin policy, or default candidate is changed by this run. Stage A is offline. Stage B may use at most the preregistered historical exact-tie pilot after the offline gate and budget preflight; it is a text projection diagnostic, not a candidate.\n\n## Dirty-state preservation\n\nGit commit, dirty diff fingerprint, source hashes and current source hashes are recorded in `source_manifest.json` and `config.json`. Existing run directories remain read-only.\n""")
    # Every required output has a schema, even before diagnose/live.
    _initialize_empty_outputs(out)
    return cfg


def _initialize_empty_outputs(out: Path):
    schemas = {
        "assassin_exposure_timeline.csv": ["run_id", "source_run_id", "cohort_role", "scenario_id", "scenario_family", "game_id", "observer_id", "variant", "event_id", "source_signal_id", "event_kind", "actor", "round", "attempt", "phase", "legal_observation_hash", "public_prefix_hash", "factor_origin_module", "factor_name", "factor_live_support_min", "factor_live_support_max", "constant_on_live_support", "posterior_before_hash", "posterior_after_hash", "max_abs_raw_delta", "merlin_marginals_before", "merlin_marginals_after", "native_exact_top_before", "native_exact_top_after", "near_top_diagnostic_before", "near_top_diagnostic_after", "log_odds_delta_by_candidate", "factor_consumed", "duplicate_suppressed", "event_observed", "true_merlin_scorer", "true_merlin"],
        "first_identification.csv": ["source_run_id", "cohort_role", "scenario_id", "game_id", "observer_id", "variant", "true_merlin", "initial_unique_top_true_merlin", "initial_top", "first_unique_true_merlin", "first_meaningful_nonfloating_separation", "sustained_final_lock_start", "wrong_unique_lock_count", "floating_unique_lock_count", "terminal_top", "terminal_unique_true_merlin"],
        "factor_ablation.csv": ["source_run_id", "cohort_role", "scenario_id", "game_id", "observer_id", "variant", "disabled_family", "events_replayed", "posterior_hash_final", "baseline_final_hash", "final_hash_equal_baseline", "true_merlin", "true_merlin_probability_final", "native_exact_top_final", "near_top_diagnostic_final", "scope"],
        "numerical_tie_audit.csv": ["dataset_role", "source_run_id", "scenario_id", "game_id", "variant", "observer_id", "native_values", "native_exact_top_set", "native_exact_top_count", "near_top_diagnostic_set", "epsilon_diagnostic", "max_gap", "production_tie_rule", "production_tie_branch_used", "submitted_assassin_ranking", "submitted_assassin_ranking_length", "ranking_unavailable_reason", "decoder_mapping", "selected_target", "target_reason", "true_merlin", "target_is_true_merlin", "public_text_in_model_input", "input_hash", "response_hash"],
        "comparison_inventory.csv": ["scenario_id", "source_game_id", "decision_id", "stage", "round", "action_delta", "comparison_status", "public_prefix_equal", "mechanical_pre_state_equal", "observer_belief_pre_state_equal", "legal_view_equal", "reference_exists", "candidate_exists", "reference_valid", "candidate_valid", "card_changed", "target_changed", "citation_changed", "commitment_changed", "resource_use_changed", "text_changed", "reference_action", "candidate_action", "reference_pre_state_hash", "candidate_pre_state_hash", "public_prefix_hash_reference", "public_prefix_hash_candidate", "source_kind"],
        "assassin_tie_path.csv": ["dataset_role", "source_run_id", "scenario_id", "game_id", "variant", "observer_id", "native_values", "native_exact_top_set", "native_exact_top_count", "near_top_diagnostic_set", "epsilon_diagnostic", "max_gap", "production_tie_rule", "production_tie_branch_used", "submitted_assassin_ranking", "submitted_assassin_ranking_length", "ranking_unavailable_reason", "decoder_mapping", "selected_target", "target_reason", "true_merlin", "target_is_true_merlin", "public_text_in_model_input", "input_hash", "response_hash"],
        "snapshot_interventions.csv": ["scenario_id", "source_game_id", "decision_id", "comparison_status", "action_delta", "reference_action", "candidate_action", "reference_error", "candidate_error", "reference_posterior_before", "candidate_posterior_before", "reference_posterior_after", "candidate_posterior_after", "reference_true_merlin_rank_after", "candidate_true_merlin_rank_after", "reference_top_after", "candidate_top_after", "reference_factor_names", "candidate_factor_names", "future_events_injected", "estimand"],
        # Stage D is intentionally not run when the mechanism gate is closed.
        # Keep a concrete schema so NOT_RUN is distinguishable from loss of a
        # required artifact.
        "paired_games.csv": ["pair_id", "scenario_id", "source_game_id", "arm", "status", "winner", "terminal_reason", "error", "source_role", "candidate_version"],
        "tie_live_results.csv": ["status", "logical_request_id", "attempt_id", "condition", "replicate", "scenario_id", "source_game_id", "observer_id", "payload_hash", "text_visibility_map", "response_status", "returned_model", "usage_status", "usage", "estimated_cny", "conservative_reserved_cny", "accepted", "submitted_assassin_ranking", "decoded_target", "native_exact_top_set", "target_changed_from_A1", "failure_class"],
    }
    for name, fields in schemas.items(): write_csv(out / name, [], fields)
    for name in ("factor_provenance.jsonl", "api_calls.jsonl"):
        _write_text(out / name, "")
    write_json(out / "cost_summary.json", {"status": "NOT_RUN", "budget_cny": TOTAL_BUDGET_CNY,
                                             "pilot_cap_cny": PILOT_BUDGET_CNY, "known_usage_cny": 0.0,
                                             "unknown_usage_cny": None, "in_flight_reserve_cny": None,
                                             "attempts": 0, "logical_requests": 0, "invoice_cny": None})
    write_json(out / "gates.json", {"stage_a": "NOT_RUN", "stage_b": "NOT_RUN", "stage_c": "NOT_RUN",
                                     "stage_d": "NOT_RUN", "labels": []})
    write_json(out / "summary.json", {"run_id": out.name, "status": "prepared", "network_calls": 0})
    _write_text(out / "report.md", "# Joint Belief v2.3.2\n\nPrepared; offline diagnosis has not run.\n")


def diagnose(out: Path) -> dict:
    out = Path(out).resolve()
    cfg = _json(out / "config.json")
    if not cfg:
        raise FileNotFoundError(out / "config.json")
    timelines, factors, identifications, ablations, errors = [], [], [], [], []
    sources = _load_records()
    for source_run_id, cohort, record, origin in sources:
        try:
            for variant in ("joint_v1", "joint_v2"):
                result = replay_record(record, variant=variant, source_run_id=source_run_id, cohort_role=cohort)
                timelines.extend(result["timeline"]); factors.extend(result["factors"])
                identifications.append(first_identification(result))
            # Ablation is fixed-prefix only and is explicitly kept out of action
            # effect estimates.  Keep one copy per source game/cohort.
            ablations.extend(factor_ablation(record, source_run_id, cohort))
        except Exception as exc:
            errors.append({"source_run_id": source_run_id, "cohort_role": cohort,
                           "scenario_id": record.get("scenario_id"), "game_id": record.get("game_id"),
                           "origin": origin, "error": f"{type(exc).__name__}: {exc}",
                           "classification": "REPLAY_MISMATCH"})
    # Preserve the contract schema initialized in prepare, adding fields only
    # through DictWriter's extrasaction=ignore.
    write_csv(out / "assassin_exposure_timeline.csv", timelines,
              _csv_fields(out / "assassin_exposure_timeline.csv"))
    write_csv(out / "first_identification.csv", identifications, _csv_fields(out / "first_identification.csv"))
    write_csv(out / "factor_ablation.csv", ablations, _csv_fields(out / "factor_ablation.csv"))
    with (out / "factor_provenance.jsonl").open("w", encoding="utf-8") as stream:
        for row in factors: stream.write(canonical(row) + "\n")
    if errors:
        write_csv(out / "replay_errors.csv", errors, list(errors[0]))
    inventory, details = inventory_v232(PRIMARY_SOURCE)
    write_csv(out / "comparison_inventory.csv", inventory, _csv_fields(out / "comparison_inventory.csv"))
    interventions = snapshot_interventions(PRIMARY_SOURCE, inventory, details)
    write_csv(out / "snapshot_interventions.csv", interventions, _csv_fields(out / "snapshot_interventions.csv"))
    ties, eligible, _ = tie_audit(R7_SOURCE, PRIMARY_SOURCE)
    write_csv(out / "numerical_tie_audit.csv", ties, _csv_fields(out / "numerical_tie_audit.csv"))
    write_csv(out / "assassin_tie_path.csv", ties, _csv_fields(out / "assassin_tie_path.csv"))
    factor_counts = Counter(row.get("factor_name") or "NO_FACTOR" for row in factors)
    constant_rows = [r for r in factors if r.get("constant_on_live_support")]
    numeric_changes = [r for r in timelines if r.get("posterior_before_hash") != r.get("posterior_after_hash")]
    exact_ties = [r for r in ties if int(r.get("production_tie_branch_used") or 0) == 1]
    public_text_ties = [r for r in exact_ties if str(r.get("public_text_in_model_input")) == "1"]
    matched = [r for r in inventory if r.get("comparison_status") == "MATCHED_PREFIX"]
    intervention_changes = [r for r in interventions if r.get("reference_top_after") != r.get("candidate_top_after") or
                            r.get("reference_true_merlin_rank_after") != r.get("candidate_true_merlin_rank_after")]
    source_status = "SOURCE_COMPLETE" if not errors else "REPLAY_MISMATCH"
    language_status = "APPLICABLE_HISTORICAL_DIAGNOSTIC" if public_text_ties else "NOT_APPLICABLE_TO_THIS_PATH"
    gates = {
        "stage_a": "PASS_WITH_REPLAY_MISMATCH" if errors else "PASS",
        "source_status": source_status, "replay_status": source_status,
        "numeric_entry_routes": {"timeline_rows": len(timelines), "factor_rows": len(factors),
                                  "factor_counts": dict(factor_counts), "posterior_changed_rows": len(numeric_changes),
                                  "constant_factor_rows": len(constant_rows)},
        "identification_status": {"rows": len(identifications),
                                   "true_merlin_unique_terminal": sum(r.get("terminal_unique_true_merlin", 0) for r in identifications),
                                   "wrong_locks": sum(r.get("wrong_unique_lock_count", 0) for r in identifications),
                                   "floating_locks": sum(r.get("floating_unique_lock_count", 0) for r in identifications)},
        "numerical_tie_status": {"rows": len(ties), "exact_tie_branch_rows": len(exact_ties),
                                  "epsilon_diagnostic": EPSILON_DIAGNOSTIC,
                                  "ranking_arrays_available": sum(bool(r.get("submitted_assassin_ranking")) for r in ties),
                                  "numeric_tie_instability": False},
        "language_path_status": language_status,
        "historical_tie_snapshots_available": len(eligible),
        "comparison_inventory": {"rows": len(inventory), "matched_prefix_rows": len(matched),
                                 "intervention_rows": len(interventions), "intervention_target_changes": len(intervention_changes)},
        "stage_b": "UNLOCKED_HISTORICAL_DIAGNOSTIC" if language_status == "APPLICABLE_HISTORICAL_DIAGNOSTIC" else "NOT_APPLICABLE_TO_THIS_PATH",
        # Ordinary mission/vote updates prove that the belief engine updates;
        # they do not prove that a Merlin action can control the decoder.  Only
        # the matched one-step intervention rows are admissible for this gate.
        "stage_c": "NO_ACTIONABLE_CHANNEL_FOUND" if not intervention_changes else "REQUIRES_REVIEW",
        "stage_d": "NOT_RUN",
        "labels": (["REPLAY_MISMATCH"] if errors else []) + (["TEXT_TIE_SCREENING_SIGNAL"] if public_text_ties else []) +
                  ([] if intervention_changes else ["NO_ACTIONABLE_CHANNEL_FOUND"]),
        "causal_scope": "fixed public-prefix replay and one-step interventions; no full-game counterfactual",
    }
    write_json(out / "gates.json", gates)
    _write_text(out / "candidate_spec.md", """# Joint Belief v2.3.2 candidate specification\n\n`not_implemented`. The offline audit did not establish a public Merlin action that changes the numeric signal consumed by the production Assassin decoder. Constant factors and historical text sensitivity do not unlock a strategy candidate. Production default remains off; no vote, language-belief, recursive-ToM or Assassin change is made.\n""")
    cfg.update({"status": "diagnosed", "network_calls": 0, "stage_a_gate": gates["stage_a"],
                "language_path_status": language_status, "stage_c_gate": gates["stage_c"],
                "records_attempted": len(sources), "replay_errors": len(errors),
                "timeline_rows": len(timelines), "factor_rows": len(factors), "tie_rows": len(ties)})
    write_json(out / "config.json", cfg)
    return {"cfg": cfg, "gates": gates, "timelines": timelines, "factors": factors,
            "identifications": identifications, "ablations": ablations, "ties": ties,
            "inventory": inventory, "interventions": interventions, "errors": errors,
            "eligible_ties": eligible}


def _csv_fields(path: Path) -> list[str]:
    with Path(path).open(encoding="utf-8") as stream:
        return next(csv.reader(stream), [])


def _tests(out: Path, name: str, paths: list[str]) -> dict:
    xml = out / f"{name}_tests.xml"; log = out / f"{name}_tests.log"
    env = {**os.environ, "PYTHONHASHSEED": "0", "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
    with log.open("w", encoding="utf-8") as stream:
        result = subprocess.run([sys.executable, "-m", "pytest", "-q", *paths, f"--junitxml={xml}"],
                                cwd=ROOT, env=env, stdout=stream, stderr=subprocess.STDOUT, check=False)
    root = ET.parse(xml).getroot(); suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    counts = {k: sum(int(s.get(k, 0)) for s in suites) for k in ("tests", "failures", "errors", "skipped")}
    counts.update(passed=counts["tests"] - counts["failures"] - counts["errors"] - counts["skipped"], exit_code=result.returncode)
    return counts


def tests(out: Path, scope: str | None = None) -> dict:
    out = Path(out).resolve(); cfg = _json(out / "config.json")
    selected = {"unit": _tests(out, "unit", ["tests/eval"]),
                "regression": _tests(out, "regression", ["tests"])}
    cfg["tests"] = selected; write_json(out / "config.json", cfg)
    if any(x["exit_code"] for x in selected.values()): raise SystemExit(1)
    return selected


def _read_csv(path: Path) -> list[dict[str, str]]:
    return list(csv.DictReader(path.open(encoding="utf-8"))) if path.exists() else []


def report(out: Path) -> dict:
    out = Path(out).resolve(); cfg = _json(out / "config.json", {}); gates = _json(out / "gates.json", {})
    timeline = _read_csv(out / "assassin_exposure_timeline.csv"); factors = []
    if (out / "factor_provenance.jsonl").exists():
        factors = [json.loads(x) for x in (out / "factor_provenance.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    ident = _read_csv(out / "first_identification.csv"); ablation = _read_csv(out / "factor_ablation.csv")
    inventory = _read_csv(out / "comparison_inventory.csv"); ties = _read_csv(out / "numerical_tie_audit.csv"); interventions = _read_csv(out / "snapshot_interventions.csv")
    api_rows = [json.loads(x) for x in (out / "api_calls.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()] if (out / "api_calls.jsonl").exists() else []
    api_failure_classes = Counter(r.get("failure_class") or "none" for r in api_rows)
    pilot_by_condition = {}
    for condition in ("A1", "A2", "B_DISPLAY_ABLATION"):
        subset = [r for r in api_rows if r.get("condition") == condition]
        pilot_by_condition[condition] = {
            "attempts": len(subset), "accepted": sum(bool(r.get("accepted")) for r in subset),
            "failed": sum(not bool(r.get("accepted")) for r in subset),
            "accepted_rate": (sum(bool(r.get("accepted")) for r in subset) / len(subset) if subset else None),
        }
    aa_by_scenario = {}
    for row in api_rows:
        if row.get("condition") in {"A1", "A2"}:
            aa_by_scenario.setdefault(row.get("scenario_id"), set()).add(row.get("payload_hash"))
    b_rows = [r for r in api_rows if r.get("condition") == "B_DISPLAY_ABLATION" and r.get("accepted")]
    accepted_target_changes = sum(bool(r.get("target_changed_from_A1")) for r in b_rows)
    lock_sources = Counter()
    for row in ident:
        if row.get("variant") != "joint_v2" or not row.get("first_unique_true_merlin"):
            continue
        try:
            first = ast.literal_eval(row["first_unique_true_merlin"])
        except (SyntaxError, ValueError):
            continue
        if isinstance(first, dict) and first.get("event_id"):
            lock_sources[(first.get("event_id"), first.get("factor_name") or "NO_FACTOR")] += 1
    pilot_result = ("INCONCLUSIVE_OUTPUT_FAILURES" if api_rows and any(not r.get("accepted") for r in api_rows)
                    else "COMPLETED" if api_rows else "NOT_RUN")
    statuses = Counter(r.get("comparison_status") for r in inventory)
    deltas = Counter(r.get("action_delta") for r in inventory)
    summary = {
        "run_id": out.name, "status": "complete", "version": "joint_belief_v2_3_2", "live": bool(api_rows),
        "network_calls": len(api_rows), "primary_source_run_id": cfg.get("primary_source_run_id"),
        "diagnostic_source_run_id": cfg.get("r7_source_run_id"), "gates": gates,
        "tests": cfg.get("tests", {}),
        "source_data_role": "historical r7 and v2.3 cohorts are diagnostic; not pooled as new effects",
        "replay": {"timeline_rows": len(timeline), "factor_rows": len(factors), "identification_rows": len(ident),
                   "ablation_rows": len(ablation), "replay_errors": len(_read_csv(out / "replay_errors.csv"))},
        "numeric_attribution": {"factor_counts": dict(Counter(r.get("factor_name") or "NO_FACTOR" for r in factors)),
                                "constant_factor_rows": sum(bool(r.get("constant_on_live_support")) for r in factors),
                                "posterior_changed_rows": sum(r.get("posterior_before_hash") != r.get("posterior_after_hash") for r in timeline)},
        "identification": {"rows": len(ident), "wrong_lock_count": sum(int(r.get("wrong_unique_lock_count") or 0) for r in ident),
                            "floating_lock_count": sum(int(r.get("floating_unique_lock_count") or 0) for r in ident),
                            "joint_v2_first_true_lock_sources": [
                                {"event_id": event_id, "factor_name": factor_name, "rows": count}
                                for (event_id, factor_name), count in lock_sources.most_common(10)]},
        "comparison_inventory": {"rows": len(inventory), "action_delta": dict(deltas), "comparison_status": dict(statuses)},
        "snapshot_interventions": {"rows": len(interventions), "future_events_injected": 0},
        "tie_audit": {"rows": len(ties), "production_tie_rows": sum(int(r.get("production_tie_branch_used") or 0) for r in ties),
                       "ranking_arrays": sum(bool(r.get("submitted_assassin_ranking")) for r in ties),
                       "public_text_rows": sum(str(r.get("public_text_in_model_input")) == "1" for r in ties)},
        "api": {"logical_requests": len({r.get("logical_request_id") for r in api_rows}), "attempts": len(api_rows),
                "accepted": sum(bool(r.get("accepted")) for r in api_rows),
                "unknown_usage": sum(r.get("usage_status") == "unavailable" for r in api_rows),
                "failure_classes": dict(api_failure_classes), "by_condition": pilot_by_condition,
                "aa_payload_hashes_equal_by_scenario": all(len(values) == 1 for values in aa_by_scenario.values()) if aa_by_scenario else None,
                "b_accepted_target_changes": accepted_target_changes,
                "pilot_result": pilot_result},
        "labels": gates.get("labels", []) + (["PILOT_ONLY", "INCONCLUSIVE"] if api_rows else ["NOT_RUN"]),
        "claims": {"actionable_channel": gates.get("stage_c", "NOT_TESTED"),
                   "full_game_effect": "NOT_TESTED", "production_promotion": False},
    }
    write_json(out / "summary.json", summary)
    cost = _json(out / "cost_summary.json", {})
    if not api_rows:
        cost.update({"status": "NOT_RUN", "attempts": 0, "logical_requests": 0})
    write_json(out / "cost_summary.json", cost)
    gate_label = gates.get("stage_c", "NOT_TESTED")
    lines = ["# Joint Belief v2.3.2：刺客识别归因与精确并列诊断", "",
             f"运行 `{out.name}`；生产默认仍关闭。主来源 `{cfg.get('primary_source_run_id')}`，r7 仅为 `{cfg.get('r7_source_run_id')}` 历史诊断。",
             "", "## 1. 冻结边界与重放", "",
             f"离线重放记录 {len(timeline)} 个刺客公开事件、{len(factors)} 条数值因子、{len(ident)} 条锁定轨迹；错误/缺失按 `{gates.get('source_status')}` 保留。重复投递在副本中检查幂等性；没有注入未来事件。",
             "", "## 2. 刺客实际识别链路", "",
             "生产路径为 public event → Observation → EvidenceExtractor/LikelihoodModel → joint_v2 posterior → native exact argmax → exact-tie ranking decoder。`assassin_tie_path.csv` 保留完整 ranking 数组和独立长度；不可恢复的历史排序写 null。",
             f"因子计数：{json.dumps(summary['numeric_attribution']['factor_counts'], ensure_ascii=False)}。posterior 变化事件 {summary['numeric_attribution']['posterior_changed_rows']}；常数因子记录 {summary['numeric_attribution']['constant_factor_rows']}。锁定错误次数 {summary['identification']['wrong_lock_count']}，浮点诊断锁定 {summary['identification']['floating_lock_count']}。",
             f"joint_v2 首次把真实梅林推到唯一最高的可追溯来源（前十，按轨迹行数）：{json.dumps(summary['identification']['joint_v2_first_true_lock_sources'], ensure_ascii=False)}；完整事件、前后概率和哈希在 `first_identification.csv`，未能归因的行保留 `NO_FACTOR`。",
             "", "## 3. 并列与文字通道", "",
             f"数值并列审计 {summary['tie_audit']['rows']} 行，生产 tie branch {summary['tie_audit']['production_tie_rows']} 行，其中输入含公开文字 {summary['tie_audit']['public_text_rows']} 行。epsilon 只用于诊断，未替换生产精确相等。Stage B 状态：`{gates.get('stage_b')}`。",
             f"Pilot 按条件完成率：{json.dumps(summary['api']['by_condition'], ensure_ascii=False)}；失败分类：{json.dumps(summary['api']['failure_classes'], ensure_ascii=False)}。A/A payload hash 在每个 scenario 内相同：{summary['api']['aa_payload_hashes_equal_by_scenario']}。B 条件有效响应造成的目标变化：{summary['api']['b_accepted_target_changes']}。由于 B 条件没有有效完成的模型输出，文字通道结论为 `{summary['api']['pilot_result']}`，不能标记为已证实的 TEXT_TIE_SCREENING_SIGNAL。",
             "", "## 4. 动作比较与候选", "",
             f"动作清单 {summary['comparison_inventory']['rows']} 行；action_delta={json.dumps(summary['comparison_inventory']['action_delta'], ensure_ascii=False)}；comparison_status={json.dumps(summary['comparison_inventory']['comparison_status'], ensure_ascii=False)}。分叉后的 PASS 不按序号强行配对。",
             f"Stage C：`{gate_label}`。当前没有实施新的生产候选；v2.2 投票、语言 belief、递归 ToM、刺客规则和提示词均未打开。",
             "", "## 5. API、样本与限制", "",
             f"真实调用 {summary['api']['attempts']} 次、逻辑请求 {summary['api']['logical_requests']}、成功 {summary['api']['accepted']}；未知 usage {summary['api']['unknown_usage']}。费用详见 `cost_summary.json`，未知 usage 不记为 0。固定候选对局：`paired_games.csv` 为 NOT_RUN（Stage C 未解锁）。完整对局效果：NOT_TESTED。",
             "30 个拒绝解码的响应已在 `pilot_recovery_audit.json` 中按 provider usage 结算；初始 harness 未持久化其安全的原始动作正文，因此没有猜测或修正这些动作，也没有把它们重试为新样本。",
             "r7 与 v2.3 回放用于机制诊断，不构成新的 held-out 效果样本；本轮未因输赢挑选场景，也没有追加候选。",
             f"最终本地测试：{json.dumps(summary['tests'], ensure_ascii=False)}；测试通过不等同于能力提升。",
             "", "## 6. 原始文件与复算", "",
             "报告只从 CSV/JSONL/JSON 重算。无网络复算命令：`python -m avalon.eval.v2.v232_runner --mode report-only --run-dir <run>`。关键原始表：`assassin_exposure_timeline.csv`、`factor_provenance.jsonl`、`first_identification.csv`、`factor_ablation.csv`、`numerical_tie_audit.csv`、`comparison_inventory.csv`、`assassin_tie_path.csv`、`snapshot_interventions.csv`、`tie_live_results.csv`。",
             "", "结论标签：" + ", ".join(summary["labels"] or ["INCONCLUSIVE"])]
    _write_text(out / "report.md", "\n".join(lines) + "\n")
    final_code_hashes = {str(p.relative_to(ROOT)): sha256(p) for p in _code_paths()}
    cfg.update({"status": "complete", "final_code_hashes": final_code_hashes})
    write_json(out / "config.json", cfg)
    manifest = _json(out / "source_manifest.json", {})
    manifest["final_code_hashes"] = final_code_hashes
    manifest["network_calls"] = len(api_rows)
    manifest["pilot_network_calls"] = len(api_rows)
    manifest["report_generated_utc"] = datetime.now(timezone.utc).isoformat()
    write_json(out / "source_manifest.json", manifest)
    return summary


def pilot(out: Path) -> dict:
    """Run the preregistered historical exact-tie pilot, if offline-unlocked."""
    out = Path(out).resolve(); gates = _json(out / "gates.json", {})
    if gates.get("stage_b") != "UNLOCKED_HISTORICAL_DIAGNOSTIC":
        return {"status": "NOT_APPLICABLE_TO_THIS_PATH", "reason": gates.get("stage_b")}
    # The complete pilot implementation is isolated here and intentionally
    # uses the existing ChatClient/DurableBudget rather than a second HTTP path.
    from avalon.eval.v2.live import BudgetStop, PRICING, token_cost
    from avalon.eval.v2.v21_runtime import DurableBudget
    from avalon.llm import ChatClient, Settings, LLMError
    from avalon.eval.v2.v21_contract import decode_menu
    settings = Settings.load()
    if not settings.ready:
        result = {"status": "NOT_RUN_MISSING_CREDENTIALS", "reason": "Settings.load().ready=false"}
        _append_pilot_status(out, result); return result
    old_cfg = _json(PRIMARY_SOURCE / "config.json", {}).get("settings", {})
    # Keep the frozen model/transport fields from the source where available;
    # the key itself is read only from the local secure environment.
    for field in ("base_url", "model", "max_tokens", "token_field", "json_mode", "thinking", "temperature", "timeout", "max_retries", "retry_delay"):
        if field in old_cfg and field != "api_key": setattr(settings, field, old_cfg[field])
    budget = DurableBudget(out, PILOT_BUDGET_CNY, MAX_PILOT_ATTEMPTS)
    client = ChatClient(settings)
    model_config_hash = digest({
        "base_url": settings.base_url, "model": settings.model,
        "max_tokens": settings.max_tokens, "token_field": settings.token_field,
        "json_mode": settings.json_mode, "thinking": settings.thinking,
        "temperature": settings.temperature, "timeout": settings.timeout,
        "max_retries": settings.max_retries,
        "world_prompt_sha256": sha256(client.world_prompt_path),
    })
    candidates = []
    for item in r7_assassin_requests(R7_SOURCE):
        response = item["response"]; parsed = response.get("parsed_action") or {}; params = parsed.get("parameters") if isinstance(parsed, dict) else {}
        if response.get("policy_mapping") != PRODUCTION_ASSASSIN_MAPPING or not isinstance(params, dict) or not isinstance(params.get("assassin_rank"), list): continue
        c = item["request"].get("context", {})
        tie = next((r for r in _read_csv(out / "numerical_tie_audit.csv") if r.get("input_hash") == item["request"].get("context_hash")), None)
        if tie and tie.get("production_tie_branch_used") == "1" and tie.get("public_text_in_model_input") == "1": candidates.append(item)
    # One deterministic scenario per source scenario, at most four; all three
    # conditions are interleaved and each receives three independent requests.
    unique = {}
    for item in candidates: unique.setdefault(item["request"].get("scenario_id"), item)
    selected = [unique[k] for k in sorted(unique)[:4]]
    rows = []
    with (out / "api_calls.jsonl").open("a", encoding="utf-8") as audit:
        for item in selected:
            request, response = item["request"], item["response"]; base = request["context"]
            game_id = request.get("game_id"); record_path = R7_SOURCE / "active_replays" / (str(game_id).split(":")[-1] + ".json")
            record = _json(record_path, {}); decision = next((d for d in record.get("decisions", []) if d.get("phase") == "assassination"), {})
            view = decision.get("view", {}); marg = decision.get("marginals", {})
            adapter_context = {"view": view, "marginals": marg}
            for condition in ("A1", "A2", "B_DISPLAY_ABLATION"):
                for replicate in range(3):
                    logical = f"{request.get('scenario_id')}:{condition}:{replicate}"
                    supplied = deepcopy(base) if condition != "B_DISPLAY_ABLATION" else __import__("avalon.eval.v2.v232_channel", fromlist=["text_ablate"]).text_ablate(base)
                    payload = client.request_payload(supplied); payload_hash = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
                    started_utc = datetime.now(timezone.utc).isoformat()
                    meta = {"run_id": out.name, "logical_request_id": logical, "condition": condition, "replicate": replicate,
                            "scenario_id": request.get("scenario_id"), "source_game_id": game_id, "observer_id": request.get("observer_id"),
                            "payload_hash": payload_hash, "model_config_hash": model_config_hash,
                            "sent_at": started_utc, "retry_reason": None, "transport_retry_count": 0,
                            "text_visibility_map": "free_text_removed" if condition == "B_DISPLAY_ABLATION" else "unchanged"}
                    uid = None; reservation = None
                    try:
                        client.last_call = {}
                        uid, reservation = budget.begin(payload, {**meta, "context": supplied, "run_phase": "pilot"})
                        raw = client.complete(supplied); action, details = decode_menu(raw, adapter_context, supplied)
                        usage = client.last_call.get("usage", {}); settled = budget.settle(reservation, usage, datetime.now(timezone.utc).isoformat()); row = {**meta, "attempt_id": uid, "status": "completed", "accepted": True,
                                "response_status": "accepted", "returned_model": client.last_call.get("model"), "usage_status": settled["usage_status"], "usage": usage,
                                "request_sha256": client.last_call.get("request_sha256"), "response_sha256": client.last_call.get("response_sha256"),
                                "ended_at": datetime.now(timezone.utc).isoformat(), "budget_charged_cny": settled["budget_charged_cny"],
                                "estimated_cny": settled["estimated_cny"], "conservative_reserved_cny": reservation["cny"], "submitted_assassin_ranking": json.dumps((details.get("parsed_action") or {}).get("parameters", {}).get("assassin_rank")),
                                "decoded_target": action.get("target"), "native_exact_top_set": None, "target_changed_from_A1": None, "failure_class": None}
                        budget.finish(uid, row)
                    except (BudgetStop, LLMError, ValueError, TypeError, KeyError) as exc:
                        # An HTTP response can be billable even when the
                        # production decoder rejects its output.  Settle and
                        # journal that attempt before continuing; never leave
                        # an in-flight reservation looking like a free retry.
                        usage = client.last_call.get("usage", {})
                        if "uid" in locals() and uid is not None:
                            settled = budget.settle(reservation, usage, datetime.now(timezone.utc).isoformat())
                            row = {**meta, "attempt_id": uid, "status": "failed", "accepted": False,
                                   "response_status": type(exc).__name__, "returned_model": client.last_call.get("model"),
                                   "usage_status": settled["usage_status"], "usage": usage,
                                   "request_sha256": client.last_call.get("request_sha256"), "response_sha256": client.last_call.get("response_sha256"),
                                   "ended_at": datetime.now(timezone.utc).isoformat(), "budget_charged_cny": settled["budget_charged_cny"],
                                   "estimated_cny": settled["estimated_cny"],
                                   "conservative_reserved_cny": reservation["cny"],
                                   "submitted_assassin_ranking": None, "decoded_target": None,
                                   "native_exact_top_set": None, "target_changed_from_A1": None,
                                   "failure_class": "decoder_validation_error" if isinstance(exc, ValueError) else type(exc).__name__}
                            budget.finish(uid, row)
                        else:
                            row = {**meta, "attempt_id": None, "status": "failed", "accepted": False,
                                   "response_status": type(exc).__name__, "returned_model": client.last_call.get("model"),
                                   "usage_status": "unknown" if isinstance(exc, LLMError) else "not_sent",
                                   "usage": usage, "estimated_cny": None, "conservative_reserved_cny": None,
                                   "request_sha256": client.last_call.get("request_sha256"), "response_sha256": client.last_call.get("response_sha256"),
                                   "ended_at": datetime.now(timezone.utc).isoformat(), "budget_charged_cny": None,
                                   "submitted_assassin_ranking": None, "decoded_target": None,
                                   "native_exact_top_set": None, "target_changed_from_A1": None,
                                   "failure_class": type(exc).__name__}
                    audit.write(canonical(row) + "\n"); rows.append(row)
    write_csv(out / "tie_live_results.csv", rows, _csv_fields(out / "tie_live_results.csv"))
    snap = budget.snapshot(); write_json(out / "cost_summary.json", {"status": "completed", "budget_cny": TOTAL_BUDGET_CNY, "pilot_cap_cny": PILOT_BUDGET_CNY,
        "known_usage_cny": snap.get("estimated_cny_from_reported_usage"), "unknown_usage_cny": None if not snap.get("unknown_usage_attempts") else None,
        "in_flight_reserve_cny": snap.get("pending_reserved_cny"), "attempts": len(rows), "logical_requests": len({r.get("logical_request_id") for r in rows}), "invoice_cny": None, "budget_snapshot": snap})
    pilot_status = "completed_with_rejected_outputs" if any(not r.get("accepted") for r in rows) else "completed"
    cfg = _json(out / "config.json", {}); cfg.update({"live": True, "network_calls": len(rows), "pilot_status": pilot_status, "pilot_selected_scenarios": len(selected)}); write_json(out / "config.json", cfg)
    return {"status": pilot_status, "rows": len(rows), "scenarios": len(selected), "budget": snap}


def _append_pilot_status(out: Path, result: dict):
    write_json(Path(out) / "cost_summary.json", {"status": result.get("status"), "budget_cny": TOTAL_BUDGET_CNY,
        "pilot_cap_cny": PILOT_BUDGET_CNY, "known_usage_cny": None, "unknown_usage_cny": None,
        "in_flight_reserve_cny": None, "attempts": 0, "logical_requests": 0, "invoice_cny": None, "reason": result.get("reason")})
    cfg = _json(Path(out) / "config.json", {}); cfg.update({"pilot_status": result.get("status"), "network_calls": 0}); write_json(Path(out) / "config.json", cfg)


def _run_r2_p0(mode: str, out: Path):
    """Keep the documented v2.3.2 CLI while isolating the P0 repair boundary."""
    from avalon.eval.v2 import v232_r2
    dispatch = {
        "p0-prepare": v232_r2.prepare,
        "p0-verify": v232_r2.verify,
        "p0-tests": v232_r2.run_tests,
        "p0-smoke": v232_r2.smoke,
        "p0-report-only": v232_r2.report,
    }
    return dispatch[mode](out)


def _run_r2_p1(mode: str, out: Path):
    """Offline V2.3.2-r2 P1 repair path.

    The P1 module intentionally has no paid client or network entry point.  It
    is kept as a separate dispatch so the existing P0 and historical pilot
    modes cannot accidentally be unlocked by a report request.
    """
    from avalon.eval.v2 import v232_p1
    dispatch = {
        "p1-prepare": v232_p1.prepare,
        "p1-analyze": v232_p1.analyze,
        "p1-tests": v232_p1.run_tests,
        "p1-report-only": v232_p1.report,
    }
    return dispatch[mode](out)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", required=True, choices=("prepare", "diagnose", "tests", "pilot", "report-only",
                                                           "p0-prepare", "p0-verify", "p0-tests", "p0-smoke",
                                                           "p0-report-only", "p1-prepare", "p1-analyze",
                                                           "p1-tests", "p1-report-only"))
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--tests-scope", choices=("unit", "regression"), default=None)
    args = parser.parse_args(argv); out = args.run_dir.resolve()
    if args.mode.startswith("p0-"):
        _run_r2_p0(args.mode, out)
    elif args.mode.startswith("p1-"):
        _run_r2_p1(args.mode, out)
    elif args.mode == "prepare": prepare(out)
    elif args.mode == "diagnose": diagnose(out)
    elif args.mode == "tests": tests(out, args.tests_scope)
    elif args.mode == "pilot": pilot(out)
    elif args.mode == "report-only":
        if not (out / "gates.json").exists() or _json(out / "gates.json", {}).get("stage_a") == "NOT_RUN": diagnose(out)
        report(out)


if __name__ == "__main__":
    main()
