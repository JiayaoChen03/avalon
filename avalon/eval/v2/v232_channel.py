"""Joint Belief v2.3.2 offline attribution and exact-tie diagnostics.

The module is intentionally an evaluation-only layer.  It replays the frozen
public event streams through the production ``joint_v1``/``joint_v2`` adapters,
records every numeric factor and decoder input, and keeps scorer-only truth in
separate columns.  It never changes production tie equality, evidence weights,
or a live game trajectory.
"""

from __future__ import annotations

import ast
import csv
from copy import deepcopy
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable

from avalon.chronicle import PUBLIC_KINDS, context_record
from avalon.eval.simulation import canonical, digest, validate_replay
from avalon.eval.v2.adapters import make_version
from avalon.eval.v2.v21_contract import decode_menu, legal_menu
from avalon.evidence import Observation, EvidenceType


EPSILON_DIAGNOSTIC = 1e-10
PUBLIC_TEXT_FIELDS = {"public_writing", "statement"}
PRODUCTION_ASSASSIN_MAPPING = "existing_native_merlin_argmax_with_model_tiebreak"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    path = Path(path)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def write_json(path: Path, value: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fields: list[str] | None = None) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = list(rows)
    if fields is None:
        fields = list(rows[0]) if rows else []
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def parse_action(value: Any) -> dict[str, Any] | None:
    if value in (None, "", "null", "None"):
        return None
    if isinstance(value, dict):
        return deepcopy(value)
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        parsed = ast.literal_eval(value)
    return deepcopy(parsed) if isinstance(parsed, dict) else None


def public_events(record: dict[str, Any]) -> list[dict[str, Any]]:
    return sorted((context_record(e) for e in record.get("events", [])
                   if e.get("kind") in PUBLIC_KINDS), key=lambda e: (e.get("seq", 0), e.get("record_id", "")))


def truth_roles(record: dict[str, Any]) -> dict[str, str]:
    return {p["id"]: p["role"] for p in record.get("players", [])}


def record_identity(record: dict[str, Any]) -> tuple[str, str, str]:
    return (str(record.get("run_id") or record.get("source_run_id") or ""),
            str(record.get("scenario_id") or ""), str(record.get("game_id") or ""))


def _posterior_hash(observer) -> str:
    try:
        return observer.snapshot()["posterior_hash"]
    except Exception:
        return digest([[list(w), round(p, 15)] for w, p in sorted(observer.distribution().items())])


def _distribution(observer) -> dict:
    return observer.distribution()


def _stats(observer, legal_targets: list[str]) -> dict[str, Any]:
    marginals = observer.marginals()
    values = {p: float(marginals.get(p, {}).get("merlin", 0.0)) for p in legal_targets}
    top_value = max(values.values(), default=None)
    top = sorted(p for p, value in values.items() if top_value is not None and value == top_value)
    near = sorted(p for p, value in values.items()
                  if top_value is not None and top_value - value <= EPSILON_DIAGNOSTIC)
    lead = None
    if top_value is not None:
        second = sorted(values.values(), reverse=True)[1] if len(values) > 1 else None
        lead = top_value - second if second is not None else None
    return {"marginals": marginals, "values": values, "native_top": top,
            "near_top": near, "top_value": top_value, "top_gap": lead,
            "posterior_hash": _posterior_hash(observer)}


def _log_odds(p: float) -> float:
    p = min(max(float(p), 0.0), 1.0)
    tiny = 1e-300
    return math.log(max(p, tiny)) - math.log(max(1.0 - p, tiny))


def _event_observation(event: dict[str, Any], variant: str = "joint_v2") -> Observation | None:
    # joint_v1 intentionally retains its frozen evidence module, which has a
    # distinct Observation class.  Using that class here is part of replay
    # equivalence; it is not a production compatibility shim.
    if variant == "joint_v1":
        from avalon.eval.frozen_v1.evidence import Observation as FrozenObservation
        return FrozenObservation.from_event(event)
    return Observation.from_event(event)


