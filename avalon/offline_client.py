"""Deterministic local model boundary for browser smoke play.

This is deliberately separate from the real ChatClient and performs no network
access. It returns only the structured fields that Agent validates.
"""
from copy import deepcopy


def _statement_for(view, legal_actions=()):
    """Return a phase-appropriate public line for the deterministic smoke client.

    The offline client is a local stand-in for the provider boundary. It must
    still respect the current public task so that browser smoke play does not
    make every phase sound like a pending vote.
    """
    phase = view.get("phase")
    if phase == "team":
        return "我先根据当前任务规则和候选队伍提出方案。"
    if phase == "council_discussion":
        return "我先根据已公开的任务结果和记录调整判断。"
    if phase in {"discussion", "challenge", "reaction", "revision"}:
        return "我先根据当前公开记录和队伍状态行动。"
    if any(isinstance(option, dict) and option.get("kind") in {"VOTE", "STRONG_VOTE"}
           for option in legal_actions):
        return "我按当前公开的投票选项作出选择。"
    return "我按当前阶段的公开规则行动。"


def _plan(view, legal_actions=()):
    players = [p["id"] for p in view["players"]]
    # bounded_game_view exposes the seat as ``self``. Keep ``self_id`` as a
    # compatibility fallback for direct callers of this small test boundary.
    self_id = view.get("self", view.get("self_id", ""))
    target = next((pid for pid in players if pid != self_id), players[0])
    return {
        "beliefs": {pid: {"evil": 0.3, "merlin": 0.2} for pid in players},
        "profiles": {pid: {"aggression": 0.4, "retaliation": 0.3, "approval": 0.5, "consensus": 0.5}
                     for pid in players},
        "strategy": "probe",
        "team_rank": list(reversed(players)),
        "vote_threshold": 0.9,
        "approve_last": True,
        "mission": "SUCCESS",
        "social": {
            "card": "HEDGE", "target": target, "reason": "observe",
            "statement": _statement_for(view, legal_actions),
            "rationale": "离线联调不调用外部模型。",
            "evidence": [],
        },
        "assassin_rank": players,
    }


class OfflineClient:
    """Provider-shaped client used only by the explicit offline web mode."""

    def complete(self, context):
        decision = context.get("decision")
        if decision == "exile_nomination":
            candidates = context["game"].get("exile_candidates", [])
            return {"target": candidates[0]}
        if decision == "exile_vote":
            return {"choice": "ABSTAIN"}
        if decision == "window":
            # Zero-cost silence is always the safe legal response in the
            # challenge/reaction windows used by the offline smoke client.
            allowed = context["game"].get("legal_actions", [])
            if "DECLINE" in allowed:
                return {"action": {"kind": "DECLINE"}}
            if "SKIP" in allowed:
                return {"action": {"kind": "SKIP"}}
            raise ValueError("Offline window has no legal silence action")
        if "tactical" in context:
            tactical = context["tactical"]
            return {"social": {
                "card": tactical["allowed_cards"][0],
                "target": tactical["primary_target"],
                "reason": "observe",
                "statement": _statement_for(context["game"], context.get("legal_actions", ())),
                "rationale": "离线联调不调用外部模型。",
                "evidence": [],
            }}
        return deepcopy(_plan(context["game"], context.get("legal_actions", ())))
