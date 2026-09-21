"""Public-evidence estimates for a single evil pair; never a hidden role table."""

from collections import deque
from copy import deepcopy
from dataclasses import dataclass, field
from functools import cached_property
import re

from .engine import CARDS, EVIDENCE_KINDS, SOCIAL_EVENTS
from .joint_beliefs import JointBeliefState, enumerate_hypotheses


def bounded(value):
    return round(max(0.0, min(1.0, value)), 6)


@dataclass
class EvilSharedState:
    public_suspicion: dict
    public_trust: dict
    profiles: dict
    public_tags: dict
    roles: dict
    pair_suspicion: float = 0.0
    distance_strength: float = 0.0
    strategy_mode: str = "NORMAL_DECEPTION"
    mode_scores: dict = field(default_factory=dict)
    primary_objectives: dict = field(default_factory=dict)
    secondary_objectives: dict = field(default_factory=dict)
    targets: dict = field(default_factory=dict)
    primary_target: str | None = None
    secondary_target: str | None = None
    sacrifice_target: str | None = None
    mission_fail_owner: str | None = None
    active_narratives: list = field(default_factory=list)
    agenda_topic: str | None = None
    partner_agreement_streak: int = 0
    partner_agreement_history: list = field(default_factory=list)
    partner_defense_history: list = field(default_factory=list)
    pair_allegation_history: list = field(default_factory=list)
    framed_players: list = field(default_factory=list)
    mission_history: list = field(default_factory=list)
    sabotage_history: list = field(default_factory=list)
    mode_history: list = field(default_factory=list)

    @cached_property
    def _fallback_role_prior(self):
        # Compatibility for standalone strategy callers. This is a fixed legal
        # prior, never a second event-updated or shared agent belief distribution.
        ids, evil = tuple(self.public_tags), set(self.roles)
        counts = {"GOOD": len(ids) - 3, "MERLIN": 1, "ASSASSIN": 1, "EVIL": 1}
        alignments = {r: "EVIL" if r in {"ASSASSIN", "EVIL"} else "GOOD" for r in counts}
        hypotheses = [h for h in enumerate_hypotheses(ids, counts)
                      if {p for p, r in h.roles.items() if alignments[r] == "EVIL"} == evil]
        prior = JointBeliefState(hypotheses, counts, alignments)
        prior.normalize()
        return prior

    @property
    def merlin_probabilities(self):
        """Deprecated read-only prior projection; live callers supply their beliefs."""
        return {p: self._fallback_role_prior.P_role(p, "MERLIN") for p in self.public_tags}

    @property
    def likely_merlin(self):
        return max(self.merlin_probabilities, key=self.merlin_probabilities.get)

    @property
    def partner_agreement_count(self):
        return sum(event["agree"] for event in self.partner_agreement_history)

    @property
    def partner_defense_count(self):
        return len(self.partner_defense_history)


