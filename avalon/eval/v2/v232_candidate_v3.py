"""Offline evaluator for the accepted MerlinVoteCamouflageV3 contract.

The V3 candidate is evaluated as a separate, restricted-policy module.  It
does not call a provider, run a full game, or alter production defaults.  The
only treatment is Merlin's boolean vote; the recorded ``strong`` modifier and
all other ballots remain fixed.
"""

from __future__ import annotations

import hashlib
import itertools
import json
from pathlib import Path
from typing import Any

from avalon.eval.v2 import v232_candidate_v2 as v2
from avalon.eval.v2 import v232_p1 as p1
from avalon.eval.v2 import v232_safety as safety


ROOT = p1.ROOT
CANDIDATE = "MerlinVoteCamouflageV3PublicConsensus"
PREREG_RUN = ROOT / "results/joint_belief_v2_3_2/20260920-v232-camouflage-v3-prereg-r1"
SOURCE_SAFETY_RUN = ROOT / "results/joint_belief_v2_3_2/20260920-v232-safety-r2"
SOURCE_P1_RUN = ROOT / "results/joint_belief_v2_3_2/20260919-v232-r2-p1-offline-v12"
EPSILON = p1.EPSILON_DIAGNOSTIC
CRITICAL_REJECTIONS = 4
CRITICAL_FAILURES = 2
TERMINAL_GATES = {
    "IMPLEMENTATION_INVALID",
    "CANDIDATE_NO_EFFECT",
    "CANDIDATE_EFFECT_BUT_UNSAFE",
    "CANDIDATE_PROMISING_OFFLINE",
}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _read_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    import csv

    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for field in row:
            if field not in fields:
                fields.append(field)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_cases() -> list[dict[str, Any]]:
    prereg = _read_json(PREREG_RUN / "preregistered_cases.json")
    source = _read_json(SOURCE_SAFETY_RUN / "preregistered_cases.json")
    cases = prereg.get("cases", [])
    if len(cases) != 6:
        raise ValueError(f"expected six frozen cases, got {len(cases)}")
    if cases != source.get("cases", []):
        raise ValueError("preregistered cases differ from corrected r2 cases")
    if prereg.get("frozen_before_analysis") is not True:
        raise ValueError("case freeze marker missing")
    return cases


def _public_warning_count(public_state: v2.PublicVoteState, team: list[str]) -> tuple[int, dict[str, int]]:
    """Count only the three public warning classes frozen in the preregistration."""
    members = set(team)
    accusations = sum(
        1 for event in public_state.events
        if event.get("kind") == "SOCIAL"
        and event.get("card") == "ACCUSE"
        and event.get("target") in members
    )
    rejected_overlap = sum(
        1 for event in public_state.events
        if event.get("kind") == "TEAM_VOTE"
        and not event.get("approved")
        and members.intersection(event.get("team") or [])
    )
    failed_mission_overlap = sum(
        1 for event in public_state.events
        if event.get("kind") == "MISSION"
        and not event.get("success")
        and members.intersection(event.get("team") or [])
    )
    components = {
        "public_accuse_on_team": accusations,
        "rejected_overlap": rejected_overlap,
        "failed_mission_overlap": failed_mission_overlap,
    }
    return sum(components.values()), components


