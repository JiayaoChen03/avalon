"""Opt-in browser discussion guidance; the engine and model decoder stay authoritative.

This module describes one current turn to a model and rejects a policy-violating
plan. It never creates, rewrites, or publishes an action. The policy identifier
is kept in the host configuration and is deliberately absent from model input.
"""

from copy import deepcopy

from .chronicle import EVIDENCE_KINDS, record_id
from .engine import CARDS, EVIL_ROLES, RESOLVE_COSTS


_PHASES = {"team", "discussion", "council_discussion"}
_DISCUSSION_PHASES = {"discussion", "council_discussion"}
_STRATEGIES = ["observe", "probe", "protect", "misdirect"]
_REASONS = ["observe", "support", "test_reaction", "team_risk", "strategy"]
_VOTE_EVIDENCE = {"VOTE", "TEAM_VOTE", "STRONG_VOTE", "EXILE_VOTE", "EXILE_RESULT"}


def _object(properties):
    return {"type": "object", "properties": properties,
            "required": list(properties), "additionalProperties": False}


def _public_evidence(context):
    """Mirror the public sources of Agent._public_context, without host truth."""
    game = context.get("game", {})
    memory = context.get("agent_memory", {})
    tactical = context.get("tactical", {})
    rows = (game.get("recent_events", []) + game.get("focused_events", [])
            + memory.get("working_memory", []) + context.get("retrieved_chronicle", [])
            + tactical.get("relevant_public_events", []))
    for observation in context.get("observations", []):
        if not isinstance(observation, dict) or not isinstance(observation.get("payload"), dict):
            continue
        rows.append({"seq": observation.get("seq"), "round": observation.get("round"),
                     "attempt": observation.get("proposal"), "actor": observation.get("actor"),
                     "target": observation.get("target"), **observation["payload"]})
    evidence = {}
    for row in rows:
        if not isinstance(row, dict) or row.get("kind") not in EVIDENCE_KINDS:
            continue
        rid = row.get("record_id")
        if not isinstance(rid, str) and type(row.get("round")) is int and type(row.get("seq")) is int:
            rid = record_id(row)
        if isinstance(rid, str):
            evidence[rid] = row["kind"]
    return evidence


def _speech_available(view):
    return (view.get("phase") in _DISCUSSION_PHASES
            and "SOCIAL" in view.get("legal_actions", ())
            and view["resolve"][view["self"]] >= RESOLVE_COSTS["SOCIAL"])


def _social_schema(view, context, ids, evidence, managed):
    reasons = list(_REASONS)
    if any(kind == "MISSION" for kind in evidence.values()):
        reasons.append("mission_record")
    if any(kind in _VOTE_EVIDENCE for kind in evidence.values()):
        reasons.append("vote_pattern")
    if view["attempt"] == view["rules"]["max_proposals"]:
        reasons.append("last_chance")
    cards, targets = list(CARDS), ids
    if managed:
        tactical = context.get("tactical")
        if not isinstance(tactical, dict):
            raise ValueError("Invalid resource action")
        target = tactical.get("primary_target")
        allowed = tactical.get("allowed_cards")
        if target not in ids or not isinstance(allowed, list) or not allowed or any(card not in CARDS for card in allowed):
            raise ValueError("Invalid resource action")
        targets, cards = [target], list(dict.fromkeys(allowed))
    citations = ({"type": "array", "items": {"enum": list(evidence)},
                  "maxItems": 3, "uniqueItems": True} if evidence else
                 {"type": "array", "items": {"type": "string"}, "maxItems": 0})
    return _object({
        "card": {"enum": cards}, "target": {"enum": targets},
        "reason": {"enum": reasons},
        "public_writing": {"type": "string", "minLength": 1, "maxLength": 240},
        "citations": citations,
    })


def _revision_schema(view, *, speech_required):
    lock = _object({"kind": {"const": "LOCK"}})
    remaining = view["resolve"][view["self"]] - int(speech_required)
    if (view["phase"] != "discussion" or view["leader"] != view["self"]
            or remaining < RESOLVE_COSTS["REVISE"]):
        return lock
    replacements = [p["id"] for p in view["players"] if p["id"] not in view["team"]]
    if not view["team"] or not replacements:
        return lock
    return {"oneOf": [lock, _object({
        "kind": {"const": "REVISE"}, "removed": {"enum": list(view["team"])},
        "added": {"enum": replacements},
    })]}


def _action_schema(view, context, *, managed, ids, evidence):
    phase = view["phase"]
    speech_required = _speech_available(view)
    if phase == "team" or not speech_required:
        social = {"type": "null"}
        discussion = _object({"kind": {"const": "PASS"}})
    else:
        social = _social_schema(view, context, ids, evidence, managed)
        discussion = _object({"kind": {"const": "SOCIAL"}})
    revision = _revision_schema(view, speech_required=speech_required)
    strong_vote = {"type": "boolean"} if phase == "discussion" else {"const": False}
    if managed:
        return _object({"social": social, "discussion": discussion,
                        "revision": revision, "strong_vote": strong_vote})
    rank = {"type": "array", "items": {"enum": ids}, "minItems": len(ids),
            "maxItems": len(ids), "uniqueItems": True}
    missions = ["SUCCESS", "FAIL"] if view["role"] in EVIL_ROLES else ["SUCCESS"]
    return _object({
        "strategy": {"enum": _STRATEGIES}, "team_rank": rank,
        "vote_threshold": {"type": "number", "minimum": 0, "maximum": 1},
        "approve_last": {"type": "boolean"}, "mission": {"enum": missions},
        "social": social, "assassin_rank": rank, "discussion": discussion,
        "revision": revision, "strong_vote": strong_vote,
    })


