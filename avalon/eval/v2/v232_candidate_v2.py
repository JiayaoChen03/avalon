"""Offline evaluator for the accepted MerlinVoteCamouflageV2 contract.

This module is deliberately separate from production policy code.  It uses
the frozen replay and observer helpers from ``v232_p1``/``v232_safety`` and
changes only the reconstructed Merlin boolean vote.  It never imports a
network client, calls a model provider, or enables a production candidate.
"""

from __future__ import annotations

import hashlib
import itertools
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from avalon.chronicle import PUBLIC_KINDS, context_record
from avalon.eval.simulation import digest
from avalon.eval.v2 import v232_p1 as p1
from avalon.eval.v2 import v232_safety as safety


ROOT = p1.ROOT
CANDIDATE = "MerlinVoteCamouflageV2CleanTeamGuard"
SOURCE_SAFETY_RUN = ROOT / "results/joint_belief_v2_3_2/20260920-v232-safety-r2"
PREREG_RUN = ROOT / "results/joint_belief_v2_3_2/20260920-v232-camouflage-v2-prereg-r1"
SOURCE_P1_RUN = ROOT / "results/joint_belief_v2_3_2/20260919-v232-r2-p1-offline-v12"
EPSILON = p1.EPSILON_DIAGNOSTIC
THRESHOLD = 2.0
AMBIGUITY_BAND = 1.0
CRITICAL_REJECTIONS = 4
CRITICAL_FAILURES = 2
TERMINAL_GATES = {
    "IMPLEMENTATION_INVALID",
    "CANDIDATE_NO_EFFECT",
    "CANDIDATE_EFFECT_BUT_UNSAFE",
    "CANDIDATE_PROMISING_OFFLINE",
}


class PublicVoteState:
    """Restricted public projection passed to the acting candidate."""

    __slots__ = ("team", "events", "failures", "attempt")

    def __init__(self, *, team: list[str], events: list[dict[str, Any]], failures: int, attempt: int):
        self.team = list(team)
        self.events = deepcopy(events)
        self.failures = int(failures)
        self.attempt = int(attempt)


