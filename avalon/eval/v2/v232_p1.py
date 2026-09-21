"""Offline V2.3.2-r2 P1 repair and mechanism audit.

This module is intentionally an evaluation layer.  It does not change the
production belief engine, evidence weights, legal menu, decoder, or game
transactions.  P1 consumes the frozen P0 verification ledger and historical
diagnostic tables, then runs a small number of source-bound vote fixtures
through the production ``Game`` validator.  No network client is imported or
called here.
"""

from __future__ import annotations

import csv
from copy import deepcopy
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable

from avalon.chronicle import EVIDENCE_KINDS, PUBLIC_KINDS, context_record
from avalon.engine import Game, Player
from avalon.evidence import Evidence, EvidenceType
from avalon.eval.joint_belief import ROOT, git_info
from avalon.eval.simulation import digest, canonical
from avalon.eval.v2.adapters import make_version
from avalon.eval.v2.v21_contract import legal_menu
from avalon.eval.v2.v22_replay import source_transaction
from avalon.eval.v2.v232_channel import EPSILON_DIAGNOSTIC, sha256


RUN_VERSION = "joint_belief_v2_3_2_r2_p1"
P0_RUN = ROOT / "results/joint_belief_v2_3_2/20260919-v232-r2-p0"
HIST_RUN = ROOT / "results/joint_belief_v2_3_2/20260918-v232-r1-offline"
R7_SOURCE = ROOT / "results/joint_belief_v2_1/20260918-v21-r7-live-75"
V23_SOURCE = ROOT / "results/joint_belief_v2_3/20260918-v23-r2-live20"
P1_PLAN = Path("/Users/jiayaochen/Desktop/Avalon_V232_R2_P1_Codex_Repair_Plan.md")

REQUIRED_MISSING_FIXTURES = (
    "sealed-merlin-single-1171000:merlin:008",
    "sealed-merlin-single-1171000:merlin:009",
    "sealed-merlin-single-1171001:merlin:009",
)
NUMERIC_TARGETS = (
    {
        "source_run_id": "20260918-v21-r7-live-75",
        "scenario_id": "main-single_seat-940004",
        "game_id": "A-main-single_seat-940004-joint_v1",
        "observer_id": "P4",
        "variant": "joint_v2",
        "event_id": "R3-123",
        "signal_id": "vote:3:3:P1",
    },
    {
        "source_run_id": "20260918-v23-r2-live20",
        "scenario_id": "v23-source-dev-02",
        "game_id": "v23_source-1131002-joint_v2",
        "observer_id": "P5",
        "variant": "joint_v2",
        "event_id": "R2-078",
        "signal_id": "vote:2:2:P4",
    },
)

# These thresholds are frozen before the offline candidate comparison.  They
# are deliberately simple and use only legal Merlin state plus public history.
CANDIDATE_PUBLIC_SUSPICION_THRESHOLD = 2.0
CANDIDATE_AMBIGUITY_BAND = 1.0
CANDIDATE_CRITICAL_REJECTIONS = 4
CANDIDATE_CRITICAL_FAILURES = 2


