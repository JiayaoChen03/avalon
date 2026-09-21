"""Joint Belief v2.3 Merlin public-action aid.

This module is deliberately a small policy-context extension.  It does not
change the joint posterior, the legal menu, the Game transition, or the
assassin's native probability argmax.  The aid is constructed only from the
Merlin seat's legal view and the public event projection already supplied to
that seat.
"""
from copy import deepcopy
from datetime import datetime, timezone
import threading
import time

from avalon.eval.simulation import canonical, digest
from avalon.eval.v2.v21_contract import menu_context, decode_menu, legal_menu
from avalon.eval.v2.v21_runtime import MenuClient, Cancelled, atomic_json
from avalon.eval.v2.v21_contract import ADAPTER_REVISION
from avalon.eval.v2.v21_audit import failure_class
from avalon.llm import LLMError


MERLIN_DISCLOSURE_REVISION = "merlin-disclosure-v23-r1"
PUBLIC_ACTION_PHASES = frozenset({"discussion", "council_discussion"})
_PRIVATE_KEYS = frozenset({
    "roles", "truth", "referee", "posterior", "assassin_posterior",
    "assassin_internal_posterior", "reasoning_content", "future_events",
})


def _event_rows(context):
    """Return the current public prefix, deduplicated by real record ID."""
    view = context["view"]
    rows = list(view.get("legal_public_history", []))
    rows.extend(view.get("recent_events", []))
    rows.extend(context.get("public_event_history", []))
    seen = {}
    for event in rows:
        rid = event.get("record_id")
        if not isinstance(rid, str):
            continue
        # A legal public projection can occur through more than one bounded
        # view field.  Preserve the first exact event and never merge fields.
        seen.setdefault(rid, deepcopy(event))
    return sorted(seen.values(), key=lambda e: (int(e.get("seq", 0)), e["record_id"]))


def _public_evidence_index(context):
    """Build compact, typed public support without turning claims into facts."""
    view = context["view"]
    rules = view["rules"]
    events = _event_rows(context)
    supports = []
    claims = []
    for event in events:
        rid, kind = event["record_id"], event.get("kind")
        if kind == "MISSION":
            team = sorted(event.get("team", []))
            fail_threshold = event.get("fail_threshold", rules.get("fail_threshold", 1))
            fail_count = event.get("fail_count")
            if event.get("success") is False or (isinstance(fail_count, int) and fail_count >= fail_threshold):
                supports.append({
                    "claim": "该公开任务队伍至少有一名坏阵营成员",
                    "basis": "public_rule_constraint",
                    "event_ids": [rid],
                    "team": team,
                    "does_not_establish": "任一特定成员的确定身份",
                })
            elif event.get("success") is True:
                supports.append({
                    "claim": "该公开任务结果为成功",
                    "basis": "public_mission_result",
                    "event_ids": [rid],
                    "team": team,
                    "does_not_establish": "全队好人或任一成员的确定身份",
                })
        elif kind in {"SOCIAL", "REACT", "CHALLENGE_RESPONSE", "CHALLENGE", "CITE"}:
            actor = event.get("actor")
            target = event.get("target")
            if actor and (target or event.get("public_writing") or event.get("statement")):
                claims.append({
                    "event_id": rid,
                    "actor": actor,
                    "target": target,
                    "kind": kind,
                    "card": event.get("card"),
                    "claim_status": "public_claim_not_role_fact",
                })
    # Keep the aid deterministic and bounded.  Event IDs are real IDs, sorted
    # by chronology, and no private role labels are copied into the result.
    claims = claims[-4:]
    supports = supports[-4:]
    score = view.get("successes", 0), view.get("failures", 0)
    own_actions = [e for e in events if e.get("actor") == view.get("self")
                   and e.get("kind") in {"SOCIAL", "REACT", "CHALLENGE_RESPONSE"}]
    own = [{"event_id": e["record_id"], "card": e.get("card"), "target": e.get("target"),
            "citations": list(e.get("citations", []))[:3]} for e in own_actions[-2:]]
    return {
        "status": "decision_aid_not_assassination_probability",
        "scope": "current_public_social_action_only",
        "public_support": supports,
        "public_claims": claims,
        "private_public_gap": "个人判断可以比公开依据更具体；公开陈述仍是 claim，不是身份事实",
        "mission_priority": "保留任务贡献；紧迫风险可以支持强表达，但不捏造公共事件",
        "prior_public_actions": own,
        "public_score": {"successes": score[0], "failures": score[1]},
        "guidance": (
            "保持代码提供的私有判断不变。公开记录支持的结论可以正常表达；不要把仅由私有知识"
            "得到的精确身份判断反复包装成公开事实。多个合法表达同样有用时，可选择较少暴露特权"
            "知识的表达。不要固定沉默或 HEDGE，不要忽略迫在眉睫的失败，按现有契约选择合法动作。"
        ),
    }


