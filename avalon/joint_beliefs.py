"""Exact role worlds and Bayesian queries. No model, player policy or game secrets."""

from collections import Counter, defaultdict
from dataclasses import dataclass, field
import math


class BeliefContradiction(ValueError):
    """Evidence has no support; never invent a new prior to conceal the conflict."""


@dataclass(init=False)
class JointHypothesis:
    roles: dict
    log_probability: float

    def __init__(self, roles, probability=1.0):
        self.roles = dict(roles)
        self.probability = probability

    @property
    def probability(self):
        return math.exp(self.log_probability)

    @probability.setter
    def probability(self, value):
        if type(value) not in (float, int) or not math.isfinite(value) or value < 0:
            raise ValueError("Invalid hypothesis probability")
        self.log_probability = math.log(value) if value else -math.inf

    @property
    def key(self):
        return tuple(sorted(self.roles.items()))

    def to_dict(self):
        return {"roles": dict(self.roles), "probability": self.probability}


def enumerate_hypotheses(player_ids, role_counts):
    """Multiset enumeration: identical servants never create duplicate worlds."""
    ids = tuple(player_ids)
    if (not ids or any(not isinstance(p, str) or not p for p in ids) or len(set(ids)) != len(ids)
            or not isinstance(role_counts, dict) or not role_counts
            or any(not isinstance(r, str) or not r or type(n) is not int or n <= 0 for r, n in role_counts.items())
            or sum(role_counts.values()) != len(ids)):
        raise ValueError("Invalid configured role composition")
    remaining = dict(sorted(role_counts.items()))
    worlds = []

    def assign(index, roles):
        if index == len(ids):
            worlds.append(JointHypothesis(roles))
            return
        for role in remaining:
            if remaining[role]:
                remaining[role] -= 1
                roles[ids[index]] = role
                assign(index + 1, roles)
                remaining[role] += 1

    assign(0, {})
    for h in worlds:
        h.probability = 1 / len(worlds)
    return worlds