def _factor_values(observer, hypotheses, evidence) -> tuple[list[float], dict[str, float | None]]:
    if not getattr(observer, "engine", None):
        return [], {}
    model = observer.engine.likelihood_model
    values = [float(model.evaluate(h, evidence)) for h in hypotheses]
    live = [(h, value) for h, value in zip(hypotheses, values) if h.probability > 0]
    by_merlin: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for hypothesis, value in live:
        for pid, role in hypothesis.roles.items():
            if role == "MERLIN":
                by_merlin[pid].append((float(hypothesis.probability), value))
    conditional = {}
    for pid, pairs in by_merlin.items():
        denom = math.fsum(weight for weight, _ in pairs)
        conditional[pid] = (math.fsum(weight * value for weight, value in pairs) / denom
                            if denom else None)
    return values, conditional


def _serial_evidence(item) -> dict[str, Any]:
    return {"origin_event_id": item.origin_event_id, "signal_id": item.signal_id,
            "source_agent": item.source_agent, "target_agents": list(item.target_agents),
            "evidence_type": item.evidence_type.value, "feature": item.feature,
            "direction": item.direction, "strength": item.strength,
            "metadata": deepcopy(item.metadata)}


def _factor_family(feature: str | None, evidence_type: str | None) -> str:
    if feature is None:
        return "none"
    if evidence_type == EvidenceType.HARD.value:
        return "hard"
    if feature.startswith("mission"):
        return "mission_soft"
    if feature in {"defense", "opposition", "team_proposal", "team_vote", "exile_vote"}:
        return "social"
    return feature


def _legal_targets(view: dict[str, Any], observer) -> list[str]:
    known = set(view.get("known_evil", []))
    return [p for p in observer.ids if p != observer.pid and p not in known]