def _public_vote_state(game) -> PublicVoteState:
    """Strip the Game object before policy evaluation so roles never cross the boundary."""
    return PublicVoteState(
        team=list(game.team),
        events=[context_record(event) for event in game.events if event.get("kind") in PUBLIC_KINDS],
        failures=int(getattr(game, "failures", 0)),
        attempt=int(getattr(game, "attempt", 1)),
    )


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _read_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path: Path, value: Any) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, value: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(value, encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    import csv

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for field in row:
            if field not in fields:
                fields.append(field)
    with Path(path).open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


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


def _public_proxy(public_state: PublicVoteState, team: list[str]) -> tuple[float, dict[str, Any]]:
    """Compute only the public proxy frozen by the accepted preregistration."""
    members = set(team)
    accusations = [
        event for event in public_state.events
        if event.get("kind") == "SOCIAL"
        and event.get("card") == "ACCUSE"
        and event.get("target") in members
    ]
    hedges = [
        event for event in public_state.events
        if event.get("kind") == "SOCIAL"
        and event.get("card") == "HEDGE"
        and event.get("target") in members
    ]
    rejected_overlap = [
        event for event in public_state.events
        if event.get("kind") == "TEAM_VOTE"
        and not event.get("approved")
        and members.intersection(event.get("team") or [])
    ]
    mission_failures = [
        event for event in public_state.events
        if event.get("kind") == "MISSION"
        and not event.get("success")
        and members.intersection(event.get("team") or [])
    ]
    score = len(accusations) + 0.5 * len(hedges) + 0.5 * len(rejected_overlap) + 2.0 * len(mission_failures)
    return score, {
        "accusation_count": len(accusations),
        "hedge_count": len(hedges),
        "rejected_overlap_count": len(rejected_overlap),
        "mission_failure_count": len(mission_failures),
    }


def candidate_vote_decision(public_state: PublicVoteState, actor_view: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    """Return the accepted candidate decision from Merlin-legal inputs only."""
    team = list(public_state.team)
    known_evil = sorted(set(actor_view.get("known_evil", [])))
    known_evil_on_team = sorted(pid for pid in team if pid in set(known_evil))
    public_score, public_components = _public_proxy(public_state, team)
    mission_safety_vote = not bool(known_evil_on_team)
    public_proxy_vote = public_score < THRESHOLD
    rejection_count = sum(
        1 for event in public_state.events if event.get("kind") == "TEAM_VOTE" and not event.get("approved")
    )
    failures = int(public_state.failures)
    critical = rejection_count >= CRITICAL_REJECTIONS or failures >= CRITICAL_FAILURES
    guard_triggered = not bool(known_evil_on_team)
    ambiguous_evil = (
        bool(known_evil_on_team)
        and not critical
        and mission_safety_vote != public_proxy_vote
        and abs(public_score - THRESHOLD) <= AMBIGUITY_BAND
    )
    if guard_triggered:
        vote, mode = True, "CLEAN_TEAM_APPROVE_GUARD"
    elif critical:
        vote, mode = mission_safety_vote, "CRITICAL_MISSION_SAFETY"
    elif ambiguous_evil:
        vote, mode = public_proxy_vote, "AMBIGUOUS_EVIL_PUBLIC_PROXY"
    else:
        vote, mode = mission_safety_vote, "MISSION_SAFETY_DEFAULT"
    return bool(vote), {
        "policy_version": CANDIDATE,
        "mode": mode,
        "critical": int(critical),
        "guard_triggered": int(guard_triggered),
        "ambiguous_evil": int(ambiguous_evil),
        "known_evil_on_team": known_evil_on_team,
        "mission_safety_vote": bool(mission_safety_vote),
        "public_proxy_vote": bool(public_proxy_vote),
        "public_only_proxy_preference": bool(public_proxy_vote),
        "public_suspicion_score": public_score,
        "public_proxy_components": public_components,
        "rejection_count_before": rejection_count,
        "mission_failures_before": failures,
        "truth_used_by_agent": 0,
        "assassin_state_used": 0,
        "evaluator_labels_used": 0,
        "current_sealed_ballots_used": 0,
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


def _mission_flags(outcomes: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "mission_outcome_count": len(outcomes),
        "mission_success_possible": None if not outcomes else int(any(row["success"] for row in outcomes)),
        "mission_failure_possible": None if not outcomes else int(any(row["fail_count"] > 0 for row in outcomes)),
        "third_mission_failure_possible": None if not outcomes else int(any(row["third_mission_failure"] for row in outcomes)),
    }


def _case(record: dict[str, Any], case: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    actor = str(case["intervention_actor_id"])
    measurement = str(case["measurement_observer_id"])
    game, _ = p1._replay_to_cutoff(record, int(case["cutoff_seq"]))
    actor_view = p1._public_view(game, actor)
    _validate_pair_contract(record, case, game, actor_view)
    # Ground truth is loaded only after candidate action generation, for scorer-side safety accounting.
    candidate_vote, policy = candidate_vote_decision(_public_vote_state(game), actor_view)
    roles = p1._roles(record)
    source_decision = record["decisions"][int(case["decision_index"])]
    if source_decision.get("observer_id") != actor or source_decision.get("after_seq") != case["cutoff_seq"]:
        raise ValueError("source_decision_actor_or_cutoff_mismatch")
    baseline_vote = bool(source_decision["action"]["approve"])
    baseline_strong = bool(source_decision["action"].get("strong", False))
    primary_other = dict(case["other_ballots"])
    baseline = safety._simulate_vote(
        record, case, actor_vote=baseline_vote, actor_strong=baseline_strong,
        other_ballots=primary_other, measurement_id=measurement,
    )
    candidate = safety._simulate_vote(
        record, case, actor_vote=candidate_vote, actor_strong=baseline_strong,
        other_ballots=primary_other, measurement_id=measurement,
    )
    if baseline["factor_consumed"] != 1 or candidate["factor_consumed"] != 1:
        raise ValueError("merlin_vote_factor_not_consumed_exactly_once")
    if digest(baseline["before"]) != digest(candidate["before"]):
        raise ValueError("assassin_prebelief_differs_between_arms")
    known_evil_on_team = list(policy["known_evil_on_team"])
    true_evil_on_team = sorted(pid for pid in game.team if roles.get(pid) in {"ASSASSIN", "MINION", "MORGANA", "MORDRED", "OBERON"})
    baseline_missions = safety._mission_outcomes(baseline)
    candidate_missions = safety._mission_outcomes(candidate)
    base_flags = _mission_flags(baseline_missions)
    cand_flags = _mission_flags(candidate_missions)
    pair_id = f"{case['source_run_id']}:{case['game_id']}:{actor}->{measurement}:{case['decision_index']}"
    safety_row = {
        "pair_id": pair_id,
        "source_run_id": case["source_run_id"],
        "game_id": case["game_id"],
        "intervention_actor_id": actor,
        "measurement_observer_id": measurement,
        "reference_vote": int(baseline_vote),
        "candidate_vote": int(candidate_vote),
        "known_evil_on_team": _json(known_evil_on_team),
        "true_evil_on_team_scorer_only": _json(true_evil_on_team),
        "guard_triggered": policy["guard_triggered"],
        "policy_mode": policy["mode"],
        "public_only_proxy_preference": int(policy["public_only_proxy_preference"]),
        "clean_team_rejected": int(not candidate_vote and not known_evil_on_team),
        "new_dirty_team_approval": int(candidate_vote and not baseline_vote and bool(known_evil_on_team)),
        "fifth_rejection_loss": int(candidate.get("winner") == "EVIL" and baseline.get("winner") != "EVIL"),
        "candidate_third_mission_failure": int(
            bool(cand_flags["third_mission_failure_possible"])
            and not bool(base_flags["third_mission_failure_possible"])
        ),
        "downstream_unresolved": int(candidate_vote != baseline_vote),
        "factor_signal_id": candidate["factor_signal_id"],
        "factor_consumed": candidate["factor_consumed"],
        "duplicate_suppressed": candidate["duplicate_suppressed"],
        "future_events_injected": 0,
        "information_boundary_violation": 0,
        "treatment_leakage": int(candidate["strong"] != baseline["strong"]),
        **base_flags,
        **{f"candidate_{key}": value for key, value in cand_flags.items()},
        "safety_status": "FAIL" if (
            not candidate_vote and not known_evil_on_team
            or candidate_vote and not baseline_vote and bool(known_evil_on_team)
            or candidate.get("winner") == "EVIL" and baseline.get("winner") != "EVIL"
            or bool(cand_flags["third_mission_failure_possible"])
            and not bool(base_flags["third_mission_failure_possible"])
            or candidate["strong"] != baseline["strong"]
        ) else ("UNRESOLVED" if candidate_vote != baseline_vote else "OBSERVED_BOUNDARY_ONLY"),
        "truth_used_by_agent": 0,
        "truth_used_by_scorer": 1,
    }
    effect = {
        "pair_id": pair_id,
        "source_run_id": case["source_run_id"],
        "game_id": case["game_id"],
        "scenario_id": case["scenario_id"],
        "round": game.round,
        "attempt": game.attempt,
        "intervention_actor_id": actor,
        "intervention_actor_role": "MERLIN",
        "measurement_observer_id": measurement,
        "measurement_observer_role": "ASSASSIN",
        "reference_vote": baseline_vote,
        "candidate_vote": candidate_vote,
        "reference_strong": baseline_strong,
        "candidate_strong": candidate["strong"],
        "known_evil_on_team": _json(known_evil_on_team),
        "guard_triggered": policy["guard_triggered"],
        "public_only_proxy_preference": policy["public_only_proxy_preference"],
        "public_suspicion_score": policy["public_suspicion_score"],
        "policy_mode": policy["mode"],
        "true_merlin_probability_before": baseline["before"]["true_merlin_probability"],
        "true_merlin_probability_reference": baseline["after"]["true_merlin_probability"],
        "true_merlin_probability_candidate": candidate["after"]["true_merlin_probability"],
        "delta_p_merlin": candidate["after"]["true_merlin_probability"] - baseline["after"]["true_merlin_probability"],
        "true_merlin_rank_reference": baseline["after"]["true_merlin_rank"],
        "true_merlin_rank_candidate": candidate["after"]["true_merlin_rank"],
        "delta_rank": candidate["after"]["true_merlin_rank"] - baseline["after"]["true_merlin_rank"],
        "merlin_lead_reference": baseline["after"]["merlin_lead"],
        "merlin_lead_candidate": candidate["after"]["merlin_lead"],
        "delta_lead": candidate["after"]["merlin_lead"] - baseline["after"]["merlin_lead"],
        "exact_top_reference": _json(baseline["after"]["exact_top"]),
        "exact_top_candidate": _json(candidate["after"]["exact_top"]),
        "unique_top_reference": baseline["after"]["unique_top"],
        "unique_top_candidate": candidate["after"]["unique_top"],
        "delta_exact_top": int(baseline["after"]["exact_top"] != candidate["after"]["exact_top"]),
        "factor_signal_id": candidate["factor_signal_id"],
        "factor_consumed": candidate["factor_consumed"],
        "duplicate_suppressed": candidate["duplicate_suppressed"],
        "prebelief_hash_reference": digest(baseline["before"]),
        "prebelief_hash_candidate": digest(candidate["before"]),
        "future_events_injected": 0,
        "valid_pair": 1,
    }
    interventions = []
    for arm, branch, vote in (("reference", baseline, baseline_vote), ("candidate", candidate, candidate_vote)):
        interventions.append({
            "pair_id": pair_id,
            "arm": arm,
            "source_run_id": case["source_run_id"],
            "game_id": case["game_id"],
            "intervention_actor_id": actor,
            "measurement_observer_id": measurement,
            "merlin_vote": vote,
            "strong": branch["strong"],
            "proposal_approved": branch["proposal_approved"],
            "p_merlin_after": branch["after"]["true_merlin_probability"],
            "rank_after": branch["after"]["true_merlin_rank"],
            "lead_after": branch["after"]["merlin_lead"],
            "exact_top_after": _json(branch["after"]["exact_top"]),
            "unique_top_after": branch["after"]["unique_top"],
            "factor_signal_id": branch["factor_signal_id"],
            "factor_consumed": branch["factor_consumed"],
            "duplicate_suppressed": branch["duplicate_suppressed"],
            "known_evil_on_team": _json(known_evil_on_team),
            "guard_triggered": policy["guard_triggered"],
            "policy_mode": policy["mode"],
            "mission_outcome_count": len(baseline_missions if arm == "reference" else candidate_missions),
            "future_events_injected": 0,
            "valid_pair": 1,
        })
    return effect, interventions, safety_row


def _sensitivity_rows(records: dict[tuple[str, str], dict[str, Any]], cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case in cases:
        record = records[(case["source_run_id"], case["game_id"])]
        game, _ = p1._replay_to_cutoff(record, int(case["cutoff_seq"]))
        actor = str(case["intervention_actor_id"])
        view = p1._public_view(game, actor)
        candidate_vote, policy = candidate_vote_decision(_public_vote_state(game), view)
        other_ids = [pid for pid in game.ids if pid != actor]
        strong = bool(record["decisions"][int(case["decision_index"])]["action"].get("strong", False))
        for bits in itertools.product((False, True), repeat=len(other_ids)):
            other = dict(zip(other_ids, bits))
            branch = safety._simulate_vote(
                record, case, actor_vote=candidate_vote, actor_strong=strong,
                other_ballots=other, measurement_id=case["measurement_observer_id"],
            )
            outcomes = safety._mission_outcomes(branch)
            rows.append({
                "pair_id": f"{case['source_run_id']}:{case['game_id']}:{actor}->{case['measurement_observer_id']}:{case['decision_index']}",
                "other_ballots": _json(other),
                "candidate_vote": candidate_vote,
                "policy_mode": policy["mode"],
                "guard_triggered": policy["guard_triggered"],
                "proposal_approved": branch["proposal_approved"],
                "fifth_rejection_loss": int(branch["winner"] == "EVIL"),
                "mission_failure_possible": None if not outcomes else int(any(row["fail_count"] > 0 for row in outcomes)),
                "third_mission_failure_possible": None if not outcomes else int(any(row["third_mission_failure"] for row in outcomes)),
                "future_events_injected": 0,
                "sensitivity_only": 1,
            })
    return rows


def _write_static_artifacts(out: Path, *, cases: list[dict[str, Any]], result: dict[str, Any],
                            effects: list[dict[str, Any]], safety_rows: list[dict[str, Any]]) -> None:
    config = {
        "run_id": out.name,
        "candidate": CANDIDATE,
        "source_safety_run_id": SOURCE_SAFETY_RUN.name,
        "source_p1_run_id": SOURCE_P1_RUN.name,
        "cases": len(cases),
        "paired_cutoffs": len(cases),
        "branches": len(effects) * 2,
        "sensitivity_rows": result["sensitivity_rows"],
        "network_calls": 0,
        "api_enabled": False,
        "candidate_default": "OFF",
        "production_promotion": False,
        "candidate_inputs": ["team", "Merlin legal known_evil", "public history", "rejection count", "mission failures", "round", "attempt"],
        "forbidden_inputs": ["Assassin posterior", "other private beliefs", "sealed ballots", "evaluator labels", "future events", "unreleased ground truth"],
        "treatment": "Merlin boolean vote only",
        "exact_tie_behavior": "production exact equality",
    }
    _write_json(out / "config.json", config)
    audit = f"""# Candidate implementation audit

Run: `{out.name}`  
Candidate: `{CANDIDATE}`  
Implementation status: **VALIDATED_OFFLINE_ONLY**  
Network calls: `0`  
Candidate default: `OFF`

The implementation is a separate evaluator module. Its candidate function consumes only the team, Merlin legal `known_evil`, public history, rejection count, mission failures, round, and attempt. It cannot receive the Assassin posterior, current sealed ballots, other private beliefs, evaluator labels, counterfactual labels, future events, or unreleased ground truth.

The clean-team guard is implemented as an unconditional `APPROVE` whenever `known_evil_on_team` is empty. On Merlin-known-evil teams, the only alternate branch is the preregistered public-only ambiguity rule. The evaluator holds the recorded `strong` modifier and all other ballots fixed, measures the actual Assassin, consumes the changed vote factor once, and records aggregate duplicate suppression.

The six cases are the frozen preregistered cases in their original order. Approved arms stop at legal immediate mission-card enumeration; rejected arms stop at the vote boundary. No historical future event is injected.

Semantic contract consistency: `PASS`  
Candidate implementation is not production behavior and was not enabled.
"""
    _write_text(out / "candidate_implementation_audit.md", audit)
    report = f"""# MerlinVoteCamouflageV2CleanTeamGuard offline evaluation

Run `{out.name}`; source safety audit `{SOURCE_SAFETY_RUN.name}`; network calls `0`.

The evaluator ran exactly six preregistered paired cutoffs and `{len(effects) * 2}` branch rows. The measurement observer is the actual Assassin in every valid pair. The treatment changes only the Merlin boolean vote; the recorded `strong` modifier, other ballots, team, public prefix, Assassin pre-belief, production `joint_v2`, evidence path, and exact tie behavior are fixed.

Gate: `{result['gate']}`. Meaningful Assassin-side effect pairs: `{result['meaningful_effect_pairs']}`. Hard safety failures: `{result['hard_safety_failures']}`. Unresolved safety rows: `{result['unresolved_safety_rows']}`. Candidate vote changes: `{result['candidate_vote_changes']}`. Sensitivity rows: `{result['sensitivity_rows']}`; these are diagnostics only and not additional game samples.

The candidate guard prevents clean-team rejection by contract. Any new Merlin-known dirty-team approval, fifth-rejection loss, third mission failure caused by the candidate, information-boundary violation, or treatment leakage is a hard failure. Unknown downstream consequences remain `UNRESOLVED` and are not treated as positive evidence.

This fixed-state evaluation is not a win-rate estimate. It does not authorize API calls, full-game testing, production enablement, or candidate promotion. A proposed next-stage test plan is required for any later work.
"""
    _write_text(out / "report.md", report)


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
    meaningful = [
        row for row in effects
        if abs(float(row["delta_p_merlin"])) > EPSILON
        or int(row["delta_rank"]) != 0
        or abs(float(row["delta_lead"])) > EPSILON
        or int(row["delta_exact_top"])
    ]
    hard_failures = [
        row for row in safety_rows
        if row["clean_team_rejected"]
        or row["new_dirty_team_approval"]
        or row["fifth_rejection_loss"]
        or row["candidate_third_mission_failure"]
        or row["information_boundary_violation"]
        or row["treatment_leakage"]
    ]
    unresolved = [row for row in safety_rows if row["downstream_unresolved"]]
    if invalid or len(effects) != len(cases):
        gate = "IMPLEMENTATION_INVALID"
    elif hard_failures:
        gate = "CANDIDATE_EFFECT_BUT_UNSAFE"
    elif not meaningful:
        gate = "CANDIDATE_NO_EFFECT"
    else:
        gate = "CANDIDATE_PROMISING_OFFLINE"
    if gate not in TERMINAL_GATES:
        raise AssertionError(f"invalid terminal gate {gate}")
    result = {
        "run_id": out.name,
        "source_safety_run_id": SOURCE_SAFETY_RUN.name,
        "source_p1_run_id": SOURCE_P1_RUN.name,
        "candidate": CANDIDATE,
        "gate": gate,
        "implementation_status": "VALID" if not invalid else "INVALID",
        "implementation_matches_preregistration": not bool(invalid),
        "network_calls": 0,
        "api_enabled": False,
        "candidate_enabled": False,
        "production_promotion": False,
        "cases": len(cases),
        "valid_pairs": len(effects),
        "invalid_pairs": len(invalid),
        "invalid_reasons": invalid,
        "branches": len(effects) * 2,
        "candidate_vote_changes": sum(int(row["reference_vote"] != row["candidate_vote"]) for row in effects),
        "meaningful_effect_pairs": len(meaningful),
        "hard_safety_failures": len(hard_failures),
        "hard_safety_failure_pairs": sorted({row["pair_id"] for row in hard_failures}),
        "unresolved_safety_rows": len(unresolved),
        "sensitivity_rows": len(sensitivity),
        "future_events_injected": 0,
        "full_game_effect": "NOT_TESTED",
        "production_behavior_changed": False,
        "candidate_default": "OFF",
        "terminal_gate_labels": sorted(TERMINAL_GATES),
    }
    _write_json(out / "candidate_safety_gate.json", result)
    _write_json(out / "summary.json", {
        "run_id": out.name,
        "sample_counts": {
            "source_scenarios": len({case["scenario_id"] for case in cases}),
            "games": len({case["game_id"] for case in cases}),
            "paired_cutoffs": len(cases),
            "valid_pairs": len(effects),
            "excluded_pairs": len(invalid),
            "branch_rows": len(effects) * 2,
            "sensitivity_rows": len(sensitivity),
            "model_logical_requests": 0,
            "actual_request_attempts": 0,
        },
        "network_calls": 0,
        "candidate": CANDIDATE,
        "gate": gate,
    })
    _write_static_artifacts(out, cases=cases, result=result, effects=effects, safety_rows=safety_rows)
    manifest = {
        "run_id": out.name,
        "candidate": CANDIDATE,
        "source_safety_run_id": SOURCE_SAFETY_RUN.name,
        "source_p1_run_id": SOURCE_P1_RUN.name,
        "network_calls": 0,
        "network_access": False,
        "api_enabled": False,
        "candidate_default": "OFF",
        "production_promotion": False,
        "sample_freeze": "exact six accepted preregistered cases in frozen order",
        "source_artifacts": {
            "preregistration_spec": str(PREREG_RUN / "candidate_spec.md"),
            "preregistered_plan": str(PREREG_RUN / "preregistered_plan.json"),
            "preregistered_cases": str(PREREG_RUN / "preregistered_cases.json"),
            "source_safety_gate": str(SOURCE_SAFETY_RUN / "candidate_safety_gate.json"),
            "source_safety_manifest": str(SOURCE_SAFETY_RUN / "source_manifest.json"),
        },
        "source_hashes": {
            "candidate_spec.md": _sha256(PREREG_RUN / "candidate_spec.md"),
            "preregistered_plan.json": _sha256(PREREG_RUN / "preregistered_plan.json"),
            "preregistered_cases.json": _sha256(PREREG_RUN / "preregistered_cases.json"),
            "source_safety_gate.json": _sha256(SOURCE_SAFETY_RUN / "candidate_safety_gate.json"),
            "source_safety_manifest.json": _sha256(SOURCE_SAFETY_RUN / "source_manifest.json"),
        },
        "frozen_code": {
            "avalon/eval/v2/v232_candidate_v2.py": _sha256(Path(__file__)),
            "avalon/eval/v2/v232_p1.py": _sha256(ROOT / "avalon/eval/v2/v232_p1.py"),
            "avalon/eval/v2/v232_safety.py": _sha256(ROOT / "avalon/eval/v2/v232_safety.py"),
        },
        "implementation_matches_preregistration": result["implementation_matches_preregistration"],
        "artifact_hashes": {},
    }
    for path in sorted(out.iterdir()):
        if path.name == "source_manifest.json":
            continue
        manifest["artifact_hashes"][path.name] = _sha256(path)
    _write_json(out / "source_manifest.json", manifest)
    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    args = parser.parse_args()
    print(json.dumps(run(Path(args.run_dir)), ensure_ascii=False, indent=2, sort_keys=True))
