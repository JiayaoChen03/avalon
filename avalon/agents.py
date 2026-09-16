"""Independent private state and LLM policies refreshed for each speaking turn."""

from collections import deque
from copy import deepcopy
import math
import re
import time

from .engine import (DISCUSSION_ACTIONS, EVIDENCE_KINDS, EVIL_ROLES, RESOLVE_COSTS,
                     SOCIAL_EVENTS, validate_action, validate_social)
from .llm import LLMError


PROFILE_FIELDS = {"aggression", "retaliation", "approval", "consensus"}
STRATEGIES = {"observe", "probe", "protect", "misdirect"}
_ROLE_WORDS = r"(?:邪恶|善良|好人|坏人|刺客|梅林|evil|good|assassin|merlin)"
_PRIVATE_DISCLOSURE = re.compile(
    r"(?:作为|身为|我是|我属于|我扮演|我拿到|我的.{0,4}(?:角色|身份|阵营)|我知道).{0,24}" + _ROLE_WORDS
    + r"|(?:as (?:an? |the )?|i(?: am|'m|’m) (?:on (?:the )?|an? |the )?|my (?:role|alignment) is )" + _ROLE_WORDS
    + r"|known_evil|已知邪恶|私有(?:身份|信息|判断)|private (?:role|belief)", re.IGNORECASE)
_TACTICAL_DISCLOSURE = re.compile(
    r"evil[_ ]?shared[_ ]?state|tactical[_ ]?context|strategy[_ ]?mode|mission[_ ]?fail[_ ]?owner"
    r"|evil_partner|likely_merlin|merlin_probabilities|active_narratives|framed_players|agenda_topic"
    r"|aggressor_agent_id|sleeper_agent_id|partner_agreement_count|partner_defense_count"
    r"|suspicion_scores|trust_scores|pair_suspicion"
    r"|primary[_ ]?objective|secondary[_ ]?objective|distance[_ ]?strength|sacrifice[_ ]?target"
    r"|NORMAL_DECEPTION|FAKE_CONFLICT|CONSENSUS_SEEDING|AGENDA_CAPTURE|MERLIN_HUNT|CRISIS_RECOVERY"
    r"|CREATE_DISTANCE_FROM_PARTNER|MAINTAIN_INDEPENDENCE|SACRIFICE_SELF|SACRIFICE_PARTNER"
    r"|REDUCE_SELF_SUSPICION|REDUCE_PARTNER_SUSPICION|INCREASE_TARGET_SUSPICION|BUILD_TRUST"
    r"|CONTROL_AGENDA|PROBE_MERLIN|SEED_NARRATIVE|REINFORCE_NARRATIVE|CAUSE_UNCERTAINTY"
    r"|MAXIMIZE_PARTNER_SURVIVAL|MAXIMIZE_ENEMY_MISDIRECTION|\bSACRIFICE\b"
    r"|(?:my|our) (?:evil )?(?:partner|teammate)|(?:我的|我方)(?:邪恶)?(?:队友|同伙)"
    r"|战术(?:上下文|指令|目标)|共享(?:状态|战略)|策略管理器|失败票负责人"
    r"|我(?:是|负责|担任).{0,8}(?:潜伏|进攻|aggressor|sleeper)"
    r"|我(?:和|与|跟)\s*P\d+.{0,8}(?:都是|同为|同属).{0,4}(?:坏人|邪恶)", re.IGNORECASE)


def _guard_public_speech(action):
    """Retry disclosures; only validated, model-authored dialogue may be published."""
    for field in ("statement", "rationale"):
        if _PRIVATE_DISCLOSURE.search(action[field]):
            raise LLMError("private_disclosure")


def _probability(value):
    return type(value) in (int, float) and 0 <= value <= 1 and math.isfinite(value)