def _turn_instruction(view, *, managed=False):
    if view["phase"] == "team":
        lead = ("The code has already selected planned_action.team. " if managed else
                "Choose the team's ranking now. ")
        return (lead + "The discussion and writing fields are provisional here: "
                'discussion={"kind":"PASS"}, social=null, '
                'revision={"kind":"LOCK"}. '
                "A later discussion turn requests its own model-authored writing.")
    if _speech_available(view):
        return ('For this discussion turn, submit discussion={"kind":"SOCIAL"} and a non-null '
                "social object with your own public_writing. Write 1-3 concise Chinese sentences "
                "about the current team or preceding public discussion: a qualified observation, "
                "stance, or question. If evidence is limited, express uncertainty or ask a question "
                "rather than stay silent. Do not invent events, disclose private roles or tactics, "
                "or repeat earlier wording verbatim. citations=[] is valid without supporting "
                "records. This costs one Resolve. Do not choose PASS, HOLD, CITE, CHALLENGE, "
                "or COMMITTED_SOCIAL here.")
    return ("No affordable SOCIAL action is available for this discussion turn. "
            'Submit discussion={"kind":"PASS"}, social=null, and public_stance_change=null.')


def engaged_context(view, context, *, managed):
    """Return only code-owned current-turn guidance for the optional live policy."""
    if view["phase"] not in _PHASES:
        return {}
    ids = [p["id"] for p in view["players"]]
    evidence = _public_evidence(context)
    action = _action_schema(view, context, managed=managed, ids=ids, evidence=evidence)
    if evidence:
        interpretation = {"type": "array", "maxItems": 4, "items": _object({
            "evidence": {"type": "array", "items": {"enum": list(evidence)},
                         "minItems": 1, "maxItems": 3, "uniqueItems": True},
            "summary": {"type": "string", "minLength": 1, "maxLength": 240},
        })}
    else:
        interpretation = {"type": "array", "maxItems": 0}
    if _speech_available(view):
        stance_targets = (action["properties"]["social"]["properties"]["target"]["enum"])
        stance = {"anyOf": [{"type": "null"}, _object({
            "target": {"enum": stance_targets},
            "stance": {"enum": ["SUSPICIOUS", "TRUST", "UNCERTAIN", "QUESTIONING"]},
        })]}
    else:
        stance = {"type": "null"}
    return {
        "current_turn_instruction": _turn_instruction(view, managed=managed),
        "response_contract": {
            "purpose": ("For the final action, return one JSON instance of schema, not the schema "
                        "itself. No extra fields. If a separate memory or language-evidence pass "
                        "is pending, complete that pass first. A non-null public_stance_change "
                        "must match the social card and target: ACCUSE=SUSPICIOUS, DEFEND=TRUST, "
                        "HEDGE/BAIT=UNCERTAIN, PRESSURE=QUESTIONING. Use null if no stance is "
                        "intended. The engine still validates legality."),
            "schema": _object({
                "belief_updates": {"type": "array", "maxItems": 0},
                "interpretation": interpretation,
                "public_stance_change": stance,
                "recommended_action": action,
                "short_rationale": {"type": "string", "minLength": 1, "maxLength": 240},
            }),
        },
    }


def validate_engaged_discussion(plan, view):
    """Reject a non-speaking plan; never turn silence or a draft into speech."""
    if view["phase"] not in _DISCUSSION_PHASES:
        return
    if not isinstance(plan, dict) or not isinstance(plan.get("discussion"), dict):
        raise ValueError("Invalid resource action")
    kind = plan["discussion"].get("kind")
    if _speech_available(view):
        if kind != "SOCIAL" or not isinstance(plan.get("social"), dict):
            raise ValueError("Invalid resource action")
    elif kind != "PASS" or plan.get("social") is not None:
        raise ValueError("Invalid resource action")


def engaged_retry_feedback(feedback, view):
    """Keep validation feedback while removing its conflicting PASS suggestion."""
    result = deepcopy(feedback) if isinstance(feedback, dict) else {}
    if view["phase"] not in _DISCUSSION_PHASES:
        return result
    rule = result.get("rule")
    rule = rule if isinstance(rule, str) else ""
    rule = rule.replace("Use PASS to conserve.", "")
    rule = rule.replace("or PASS if no valid event supports CHALLENGE/CITE.", "")
    result["rule"] = (rule.strip() + " " + _turn_instruction(view)).strip()
    return result
