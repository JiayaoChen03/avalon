"""Independent private state and LLM policies refreshed for each speaking turn."""

from copy import deepcopy
import math
import re
import time

from .engine import (DISCUSSION_ACTIONS, EVIDENCE_KINDS, EVIL_ROLES, EXILE_CHOICES, RESOLVE_COSTS,
                     SOCIAL_EVENTS, public_social_text, validate_action, validate_social)
from .chronicle import context_record
from .cognition import BeliefEngine
from .discussion_policy import (engaged_context, engaged_retry_feedback,
                                validate_engaged_discussion)
from .llm import LLMError
from .memory import AgentMemory, bounded_game_view


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
    for text in public_social_text(action):
        if _PRIVATE_DISCLOSURE.search(text):
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
    plan["social"] = _validate_planned_social(plan, ids, public_events)
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


def _validate_planned_social(plan, ids, public_events):
    discussion = plan.get("discussion")
    if (plan["social"] is None and isinstance(discussion, dict)
            and discussion.get("kind") in {"PASS", "CITE", "CHALLENGE", "HOLD"}):
        return None
    return _validate_public_social(plan["social"], ids, public_events)


def validate_performance(raw, ids, public_events, tactical):
    """Managed evil may express a tactic, never overwrite strategic state."""
    # Some providers flatten the single social object. Restore only its envelope;
    # every value still goes through the same action, evidence and privacy checks.
    if isinstance(raw, dict) and set(raw) in ({"card", "target", "reason", "statement", "rationale", "evidence"},
                                            {"card", "target", "reason", "public_writing", "citations"}):
        raw = {"social": raw}
    if not isinstance(raw, dict) or set(raw) not in ({"social"}, {"social", "discussion", "revision", "strong_vote"}):
        raise ValueError("Invalid performance keys")
    social = _validate_planned_social(raw, ids, public_events)
    if social is not None and (social["target"] != tactical["primary_target"]
                               or social["card"] not in tactical["allowed_cards"]):
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
    for text in public_social_text(social):
        if (_PRIVATE_DISCLOSURE.search(text) or _TACTICAL_DISCLOSURE.search(text)
                or any(pattern.search(text) for pattern in private_patterns)):
            raise LLMError("private_disclosure")
    result = {**deepcopy(raw), "social": social, "strategy": tactical["strategy_mode"]}
    _validate_resource_policy(result, ids, public_events)
    return result