def validate_plan(raw, ids, public_events=None):
    """Reject malformed model output atomically; no partial private-state updates."""
    fields = {"beliefs", "profiles", "strategy", "team_rank", "vote_threshold",
              "approve_last", "mission", "social", "assassin_rank"}
    resource_fields = {"discussion", "revision", "strong_vote"}
    if not isinstance(raw, dict) or set(raw) not in (fields, fields | resource_fields):
        raise ValueError("Invalid plan keys")
    for section, keys in (("beliefs", {"evil", "merlin"}), ("profiles", PROFILE_FIELDS)):
        values = raw[section]
        if not isinstance(values, dict) or set(values) != set(ids):
            raise ValueError("Invalid player map")
        for record in values.values():
            if (not isinstance(record, dict) or set(record) != keys
                    or not all(_probability(v) for v in record.values())):
                raise ValueError("Invalid probabilities")
            if section == "beliefs" and record["evil"] + record["merlin"] > 1.000001:
                raise ValueError("Inconsistent role probabilities")
    for key in ("team_rank", "assassin_rank"):
        rank = raw[key]
        if (not isinstance(rank, list) or len(rank) != len(ids)
                or any(not isinstance(p, str) for p in rank) or set(rank) != set(ids)):
            raise ValueError("Invalid ranking")
    if (not isinstance(raw["strategy"], str) or raw["strategy"] not in STRATEGIES
            or not _probability(raw["vote_threshold"]) or type(raw["approve_last"]) is not bool
            or raw["mission"] not in ("SUCCESS", "FAIL")):
        raise ValueError("Invalid policy")
    plan = deepcopy(raw)
    plan["social"] = _validate_public_social(plan["social"], ids, public_events)
    _validate_resource_policy(plan, ids, public_events)
    return plan


def _discussion_action(plan):
    action = deepcopy(plan.get("discussion", {"kind": "SOCIAL"}))
    if isinstance(action, dict) and action.get("kind") in ("SOCIAL", "COMMITTED_SOCIAL"):
        action["social"] = deepcopy(plan["social"])
    return action


def _validate_resource_policy(plan, ids, events):
    if "discussion" not in plan:  # Legacy policies still pay the engine's normal cost.
        return
    action = _discussion_action(plan)
    validate_action(action, ids, events or [], require_statement=True)
    if action["kind"] not in DISCUSSION_ACTIONS:
        raise ValueError("Invalid resource action")
    # Social prose is held once in social, never duplicated in the descriptor.
    if "social" in plan["discussion"]:
        raise ValueError("Invalid resource action")
    revision = plan["revision"]
    validate_action(revision, ids, events or [])
    if revision["kind"] not in {"LOCK", "REVISE"}:
        raise ValueError("Invalid resource action")
    if type(plan["strong_vote"]) is not bool:
        raise ValueError("Invalid resource action")


def _validate_public_social(raw, ids, public_events):
    social = deepcopy(raw)
    refs = social.get("evidence") if isinstance(social, dict) else None
    visible = None if public_events is None else {e["seq"] for e in public_events
              if e["kind"] in EVIDENCE_KINDS}
    # Citation formatting should not discard a valid model decision. Never invent a reference.
    if isinstance(refs, list) and all(type(n) is int and n > 0 and (visible is None or n in visible) for n in refs):
        social["evidence"] = list(dict.fromkeys(refs))[:3]
    validate_social(social, ids, public_events, require_statement=True)
    return social


def validate_performance(raw, ids, public_events, tactical):
    """Managed evil may express a tactic, never overwrite strategic state."""
    # Some providers flatten the single social object. Restore only its envelope;
    # every value still goes through the same action, evidence and privacy checks.
    if isinstance(raw, dict) and set(raw) == {"card", "target", "reason", "statement", "rationale", "evidence"}:
        raw = {"social": raw}
    if not isinstance(raw, dict) or set(raw) not in ({"social"}, {"social", "discussion", "revision", "strong_vote"}):
        raise ValueError("Invalid performance keys")
    social = _validate_public_social(raw["social"], ids, public_events)
    if social["target"] != tactical["primary_target"] or social["card"] not in tactical["allowed_cards"]:
        raise ValueError("Social action does not implement the assigned tactic")
    private_labels = [tactical.get(key) for key in
                      ("strategy_mode", "primary_objective", "secondary_objective", "role", "agenda_topic")]
    private_labels.extend(tactical.get("constraints", []))
    private_labels.extend(narrative.get("category") for narrative in tactical.get("active_narratives", [])
                          if isinstance(narrative, dict))
    # Protect code labels and their readable spellings, while allowing public IDs/cards/evidence.
    private_patterns = [re.compile(r"[\s_-]+".join(re.escape(part) for part in re.split(r"[\s_-]+", label.strip())),
                                   re.IGNORECASE)
                        for label in private_labels if isinstance(label, str) and label.strip()]
    for field in ("statement", "rationale"):
        if (_PRIVATE_DISCLOSURE.search(social[field]) or _TACTICAL_DISCLOSURE.search(social[field])
                or any(pattern.search(social[field]) for pattern in private_patterns)):
            raise LLMError("private_disclosure")
    result = {**deepcopy(raw), "social": social, "strategy": tactical["strategy_mode"]}
    _validate_resource_policy(result, ids, public_events)
    return result