def replay_record(record: dict[str, Any], *, variant: str = "joint_v2",
                  source_run_id: str = "", cohort_role: str = "diagnostic") -> dict[str, Any]:
    """Replay one record, returning audit rows without exposing truth to the observer."""
    game, truth = validate_replay(record)
    assassin = next((p for p, role in truth.items() if role == "ASSASSIN"), None)
    if assassin is None:
        raise ValueError("record has no Assassin")
    initial_view = game.view(assassin)
    observer = make_version(variant, deepcopy(initial_view))
    legal = _legal_targets(initial_view, observer)
    timeline: list[dict[str, Any]] = []
    factors: list[dict[str, Any]] = []
    before = _stats(observer, legal)
    for event in public_events(record):
        observation = _event_observation(event, variant)
        if observation is None:
            continue
        before_dist = _distribution(observer)
        before_stats = _stats(observer, legal)
        prior_signals = set(getattr(getattr(observer, "engine", None), "_applied_signals", set()))
        prior_observed = set(getattr(getattr(observer, "engine", None), "_observed_ids", set()))
        extracted = []
        if getattr(observer, "engine", None) and variant != "joint_v1":
            extracted = deepcopy(observer.engine.extractor).extract(observation)
        value_rows = []
        all_values: list[float] = []
        for item in extracted:
            values, conditional = _factor_values(observer, observer.engine.beliefs.hypotheses, item)
            all_values.extend(values)
            live_values = [v for h, v in zip(observer.engine.beliefs.hypotheses, values) if h.probability > 0]
            row = {"run_id": str(record.get("run_id") or source_run_id),
                   "source_run_id": source_run_id, "cohort_role": cohort_role,
                   "scenario_id": record.get("scenario_id"), "scenario_family": record.get("profile"),
                   "game_id": record.get("game_id"), "observer_id": assassin,
                   "variant": variant, "event_id": observation.event_id,
                   "source_signal_id": item.signal_id, "event_kind": event.get("kind"),
                   "actor": event.get("actor"), "round": event.get("round"),
                   "attempt": event.get("attempt"), "phase": event.get("discussion_stage") or event.get("phase"),
                   "factor_origin_module": "avalon.evidence.EvidenceExtractor",
                   "factor_name": item.feature, "factor_family": _factor_family(item.feature, item.evidence_type.value),
                   "evidence_type": item.evidence_type.value, "evidence": _serial_evidence(item),
                   "likelihood_min": min(live_values) if live_values else None,
                   "likelihood_max": max(live_values) if live_values else None,
                   "constant_on_live_support": int(bool(live_values) and all(v == live_values[0] for v in live_values)),
                   "live_support_count": len(live_values), "hypothesis_count": len(values),
                   "conditional_likelihood_by_merlin": conditional,
                   "likelihood_values": sorted(set(round(v, 17) for v in live_values))}
            value_rows.append(row)
        observer.observe(deepcopy(event))
        after_stats = _stats(observer, legal)
        after_dist = _distribution(observer)
        after_signals = set(getattr(getattr(observer, "engine", None), "_applied_signals", set()))
        duplicate = False
        # A second delivery is an offline idempotence probe.  It is not added to
        # the source event stream and is checked for an unchanged posterior.
        before_duplicate_hash = _posterior_hash(observer)
        observer.observe(deepcopy(event))
        duplicate = (observation.event_id in prior_observed or
                     _posterior_hash(observer) == before_duplicate_hash)
        factor_consumed = bool(after_signals - prior_signals)
        for row in value_rows:
            row.update({"factor_consumed": int(factor_consumed), "duplicate_suppressed": int(duplicate),
                        "posterior_before_hash": before_stats["posterior_hash"],
                        "posterior_after_hash": after_stats["posterior_hash"],
                        "posterior_changed": int(before_stats["posterior_hash"] != after_stats["posterior_hash"])})
            factors.append(row)
        before_values = before_stats["values"]; after_values = after_stats["values"]
        odds = {p: _log_odds(after_values.get(p, 0.0)) - _log_odds(before_values.get(p, 0.0))
                for p in legal}
        max_delta = max((abs(after_dist.get(w, 0.0) - before_dist.get(w, 0.0)) for w in
                         set(before_dist) | set(after_dist)), default=0.0)
        timeline.append({"run_id": str(record.get("run_id") or source_run_id),
                         "source_run_id": source_run_id, "cohort_role": cohort_role,
                         "scenario_id": record.get("scenario_id"), "scenario_family": record.get("profile"),
                         "game_id": record.get("game_id"), "observer_id": assassin, "variant": variant,
                         "event_id": observation.event_id, "source_signal_id": ";".join(i.signal_id for i in extracted),
                         "event_kind": event.get("kind"), "actor": event.get("actor"),
                         "round": event.get("round"), "attempt": event.get("attempt"),
                         "phase": event.get("discussion_stage") or event.get("phase"),
                         "legal_observation_hash": digest(event),
                         "public_prefix_hash": digest(public_events(record)[:public_events(record).index(event) + 1]),
                         "factor_origin_module": "avalon.evidence.EvidenceExtractor" if extracted else None,
                         "factor_name": ";".join(i.feature for i in extracted),
                         "factor_live_support_min": min(all_values) if all_values else None,
                         "factor_live_support_max": max(all_values) if all_values else None,
                         "constant_on_live_support": int(bool(all_values) and all(v == all_values[0] for v in all_values)),
                         "posterior_before_hash": before_stats["posterior_hash"],
                         "posterior_after_hash": after_stats["posterior_hash"],
                         "max_abs_raw_delta": max_delta,
                         "merlin_marginals_before": json.dumps(before_values, ensure_ascii=False, sort_keys=True),
                         "merlin_marginals_after": json.dumps(after_values, ensure_ascii=False, sort_keys=True),
                         "native_exact_top_before": json.dumps(before_stats["native_top"], ensure_ascii=False),
                         "native_exact_top_after": json.dumps(after_stats["native_top"], ensure_ascii=False),
                         "near_top_diagnostic_before": json.dumps(before_stats["near_top"], ensure_ascii=False),
                         "near_top_diagnostic_after": json.dumps(after_stats["near_top"], ensure_ascii=False),
                         "log_odds_delta_by_candidate": json.dumps(odds, ensure_ascii=False, sort_keys=True),
                         "factor_consumed": int(factor_consumed), "duplicate_suppressed": int(duplicate),
                         "event_observed": 1, "true_merlin_scorer": next((p for p, r in truth.items() if r == "MERLIN"), None),
                         "true_merlin": next((p for p, r in truth.items() if r == "MERLIN"), None)})
        before = after_stats
    return {"timeline": timeline, "factors": factors, "truth": truth, "assassin": assassin,
            "final": _stats(observer, legal), "events": len(timeline), "record": record}