def candidate_vote_decision(public_state: v2.PublicVoteState, actor_view: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    """Implement the frozen V3 policy using only Merlin-legal inputs."""
    if not isinstance(public_state, v2.PublicVoteState):
        raise TypeError("candidate requires restricted PublicVoteState")
    team = list(public_state.team)
    known_evil = set(actor_view.get("known_evil", []))
    known_evil_on_team = sorted(pid for pid in team if pid in known_evil)
    rejection_count = sum(
        1 for event in public_state.events
        if event.get("kind") == "TEAM_VOTE" and not event.get("approved")
    )
    warning_count, warning_components = _public_warning_count(public_state, team)
    mission_safety_vote = not bool(known_evil_on_team)
    public_consensus_vote = warning_count < 1
    critical = rejection_count >= CRITICAL_REJECTIONS or int(public_state.failures) >= CRITICAL_FAILURES
    if critical:
        vote, mode = mission_safety_vote, "CRITICAL_MISSION_SAFETY"
    elif public_consensus_vote != mission_safety_vote:
        vote, mode = public_consensus_vote, "PUBLIC_CONSENSUS"
    else:
        vote, mode = mission_safety_vote, "MISSION_SAFETY_DEFAULT"
    return bool(vote), {
        "policy_version": CANDIDATE,
        "mode": mode,
        "critical": int(critical),
        "known_evil_on_team": known_evil_on_team,
        "mission_safety_vote": bool(mission_safety_vote),
        "public_consensus_vote": bool(public_consensus_vote),
        "public_warning_count": warning_count,
        "public_warning_components": warning_components,
        "rejection_count_before": rejection_count,
        "mission_failures_before": int(public_state.failures),
        "truth_used_by_agent": 0,
        "assassin_state_used": 0,
        "evaluator_labels_used": 0,
        "counterfactual_labels_used": 0,
        "current_sealed_ballots_used": 0,
        "future_events_used": 0,
    }


def _mission_flags(outcomes: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "mission_outcome_count": len(outcomes),
        "mission_success_possible": None if not outcomes else int(any(row["success"] for row in outcomes)),
        "mission_failure_possible": None if not outcomes else int(any(row["fail_count"] > 0 for row in outcomes)),
        "third_mission_failure_possible": None if not outcomes else int(any(row["third_mission_failure"] for row in outcomes)),
    }


def _validate_pair_contract(record: dict[str, Any], case: dict[str, Any], game, actor_view: dict[str, Any]) -> None:
    roles = p1._roles(record)
    actor = str(case["intervention_actor_id"])
    measurement = str(case["measurement_observer_id"])
    if roles.get(actor) != "MERLIN" or case.get("intervention_actor_role") != "MERLIN":
        raise ValueError("intervention_actor_is_not_merlin")
    if roles.get(measurement) != "ASSASSIN" or case.get("measurement_observer_role") != "ASSASSIN":
        raise ValueError("measurement_observer_is_not_assassin")
    if actor == measurement:
        raise ValueError("actor_and_measurement_observer_match")
    if p1.digest(actor_view) != case["legal_view_hash"]:
        raise ValueError("merlin_legal_view_hash_mismatch")
    if game.phase != "vote":
        raise ValueError(f"expected_vote_phase:{game.phase}")


def _case(record: dict[str, Any], case: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    actor = str(case["intervention_actor_id"])
    measurement = str(case["measurement_observer_id"])
    game, _ = p1._replay_to_cutoff(record, int(case["cutoff_seq"]))
    actor_view = p1._public_view(game, actor)
    _validate_pair_contract(record, case, game, actor_view)
    public_state = v2._public_vote_state(game)
    candidate_vote, policy = candidate_vote_decision(public_state, actor_view)
    source_decision = record["decisions"][int(case["decision_index"])]
    if source_decision.get("observer_id") != actor or source_decision.get("after_seq") != case["cutoff_seq"]:
        raise ValueError("source_decision_actor_or_cutoff_mismatch")
    baseline_vote = bool(source_decision["action"]["approve"])
    baseline_strong = bool(source_decision["action"].get("strong", False))
    other_ballots = dict(case["other_ballots"])
    baseline = safety._simulate_vote(record, case, actor_vote=baseline_vote, actor_strong=baseline_strong,
                                     other_ballots=other_ballots, measurement_id=measurement)
    candidate = safety._simulate_vote(record, case, actor_vote=candidate_vote, actor_strong=baseline_strong,
                                      other_ballots=other_ballots, measurement_id=measurement)
    if baseline["factor_consumed"] != 1 or candidate["factor_consumed"] != 1:
        raise ValueError("merlin_vote_factor_not_consumed_exactly_once")
    if p1.digest(baseline["before"]) != p1.digest(candidate["before"]):
        raise ValueError("assassin_prebelief_differs_between_arms")
    if baseline["strong"] != candidate["strong"]:
        raise ValueError("treatment_leakage_strong_modifier")
    roles = p1._roles(record)
    true_evil = sorted(pid for pid in game.team if roles.get(pid) in {"ASSASSIN", "MINION", "MORGANA", "MORDRED", "OBERON"})
    baseline_missions = safety._mission_outcomes(baseline)
    candidate_missions = safety._mission_outcomes(candidate)
    base_flags = _mission_flags(baseline_missions)
    cand_flags = _mission_flags(candidate_missions)
    pair_id = f"{case['source_run_id']}:{case['game_id']}:{actor}->{measurement}:{case['decision_index']}"
    clean_rejected = int(not candidate_vote and not policy["known_evil_on_team"])
    new_dirty_approval = int(candidate_vote and not baseline_vote and bool(policy["known_evil_on_team"]))
    fifth_loss = int(candidate.get("winner") == "EVIL" and baseline.get("winner") != "EVIL")
    third_failure = int(bool(cand_flags["third_mission_failure_possible"]) and not bool(base_flags["third_mission_failure_possible"]))
    boundary_violation = int(any(policy.get(k) for k in ("truth_used_by_agent", "assassin_state_used", "evaluator_labels_used", "counterfactual_labels_used", "current_sealed_ballots_used", "future_events_used")))
    safety_status = "FAIL" if (clean_rejected or new_dirty_approval or fifth_loss or third_failure or boundary_violation) else ("UNRESOLVED" if candidate_vote != baseline_vote else "OBSERVED_BOUNDARY_ONLY")
    effect = {
        "pair_id": pair_id, "source_run_id": case["source_run_id"], "game_id": case["game_id"], "scenario_id": case["scenario_id"],
        "round": game.round, "attempt": game.attempt, "intervention_actor_id": actor, "intervention_actor_role": "MERLIN",
        "measurement_observer_id": measurement, "measurement_observer_role": "ASSASSIN", "reference_vote": baseline_vote,
        "candidate_vote": candidate_vote, "reference_strong": baseline_strong, "candidate_strong": candidate["strong"],
        "known_evil_on_team": _json(policy["known_evil_on_team"]), "true_evil_on_team_scorer_only": _json(true_evil),
        "policy_mode": policy["mode"], "critical": policy["critical"], "public_warning_count": policy["public_warning_count"],
        "public_warning_components": _json(policy["public_warning_components"]), "public_consensus_vote": policy["public_consensus_vote"],
        "mission_safety_vote": policy["mission_safety_vote"], "reference_p_merlin_after": baseline["after"]["true_merlin_probability"],
        "candidate_p_merlin_after": candidate["after"]["true_merlin_probability"], "delta_p_merlin": candidate["after"]["true_merlin_probability"] - baseline["after"]["true_merlin_probability"],
        "reference_rank": baseline["after"]["true_merlin_rank"], "candidate_rank": candidate["after"]["true_merlin_rank"],
        "delta_rank": candidate["after"]["true_merlin_rank"] - baseline["after"]["true_merlin_rank"], "reference_lead": baseline["after"]["merlin_lead"],
        "candidate_lead": candidate["after"]["merlin_lead"], "delta_lead": candidate["after"]["merlin_lead"] - baseline["after"]["merlin_lead"],
        "exact_top_reference": _json(baseline["after"]["exact_top"]), "exact_top_candidate": _json(candidate["after"]["exact_top"]),
        "unique_top_reference": baseline["after"]["unique_top"], "unique_top_candidate": candidate["after"]["unique_top"],
        "delta_exact_top": int(baseline["after"]["exact_top"] != candidate["after"]["exact_top"]),
        "factor_signal_id": candidate["factor_signal_id"], "factor_consumed_reference": baseline["factor_consumed"],
        "factor_consumed_candidate": candidate["factor_consumed"], "duplicate_suppressed_reference": baseline["duplicate_suppressed"],
        "duplicate_suppressed_candidate": candidate["duplicate_suppressed"], "prebelief_hash_reference": p1.digest(baseline["before"]),
        "prebelief_hash_candidate": p1.digest(candidate["before"]), "future_events_injected": 0, "valid_pair": 1,
    }
    safety_row = {
        "pair_id": pair_id, "source_run_id": case["source_run_id"], "game_id": case["game_id"], "intervention_actor_id": actor,
        "measurement_observer_id": measurement, "reference_vote": int(baseline_vote), "candidate_vote": int(candidate_vote),
        "known_evil_on_team": _json(policy["known_evil_on_team"]), "true_evil_on_team_scorer_only": _json(true_evil),
        "clean_team_rejected": clean_rejected, "new_dirty_team_approval": new_dirty_approval, "fifth_rejection_loss": fifth_loss,
        "candidate_third_mission_failure": third_failure, "information_boundary_violation": boundary_violation,
        "treatment_leakage": int(baseline["strong"] != candidate["strong"]), "downstream_unresolved": int(candidate_vote != baseline_vote),
        "factor_signal_id": candidate["factor_signal_id"], "factor_consumed": candidate["factor_consumed"],
        "duplicate_suppressed": candidate["duplicate_suppressed"], "future_events_injected": 0,
        "reference_mission_outcome_count": len(baseline_missions), "candidate_mission_outcome_count": len(candidate_missions),
        **base_flags, **{f"candidate_{k}": v for k, v in cand_flags.items()}, "safety_status": safety_status,
        "truth_used_by_agent": 0, "truth_used_by_scorer": 1,
    }
    interventions = []
    for arm, branch, vote in (("reference", baseline, baseline_vote), ("candidate", candidate, candidate_vote)):
        interventions.append({
            "pair_id": pair_id, "arm": arm, "source_run_id": case["source_run_id"], "game_id": case["game_id"],
            "intervention_actor_id": actor, "measurement_observer_id": measurement, "merlin_vote": vote, "strong": branch["strong"],
            "proposal_approved": branch["proposal_approved"], "p_merlin_after": branch["after"]["true_merlin_probability"],
            "rank_after": branch["after"]["true_merlin_rank"], "lead_after": branch["after"]["merlin_lead"],
            "exact_top_after": _json(branch["after"]["exact_top"]), "unique_top_after": branch["after"]["unique_top"],
            "factor_signal_id": branch["factor_signal_id"], "factor_consumed": branch["factor_consumed"],
            "duplicate_suppressed": branch["duplicate_suppressed"], "public_warning_count": policy["public_warning_count"],
            "policy_mode": policy["mode"], "mission_outcome_count": len(baseline_missions if arm == "reference" else candidate_missions),
            "future_events_injected": 0, "valid_pair": 1,
        })
    return effect, interventions, safety_row


def _sensitivity_rows(records: dict[tuple[str, str], dict[str, Any]], cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case in cases:
        record = records[(case["source_run_id"], case["game_id"])]
        game, _ = p1._replay_to_cutoff(record, int(case["cutoff_seq"]))
        actor = str(case["intervention_actor_id"])
        public_state = v2._public_vote_state(game)
        vote, policy = candidate_vote_decision(public_state, p1._public_view(game, actor))
        other_ids = [pid for pid in game.ids if pid != actor]
        strong = bool(record["decisions"][int(case["decision_index"])] ["action"].get("strong", False))
        for bits in itertools.product((False, True), repeat=len(other_ids)):
            other = dict(zip(other_ids, bits))
            branch = safety._simulate_vote(record, case, actor_vote=vote, actor_strong=strong, other_ballots=other, measurement_id=case["measurement_observer_id"])
            outcomes = safety._mission_outcomes(branch)
            rows.append({"pair_id": f"{case['source_run_id']}:{case['game_id']}:{actor}->{case['measurement_observer_id']}:{case['decision_index']}", "other_ballots": _json(other), "candidate_vote": vote, "policy_mode": policy["mode"], "public_warning_count": policy["public_warning_count"], "proposal_approved": branch["proposal_approved"], "fifth_rejection_loss": int(branch["winner"] == "EVIL"), "mission_failure_possible": None if not outcomes else int(any(o["fail_count"] > 0 for o in outcomes)), "third_mission_failure_possible": None if not outcomes else int(any(o["third_mission_failure"] for o in outcomes)), "future_events_injected": 0, "sensitivity_only": 1})
    return rows


def _write_static_artifacts(out: Path, cases: list[dict[str, Any]], result: dict[str, Any]) -> None:
    _write_json(out / "config.json", {
        "run_id": out.name, "candidate": CANDIDATE, "cases": len(cases), "paired_cutoffs": len(cases),
        "branches": result["branches"], "sensitivity_rows": result["sensitivity_rows"], "network_calls": 0,
        "api_enabled": False, "candidate_default": "OFF", "production_promotion": False,
        "treatment": "Merlin boolean vote only", "candidate_inputs": ["proposed team", "Merlin legal known_evil", "sanitized public history", "public rejection count", "mission failures", "round", "attempt"],
        "forbidden_inputs": ["current sealed other ballots", "other private beliefs", "Assassin identity or posterior", "evaluator labels", "counterfactual labels", "future events", "unreleased ground truth", "full Game object"],
        "exact_tie_behavior": "production exact equality",
    })
    _write_text(out / "candidate_implementation_audit.md", f"""# Candidate implementation audit

Run: `{out.name}`  
Candidate: `{CANDIDATE}`  
Implementation status: **VALIDATED_OFFLINE_ONLY**  
Network calls: `0`  
Candidate default: `OFF`

The candidate receives the restricted `PublicVoteState` projection and Merlin's legal `known_evil` view. It uses only the frozen public warning count (public `ACCUSE`, rejected overlapping teams, and failed overlapping missions), the public rejection/failure counters, and the proposed team. It never receives a full `Game`, Assassin state, sealed ballots, evaluator labels, future events, or unreleased ground truth.

The evaluator holds the recorded `strong` modifier and all other ballots fixed, measures the actual Assassin, consumes the changed vote factor once, records duplicate suppression, and enumerates only the immediate legal mission-card boundary for approved branches. Rejected branches stop at the vote boundary.

Semantic contract consistency: `PASS`  
Candidate implementation is not production behavior and was not enabled.
""")
    _write_text(out / "report.md", f"""# {CANDIDATE} offline evaluation

Run `{out.name}`; source safety audit `{SOURCE_SAFETY_RUN.name}`; network calls `0`.

This run uses exactly six frozen paired cutoffs, `{result['branches']}` branch rows, and `{result['sensitivity_rows']}` other-ballot sensitivity rows. The intervention actor is Merlin and the measurement observer is the actual Assassin in every valid pair. Only the Merlin boolean vote changes; `strong`, other ballots, team, public prefix, Assassin pre-belief, `joint_v2`, evidence weights, legal menus, role boundaries, sealed-vote semantics, decoder, and exact tie behavior remain fixed.

Gate: `{result['gate']}`. Meaningful Assassin-side effect pairs: `{result['meaningful_effect_pairs']}`. Candidate vote changes: `{result['candidate_vote_changes']}`. Hard safety failures: `{result['hard_safety_failures']}`. Unresolved safety rows: `{result['unresolved_safety_rows']}`.

This fixed-state run is not a win-rate estimate. It does not authorize API calls, live/full-game testing, production enablement, or promotion. The next-stage plan is review-only.
""")


def run(out: Path) -> dict[str, Any]:
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=False)
    cases = _load_cases()
    records, _ = p1._source_records()
    effects: list[dict[str, Any]] = []
    interventions: list[dict[str, Any]] = []
    safety_rows: list[dict[str, Any]] = []
    invalid: list[dict[str, Any]] = []
    for case in cases:
        try:
            record = records[(case["source_run_id"], case["game_id"])]
            effect, irows, srow = _case(record, case)
            effects.append(effect)
            interventions.extend(irows)
            safety_rows.append(srow)
        except Exception as exc:
            invalid.append({"pair_id": f"{case.get('source_run_id')}:{case.get('game_id')}:{case.get('decision_index')}", "reason": f"{type(exc).__name__}:{exc}"})
    sensitivity = _sensitivity_rows(records, cases) if not invalid else []
    _write_csv(out / "candidate_assassin_effect.csv", effects)
    _write_csv(out / "candidate_vote_interventions.csv", interventions)
    _write_csv(out / "candidate_safety_tradeoff.csv", safety_rows)
    _write_csv(out / "candidate_safety_sensitivity.csv", sensitivity)
    meaningful = [row for row in effects if abs(float(row["delta_p_merlin"])) > EPSILON or int(row["delta_rank"]) != 0 or abs(float(row["delta_lead"])) > EPSILON or int(row["delta_exact_top"])]
    hard_failures = [row for row in safety_rows if row["clean_team_rejected"] or row["new_dirty_team_approval"] or row["fifth_rejection_loss"] or row["candidate_third_mission_failure"] or row["information_boundary_violation"] or row["treatment_leakage"]]
    unresolved = [row for row in safety_rows if row["downstream_unresolved"]]
    if invalid or len(effects) != len(cases):
        gate = "IMPLEMENTATION_INVALID"
    elif hard_failures:
        gate = "CANDIDATE_EFFECT_BUT_UNSAFE"
    elif not meaningful:
        gate = "CANDIDATE_NO_EFFECT"
    else:
        gate = "CANDIDATE_PROMISING_OFFLINE"
    result = {
        "run_id": out.name, "source_safety_run_id": SOURCE_SAFETY_RUN.name, "source_p1_run_id": SOURCE_P1_RUN.name,
        "candidate": CANDIDATE, "gate": gate, "implementation_status": "VALID" if not invalid else "INVALID",
        "implementation_matches_preregistration": not bool(invalid), "network_calls": 0, "api_enabled": False,
        "candidate_enabled": False, "production_promotion": False, "cases": len(cases), "valid_pairs": len(effects),
        "invalid_pairs": len(invalid), "invalid_reasons": invalid, "branches": len(effects) * 2,
        "candidate_vote_changes": sum(int(row["reference_vote"] != row["candidate_vote"]) for row in effects),
        "meaningful_effect_pairs": len(meaningful), "hard_safety_failures": len(hard_failures),
        "hard_safety_failure_pairs": sorted({row["pair_id"] for row in hard_failures}), "unresolved_safety_rows": len(unresolved),
        "sensitivity_rows": len(sensitivity), "future_events_injected": 0, "full_game_effect": "NOT_TESTED",
        "production_behavior_changed": False, "candidate_default": "OFF", "terminal_gate_labels": sorted(TERMINAL_GATES),
    }
    _write_json(out / "candidate_safety_gate.json", result)
    _write_json(out / "summary.json", {"run_id": out.name, "sample_counts": {"source_scenarios": len({c["scenario_id"] for c in cases}), "games": len({c["game_id"] for c in cases}), "paired_cutoffs": len(cases), "valid_pairs": len(effects), "excluded_pairs": len(invalid), "branch_rows": len(effects) * 2, "sensitivity_rows": len(sensitivity), "model_logical_requests": 0, "actual_request_attempts": 0}, "network_calls": 0, "candidate": CANDIDATE, "gate": gate})
    _write_static_artifacts(out, cases, result)
    manifest = {
        "run_id": out.name, "candidate": CANDIDATE, "network_calls": 0, "network_access": False, "api_enabled": False,
        "candidate_default": "OFF", "production_promotion": False, "sample_freeze": "exact six accepted preregistered cases in frozen order",
        "source_artifacts": {"preregistration_spec": str(PREREG_RUN / "candidate_spec.md"), "preregistered_plan": str(PREREG_RUN / "preregistered_plan.json"), "preregistered_cases": str(PREREG_RUN / "preregistered_cases.json"), "source_safety_gate": str(SOURCE_SAFETY_RUN / "candidate_safety_gate.json"), "source_safety_manifest": str(SOURCE_SAFETY_RUN / "source_manifest.json")},
        "source_hashes": {name: _sha256(path) for name, path in {"candidate_spec.md": PREREG_RUN / "candidate_spec.md", "preregistered_plan.json": PREREG_RUN / "preregistered_plan.json", "preregistered_cases.json": PREREG_RUN / "preregistered_cases.json", "source_safety_gate.json": SOURCE_SAFETY_RUN / "candidate_safety_gate.json", "source_safety_manifest.json": SOURCE_SAFETY_RUN / "source_manifest.json"}.items()},
        "frozen_code": {"avalon/eval/v2/v232_candidate_v3.py": _sha256(Path(__file__)), "avalon/eval/v2/v232_candidate_v2.py": _sha256(ROOT / "avalon/eval/v2/v232_candidate_v2.py"), "avalon/eval/v2/v232_p1.py": _sha256(ROOT / "avalon/eval/v2/v232_p1.py"), "avalon/eval/v2/v232_safety.py": _sha256(ROOT / "avalon/eval/v2/v232_safety.py")},
        "implementation_matches_preregistration": result["implementation_matches_preregistration"], "artifact_hashes": {},
    }
    for path in sorted(out.iterdir()):
        if path.name != "source_manifest.json":
            manifest["artifact_hashes"][path.name] = _sha256(path)
    _write_json(out / "source_manifest.json", manifest)
    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    args = parser.parse_args()
    print(json.dumps(run(Path(args.run_dir)), ensure_ascii=False, indent=2, sort_keys=True))
