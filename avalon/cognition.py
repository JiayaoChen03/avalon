"""Per-seat cognition: rule-constrained joint worlds, never shared private state.

Only engine observations can eliminate worlds or change an expressed stance.
The model supplies bounded, cited interpretations; code owns every numeric weight.
"""

from collections import deque
from copy import deepcopy
from dataclasses import asdict, dataclass, field
import math
import re

from .chronicle import PUBLIC_KINDS, EVIDENCE_KINDS, context_record, involves, record_id
from .evidence import (Observation, Evidence, EvidenceType, EvidenceExtractor, LikelihoodModel,
                       LANGUAGE_REASONS, LANGUAGE_SIGNALS, language_signal_id)
from .joint_beliefs import (JointHypothesis, JointBeliefState, BeliefUpdateRecord, BeliefContradiction,
                           enumerate_hypotheses, marginal_changes)


OBSERVATION_LIMIT = 12
HISTORY_LIMIT = 32
UPDATE_LIMIT = 40
STANCE_BY_CARD = {"ACCUSE": "SUSPICIOUS", "DEFEND": "TRUST", "HEDGE": "UNCERTAIN",
                  "PRESSURE": "QUESTIONING", "BAIT": "UNCERTAIN"}
ENVELOPE_FIELDS = {"belief_updates", "interpretation", "public_stance_change",
                   "recommended_action", "short_rationale"}


@dataclass
class PrivateBeliefs(JointBeliefState):
    observer_id: str | None = None
    eliminated_worlds: list = field(default_factory=list)
    updates: deque = field(default_factory=lambda: deque(maxlen=UPDATE_LIMIT))
    interpretations: deque = field(default_factory=lambda: deque(maxlen=12))
    update_records: deque = field(default_factory=lambda: deque(maxlen=HISTORY_LIMIT))

    @property
    def possible_worlds(self):
        return self.alignment_worlds()


@dataclass
class AgentState:
    objective_state: dict
    private_knowledge: dict
    private_beliefs: PrivateBeliefs
    public_stances: dict
    observations: deque = field(default_factory=lambda: deque(maxlen=OBSERVATION_LIMIT))
    belief_history: deque = field(default_factory=lambda: deque(maxlen=HISTORY_LIMIT))


def _short_text(value, limit=240):
    return isinstance(value, str) and bool(value.strip()) and len(value) <= limit and value.isprintable()


def _knowledge(view):
    return deepcopy({k: view["private_knowledge"][k] for k in
        ("self_role", "self_alignment", "known_evil_players", "known_good_players", "known_special_roles")})


def _objective(view):
    """Positive projection at the last context boundary, including nested records."""
    source = view["objective_state"]
    fields = {"mission_round", "proposal_number", "leader", "proposed_team", "team_size", "phase",
              "safe_round", "discussion_stage", "exile_nominee"}
    result = deepcopy({k: v for k, v in source.items() if k in fields})
    result["rules"] = {k: deepcopy(source["rules"][k]) for k in
                       ("fail_threshold", "good_may_fail", "evil_may_succeed", "evil_count", "team_sizes", "max_proposals",
                        "role_counts", "role_alignments")}
    result["mission_score"] = {k: source["mission_score"][k] for k in ("good", "evil")}
    ids = [p["id"] for p in view["players"]]
    result["resolve"] = {p: source["resolve"][p] for p in ids}
    result["lives"] = {p: {k: source["lives"][p][k] for k in ("life", "alive")} for p in ids}
    for key in ("public_votes", "public_actions", "public_commitments"):
        result[key] = [context_record(e) for e in source[key] if e["kind"] in EVIDENCE_KINDS]
    mission_fields = {"round", "attempt", "record_id", "team", "success", "fail_count", "fail_threshold",
                      "successes", "failures", "safe_round"}
    result["mission_results"] = [{k: deepcopy(v) for k, v in m.items() if k in mission_fields}
                                 for m in source["mission_results"]]
    return result