def first_identification(result: dict[str, Any]) -> dict[str, Any]:
    rows = result["timeline"]
    truth = result["truth"]
    true_merlin = next((p for p, r in truth.items() if r == "MERLIN"), None)
    initial_top = json.loads(rows[0]["native_exact_top_before"]) if rows else []
    initial_unique_true = int(initial_top == [true_merlin])
    first_unique = next((r for r in rows if json.loads(r["native_exact_top_after"]) == [true_merlin]), None)
    first_meaningful = next((r for r in rows if true_merlin in json.loads(r["native_exact_top_after"])
                             and float(r.get("max_abs_raw_delta") or 0) >= 0
                             and (len(json.loads(r["native_exact_top_after"])) == 1)
                             and float((json.loads(r["merlin_marginals_after"]).get(true_merlin, 0.0)) -
                                       max((v for p, v in json.loads(r["merlin_marginals_after"]).items() if p != true_merlin), default=0.0)) > EPSILON_DIAGNOSTIC), None)
    # A sustained lock is one that is unique for the rest of this recorded
    # trajectory.  This deliberately distinguishes a transient correct guess.
    sustained = None
    for idx, row in enumerate(rows):
        if json.loads(row["native_exact_top_after"]) == [true_merlin] and all(
                json.loads(later["native_exact_top_after"]) == [true_merlin] for later in rows[idx:]):
            sustained = row
            break
    wrong = [r for r in rows if len(json.loads(r["native_exact_top_after"])) == 1 and
             json.loads(r["native_exact_top_after"])[0] != true_merlin]
    floating = [r for r in rows if len(json.loads(r["native_exact_top_after"])) == 1 and
                float(json.loads(r["merlin_marginals_after"]).get(true_merlin, 0.0)) -
                max((v for p, v in json.loads(r["merlin_marginals_after"]).items() if p != true_merlin), default=0.0) <= EPSILON_DIAGNOSTIC]
    def select(row):
        if not row: return None
        fs = row.get("factor_name") or None
        return {"event_id": row.get("event_id"), "factor_name": fs,
                "posterior_before_hash": row.get("posterior_before_hash"),
                "posterior_after_hash": row.get("posterior_after_hash"),
                "probability_before": (json.loads(row["merlin_marginals_before"]).get(true_merlin)
                                        if row.get("merlin_marginals_before") else None),
                "probability_after": (json.loads(row["merlin_marginals_after"]).get(true_merlin)
                                       if row.get("merlin_marginals_after") else None),
                "top_before": row.get("native_exact_top_before"), "top_after": row.get("native_exact_top_after")}
    return {"source_run_id": result["timeline"][0].get("source_run_id") if rows else None,
            "cohort_role": result["timeline"][0].get("cohort_role") if rows else None,
            "scenario_id": result["record"].get("scenario_id"), "game_id": result["record"].get("game_id"),
            "observer_id": result["assassin"], "variant": result["timeline"][0].get("variant") if rows else None,
            "true_merlin": true_merlin, "initial_unique_top_true_merlin": initial_unique_true,
            "initial_top": json.dumps(initial_top), "first_unique_true_merlin": select(first_unique),
            "first_meaningful_nonfloating_separation": select(first_meaningful),
            "sustained_final_lock_start": select(sustained),
            "wrong_unique_lock_count": len(wrong), "floating_unique_lock_count": len(floating),
            "terminal_top": rows[-1].get("native_exact_top_after") if rows else None,
            "terminal_unique_true_merlin": int(bool(rows and json.loads(rows[-1]["native_exact_top_after"]) == [true_merlin]))}


