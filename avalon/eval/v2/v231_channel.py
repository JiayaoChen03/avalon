"""Offline v2.3.1 audit of the Merlin action -> Assassin signal path.

This module deliberately does not add a policy or a belief factor.  It reuses
the production legal validator, ``Observation`` conversion, ``EvidenceExtractor``
and ``joint_v2`` engine on detached one-step belief states.  Role labels and
the selected Assassin seat are only used by the offline scorer.
"""

from __future__ import annotations

import ast
import csv
from copy import deepcopy
from collections import defaultdict
import json
from pathlib import Path
from typing import Any

from avalon.chronicle import EVIDENCE_KINDS, PUBLIC_KINDS, context_record
from avalon.eval.simulation import canonical, digest, validate_replay
from avalon.eval.v2.adapters import make_version
from avalon.eval.v2.v21_contract import validate_legal_action
from avalon.evidence import Observation


SOCIAL_KINDS = {"SOCIAL", "COMMITTED_SOCIAL", "RESPOND", "REACT"}
PUBLIC_TEXT_FIELDS = ("public_writing", "statement", "rationale")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()
            if line.strip()]


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fields is None:
        fields = list(rows[0]) if rows else []
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def parse_action(value: Any) -> dict[str, Any] | None:
    """Read the CSV representation without changing action semantics."""
    if value in (None, "", "null", "None"):
        return None
    if isinstance(value, dict):
        return deepcopy(value)
    if not isinstance(value, str):
        raise ValueError("action must be a mapping or a serialized mapping")
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        parsed = ast.literal_eval(value)
    if not isinstance(parsed, dict):
        raise ValueError("serialized action must be an object")
    return parsed


def action_kind(action: dict[str, Any] | None) -> str | None:
    if not action:
        return None
    if "team" in action:
        return "TEAM"
    return action.get("kind")


def _social(action: dict[str, Any] | None) -> dict[str, Any]:
    if not action:
        return {}
    return action.get("social", {}) if isinstance(action.get("social", {}), dict) else {}


def _field(action: dict[str, Any] | None, name: str) -> Any:
    if not action:
        return None
    if name in action:
        return action[name]
    return _social(action).get(name)


def _sorted_team(value: Any) -> Any:
    return sorted(value) if isinstance(value, list) else value


def action_projection(action: dict[str, Any] | None) -> dict[str, Any] | None:
    """Projection used only for equality; all game-semantic fields remain."""
    if action is None:
        return None
    return {
        "kind": action_kind(action),
        "card": _field(action, "card"),
        "target": _field(action, "target"),
        "reason": _field(action, "reason"),
        "citations": _field(action, "citations"),
        "team": _sorted_team(action.get("team")),
        "approve": action.get("approve"),
        "strong": action.get("strong"),
        "choice": action.get("choice"),
        "evidence": action.get("evidence"),
        "removed": action.get("removed"),
        "added": action.get("added"),
        "commitment": bool(action.get("committed", False)) or action_kind(action) == "COMMITTED_SOCIAL",
    }


def _text_projection(action: dict[str, Any] | None) -> dict[str, Any]:
    social = _social(action)
    return {name: social.get(name, action.get(name) if action else None)
            for name in PUBLIC_TEXT_FIELDS}


def _event_projection(action: dict[str, Any] | None) -> dict[str, Any] | None:
    if action is None:
        return None
    event = action_to_event(action, {"observer_id": "MERLIN", "round": 1, "attempt": 1}, 1)
    return context_record(event)