class BeliefEngine:
    def __init__(self, view, *, likelihood_config=None):
        self.pid = view["self"]
        self.ids = tuple(p["id"] for p in view["players"])
        self.rules = deepcopy(view["rules"])
        counts, alignments = self.rules["role_counts"], self.rules["role_alignments"]
        beliefs = PrivateBeliefs(enumerate_hypotheses(self.ids, counts), deepcopy(counts), deepcopy(alignments),
                                observer_id=self.pid)
        beliefs.normalize()
        self.state = AgentState({}, _knowledge(view), beliefs,
                                {p: {"stance": "UNCERTAIN", "confidence": "LOW", "reason": None,
                                     "last_updated_round": None, "event_id": None} for p in self.ids})
        self.likelihood_model = LikelihoodModel(alignments, likelihood_config)
        self.extractor = EvidenceExtractor(self.pid, self.ids, self.rules, self.likelihood_model.config)
        self._applied_signals = set()
        self._hard_evidence = []
        self._reviewed_language = set()
        self._observed_ids = set()
        self.seen_seq = 0
        self._process(Observation.from_knowledge(self.pid, self.state.private_knowledge), remember=False)
        self.sync_view(view)

    @property
    def beliefs(self):
        return self.state.private_beliefs

    @property
    def worlds(self):
        return self.beliefs.possible_worlds

    def P_role(self, agent_id, role):
        return self.beliefs.P_role(agent_id, role)

    def P_alignment(self, agent_id, alignment):
        return self.beliefs.P_alignment(agent_id, alignment)

    def P_joint(self, assignments):
        return self.beliefs.P_joint(assignments)

    def P_conditional(self, query, condition):
        return self.beliefs.P_conditional(query, condition)

    def apply_known_alignments(self, evil=(), good=()):
        """Host-only knowledge still enters through an explicit private Observation."""
        evil, good = set(evil), set(good)
        if evil & good or not (evil | good) <= set(self.ids):
            raise BeliefContradiction("Invalid role-authorized knowledge")
        key = f"ROLE_KNOWLEDGE:{self.pid}:evil={','.join(sorted(evil))}:good={','.join(sorted(good))}"
        self._process(Observation(key, 0, 0, 0, self.pid, "ROLE_KNOWLEDGE", self.pid,
                                 {"known_evil": sorted(evil), "known_good": sorted(good)}), remember=False)

    def sync_view(self, view):
        if (view["self"] != self.pid or tuple(p["id"] for p in view["players"]) != self.ids
                or _knowledge(view) != self.state.private_knowledge
                or view["rules"]["role_counts"] != self.beliefs.role_counts
                or view["rules"]["role_alignments"] != self.beliefs.role_alignments):
            raise ValueError("An agent can only receive its own legal knowledge")
        self.state.objective_state = _objective(view)
        for mission in view.get("missions", []):
            self._process(Observation.from_mission(mission), remember=False)

    def _apply_evidence(self, observation_id, evidence, round_no):
        fresh = []
        keys = set(self._applied_signals)
        for item in evidence:
            if (not isinstance(item, Evidence) or not isinstance(item.evidence_type, EvidenceType)
                    or item.source_agent is not None and item.source_agent not in self.ids
                    or any(p not in self.ids for p in item.target_agents)
                    or not isinstance(item.signal_id, str) or not item.signal_id
                    or type(item.strength) not in (int, float) or not math.isfinite(item.strength) or item.strength <= 0):
                raise ValueError("Invalid extracted evidence")
            if item.signal_id not in keys:
                keys.add(item.signal_id)
                fresh.append(item)
        if not fresh:
            return None
        trial = JointBeliefState(deepcopy(self.beliefs.hypotheses), self.beliefs.role_counts,
                                 self.beliefs.role_alignments, set(self.beliefs.eliminated_keys))
        eliminated = []
        for item in fresh:
            # A constant mission factor cancels analytically. Do not add and
            # subtract its log offset: rounding alone could break a downstream
            # exact argmax tie despite providing no information. Keep the
            # evidence/provenance record and normalize the hard batch normally.
            if item.feature == "mission_outcome" and trial.hypotheses:
                values = [self.likelihood_model.evaluate(h, item) for h in trial.hypotheses]
                if all(v == values[0] for v in values) and math.isfinite(values[0]) and values[0] > 0:
                    continue
            survivors = []
            for hypothesis in trial.hypotheses:
                likelihood = self.likelihood_model.evaluate(hypothesis, item)
                if not math.isfinite(likelihood) or likelihood < 0:
                    raise ValueError("Invalid likelihood")
                if likelihood == 0:
                    if item.evidence_type != EvidenceType.HARD:
                        raise ValueError("Soft evidence cannot eliminate hypotheses")
                    eliminated.append({"roles": dict(hypothesis.roles),
                        "evil_team": sorted(p for p, r in hypothesis.roles.items() if self.beliefs.role_alignments[r] == "EVIL"),
                        "reason": item.feature, "evidence": [item.origin_event_id]})
                    trial.eliminated_keys.add(hypothesis.key)
                else:
                    hypothesis.log_probability += math.log(likelihood)
                    survivors.append(hypothesis)
            trial.hypotheses = survivors
        trial.normalize()  # Reject an impossible entire batch before mutating real state.
        before, prior_top = self.beliefs.marginals(), self.beliefs.top_hypotheses(3)
        before_summary = self.summary()
        after = trial.marginals()
        changes, largest = marginal_changes(before, after)
        self.beliefs.hypotheses = trial.hypotheses
        self.beliefs.eliminated_keys = trial.eliminated_keys
        self.beliefs.eliminated_worlds.extend(eliminated)
        self._applied_signals = keys
        record = BeliefUpdateRecord(observation_id, deepcopy(fresh), prior_top, trial.top_hypotheses(3),
                                    changes, len(eliminated), largest)
        self.beliefs.update_records.append(record)
        for item in fresh:
            hard = item.evidence_type == EvidenceType.HARD
            if (hard and any(item.origin_event_id in h["evidence"] for h in eliminated)
                    and item.origin_event_id not in self._hard_evidence):
                self._hard_evidence.append(item.origin_event_id)
            self.beliefs.updates.append({"kind": "HARD" if hard else "SOFT", "round": round_no,
                "targets": sorted(set(item.target_agents) | set(changes)), "reason": item.feature,
                "evidence": [item.origin_event_id], "origin_signal": item.signal_id,
                "strength": item.metadata.get("strength_label", "WEAK").upper(),
                "direction": {"increase_suspicion": "MORE_SUSPICIOUS", "decrease_suspicion": "LESS_SUSPICIOUS"}.get(item.direction),
                "alternative_explanations": deepcopy(item.metadata.get("alternative_explanations", []))})
        self._history(before_summary, [item.origin_event_id for item in fresh], round_no,
                      "HARD" if any(e.evidence_type == EvidenceType.HARD for e in fresh) else "SOFT")
        return record

    def _process(self, observation, *, remember=True):
        if not isinstance(observation, Observation):
            raise TypeError("Belief updates require an Observation")
        if observation.event_id in self._observed_ids:
            return
        extractor = deepcopy(self.extractor)
        evidence = extractor.extract(observation)
        self._apply_evidence(observation.event_id, evidence, observation.round)
        self.extractor = extractor
        self._observed_ids.add(observation.event_id)
        if remember:
            self.state.observations.append(observation)
            self._public_action(observation.to_event())
            self.seen_seq = max(self.seen_seq, observation.seq)

    def observe(self, event):
        observation = Observation.from_event(event)
        if observation is not None:
            self._process(observation)

    def _public_action(self, event):
        """Record what THIS seat actually expressed, not what it privately believes.

        A strong team vote addresses the TEAM, and CITE only references a record;
        neither establishes trust/distrust of every player mentioned in it.
        """
        if event.get("actor") != self.pid:
            return
        kind, target, stance = event["kind"], event.get("target"), None
        if kind in {"SOCIAL", "REACT", "CHALLENGE_RESPONSE"} and "card" in event:
            stance = STANCE_BY_CARD[event["card"]]
        elif kind == "CHALLENGE":
            stance = "QUESTIONING"
        elif kind == "CITE":
            target, stance = f"EVIDENCE:{event['evidence']}", "REFERENCED"
        elif kind in {"VOTE", "STRONG_VOTE"} and event.get("strong", kind == "STRONG_VOTE"):
            team = event.get("team", self.state.objective_state.get("proposed_team", []))
            target = "TEAM:" + ",".join(sorted(team))
            stance = "SUPPORT_TEAM" if event["approve"] else "OPPOSE_TEAM"
        elif kind == "EXILE_NOMINATION":
            stance = "NOMINATE_EXILE"
        elif kind == "EXILE_VOTE":
            target, stance = f"EXILE:{target}", event["choice"]
        if stance is None or target is None:
            return
        self.state.public_stances[target] = {"stance": stance,
            "confidence": "HIGH" if event.get("committed") or event.get("strong") else "MEDIUM",
            "reason": event.get("public_writing", event.get("statement", event.get("reason"))),
            "last_updated_round": event["round"], "event_id": record_id(event)}

    def marginals(self):
        """Compatibility values derived exclusively from exact role hypotheses."""
        return {p: {"evil": self.P_alignment(p, "EVIL"),
                    "merlin": self.P_role(p, "MERLIN") if "MERLIN" in self.beliefs.role_counts else 0.0}
                for p in self.ids}

    def summary(self):
        result = {}
        for pid, belief in self.marginals().items():
            membership = [pid in w["evil_team"] for w in self.worlds]
            certain = all(membership) or not any(membership)
            evidence = [u for u in self.state.private_beliefs.updates if pid in u["targets"]]
            p = belief["evil"]
            label = ("KNOWN_EVIL" if all(membership) else "KNOWN_GOOD" if not any(membership)
                     else "STRONGLY_SUSPICIOUS" if p >= .8 else "SUSPICIOUS" if p >= .6
                     else "LIKELY_GOOD" if p <= .2 else "UNCERTAIN")
            result[pid] = {"assessment": label, "confidence": "HIGH" if certain else
                           "MEDIUM" if evidence and evidence[-1].get("strength") == "STRONG" else "LOW",
                           "evidence": list(dict.fromkeys(
                               (self._hard_evidence if certain else []) +
                               [r for u in evidence[-3:] for r in u["evidence"]]))[-6:],
                           "evidence_quality": "RULE_CONSTRAINT" if certain or evidence and evidence[-1]["kind"] == "HARD" else
                           evidence[-1]["strength"] if evidence else "NO_EVIDENCE"}
        return result

    def _history(self, before, evidence, round_no, kind):
        for pid, after in self.summary().items():
            if before[pid]["assessment"] != after["assessment"]:
                self.state.belief_history.append({"round": round_no, "target": pid,
                    "from": before[pid]["assessment"], "to": after["assessment"],
                    "cause": list(evidence), "kind": kind})

    def validate_updates(self, updates, public_events):
        """Interpret only supplied public observations, never model probability maps.

        Old cited-update envelopes remain readable, but can only request replay of
        the deterministic evidence attached to those records. They cannot turn a
        mission result or a DEFEND card into a second subjective multiplier.
        """
        if not isinstance(updates, list) or len(updates) > 4:
            raise ValueError("Invalid belief updates")
        available = self._public_observations(public_events)
        extracted = []
        for update in updates:
            if not isinstance(update, dict):
                raise ValueError("Invalid belief updates")
            if "direction" in update:  # Compatibility for the first cognition protocol.
                required = {"targets", "direction", "strength", "evidence", "alternative_explanations"}
                targets, refs, alternatives = update.get("targets"), update.get("evidence"), update.get("alternative_explanations")
                if (set(update) != required or not isinstance(targets, list) or not 1 <= len(targets) <= 2
                        or any(not isinstance(p, str) or p not in self.ids for p in targets) or len(set(targets)) != len(targets)
                        or update["direction"] not in ("MORE_SUSPICIOUS", "LESS_SUSPICIOUS")
                        or update["strength"] not in ("WEAK", "MODERATE", "STRONG")
                        or not isinstance(refs, list) or not 1 <= len(refs) <= 3
                        or any(not isinstance(r, str) or r not in available for r in refs) or len(set(refs)) != len(refs)
                        or any(not any(involves(available[r].to_event(), p) for r in refs) for p in targets)
                        or not isinstance(alternatives, list) or not 2 <= len(alternatives) <= 4
                        or any(not _short_text(a) for a in alternatives)):
                    raise ValueError("Invalid belief updates")
                # A detached extractor makes validation pure. Replay uses canonical
                # origins and the same likelihood as the observed action itself.
                extractor = deepcopy(self.extractor)
                for ref in refs:
                    extracted.extend(extractor.extract(available[ref]))
                continue
            required = {"origin_event_id", "signal", "strength", "reason_type", "confidence"}
            if set(update) not in (required | {"target"}, required | {"targets"}):
                raise ValueError("Invalid language evidence")
            targets = update.get("targets", [update.get("target")])
            ref = update["origin_event_id"]
            if (not isinstance(targets, list) or not 1 <= len(targets) <= 2
                    or any(not isinstance(p, str) or p not in self.ids for p in targets)
                    or len(set(targets)) != len(targets)
                    or not isinstance(ref, str) or ref not in available
                    or not isinstance(update["signal"], str) or update["signal"] not in LANGUAGE_SIGNALS
                    or not isinstance(update["reason_type"], str) or update["reason_type"] not in LANGUAGE_REASONS
                    or not isinstance(update["strength"], str) or update["strength"] not in self.likelihood_model.config.language
                    or not isinstance(update["confidence"], str) or update["confidence"] not in self.likelihood_model.config.confidence):
                raise ValueError("Invalid language evidence")
            observation = available[ref]
            if not self._has_language(observation):
                raise ValueError("Language evidence requires public speech")
            prose = self._prose(observation)
            if (any(not involves(observation.to_event(), p) and not re.search(r"(?<![A-Za-z0-9_])" + re.escape(p) + r"(?![A-Za-z0-9_])", prose)
                    for p in targets)
                    or update["reason_type"] == "privileged_information_signal" and len(targets) != 1):
                raise ValueError("Invalid language evidence")
            strength = self.likelihood_model.config.language[update["strength"]] ** self.likelihood_model.config.confidence[update["confidence"]]
            extracted.append(Evidence(ref, observation.actor, list(targets), EvidenceType.LANGUAGE,
                update["reason_type"], update["signal"], strength,
                {"signal_id": language_signal_id(observation, update["reason_type"]),
                 "strength_label": update["strength"], "confidence": update["confidence"]}))
        return extracted

    def apply_soft_updates(self, updates, public_events, round_no):
        evidence = self.validate_updates(updates, public_events)
        # Batch validation and probability calculation complete before any commit.
        origins = list(dict.fromkeys(e.origin_event_id for e in evidence))
        return self._apply_evidence(",".join(origins), evidence, round_no)

    @staticmethod
    def _prose(observation):
        return " ".join(v for k in ("public_writing", "statement")
                        if isinstance(v := observation.payload.get(k), str))

    def _has_language(self, observation):
        # Mechanical results (even if prose is injected into them) are never
        # semantic evidence; neither are our own policy outputs.
        return (observation.actor in self.ids and observation.actor != self.pid
                and observation.type not in {"MISSION_RESULT", "ROLE_KNOWLEDGE", "TEAM_VOTE", "DEATH", "REBIRTH", "ASSASSINATE"}
                and bool(self._prose(observation).strip()))

    def pending_language(self, public_events):
        observations = self._public_observations(public_events)
        return [asdict(o) for o in observations.values()
                if self._has_language(o) and o.event_id not in self._reviewed_language
                and f"language:{o.event_id}" not in self._applied_signals][-4:]

    def _public_observations(self, public_events):
        observations = {}
        for event in public_events:
            if event["kind"] not in EVIDENCE_KINDS:
                continue
            observation = Observation.from_event(event)
            previous = observations.get(observation.event_id)
            # A tactical or working-memory projection may omit the speech. It
            # must not erase an authorized complete record supplied alongside it.
            if previous is None or self._prose(observation) or not self._prose(previous):
                observations[observation.event_id] = observation
        return observations

    def review_language(self, updates, public_events, round_no, reviewed_ids):
        if any(not isinstance(u, dict) or "direction" in u for u in updates):
            raise ValueError("Invalid language evidence")
        if any(u.get("origin_event_id") not in reviewed_ids for u in updates):
            raise ValueError("Invalid language evidence")
        record = self.apply_soft_updates(updates, public_events, round_no)
        self._reviewed_language.update(reviewed_ids)
        return record

    def unwrap_response(self, raw, public_events):
        """Validate the cognitive envelope without committing any model state.

        Legacy action policies remain readable during migration, but their numeric
        beliefs/profiles never update the new cognition state.
        """
        if not isinstance(raw, dict) or not set(raw) & ENVELOPE_FIELDS:
            return raw, None
        if set(raw) != ENVELOPE_FIELDS or not isinstance(raw["recommended_action"], dict):
            raise ValueError("Invalid cognition response")
        evidence = self.validate_updates(raw["belief_updates"], public_events)
        if any(e.signal_id not in self._applied_signals for e in evidence):
            raise ValueError("Language evidence must precede action")
        interpretations = raw["interpretation"]
        available = {record_id(e) for e in public_events if e["kind"] in EVIDENCE_KINDS}
        if (not isinstance(interpretations, list) or len(interpretations) > 4
                or not _short_text(raw["short_rationale"])):
            raise ValueError("Invalid cognition response")
        for item in interpretations:
            if (not isinstance(item, dict) or set(item) != {"evidence", "summary"}
                    or not _short_text(item["summary"]) or not isinstance(item["evidence"], list)
                    or not 1 <= len(item["evidence"]) <= 3
                    or any(not isinstance(r, str) or r not in available for r in item["evidence"])):
                raise ValueError("Invalid cognition response")
        return deepcopy(raw["recommended_action"]), deepcopy(raw)

    def validate_stance_intent(self, envelope, action, phase):
        if envelope is None or envelope["public_stance_change"] is None:
            return
        change = envelope["public_stance_change"]
        social = action.get("social")
        expected = STANCE_BY_CARD.get(social.get("card")) if isinstance(social, dict) else (
            "QUESTIONING" if action.get("kind") == "CHALLENGE" else None)
        target = social.get("target") if isinstance(social, dict) else action.get("target")
        if (phase not in {"discussion", "council_discussion", "challenge", "reaction"}
                or expected is None or not isinstance(change, dict)
                or set(change) != {"target", "stance"} or change != {"target": target, "stance": expected}):
            raise ValueError("Invalid public stance change")

    def commit_response(self, envelope, public_events, round_no):
        if envelope is None:
            return
        self.apply_soft_updates(envelope["belief_updates"], public_events, round_no)
        self.state.private_beliefs.interpretations.extend(deepcopy(envelope["interpretation"]))
        # public_stance_change is only an intent. observe(accepted event) owns publication.

    def prompt_state(self):
        worlds = sorted(self.worlds, key=lambda w: (-w["weight"], w["evil_team"]))
        marginals = self.beliefs.marginals()
        conditional = []
        uncertain = [p for p in self.ids if 1e-12 < self.P_alignment(p, "EVIL") < 1 - 1e-12]
        for pid in sorted(uncertain, key=lambda p: -self.P_alignment(p, "EVIL"))[:2]:
            for alignment in ("GOOD", "EVIL"):
                candidates = [(w, self.P_conditional({p: "EVIL" for p in w["evil_team"]}, {pid: alignment})) for w in worlds]
                best, probability = max(candidates, key=lambda pair: pair[1] or 0)
                conditional.append({"condition": {pid: alignment}, "dominant_evil_team": best["evil_team"],
                                    "probability_given_condition": probability})
        summaries = self.summary()
        belief_summary = {"hypotheses_remaining": len(self.beliefs.hypotheses), "marginals": marginals,
            "top_role_hypotheses": self.beliefs.top_hypotheses(3),
            "possible_worlds": [{"evil_team": w["evil_team"], "weight": w["weight"]} for w in worlds[:5]],
            "shown_evil_team_mass": math.fsum(w["weight"] for w in worlds[:5]),
            "conditional_relationships": conditional, "summary": summaries,
            "weight_status": "NORMALIZED_POSTERIOR_UNCALIBRATED_LIKELIHOODS",
            "recent_updates": list(self.beliefs.updates)[-4:]}
        return deepcopy({"private_knowledge": self.state.private_knowledge,
            "objective_state": self.state.objective_state,
            "private_beliefs": belief_summary,
            "inferences": {p: s["assessment"] for p, s in summaries.items()},
            "strategic_objective": "Seek survival in the castle; consider commitments, future accountability and remaining Resolve.",
            "public_stances": self.state.public_stances,
            "observations": [asdict(o) for o in self.state.observations],
            "belief_history": list(self.state.belief_history)[-8:]})

    def debug_snapshot(self):
        return {"agent": self.pid, "role": self.state.private_knowledge["self_role"],
                **self.prompt_state(),
                "hypotheses_remaining": len(self.beliefs.hypotheses),
                "top_hypotheses": self.beliefs.top_hypotheses(5), "marginals": self.beliefs.marginals(),
                "last_update": asdict(self.beliefs.update_records[-1]) if self.beliefs.update_records else None,
                "update_records": [asdict(r) for r in self.beliefs.update_records],
                "likelihood_parameters": asdict(self.likelihood_model.config),
                "eliminated_worlds": deepcopy(self.state.private_beliefs.eliminated_worlds),
                "belief_updates": deepcopy(list(self.state.private_beliefs.updates)),
                "interpretations": deepcopy(list(self.state.private_beliefs.interpretations))}