class Agent:
    def __init__(self, view, client=None, *, max_retries=2, retry_delay=2.0, evil_strategy=None):
        self.id, self.role = view["self"], view["role"]
        self.ids = [p["id"] for p in view["players"]]
        self.known_evil = set(view["known_evil"])
        self.client = client
        self.max_retries, self.retry_delay = max_retries, retry_delay
        self.memory = {
            "beliefs": {p: {"evil": 2 / (len(self.ids) - 1), "merlin": 0.1} for p in self.ids},
            "profiles": {p: {key: 0.5 for key in sorted(PROFILE_FIELDS)} for p in self.ids},
        }
        self.plan = None
        self.plans, self.sources, self.calls = {}, {}, {}
        self.window_plans = {}
        self.seen_seq = 0
        self.attacks = {}
        self.evidence = deque(maxlen=6)
        self.snapshots = []
        self.last_discussion = None
        self.evil_strategy = None
        self._view = deepcopy(view)
        self.tactical = None
        if evil_strategy is not None:
            self.bind_evil_strategy(evil_strategy)
        self._lock_facts()

    def bind_evil_strategy(self, manager):
        if (self.role not in EVIL_ROLES or self.id not in manager.controlled_evil_ids
                or self.known_evil != set(manager.evil_ids)):
            raise ValueError("Only an authorized evil AI can bind the shared strategy")
        if self.evil_strategy is not None and self.evil_strategy is not manager:
            raise ValueError("An agent cannot change shared strategy mid-game")
        self.evil_strategy = manager

    def update_view(self, view):
        if view["self"] != self.id or view["role"] != self.role:
            raise ValueError("An agent can only receive its own view")
        self._view = deepcopy(view)

    def _lock_facts(self):
        for pid, belief in self.memory["beliefs"].items():
            belief["evil"] = max(0.0, min(1.0, belief["evil"]))
            if pid in self.known_evil:
                belief["evil"], belief["merlin"] = 1.0, 0.0
            elif self.known_evil:
                belief["evil"] = 0.0
            if self.role == "MERLIN":
                belief["merlin"] = float(pid == self.id)
            if pid == self.id:
                belief["evil"] = float(self.role in EVIL_ROLES)
                belief["merlin"] = float(self.role == "MERLIN")
            belief["merlin"] = max(0.0, min(1 - belief["evil"], belief["merlin"]))

    def prepare(self, view, on_retry=None):
        """Retry recoverable failures in place; publish/cache only a validated plan."""
        self.update_view(view)
        round_no = view["round"]
        turn = (round_no, view["attempt"], view["phase"])
        if turn in self.plans:
            self.plan = deepcopy(self.plans[turn])
            return "llm"
        self.plan = None
        if self.client is None:
            raise LLMError("missing_configuration")
        if self.evil_strategy is not None:
            self.tactical = self.evil_strategy.tactical_context(view).to_dict()
            context = {"game": deepcopy(view), "tactical": deepcopy(self.tactical)}
            if view["phase"] == "team":
                context["planned_action"] = {"team": self.evil_strategy.choose_team(view)}
            elif view["phase"] == "discussion" and view["leader"] == self.id:
                context["planned_action"] = {"team": list(view["team"])}
            public_events = view["recent_events"] + view.get("focused_events", []) + self.tactical["relevant_public_events"]
        else:
            has_model_history = bool(self.plans)
            context = {"game": deepcopy(view),
                       "memory": deepcopy(self.memory) if has_model_history else {"beliefs": {}, "profiles": {}},
                       "memory_status": "model_estimates" if has_model_history else "no_previous_model",
                       "evidence": deepcopy(list(self.evidence))}
            public_events = view["recent_events"] + view.get("focused_events", []) + list(self.evidence)
        for attempt in range(self.max_retries + 1):
            self.calls[round_no] = self.calls.get(round_no, 0) + 1
            try:
                raw = self.client.complete(deepcopy(context))
                if self.evil_strategy is not None:
                    plan = validate_performance(raw, self.ids, public_events, self.tactical)
                else:
                    plan = validate_plan(raw, self.ids, public_events)
                    _guard_public_speech(plan["social"])
                if view["phase"] == "discussion" and "discussion" in plan:
                    action = _discussion_action(plan)
                    if (RESOLVE_COSTS[action["kind"]] > view["resolve"][self.id]
                            or action["kind"] == "CHALLENGE" and action["target"] == self.id):
                        raise ValueError("Invalid resource action")
                    revision = plan["revision"]
                    if revision["kind"] == "REVISE" and (self.id != view["leader"]
                            or revision["removed"] not in view["team"] or revision["added"] in view["team"]):
                        raise ValueError("Invalid resource action")
            except (LLMError, ValueError, TypeError) as cause:
                error = cause if isinstance(cause, LLMError) else LLMError("invalid_plan", validation_reason=str(cause))
                if not error.retryable or attempt == self.max_retries:
                    raise error from None
                if error.retry_feedback is not None:
                    context["validation_feedback"] = error.retry_feedback
                delay = min(self.retry_delay * 2 ** attempt, 30.0)
                if on_retry is not None:
                    on_retry(error, attempt + 1, delay)
                time.sleep(delay)
            else:
                break
        if self.evil_strategy is None:
            self.memory = {key: deepcopy(plan[key]) for key in ("beliefs", "profiles")}
        self._lock_facts()
        self.plan = plan
        self.plans[turn] = deepcopy(plan)
        self.sources[round_no] = "llm"
        return "llm"

    def observe(self, event):
        """Update from public facts only; repeated delivery is harmless."""
        if event["seq"] <= self.seen_seq:
            return
        self.seen_seq = event["seq"]
        kind = event["kind"]
        if kind in {"SOCIAL", "PASS", "CHALLENGE", "CITE", "HOLD"} and event.get("actor") == self.id:
            self.last_discussion = deepcopy(event)
        beliefs, profiles = self.memory["beliefs"], self.memory["profiles"]

        def update(pid, field, observed):
            profiles[pid][field] = round(0.75 * profiles[pid][field] + 0.25 * observed, 4)

        if kind in SOCIAL_EVENTS and "card" in event:
            actor, target, card = event["actor"], event["target"], event["card"]
            aggressive = card in {"ACCUSE", "PRESSURE"}
            update(actor, "aggression", float(aggressive))
            if actor in self.attacks:
                attacker = self.attacks.pop(actor)
                update(actor, "retaliation", float(aggressive and target == attacker))
            if card in {"ACCUSE", "PRESSURE", "BAIT"} and actor != target:
                self.attacks[target] = actor
            delta = {"ACCUSE": 0.06, "DEFEND": -0.035, "HEDGE": 0.01}.get(card, 0)
            beliefs[target]["evil"] += delta * (1 - beliefs[actor]["evil"])
            self.evidence.append(deepcopy(event))
        elif kind == "TEAM_VOTE":
            votes = event["votes"]
            approvals = sum(votes.values())
            risk = sum(beliefs[p]["evil"] for p in event["team"]) / len(event["team"])
            for pid, approved in votes.items():
                update(pid, "approval", float(approved))
                if approvals * 2 != len(self.ids):
                    update(pid, "consensus", float(approved == (approvals * 2 > len(self.ids))))
                # Evil knows which teams contain evil; consistent avoidance is a Merlin clue.
                if self.role in EVIL_ROLES and pid not in self.known_evil:
                    dirty = bool(set(event["team"]) & self.known_evil)
                    beliefs[pid]["merlin"] += 0.06 if approved != dirty else -0.025
                elif risk > 0.6 and approved:
                    beliefs[pid]["evil"] += 0.02
        elif kind == "MISSION":
            for pid in event["team"]:
                beliefs[pid]["evil"] += -0.09 if event["success"] else 0.25 / len(event["team"])
            self.evidence.append({k: event[k] for k in ("seq", "round", "kind", "team", "success", "fail_count")})
        elif kind in {"PASS", "CITE", "CHALLENGE", "CHALLENGE_RESPONSE", "HOLD", "TEAM_REVISE", "VOTE"}:
            # Visibility is evidence; spending/commitment never applies a belief bonus.
            self.evidence.append(deepcopy(event))
        self._lock_facts()

    def choose_team(self, size, attempt=1):
        if self.evil_strategy is not None:
            return self.evil_strategy.choose_team(self._view)
        return self.plan["team_rank"][:size]

    def social_action(self):
        return deepcopy(self.plan["social"])

    def discussion_action(self):
        if not self._view["resolve"][self.id]:
            return {"kind": "PASS"}
        return _discussion_action(self.plan)

    def revise_team(self):
        if self._view["resolve"][self.id] < RESOLVE_COSTS["REVISE"]:
            return {"kind": "LOCK"}
        return deepcopy(self.plan.get("revision", {"kind": "LOCK"}))

    def ballot(self, team, attempt):
        return {"approve": self.vote(team, attempt),
                "strong": bool(self.plan.get("strong_vote", False)
                               and self._view["resolve"][self.id] >= RESOLVE_COSTS["STRONG_VOTE"])}

    def window_action(self, on_retry=None):
        """Only an actual response opportunity gets a small, bounded fresh speech call."""
        view = self._view
        allowed = view["legal_actions"]
        if allowed == ["DECLINE"]:
            return {"kind": "DECLINE"}
        if view["phase"] not in {"challenge", "reaction"} or view["next_actor"] != self.id:
            raise ValueError("No response opportunity")
        trigger = view["challenge"]["seq"] if view["challenge"] else view["reaction_trigger"]
        key = (view["round"], view["attempt"], view["phase"], trigger)
        if key in self.window_plans:
            return deepcopy(self.window_plans[key])
        if self.client is None:
            raise LLMError("missing_configuration")
        context = {"game": deepcopy(view), "decision": "window"}
        events = view["recent_events"] + view.get("focused_events", [])
        if self.evil_strategy is not None:
            tactic = self.evil_strategy.tactical_context(view, phase="discussion").to_dict()
            context["tactical"] = tactic
            events += tactic["relevant_public_events"]
        else:
            context["memory"] = deepcopy(self.memory) if self.plans else {"beliefs": {}, "profiles": {}}
            context["memory_status"] = "model_estimates" if self.plans else "no_previous_model"
            context["evidence"] = deepcopy(list(self.evidence))
            events += list(self.evidence)
        for attempt in range(self.max_retries + 1):
            self.calls[view["round"]] = self.calls.get(view["round"], 0) + 1
            try:
                raw = self.client.complete(deepcopy(context))
                if not isinstance(raw, dict) or set(raw) != {"action"}:
                    raise ValueError("Invalid resource action")
                action = raw["action"]
                validate_action(action, self.ids, events, require_statement=True)
                if action["kind"] not in allowed:
                    raise ValueError("Invalid resource action")
                if "social" in action:
                    if self.evil_strategy is not None:
                        validate_performance({"social": action["social"]}, self.ids, events, tactic)
                    else:
                        _guard_public_speech(action["social"])
            except (LLMError, ValueError, TypeError) as cause:
                error = cause if isinstance(cause, LLMError) else LLMError("invalid_plan", validation_reason=str(cause))
                if not error.retryable or attempt == self.max_retries:
                    raise error from None
                if error.retry_feedback is not None:
                    context["validation_feedback"] = error.retry_feedback
                delay = min(self.retry_delay * 2 ** attempt, 30.0)
                if on_retry is not None:
                    on_retry(error, attempt + 1, delay)
                time.sleep(delay)
            else:
                self.window_plans[key] = deepcopy(action)
                return deepcopy(action)

    def vote(self, team, attempt):
        if self.evil_strategy is not None:
            return self.evil_strategy.vote(self._view)
        if attempt == 5 and self.plan["approve_last"]:
            return True
        if self.role in EVIL_ROLES:
            risk = 0.0 if set(team) & self.known_evil else 1.0
        else:
            risk = sum(self.memory["beliefs"][p]["evil"] for p in team) / len(team)
        return risk <= self.plan["vote_threshold"]

    def mission(self, external_cards=None):
        if self.evil_strategy is not None:
            return self.evil_strategy.mission_cards(self._view, external_cards=external_cards)[self.id]
        return self.plan["mission"] if self.role in EVIL_ROLES else "SUCCESS"

    def assassinate(self):
        if self.evil_strategy is not None:
            return self.evil_strategy.assassinate(self._view)
        rank = self.plan["assassin_rank"]
        candidates = [p for p in rank if p not in self.known_evil and p != self.id]
        return max(candidates, key=lambda p: self.memory["beliefs"][p]["merlin"]
                   - 0.04 * rank.index(p))

    def record_snapshot(self, round_no, human_id="P1"):
        self.snapshots.append({"round": round_no,
                               "belief": deepcopy(self.memory["beliefs"][human_id]),
                               "profile": deepcopy(self.memory["profiles"][human_id]),
                               "strategy": self.plan["strategy"],
                               "discussion": deepcopy(self.last_discussion),
                               "social": self.social_action(), "evidence": deepcopy(list(self.evidence))})

    def dossier(self):
        return {"agent": self.id, "snapshots": deepcopy(self.snapshots),
                "calls_by_round": dict(self.calls), "sources": dict(self.sources)}