def diff_actions(reference: dict[str, Any] | None, candidate: dict[str, Any] | None,
                 *, pre_state_equal: bool = True,
                 candidate_context_present: bool = False) -> dict[str, Any]:
    """Field-by-field inventory.  Team order is the only presentation normalization."""
    ref_struct = action_projection(reference)
    cand_struct = action_projection(candidate)
    ref_text, cand_text = _text_projection(reference), _text_projection(candidate)
    public_text_changed = ref_text != cand_text
    card_changed = _field(reference, "card") != _field(candidate, "card")
    target_changed = _field(reference, "target") != _field(candidate, "target")
    citation_changed = _field(reference, "citations") != _field(candidate, "citations")
    commitment_changed = bool(ref_struct and ref_struct["commitment"]) != bool(cand_struct and cand_struct["commitment"])
    resource_use_changed = (action_kind(reference) != action_kind(candidate)
                            or (reference or {}).get("strong") != (candidate or {}).get("strong"))
    semantic_action_changed = ref_struct != cand_struct
    event_changed = _event_projection(reference) != _event_projection(candidate)
    if not semantic_action_changed and not public_text_changed and pre_state_equal:
        category = "NO_CHANGE"
    elif not semantic_action_changed and public_text_changed and pre_state_equal:
        category = "TEXT_ONLY"
    elif not pre_state_equal or resource_use_changed:
        category = "MECHANICAL_CHANGE"
    else:
        category = "STRUCTURED_ACTION_CHANGE"
    return {
        "reference_action": canonical(reference) if reference is not None else None,
        "candidate_action": canonical(candidate) if candidate is not None else None,
        "public_text_changed": int(public_text_changed),
        "card_changed": int(card_changed),
        "target_changed": int(target_changed),
        "citation_changed": int(citation_changed),
        "commitment_changed": int(commitment_changed),
        "resource_use_changed": int(resource_use_changed),
        "semantic_action_changed": int(semantic_action_changed),
        "public_event_changed": int(event_changed),
        "candidate_context_present": int(candidate_context_present),
        "action_category": category,
        "mechanical_state_diverged": int(not pre_state_equal),
    }