class Agent:
    def __init__(self, view, client=None, *, max_retries=2, retry_delay=2.0, evil_strategy=None,
                 chronicle=None, discussion_policy="baseline"):
        if discussion_policy not in {"baseline", "engaged_v1"}:
            raise ValueError("Unknown discussion policy")
        self.discussion_policy = discussion_policy
        self.id, self.role = view["self"], view["role"]
        self.ids = [p["id"] for p in view["players"]]
        self.known_evil = set(view["known_evil"])
        self.client = client
        self.max_retries, self.retry_delay = max_retries, retry_delay
        self.cognition = BeliefEngine(view)
        self.state = self.cognition.state
        self.memory = {
            "beliefs": self.cognition.marginals(),
            "profiles": {p: {key: 0.5 for key in sorted(PROFILE_FIELDS)} for p in self.ids},
        }
        self.plan = None
        self.plans, self.sources, self.calls = {}, {}, {}
        self.window_plans = {}
        self.seen_seq = 0
        self.attacks = {}
        self.long_term = AgentMemory(self.id, self.ids)
        self.evidence = self.long_term.working  # The existing recent-evidence window is Working Memory.
        self.chronicle = chronicle
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
        self.cognition.sync_view(view)
        self._lock_facts()

    def bind_chronicle(self, reader):
        self.chronicle = reader

    def _context(self, view, *, tactical=None, window=False):
        self.update_view(view)
        # A reader can replay missed public observations without exposing the host.
        events = (self.chronicle.observations_since(self.seen_seq) if self.chronicle is not None
                  else view.get("recent_events", []))
        for event in events:
            self.observe(event)
        if self.evil_strategy is not None:
            phase = (("council_discussion" if view.get("discussion_stage") == "council" else "discussion")
                     if view["phase"] in {"challenge", "reaction"} else view["phase"])
            tactical = self.evil_strategy.tactical_context(view, phase=phase, joint_beliefs=self.cognition.beliefs).to_dict()
            self.tactical = deepcopy(tactical)
        context = {"game": bounded_game_view(view), "agent_memory": self.long_term.snapshot()}
        context.update(self.cognition.prompt_state(), legal_actions=deepcopy(view["legal_options"]),
                       current_resolve=view["resolve"][self.id])
        if window:
            context["decision"] = "window"
        if tactical is not None:
            context["tactical"] = deepcopy(tactical)
            context["strategic_objective"] = tactical["primary_objective"]
            context["tactical"]["relevant_public_events"] = [context_record(e) for e in
                                                            tactical["relevant_public_events"][-5:]]
            target = tactical["primary_target"]
        else:
            has_history = bool(self.plans or self.long_term.lives)
            context.update(memory=deepcopy(self.memory) if has_history else {"beliefs": {}, "profiles": {}},
                           memory_status="code_derived_estimates" if has_history else "no_previous_model")
            # A previous-life relationship is a retrieval cue, never a forced target/action.
            target = (self.long_term.scars[0]["source_character"] if self.long_term.scars else
                      max(self.long_term.relationships, key=lambda pid: abs(self.long_term.relationships[pid]["trust"])))
        refs = self.long_term.retrieval_hints(target)
        for e in view.get("focused_events", []) + view.get("recent_events", [])[-3:]:
            refs += e.get("citations", [])
        context["retrieved_chronicle"] = (self.chronicle.search_records(target=target, record_ids=refs)
                                          if self.chronicle is not None else [])
        context["pending_language_observations"] = self.cognition.pending_language(self._public_context(context))
        context["language_interpretation_complete"] = not bool(context["pending_language_observations"])
        if self.discussion_policy == "engaged_v1":
            context.update(engaged_context(view, context, managed=self.evil_strategy is not None))
        return context

    @staticmethod
    def _public_context(context):
        return (context["game"]["recent_events"] + context["game"].get("focused_events", [])
                + context["agent_memory"]["working_memory"] + context.get("retrieved_chronicle", [])
                + context.get("tactical", {}).get("relevant_public_events", [])
                + [{"seq": o["seq"], "round": o["round"], "attempt": o["proposal"],
                    "actor": o["actor"], "target": o["target"], **o["payload"]}
                   for o in context.get("observations", [])])

    def _complete(self, context, round_no):
        # At most one retrieval, one semantic pass and one final action. Legacy
        # clients can still return actions directly, without inventing evidence.
        for _ in range(3):
            if self.discussion_policy == "engaged_v1":
                # Retrieval and language review can change legal citations/tactics.
                context.update(engaged_context(self._view, context,
                                               managed=self.evil_strategy is not None))
            self.calls[round_no] = self.calls.get(round_no, 0) + 1
            raw = self.client.complete(deepcopy(context))
            if isinstance(raw, dict) and set(raw) == {"memory_query"}:
                queries = raw["memory_query"]
                if (context.get("retrieval_complete") or context.get("semantic_pass_complete")
                        or not isinstance(queries, list) or not 1 <= len(queries) <= 2
                        or any(not isinstance(q, str) or not q.strip() or len(q) > 120 or not q.isprintable() for q in queries)):
                    raise ValueError("Invalid memory query")
                batches = []
                if self.chronicle is not None:
                    for query in queries:
                        batches.append(self.chronicle.search_records(query))
                records = [batch[i] for i in range(5) for batch in batches if i < len(batch)]
                context["retrieved_chronicle"] = list({e["record_id"]: e for e in records}.values())[:5]
                context["retrieval_complete"] = True
                context["pending_language_observations"] = self.cognition.pending_language(self._public_context(context))
                context["language_interpretation_complete"] = not bool(context["pending_language_observations"])
                continue
            if isinstance(raw, dict) and set(raw) == {"language_evidence"}:
                if context.get("language_interpretation_complete") or not isinstance(raw["language_evidence"], list):
                    raise ValueError("Invalid language evidence")
                public_events = self._public_context(context)
                reviewed = [o["event_id"] for o in context["pending_language_observations"]]
                self.cognition.review_language(raw["language_evidence"], public_events, round_no, reviewed)
                self._lock_facts()
                context.update(self.cognition.prompt_state())
                if self.evil_strategy is not None and "tactical" in context:
                    phase = (("council_discussion" if self._view.get("discussion_stage") == "council" else "discussion")
                             if self._view["phase"] in {"challenge", "reaction"} else self._view["phase"])
                    self.tactical = self.evil_strategy.tactical_context(self._view, phase=phase,
                        joint_beliefs=self.cognition.beliefs).to_dict()
                    context["tactical"] = deepcopy(self.tactical)
                    context["strategic_objective"] = self.tactical["primary_objective"]
                    context["tactical"]["relevant_public_events"] = [context_record(e) for e in
                        self.tactical["relevant_public_events"][-5:]]
                if "memory" in context:
                    context["memory"]["beliefs"] = deepcopy(self.memory["beliefs"])
                    context["memory_status"] = "code_derived_estimates"
                context["pending_language_observations"] = []
                context["language_interpretation_complete"] = True
                context["semantic_pass_complete"] = True
                continue
            if isinstance(raw, dict) and "memory_query" in raw:
                raise ValueError("Invalid memory query")
            return raw
        raise ValueError("Invalid cognition response")

    def _lock_facts(self):
        # Compatibility with vote/dossier consumers; never a second source of beliefs.
        self.memory["beliefs"] = self.cognition.marginals()

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
        context = self._context(view)
        if self.evil_strategy is not None:
            if view["phase"] == "team":
                context["planned_action"] = {"team": self.evil_strategy.choose_team(view)}
            elif view["phase"] == "discussion" and view["leader"] == self.id:
                context["planned_action"] = {"team": list(view["team"])}
        for attempt in range(self.max_retries + 1):
            try:
                raw = self._complete(context, round_no)
                public_events = self._public_context(context)
                raw, cognition = self.cognition.unwrap_response(raw, public_events)
                if self.evil_strategy is not None:
                    plan = validate_performance(raw, self.ids, public_events, self.tactical)
                else:
                    if cognition is not None:
                        if "beliefs" in raw or "profiles" in raw:
                            raise ValueError("Invalid cognition response")
                        raw = {**raw, "beliefs": self.cognition.marginals(),
                               "profiles": deepcopy(self.memory["profiles"])}
                    plan = validate_plan(raw, self.ids, public_events)
                    _guard_public_speech(plan["social"])
                self.cognition.validate_stance_intent(cognition, _discussion_action(plan), view["phase"])
                if view["phase"] in {"discussion", "council_discussion"} and "discussion" in plan:
                    action = _discussion_action(plan)
                    if (RESOLVE_COSTS[action["kind"]] > view["resolve"][self.id]
                            or action["kind"] == "CHALLENGE" and action["target"] == self.id):
                        raise ValueError("Invalid resource action")
                    revision = plan["revision"]
                    if revision["kind"] == "REVISE" and (view["phase"] == "council_discussion" or self.id != view["leader"]
                            or revision["removed"] not in view["team"] or revision["added"] in view["team"]):
                        raise ValueError("Invalid resource action")
                if self.discussion_policy == "engaged_v1":
                    validate_engaged_discussion(plan, view)
            except (LLMError, ValueError, TypeError) as cause:
                error = cause if isinstance(cause, LLMError) else LLMError("invalid_plan", validation_reason=str(cause))
                if not error.retryable or attempt == self.max_retries:
                    raise error from None
                if error.retry_feedback is not None:
                    context["validation_feedback"] = error.retry_feedback
                    if self.discussion_policy == "engaged_v1":
                        context["validation_feedback"] = engaged_retry_feedback(
                            context["validation_feedback"], view)
                delay = min(self.retry_delay * 2 ** attempt, 30.0)
                if on_retry is not None:
                    on_retry(error, attempt + 1, delay)
                time.sleep(delay)
            else:
                break
        self.cognition.commit_response(cognition, public_events, round_no)
        self._lock_facts()
        self.plan = plan
        self.plans[turn] = deepcopy(plan)
        while len(self.plans) > 12:
            del self.plans[next(iter(self.plans))]
        self.sources[round_no] = "llm"
        return "llm"

    def observe(self, event):
        """Update from public facts only; repeated delivery is harmless."""
        if event["seq"] <= self.seen_seq:
            return
        self.cognition.observe(event)
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
        elif kind == "TEAM_VOTE":
            votes = event["votes"]
            approvals = sum(votes.values())
            for pid, approved in votes.items():
                update(pid, "approval", float(approved))
                if approvals * 2 != len(self.ids):
                    update(pid, "consensus", float(approved == (approvals * 2 > len(self.ids))))
        self._lock_facts()
        self.long_term.observe(event, self.memory["beliefs"])
        if kind == "REBIRTH" and event.get("target") == self.id:
            self.plans.clear()
            self.window_plans.clear()
            self.attacks.clear()

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
        context = self._context(view, window=True)
        for attempt in range(self.max_retries + 1):
            try:
                raw = self._complete(context, view["round"])
                events = self._public_context(context)
                raw, cognition = self.cognition.unwrap_response(raw, events)
                if not isinstance(raw, dict) or set(raw) != {"action"}:
                    raise ValueError("Invalid resource action")
                action = raw["action"]
                validate_action(action, self.ids, events, require_statement=True)
                if action["kind"] not in allowed:
                    raise ValueError("Invalid resource action")
                self.cognition.validate_stance_intent(cognition, action, view["phase"])
                if "social" in action:
                    if self.evil_strategy is not None:
                        validate_performance({"social": action["social"]}, self.ids, events, context["tactical"])
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
                self.cognition.commit_response(cognition, events, view["round"])
                self._lock_facts()
                self.window_plans[key] = deepcopy(action)
                while len(self.window_plans) > 12:
                    del self.window_plans[next(iter(self.window_plans))]
                return deepcopy(action)

    def council_decision(self, on_retry=None):
        """Fresh, sealed nomination/ballot decisions with the same bounded memory."""
        view = self._view
        phase = view["phase"]
        if phase not in {"exile_nomination", "exile_vote"} or (
                phase == "exile_nomination" and view["next_actor"] != self.id):
            raise ValueError("No council decision opportunity")
        key = (view["round"], view["attempt"], phase, view["exile_nominee"])
        if key in self.window_plans:
            return deepcopy(self.window_plans[key])
        if self.client is None:
            raise LLMError("missing_configuration")
        context = self._context(view)
        context["decision"] = phase
        for attempt in range(self.max_retries + 1):
            try:
                raw = self._complete(context, view["round"])
                events = self._public_context(context)
                raw, cognition = self.cognition.unwrap_response(raw, events)
                if phase == "exile_nomination":
                    valid = (isinstance(raw, dict) and set(raw) == {"target"}
                             and isinstance(raw["target"], str) and raw["target"] in view["exile_candidates"])
                else:
                    valid = (isinstance(raw, dict) and set(raw) == {"choice"}
                             and isinstance(raw["choice"], str) and raw["choice"] in EXILE_CHOICES)
                if not valid:
                    raise ValueError("Invalid council decision")
                self.cognition.validate_stance_intent(cognition, {}, phase)
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
                self.cognition.commit_response(cognition, events, view["round"])
                self._lock_facts()
                self.window_plans[key] = deepcopy(raw)
                while len(self.window_plans) > 12:
                    del self.window_plans[next(iter(self.window_plans))]
                return deepcopy(raw)

    def vote(self, team, attempt):
        if self.evil_strategy is not None:
            return self.evil_strategy.vote(self._view)
        if attempt == 5 and self.plan["approve_last"]:
            return True
        if self.role in EVIL_ROLES:
            risk = 0.0 if set(team) & self.known_evil else 1.0
        else:
            risk = min(1.0, sum(w["weight"] for w in self.cognition.worlds
                                if set(team) & set(w["evil_team"])))
        return risk <= self.plan["vote_threshold"]

    def mission(self, external_cards=None):
        if self.evil_strategy is not None:
            return self.evil_strategy.mission_cards(self._view, external_cards=external_cards)[self.id]
        return self.plan["mission"] if self.role in EVIL_ROLES else "SUCCESS"

    def assassinate(self):
        if self.evil_strategy is not None:
            return self.evil_strategy.assassinate(self._view, joint_beliefs=self.cognition.beliefs)
        rank = self.plan["assassin_rank"]
        candidates = [p for p in rank if p not in self.known_evil and p != self.id]
        return max(candidates, key=lambda p: (self.cognition.P_role(p, "MERLIN"), -rank.index(p)))

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

    def cognition_debug_view(self):
        """Developer-only detached snapshot. Never used to build model context."""
        return self.cognition.debug_snapshot()