def _clone_with_family(record, family: str):
    game, truth = validate_replay(record)
    assassin = next(p for p, r in truth.items() if r == "ASSASSIN")
    observer = make_version("joint_v2", deepcopy(game.view(assassin)))
    if family != "all":
        original = observer.engine._apply_evidence
        def filtered(observation_id, evidence, round_no):
            kept = []
            for item in evidence:
                item_family = _factor_family(item.feature, item.evidence_type.value)
                if family == "hard_only" and item.evidence_type == EvidenceType.HARD:
                    kept.append(item)
                elif family == "no_social" and item_family != "social":
                    kept.append(item)
                elif family == "no_mission_soft" and item_family != "mission_soft":
                    kept.append(item)
                elif family == "no_hard" and item.evidence_type != EvidenceType.HARD:
                    kept.append(item)
            return original(observation_id, kept, round_no)
        observer.engine._apply_evidence = filtered
    legal = _legal_targets(game.view(assassin), observer)
    for event in public_events(record):
        observer.observe(deepcopy(event))
    stats = _stats(observer, legal)
    return {"observer": assassin, "truth": truth, "stats": stats, "events": len(public_events(record)),
            "posterior_hash": stats["posterior_hash"]}


def factor_ablation(record: dict[str, Any], source_run_id: str, cohort_role: str) -> list[dict[str, Any]]:
    baseline = _clone_with_family(record, "all")
    rows = []
    for family in ("all", "hard_only", "no_social", "no_mission_soft"):
        run = _clone_with_family(record, family)
        true_merlin = next((p for p, r in run["truth"].items() if r == "MERLIN"), None)
        rows.append({"source_run_id": source_run_id, "cohort_role": cohort_role,
                     "scenario_id": record.get("scenario_id"), "game_id": record.get("game_id"),
                     "observer_id": run["observer"], "variant": "joint_v2", "disabled_family": family,
                     "events_replayed": run["events"], "posterior_hash_final": run["posterior_hash"],
                     "baseline_final_hash": baseline["posterior_hash"],
                     "final_hash_equal_baseline": int(run["posterior_hash"] == baseline["posterior_hash"]),
                     "true_merlin": true_merlin,
                     "true_merlin_probability_final": run["stats"]["marginals"].get(true_merlin, {}).get("merlin") if true_merlin else None,
                     "native_exact_top_final": json.dumps(run["stats"]["native_top"]),
                     "near_top_diagnostic_final": json.dumps(run["stats"]["near_top"]),
                     "scope": "same_public_prefix_fixed_trace; no action counterfactual"})
    return rows


def r7_assassin_requests(r7_root: Path) -> list[dict[str, Any]]:
    rows = []
    for request_path in sorted((Path(r7_root) / "requests").glob("*.request.json")):
        request = json.loads(request_path.read_text(encoding="utf-8"))
        if request.get("phase") != "assassination":
            continue
        response_path = request_path.with_name(request_path.name.replace(".request.json", ".response.json"))
        response = json.loads(response_path.read_text(encoding="utf-8")) if response_path.exists() else {}
        parsed = response.get("parsed_action") or {}
        params = parsed.get("parameters") if isinstance(parsed, dict) else {}
        ranking = params.get("assassin_rank") if isinstance(params, dict) else None
        rows.append({"request_path": str(request_path), "response_path": str(response_path),
                     "request": request, "response": response,
                     "submitted_ranking": ranking if isinstance(ranking, list) else None})
    return rows