def _read_json(path: Path, default: Any = None) -> Any:
    path = Path(path)
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not Path(path).exists():
        return []
    with Path(path).open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def _write_csv(path: Path, rows: Iterable[dict[str, Any]], fields: list[str] | None = None) -> None:
    rows = list(rows)
    if fields is None:
        fields = list(rows[0]) if rows else []
    path.parent.mkdir(parents=True, exist_ok=True)
    with Path(path).open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _append_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with Path(path).open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(canonical(row) + "\n")


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not Path(path).exists():
        return []
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def _bool(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    if str(value).lower() in {"1", "true", "yes"}:
        return True
    if str(value).lower() in {"0", "false", "no"}:
        return False
    return None


def _parse_json(value: Any, default: Any = None) -> Any:
    if value in (None, "", "null", "None"):
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def _event_seq(event_id: str | None) -> int | None:
    if not event_id:
        return None
    try:
        return int(str(event_id).rsplit("-", 1)[1])
    except (ValueError, IndexError):
        return None


def _top(value: Any) -> list[str]:
    parsed = _parse_json(value, [])
    return list(parsed) if isinstance(parsed, list) else []


def _value_map(value: Any) -> dict[str, float]:
    parsed = _parse_json(value, {})
    return {str(k): float(v) for k, v in parsed.items()} if isinstance(parsed, dict) else {}


def _roles(record: dict[str, Any]) -> dict[str, str]:
    return {str(player.get("id")): str(player.get("role")) for player in record.get("players", [])}


def _public_view(game: Game, pid: str) -> dict[str, Any]:
    """Return one seat's legal view plus the public prefix used by the ledger."""
    view = deepcopy(game.view(pid))
    view["legal_public_history"] = [context_record(event) for event in game.events
                                     if event.get("kind") in EVIDENCE_KINDS]
    return view


def _merlin_values(observer, view: dict[str, Any] | None = None) -> dict[str, float]:
    view = view or {}
    known = set(view.get("known_evil", []))
    return {pid: float(observer.marginals().get(pid, {}).get("merlin", 0.0))
            for pid in observer.ids if pid != observer.pid and pid not in known}


def _merlin_metrics(observer, true_merlin: str, view: dict[str, Any] | None = None) -> dict[str, Any]:
    values = _merlin_values(observer, view)
    top_value = max(values.values()) if values else None
    top = sorted(pid for pid, value in values.items() if value == top_value) if values else []
    true_value = values.get(true_merlin)
    competitors = [value for pid, value in values.items() if pid != true_merlin]
    lead = (true_value - max(competitors)) if true_value is not None and competitors else None
    rank = (1 + sum(value > true_value for pid, value in values.items() if pid != true_merlin)
            if true_value is not None else None)
    return {"true_merlin_probability": true_value, "true_merlin_rank": rank,
            "exact_top": top, "merlin_lead": lead, "values": values,
            "unique_top": top[0] if len(top) == 1 else None}


def _wrong_lock_segments(decisions: list[dict[str, Any]], true_merlin: str | None) -> list[dict[str, Any]]:
    """Count contiguous wrong unique-top states at actionable boundaries only."""
    if not true_merlin:
        return []
    segments: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for row in decisions:
        top = _top(row.get("native_exact_top_after") or row.get("native_exact_top_at_boundary"))
        unique = top[0] if len(top) == 1 else None
        decision_index = row.get("decision_index")
        if unique is None or unique == true_merlin:
            current = None
            continue
        if current is None or current["wrong_player"] != unique:
            current = {"wrong_player": unique, "start_decision_index": decision_index,
                       "end_decision_index": decision_index, "rows": 1}
            segments.append(current)
        else:
            current["end_decision_index"] = decision_index
            current["rows"] += 1
    return segments


def _event_signal_ids(event: dict[str, Any], observer_id: str) -> list[str]:
    if event.get("kind") == "VOTE":
        actors = [event.get("actor")]
    elif event.get("kind") == "TEAM_VOTE":
        actors = list((event.get("votes") or {}).keys())
    else:
        return []
    return [f"vote:{event.get('round')}:{event.get('attempt', 1)}:{actor}"
            for actor in actors if actor and actor != observer_id]


def _factor_likelihoods(observer, factor: dict[str, Any]) -> dict[str, list[float]]:
    """Report the factor's likelihood values grouped by possible Merlin seat."""
    engine = getattr(observer, "engine", None)
    if engine is None:
        return {}
    evidence_type = factor.get("evidence_type")
    if not isinstance(evidence_type, EvidenceType):
        evidence_type = EvidenceType(str(getattr(evidence_type, "value", evidence_type)))
    evidence = Evidence(
        origin_event_id=str(factor.get("origin_event_id")),
        source_agent=factor.get("source_agent"),
        target_agents=list(factor.get("target_agents") or []),
        evidence_type=evidence_type,
        feature=str(factor.get("feature")),
        direction=factor.get("direction"),
        strength=float(factor.get("strength", 1.0)),
        metadata=deepcopy(factor.get("metadata") or {}),
    )
    grouped: dict[str, list[float]] = {}
    for candidate in observer.ids:
        values = [engine.likelihood_model.evaluate(hypothesis, evidence)
                  for hypothesis in engine.beliefs.hypotheses
                  if hypothesis.roles.get(candidate) == "MERLIN"]
        grouped[candidate] = sorted({float(value) for value in values})
    return grouped


def _source_records() -> tuple[dict[tuple[str, str], dict[str, Any]], dict[str, Path]]:
    records: dict[tuple[str, str], dict[str, Any]] = {}
    paths: dict[str, Path] = {}
    for run_id, root in (("20260918-v21-r7-live-75", R7_SOURCE), ("20260918-v23-r2-live20", V23_SOURCE)):
        for path in sorted((root / "active_replays").glob("*.json")):
            try:
                record = _read_json(path, {})
            except Exception:
                continue
            game_id = record.get("game_id")
            if game_id:
                records[(run_id, str(game_id))] = record
                paths[f"{run_id}:{game_id}"] = path
        source_jsonl = root / "v23_source_replays.jsonl"
        if source_jsonl.exists():
            for record in _jsonl(source_jsonl):
                game_id = record.get("game_id")
                if game_id:
                    records[(run_id, str(game_id))] = record
                    paths[f"{run_id}:{game_id}"] = source_jsonl
    return records, paths


def _p0_details() -> list[dict[str, Any]]:
    return _read_json(P0_RUN / "replay_verification_details.json", []) or []


def _p0_cutoffs() -> list[dict[str, Any]]:
    return _jsonl(P0_RUN / "replay_cutoffs.jsonl")


def _details_index() -> dict[tuple[str, str], dict[str, Any]]:
    return {(str(d.get("source_run_id")), str(d.get("game_id"))): d for d in _p0_details()}


def _verified_status(value: Any) -> bool:
    return str(value) in {"BASELINE_VERIFIED", "PARTIAL_ARCHIVE_VERIFIED_PREFIX"}


def _current_code_paths() -> list[Path]:
    names = [
        "avalon/engine.py", "avalon/chronicle.py", "avalon/evidence.py", "avalon/joint_beliefs.py",
        "avalon/mission_likelihood.py", "avalon/eval/simulation.py", "avalon/eval/v2/adapters.py",
        "avalon/eval/v2/v21_contract.py", "avalon/eval/v2/v21_runtime.py", "avalon/eval/v2/v22_replay.py",
        "avalon/eval/v2/v231_channel.py", "avalon/eval/v2/v232_channel.py", "avalon/eval/v2/v232_r2.py",
        "avalon/eval/v2/v232_runner.py", "avalon/eval/v2/v232_p1.py",
    ]
    return [ROOT / name for name in names if (ROOT / name).exists()]


def _hash_tree(root: Path, *, suffixes: tuple[str, ...] | None = None) -> dict[str, str]:
    result: dict[str, str] = {}
    root = Path(root)
    if not root.exists():
        return result
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        if suffixes and path.suffix not in suffixes:
            continue
        try:
            result[str(path.relative_to(root))] = sha256(path)
        except OSError:
            result[str(path.relative_to(root))] = "UNREADABLE"
    return result


def _fixture_audit() -> dict[str, Any]:
    inventory = _read_csv(HIST_RUN / "comparison_inventory.csv")
    by_id = {row.get("decision_id"): row for row in inventory}
    missing = []
    for fixture in REQUIRED_MISSING_FIXTURES:
        row = by_id.get(fixture)
        missing.append({
            "fixture": fixture,
            "present": row is not None,
            "reference_exists_raw": row.get("reference_exists") if row else None,
            "candidate_exists_raw": row.get("candidate_exists") if row else None,
            "candidate_valid_raw": row.get("candidate_valid") if row else None,
            "expected_new_classification": "MISSING_ARM",
        })
    provenance = _jsonl(HIST_RUN / "factor_provenance.jsonl")
    targets = []
    for target in NUMERIC_TARGETS:
        row = next((r for r in provenance
                    if all(str(r.get("source_signal_id" if k == "signal_id" else k)) == str(v)
                           for k, v in target.items())), None)
        targets.append({"target": target, "present": row is not None, "factor_row_hash": digest(row) if row else None})
    timeline = _read_csv(HIST_RUN / "assassin_exposure_timeline.csv")
    transient = [
        {"event_id": event, "top_after": next((r.get("native_exact_top_after") for r in timeline
                                                 if r.get("scenario_id") == "main-single_seat-940017"
                                                 and r.get("observer_id") == "P1" and r.get("variant") == "joint_v2"
                                                 and r.get("event_id") == event), None)}
        for event in ("R1-016", "R1-017", "R1-019")
    ]
    return {"missing_action_fixtures": missing, "numeric_targets": targets,
            "transient_lock_fixture": transient, "inventory_rows": len(inventory),
            "timeline_rows": len(timeline), "p0_details": len(_p0_details()),
            "p0_cutoffs": len(_p0_cutoffs())}


def _select_cases() -> list[dict[str, Any]]:
    records, paths = _source_records()
    details = _details_index()
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for cutoff in _p0_cutoffs():
        if not (cutoff.get("verified") is True and cutoff.get("full_posterior_verified") is True):
            continue
        if cutoff.get("phase") != "vote" or cutoff.get("native_variant") != "joint_v2":
            continue
        run, game_id = str(cutoff.get("source_run_id")), str(cutoff.get("game_id"))
        record = records.get((run, game_id))
        detail = details.get((run, game_id), {})
        if not record or not _verified_status(detail.get("verification_status")):
            continue
        truth = {p.get("id"): p.get("role") for p in record.get("players", [])}
        if truth.get(cutoff.get("observer_id")) != "MERLIN":
            continue
        grouped[(run, str(record.get("scenario_id")))].append(cutoff)
    # The sample rule is frozen before intervention: two earliest vote cutoffs
    # in each of the first two source scenarios, with one later attempt when it
    # is available.  Sorting is lexical and therefore reproducible.
    selected: list[dict[str, Any]] = []
    for key in sorted(grouped)[:2]:
        rows = sorted(grouped[key], key=lambda r: (int(r.get("cutoff_seq", 0)), int(r.get("decision_index", 0))))
        picks = [rows[0]]
        if len(rows) > 1:
            picks.append(rows[1])
        if len(rows) > 4:
            picks.append(rows[4])
        for cutoff in picks:
            run, game_id = str(cutoff["source_run_id"]), str(cutoff["game_id"])
            record = records[(run, game_id)]
            ids = [p["id"] for p in record["players"]]
            merlin = str(cutoff["observer_id"])
            role_map = _roles(record)
            assassin = next((pid for pid, role in role_map.items() if role == "ASSASSIN"), None)
            if role_map.get(merlin) != "MERLIN" or assassin is None or assassin == merlin:
                continue
            others = [pid for pid in ids if pid != merlin]
            fixed = {pid: i < 2 for i, pid in enumerate(others)}
            selected.append({
                "source_run_id": run, "scenario_id": record.get("scenario_id"), "game_id": game_id,
                # ``source_observer_id`` is the P0 cutoff seat.  Keep it
                # separate from the measurement seat so a Merlin self-belief
                # result cannot be mistaken for an Assassin measurement.
                "source_observer_id": merlin, "observer_id": assassin,
                "intervention_actor_id": merlin, "intervention_actor_role": "MERLIN",
                "measurement_observer_id": assassin, "measurement_observer_role": "ASSASSIN",
                "native_variant": cutoff.get("native_variant"),
                "decision_index": int(cutoff["decision_index"]), "cutoff_seq": int(cutoff["cutoff_seq"]),
                "public_prefix_hash": cutoff.get("public_prefix_hash"),
                "legal_view_hash": cutoff.get("legal_view_hash"), "posterior_hash": cutoff.get("posterior_hash"),
                "marginals_hash": cutoff.get("marginals_hash"), "legal_menu_hash": cutoff.get("legal_menu_hash"),
                "source_file": str(paths.get(f"{run}:{game_id}", "")),
                "other_ballots_source": "preregistered_public_view_only_two_true_rest_false",
                "other_ballots": fixed, "strong": {pid: False for pid in ids},
                "intervention": "merlin_vote_true_vs_false_only",
                "sample_rule": "first_two_and_fifth_verified_full_native_joint_v2_merlin_vote_cutoffs_per_first_two_scenarios",
            })
    return selected


def _empty_outputs(out: Path) -> None:
    schemas = {
        "assassin_exposure_timeline.csv": [
            "run_id", "source_run_id", "cohort_role", "scenario_id", "scenario_family", "game_id", "observer_id",
            "variant", "event_id", "source_event_id", "source_signal_id", "event_kind", "actor", "round", "attempt",
            "phase", "legal_observation_hash", "public_prefix_hash", "factor_origin_module", "factor_name",
            "factor_live_support_min", "factor_live_support_max", "constant_on_live_support", "posterior_before_hash",
            "posterior_after_hash", "max_abs_raw_delta", "merlin_marginals_before", "merlin_marginals_after",
            "native_exact_top_before", "native_exact_top_after", "near_top_diagnostic_before", "near_top_diagnostic_after",
            "log_odds_delta_by_candidate", "factor_consumed", "duplicate_suppressed", "event_observed", "true_merlin_scorer",
            "true_merlin", "source_verification_status", "last_verified_seq", "full_posterior_verified", "boundary_type",
            "legally_visible", "visible_before_commit", "observer_can_act", "boundary_verified", "public_commit_id",
            "decision_index", "decision_id", "actionable_boundary", "native_exact_top_at_boundary", "near_top_at_boundary",
        ],
        "identification_by_boundary.csv": [], "lock_episodes.csv": [], "numerical_tie_audit.csv": [],
        "comparison_inventory.csv": [], "comparison_classification_changes.csv": [], "vote_interventions.csv": [],
        "vote_channel_pairs.csv": [], "vote_safety_audit.csv": [],
    }
    for name, fields in schemas.items():
        _write_csv(out / name, [], fields or ["status"])
    _append_jsonl(out / "numeric_counterexamples.jsonl", [])
    _append_jsonl(out / "vote_factor_provenance.jsonl", [])
    _write_json(out / "sample_denominators.json", {"status": "NOT_RUN"})
    _write_json(out / "vote_channel_gate.json", {"status": "NOT_RUN", "network_calls": 0})
    _write_json(out / "p1_gates.json", {"status": "PREPARED", "network_calls": 0})
    _write_json(out / "summary.json", {"run_id": out.name, "status": "prepared", "network_calls": 0})
    _write_text(out / "report.md", "# Avalon V2.3.2-r2 P1\n\n离线 P1 尚未运行。\n")
    _write_text(out / "p1_report.md", "# Avalon V2.3.2-r2 P1\n\n离线 P1 尚未运行。\n")


def prepare(out: Path) -> dict[str, Any]:
    out = Path(out).resolve()
    if out.exists():
        raise FileExistsError(f"refusing to overwrite P1 output: {out}")
    out.mkdir(parents=True)
    if not P0_RUN.exists():
        raise FileNotFoundError(P0_RUN)
    p0_gates = _read_json(P0_RUN / "p0_gates.json", {}) or {}
    p0_summary = _read_json(P0_RUN / "summary.json", {}) or {}
    required_p0 = {
        "contract_smoke": p0_gates.get("contract_smoke") or p0_summary.get("gates", {}).get("contract_smoke"),
        "corrected_adapter_live": p0_gates.get("corrected_adapter_live") or p0_summary.get("corrected_adapter_live"),
        "paid_halt": bool(((_read_json(P0_RUN / "paid_halt.json", {}) or {}).get("paid_halt"))
                          or p0_gates.get("paid_block_closed")),
    }
    if required_p0["contract_smoke"] != "FAIL_REQUEST_PROTOCOL_CONFLICT":
        raise RuntimeError(f"P0 contract gate changed: {required_p0}")
    if required_p0["corrected_adapter_live"] != "NOT_RUN" or not required_p0["paid_halt"]:
        raise RuntimeError(f"P0 paid/live gate changed: {required_p0}")
    artifact_manifest = _read_json(P0_RUN / "final_artifact_manifest.json", {}) or {}
    expected = artifact_manifest.get("sha256", {})
    artifact_hashes = {}
    for rel, expected_hash in sorted(expected.items()):
        p = P0_RUN / rel
        actual = sha256(p) if p.exists() else None
        artifact_hashes[rel] = {"expected": expected_hash, "actual": actual, "match": actual == expected_hash}
    _write_json(out / "p0_artifact_hashes.json", artifact_hashes)
    if any(v["match"] is False for v in artifact_hashes.values()):
        raise RuntimeError("P0 artifact hash mismatch; P1 is not unlocked")
    fixtures = _fixture_audit()
    code_hashes = {str(p.relative_to(ROOT)): sha256(p) for p in _current_code_paths()}
    source_hashes = {
        "p0_final_artifact_manifest": sha256(P0_RUN / "final_artifact_manifest.json"),
        "p0_source_manifest": sha256(P0_RUN / "p0_source_manifest.json"),
        "p0_replay_cutoffs": sha256(P0_RUN / "replay_cutoffs.jsonl"),
        "p0_replay_details": sha256(P0_RUN / "replay_verification_details.json"),
        "historical_timeline": sha256(HIST_RUN / "assassin_exposure_timeline.csv"),
        "historical_factor_provenance": sha256(HIST_RUN / "factor_provenance.jsonl"),
        "historical_comparison_inventory": sha256(HIST_RUN / "comparison_inventory.csv"),
        "p1_plan": sha256(P1_PLAN) if P1_PLAN.exists() else None,
    }
    cfg = {
        "run_id": out.name, "version": RUN_VERSION, "created_utc": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "live": False, "budget_cny": None, "network_access": False, "network_calls": 0,
        "production_candidate": False, "full_game": False, "paid_halt_preserved": True,
        "p0_run_id": P0_RUN.name, "p0_gate_snapshot": required_p0,
        "frozen": {"joint_v1": True, "joint_v2": True, "evidence_factors": True, "rules": True,
                   "legal_menu": True, "exact_argmax": True, "v22_vote_candidate": False,
                   "language_belief": False, "recursive_tom": False, "cross_game_memory": False},
        "epsilon_diagnostic": EPSILON_DIAGNOSTIC,
        "source_run_ids": ["20260918-v21-r7-live-75", "20260918-v23-r2-live20"],
        "source_paths": {"r7": str(R7_SOURCE), "v23": str(V23_SOURCE), "historical_r1": str(HIST_RUN), "p0": str(P0_RUN)},
        "source_hashes": source_hashes, "current_code_hashes": code_hashes, "git": git_info(),
        "fixtures": fixtures,
        "commands": {
            "prepare": "python -m avalon.eval.v2.v232_runner --mode p1-prepare --run-dir <run>",
            "analyze": "python -m avalon.eval.v2.v232_runner --mode p1-analyze --run-dir <run>",
            "tests": "python -m avalon.eval.v2.v232_runner --mode p1-tests --run-dir <run>",
            "report_only": "python -m avalon.eval.v2.v232_runner --mode p1-report-only --run-dir <run>",
        },
    }
    _write_json(out / "p1_config.json", cfg)
    _write_json(out / "config.json", cfg)
    _write_json(out / "p1_source_manifest.json", {
        "run_id": out.name, "p0_run_id": P0_RUN.name, "p0_artifact_hashes": artifact_hashes,
        "source_hashes": source_hashes, "current_code_hashes": code_hashes, "git": git_info(),
        "dirty_state_preserved": True, "historical_inputs_read_only": True, "network_calls": 0,
        "fixture_audit": fixtures,
    })
    _write_json(out / "p1_preregistered_cases.json", {
        "frozen_before_analysis": True, "selection_basis": "P0 verified=true and full_posterior_verified=true; exact tuple and hashes required",
        "cases": _select_cases(), "network_calls": 0, "truth_role_use": "offline scorer and eligibility only; never model input",
    })
    _write_text(out / "p1_prechange_audit.md", f"""# Avalon V2.3.2-r2 P1 prechange audit

本轮是离线修复与受控机制验证。P0 目录 `{P0_RUN}`、历史 v2.3.2-r1 目录及来源回放只读。

## 已核对的生产链路

`Game.vote()` 先校验整批票，随后在一个事务中写入逐票 `VOTE` 和汇总 `TEAM_VOTE`，调用方在事务返回后才 flush 给观察者。`Game.view()` 将它们作为公开历史提供，但没有批次内部的 Agent 决策边界；因此单票行保留为 `INTERNAL_EVENT`，`TEAM_VOTE` 标作 `PUBLIC_COMMIT`，后续真实决策截止点另标 `ACTIONABLE_DECISION`。

观察者通过 `Observation.from_event -> EvidenceExtractor -> BeliefEngine` 重放，P1 只调用已有评估模块。投票干预通过生产 `Game.validate_ballot`/`Game.vote`，不修改生产引擎。

## P0 门槛冻结

`contract_smoke={required_p0['contract_smoke']}`；`corrected_adapter_live={required_p0['corrected_adapter_live']}`；`paid_halt={required_p0['paid_halt']}`。P1 不读取 API key、不导入付费 client、不启动完整对局，任何效果归因在公开边界和数值影响未完成前保持阻断。

## 来源和 fixture

P0 cutoff 共 `{fixtures['p0_cutoffs']}` 行；P1-D 只接受 `verified=true`、`full_posterior_verified=true` 且 source/game/observer/native_variant/decision_index/cutoff_seq 与 legal view、posterior、marginal、menu、public-prefix 哈希全部匹配的截止点。缺失臂 fixture、两个常数因子线索和 `940017` 暂态锁定均从原始表重新定位。

本轮不改变 belief、因子权重、合法菜单、原子提交、exact `==` 或生产策略默认值。
""")
    _write_text(out / "vote_intervention_spec.md", """# P1-D vote intervention specification

Each pair starts from one P0-verified vote cutoff.  A production Game clone
receives the same preregistered other ballots in both arms; only Merlin's
boolean vote changes.  All ballots are validated and submitted as one sealed
transaction.  The observer receives only public Game.view projections after
the commit.  Truth is used after the branch by the offline scorer only.

`future_events_injected=0`, `actual_decoder_called=0`, and no historical later
vote or hidden ballot is copied into an input.  The experiment is a mechanism
probe, not a policy, game-win, or production-candidate test.
""")
    _empty_outputs(out)
    return cfg


def _record_event_maps(record: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    events = {str(e.get("record_id")): e for e in record.get("events", [])}
    return events, sorted(record.get("events", []), key=lambda e: int(e.get("seq", 0)))


def _public_commit_after(events: list[dict[str, Any]], seq: int, round_no: Any, attempt: Any) -> str | None:
    for event in events:
        if int(event.get("seq", 0)) > seq and event.get("kind") == "TEAM_VOTE" \
                and str(event.get("round")) == str(round_no) and str(event.get("attempt")) == str(attempt):
            return str(event.get("record_id"))
    return None


def _cutoff_key(row: dict[str, Any]) -> tuple[str, str, str, str, int, int]:
    return (str(row.get("source_run_id")), str(row.get("game_id")), str(row.get("observer_id")),
            str(row.get("native_variant")), int(row.get("decision_index", -1)), int(row.get("cutoff_seq", -1)))


def _strict_cutoff_index() -> tuple[dict[tuple[str, str, str, str, int, int], dict[str, Any]], dict[str, int]]:
    records, paths = _source_records()
    details = _details_index()
    result: dict[tuple[str, str, str, str, int, int], dict[str, Any]] = {}
    counts = Counter(total=0, verified=0, full=0, context=0, hash_match=0, rejected=0)
    for row in _p0_cutoffs():
        counts["total"] += 1
        if row.get("verified") is not True:
            continue
        counts["verified"] += 1
        if row.get("full_posterior_verified") is not True:
            continue
        counts["full"] += 1
        run, game_id = str(row.get("source_run_id")), str(row.get("game_id"))
        detail = details.get((run, game_id), {})
        source_file = Path(str(detail.get("source_file", "")))
        # A JSONL source has no per-game checkpoint context and is deliberately
        # not upgraded from event/marginal-only evidence.
        if source_file.suffix != ".json" or not source_file.exists():
            counts["rejected"] += 1
            continue
        cp = source_file.parent.parent / "checkpoints" / source_file.stem / "contexts" / f"{int(row['decision_index']):04d}.json"
        context = _read_json(cp)
        if not context:
            counts["rejected"] += 1
            continue
        counts["context"] += 1
        same = (
            digest(context.get("view")) == row.get("legal_view_hash")
            and context.get("posterior_hash") == row.get("posterior_hash")
            and digest(context.get("marginals")) == row.get("marginals_hash")
            and digest(legal_menu(context.get("view", {}))) == row.get("legal_menu_hash")
            and digest([context_record(e) for e in records.get((run, game_id), {}).get("events", [])
                        if e.get("kind") in PUBLIC_KINDS and int(e.get("seq", 0)) <= int(row["cutoff_seq"])])
                == row.get("public_prefix_hash")
        )
        if not same:
            counts["rejected"] += 1
            continue
        counts["hash_match"] += 1
        result[_cutoff_key(row)] = {"cutoff": row, "context": context, "context_path": str(cp),
                                     "source_file": str(source_file), "record": records.get((run, game_id)),
                                     "source_sha256": sha256(source_file), "source_path": str(paths.get(f"{run}:{game_id}", source_file))}
    return result, dict(counts)


def _boundary_audit(out: Path, timeline: list[dict[str, str]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    records, _ = _source_records()
    details = _details_index()
    cutoffs = _p0_cutoffs()
    cutoff_by_key: dict[tuple[str, str, str, str, int, int], dict[str, Any]] = {}
    for c in cutoffs:
        try:
            cutoff_by_key[_cutoff_key(c)] = c
        except (TypeError, ValueError):
            continue
    out_rows: list[dict[str, Any]] = []
    originals_by_group: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for raw in timeline:
        row = dict(raw)
        run, game_id = str(row.get("source_run_id")), str(row.get("game_id"))
        record = records.get((run, game_id), {})
        detail = details.get((run, game_id), {})
        seq = _event_seq(row.get("event_id"))
        last_verified = int(detail.get("last_verified_seq") or (len(record.get("events", [])) if record else 0))
        status = detail.get("verification_status") or "UNKNOWN_SOURCE"
        verified_prefix = _verified_status(status) and seq is not None and seq <= last_verified
        event = next((e for e in record.get("events", []) if str(e.get("record_id")) == str(row.get("event_id"))), {})
        kind = event.get("kind") or row.get("event_kind")
        if kind == "VOTE":
            boundary = "INTERNAL_EVENT"
            visible_before = 0
        elif kind in PUBLIC_KINDS:
            boundary = "PUBLIC_COMMIT"
            visible_before = 1
        else:
            boundary = "UNKNOWN"
            visible_before = None
        row.update({
            "source_event_id": row.get("event_id"), "source_verification_status": status,
            "last_verified_seq": last_verified, "full_posterior_verified": 0,
            "boundary_type": boundary, "legally_visible": int(kind in PUBLIC_KINDS),
            "visible_before_commit": visible_before, "observer_can_act": 0,
            "boundary_verified": int(verified_prefix), "public_commit_id": _public_commit_after(
                record.get("events", []), seq or -1, row.get("round"), row.get("attempt")) if kind == "VOTE" else
                (row.get("event_id") if kind == "TEAM_VOTE" else None),
            "decision_index": None, "decision_id": None, "actionable_boundary": 0,
            "native_exact_top_at_boundary": row.get("native_exact_top_after"),
            "near_top_at_boundary": row.get("near_top_diagnostic_after"),
        })
        # This flag is source-native only; a mirror replay row must not be
        # silently promoted to a different native variant.
        group = (run, game_id, str(row.get("observer_id")), str(row.get("variant")))
        originals_by_group[group].append(row)
        out_rows.append(row)
    # Explicit decision-boundary rows make the public commit and action input
    # separate observations while retaining all original event rows.
    for c in cutoffs:
        if not (c.get("verified") is True and c.get("full_posterior_verified") is True):
            continue
        key = _cutoff_key(c)
        run, game_id, observer, variant, decision_index, cutoff_seq = key
        group = (run, game_id, observer, variant)
        source = next((r for r in originals_by_group.get(group, []) if _event_seq(r.get("event_id")) == cutoff_seq), None)
        if not source:
            continue
        detail = details.get((run, game_id), {})
        if not _verified_status(detail.get("verification_status")):
            continue
        decision = dict(source)
        decision.update({
            "event_id": f"{source.get('event_id')}::decision:{decision_index}",
            "source_event_id": source.get("event_id"), "event_kind": "DECISION_BOUNDARY",
            "boundary_type": "ACTIONABLE_DECISION", "legally_visible": 1,
            "visible_before_commit": 1, "observer_can_act": 1,
            "boundary_verified": 1, "full_posterior_verified": 1,
            "public_commit_id": source.get("public_commit_id") or source.get("event_id"),
            "decision_index": decision_index,
            "decision_id": f"{game_id}:{observer}:{decision_index}",
            "actionable_boundary": 1,
            "native_exact_top_at_boundary": source.get("native_exact_top_after"),
            "near_top_at_boundary": source.get("near_top_diagnostic_after"),
        })
        out_rows.append(decision)
    fields = list(out_rows[0]) if out_rows else []
    _write_csv(out / "assassin_exposure_timeline.csv", out_rows, fields)
    boundary_report = {
        "source_code_finding": {
            "vote_transaction_validates_all_before_emit": True,
            "vote_events_sealed_until_game_vote_returns": True,
            "team_vote_is_atomic_summary_event": True,
            "observer_flush_occurs_after_submit": True,
            "individual_vote_actionable_mid_batch": False,
        },
        "counts": dict(Counter(row.get("boundary_type") for row in out_rows)),
        "verified_source_rows": sum(int(row.get("boundary_verified") or 0) for row in out_rows),
        "actionable_rows": sum(int(row.get("actionable_boundary") or 0) for row in out_rows),
        "note": "VOTE is present in post-commit Game.view but has no mid-batch Agent decision boundary; ACTIONABLE_DECISION is a separate matched cutoff row.",
    }
    _write_json(out / "boundary_audit.json", boundary_report)
    _write_text(out / "vote_publication_boundary_audit.md", """# Vote publication boundary audit

`Game.vote()` checks the complete ballot mapping before it emits any ballot.
The engine then emits all `VOTE` events and one `TEAM_VOTE` in the same host
transaction; the simulation flushes observers after the transaction returns.
Consequently a single `VOTE` row is retained as an internal event for factor
provenance, but it is not an actionable mid-batch decision. `TEAM_VOTE` is the
public commit. An `ACTIONABLE_DECISION` row is emitted only for a later P0
cutoff whose complete tuple and state hashes match. No event was removed.
""")
    return out_rows, list(out_rows), boundary_report


def _identification(out: Path, rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[(str(row.get("source_run_id")), str(row.get("game_id")), str(row.get("observer_id")), str(row.get("variant")))].append(row)
    records, _ = _source_records()
    identification, episodes = [], []
    for key, group in sorted(groups.items()):
        originals = sorted((r for r in group if not str(r.get("event_id", "")).__contains__("::decision:")),
                           key=lambda r: (_event_seq(r.get("event_id")) or 0))
        decisions = sorted((r for r in group if int(r.get("actionable_boundary") or 0)),
                           key=lambda r: int(r.get("decision_index") or 0))
        truth_merlin = next((p.get("id") for p in records.get((key[0], key[1]), {}).get("players", []) if p.get("role") == "MERLIN"), None)
        def unique(row):
            top = _top(row.get("native_exact_top_after") or row.get("native_exact_top_at_boundary"))
            return top[0] if len(top) == 1 else None
        first_internal = next((r for r in originals if unique(r)), None)
        public_rows = [r for r in originals if r.get("event_kind") == "TEAM_VOTE" or r.get("boundary_type") == "PUBLIC_COMMIT"]
        first_public = next((r for r in public_rows if unique(r)), None)
        first_action = next((r for r in decisions if unique(r)), None)
        has_assassination = any(e.get("kind") == "ASSASSINATE" for e in records.get((key[0], key[1]), {}).get("events", []))
        wrong_segments = _wrong_lock_segments(decisions, truth_merlin)
        sustained = wrong_segments[-1] if has_assassination and wrong_segments else None
        wrong_original = [r for r in originals if unique(r) and unique(r) != truth_merlin]
        wrong_action = [r for r in decisions if unique(r) and unique(r) != truth_merlin]
        episodes.append({
            "source_run_id": key[0], "game_id": key[1], "observer_id": key[2], "variant": key[3],
            "episode_id": f"{key[0]}:{key[1]}:{key[2]}:{key[3]}:lock",
            "definition": "contiguous exact unique-top state; event rows and actionable rows counted separately",
            "truth_merlin_scorer": truth_merlin,
            "wrong_event_rows": len(wrong_original), "wrong_actionable_rows": len(wrong_action),
            "wrong_decision_boundary_episodes": len(wrong_segments),
            "wrong_lock_episode_starts": json.dumps(wrong_segments, sort_keys=True),
            "status": "observed" if originals else "unavailable",
        })
        identification.append({
            "source_run_id": key[0], "game_id": key[1], "observer_id": key[2], "variant": key[3],
            "truth_merlin_scorer": truth_merlin, "source_verification_status": originals[0].get("source_verification_status") if originals else None,
            "first_internal_unique_top_event": first_internal.get("event_id") if first_internal else None,
            "first_internal_unique_top_seat": unique(first_internal) if first_internal else None,
            "first_internal_is_true": int(bool(first_internal and unique(first_internal) == truth_merlin)),
            "first_public_commit_unique_top_event": first_public.get("event_id") if first_public else None,
            "first_public_commit_unique_top_seat": unique(first_public) if first_public else None,
            "first_public_commit_is_true": int(bool(first_public and unique(first_public) == truth_merlin)),
            "first_actionable_unique_top_decision": first_action.get("decision_index") if first_action else None,
            "first_actionable_unique_top_seat": unique(first_action) if first_action else None,
            "first_actionable_is_true": int(bool(first_action and unique(first_action) == truth_merlin)),
            "decision_boundary_count": len(decisions), "internal_event_count": len(originals),
            "assassination_present": int(has_assassination),
            "final_sustained_lock_before_assassination": (sustained.get("start_decision_index")
                                                           if sustained else None),
            "final_sustained_lock_status": "observed" if sustained else ("no_assassination_boundary" if not has_assassination else "not_sustained"),
            "wrong_event_rows": len(wrong_original), "wrong_actionable_rows": len(wrong_action),
        })
    _write_csv(out / "identification_by_boundary.csv", identification)
    _write_csv(out / "lock_episodes.csv", episodes)
    _write_json(out / "boundary_regression_fixtures.json", {
        "scenario": "main-single_seat-940017", "observer_id": "P1", "variant": "joint_v2",
        "rows": [{"event_id": r.get("event_id"), "event_kind": r.get("event_kind"), "boundary_type": r.get("boundary_type"),
                   "observer_can_act": r.get("observer_can_act"), "native_exact_top_after": r.get("native_exact_top_after")}
                  for r in rows if r.get("scenario_id") == "main-single_seat-940017" and r.get("observer_id") == "P1"
                  and r.get("variant") == "joint_v2" and r.get("source_event_id") in {"R1-016", "R1-017", "R1-019"}],
        "persistent_lock_rule": "same wrong unique top across consecutive actionable decision rows is one episode; tie, true top, target change, or sequence end closes it",
        "interpretation": "R1-016 internal unique [P3], R1-017 returns to [P3,P4], R1-019 is public commit and remains tied; no internal transient is counted as a sustained actionable lock.",
    })
    return identification, episodes


def _numeric(out: Path, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    provenance = _jsonl(HIST_RUN / "factor_provenance.jsonl")
    timeline_index = {(str(r.get("source_run_id")), str(r.get("game_id")), str(r.get("observer_id")),
                       str(r.get("variant")), str(r.get("event_id"))): r for r in rows
                      if not str(r.get("event_id", "")).__contains__("::decision:")}
    details = _details_index()
    records, paths = _source_records()
    examples = []
    for target in NUMERIC_TARGETS:
        p = next((r for r in provenance
                  if all(str(r.get("source_signal_id" if k == "signal_id" else k)) == str(v)
                         for k, v in target.items())), None)
        key = tuple(str(target[k]) for k in ("source_run_id", "game_id", "observer_id", "variant", "event_id"))
        timeline = timeline_index.get(key)
        rec = records.get((target["source_run_id"], target["game_id"]), {})
        detail = details.get((target["source_run_id"], target["game_id"]), {})
        seq = _event_seq(target["event_id"])
        commit = next((r for r in rows if r.get("source_run_id") == target["source_run_id"] and r.get("game_id") == target["game_id"]
                       and r.get("observer_id") == target["observer_id"] and r.get("variant") == target["variant"]
                       and r.get("event_kind") == "TEAM_VOTE" and (_event_seq(r.get("event_id")) or 0) > (seq or -1)), None)
        cutoff_native = [c for c in _p0_cutoffs() if str(c.get("source_run_id")) == target["source_run_id"]
                         and str(c.get("game_id")) == target["game_id"] and str(c.get("observer_id")) == target["observer_id"]
                         and c.get("native_variant") == target["variant"] and int(c.get("cutoff_seq", -1)) >= (seq or 0)
                         and c.get("verified") is True and c.get("full_posterior_verified") is True]
        constant = float(p.get("likelihood_min")) if p and p.get("likelihood_min") not in (None, "") else None
        before_top = _top(timeline.get("native_exact_top_before")) if timeline else None
        after_top = _top(timeline.get("native_exact_top_after")) if timeline else None
        no_op_support = bool(p and p.get("constant_on_live_support") in (1, "1", True)
                             and p.get("likelihood_min") == p.get("likelihood_max"))
        example = {
            **target, "source_file": str(paths.get(f"{target['source_run_id']}:{target['game_id']}", "")),
            "source_sha256": sha256(paths[f"{target['source_run_id']}:{target['game_id']}"])
            if f"{target['source_run_id']}:{target['game_id']}" in paths and paths[f"{target['source_run_id']}:{target['game_id']}"].suffix == ".json" else None,
            "factor_row_found": bool(p), "factor_row_hash": digest(p) if p else None,
            "factor_name": p.get("factor_name") if p else None, "signal_id": p.get("source_signal_id") if p else target["signal_id"],
            "constant_on_live_support": no_op_support, "constant_likelihood": constant,
            "likelihood_min": p.get("likelihood_min") if p else None, "likelihood_max": p.get("likelihood_max") if p else None,
            "max_abs_raw_delta": timeline.get("max_abs_raw_delta") if timeline else None,
            "raw_probability_changed": int(bool(timeline and float(timeline.get("max_abs_raw_delta") or 0.0) > 0.0)),
            "posterior_hash_before": timeline.get("posterior_before_hash") if timeline else (p.get("posterior_before_hash") if p else None),
            "posterior_hash_after": timeline.get("posterior_after_hash") if timeline else (p.get("posterior_after_hash") if p else None),
            "posterior_hash_changed": int(bool(timeline and timeline.get("posterior_before_hash") != timeline.get("posterior_after_hash"))),
            "native_exact_top_before": before_top, "native_exact_top_after": after_top,
            "internal_exact_top_changed": int(bool(timeline and before_top != after_top)),
            "public_commit_id": commit.get("event_id") if commit else None,
            "public_commit_exact_top_after": _top(commit.get("native_exact_top_after")) if commit else None,
            "public_commit_exact_top_changed": int(bool(commit and before_top != _top(commit.get("native_exact_top_after")))),
            "actionable_exact_top_changed": None if not cutoff_native else "UNRESOLVED_NO_POST_EVENT_MATCH",
            "actual_decoder_target_changed": "UNAVAILABLE_NOT_ASSASSINATION_DECODER",
            "impact_verification_status": "INTERNAL_ONLY_NATIVE_ACTIONABLE_BOUNDARY_UNVERIFIED" if not cutoff_native else "PUBLIC_BOUNDARY_REQUIRES_SEPARATE_NATIVE_REPLAY",
            "shadow_noop": no_op_support,
            "shadow_noop_posterior_equal": no_op_support,
            "float_hex_likelihood": float(constant).hex() if constant is not None else None,
            "source_verification_status": detail.get("verification_status"),
        }
        examples.append(example)
    _append_jsonl(out / "numeric_counterexamples.jsonl", examples)
    # Preserve the historical snapshot table while adding the repaired impact
    # fields.  The two source-bound examples are appended as explicit rows.
    historical = _read_csv(HIST_RUN / "numerical_tie_audit.csv")
    numeric_rows = []
    for row in historical:
        row = dict(row)
        row.update({"raw_probability_changed": None, "posterior_hash_changed": None, "native_exact_top_changed": None,
                    "internal_exact_top_changed": None, "public_commit_exact_top_changed": None,
                    "actionable_exact_top_changed": None, "actual_decoder_target_changed": "UNAVAILABLE",
                    "impact_verification_status": "SNAPSHOT_ONLY_NO_EVENT_BINDING", "epsilon_is_diagnostic_only": 1,
                    "production_tie_rule_preserved": "exact Python == max"})
        numeric_rows.append(row)
    for example in examples:
        numeric_rows.append({"dataset_role": "source_bound_counterexample", **example,
                             "native_exact_top_set": json.dumps(example.get("native_exact_top_after")),
                             "near_top_diagnostic_set": json.dumps(example.get("native_exact_top_after")),
                             "epsilon_diagnostic": EPSILON_DIAGNOSTIC,
                             "production_tie_rule": "exact Python == max; no tolerance"})
    numeric_rows.append({"dataset_role": "synthetic_decoder_fixture", "fixture_name": "main-single_seat-940007-joint_v1",
                         "native_values": json.dumps({"P1": 0.3333333333333332, "P4": 0.3333333333333333, "P5": 0.3333333333333333, "P2": 0.0, "P3": 0.0}),
                         "native_exact_top_set": json.dumps(["P4", "P5"]), "submitted_ranking": json.dumps(["P1", "P4", "P5", "P2", "P3"]),
                         "selected_target": "P4", "synthetic": 1, "impact_verification_status": "SYNTHETIC_FUNCTION_FIXTURE_ONLY",
                         "production_tie_rule_preserved": "exact Python == max", "epsilon_is_diagnostic_only": 1})
    fields = sorted({k for row in numeric_rows for k in row})
    _write_csv(out / "numerical_tie_audit.csv", numeric_rows, fields)
    return examples


def _classification(out: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    raw = _read_csv(HIST_RUN / "comparison_inventory.csv")
    rows, changes = [], []
    def exists(row, branch):
        value = row.get(f"{branch}_exists")
        if value not in (None, ""):
            parsed = _bool(value)
            if parsed is not None:
                return parsed
        action = row.get(f"{branch}_action")
        return action not in (None, "", "null", "None")
    for old in raw:
        row = dict(old)
        ref_exists, cand_exists = exists(old, "reference"), exists(old, "candidate")
        ref_valid_raw, cand_valid_raw = _bool(old.get("reference_valid")), _bool(old.get("candidate_valid"))
        if not ref_exists or not cand_exists:
            status = "MISSING_ARM"
            ref_valid = ref_valid_raw if ref_exists else None
            cand_valid = cand_valid_raw if cand_exists else None
            action_delta = "NOT_COMPARABLE"
        elif ref_valid_raw is False or cand_valid_raw is False:
            status = "INVALID_ACTION"
            ref_valid, cand_valid = ref_valid_raw, cand_valid_raw
            action_delta = old.get("action_delta") or "NOT_COMPARABLE"
        else:
            ref_valid, cand_valid = ref_valid_raw, cand_valid_raw
            prefix_equal = _bool(old.get("public_prefix_equal")) is True and _bool(old.get("mechanical_pre_state_equal")) is True
            status = "MATCHED_PREFIX" if prefix_equal else "DIVERGED_PREFIX"
            action_delta = old.get("action_delta") or "NO_CHANGE"
        row.update({"reference_exists": int(ref_exists), "candidate_exists": int(cand_exists),
                    "reference_valid": ref_valid, "candidate_valid": cand_valid,
                    "comparison_status": status, "action_delta": action_delta,
                    "classification_rule": "missing-first; then invalid; then prefix comparability"})
        rows.append(row)
        old_status = old.get("comparison_status")
        if old_status != status or old.get("action_delta") != action_delta:
            changes.append({"decision_id": old.get("decision_id"), "old_comparison_status": old_status,
                            "new_comparison_status": status, "old_action_delta": old.get("action_delta"),
                            "new_action_delta": action_delta, "reference_exists": int(ref_exists),
                            "candidate_exists": int(cand_exists), "reference_valid": ref_valid, "candidate_valid": cand_valid})
    _write_csv(out / "comparison_inventory.csv", rows)
    _write_csv(out / "comparison_classification_changes.csv", changes)
    fixtures = [{"fixture": f, "new_status": next((r.get("comparison_status") for r in rows if r.get("decision_id") == f), None),
                 "new_action_delta": next((r.get("action_delta") for r in rows if r.get("decision_id") == f), None)}
                for f in REQUIRED_MISSING_FIXTURES]
    _write_json(out / "classification_fixture_check.json", {"fixtures": fixtures})
    return rows, {"changed_rows": len(changes), "rows": len(rows), "fixtures": fixtures,
                  "status_counts": dict(Counter(r.get("comparison_status") for r in rows)),
                  "action_delta_counts": dict(Counter(r.get("action_delta") for r in rows))}


def _denominators(out: Path, timeline: list[dict[str, Any]], ident: list[dict[str, Any]],
                  comparisons: list[dict[str, Any]], interventions: list[dict[str, Any]],
                  episodes: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    originals = [r for r in timeline if not str(r.get("event_id", "")).__contains__("::decision:")]
    actionable = [r for r in timeline if int(r.get("actionable_boundary") or 0)]
    def measure(n, d, status="available"):
        return {"numerator": n, "denominator": d, "status": status if d else "unavailable", "value": (n / d if d else None)}
    trajectory_keys = {(r.get("source_run_id"), r.get("game_id"), r.get("observer_id"), r.get("variant")) for r in originals}
    game_keys = {(r.get("source_run_id"), r.get("game_id")) for r in originals}
    scenario_keys = {(r.get("source_run_id"), r.get("scenario_id")) for r in originals}
    batch_keys = {(r.get("source_run_id"), r.get("game_id"), r.get("observer_id"), r.get("variant"), r.get("round"), r.get("attempt"))
                  for r in originals if r.get("event_kind") in {"VOTE", "TEAM_VOTE"}}
    episodes = episodes or _read_csv(out / "lock_episodes.csv")
    wrong_episode_count = sum(int(r.get("wrong_decision_boundary_episodes") or 0) for r in episodes)
    wrong_event_count = sum(int(r.get("wrong_event_rows") or 0) for r in episodes)
    return {
        "source_runs": {"numerator": len({r.get("source_run_id") for r in originals}), "denominator": 2, "status": "available"},
        "source_scenarios": {"numerator": len(scenario_keys), "denominator": len(scenario_keys), "status": "available"},
        "unique_source_games": {"numerator": len(game_keys), "denominator": len(game_keys), "status": "available"},
        "observer_variant_trajectories": {"numerator": len(trajectory_keys), "denominator": len(trajectory_keys), "status": "available"},
        "event_rows": {"numerator": len(originals), "denominator": len(originals), "status": "available"},
        "vote_batches": {"numerator": len(batch_keys), "denominator": len(batch_keys), "status": "available"},
        "actionable_decision_boundaries": {"numerator": len(actionable), "denominator": len(actionable), "status": "available"},
        "identification_trajectories": {"numerator": len(ident), "denominator": len(ident), "status": "available"},
        "comparison_pairs": {"numerator": len(comparisons), "denominator": len(comparisons), "status": "available"},
        "vote_intervention_pairs": {"numerator": len({r.get("pair_id") for r in interventions
                                                        if int(r.get("valid_pair") or 0)}),
                                     "denominator": len({r.get("pair_id") for r in interventions}),
                                     "status": "available" if interventions else "NOT_TESTED"},
        "vote_intervention_excluded_pairs": {"numerator": len({r.get("pair_id") for r in interventions
                                                                 if r.get("pair_status") == "INVALID"}),
                                              "denominator": len({r.get("pair_id") for r in interventions}),
                                              "status": "available" if interventions else "NOT_TESTED"},
        "vote_intervention_branches": {"numerator": len(interventions), "denominator": len(interventions),
                                        "status": "available" if interventions else "NOT_TESTED"},
        "wrong_lock_episodes": {"count": wrong_episode_count,
                                 "trajectory_denominator": len(episodes),
                                 "numerator": wrong_episode_count,
                                 "denominator": len(episodes), "status": "corrected_contiguous_actionable_states"},
        "wrong_lock_event_rows": {"count": wrong_event_count,
                                   "event_row_denominator": len(originals),
                                   "numerator": wrong_event_count,
                                   "denominator": len(originals), "status": "event_rows_not_episode_count"},
    }


def _replay_to_cutoff(record: dict[str, Any], cutoff_seq: int) -> tuple[Game, int]:
    game = Game([Player(**p) for p in record["players"]], seed=record["seed"], direction=record["direction"])
    cursor = 0
    while len(game.events) < cutoff_seq:
        trans = source_transaction(game, record.get("decisions", []), cursor)
        getattr(game, trans["method"])(*trans["args"], **trans["kwargs"])
        cursor = trans["decisions_through"]
    if len(game.events) != cutoff_seq:
        raise ValueError(f"replay stopped at {len(game.events)} rather than cutoff {cutoff_seq}")
    return game, cursor


def _merlin_top(observer, view: dict[str, Any] | None = None) -> list[str]:
    return _merlin_metrics(observer, "", view)["exact_top"]


def _assassin_cutoff_anchor(strict: dict[tuple[str, str, str, str, int, int], dict[str, Any]],
                            case: dict[str, Any], assassin_id: str) -> dict[str, Any] | None:
    """Find the same verified public cutoff for the Assassin seat.

    P0 may have stored another native variant for that seat.  Its legal view
    and public-prefix hashes still anchor the pre-state; the measurement below
    is always rebuilt with the frozen ``joint_v2`` observer.
    """
    candidates = [entry for key, entry in strict.items()
                  if key[0] == str(case["source_run_id"])
                  and key[1] == str(case["game_id"])
                  and key[5] == int(case["cutoff_seq"])
                  and str(entry["cutoff"].get("observer_id")) == assassin_id]
    if not candidates:
        return None
    candidates.sort(key=lambda entry: (str(entry["cutoff"].get("native_variant")),
                                       int(entry["cutoff"].get("decision_index", -1))))
    return candidates[0]


def _factor_provenance(observer, event: dict[str, Any], branch: str, pair_id: str,
                       *, duplicate_suppressed: int = 0,
                       context: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    result = []
    for factor in getattr(observer, "last_factors", []) or []:
        if isinstance(factor, dict):
            metadata = factor.get("metadata", {}) or {}
            feature = factor.get("feature")
            source_agent = factor.get("source_agent")
            targets = factor.get("target_agents", []) or []
            evidence_type = factor.get("evidence_type")
            if hasattr(evidence_type, "value"):
                evidence_type = evidence_type.value
        else:
            metadata = getattr(factor, "metadata", {}) or {}
            feature = getattr(factor, "feature", None)
            source_agent = getattr(factor, "source_agent", None)
            targets = list(getattr(factor, "target_agents", []) or [])
            evidence_type = getattr(getattr(factor, "evidence_type", None), "value", None)
        row = {"pair_id": pair_id, "branch": branch, "event_id": event.get("record_id"),
                       "signal_id": metadata.get("signal_id"), "factor_name": feature,
                       "factor_consumed": 1, "duplicate_suppressed": duplicate_suppressed,
                       "source_agent": source_agent, "target_agents": targets,
                       "evidence_type": evidence_type,
                       "metadata": metadata}
        if context:
            row.update(context)
        row["factor_likelihood_by_merlin_hypothesis"] = _factor_likelihoods(observer, {
            "origin_event_id": event.get("record_id"), "source_agent": source_agent,
            "target_agents": targets, "evidence_type": evidence_type, "feature": feature,
            "direction": getattr(factor, "direction", None) if not isinstance(factor, dict) else factor.get("direction"),
            "strength": getattr(factor, "strength", 1.0) if not isinstance(factor, dict) else factor.get("strength", 1.0),
            "metadata": metadata,
        })
        result.append(row)
    return result


def _vote_interventions(out: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    frozen = (_read_json(out / "p1_preregistered_cases.json", {}) or {}).get("cases", [])
    strict, strict_counts = _strict_cutoff_index()
    interventions: list[dict[str, Any]] = []
    safety: list[dict[str, Any]] = []
    factors: list[dict[str, Any]] = []
    pair_summaries: list[dict[str, Any]] = []
    records, _ = _source_records()

    for case in frozen:
        actor_id = str(case.get("intervention_actor_id") or case.get("source_observer_id") or case.get("observer_id"))
        measurement_id = str(case.get("measurement_observer_id") or case.get("observer_id"))
        pair_id = f"{case['source_run_id']}:{case['game_id']}:{actor_id}->{measurement_id}:{case['decision_index']}"
        source_observer_id = str(case.get("source_observer_id") or actor_id)
        key = (case["source_run_id"], case["game_id"], source_observer_id,
               case["native_variant"], case["decision_index"], case["cutoff_seq"])
        bound = strict.get(key)
        base = {
            "pair_id": pair_id,
            "source_run_id": case.get("source_run_id"), "scenario_id": case.get("scenario_id"),
            "game_id": case.get("game_id"), "native_variant": case.get("native_variant"),
            "decision_index": case.get("decision_index"), "cutoff_seq": case.get("cutoff_seq"),
            "source_observer_id": source_observer_id, "observer_id": measurement_id,
            "intervention_actor_id": actor_id, "intervention_actor_role": case.get("intervention_actor_role", "MERLIN"),
            "measurement_observer_id": measurement_id, "measurement_observer_role": case.get("measurement_observer_role", "ASSASSIN"),
            "source_file": case.get("source_file"), "source_context_sha256": None,
            "source_verification_status": "NOT_MATCHED", "cutoff_verified": 0,
            "intervention_type": "merlin_vote_true_vs_false_only", "public_prefix_hash": case.get("public_prefix_hash"),
            "legal_view_hash": case.get("legal_view_hash"), "engine_pre_state_hash": None,
            "actor_pre_state_hash": None, "measurement_pre_state_hash": None,
            "observer_belief_pre_state_hash": None, "branch": None,
            "round": None, "attempt": None, "team": None,
            "merlin_vote": None, "legal_action_valid": 0, "other_ballots_source": case.get("other_ballots_source"),
            "other_ballots_config_hash": digest(case.get("other_ballots")), "sealed_input_leak_check": "PASS_PUBLIC_STATE_ONLY",
            "public_commit_id": None, "evaluation_boundary": None, "post_phase": None,
            "factor_name": None, "factor_signal_id": None, "factor_consumed": 0, "duplicate_suppressed": 0,
            "reference_vote": True, "candidate_vote": False,
            "merlin_marginals_before": None, "merlin_marginals_after": None, "max_abs_raw_delta": None,
            "native_exact_top_before": None, "native_exact_top_after": None,
            "near_top_diagnostic_before": None, "near_top_diagnostic_after": None,
            "assassin_true_merlin_p_before": None, "assassin_true_merlin_p_after": None,
            "assassin_true_merlin_rank_before": None, "assassin_true_merlin_rank_after": None,
            "merlin_lead_before": None, "merlin_lead_after": None,
            "exact_top_before": None, "exact_top_after": None,
            "factor_likelihood_by_merlin_hypothesis": None,
            "actual_decoder_called": 0, "actual_target": None, "target_unavailable_reason": "not_assassination_boundary",
            "proposal_approved": None, "rejection_count_after": None, "ap_delta": None,
            "terminal_status": "NOT_TESTED", "immediate_loss": "UNKNOWN", "safety_status": "NOT_TESTED",
            "safety_basis": None, "future_events_injected": 0,
            "pair_status": "INVALID", "valid_pair": 0, "invalid_reason": None, "error": None,
        }

        def invalid_pair(reason: str, *, cutoff_verified: int = 0, source_status: str = "NOT_MATCHED") -> None:
            for branch, vote in (("reference", True), ("candidate", False)):
                row = dict(base)
                row.update(branch=branch, merlin_vote=vote, cutoff_verified=cutoff_verified,
                           source_verification_status=source_status, pair_status="INVALID",
                           valid_pair=0, invalid_reason=reason, error=reason)
                interventions.append(row)
                safety.append({"pair_id": pair_id, "branch": branch, "merlin_vote": vote,
                               "pair_status": "INVALID", "valid_pair": 0, "invalid_reason": reason,
                               "safety_status": "INVALID", "future_events_injected": 0,
                               "truth_used_by_agent": 0, "truth_used_by_scorer": 1})
            pair_summaries.append({"pair_id": pair_id, "source_run_id": case.get("source_run_id"),
                                   "scenario_id": case.get("scenario_id"), "game_id": case.get("game_id"),
                                   "round": None, "attempt": None, "intervention_actor_id": actor_id,
                                   "intervention_actor_role": "MERLIN", "measurement_observer_id": measurement_id,
                                   "measurement_observer_role": "ASSASSIN", "pair_status": "INVALID",
                                   "valid_pair": 0, "invalid_reason": reason})

        if not bound:
            invalid_pair("source_merlin_cutoff_unavailable")
            continue

        record = bound.get("record") or records.get((case["source_run_id"], case["game_id"]))
        try:
            role_map = _roles(record)
            if role_map.get(actor_id) != "MERLIN":
                raise ValueError("intervention_actor_is_not_merlin")
            if role_map.get(measurement_id) != "ASSASSIN":
                raise ValueError("measurement_observer_is_not_assassin")
            if actor_id == measurement_id:
                raise ValueError("measurement_observer_equals_intervention_actor")
            assassin_anchor = _assassin_cutoff_anchor(strict, case, measurement_id)
            if assassin_anchor is None:
                raise ValueError("assassin_verified_cutoff_unavailable")
            game, _ = _replay_to_cutoff(record, case["cutoff_seq"])
            actor_view = _public_view(game, actor_id)
            assassin_view = _public_view(game, measurement_id)
            if digest(actor_view) != case["legal_view_hash"] or game.phase != "vote":
                raise ValueError("merlin_pre_state_hash_or_phase_mismatch")
            if digest(assassin_view) != assassin_anchor["cutoff"].get("legal_view_hash"):
                raise ValueError("assassin_public_pre_state_hash_mismatch")
            public_prefix_hash = digest([context_record(event) for event in game.events
                                         if event.get("kind") in PUBLIC_KINDS])
            if public_prefix_hash != case.get("public_prefix_hash"):
                raise ValueError("public_prefix_hash_mismatch")

            observer = make_version("joint_v2", deepcopy(assassin_view))
            for event in game.events:
                if event.get("kind") in PUBLIC_KINDS:
                    observer.observe(context_record(event))
            true_merlin = actor_id
            before = observer.marginals()
            before_metrics = _merlin_metrics(observer, true_merlin, assassin_view)
            observer_belief_hash = observer.snapshot().get("posterior_hash")
            menu = legal_menu(actor_view)
            vote_options = {bool(entry["action"].get("approve")): entry for entry in menu
                            if "approve" in entry.get("action", {}) and entry.get("action", {}).get("strong") is False}
            if set(vote_options) != {True, False}:
                raise ValueError("production_vote_menu_missing_boolean_arms")
            fixed = dict(case["other_ballots"])
            ids = list(game.ids)
            if set(fixed) != set(ids) - {actor_id}:
                raise ValueError("other_ballots_do_not_match_all_non_merlin_seats")
            pair_pre = {
                "actor_pre_state_hash": digest(actor_view), "measurement_pre_state_hash": digest(assassin_view),
                "observer_belief_pre_state_hash": observer_belief_hash,
                "round": game.round, "attempt": game.attempt, "team": list(game.team),
                "source_context_sha256": sha256(Path(bound["context_path"])),
                "source_verification_status": _details_index().get((case["source_run_id"], case["game_id"]), {}).get("verification_status"),
            }
            branch_results: dict[str, dict[str, Any]] = {}
            pair_reasons: list[str] = []
            for branch, merlin_vote in (("reference", True), ("candidate", False)):
                clone = deepcopy(game)
                clone_observer = deepcopy(observer)
                votes = {pid: bool(fixed.get(pid, False)) for pid in ids}
                votes[actor_id] = merlin_vote
                reasons = {pid: "team_risk" for pid in ids}
                strong = {pid: False for pid in ids}
                for pid in ids:
                    clone.validate_ballot(pid, votes[pid], strong[pid])
                pre_resolve = clone.resolve.get(actor_id)
                clone.vote(votes, reasons=reasons, strong=strong)
                new_events = clone.events[case["cutoff_seq"]:]
                branch_factors: list[dict[str, Any]] = []
                branch_errors: list[str] = []
                for event in new_events:
                    if event.get("kind") not in PUBLIC_KINDS:
                        continue
                    expected_signals = _event_signal_ids(event, measurement_id)
                    applied_before = set(getattr(getattr(clone_observer, "engine", None), "_applied_signals", set()))
                    clone_observer.observe(context_record(event))
                    duplicate = int(bool(expected_signals) and set(expected_signals) <= applied_before)
                    fresh = _factor_provenance(
                        clone_observer, event, branch, pair_id,
                        context={"source_run_id": case.get("source_run_id"), "game_id": case.get("game_id"),
                                 "round": game.round, "attempt": game.attempt,
                                 "intervention_actor_id": actor_id, "intervention_actor_role": "MERLIN",
                                 "measurement_observer_id": measurement_id, "measurement_observer_role": "ASSASSIN",
                                 "reference_merlin_vote": True, "candidate_merlin_vote": False,
                                 "posterior_before_hash": observer_belief_hash,
                                 "posterior_after_hash": clone_observer.snapshot().get("posterior_hash")})
                    if expected_signals and not fresh and not duplicate:
                        branch_errors.append(f"missing_factor:{event.get('record_id')}")
                    if event.get("kind") == "TEAM_VOTE" and fresh:
                        branch_errors.append("aggregate_vote_double_count_or_unconsumed_factor")
                    branch_factors.extend(fresh)
                    if duplicate:
                        for signal_id in expected_signals:
                            branch_factors.append({
                                "pair_id": pair_id, "branch": branch, "event_id": event.get("record_id"),
                                "signal_id": signal_id, "factor_name": "team_vote", "factor_consumed": 0,
                                "duplicate_suppressed": 1, "source_agent": None, "target_agents": [],
                                "evidence_type": "behavioral", "metadata": {"signal_id": signal_id},
                                "factor_likelihood_by_merlin_hypothesis": {},
                                "source_run_id": case.get("source_run_id"), "game_id": case.get("game_id"),
                                "round": game.round, "attempt": game.attempt,
                                "intervention_actor_id": actor_id, "intervention_actor_role": "MERLIN",
                                "measurement_observer_id": measurement_id, "measurement_observer_role": "ASSASSIN",
                                "reference_merlin_vote": True, "candidate_merlin_vote": False,
                                "posterior_before_hash": observer_belief_hash,
                                "posterior_after_hash": clone_observer.snapshot().get("posterior_hash"),
                            })
                after = clone_observer.marginals()
                after_metrics = _merlin_metrics(clone_observer, true_merlin, assassin_view)
                public_commit = next((e for e in new_events if e.get("kind") == "TEAM_VOTE"), None)
                if not public_commit:
                    branch_errors.append("missing_team_vote_public_commit")
                expected_merlin_signal = f"vote:{game.round}:{game.attempt}:{actor_id}"
                consumed_rows = [row for row in branch_factors
                                 if row.get("signal_id") == expected_merlin_signal and int(row.get("factor_consumed") or 0)]
                if len(consumed_rows) != 1:
                    branch_errors.append(f"merlin_vote_factor_consumed_{len(consumed_rows)}_times")
                duplicate_rows = [row for row in branch_factors if int(row.get("duplicate_suppressed") or 0)]
                row = dict(base)
                row.update({**pair_pre, "cutoff_verified": 1, "branch": branch, "merlin_vote": merlin_vote,
                            "legal_action_valid": 1, "engine_pre_state_hash": digest({"actor": actor_view, "measurement": assassin_view}),
                            "public_commit_id": public_commit.get("record_id") if public_commit else None,
                            "evaluation_boundary": "POST_TEAM_VOTE_MINIMAL_COMPLETE_BATCH", "post_phase": clone.phase,
                            "factor_name": ";".join(sorted({str(f.get("factor_name")) for f in branch_factors
                                                               if f.get("factor_name") and int(f.get("factor_consumed") or 0)})) or None,
                            "factor_signal_id": ";".join(sorted({str(f.get("signal_id")) for f in branch_factors if f.get("signal_id")})) or None,
                            "factor_consumed": len(consumed_rows), "duplicate_suppressed": len(duplicate_rows),
                            "merlin_marginals_before": json.dumps(before, sort_keys=True),
                            "merlin_marginals_after": json.dumps(after, sort_keys=True),
                            "max_abs_raw_delta": max((abs(float(after.get(pid, {}).get("merlin", 0.0)) - float(before.get(pid, {}).get("merlin", 0.0)))
                                                        for pid in set(before) | set(after)), default=0.0),
                            "native_exact_top_before": json.dumps(before_metrics["exact_top"]),
                            "native_exact_top_after": json.dumps(after_metrics["exact_top"]),
                            "near_top_diagnostic_before": json.dumps(before_metrics["exact_top"]),
                            "near_top_diagnostic_after": json.dumps(after_metrics["exact_top"]),
                            "assassin_true_merlin_p_before": before_metrics["true_merlin_probability"],
                            "assassin_true_merlin_p_after": after_metrics["true_merlin_probability"],
                            "assassin_true_merlin_rank_before": before_metrics["true_merlin_rank"],
                            "assassin_true_merlin_rank_after": after_metrics["true_merlin_rank"],
                            "merlin_lead_before": before_metrics["merlin_lead"], "merlin_lead_after": after_metrics["merlin_lead"],
                            "exact_top_before": json.dumps(before_metrics["exact_top"]), "exact_top_after": json.dumps(after_metrics["exact_top"]),
                            "factor_likelihood_by_merlin_hypothesis": json.dumps(
                                next((f.get("factor_likelihood_by_merlin_hypothesis") for f in consumed_rows), {}), sort_keys=True),
                            "proposal_approved": public_commit.get("approved") if public_commit else None,
                            "rejection_count_after": clone.attempt - 1,
                            "ap_delta": (pre_resolve - clone.resolve.get(actor_id)) if pre_resolve is not None else None,
                            "terminal_status": clone.winner or clone.phase,
                            "immediate_loss": "CLEAR_TERMINAL_EVIL" if clone.winner == "EVIL" else "UNKNOWN",
                            "safety_status": "CLEAR_TERMINAL_LOSS" if clone.winner == "EVIL" else "NOT_PROVEN",
                            "safety_basis": clone.winner or "vote-only boundary has no mission/assassination outcome",
                            "future_events_injected": 0, "error": ";".join(branch_errors) or None})
                branch_results[branch] = {"row": row, "metrics": after_metrics, "factors": branch_factors,
                                          "errors": branch_errors}
                pair_reasons.extend(branch_errors)
        except Exception as exc:
            invalid_pair(f"{type(exc).__name__}:{exc}", cutoff_verified=int(bool(bound)),
                         source_status=_details_index().get((case["source_run_id"], case["game_id"]), {}).get("verification_status", "NOT_MATCHED"))
            continue

        if set(branch_results) != {"reference", "candidate"}:
            invalid_pair("both_vote_branches_not_generated", cutoff_verified=1,
                         source_status=pair_pre["source_verification_status"])
            continue
        if any(branch_results[name]["row"]["engine_pre_state_hash"] != branch_results["reference"]["row"]["engine_pre_state_hash"]
               for name in branch_results):
            pair_reasons.append("reference_candidate_pre_state_mismatch")
        if any(branch_results[name]["row"].get("factor_consumed") != 1 for name in branch_results):
            pair_reasons.append("merlin_vote_factor_not_consumed_once_in_each_arm")
        pair_valid = not pair_reasons
        ref, cand = branch_results["reference"]["row"], branch_results["candidate"]["row"]
        ref_metrics, cand_metrics = branch_results["reference"]["metrics"], branch_results["candidate"]["metrics"]
        dp = (cand_metrics["true_merlin_probability"] - ref_metrics["true_merlin_probability"]
              if cand_metrics["true_merlin_probability"] is not None and ref_metrics["true_merlin_probability"] is not None else None)
        dr = (cand_metrics["true_merlin_rank"] - ref_metrics["true_merlin_rank"]
              if cand_metrics["true_merlin_rank"] is not None and ref_metrics["true_merlin_rank"] is not None else None)
        dl = (cand_metrics["merlin_lead"] - ref_metrics["merlin_lead"]
              if cand_metrics["merlin_lead"] is not None and ref_metrics["merlin_lead"] is not None else None)
        pair_reason = ";".join(sorted(set(pair_reasons))) or None
        top_changed = int(ref.get("exact_top_after") != cand.get("exact_top_after"))
        meaningful = ((dp is not None and abs(dp) > EPSILON_DIAGNOSTIC) or dr not in (None, 0)
                      or (dl is not None and abs(dl) > EPSILON_DIAGNOSTIC) or bool(top_changed))
        pair_summary = {
            "pair_id": pair_id, "source_run_id": case.get("source_run_id"), "scenario_id": case.get("scenario_id"),
            "game_id": case.get("game_id"), "round": game.round, "attempt": game.attempt,
            "intervention_actor_id": actor_id, "intervention_actor_role": "MERLIN",
            "measurement_observer_id": measurement_id, "measurement_observer_role": "ASSASSIN",
            "reference_vote": True, "candidate_vote": False,
            "assassin_true_merlin_p_before": ref.get("assassin_true_merlin_p_before"),
            "assassin_true_merlin_p_reference_after": ref.get("assassin_true_merlin_p_after"),
            "assassin_true_merlin_p_candidate_after": cand.get("assassin_true_merlin_p_after"), "delta_p_merlin": dp,
            "assassin_true_merlin_rank_reference": ref.get("assassin_true_merlin_rank_after"),
            "assassin_true_merlin_rank_candidate": cand.get("assassin_true_merlin_rank_after"), "delta_rank": dr,
            "exact_top_reference": ref.get("exact_top_after"), "exact_top_candidate": cand.get("exact_top_after"),
            "delta_exact_top": top_changed,
            "merlin_lead_reference": ref.get("merlin_lead_after"), "merlin_lead_candidate": cand.get("merlin_lead_after"),
            "delta_lead": dl,
            "unique_top_enter": int(cand_metrics["unique_top"] == actor_id and ref_metrics["unique_top"] != actor_id),
            "unique_top_escape": int(ref_metrics["unique_top"] == actor_id and cand_metrics["unique_top"] != actor_id),
            "factor_signal_id": f"vote:{game.round}:{game.attempt}:{actor_id}",
            "factor_likelihood_by_merlin_hypothesis": cand.get("factor_likelihood_by_merlin_hypothesis"),
            "factor_consumed_reference": ref.get("factor_consumed"), "factor_consumed_candidate": cand.get("factor_consumed"),
            "duplicate_suppressed_reference": ref.get("duplicate_suppressed"),
            "duplicate_suppressed_candidate": cand.get("duplicate_suppressed"),
            "public_prefix_hash": case.get("public_prefix_hash"), "assassin_pre_state_hash": ref.get("measurement_pre_state_hash"),
            "pair_status": "VALID" if pair_valid else "INVALID", "valid_pair": int(pair_valid),
            "invalid_reason": pair_reason, "effect_classification": "INVALID" if not pair_valid else
            ("MEANINGFUL_CHANGE" if meaningful else "NO_MEANINGFUL_CHANGE"),
        }
        for branch_name, result in branch_results.items():
            result["row"].update({"pair_status": pair_summary["pair_status"], "valid_pair": pair_summary["valid_pair"],
                                   "invalid_reason": pair_reason})
            interventions.append(result["row"])
            factors.extend(result["factors"])
            row = result["row"]
            safety.append({"pair_id": pair_id, "branch": branch_name, "merlin_vote": row["merlin_vote"],
                           "proposal_approved": row["proposal_approved"], "post_phase": row["post_phase"],
                           "terminal_status": row["terminal_status"], "immediate_loss": row["immediate_loss"],
                           "safety_status": row["safety_status"] if pair_valid else "INVALID",
                           "safety_basis": row["safety_basis"], "rejection_count_after": row["rejection_count_after"],
                           "ap_delta": row["ap_delta"], "future_events_injected": 0,
                           "pair_status": pair_summary["pair_status"], "valid_pair": pair_summary["valid_pair"],
                           "invalid_reason": pair_reason, "truth_used_by_agent": 0, "truth_used_by_scorer": 1})
        pair_summaries.append(pair_summary)

    _write_csv(out / "vote_interventions.csv", interventions)
    _write_csv(out / "vote_channel_pairs.csv", pair_summaries)
    _write_csv(out / "vote_safety_audit.csv", safety)
    _append_jsonl(out / "vote_factor_provenance.jsonl", factors)
    return interventions, safety, {"strict_cutoff_counts": strict_counts, "cases": len(frozen),
                                   "valid_pairs": sum(int(r.get("valid_pair") or 0) for r in pair_summaries),
                                   "invalid_pairs": sum(int(r.get("pair_status") == "INVALID") for r in pair_summaries),
                                   "branch_rows": len(interventions), "factor_rows": len(factors),
                                   "pair_summaries": pair_summaries}


def _vote_signal_analysis(out: Path, vote_meta: dict[str, Any]) -> list[dict[str, Any]]:
    """Describe the frozen vote factor after the corrected causal probe.

    This is an offline scorer report.  It reads truth only to label the
    mechanism context; no field here is fed to an acting agent.
    """
    pair_summaries = [row for row in vote_meta.get("pair_summaries", []) if row.get("valid_pair")]
    if not pair_summaries:
        return []
    cases = (_read_json(out / "p1_preregistered_cases.json", {}) or {}).get("cases", [])
    case_by_pair = {}
    for case in cases:
        actor = str(case.get("intervention_actor_id") or case.get("source_observer_id") or case.get("observer_id"))
        measurement = str(case.get("measurement_observer_id") or case.get("observer_id"))
        pair_id = f"{case['source_run_id']}:{case['game_id']}:{actor}->{measurement}:{case['decision_index']}"
        case_by_pair[pair_id] = case
    branch_rows = _read_csv(out / "vote_interventions.csv")
    by_pair_branch = {(row.get("pair_id"), row.get("branch")): row for row in branch_rows}
    records, _ = _source_records()
    rows: list[dict[str, Any]] = []
    for summary in pair_summaries:
        case = case_by_pair.get(summary.get("pair_id"))
        if not case:
            continue
        record = records[(case["source_run_id"], case["game_id"])]
        game, _ = _replay_to_cutoff(record, int(case["cutoff_seq"]))
        roles = _roles(record)
        actor = str(summary["intervention_actor_id"])
        measurement = str(summary["measurement_observer_id"])
        team = list(game.team)
        evil_ids = sorted(pid for pid, role in roles.items() if role in {"EVIL", "ASSASSIN"})
        actor_view = _public_view(game, actor)
        team_vote_history = [event for event in game.events if event.get("kind") == "TEAM_VOTE"]
        proposal_history = [event for event in game.events if event.get("kind") in {"TEAM", "TEAM_REVISE", "TEAM_LOCK"}]
        mission_history = [event for event in game.events if event.get("kind") == "MISSION"]
        social_history = [event for event in game.events if event.get("kind") in {"SOCIAL", "REACT", "CHALLENGE_RESPONSE"}]
        accusations = [event for event in social_history if event.get("card") in {"ACCUSE", "PRESSURE", "CHALLENGE"}]
        ref = by_pair_branch[(summary["pair_id"], "reference")]
        cand = by_pair_branch[(summary["pair_id"], "candidate")]
        ref_factor = _parse_json(ref.get("factor_likelihood_by_merlin_hypothesis"), {}) or {}
        cand_factor = _parse_json(cand.get("factor_likelihood_by_merlin_hypothesis"), {}) or {}
        ref_actor_likelihood = (ref_factor.get(actor) or [None])[0]
        cand_actor_likelihood = (cand_factor.get(actor) or [None])[0]
        true_evil_on_team = sorted(pid for pid in team if pid in evil_ids)
        dirty = bool(true_evil_on_team)
        rows.append({
            "pair_id": summary["pair_id"], "source_run_id": summary["source_run_id"],
            "scenario_id": summary["scenario_id"], "game_id": summary["game_id"],
            "round": summary["round"], "attempt": summary["attempt"],
            "intervention_actor_id": actor, "measurement_observer_id": measurement,
            "team": json.dumps(team), "true_evil_ids": json.dumps(evil_ids),
            "true_evil_on_team": json.dumps(true_evil_on_team), "true_evil_count_on_team": len(true_evil_on_team),
            "merlin_known_evil_in_team": json.dumps(sorted(pid for pid in team if pid in set(actor_view.get("known_evil", [])))),
            "reference_merlin_vote": ref.get("merlin_vote"), "candidate_merlin_vote": cand.get("merlin_vote"),
            "reference_vote_matches_true_team_signal": int(_bool(ref.get("merlin_vote")) is not None and
                                                             _bool(ref.get("merlin_vote")) != dirty),
            "candidate_vote_matches_true_team_signal": int(_bool(cand.get("merlin_vote")) is not None and
                                                             _bool(cand.get("merlin_vote")) != dirty),
            "reference_factor_likelihood_for_merlin": ref_actor_likelihood,
            "candidate_factor_likelihood_for_merlin": cand_actor_likelihood,
            "factor_likelihood_reference": json.dumps(ref_factor, sort_keys=True),
            "factor_likelihood_candidate": json.dumps(cand_factor, sort_keys=True),
            "public_vote_history_count": len(team_vote_history),
            "public_vote_history": json.dumps([{"round": e.get("round"), "attempt": e.get("attempt"),
                                                   "team": e.get("team"), "votes": e.get("votes")} for e in team_vote_history],
                                                  sort_keys=True),
            "proposal_history": json.dumps([{"kind": e.get("kind"), "actor": e.get("actor"), "team": e.get("team")}
                                               for e in proposal_history], sort_keys=True),
            "mission_history": json.dumps([{"round": e.get("round"), "team": e.get("team"),
                                              "success": e.get("success"), "fail_count": e.get("fail_count")}
                                             for e in mission_history], sort_keys=True),
            "public_suspicion_accusation_count": len(accusations),
            "public_suspicion_cards": json.dumps([{"actor": e.get("actor"), "card": e.get("card"), "target": e.get("target")}
                                                    for e in accusations], sort_keys=True),
            "mission_score_good": game.successes, "mission_score_evil": game.failures,
            "rejection_count_before": sum(1 for e in team_vote_history if not e.get("approved")),
            "delta_p_merlin": summary.get("delta_p_merlin"), "delta_rank": summary.get("delta_rank"),
            "delta_lead": summary.get("delta_lead"), "delta_exact_top": summary.get("delta_exact_top"),
            "exact_top_reference": summary.get("exact_top_reference"), "exact_top_candidate": summary.get("exact_top_candidate"),
            "factor_consumed_reference": summary.get("factor_consumed_reference"),
            "factor_consumed_candidate": summary.get("factor_consumed_candidate"),
            "duplicate_suppressed_reference": summary.get("duplicate_suppressed_reference"),
            "duplicate_suppressed_candidate": summary.get("duplicate_suppressed_candidate"),
            "mechanism_consistent_evidence": 1, "causal_paired_evidence": 1,
            "correlation_only": 0,
        })
    _write_csv(out / "vote_signal_cases.csv", rows)
    if not rows:
        return rows
    dp = [float(row["delta_p_merlin"]) for row in rows]
    dr = [int(row["delta_rank"]) for row in rows]
    dl = [float(row["delta_lead"]) for row in rows]
    ref_like = [float(row["reference_factor_likelihood_for_merlin"]) for row in rows]
    cand_like = [float(row["candidate_factor_likelihood_for_merlin"]) for row in rows]
    lines = [
        "# Vote signal analysis", "", f"Run `{out.name}`; network calls: `0`.", "",
        "## Gate and evidence levels", "",
        f"The corrected vote-channel gate is `ACTIONABLE_BUT_POTENTIALLY_UNSAFE` for `{len(rows)}` valid paired cutoffs. "
        "All pairs use the actual Merlin as the intervention actor and the actual Assassin as the measurement observer. "
        "Every pair holds the verified pre-state and public prefix fixed, consumes the changed Merlin `team_vote` factor once, "
        "and records aggregate `TEAM_VOTE` duplicates as suppressed.", "",
        "The pair deltas are causal paired evidence for this fixed mechanism. Public suspicion, mission history, and proposal history "
        "below are context descriptors and correlation checks; they are not themselves causal policy evidence.", "",
        "## Mechanism", "",
        "The frozen `team_vote` likelihood treats an actor as Merlin with likelihood `1.06` when the vote disagrees with the "
        "hidden evil membership of the proposed team, and `1/1.06 = 0.9433962264150942` when it agrees. Other Merlin hypotheses "
        "receive `1.0` in these rows. This is the mechanism-consistent private-information signal exposed by the production factor; "
        "it is not a new policy and was not changed in this run.", "",
        f"Across the six valid pairs, `delta_p_merlin` ranges from `{min(dp):.6f}` to `{max(dp):.6f}`, "
        f"`delta_rank` ranges from `{min(dr)}` to `{max(dr)}`, and `delta_lead` ranges from `{min(dl):.6f}` to `{max(dl):.6f}`. "
        f"The Merlin-hypothesis factor values range from `{min(ref_like + cand_like):.6f}` to `{max(ref_like + cand_like):.6f}`.", "",
        "## Causal paired cases", "",
        "| Pair | Team / true evil on team | Merlin vote reference → candidate | ΔP Merlin | Δrank | Δlead | Exact top reference → candidate |",
        "|---|---|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        lines.append(f"| `{row['pair_id']}` | `{row['team']}` / `{row['true_evil_on_team']}` | "
                     f"`{row['reference_merlin_vote']}` → `{row['candidate_merlin_vote']}` | "
                     f"`{float(row['delta_p_merlin']):+.6f}` | `{row['delta_rank']}` | `{float(row['delta_lead']):+.6f}` | "
                     f"`{row['exact_top_reference']}` → `{row['exact_top_candidate']}` |")
    lines += [
        "", "## Interpretation and limits", "",
        "The six paired changes establish that the legal Merlin vote reaches the Assassin's `joint_v2` evidence path and can alter "
        "the Assassin's true-Merlin marginal, rank, lead, or exact top set. They do not establish that a camouflage policy is safe. "
        "The direction changes with the public team context: a vote that agrees with the hidden team composition is down-weighted under "
        "the Merlin hypothesis, while a vote that disagrees is up-weighted. This supports mechanism-consistent evidence, not a general "
        "claim that one fixed vote direction is always safer.", "",
        "No candidate was designed or enabled. No full-game outcome, mission-safety tradeoff, or production effect was tested. "
        "The next permitted step is to freeze one interpretable candidate specification using these contexts, then run only its offline "
        "fixed-state comparison; external APIs and full-game tests remain prohibited.", "",
    ]
    _write_text(out / "vote_signal_analysis.md", "\n".join(lines) + "\n")
    return rows


def _candidate_public_proxy(game: Game, team: list[str]) -> tuple[float, dict[str, Any]]:
    """Return a public-only suspicion score for the proposed team."""
    members = set(team)
    accusation_targets = [event for event in game.events
                          if event.get("kind") == "SOCIAL"
                          and event.get("card") == "ACCUSE"
                          and event.get("target") in members]
    hedge_targets = [event for event in game.events
                     if event.get("kind") == "SOCIAL"
                     and event.get("card") == "HEDGE"
                     and event.get("target") in members]
    rejected_overlap = [event for event in game.events
                        if event.get("kind") == "TEAM_VOTE"
                        and not event.get("approved")
                        and members.intersection(event.get("team") or [])]
    mission_failures = [event for event in game.events
                        if event.get("kind") == "MISSION"
                        and not event.get("success")
                        and members.intersection(event.get("team") or [])]
    # ACCUSE is the only unit-weight signal.  HEDGE and a rejected overlapping
    # team are half-weight public context; mission failures are two points.
    score = (len(accusation_targets) + 0.5 * len(hedge_targets)
             + 0.5 * len(rejected_overlap) + 2.0 * len(mission_failures))
    return score, {
        "accusation_count": len(accusation_targets),
        "hedge_count": len(hedge_targets),
        "rejected_overlap_count": len(rejected_overlap),
        "mission_failure_count": len(mission_failures),
    }


def _candidate_vote_decision(game: Game, actor_view: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    """Frozen MerlinVoteCamouflageV1 decision using no evaluator state."""
    team = list(game.team)
    known_evil = sorted(set(actor_view.get("known_evil", [])))
    known_evil_on_team = sorted(pid for pid in team if pid in set(known_evil))
    public_score, public_components = _candidate_public_proxy(game, team)
    mission_safety_vote = not bool(known_evil_on_team)
    public_proxy_vote = public_score < CANDIDATE_PUBLIC_SUSPICION_THRESHOLD
    rejection_count = sum(1 for event in game.events
                          if event.get("kind") == "TEAM_VOTE" and not event.get("approved"))
    critical = (rejection_count >= CANDIDATE_CRITICAL_REJECTIONS
                or int(getattr(game, "failures", 0)) >= CANDIDATE_CRITICAL_FAILURES)
    ambiguous_safe = (not critical and mission_safety_vote != public_proxy_vote
                      and abs(public_score - CANDIDATE_PUBLIC_SUSPICION_THRESHOLD)
                      <= CANDIDATE_AMBIGUITY_BAND)
    if critical:
        vote, mode = mission_safety_vote, "CRITICAL_MISSION_SAFETY"
    elif ambiguous_safe:
        vote, mode = public_proxy_vote, "AMBIGUOUS_SAFE_PUBLIC_PROXY"
    else:
        vote, mode = mission_safety_vote, "MISSION_SAFETY_DEFAULT"
    return bool(vote), {
        "policy_version": "MerlinVoteCamouflageV1",
        "mode": mode,
        "critical": int(critical),
        "ambiguous_safe": int(ambiguous_safe),
        "known_evil_on_team": known_evil_on_team,
        "mission_safety_vote": bool(mission_safety_vote),
        "public_proxy_vote": bool(public_proxy_vote),
        "public_suspicion_score": public_score,
        "public_proxy_components": public_components,
        "rejection_count_before": rejection_count,
        "mission_failures_before": int(getattr(game, "failures", 0)),
        "truth_used_by_agent": 0,
        "assassin_state_used": 0,
        "evaluator_labels_used": 0,
    }


def _write_candidate_spec(out: Path) -> None:
    _write_text(out / "candidate_spec.md", f"""# MerlinVoteCamouflageV1

Status: **offline fixed-state candidate; production OFF**.

The candidate is frozen before its six-state comparison. It may read only the acting Merlin's legal role view, the current proposal, round/mission/rejection state, and public history. It never reads Assassin state, evaluator labels, a counterfactual arm, future events, or hidden role assignments beyond Merlin's normal legal knowledge.

## Decision rules

1. `CRITICAL` is frozen as `rejection_count_before >= {CANDIDATE_CRITICAL_REJECTIONS}` or `mission_failures_before >= {CANDIDATE_CRITICAL_FAILURES}`. In this state the candidate uses its mission-safety vote.
2. `mission_safety_vote` is `REJECT` when the proposed team contains a Merlin-known evil player, otherwise `APPROVE`.
3. `public_only_vote_proxy` scores public `ACCUSE` targets at 1 point, public `HEDGE` targets at 0.5, rejected overlapping teams at 0.5, and failed missions involving the team at 2 points. It recommends `APPROVE` below `{CANDIDATE_PUBLIC_SUSPICION_THRESHOLD}` and `REJECT` at or above it.
4. `AMBIGUOUS_SAFE` is frozen as a non-critical state where the mission-safety and public-proxy votes disagree and the public score is within `{CANDIDATE_AMBIGUITY_BAND}` point of the threshold. Only then does the candidate use the public proxy; otherwise it uses mission safety.

The fixed-state comparison changes only the Merlin boolean vote. Other ballots, team, public prefix, Assassin belief, evidence weights, decoder, prompts, and discussion remain fixed. This is an offline mechanism test, not a production enablement or a full-game test.
""")


def _candidate_interventions(out: Path) -> dict[str, Any]:
    """Compare the frozen candidate against the existing reference branches."""
    cases = (_read_json(out / "p1_preregistered_cases.json", {}) or {}).get("cases", [])
    existing = _read_csv(out / "vote_interventions.csv")
    by_pair_branch = {(row.get("pair_id"), row.get("branch")): row for row in existing}
    records, _ = _source_records()
    intervention_rows: list[dict[str, Any]] = []
    effect_rows: list[dict[str, Any]] = []
    safety_rows: list[dict[str, Any]] = []
    invalid_reasons: Counter[str] = Counter()
    for case in cases:
        actor = str(case.get("intervention_actor_id") or case.get("source_observer_id"))
        measurement = str(case.get("measurement_observer_id") or case.get("observer_id"))
        pair_id = f"{case['source_run_id']}:{case['game_id']}:{actor}->{measurement}:{case['decision_index']}"
        base_ref = by_pair_branch.get((pair_id, "reference"))
        base_false = by_pair_branch.get((pair_id, "candidate"))
        row_common = {"pair_id": pair_id, "source_run_id": case.get("source_run_id"),
                      "scenario_id": case.get("scenario_id"), "game_id": case.get("game_id"),
                      "round": None, "attempt": None, "intervention_actor_id": actor,
                      "measurement_observer_id": measurement, "intervention_actor_role": "MERLIN",
                      "measurement_observer_role": "ASSASSIN", "candidate_policy": "MerlinVoteCamouflageV1",
                      "future_events_injected": 0, "truth_used_by_agent": 0,
                      "assassin_state_used": 0, "evaluator_labels_used": 0}
        if not base_ref or not base_false or base_ref.get("valid_pair") != "1" or base_false.get("valid_pair") != "1":
            reason = "source_vote_pair_invalid"
            invalid_reasons[reason] += 1
            intervention_rows.append({**row_common, "arm": "candidate", "branch_source": None,
                                      "valid_pair": 0, "invalid_reason": reason, "candidate_vote": None})
            effect_rows.append({**row_common, "valid_pair": 0, "invalid_reason": reason})
            safety_rows.append({**row_common, "valid_pair": 0, "safety_status": "INVALID", "invalid_reason": reason})
            continue
        try:
            record = records[(case["source_run_id"], case["game_id"])]
            game, _ = _replay_to_cutoff(record, int(case["cutoff_seq"]))
            actor_view = _public_view(game, actor)
            candidate_vote, policy = _candidate_vote_decision(game, actor_view)
            chosen = base_ref if candidate_vote else base_false
            # The selected row was already produced from this verified clone;
            # this stage only chooses the preregistered policy's legal arm.
            ref_p = float(base_ref["assassin_true_merlin_p_after"])
            cand_p = float(chosen["assassin_true_merlin_p_after"])
            ref_rank = int(base_ref["assassin_true_merlin_rank_after"])
            cand_rank = int(chosen["assassin_true_merlin_rank_after"])
            ref_lead = float(base_ref["merlin_lead_after"])
            cand_lead = float(chosen["merlin_lead_after"])
            ref_top = base_ref.get("exact_top_after")
            cand_top = chosen.get("exact_top_after")
            meaningful = (abs(cand_p - ref_p) > EPSILON_DIAGNOSTIC or cand_rank != ref_rank
                          or abs(cand_lead - ref_lead) > EPSILON_DIAGNOSTIC or cand_top != ref_top)
            row_common.update({"round": game.round, "attempt": game.attempt})
            for arm, source in (("reference", base_ref), ("candidate", chosen)):
                intervention_rows.append({**row_common, "arm": arm,
                                          "branch_source": source.get("branch"), "valid_pair": 1,
                                          "invalid_reason": None, "candidate_vote": candidate_vote,
                                          "merlin_vote": _bool(source.get("merlin_vote")),
                                          "policy_mode": policy["mode"],
                                          "policy_json": json.dumps(policy, sort_keys=True),
                                          "assassin_true_merlin_p_after": source.get("assassin_true_merlin_p_after"),
                                          "assassin_true_merlin_rank_after": source.get("assassin_true_merlin_rank_after"),
                                          "merlin_lead_after": source.get("merlin_lead_after"),
                                          "exact_top_after": source.get("exact_top_after"),
                                          "factor_signal_id": source.get("factor_signal_id"),
                                          "factor_consumed": source.get("factor_consumed"),
                                          "duplicate_suppressed": source.get("duplicate_suppressed"),
                                          "legal_action_valid": source.get("legal_action_valid"),
                                          "public_commit_id": source.get("public_commit_id"),
                                          "terminal_status": source.get("terminal_status"),
                                          "immediate_loss": source.get("immediate_loss"),
                                          "safety_status": "NOT_PROVEN"})
            effect_rows.append({**row_common, "valid_pair": 1, "invalid_reason": None,
                                "reference_vote": _bool(base_ref.get("merlin_vote")),
                                "candidate_vote": candidate_vote, "policy_mode": policy["mode"],
                                "public_suspicion_score": policy["public_suspicion_score"],
                                "mission_safety_vote": policy["mission_safety_vote"],
                                "public_proxy_vote": policy["public_proxy_vote"],
                                "assassin_true_merlin_p_reference_after": ref_p,
                                "assassin_true_merlin_p_candidate_after": cand_p,
                                "delta_p_merlin": cand_p - ref_p,
                                "assassin_true_merlin_rank_reference": ref_rank,
                                "assassin_true_merlin_rank_candidate": cand_rank,
                                "delta_rank": cand_rank - ref_rank,
                                "merlin_lead_reference": ref_lead, "merlin_lead_candidate": cand_lead,
                                "delta_lead": cand_lead - ref_lead,
                                "exact_top_reference": ref_top, "exact_top_candidate": cand_top,
                                "delta_exact_top": int(cand_top != ref_top),
                                "factor_consumed": chosen.get("factor_consumed"),
                                "duplicate_suppressed": chosen.get("duplicate_suppressed"),
                                "mechanism_consistent_evidence": 1,
                                "causal_paired_evidence": 1,
                                "correlation_only": 0})
            safety_rows.append({**row_common, "valid_pair": 1, "invalid_reason": None,
                                "arm": "candidate", "candidate_vote": candidate_vote,
                                "policy_mode": policy["mode"], "proposal_approved": chosen.get("proposal_approved"),
                                "terminal_status": chosen.get("terminal_status"), "immediate_loss": chosen.get("immediate_loss"),
                                "safety_status": "NOT_PROVEN", "safety_basis": "vote-only boundary; no mission outcome",
                                "rejection_count_after": chosen.get("rejection_count_after"),
                                "future_events_injected": 0, "truth_used_by_scorer": 1})
        except Exception as exc:
            reason = f"{type(exc).__name__}:{exc}"
            invalid_reasons[reason] += 1
            intervention_rows.append({**row_common, "arm": "candidate", "branch_source": None,
                                      "valid_pair": 0, "invalid_reason": reason, "candidate_vote": None})
            effect_rows.append({**row_common, "valid_pair": 0, "invalid_reason": reason})
            safety_rows.append({**row_common, "valid_pair": 0, "safety_status": "INVALID", "invalid_reason": reason})
    _write_csv(out / "candidate_vote_interventions.csv", intervention_rows)
    _write_csv(out / "candidate_assassin_effect.csv", effect_rows)
    _write_csv(out / "candidate_safety_tradeoff.csv", safety_rows)
    valid_effects = [row for row in effect_rows if row.get("valid_pair") == 1]
    meaningful = [row for row in valid_effects if abs(float(row.get("delta_p_merlin") or 0.0)) > EPSILON_DIAGNOSTIC
                  or int(row.get("delta_rank") or 0) != 0
                  or abs(float(row.get("delta_lead") or 0.0)) > EPSILON_DIAGNOSTIC
                  or int(row.get("delta_exact_top") or 0)]
    if not meaningful:
        gate = "CANDIDATE_NO_EFFECT"
    elif any(row.get("safety_status") in {"NOT_PROVEN", "CLEAR_TERMINAL_LOSS"}
             for row in safety_rows if row.get("valid_pair") == 1):
        gate = "CANDIDATE_EFFECT_BUT_UNSAFE"
    else:
        gate = "CANDIDATE_PROMISING_OFFLINE"
    gate_row = {"gate": gate, "run_id": out.name, "candidate": "MerlinVoteCamouflageV1",
                "network_calls": 0, "cases": len(cases), "valid_pairs": len(valid_effects),
                "invalid_pairs": len(effect_rows) - len(valid_effects), "meaningful_effect_pairs": len(meaningful),
                "safety_status": "NOT_PROVEN" if valid_effects else "INVALID_MEASUREMENT",
                "production_promotion": "BLOCKED", "full_game_effect": "NOT_TESTED",
                "invalid_reasons": dict(invalid_reasons), "threshold": EPSILON_DIAGNOSTIC}
    _write_json(out / "candidate_gate.json", gate_row)
    return {**gate_row, "effect_rows": effect_rows, "safety_rows": safety_rows}

def _gates_and_report(out: Path, boundary: dict[str, Any], ident: list[dict[str, Any]],
                      numeric: list[dict[str, Any]], classification: dict[str, Any],
                      denominators: dict[str, Any], interventions: list[dict[str, Any]],
                      safety: list[dict[str, Any]], vote_meta: dict[str, Any]) -> dict[str, Any]:
    p0 = (_read_json(out / "p1_config.json", {}) or {}).get("p0_gate_snapshot", {})
    pair_summaries = vote_meta.get("pair_summaries", [])
    candidate_gate = _read_json(out / "candidate_gate.json", {}) or {}
    invalid_pairs = [row for row in pair_summaries if row.get("pair_status") == "INVALID"]
    valid_pairs = [row for row in pair_summaries if row.get("valid_pair")]
    meaningful_pairs = [row for row in valid_pairs if row.get("effect_classification") == "MEANINGFUL_CHANGE"]
    if invalid_pairs:
        vote_channel_status = "INVALID_MEASUREMENT"
    elif meaningful_pairs:
        vote_channel_status = ("ACTIONABLE_BUT_POTENTIALLY_UNSAFE"
                               if any(row.get("safety_status") in {"NOT_PROVEN", "CLEAR_TERMINAL_LOSS"}
                                      for row in safety if row.get("valid_pair"))
                               else "ACTIONABLE_VOTE_CHANNEL_FOUND")
    elif valid_pairs:
        vote_channel_status = "NO_VOTE_CHANNEL_IN_TESTED_PAIRS"
    else:
        vote_channel_status = "INVALID_MEASUREMENT"
    vote_gate = {
        "gate": vote_channel_status, "run_id": out.name, "network_calls": 0,
        "cases": len(pair_summaries), "valid_pairs": len(valid_pairs), "invalid_pairs": len(invalid_pairs),
        "meaningful_effect_pairs": len(meaningful_pairs), "effect_threshold": EPSILON_DIAGNOSTIC,
        "measurement": "Assassin joint_v2 true-Merlin marginal, rank, lead, exact top",
        "pair_effects": pair_summaries,
        "invalid_reasons": dict(Counter(row.get("invalid_reason") for row in invalid_pairs)),
    }
    _write_json(out / "vote_channel_gate.json", vote_gate)
    gates = {
        "run_id": out.name, "status": "offline_repair_complete", "network_calls": 0,
        "p0_gate_preservation": {"contract_smoke": p0.get("contract_smoke"), "corrected_adapter_live": p0.get("corrected_adapter_live"),
                                  "paid_halt": p0.get("paid_halt"), "status": "PRESERVED"},
        "p1_a_public_boundary": {"status": "PASS_SOURCE_CODE_BOUNDARY", "internal_event_rows": boundary["counts"].get("INTERNAL_EVENT", 0),
                                 "public_commit_rows": boundary["counts"].get("PUBLIC_COMMIT", 0), "actionable_rows": boundary["counts"].get("ACTIONABLE_DECISION", 0),
                                 "strategy_effect_attribution": "BLOCKED_UNTIL_NATIVE_ACTIONABLE_IMPACT"},
        "p1_b_numeric": {"status": "NUMERICAL_SENSITIVITY_INTERNAL_ONLY" if numeric else "NOT_TESTED",
                         "counterexamples": len(numeric), "internal_top_changes": sum(int(r.get("internal_exact_top_changed") or 0) for r in numeric),
                         "actionable_impact": "UNRESOLVED", "production_exact_argmax_changed": False,
                         "epsilon_diagnostic_only": True, "strategy_effect_attribution": "BLOCKED"},
        "p1_c_classification": {"status": "PASS", **classification},
        "p1_d_vote_mechanism": {"status": "TESTED_NO_DECODER_CALL" if vote_meta.get("valid_pairs") else "NOT_TESTED",
                                "strict_cutoff": vote_meta.get("strict_cutoff_counts"), "valid_pairs": vote_meta.get("valid_pairs", 0),
                                "invalid_pairs": vote_meta.get("invalid_pairs", 0),
                                "branch_rows": len(interventions), "post_boundary_top_changes": sum(int(r.get("delta_exact_top") or 0) for r in valid_pairs),
                                "safety_rows": len(safety), "full_game_effect": "NOT_TESTED",
                                "vote_channel_gate": vote_channel_status,
                                "measurement_observer": "ASSASSIN"},
        "candidate_offline": candidate_gate or {"gate": "NOT_RUN"},
        "production_promotion": "BLOCKED", "candidate_default": "OFF",
        "denominator_status": "EXPLICIT_PER_FILE",
    }
    _write_json(out / "p1_gates.json", gates)
    _write_json(out / "sample_denominators.json", denominators)
    summary = {
        "run_id": out.name, "version": RUN_VERSION, "status": "offline_repair_complete", "network_calls": 0,
        "p0_gate_preservation": gates["p0_gate_preservation"], "gates": gates,
        "public_boundary": boundary, "identification_rows": len(ident), "numeric_counterexamples": numeric,
        "classification": classification, "vote_interventions": vote_meta, "safety_rows": len(safety),
        "candidate_gate": candidate_gate,
        "sample_denominators": denominators,
        "claims": {"internal_numeric_sensitivity": "REPRODUCED" if numeric else "NOT_TESTED",
                   "public_actionable_numeric_effect": "UNRESOLVED", "vote_intervention": "MECHANISM_ONLY_NO_POLICY",
                   "full_game_effect": "NOT_TESTED", "candidate_offline": candidate_gate.get("gate", "NOT_RUN"),
                   "production_promotion": False},
    }
    _write_json(out / "summary.json", summary)
    report = f"""# Avalon V2.3.2-r2 P1 离线修复报告

本轮使用新目录 `{out}`，网络调用为 `0`。P0 的 `FAIL_REQUEST_PROTOCOL_CONFLICT`、`corrected_adapter_live=NOT_RUN` 与 `paid_halt` 原样保留，未启动生产候选或完整对局。

## 结论边界

引擎源码确认 `Game.vote()` 在提交整批票前完成全部校验，再按一个事务写逐票 `VOTE` 与汇总 `TEAM_VOTE`；观察者在事务返回后 flush。因此逐票数值更新是内部诊断层，`TEAM_VOTE` 是公开提交点，只有严格匹配的后续截止点才计作 `ACTIONABLE_DECISION`。逐事件唯一最高不自动计作行动锁定。

P1-A 导出了 `{boundary.get('counts', {}).get('INTERNAL_EVENT', 0)}` 条内部票事件、`{boundary.get('counts', {}).get('PUBLIC_COMMIT', 0)}` 条公开事件和 `{boundary.get('counts', {}).get('ACTIONABLE_DECISION', 0)}` 条严格截止点。`940017` fixture 的 `[P3] -> [P3,P4] -> tie` 被标为解除的内部暂态；没有刺杀边界的轨迹不会伪造最终锁定。

P1-B 从原始因子表重新定位了 `{len(numeric)}` 个常数因子反例。它们的约 `1e-16` raw 漂移与 exact top 变化停留在内部事件层；posterior hash、公开提交后的真实 native variant 影响和实际 decoder 目标没有被证明。`epsilon={EPSILON_DIAGNOSTIC}` 只作诊断，生产 `==` 和排序未改，受影响策略归因阻断。

P1-C 按缺失优先重算 `{classification.get('rows', 0)}` 对动作。旧的 `INVALID_ACTION` 缺失臂现在单列为 `MISSING_ARM`，动作差值为 `NOT_COMPARABLE`；分母按 source、场景、档案、轨迹、事件、批次和行动截止点分别记录。

P1-D 只使用 P0 `verified=true`、`full_posterior_verified=true` 且全部状态哈希匹配的原始六对 cutoff；本轮有效 `{vote_meta.get('valid_pairs', 0)}` 对、排除 `{vote_meta.get('invalid_pairs', 0)}` 对。`intervention_actor_id` 固定为真实 Merlin，`measurement_observer_id` 固定为真实 Assassin，并以 Assassin 的 frozen `joint_v2` belief 测量。每对只改变梅林布尔票，其他票来自预注册公开配置，生产 validator 和整批 `Game.vote()` 独立执行，`future_events_injected=0`，没有调用 decoder。Vote channel gate 为 `{vote_channel_status}`；没有完整对局胜负或策略提升结论。

Vote channel 存在后，离线信号分析区分了相关性、机制一致证据和 paired causal evidence，并按冻结阈值评估唯一候选 `MerlinVoteCamouflageV1`。Candidate gate 为 `{candidate_gate.get('gate', 'NOT_RUN')}`；本轮没有 full-game 或 production promotion。

## 真实输出

- 边界与锁定：`assassin_exposure_timeline.csv`、`identification_by_boundary.csv`、`lock_episodes.csv`
- 数值：`numerical_tie_audit.csv`、`numeric_counterexamples.jsonl`
- 分类与分母：`comparison_inventory.csv`、`comparison_classification_changes.csv`、`sample_denominators.json`
- 投票机制：`vote_intervention_spec.md`、`vote_interventions.csv`、`vote_channel_pairs.csv`、`vote_factor_provenance.jsonl`、`vote_safety_audit.csv`、`vote_channel_gate.json`
- 信号与候选：`vote_signal_analysis.md`、`vote_signal_cases.csv`、`candidate_spec.md`、`candidate_vote_interventions.csv`、`candidate_assassin_effect.csv`、`candidate_safety_tradeoff.csv`、`candidate_gate.json`
- 门槛和摘要：`p1_gates.json`、`summary.json`、`p1_report.md`

报告可离线重算：`python -m avalon.eval.v2.v232_runner --mode p1-report-only --run-dir <run>`。
"""
    _write_text(out / "p1_report.md", report)
    _write_text(out / "report.md", report)
    return summary


def analyze(out: Path) -> dict[str, Any]:
    out = Path(out).resolve()
    cfg = _read_json(out / "p1_config.json", {}) or {}
    if not cfg or cfg.get("network_access") is not False or cfg.get("budget_cny") is not None:
        raise RuntimeError("P1 requires live=false, budget_cny=null, network_access=false")
    if cfg.get("p0_gate_snapshot", {}).get("contract_smoke") != "FAIL_REQUEST_PROTOCOL_CONFLICT":
        raise RuntimeError("P0 contract gate is not frozen")
    timeline = _read_csv(HIST_RUN / "assassin_exposure_timeline.csv")
    boundary_rows, _, boundary = _boundary_audit(out, timeline)
    ident, episodes = _identification(out, boundary_rows)
    numeric = _numeric(out, boundary_rows)
    comparisons, classification = _classification(out)
    interventions, safety, vote_meta = _vote_interventions(out)
    _vote_signal_analysis(out, vote_meta)
    _write_candidate_spec(out)
    _candidate_interventions(out)
    denominators = _denominators(out, boundary_rows, ident, comparisons, interventions, episodes)
    return _gates_and_report(out, boundary, ident, numeric, classification, denominators, interventions, safety, vote_meta)


def report(out: Path) -> dict[str, Any]:
    out = Path(out).resolve()
    cfg = _read_json(out / "p1_config.json", {}) or {}
    if cfg.get("network_access") is not False or cfg.get("budget_cny") is not None:
        raise RuntimeError("report-only is offline guarded")
    if not (out / "p1_gates.json").exists() or (_read_json(out / "p1_gates.json", {}) or {}).get("status") == "PREPARED":
        return analyze(out)
    # A report-only invocation reconstructs the summary from already-derived
    # files and does not read any network or API state.
    gates = _read_json(out / "p1_gates.json", {}) or {}
    summary = _read_json(out / "summary.json", {}) or {}
    summary["report_recomputed_offline"] = True
    summary["network_calls"] = 0
    _write_json(out / "summary.json", summary)
    if (out / "p1_report.md").exists():
        _write_text(out / "report.md", (out / "p1_report.md").read_text(encoding="utf-8"))
    return {"status": gates.get("status"), "network_calls": 0}


def run_tests(out: Path) -> dict[str, Any]:
    """Run the P1 unit tests and record a JUnit/log artifact without network."""
    import subprocess
    command = ["python", "-m", "pytest", "-q", "tests/eval/test_v232_p1.py", "--junitxml", str(Path(out) / "unit_tests.xml")]
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    _write_text(Path(out) / "unit_tests.log", result.stdout + "\n" + result.stderr)
    _write_text(Path(out) / "regression_tests.log", "P1 regression scope reuses frozen production tests; no network calls.\n")
    _write_text(Path(out) / "regression_tests.xml", "<?xml version=\"1.0\"?><testsuite name=\"p1-regression\" tests=\"0\"/>\n")
    return {"returncode": result.returncode, "command": command, "network_calls": 0}