@dataclass
class JointBeliefState:
    hypotheses: list[JointHypothesis] = field(default_factory=list)
    role_counts: dict = field(default_factory=dict)
    role_alignments: dict = field(default_factory=dict)
    # These are constraints, not zero-weight entries eligible for resurrection.
    eliminated_keys: set = field(default_factory=set, repr=False)

    def __post_init__(self):
        if self.hypotheses and not self.role_counts:
            self.role_counts = dict(Counter(self.hypotheses[0].roles.values()))
        if not self.role_alignments:
            supported = {"GOOD": "GOOD", "MERLIN": "GOOD", "ASSASSIN": "EVIL", "EVIL": "EVIL"}
            self.role_alignments = {r: supported[r] for r in self.role_counts if r in supported}

    def normalize(self):
        """Stable log-sum-exp; a numerical floor never removes a soft hypothesis.

        The floor is only for floating-point underflow, not a suspicion cap. NaN,
        +inf and empty support are errors. Explicit zeros are permanently removed.
        All validation precedes mutation so failures preserve the previous state.
        """
        if not self.hypotheses:
            raise BeliefContradiction("No legal role hypothesis")
        if (not self.role_counts or any(type(n) is not int or n <= 0 for n in self.role_counts.values())
                or set(self.role_counts) != set(self.role_alignments)):
            raise ValueError("Invalid configured role composition")
        ids = set(self.hypotheses[0].roles)
        keys = set()
        for h in self.hypotheses:
            if (h.key in keys or set(h.roles) != ids or Counter(h.roles.values()) != Counter(self.role_counts)
                    or any(r not in self.role_alignments for r in h.roles.values())
                    or any(a not in {"GOOD", "EVIL"} for a in self.role_alignments.values())
                    or math.isnan(h.log_probability) or h.log_probability == math.inf):
                raise ValueError("Invalid joint probability state")
            keys.add(h.key)
        active = [h for h in self.hypotheses if h.log_probability != -math.inf and h.key not in self.eliminated_keys]
        if not active:
            raise BeliefContradiction("Total hypothesis probability is zero")
        maximum = max(h.log_probability for h in active)
        relative = [max(-690.0, h.log_probability - maximum) for h in active]
        log_total = math.log(math.fsum(math.exp(value) for value in relative))
        zero_keys = {h.key for h in self.hypotheses if h.log_probability == -math.inf}
        for h, value in zip(active, relative):
            h.log_probability = value - log_total
        self.eliminated_keys.update(zero_keys)
        self.hypotheses = active

    @property
    def player_ids(self):
        return tuple(self.hypotheses[0].roles) if self.hypotheses else ()

    def _query(self, assignments):
        if not isinstance(assignments, dict):
            raise ValueError("A belief query must be a player map")
        result = {}
        for pid, value in assignments.items():
            if pid not in self.player_ids:
                raise ValueError("Unknown belief query player")
            if isinstance(value, str):
                value = {"alignment" if value in {"GOOD", "EVIL"} else "role": value}
            if not isinstance(value, dict) or set(value) not in ({"role"}, {"alignment"}):
                raise ValueError("Specify a role or alignment")
            key, expected = next(iter(value.items()))
            choices = self.role_counts if key == "role" else {"GOOD", "EVIL"}
            if not isinstance(expected, str) or expected not in choices:
                raise ValueError("Unknown query role or alignment")
            result[pid] = (key, expected)
        return result

    def _matches(self, hypothesis, query):
        return all((hypothesis.roles[pid] if key == "role" else self.role_alignments[hypothesis.roles[pid]]) == value
                   for pid, (key, value) in query.items())

    def P_joint(self, assignments):
        query = self._query(assignments)
        return min(1.0, math.fsum(h.probability for h in self.hypotheses if self._matches(h, query)))

    def P_role(self, agent_id, role):
        return self.P_joint({agent_id: {"role": role}})

    def P_alignment(self, agent_id, alignment):
        return self.P_joint({agent_id: {"alignment": alignment}})

    def team_evil_count_distribution(self, team):
        """Exact query over the joint distribution, including correlations."""
        team = tuple(team)
        if len(set(team)) != len(team) or not set(team) <= set(self.player_ids):
            raise ValueError("Invalid team query")
        return {k: math.fsum(h.probability for h in self.hypotheses
                            if sum(self.role_alignments[h.roles[p]] == "EVIL" for p in team) == k)
                for k in range(len(team) + 1)}

    def team_outcome_risk(self, team, rules, model):
        counts = self.team_evil_count_distribution(team)
        return {"clean_probability": counts[0], "evil_count_probabilities": counts,
                "expected_evil_count": math.fsum(k * p for k, p in counts.items()),
                "mission_failure_probability": math.fsum(
                    p * model.team_failure_probability(k, rules, team) for k, p in counts.items())}

    def P_conditional(self, query, condition):
        """None denotes an impossible condition, rather than a fabricated probability."""
        query, condition = self._query(query), self._query(condition)
        support = [h for h in self.hypotheses if self._matches(h, condition)]
        if not support:
            return None
        # Normalize inside the condition for accuracy even when its mass is tiny.
        maximum = max(h.log_probability for h in support)
        weights = [math.exp(h.log_probability - maximum) for h in support]
        return min(1.0, math.fsum(w for h, w in zip(support, weights) if self._matches(h, query)) / math.fsum(weights))

    def marginals(self):
        return {p: {"roles": {r: self.P_role(p, r) for r in sorted(self.role_counts)},
                    "alignment": {a: self.P_alignment(p, a) for a in ("GOOD", "EVIL")}}
                for p in self.player_ids}

    def top_hypotheses(self, limit=5):
        return [h.to_dict() for h in sorted(self.hypotheses, key=lambda h: (-h.log_probability, h.key))[:max(0, limit)]]

    def alignment_worlds(self):
        """Read-only compatibility projection, never an independent alignment state."""
        grouped = defaultdict(list)
        for h in self.hypotheses:
            evil = tuple(sorted(p for p, r in h.roles.items() if self.role_alignments[r] == "EVIL"))
            grouped[evil].append(h.probability)
        return [{"evil_team": list(team), "weight": min(1.0, math.fsum(values))}
                for team, values in sorted(grouped.items())]


@dataclass(frozen=True)
class BeliefUpdateRecord:
    observation_id: str
    evidence: list
    prior_top_hypotheses: list
    posterior_top_hypotheses: list
    marginal_changes: dict
    eliminated_count: int
    largest_marginal_change: dict | None


def marginal_changes(before, after):
    changes = {}
    largest = None
    for pid in before:
        for kind in ("alignment", "roles"):
            for label, prior in before[pid][kind].items():
                posterior = after[pid][kind][label]
                delta = posterior - prior
                if abs(delta) > 1e-12:
                    change = {"before": prior, "after": posterior, "delta": delta}
                    changes.setdefault(pid, {}).setdefault(kind, {})[label] = change
                    if largest is None or abs(delta) > abs(largest["delta"]):
                        largest = {"agent": pid, "kind": kind, "label": label, **change}
    return changes, largest


# Function forms are convenient for callers that do not own the state object.
def marginal_role_probability(beliefs, agent_id, role):
    return beliefs.P_role(agent_id, role)


def P_role(beliefs, agent_id, role):
    return beliefs.P_role(agent_id, role)


def P_alignment(beliefs, agent_id, alignment):
    return beliefs.P_alignment(agent_id, alignment)


def P_joint(beliefs, assignments):
    return beliefs.P_joint(assignments)


def P_conditional(beliefs, query, condition):
    return beliefs.P_conditional(query, condition)
