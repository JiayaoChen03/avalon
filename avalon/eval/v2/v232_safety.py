"""Offline mission-safety audit for the frozen MerlinVoteCamouflageV1 policy.

This module deliberately stops at the first post-vote mission boundary.  It
does not replay historical future events after a vote branch diverges and it
does not call a model provider.
"""

from __future__ import annotations

import itertools
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from avalon.chronicle import PUBLIC_KINDS, context_record
from avalon.eval.simulation import digest
from avalon.eval.v2.adapters import make_version
from avalon.eval.v2 import v232_p1 as p1


ROOT = p1.ROOT
EPSILON = p1.EPSILON_DIAGNOSTIC


def _bool(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    return str(value).lower() in {"1", "true", "yes"}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _observer(game, observer_id: str):
    view = p1._public_view(game, observer_id)
    observer = make_version("joint_v2", deepcopy(view))
    for event in game.events:
        if event.get("kind") in PUBLIC_KINDS:
            observer.observe(context_record(event))
    return observer, view


def _simulate_vote(record: dict[str, Any], case: dict[str, Any], *, actor_vote: bool,
                   actor_strong: bool, other_ballots: dict[str, bool],
                   measurement_id: str) -> dict[str, Any]:
    actor = str(case["intervention_actor_id"])
    game, _ = p1._replay_to_cutoff(record, int(case["cutoff_seq"]))
    observer, measurement_view = _observer(game, measurement_id)
    before = p1._merlin_metrics(observer, actor, measurement_view)
    clone = deepcopy(game)
    votes = {pid: bool(other_ballots[pid]) for pid in clone.ids if pid != actor}
    votes[actor] = bool(actor_vote)
    strong = {pid: False for pid in clone.ids}
    strong[actor] = bool(actor_strong)
    for pid in clone.ids:
        clone.validate_ballot(pid, votes[pid], strong[pid])
    pre_event_count = len(clone.events)
    clone.vote(votes, reasons={pid: "team_risk" for pid in clone.ids}, strong=strong)
    factor_rows: list[dict[str, Any]] = []
    duplicate_rows = 0
    signal_id = f"vote:{game.round}:{game.attempt}:{actor}"
    for event in clone.events[pre_event_count:]:
        if event.get("kind") not in PUBLIC_KINDS:
            continue
        expected = p1._event_signal_ids(event, measurement_id)
        applied_before = set(getattr(getattr(observer, "engine", None), "_applied_signals", set()))
        observer.observe(context_record(event))
        duplicate = int(bool(expected) and set(expected) <= applied_before)
        fresh = p1._factor_provenance(
            observer, event, "safety", "safety",
            context={"intervention_actor_id": actor, "measurement_observer_id": measurement_id},
        )
        if duplicate:
            duplicate_rows += len(expected)
        factor_rows.extend(fresh)
    after = p1._merlin_metrics(observer, actor, measurement_view)
    consumed = sum(1 for row in factor_rows if row.get("signal_id") == signal_id
                   and int(row.get("factor_consumed") or 0))
    commit = next((event for event in clone.events[pre_event_count:]
                   if event.get("kind") == "TEAM_VOTE"), None)
    return {
        "vote": bool(actor_vote), "strong": bool(actor_strong),
        "before": before, "after": after,
        "factor_signal_id": signal_id, "factor_consumed": consumed,
        "duplicate_suppressed": duplicate_rows,
        "proposal_approved": commit.get("approved") if commit else None,
        "post_phase": clone.phase, "winner": clone.winner,
        "rejection_count_after": clone.attempt - 1,
        "current_failures_after_vote": clone.failures,
        "future_events_injected": 0, "factor_rows": factor_rows,
        "game": clone,
    }


def _mission_outcomes(branch: dict[str, Any]) -> list[dict[str, Any]]:
    """Enumerate legal mission cards from the branch's current mission state."""
    game = branch["game"]
    if game.phase != "mission":
        return []
    options = [game.legal_mission_cards(pid) for pid in game.team]
    outcomes = []
    for cards in itertools.product(*options):
        clone = deepcopy(game)
        card_map = dict(zip(clone.team, cards))
        clone.resolve_mission(card_map)
        outcomes.append({
            "cards": card_map,
            "success": bool(clone.successes > game.successes),
            "fail_count": sum(card == "FAIL" for card in cards),
            "failures_after": clone.failures,
            "successes_after": clone.successes,
            "third_mission_failure": int(clone.failures >= 3),
            "winner": clone.winner,
        })
    return outcomes


def _safety_summary(branch: dict[str, Any], *, baseline_approved: bool,
                    known_evil_on_team: list[str], mission_outcomes: list[dict[str, Any]]) -> dict[str, Any]:
    game = branch["game"]
    approved = bool(branch.get("proposal_approved"))
    clean_delay = int(baseline_approved and not approved and not known_evil_on_team)
    return {
        "proposal_approved": approved,
        "rejection_count_after": branch.get("rejection_count_after"),
        "fifth_rejection_loss": int(branch.get("winner") == "EVIL" and not approved),
        "clean_team_delayed": clean_delay,
        "mission_success_possible": (None if not mission_outcomes else int(any(o["success"] for o in mission_outcomes))),
        "mission_failure_possible": (None if not mission_outcomes else int(any(o["fail_count"] > 0 for o in mission_outcomes))),
        "third_mission_failure_possible": (None if not mission_outcomes else int(any(o["third_mission_failure"] for o in mission_outcomes))),
        "mission_outcome_count": len(mission_outcomes),
        "known_evil_on_team": known_evil_on_team,
        "terminal_status": branch.get("winner") or branch["game"].phase,
        "safety_status": "FAIL" if branch.get("winner") == "EVIL" else ("UNRESOLVED" if clean_delay else "OBSERVED_BOUNDARY_ONLY"),
        "safety_basis": "legal mission-card enumeration" if mission_outcomes else "vote boundary; no future event injected",
    }


def _case_rows(record: dict[str, Any], case: dict[str, Any], *, primary_other: dict[str, bool]) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    actor = str(case["intervention_actor_id"])
    measurement = str(case["measurement_observer_id"])
    role_map = p1._roles(record)
    game, _ = p1._replay_to_cutoff(record, int(case["cutoff_seq"]))
    actor_view = p1._public_view(game, actor)
    candidate_vote, policy = p1._candidate_vote_decision(game, actor_view)
    source_decision = record["decisions"][int(case["decision_index"])]
    baseline_vote = bool(source_decision["action"]["approve"])
    baseline_strong = bool(source_decision["action"].get("strong", False))
    if source_decision.get("observer_id") != actor or source_decision.get("after_seq") != case["cutoff_seq"]:
        raise ValueError("source_decision_actor_or_cutoff_mismatch")
    if p1.digest(actor_view) != case["legal_view_hash"]:
        raise ValueError("merlin_legal_view_hash_mismatch")
    baseline = _simulate_vote(record, case, actor_vote=baseline_vote, actor_strong=baseline_strong,
                              other_ballots=primary_other, measurement_id=measurement)
    candidate = _simulate_vote(record, case, actor_vote=candidate_vote, actor_strong=baseline_strong,
                               other_ballots=primary_other, measurement_id=measurement)
    if baseline["factor_consumed"] != 1 or candidate["factor_consumed"] != 1:
        raise ValueError("candidate_vote_factor_not_consumed_once")
    before = baseline["before"]
    effect = {
        "pair_id": f"{case['source_run_id']}:{case['game_id']}:{actor}->{measurement}:{case['decision_index']}",
        "source_run_id": case["source_run_id"], "game_id": case["game_id"],
        "scenario_id": case["scenario_id"], "round": game.round, "attempt": game.attempt,
        "intervention_actor_id": actor, "measurement_observer_id": measurement,
        "baseline_vote": baseline_vote, "candidate_vote": candidate_vote,
        "baseline_strong": baseline_strong, "policy_mode": policy["mode"],
        "public_suspicion_score": policy["public_suspicion_score"],
        "assassin_true_merlin_p_before": before["true_merlin_probability"],
        "assassin_true_merlin_p_baseline_after": baseline["after"]["true_merlin_probability"],
        "assassin_true_merlin_p_candidate_after": candidate["after"]["true_merlin_probability"],
        "delta_p_merlin": candidate["after"]["true_merlin_probability"] - baseline["after"]["true_merlin_probability"],
        "rank_baseline": baseline["after"]["true_merlin_rank"], "rank_candidate": candidate["after"]["true_merlin_rank"],
        "delta_rank": candidate["after"]["true_merlin_rank"] - baseline["after"]["true_merlin_rank"],
        "lead_baseline": baseline["after"]["merlin_lead"], "lead_candidate": candidate["after"]["merlin_lead"],
        "delta_lead": candidate["after"]["merlin_lead"] - baseline["after"]["merlin_lead"],
        "exact_top_baseline": _json(baseline["after"]["exact_top"]),
        "exact_top_candidate": _json(candidate["after"]["exact_top"]),
        "delta_exact_top": int(baseline["after"]["exact_top"] != candidate["after"]["exact_top"]),
        "factor_signal_id": candidate["factor_signal_id"],
        "factor_consumed_baseline": baseline["factor_consumed"], "factor_consumed_candidate": candidate["factor_consumed"],
        "duplicate_suppressed_baseline": baseline["duplicate_suppressed"],
        "duplicate_suppressed_candidate": candidate["duplicate_suppressed"],
        "future_events_injected": 0, "valid_pair": 1,
        "mechanism_consistent_evidence": 1, "causal_paired_evidence": 1,
    }
    known_evil_on_team = sorted(pid for pid in game.team if pid in set(actor_view.get("known_evil", [])))
    baseline_missions = _mission_outcomes(baseline)
    candidate_missions = _mission_outcomes(candidate)
    safety = _safety_summary(candidate, baseline_approved=bool(baseline.get("proposal_approved")),
                             known_evil_on_team=known_evil_on_team, mission_outcomes=candidate_missions)
    safety.update({"pair_id": effect["pair_id"], "source_run_id": case["source_run_id"], "game_id": case["game_id"],
                   "intervention_actor_id": actor, "measurement_observer_id": measurement,
                   "baseline_mission_outcome_count": len(baseline_missions), "candidate_mission_outcome_count": len(candidate_missions),
                   "baseline_vote": baseline_vote, "candidate_vote": candidate_vote,
                   "policy_mode": policy["mode"], "truth_used_by_agent": 0, "truth_used_by_scorer": 1})
    interventions = []
    for arm, branch in (("baseline", baseline), ("candidate", candidate)):
        interventions.append({"pair_id": effect["pair_id"], "arm": arm, "branch": arm,
                              "source_run_id": case["source_run_id"], "game_id": case["game_id"],
                              "intervention_actor_id": actor, "measurement_observer_id": measurement,
                              "merlin_vote": branch["vote"], "strong": branch["strong"],
                              "proposal_approved": branch["proposal_approved"],
                              "p_merlin_after": branch["after"]["true_merlin_probability"],
                              "rank_after": branch["after"]["true_merlin_rank"],
                              "lead_after": branch["after"]["merlin_lead"],
                              "exact_top_after": _json(branch["after"]["exact_top"]),
                              "factor_signal_id": branch["factor_signal_id"], "factor_consumed": branch["factor_consumed"],
                              "duplicate_suppressed": branch["duplicate_suppressed"], "policy_mode": policy["mode"],
                              "mission_outcome_count": len(baseline_missions if arm == "baseline" else candidate_missions),
                              "future_events_injected": 0, "valid_pair": 1})
    return effect, interventions, [safety]


def _sensitivity(out: Path, records: dict[tuple[str, str], dict[str, Any]], cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for case in cases:
        record = records[(case["source_run_id"], case["game_id"])]
        game, _ = p1._replay_to_cutoff(record, int(case["cutoff_seq"]))
        actor = case["intervention_actor_id"]
        view = p1._public_view(game, actor)
        candidate_vote, policy = p1._candidate_vote_decision(game, view)
        other_ids = [pid for pid in game.ids if pid != actor]
        for bits in itertools.product((False, True), repeat=len(other_ids)):
            other = dict(zip(other_ids, bits))
            branch = _simulate_vote(record, case, actor_vote=candidate_vote,
                                    actor_strong=bool(record["decisions"][int(case["decision_index"])]["action"].get("strong", False)),
                                    other_ballots=other, measurement_id=case["measurement_observer_id"])
            outcomes = _mission_outcomes(branch)
            rows.append({"pair_id": f"{case['source_run_id']}:{case['game_id']}:{actor}->{case['measurement_observer_id']}:{case['decision_index']}",
                         "other_ballots": _json(other), "candidate_vote": candidate_vote,
                         "policy_mode": policy["mode"], "proposal_approved": branch["proposal_approved"],
                         "fifth_rejection_loss": int(branch["winner"] == "EVIL"),
                         "mission_failure_possible": None if not outcomes else int(any(o["fail_count"] > 0 for o in outcomes)),
                         "third_mission_failure_possible": None if not outcomes else int(any(o["third_mission_failure"] for o in outcomes)),
                         "future_events_injected": 0})
    p1._write_csv(out / "candidate_safety_sensitivity.csv", rows)
    return rows


def run(out: Path) -> dict[str, Any]:
    out = Path(out).resolve()
    source = p1.ROOT / "results/joint_belief_v2_3_2/20260919-v232-r2-p1-offline-v12"
    cases = (p1._read_json(source / "p1_preregistered_cases.json", {}) or {}).get("cases", [])
    records, _ = p1._source_records()
    effects, interventions, safety = [], [], []
    invalid = []
    for case in cases:
        try:
            actor = str(case["intervention_actor_id"])
            record = records[(case["source_run_id"], case["game_id"])]
            primary_other = dict(case["other_ballots"])
            effect, irows, srows = _case_rows(record, case, primary_other=primary_other)
            effects.append(effect); interventions.extend(irows); safety.extend(srows)
        except Exception as exc:
            invalid.append({"case": case, "reason": f"{type(exc).__name__}:{exc}"})
    sens = _sensitivity(out, records, cases) if not invalid else []
    p1._write_csv(out / "candidate_assassin_effect.csv", effects)
    p1._write_csv(out / "candidate_vote_interventions.csv", interventions)
    p1._write_csv(out / "candidate_safety_tradeoff.csv", safety)
    meaningful = [row for row in effects if abs(float(row["delta_p_merlin"])) > EPSILON
                  or int(row["delta_rank"]) != 0 or abs(float(row["delta_lead"])) > EPSILON
                  or int(row["delta_exact_top"])]
    hard_fail = [row for row in safety if row["fifth_rejection_loss"] or row["third_mission_failure_possible"]]
    unresolved = [row for row in safety if row["clean_team_delayed"]
                  or (row["candidate_vote"] != row["baseline_vote"]
                      and row["mission_failure_possible"] is None)]
    if invalid:
        gate = "INVALID_MEASUREMENT"
    elif hard_fail:
        gate = "CANDIDATE_EFFECT_BUT_UNSAFE"
    elif meaningful and unresolved:
        gate = "CANDIDATE_EFFECT_BUT_UNSAFE"
    elif meaningful:
        gate = "CANDIDATE_PROMISING_OFFLINE"
    else:
        gate = "CANDIDATE_NO_EFFECT"
    result = {"run_id": out.name, "source_run_id": source.name, "candidate": "MerlinVoteCamouflageV1",
              "gate": gate, "network_calls": 0, "cases": len(cases), "valid_pairs": len(effects),
              "invalid_pairs": len(invalid), "meaningful_effect_pairs": len(meaningful),
              "safety_status": "FAIL" if hard_fail else ("UNRESOLVED" if unresolved else "OBSERVED_BOUNDARY_ONLY"),
              "hard_safety_failures": len(hard_fail), "unresolved_safety_rows": len(unresolved),
              "sensitivity_rows": len(sens), "full_game_effect": "NOT_TESTED",
              "production_promotion": "BLOCKED", "candidate_enabled": False,
              "future_events_injected": 0, "invalid_reasons": invalid}
    p1._write_json(out / "candidate_safety_gate.json", result)
    p1._write_text(out / "safety_report.md", f"""# MerlinVoteCamouflageV1 safety audit

Run `{out.name}`; source `{source.name}`; network calls `0`.

The baseline uses the recorded Merlin boolean vote and recorded `strong` modifier at each of the same six cutoffs. The candidate uses the frozen policy from `candidate_spec.md`. Other ballots are held to the preregistered values. No historical future event is replayed after a branch diverges.

The candidate gate is `{gate}`. There are `{len(effects)}` valid paired cutoffs, `{len(meaningful)}` meaningful Assassin-side effects, `{len(hard_fail)}` hard safety failures, and `{len(unresolved)}` unresolved safety rows. Approved branches enumerate only legal mission cards at the immediate mission boundary; rejected branches stop and keep downstream values unknown. The 16-vector sensitivity table is diagnostic and is not an independent game sample.

No API, full game, discussion continuation, assassination, candidate enablement, or production change occurred.
""")
    return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    args = parser.parse_args()
    print(json.dumps(run(Path(args.run_dir)), indent=2, sort_keys=True))