class PublicEvidence:
    """Ingest each public sequence once and retain only bounded structured facts."""

    def __init__(self, player_ids, evil_ids, roles):
        self.ids, self.evil = tuple(player_ids), set(evil_ids)
        self.good = tuple(p for p in self.ids if p not in self.evil)
        self.state = EvilSharedState(
            public_suspicion={p: 2 / len(self.ids) for p in self.ids},
            public_trust={p: .5 for p in self.ids},
            profiles={p: {k: .5 for k in ("aggression", "retaliation", "approval", "consensus",
                                        "evidence_use", "leadership", "support")}
                      for p in self.ids},
            public_tags={p: [] for p in self.ids},
            roles=dict(roles),
        )
        self.events = deque(maxlen=80)
        self.seen = set()
        self.attackers = {}
        self.proposal_votes = {}
        self.round, self.attempt = 1, 1
        self.successes = self.failures = 0

    def observe(self, event):
        if not isinstance(event, dict) or event.get("kind") == "REVEAL":
            return False
        seq, kind = event.get("seq"), event.get("kind")
        if type(seq) is not int or seq < 1 or seq in self.seen:
            return False
        # Whitelisting discards prose, private cards, role tables and model fields.
        fields = {
            "SOCIAL": ("actor", "target", "card", "reason"),
            "TEAM": ("actor", "team", "speaking_order"),
            "TEAM_VOTE": ("team", "votes", "approved"),
            "VOTE": ("actor", "approve", "reason"),
            "MISSION": ("team", "success", "fail_count", "successes", "failures"),
            "ROUND": ("leader", "team_size", "successes", "failures"),
            "PASS": ("actor",), "HOLD": ("actor",),
            "CHALLENGE": ("actor", "target", "evidence"),
            "CITE": ("actor", "evidence"),
            "REACT": ("actor", "target", "card", "reason", "trigger"),
            "CHALLENGE_RESPONSE": ("actor", "target", "card", "reason", "challenger", "challenge", "declined"),
            "TEAM_REVISE": ("actor", "removed", "added", "team"),
        }
        if kind not in fields:
            return False
        clean = {k: deepcopy(event[k]) for k in ("seq", "kind", "round", "attempt") + fields[kind]
                 if k in event}
        for field in ("committed", "strong", "resolve_cost", "resolve_after"):
            if field in event:
                clean[field] = deepcopy(event[field])
        if not self._valid(clean):
            return False
        self.seen.add(seq)
        self.round, self.attempt = clean.get("round", self.round), clean.get("attempt", self.attempt)
        if kind in SOCIAL_EVENTS and "card" in clean:
            refs = event.get("evidence", [])
            if isinstance(refs, list):
                allowed = {e["seq"] for e in self.events if e["kind"] in EVIDENCE_KINDS}
                clean["evidence"] = list(dict.fromkeys(n for n in refs if type(n) is int and n in allowed))[:3]
            self._social(clean, self._pair_allegation(event))
        elif kind == "TEAM_VOTE":
            self._vote(clean)
        elif kind == "MISSION":
            self._mission(clean)
        elif kind == "TEAM" and self.evil <= set(clean["team"]):
            self.state.pair_suspicion = bounded(self.state.pair_suspicion + .035)
        if kind in {"MISSION", "ROUND"}:
            self.successes = clean.get("successes", self.successes)
            self.failures = clean.get("failures", self.failures)
        self.events.append(clean)
        self._tags()
        return True

    def _pair_allegation(self, event):
        statement = event.get("statement", "")
        if (not isinstance(statement, str) or event.get("actor") in self.evil
                or event.get("card") == "DEFEND"):
            return False
        statement = statement[:240]
        if re.search(r"\bnot\b|aren['’]t|isn['’]t|不是|并非|不认为|不觉得", statement, re.IGNORECASE):
            return False
        mentions_both = all(re.search(r"(?<![A-Za-z0-9_])" + re.escape(pid) + r"(?![A-Za-z0-9_])",
                                     statement, re.IGNORECASE) for pid in self.evil)
        return mentions_both and bool(re.search(r"evil|bad|坏人|邪恶|同伙|一伙|关联|配合", statement, re.IGNORECASE))

    def _valid(self, event):
        for key in ("round", "attempt"):
            if key in event and (type(event[key]) is not int or not 1 <= event[key] <= 5):
                return False
        kind = event["kind"]
        if kind not in {"ROUND", "MISSION", "TEAM_VOTE"} and event.get("actor") not in self.ids:
            return False
        if kind in SOCIAL_EVENTS and not event.get("declined", False):
            return event.get("target") in self.ids and event.get("card") in CARDS
        if kind in {"TEAM", "TEAM_REVISE", "TEAM_VOTE", "MISSION"}:
            team = event.get("team")
            if (not isinstance(team, list) or not team or
                    any(p not in self.ids for p in team) or len(set(team)) != len(team)):
                return False
        if kind == "TEAM_VOTE":
            votes = event.get("votes")
            return (isinstance(votes, dict) and set(votes) == set(self.ids)
                    and all(type(v) is bool for v in votes.values())
                    and type(event.get("approved")) is bool)
        if kind == "MISSION":
            return (type(event.get("success")) is bool and type(event.get("fail_count")) is int
                    and 0 <= event["fail_count"] <= len(event["team"]))
        return True

    def _profile(self, pid, key, observed):
        profile = self.state.profiles[pid]
        profile[key] = bounded(.75 * profile[key] + .25 * observed)

    def _narratives(self, *records):
        state = self.state
        for category, targets, seq in records:
            state.active_narratives = [n for n in state.active_narratives
                                      if (n["category"], n["targets"]) != (category, list(targets))]
            state.active_narratives.append({"category": category, "targets": list(targets), "evidence": [seq]})
        state.active_narratives = state.active_narratives[-4:]

    def _social(self, event, pair_allegation=False):
        state = self.state
        actor, target, card, seq = (event[k] for k in ("actor", "target", "card", "seq"))
        aggressive = card in {"ACCUSE", "PRESSURE", "BAIT"}
        self._profile(actor, "aggression", float(aggressive))
        self._profile(actor, "support", float(card == "DEFEND"))
        cited_kinds = {e["kind"] for e in self.events if e["seq"] in event.get("evidence", [])}
        grounded = ((event.get("reason") == "mission_record" and "MISSION" in cited_kinds)
                    or (event.get("reason") == "vote_pattern" and bool(cited_kinds & {"VOTE", "TEAM_VOTE"})))
        self._profile(actor, "evidence_use", float(grounded))
        if actor in self.attackers:
            self._profile(actor, "retaliation", float(aggressive and target == self.attackers.pop(actor)))
        if aggressive and actor != target:
            self.attackers[target] = actor
        recent = [e for e in self.events if e["kind"] in SOCIAL_EVENTS and "card" in e]
        if recent:
            previous = recent[-1]
            agrees = target == previous["target"] and card == previous["card"]
            self._profile(actor, "consensus", float(agrees))
            if agrees and actor != previous["actor"]:
                self._profile(previous["actor"], "leadership", 1)
        credibility = .5 + state.public_trust[actor]
        delta = {"ACCUSE": .075, "PRESSURE": .05, "BAIT": .02, "DEFEND": -.045, "HEDGE": 0}[card]
        state.public_suspicion[target] = bounded(state.public_suspicion[target] + delta * credibility)
        state.public_trust[target] = bounded(state.public_trust[target] - delta * .7 * credibility)
        if pair_allegation:
            state.pair_suspicion = bounded(state.pair_suspicion + .38)
            state.pair_allegation_history.append({"seq": seq, "targets": sorted(self.evil)})
            state.pair_allegation_history = state.pair_allegation_history[-25:]
        if actor in self.evil and target in self.evil and actor != target:
            if card == "DEFEND":
                state.partner_defense_history.append({"seq": seq, "actor": actor, "target": target})
                state.partner_defense_history = state.partner_defense_history[-25:]
                state.pair_suspicion = bounded(state.pair_suspicion + .11)
            elif aggressive:
                state.pair_suspicion = bounded(state.pair_suspicion - .09)
        elif actor in self.evil and recent:
            previous = recent[-1]
            if (previous["actor"] in self.evil and previous["actor"] != actor
                    and previous["target"] == target and previous["card"] == card):
                state.pair_suspicion = bounded(state.pair_suspicion + .12)
        if aggressive:
            self._narratives(("INFORMED_PRESSURE", [target], seq), ("MISDIRECTION", [actor], seq))
        elif card == "DEFEND":
            self._narratives(("PUBLIC_SUPPORT", [target], seq), ("POSSIBLE_AFFILIATION", [actor, target], seq))

    def _vote(self, event):
        state, votes = self.state, event["votes"]
        approvals = sum(votes.values())
        for pid, approve in votes.items():
            self._profile(pid, "approval", float(approve))
            if approvals * 2 != len(self.ids):
                self._profile(pid, "consensus", float(approve == (approvals * 2 > len(self.ids))))
        first, second = sorted(self.evil)
        agree = votes[first] == votes[second]
        state.partner_agreement_streak = state.partner_agreement_streak + 1 if agree else 0
        state.partner_agreement_history.append({"seq": event["seq"], "agree": agree})
        state.partner_agreement_history = state.partner_agreement_history[-25:]
        state.pair_suspicion = bounded(state.pair_suspicion +
            (.035 + .02 * min(state.partner_agreement_streak, 4) if agree else -.10))
        key = (event.get("round", self.round), event.get("attempt", self.attempt))
        self.proposal_votes[key] = deepcopy(event)
        supporters = [p for p in self.ids if votes[p]]
        opponents = [p for p in self.ids if not votes[p]]
        narratives = []
        if supporters:
            narratives.extend([("TEAM_CONFIDENCE", supporters, event["seq"]),
                               ("POSSIBLE_VOTE_ALIGNMENT", supporters, event["seq"])])
        if opponents:
            narratives.extend([("CAUTIOUS_REJECTION", opponents, event["seq"]),
                               ("POSSIBLE_OBSTRUCTION", opponents, event["seq"])])
        self._narratives(*narratives)

    def _mission(self, event):
        state, team, success = self.state, event["team"], event["success"]
        for pid in team:
            delta = -.075 if success else .32 / len(team)
            state.public_suspicion[pid] = bounded(state.public_suspicion[pid] + delta)
            state.public_trust[pid] = bounded(state.public_trust[pid] + (.08 if success else -.20 / len(team)))
        vote = self.proposal_votes.get((event.get("round", self.round), event.get("attempt", self.attempt)))
        if vote:
            for pid, approved in vote["votes"].items():
                if approved and not success:
                    state.public_suspicion[pid] = bounded(state.public_suspicion[pid] + .025)
                elif approved and success:
                    state.public_trust[pid] = bounded(state.public_trust[pid] + .02)
        if self.evil <= set(team) and not success:
            state.pair_suspicion = bounded(state.pair_suspicion + .17)
        state.mission_history.append(deepcopy(event))
        state.mission_history = state.mission_history[-5:]
        if success:
            self._narratives(("TEAM_TRUST", team, event["seq"]), ("POSSIBLE_COVER_SUCCESS", team, event["seq"]))
        else:
            self._narratives(*[("POSSIBLE_INFILTRATOR", [p], event["seq"]) for p in team[:4]])

    def _tags(self):
        state = self.state
        for pid, profile in state.profiles.items():
            tags = []
            for condition, tag in ((profile["aggression"] >= .68, "aggressive"),
                                   (profile["aggression"] <= .32, "cautious"),
                                   (profile["evidence_use"] >= .68, "logic_driven"),
                                   (profile["leadership"] >= .68, "leader"),
                                   (profile["support"] >= .68, "social_trust"),
                                   (profile["retaliation"] >= .68, "emotional"),
                                   (profile["consensus"] >= .68, "follows_consensus"),
                                   (profile["consensus"] <= .32, "independent"),
                                   (state.public_suspicion[pid] >= .62, "suspected"),
                                   (state.public_trust[pid] >= .65, "trusted")):
                if condition:
                    tags.append(tag)
            state.public_tags[pid] = tags