def tie_audit(r7_root: Path, source_root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    rows, live_candidates, tie_snapshots = [], [], []
    requests = r7_assassin_requests(r7_root)
    for item in requests:
        request, response = item["request"], item["response"]
        context = request.get("context", {})
        game_id = request.get("game_id")
        record_path = Path(r7_root) / "active_replays" / (str(game_id).split(":")[-1] + ".json")
        record = json.loads(record_path.read_text(encoding="utf-8")) if record_path.exists() else {}
        d = next((d for d in record.get("decisions", []) if d.get("phase") == "assassination"), {})
        marg = (context.get("private_beliefs") or {}).get("marginals", {})
        legal = next((o.get("legal_targets", []) for o in context.get("action_menu", [])
                      if "assassin_rank" in (o.get("parameters") or {})), [])
        values = {p: float(marg.get(p, {}).get("merlin", 0.0)) for p in legal}
        top_value = max(values.values(), default=None)
        top = sorted(p for p, value in values.items() if top_value is not None and value == top_value)
        near = sorted(p for p, value in values.items() if top_value is not None and top_value - value <= EPSILON_DIAGNOSTIC)
        target = (response.get("normalized_action") or {}).get("target")
        tie_used = int(len(top) > 1 and target in top)
        row = {"dataset_role": "historical_r7_diagnostic", "source_run_id": request.get("run_id"),
               "scenario_id": request.get("scenario_id"), "game_id": game_id,
               "variant": request.get("variant"), "observer_id": request.get("observer_id"),
               "native_values": json.dumps(values, ensure_ascii=False, sort_keys=True),
               "native_exact_top_set": json.dumps(top, ensure_ascii=False), "native_exact_top_count": len(top),
               "near_top_diagnostic_set": json.dumps(near, ensure_ascii=False),
               "epsilon_diagnostic": EPSILON_DIAGNOSTIC,
               "max_gap": (top_value - sorted(values.values(), reverse=True)[1]
                           if top_value is not None and len(values) > 1 else None),
               "production_tie_rule": "exact Python == max; no tolerance",
               "production_tie_branch_used": tie_used,
               "submitted_assassin_ranking": json.dumps(item["submitted_ranking"], ensure_ascii=False) if item["submitted_ranking"] is not None else None,
               "submitted_assassin_ranking_length": len(item["submitted_ranking"]) if item["submitted_ranking"] is not None else None,
               "ranking_unavailable_reason": None if item["submitted_ranking"] is not None else "historical_response_missing_or_invalid",
               "decoder_mapping": response.get("policy_mapping") or PRODUCTION_ASSASSIN_MAPPING,
               "selected_target": target, "target_reason": "native_top_then_model_ranking" if tie_used else "native_unique_max",
               "true_merlin": None, "target_is_true_merlin": None,
               "public_text_in_model_input": int(any("public_writing" in e for e in context.get("game", {}).get("recent_events", []))),
               "input_hash": request.get("context_hash"), "response_hash": response.get("transport", {}).get("response_sha256")}
        rows.append(row)
        if tie_used and row["public_text_in_model_input"]:
            live_candidates.append({"snapshot_id": f"{request.get('scenario_id')}:{request.get('game_id')}:{request.get('variant')}",
                                    "request": request, "response": response, "record": record,
                                    "decision": d, "row": row})
    # A small v2.3 active diagnostic is retained in the same schema, but it
    # has no model ranking and is therefore not an eligible DeepSeek snapshot.
    for path in sorted((Path(source_root) / "active_replays").glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        truth = truth_roles(record)
        assassin = next((p for p, r in truth.items() if r == "ASSASSIN"), None)
        merlin = next((p for p, r in truth.items() if r == "MERLIN"), None)
        for d in record.get("decisions", []):
            if d.get("phase") != "assassination" or d.get("observer_id") != assassin:
                continue
            view = d.get("view", {}); legal = next((o.get("targets", []) for o in view.get("legal_options", [])
                                                    if o.get("kind") == "ASSASSINATE"), [])
            marg = d.get("marginals", {}); values = {p: float(marg.get(p, {}).get("merlin", 0.0)) for p in legal}
            top_value = max(values.values(), default=None); top = sorted(p for p, v in values.items() if v == top_value)
            rows.append({"dataset_role": "v23_active_diagnostic", "source_run_id": source_root.name,
                         "scenario_id": record.get("scenario_id"), "game_id": record.get("game_id"),
                         "variant": record.get("variant"), "observer_id": assassin,
                         "native_values": json.dumps(values, ensure_ascii=False, sort_keys=True),
                         "native_exact_top_set": json.dumps(top), "native_exact_top_count": len(top),
                         "near_top_diagnostic_set": json.dumps(top), "epsilon_diagnostic": EPSILON_DIAGNOSTIC,
                         "max_gap": None, "production_tie_rule": "exact Python == max; no tolerance",
                         "production_tie_branch_used": int(len(top) > 1), "submitted_assassin_ranking": None,
                         "submitted_assassin_ranking_length": None, "ranking_unavailable_reason": "controlled_population_direct_target",
                         "decoder_mapping": "controlled_population_direct_max; no model ranking recorded",
                         "selected_target": (d.get("action") or {}).get("target"),
                         "target_reason": "controlled_population", "true_merlin": merlin,
                         "target_is_true_merlin": int((d.get("action") or {}).get("target") == merlin),
                         "public_text_in_model_input": None, "input_hash": d.get("input_hash"), "response_hash": None})
    return rows, live_candidates, tie_snapshots


def text_ablate(value: Any) -> Any:
    """Remove only public free text from a model-input projection."""
    if isinstance(value, dict):
        return {k: text_ablate(v) for k, v in value.items() if k not in PUBLIC_TEXT_FIELDS}
    if isinstance(value, list):
        return [text_ablate(v) for v in value]
    return value


def inventory_v232(source_root: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from avalon.eval.v2.v231_channel import build_action_inventory, validate_recorded_action
    items, sources, plan = build_action_inventory(source_root)
    rows = []
    for item in items:
        ref, cand = item.get("reference_action"), item.get("candidate_action")
        ref_exists, cand_exists = ref is not None, cand is not None
        prefix_equal = bool(item.get("public_prefix_hash_reference") and
                           item.get("public_prefix_hash_reference") == item.get("public_prefix_hash_candidate"))
        view_equal = bool(item.get("reference_pre_state_hash") and
                          item.get("reference_pre_state_hash") == item.get("candidate_pre_state_hash"))
        semantic_changed = bool(item.get("semantic_action_changed")); text_changed = bool(item.get("public_text_changed"))
        only_resource = bool(item.get("resource_use_changed")) and not any(
            item.get(key) for key in ("card_changed", "target_changed", "citation_changed", "commitment_changed"))
        if not ref_exists or not cand_exists:
            action_delta = "NO_CHANGE" if not ref_exists and not cand_exists else "STRUCTURED_CHANGE"
        elif not semantic_changed and not text_changed:
            action_delta = "NO_CHANGE"
        elif not semantic_changed and text_changed:
            action_delta = "TEXT_ONLY"
        elif only_resource:
            action_delta = "RESOURCE_CHANGE"
        else:
            action_delta = "STRUCTURED_CHANGE"
        valid = item.get("reference_valid", 1) and item.get("candidate_valid", 1)
        status = "INVALID_ACTION" if not valid else ("MISSING_ARM" if not ref_exists or not cand_exists else
                "MATCHED_PREFIX" if prefix_equal and view_equal else "DIVERGED_PREFIX")
        rows.append({"scenario_id": item.get("scenario_id"), "source_game_id": item.get("source_game_id"),
                     "decision_id": item.get("decision_id"), "stage": item.get("stage"), "round": item.get("round"),
                     "action_delta": action_delta, "comparison_status": status,
                     "public_prefix_equal": int(prefix_equal), "mechanical_pre_state_equal": int(view_equal),
                     "observer_belief_pre_state_equal": int(item.get("reference_pre_state_hash") == item.get("candidate_pre_state_hash")),
                     "legal_view_equal": int(view_equal), "reference_exists": int(ref_exists), "candidate_exists": int(cand_exists),
                     "reference_valid": item.get("reference_valid"), "candidate_valid": item.get("candidate_valid"),
                     "card_changed": item.get("card_changed", 0), "target_changed": item.get("target_changed", 0),
                     "citation_changed": item.get("citation_changed", 0), "commitment_changed": item.get("commitment_changed", 0),
                     "resource_use_changed": item.get("resource_use_changed", 0), "text_changed": int(text_changed),
                     "reference_action": canonical(ref) if ref is not None else None,
                     "candidate_action": canonical(cand) if cand is not None else None,
                     "reference_pre_state_hash": item.get("reference_pre_state_hash"),
                     "candidate_pre_state_hash": item.get("candidate_pre_state_hash"),
                     "public_prefix_hash_reference": item.get("public_prefix_hash_reference"),
                     "public_prefix_hash_candidate": item.get("public_prefix_hash_candidate"),
                     "source_kind": item.get("source_kind")})
    return rows, {"items": items, "sources": sources, "plan": plan}


def tie_path(source_root: Path, r7_root: Path) -> list[dict[str, Any]]:
    rows, _, _ = tie_audit(r7_root, source_root)
    return rows


def snapshot_interventions(source_root: Path, inventory: list[dict[str, Any]], details: dict[str, Any]) -> list[dict[str, Any]]:
    from avalon.eval.v2.v231_channel import one_step_signal
    source_map = details["sources"]
    rows = []
    for item in inventory:
        if item["comparison_status"] != "MATCHED_PREFIX" or item["action_delta"] == "NO_CHANGE":
            continue
        source = source_map.get(item["decision_id"], {})
        branch_results = {}
        for branch, action_key in (("reference", "reference_action"), ("candidate", "candidate_action")):
            rec_dec = source.get(branch)
            if not rec_dec or not rec_dec[0] or not rec_dec[1] or item.get(action_key) is None:
                continue
            try:
                signal, factors = one_step_signal(rec_dec[0], rec_dec[1], parse_action(item[action_key]), branch,
                                                  action_category=item["action_delta"])
                branch_results[branch] = (signal, factors)
            except Exception as exc:
                branch_results[branch] = ({"error": f"{type(exc).__name__}: {exc}"}, [])
        if not branch_results:
            continue
        ref = branch_results.get("reference", ({}, []))[0]; cand = branch_results.get("candidate", ({}, []))[0]
        rows.append({"scenario_id": item["scenario_id"], "source_game_id": item["source_game_id"],
                     "decision_id": item["decision_id"], "comparison_status": item["comparison_status"],
                     "action_delta": item["action_delta"], "reference_action": item["reference_action"],
                     "candidate_action": item["candidate_action"], "reference_error": ref.get("error"),
                     "candidate_error": cand.get("error"), "reference_posterior_before": ref.get("posterior_hash_before"),
                     "candidate_posterior_before": cand.get("posterior_hash_before"),
                     "reference_posterior_after": ref.get("posterior_hash_after"),
                     "candidate_posterior_after": cand.get("posterior_hash_after"),
                     "reference_true_merlin_rank_after": ref.get("true_merlin_rank_after"),
                     "candidate_true_merlin_rank_after": cand.get("true_merlin_rank_after"),
                     "reference_top_after": ref.get("top_candidate_set_after"),
                     "candidate_top_after": cand.get("top_candidate_set_after"),
                     "reference_factor_names": json.dumps([f.get("factor_name") for f in branch_results.get("reference", ({}, []))[1]]),
                     "candidate_factor_names": json.dumps([f.get("factor_name") for f in branch_results.get("candidate", ({}, []))[1]]),
                     "future_events_injected": 0, "estimand": "one_step_public_action_prefix_only"})
    return rows
