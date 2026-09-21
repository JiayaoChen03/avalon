"""Legally observed facts become typed evidence; prose never becomes a hard fact."""

from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
import math

from .chronicle import PUBLIC_KINDS, context_record, record_id
from .engine import mission_result_constraints


class EvidenceType(str, Enum):
    HARD = "hard"
    BEHAVIORAL = "behavioral"
    LANGUAGE = "language"


@dataclass(frozen=True)
class Observation:
    event_id: str
    seq: int
    round: int
    proposal: int
    actor: str | None
    type: str
    target: str | None
    payload: dict

    @classmethod
    def from_event(cls, event):
        if event["kind"] not in PUBLIC_KINDS:
            return None
        safe = context_record(event)
        kind = safe["kind"]
        event_type = (safe["card"] if kind in {"SOCIAL", "REACT", "CHALLENGE_RESPONSE"} and "card" in safe
                      else "MISSION_RESULT" if kind == "MISSION" else kind)
        return cls(record_id(event), event["seq"], event["round"], event.get("attempt", 1),
                   event.get("actor"), event_type, event.get("target"),
                   {k: v for k, v in safe.items() if k not in
                    {"record_id", "seq", "round", "attempt", "actor", "target"}})

    @classmethod
    def from_mission(cls, mission):
        """Engine snapshot recovery follows the same observation path as live events."""
        rid = mission.get("record_id", f"MISSION:{mission['round']}:{mission.get('attempt', 1)}")
        return cls(rid, 0, mission["round"], mission.get("attempt", 1), None, "MISSION_RESULT", None,
                   {k: deepcopy(v) for k, v in mission.items() if k in
                    {"team", "success", "fail_count", "fail_threshold", "safe_round"}})

    @classmethod
    def from_knowledge(cls, pid, knowledge):
        roles = {pid: knowledge["self_role"]}
        for entry in knowledge["known_special_roles"]:
            if entry["player"] in roles and roles[entry["player"]] != entry["role"]:
                raise ValueError("Conflicting authorized role knowledge")
            roles[entry["player"]] = entry["role"]
        return cls(f"ROLE_KNOWLEDGE:{pid}", 0, 0, 0, pid, "ROLE_KNOWLEDGE", pid,
                   {"known_roles": roles, "known_evil": list(knowledge["known_evil_players"]),
                    "known_good": list(knowledge["known_good_players"])})

    def to_event(self):
        return {"seq": self.seq, "round": self.round, "attempt": self.proposal,
                "record_id": self.event_id, "actor": self.actor, "target": self.target, **deepcopy(self.payload)}


@dataclass(frozen=True)
class Evidence:
    origin_event_id: str
    source_agent: str | None
    target_agents: list[str]
    evidence_type: EvidenceType
    feature: str
    direction: str | None
    strength: float
    metadata: dict = field(default_factory=dict)

    @property
    def signal_id(self):
        return self.metadata["signal_id"]


LANGUAGE_LIKELIHOODS = {"weak": 1.10, "medium": 1.30, "strong": 1.60}
LANGUAGE_REASONS = {"contradiction", "defense", "accusation", "vote_inconsistency", "team_inconsistency",
                    "privileged_information_signal", "coordination_signal", "deception_signal", "unsupported_certainty"}
LANGUAGE_SIGNALS = {"increase_suspicion", "decrease_suspicion", "neutral"}
CONFIDENCE_WEIGHTS = {"low": .5, "medium": .75, "high": 1.0}
BEHAVIORAL_LIKELIHOODS = {"team_proposal": 1.04, "vote_evil": 1.03, "vote_merlin": 1.06,
                         "defense": 1.05, "opposition": 1.03}


@dataclass
class LikelihoodConfig:
    language: dict = field(default_factory=lambda: dict(LANGUAGE_LIKELIHOODS))
    behavioral: dict = field(default_factory=lambda: dict(BEHAVIORAL_LIKELIHOODS))
    confidence: dict = field(default_factory=lambda: dict(CONFIDENCE_WEIGHTS))

    def __post_init__(self):
        for values, keys in ((self.language, LANGUAGE_LIKELIHOODS), (self.behavioral, BEHAVIORAL_LIKELIHOODS),
                             (self.confidence, CONFIDENCE_WEIGHTS)):
            if (set(values) != set(keys) or any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in values.values())):
                raise ValueError("Invalid likelihood configuration")
        if (not 1 <= self.language["weak"] <= self.language["medium"] <= self.language["strong"]
                or any(v < 1 for v in self.behavioral.values()) or any(v > 1 for v in self.confidence.values())):
            raise ValueError("Invalid likelihood configuration")


def language_signal_id(observation, reason_type):
    """Do not count formal actions again as semantic restatements of those actions."""
    if reason_type == "vote_inconsistency" and observation.type in {"VOTE", "STRONG_VOTE"}:
        return f"vote:{observation.round}:{observation.proposal}:{observation.actor}"
    duplicate = ((reason_type == "defense" and observation.type == "DEFEND")
                 or reason_type == "coordination_signal" and observation.type == "DEFEND"
                 or reason_type == "accusation" and observation.type in {"ACCUSE", "PRESSURE", "CHALLENGE"}
                 or reason_type == "team_inconsistency" and observation.type in {"TEAM", "TEAM_REVISE"}
                 )
    return f"action:{observation.event_id}" if duplicate else f"language:{observation.event_id}"