def _assert_public_only(aid):
    """Fail closed if a future edit accidentally places private fields in the aid."""
    def walk(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in _PRIVATE_KEYS:
                    raise ValueError(f"private field in MerlinDisclosureContext: {key}")
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
    walk(aid)
    return aid


def build_merlin_disclosure_context(context):
    """Return the candidate aid, or an empty marker outside Merlin SOCIAL."""
    view = context["view"]
    if view.get("role") != "MERLIN" or view.get("phase") not in PUBLIC_ACTION_PHASES:
        return None
    aid = _public_evidence_index(context)
    _assert_public_only(aid)
    if len(canonical(aid).encode("utf-8")) > 2048:
        # Compression is deterministic and drops only descriptive claims, never
        # the legal menu or current state.  The first public constraints survive.
        aid["public_claims"] = aid["public_claims"][-2:]
        aid["prior_public_actions"] = aid["prior_public_actions"][-1:]
        aid["guidance"] = aid["guidance"][:600]
    if len(canonical(aid).encode("utf-8")) > 2048:
        raise ValueError("Merlin disclosure context exceeds 2KB")
    return aid


def menu_context_v23(context, policy, enabled=False):
    """Build the frozen v2.1 menu plus one opt-in Merlin private aid."""
    result = menu_context(context, policy)
    if enabled:
        aid = build_merlin_disclosure_context(context)
        if aid is not None:
            result["merlin_disclosure_context"] = aid
    return result


class MerlinMenuClient(MenuClient):
    """MenuClient with an opt-in context hook, reusing the frozen transport ledger."""

    def __init__(self, settings, budget, metadata, policy, enabled=False,
                 cancel=None, journal=None, disclosure_journal=None):
        super().__init__(settings, budget, metadata, policy, cancel)
        self.enabled = bool(enabled)
        self.journal = journal
        self.disclosure_journal = disclosure_journal

    def _write_disclosure(self, context, supplied):
        if self.disclosure_journal is None:
            return
        row = {
            **self.metadata,
            "observer_id": context["view"]["self"],
            "observer_role": context["view"]["role"],
            "phase": context["view"]["phase"],
            "enabled": self.enabled,
            "base_context_hash": digest(menu_context(context, self.policy)),
            "supplied_context_hash": digest(supplied),
            "aid_present": "merlin_disclosure_context" in supplied,
            "aid_hash": digest(supplied["merlin_disclosure_context"])
                if "merlin_disclosure_context" in supplied else None,
            "aid_bytes": len(canonical(supplied.get("merlin_disclosure_context", {})).encode("utf-8")),
        }
        self.disclosure_journal.write(row)

    def complete(self, context):
        self.calls += 1
        self.context_bytes += len(canonical(context).encode("utf-8"))
        supplied = menu_context_v23(context, self.policy, self.enabled)
        self._write_disclosure(context, supplied)
        menu = supplied["action_menu"]
        if len(menu) == 1 and not menu[0]["parameters"]:
            action = deepcopy(menu[0]["action"])
            from avalon.eval.v2.v21_contract import validate_legal_action
            validate_legal_action(action, context["view"])
            return action
        transport_used = corrections_used = attempt = 0
        while True:
            if self.cancel.is_set():
                raise Cancelled("cancelled")
            payload = self.transport.request_payload(supplied)
            meta = {**self.metadata, **self.binding, "adapter_revision": ADAPTER_REVISION,
                    "policy_revision": self.policy, "phase": context["view"]["phase"],
                    "observer_role": context["view"]["role"],
                    "started_utc": datetime.now(timezone.utc).isoformat(),
                    "retry_index": attempt, "transport_retries_used": transport_used,
                    "corrections_used": corrections_used,
                    "context": deepcopy(supplied), "model_context_hash": digest(supplied),
                    "client_cache_hit": False, "merlin_disclosure_revision":
                        MERLIN_DISCLOSURE_REVISION if "merlin_disclosure_context" in supplied else None}
            uid, reservation = self.budget.begin(payload, meta)
            self.external_calls += 1
            row = {**meta, "attempt_uid": uid, "reservation": reservation,
                   "accepted": False, "fallback": False}
            started = time.perf_counter(); error = None
            try:
                raw = self.transport.complete(supplied)
                row["raw_response"] = raw
                action, details = decode_menu(raw, context, supplied)
                row.update(details, accepted=True)
            except (LLMError, ValueError, TypeError, KeyError) as exc:
                error = exc
                reason = str(exc) if not isinstance(exc, LLMError) else exc.validation_reason
                code = str(exc) if isinstance(exc, LLMError) else "invalid_plan"
                row.update(error=code, validation_reason=reason,
                           failure_class=failure_class(code, reason))
            finally:
                telemetry = deepcopy(self.transport.last_call)
                usage = telemetry.get("usage", {})
                accounting = self.budget.settle(reservation, usage, meta["started_utc"])
                row.update(transport=telemetry, **accounting,
                           elapsed_seconds=time.perf_counter() - started,
                           ended_utc=datetime.now(timezone.utc).isoformat())
                self.budget.finish(uid, row)
                if self.journal is not None:
                    self.journal.write(row)
            if error is None:
                return action
            if isinstance(error, LLMError) and str(error).startswith(("http_", "timeout", "connection")):
                if not error.retryable or transport_used >= self.transport_retries:
                    raise error
                transport_used += 1
                self.cancel.wait(min(self.settings.retry_delay * 2 ** (transport_used - 1), 10))
            else:
                if isinstance(error, LLMError) and not error.retryable:
                    raise error
                if corrections_used >= self.corrections:
                    raise RuntimeError("correction_limit: " + str(error))
                corrections_used += 1
                from avalon.eval.v2.v21_contract import correction_feedback
                supplied["validation_feedback"] = {
                    **correction_feedback(row.get("raw_response"), supplied, row["validation_reason"]),
                    "error": row["error"],
                    "rejected_action": row.get("raw_response", {}).get("recommended_action")
                        if isinstance(row.get("raw_response"), dict) else None,
                    "correction_number": corrections_used,
                }
            attempt += 1


class Journal:
    """Thread-safe JSONL journal used by v2.3 without exposing reasoning content."""
    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()

    def write(self, row):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock, self.path.open("a", encoding="utf-8") as stream:
            stream.write(canonical(row) + "\n")