def _full_view(decision: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    """Restore public evidence that compact active archives omit from the view."""
    view = deepcopy(decision.get("view", {}))
    public = [context_record(e) for e in record.get("events", [])
              if e.get("kind") in PUBLIC_KINDS and e.get("seq", 0) <= decision.get("after_seq", 0)]
    view.setdefault("recent_events", public[-20:])
    view.setdefault("focused_events", [])
    view["legal_public_history"] = [e for e in public if e.get("kind") in EVIDENCE_KINDS]
    return view


def validate_recorded_action(action: dict[str, Any] | None, decision: dict[str, Any],
                             record: dict[str, Any]) -> tuple[bool, str | None]:
    if action is None:
        return False, "missing_action"
    try:
        validate_legal_action(action, _full_view(decision, record))
    except Exception as exc:  # The audit records defects instead of repairing them.
        return False, f"{type(exc).__name__}: {exc}"
    return True, None


def action_to_event(action: dict[str, Any], decision: dict[str, Any], seq: int) -> dict[str, Any]:
    """Make only the immediate public event; no future trajectory is copied."""
    actor = decision.get("observer_id")
    round_no, attempt = decision.get("round", 1), decision.get("attempt", 1)
    event = {"seq": seq, "record_id": f"R{round_no}-{seq:03d}", "round": round_no,
             "attempt": attempt, "actor": actor}
    kind = action_kind(action)
    if kind == "TEAM":
        event.update(kind="TEAM", team=deepcopy(action["team"]))
    elif kind in SOCIAL_KINDS:
        # Game emits COMMITTED_SOCIAL as SOCIAL with a commitment marker.
        event.update(kind="SOCIAL" if kind == "COMMITTED_SOCIAL" else kind,
                     committed=kind == "COMMITTED_SOCIAL", **deepcopy(_social(action)))
    else:
        event["kind"] = kind or "PASS"
        event.update({k: deepcopy(v) for k, v in action.items() if k != "kind"})
    return event


def _public_prefix(record: dict[str, Any], seq: int) -> list[dict[str, Any]]:
    return [context_record(e) for e in record.get("events", [])
            if e.get("kind") in PUBLIC_KINDS and e.get("seq", 0) <= seq]


def _assassin_before(record: dict[str, Any], decision: dict[str, Any]):
    """Rebuild the actual Assassin's joint_v2 state through the prefix only."""
    game, truth = validate_replay(record)
    assassin = next((pid for pid, role in truth.items() if role == "ASSASSIN"), None)
    if assassin is None:
        raise ValueError("source record has no Assassin")
    observer = make_version("joint_v2", game.view(assassin))
    for event in _public_prefix(record, int(decision.get("after_seq", 0))):
        observer.observe(deepcopy(event))
    return observer, truth, assassin


def _legal_assassin_targets(observer, view: dict[str, Any]) -> list[str]:
    known_evil = set(view.get("known_evil", []))
    return [pid for pid in observer.ids if pid != observer.pid and pid not in known_evil]


def _merlin_stats(marginals: dict[str, dict[str, float]], true_merlin: str,
                  legal_targets: list[str]) -> dict[str, Any]:
    legal = [p for p in legal_targets if p in marginals]
    values = {p: float(marginals[p].get("merlin", 0.0)) for p in legal}
    true_probability = float(marginals.get(true_merlin, {}).get("merlin", 0.0))
    others = [p for p in legal if p != true_merlin]
    highest_other = max((values[p] for p in others), default=None)
    top_value = max(values.values(), default=None)
    top = sorted(p for p, value in values.items() if top_value is not None and value == top_value)
    rank = 1 + sum(value > true_probability for p, value in values.items() if p != true_merlin)
    return {
        "true_merlin_probability": true_probability,
        "highest_other_merlin_probability": highest_other,
        "merlin_lead": true_probability - highest_other if highest_other is not None else None,
        "true_merlin_rank": rank if legal else None,
        "top_candidate_set": json.dumps(top, ensure_ascii=False),
        "unique_top": int(len(top) == 1) if top_value is not None else None,
        "tie_size": len(top) if top_value is not None else None,
        "native_top_probability": top_value,
        "native_top_set": top,
    }


def _serial_evidence(evidence):
    return [{"origin_event_id": e.origin_event_id, "source_agent": e.source_agent,
             "target_agents": list(e.target_agents), "evidence_type": e.evidence_type.value,
             "feature": e.feature, "direction": e.direction, "strength": e.strength,
             "metadata": deepcopy(e.metadata)} for e in evidence]


def _distribution_digest(distribution: dict) -> str:
    """Hash tuple-keyed worlds through the same stable projection as v2."""
    return digest([[list(world), round(probability, 15)]
                   for world, probability in sorted(distribution.items())])


def one_step_signal(record: dict[str, Any], decision: dict[str, Any], action: dict[str, Any],
                    branch: str, *, action_category: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Run exactly one detached event through the production belief path."""
    observer, truth, assassin = _assassin_before(record, decision)
    merlin = decision.get("observer_id")
    before_marginals = observer.marginals()
    before_distribution = observer.distribution()
    view = _full_view(decision, record)
    legal_targets = _legal_assassin_targets(observer, view)
    true_merlin = next((pid for pid, role in truth.items() if role == "MERLIN"), merlin)
    before_stats = _merlin_stats(before_marginals, true_merlin, legal_targets)
    event = action_to_event(action, decision, int(decision.get("after_seq", 0)) + 1)
    observation = Observation.from_event(event)
    if observation is None:
        raise ValueError("counterfactual event is not publicly observable")
    extracted = observer.engine.extractor.extract(observation)
    factor_rows = []
    for evidence in extracted:
        values = [observer.engine.likelihood_model.evaluate(hypothesis, evidence)
                  for hypothesis in observer.engine.beliefs.hypotheses]
        factor_rows.append({
            "scenario_id": record.get("scenario_id"), "source_game_id": record.get("game_id"),
            "decision_id": decision.get("decision_id"), "branch": branch,
            "action_category": action_category, "public_event": context_record(event),
            "consumed_event_fields": context_record(event),
            "evidence_extractor_output": _serial_evidence([evidence]),
            "affected_targets": list(evidence.target_agents), "factor_name": evidence.feature,
            "factor_signal_id": evidence.signal_id,
            "factor_likelihood_values": sorted(set(round(float(x), 15) for x in values)),
            "factor_likelihood_min": min(values) if values else None,
            "factor_likelihood_max": max(values) if values else None,
            "posterior_before": _distribution_digest(before_distribution), "posterior_after": None,
            "posterior_changed": None,
        })
    observer.observe(event)
    after_marginals = observer.marginals()
    after_distribution = observer.distribution()
    after_stats = _merlin_stats(after_marginals, true_merlin, legal_targets)
    posterior_changed = int(_distribution_digest(before_distribution) != _distribution_digest(after_distribution))
    for row in factor_rows:
        row["posterior_after"] = _distribution_digest(after_distribution)
        row["posterior_changed"] = posterior_changed
        row["posterior_before_marginals"] = deepcopy(before_marginals)
        row["posterior_after_marginals"] = deepcopy(after_marginals)
    if not factor_rows:
        factor_rows.append({
            "scenario_id": record.get("scenario_id"), "source_game_id": record.get("game_id"),
            "decision_id": decision.get("decision_id"), "branch": branch,
            "action_category": action_category, "public_event": context_record(event),
            "consumed_event_fields": context_record(event), "evidence_extractor_output": [],
            "affected_targets": [], "factor_name": None, "factor_signal_id": None,
            "factor_likelihood_values": [], "factor_likelihood_min": None,
            "factor_likelihood_max": None, "posterior_before": _distribution_digest(before_distribution),
            "posterior_after": _distribution_digest(after_distribution), "posterior_changed": posterior_changed,
            "posterior_before_marginals": deepcopy(before_marginals),
            "posterior_after_marginals": deepcopy(after_marginals),
        })
    row = {
        "scenario_id": record.get("scenario_id"), "source_game_id": record.get("game_id"),
        "decision_id": decision.get("decision_id"), "stage": decision.get("stage"),
        "round": decision.get("round"), "merlin_seat": merlin, "assassin_seat": assassin,
        "branch": branch, "action_category": action_category,
        **{f"{key}_before": value for key, value in before_stats.items()
           if key not in {"native_top_set"}},
        **{f"{key}_after": value for key, value in after_stats.items()
           if key not in {"native_top_set"}},
        "posterior_hash_before": _distribution_digest(before_distribution),
        "posterior_hash_after": _distribution_digest(after_distribution),
        "posterior_changed": posterior_changed,
        "event_id": observation.event_id, "event_kind": event["kind"],
        "future_events_injected": 0, "detached_one_step": 1,
        "true_merlin_offline": true_merlin,
    }
    # The required true-merlin probability is keyed to the actual scorer label.
    true_merlin = row["true_merlin_offline"]
    if true_merlin != merlin:
        row["true_merlin_probability_before"] = before_stats["true_merlin_probability"]
        row["true_merlin_probability_after"] = after_stats["true_merlin_probability"]
    return row, factor_rows


def _prefix_hash(record: dict[str, Any], decision: dict[str, Any]) -> str:
    return digest(_public_prefix(record, int(decision.get("after_seq", 0))))


def _decision_id(record: dict[str, Any], index: int, decision: dict[str, Any]) -> str:
    return f"{record.get('scenario_id', record.get('game_id'))}:merlin:{index:03d}:{decision.get('phase')}"


def _merlin_decisions(record: dict[str, Any]) -> list[dict[str, Any]]:
    observer = record.get("observer_id")
    rows = [deepcopy(d) for d in record.get("decisions", [])
            if d.get("observer_id") == observer and d.get("phase") in {"discussion", "council_discussion"}]
    for i, d in enumerate(rows):
        d["decision_id"] = _decision_id(record, i, d)
    return rows


def build_action_inventory(source_root: Path) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, Any]]:
    source_root = Path(source_root)
    plan = json.loads((source_root / "dataset_manifest.json").read_text(encoding="utf-8"))
    records = {r["game_id"]: r for r in read_jsonl(source_root / "v23_source_replays.jsonl")}
    fixed_specs = {s["snapshot_id"]: s for s in plan.get("fixed", [])}
    fixed_rows = list(csv.DictReader((source_root / "snapshot_results.csv").open(encoding="utf-8")))
    fixed_by = defaultdict(dict)
    for row in fixed_rows:
        fixed_by[row["snapshot_id"]][row["arm"]] = row
    inventory = []
    sources: dict[str, dict[str, Any]] = {}
    for snapshot_id, arms in sorted(fixed_by.items()):
        spec = fixed_specs.get(snapshot_id)
        if not spec or not {"reference", "candidate"} <= set(arms):
            continue
        record = records[spec["source_game_id"]]
        decision = deepcopy(record["decisions"][int(spec["decision_index"])])
        decision["decision_id"] = snapshot_id
        state_equal = True
        base = {"scenario_id": record.get("scenario_id", snapshot_id),
                "source_game_id": record.get("game_id"), "decision_id": snapshot_id,
                "stage": "fixed_snapshot", "round": decision.get("round"),
                "reference_action": parse_action(arms["reference"].get("action")),
                "candidate_action": parse_action(arms["candidate"].get("action")),
                "reference_pre_state_hash": digest(decision.get("view")),
                "candidate_pre_state_hash": digest(decision.get("view")),
                "public_prefix_hash_reference": _prefix_hash(record, decision),
                "public_prefix_hash_candidate": _prefix_hash(record, decision),
                "source_kind": "fixed_snapshot", "candidate_context_present": int(arms["candidate"].get("aid_present") == "True"),
                "reference_valid": None, "candidate_valid": None,
                "reference_validation_error": None, "candidate_validation_error": None}
        for arm in ("reference", "candidate"):
            valid, error = validate_recorded_action(base[f"{arm}_action"], decision, record)
            base[f"{arm}_valid"], base[f"{arm}_validation_error"] = int(valid), error
        ref_action, cand_action = base["reference_action"], base["candidate_action"]
        base.update(diff_actions(ref_action, cand_action, pre_state_equal=state_equal,
                                 candidate_context_present=bool(base["candidate_context_present"])))
        # Keep parsed objects for the intervention; CSV serialization is done
        # at the final export boundary.
        base["reference_action"], base["candidate_action"] = ref_action, cand_action
        inventory.append(base)
        sources[snapshot_id] = {"reference": (record, decision), "candidate": (record, decision)}
    active = defaultdict(dict)
    for path in sorted((source_root / "active_replays").glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("experiment") != "A":
            continue
        active[record.get("scenario_id")][record.get("arm")] = record
    for scenario_id, arms in sorted(active.items()):
        if not {"reference", "candidate"} <= set(arms):
            continue
        ref_ds, cand_ds = _merlin_decisions(arms["reference"]), _merlin_decisions(arms["candidate"])
        for i in range(max(len(ref_ds), len(cand_ds))):
            rd, cd = (ref_ds[i] if i < len(ref_ds) else None), (cand_ds[i] if i < len(cand_ds) else None)
            ref_record, cand_record = arms["reference"], arms["candidate"]
            state_equal = bool(rd and cd and _prefix_hash(ref_record, rd) == _prefix_hash(cand_record, cd)
                               and digest(rd.get("view")) == digest(cd.get("view")))
            row = {"scenario_id": scenario_id, "source_game_id": ref_record.get("game_id"),
                   "decision_id": f"{scenario_id}:merlin:{i:03d}", "stage": "active",
                   "round": (rd or cd or {}).get("round"),
                   "reference_action": deepcopy(rd.get("action")) if rd else None,
                   "candidate_action": deepcopy(cd.get("action")) if cd else None,
                   "reference_pre_state_hash": digest(rd.get("view")) if rd else None,
                   "candidate_pre_state_hash": digest(cd.get("view")) if cd else None,
                   "public_prefix_hash_reference": _prefix_hash(ref_record, rd) if rd else None,
                   "public_prefix_hash_candidate": _prefix_hash(cand_record, cd) if cd else None,
                   "source_kind": "active", "candidate_context_present": int(bool(arms["candidate"].get("candidate_enabled"))),
                   "reference_valid": None, "candidate_valid": None,
                   "reference_validation_error": None, "candidate_validation_error": None,
                   "mechanical_state_diverged": int(not state_equal)}
            for arm, d, rec in (("reference", rd, ref_record), ("candidate", cd, cand_record)):
                valid, error = validate_recorded_action(d.get("action") if d else None, d, rec) if d else (False, "missing_decision")
                row[f"{arm}_valid"], row[f"{arm}_validation_error"] = int(valid), error
            ref_action, cand_action = row["reference_action"], row["candidate_action"]
            row.update(diff_actions(ref_action, cand_action, pre_state_equal=state_equal,
                                    candidate_context_present=bool(row["candidate_context_present"])))
            row["reference_action"], row["candidate_action"] = ref_action, cand_action
            inventory.append(row)
            sources[row["decision_id"]] = {"reference": (ref_record, rd), "candidate": (cand_record, cd)}
    return inventory, sources, plan


def build_tie_path(source_root: Path) -> list[dict[str, Any]]:
    """Keep r7 diagnostic and v2.3 active paths visibly separate."""
    source_root = Path(source_root)
    rows: list[dict[str, Any]] = []
    trace = source_root / "assassin_signal_trace.csv"
    if trace.exists():
        for item in csv.DictReader(trace.open(encoding="utf-8")):
            rows.append({"dataset_role": "r7_diagnostic_reuse", "source_run_id": item.get("source_run_id"),
                         "scenario_id": item.get("scenario_id"), "game_id": item.get("game_id"),
                         "variant": item.get("variant"), "assassin_seat": item.get("assassin"),
                         "true_merlin": item.get("true_merlin_offline"),
                         "native_top_set": item.get("top_merlin_candidates"),
                         "native_top_count": item.get("top_count"),
                         "tie_tolerance": "exact == (production decoder)",
                         "true_merlin_position_in_submitted_ranking": item.get("true_merlin_rank"),
                         "submitted_assassin_ranking": item.get("rank_length"),
                         "selected_target": item.get("target"),
                         "selected_target_is_native_top": item.get("target_in_native_argmax"),
                         "tie_break_used": item.get("tie_break_used"),
                         "id_order_position": item.get("id_order_position"),
                         "name_order_position": item.get("name_order_position"),
                         "production_mapping": item.get("policy_mapping")})
    for path in sorted((source_root / "active_replays").glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        truth = {p["id"]: p["role"] for p in record.get("players", [])}
        true_merlin = next((p for p, r in truth.items() if r == "MERLIN"), None)
        assassin = next((p for p, r in truth.items() if r == "ASSASSIN"), None)
        if not assassin:
            continue
        for index, decision in enumerate(record.get("decisions", [])):
            if decision.get("phase") != "assassination":
                continue
            view = decision.get("view", {})
            option = next((o for o in view.get("legal_options", []) if o.get("kind") == "ASSASSINATE"), {})
            legal = option.get("targets", [])
            marg = decision.get("marginals", {})
            values = {p: float(marg.get(p, {}).get("merlin", 0.0)) for p in legal}
            top_value = max(values.values(), default=None)
            top = sorted(p for p, v in values.items() if top_value is not None and v == top_value)
            target = decision.get("action", {}).get("target")
            submitted = decision.get("action", {}).get("assassin_rank")
            rows.append({"dataset_role": "v23_active_replay", "source_run_id": source_root.name,
                         "scenario_id": record.get("scenario_id"), "game_id": record.get("game_id"),
                         "variant": record.get("variant"), "assassin_seat": assassin,
                         "true_merlin": true_merlin, "native_top_set": json.dumps(top),
                         "native_top_count": len(top), "tie_tolerance": "exact == (production decoder)",
                         "true_merlin_position_in_submitted_ranking": (submitted.index(true_merlin) + 1
                                                                         if isinstance(submitted, list) and true_merlin in submitted else None),
                         "submitted_assassin_ranking": json.dumps(submitted) if submitted else None,
                         "selected_target": target, "selected_target_is_native_top": int(target in top),
                         "tie_break_used": int(len(top) > 1 and target in top),
                         "id_order_position": legal.index(target) + 1 if target in legal else None,
                         "name_order_position": None,
                         "production_mapping": "controlled_population_direct_max; no model ranking recorded"})
    return rows


def run_audit(source_root: Path, output: Path) -> dict[str, Any]:
    inventory, sources, plan = build_action_inventory(source_root)
    action_fields = ["scenario_id", "source_game_id", "decision_id", "stage", "round",
                     "reference_action", "candidate_action", "public_text_changed", "card_changed",
                     "target_changed", "citation_changed", "commitment_changed", "resource_use_changed",
                     "semantic_action_changed", "public_event_changed", "candidate_context_present",
                     "action_category", "mechanical_state_diverged", "reference_valid", "candidate_valid",
                     "reference_validation_error", "candidate_validation_error", "reference_pre_state_hash",
                     "candidate_pre_state_hash", "public_prefix_hash_reference", "public_prefix_hash_candidate"]
    export_inventory = []
    for item in inventory:
        copy_item = dict(item)
        for key in ("reference_action", "candidate_action"):
            if isinstance(copy_item.get(key), dict):
                copy_item[key] = canonical(copy_item[key])
        export_inventory.append(copy_item)
    write_csv(output / "action_diff.csv", export_inventory, action_fields)
    signal_rows, factor_rows = [], []
    validation_defect = any((row.get("reference_action") is not None and not row.get("reference_valid"))
                            or (row.get("candidate_action") is not None and not row.get("candidate_valid"))
                            for row in inventory)
    for row in inventory:
        if not row.get("reference_action") or not row.get("candidate_action"):
            continue
        if not row.get("semantic_action_changed") and not row.get("public_text_changed"):
            continue
        source = sources.get(row["decision_id"], {})
        for branch, key in (("reference", "reference_action"), ("candidate", "candidate_action")):
            record, decision = source.get(branch, (None, None))
            if record is None or decision is None:
                continue
            try:
                signal, factors = one_step_signal(record, decision, row[key], branch,
                                                  action_category=row["action_category"])
                signal.update({"stage": row.get("stage"),
                               "pre_state_equal": int(not row.get("mechanical_state_diverged", 0)),
                               "counterfactual_eligible": int(not row.get("mechanical_state_diverged", 0)),
                               "reference_action": row["reference_action"],
                               "candidate_action": row["candidate_action"]})
                signal_rows.append(signal); factor_rows.extend(factors)
            except Exception as exc:
                signal_rows.append({"scenario_id": row["scenario_id"], "source_game_id": row["source_game_id"],
                                    "decision_id": row["decision_id"], "branch": branch,
                                    "action_category": row["action_category"], "error": f"{type(exc).__name__}: {exc}",
                                    "counterfactual_eligible": 0})
    signal_fields = ["scenario_id", "source_game_id", "decision_id", "stage", "round", "merlin_seat",
                     "assassin_seat", "branch", "reference_action", "candidate_action", "action_category",
                     "true_merlin_offline", "true_merlin_probability_before", "true_merlin_probability_after",
                     "highest_other_merlin_probability_before", "highest_other_merlin_probability_after",
                     "merlin_lead_before", "merlin_lead_after", "true_merlin_rank_before", "true_merlin_rank_after",
                     "top_candidate_set_before", "top_candidate_set_after", "unique_top_before", "unique_top_after",
                     "tie_size_before", "tie_size_after", "posterior_hash_before", "posterior_hash_after",
                     "posterior_changed", "pre_state_equal", "counterfactual_eligible", "future_events_injected",
                     "detached_one_step", "event_id", "event_kind", "error"]
    write_csv(output / "assassin_signal_channel.csv", signal_rows, signal_fields)
    with (output / "factor_delta.jsonl").open("w", encoding="utf-8") as stream:
        for row in factor_rows:
            stream.write(canonical(row) + "\n")
    tie_rows = build_tie_path(source_root)
    tie_fields = ["dataset_role", "source_run_id", "scenario_id", "game_id", "variant", "assassin_seat",
                  "true_merlin", "native_top_set", "native_top_count", "tie_tolerance",
                  "true_merlin_position_in_submitted_ranking", "submitted_assassin_ranking", "selected_target",
                  "selected_target_is_native_top", "tie_break_used", "id_order_position", "name_order_position",
                  "production_mapping"]
    write_csv(output / "assassin_tie_path.csv", tie_rows, tie_fields)
    eligible = [r for r in signal_rows if r.get("counterfactual_eligible") and not r.get("error")]
    numeric = [r for r in eligible if r.get("posterior_changed")]
    rank_change = [r for r in eligible if (r.get("true_merlin_rank_before") != r.get("true_merlin_rank_after")
                                           or r.get("top_candidate_set_before") != r.get("top_candidate_set_after")
                                           or r.get("tie_size_before") != r.get("tie_size_after"))]
    categories = defaultdict(int)
    for row in inventory:
        categories[row.get("action_category", "unknown")] += 1
    gate = ("IMPLEMENTATION_DEFECT_FOUND" if validation_defect else
            "STRUCTURED_CHANNEL_FOUND" if numeric else
            "TIEBREAK_CHANNEL_ONLY" if rank_change else "CHANNEL_NOT_FOUND")
    mechanism = {
        "gate": gate,
        "primary_source_run_id": source_root.name,
        "source_data_role": "v2.3 primary; r7 tie rows retained as diagnostic reuse and never pooled",
        "action_diff_counts": dict(sorted(categories.items())),
        "action_diff_rows": len(inventory),
        "one_step_signal_rows": len(signal_rows),
        "counterfactual_eligible_rows": len(eligible),
        "posterior_changed_rows": len(numeric),
        "rank_or_top_set_changed_rows": len(rank_change),
        "validation_defect_rows": sum((r.get("reference_action") is not None and not r.get("reference_valid"))
                                       or (r.get("candidate_action") is not None and not r.get("candidate_valid"))
                                       for r in inventory),
        "factor_rows": len(factor_rows),
        "factor_counts": {name or "NO_FACTOR": sum(row.get("factor_name") == name for row in factor_rows)
                           for name in sorted({row.get("factor_name") for row in factor_rows}, key=lambda x: str(x))},
        "factor_likelihood_values": sorted({value for row in factor_rows
                                              for value in row.get("factor_likelihood_values", [])}),
        "r7_diagnostic_tie_rows": sum(r.get("dataset_role") == "r7_diagnostic_reuse" for r in tie_rows),
        "v23_active_tie_rows": sum(r.get("dataset_role") == "v23_active_replay" for r in tie_rows),
        "tie_rule": "Production decoder uses exact Python equality against max marginal; no tolerance.",
        "text_channel": "Free text is not evaluated by EvidenceExtractor action-only factors; language factors remain disabled.",
        "causal_scope": "One-step detached prefix intervention only; no future trajectory events injected.",
        "candidate_recommendation": ("retire current disclosure candidate for this mechanism"
                                      if gate == "CHANNEL_NOT_FOUND" else
                                      "inspect the single demonstrated structured factor before any next experiment"),
    }
    write_json(output / "mechanism_gate.json", mechanism)
    return {"inventory": inventory, "signals": signal_rows, "factors": factor_rows,
            "tie": tie_rows, "mechanism": mechanism, "plan": plan}