class EvidenceExtractor:
    def __init__(self, observer_id, player_ids, rules):
        self.observer_id, self.ids, self.rules = observer_id, tuple(player_ids), deepcopy(rules)
        self.teams = {}

    def extract(self, observation):
        if not isinstance(observation, Observation):
            raise TypeError("Evidence extraction requires a legal Observation")
        o, payload = observation, observation.payload
        base = {"origin_event_id": o.event_id, "source_agent": o.actor,
                "target_agents": [o.target] if o.target else [], "direction": None, "strength": 1.0}
        if o.type == "ROLE_KNOWLEDGE":
            return [Evidence(**base, evidence_type=EvidenceType.HARD, feature="known_roles",
                             metadata={"signal_id": o.event_id, **deepcopy(payload)})]
        if o.type == "MISSION_RESULT":
            rules = dict(self.rules, fail_threshold=payload.get("fail_threshold", self.rules["fail_threshold"]))
            constraints = mission_result_constraints(payload["team"], payload["fail_count"], rules,
                                                     success=payload["success"])
            return [Evidence(**{**base, "target_agents": list(payload["team"])}, evidence_type=EvidenceType.HARD,
                             feature="mission_result", metadata={"signal_id": f"mission:{o.round}:{o.proposal}",
                                "team": list(payload["team"]), "fail_count": payload["fail_count"], **constraints})]
        if o.type == "ASSASSINATE":
            return [Evidence(**{**base, "target_agents": [o.actor]}, evidence_type=EvidenceType.HARD,
                             feature="known_roles", metadata={"signal_id": f"assassin:{o.actor}",
                                                             "known_roles": {o.actor: "ASSASSIN"}})]
        coordinates = (o.round, o.proposal)
        if "team" in payload:
            self.teams[coordinates] = list(payload["team"])
        if o.type in {"VOTE", "STRONG_VOTE", "TEAM_VOTE"}:
            team = payload.get("team", self.teams.get(coordinates))
            if team is None:  # An incomplete old log is not a license to guess its team.
                return []
            votes = payload["votes"] if o.type == "TEAM_VOTE" else {o.actor: payload["approve"]}
            return [Evidence(o.event_id, p, list(team), EvidenceType.BEHAVIORAL, "team_vote", None, 1.0,
                             {"signal_id": f"vote:{o.round}:{o.proposal}:{p}", "team": list(team), "approve": approve})
                    for p, approve in votes.items() if p != self.observer_id]
        # My action is a policy output, not evidence that makes my belief come true.
        if o.actor == self.observer_id:
            return []
        if o.type in {"TEAM", "TEAM_REVISE"}:
            feature, targets = "team_proposal", list(payload["team"])
        elif o.type == "DEFEND":
            feature, targets = "defense", [o.target]
        elif o.type in {"ACCUSE", "PRESSURE", "CHALLENGE"}:
            feature, targets = "opposition", [o.target]
        else:
            return []  # PASS, CITE, HOLD and HEDGE have no default directional likelihood.
        return [Evidence(**{**base, "target_agents": targets}, evidence_type=EvidenceType.BEHAVIORAL,
                         feature=feature, metadata={"signal_id": f"action:{o.event_id}"})]


class LikelihoodModel:
    def __init__(self, role_alignments, config=None):
        self.alignments = dict(role_alignments)
        self.config = deepcopy(config or LikelihoodConfig())

    def allows(self, hypothesis, evidence):
        data = evidence.metadata
        if evidence.feature == "known_roles":
            return (all(hypothesis.roles.get(p) == r for p, r in data.get("known_roles", {}).items())
                    and all(self.alignments[hypothesis.roles[p]] == "EVIL" for p in data.get("known_evil", []))
                    and all(self.alignments[hypothesis.roles[p]] == "GOOD" for p in data.get("known_good", [])))
        if evidence.feature == "mission_result":
            evil_count = sum(self.alignments[hypothesis.roles[p]] == "EVIL" for p in data["team"])
            return data["min_evil"] <= evil_count <= data["max_evil"]
        raise ValueError("Unknown hard evidence feature")

    def evaluate(self, hypothesis, evidence):
        if evidence.evidence_type == EvidenceType.HARD:
            return float(self.allows(hypothesis, evidence))
        roles = hypothesis.roles
        evil = {p for p, r in roles.items() if self.alignments[r] == "EVIL"}
        if evidence.evidence_type == EvidenceType.LANGUAGE:
            if evidence.direction == "neutral":
                return 1.0
            if evidence.feature == "privileged_information_signal":
                matched = all(roles[p] == "MERLIN" for p in evidence.target_agents)
            else:
                matched = set(evidence.target_agents) <= evil
            increase = evidence.direction == "increase_suspicion"
            return evidence.strength if matched == increase else 1 / evidence.strength
        values, actor, targets = self.config.behavioral, evidence.source_agent, set(evidence.target_agents)
        if evidence.feature == "team_proposal":
            return values["team_proposal"] if actor in evil and targets & evil else 1.0
        if evidence.feature == "defense":
            return values["defense"] if actor in evil and targets <= evil else 1.0
        if evidence.feature == "opposition":
            opposed = any((actor in evil) != (p in evil) for p in targets)
            return values["opposition"] if opposed else 1.0
        if evidence.feature == "team_vote":
            dirty = bool(targets & evil)
            approve = evidence.metadata["approve"]
            if actor in evil:
                return values["vote_evil"] if approve == dirty else 1 / values["vote_evil"]
            if roles[actor] == "MERLIN":
                return values["vote_merlin"] if approve != dirty else 1 / values["vote_merlin"]
            return 1.0
        raise ValueError("Unknown behavioral evidence feature")
