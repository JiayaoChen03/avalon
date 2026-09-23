"""Offline-only MerlinVoteCamouflageV5SymmetricSafetyGuard candidate.

V5 is a separate candidate implementation layered on the frozen V4 policy.
It preserves V4's clean-team guard and adds one symmetric safety guard: a
mission-safety REJECT cannot be changed to APPROVE by public consensus.  This
module does not modify V3, V4, or production behavior.
"""

from __future__ import annotations

from typing import Any

from avalon.eval.v2 import v232_candidate_v2 as v2
from avalon.eval.v2 import v232_candidate_v3 as v3


CANDIDATE = "MerlinVoteCamouflageV5SymmetricSafetyGuard"
CRITICAL_REJECTIONS = v3.CRITICAL_REJECTIONS
CRITICAL_FAILURES = v3.CRITICAL_FAILURES


def candidate_vote_decision(
    public_state: v2.PublicVoteState,
    actor_view: dict[str, Any],
) -> tuple[bool, dict[str, Any]]:
    """Apply the frozen V4 control flow plus the preregistered V5 guard."""
    if not isinstance(public_state, v2.PublicVoteState):
        raise TypeError("candidate requires restricted PublicVoteState")
    team = list(public_state.team)
    known_evil = set(actor_view.get("known_evil", []))
    known_evil_on_team = sorted(pid for pid in team if pid in known_evil)
    rejection_count = sum(
        1 for event in public_state.events
        if event.get("kind") == "TEAM_VOTE" and not event.get("approved")
    )
    warning_count, warning_components = v3._public_warning_count(public_state, team)
    mission_safety_vote = not bool(known_evil_on_team)
    public_consensus_vote = warning_count < 1
    critical = rejection_count >= CRITICAL_REJECTIONS or int(public_state.failures) >= CRITICAL_FAILURES

    # Existing V4 invariant: a clean mission-safety approval cannot be
    # overridden by PUBLIC_CONSENSUS.
    if not known_evil_on_team and mission_safety_vote:
        vote, mode = True, "CLEAN_TEAM_SAFETY_GUARD"
    # The single preregistered V5 change.  Existing dirty rows that already
    # reject remain reject; the branch also blocks the 20 reverse overrides.
    elif mission_safety_vote is False:
        vote, mode = False, "SYMMETRIC_SAFETY_GUARD"
    elif critical:
        vote, mode = mission_safety_vote, "CRITICAL_MISSION_SAFETY"
    elif public_consensus_vote != mission_safety_vote:
        vote, mode = public_consensus_vote, "PUBLIC_CONSENSUS"
    else:
        vote, mode = mission_safety_vote, "MISSION_SAFETY_DEFAULT"
    return bool(vote), {
        "policy_version": CANDIDATE,
        "mode": mode,
        "critical": int(critical),
        "guard_triggered": int(not known_evil_on_team and mission_safety_vote),
        "symmetric_guard_triggered": int(mission_safety_vote is False),
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
