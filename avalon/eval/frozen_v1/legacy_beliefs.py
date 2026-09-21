"""Evaluation adapters, the frozen pre-joint baseline, and proper scoring rules.

The baseline's numerical rules are ported from avalon/agents.py at 74fd078.
Model-authored replacement estimates are deliberately absent in this controlled
ablation. Its joint distribution is a *scoring-only* product projection, never
used to make its independent estimates look consistent or to drive its actions.
"""

from copy import deepcopy
import math

from avalon.chronicle import PUBLIC_KINDS
from avalon.cognition import BeliefEngine
from avalon.engine import EVIL_ROLES, SOCIAL_EVENTS
from avalon.evidence import LikelihoodConfig
from avalon.joint_beliefs import enumerate_hypotheses


BASELINE_COMMIT = "74fd078"
BASELINE_CONFIG = {
    "initial_evil": "2 / (players - 1)", "initial_merlin": 0.1,
    "social_deltas": {"ACCUSE": 0.06, "DEFEND": -0.035, "HEDGE": 0.01},
    "risky_approval_delta": 0.02, "risky_team_threshold": 0.6,
    "merlin_correct_vote_delta": 0.06, "merlin_incorrect_vote_delta": -0.025,
    "successful_mission_delta": -0.09, "failed_mission_delta": "0.25 / team_size",
    "model_estimate_replacement": "disabled for both variants (controlled local mode)",
}
EPSILON = 1e-15  # Only log scoring is clipped; exported probabilities are not.
UPDATE_KINDS = {"TEAM", "TEAM_REVISE", "SOCIAL", "REACT", "CHALLENGE_RESPONSE",
                "CHALLENGE", "VOTE", "STRONG_VOTE", "TEAM_VOTE", "MISSION", "ASSASSINATE"}


def authorized_worlds(view):
    """Public role composition plus this observer's initial private knowledge."""
    knowledge, rules = view["private_knowledge"], view["rules"]
    roles = {view["self"]: knowledge["self_role"]}
    roles.update({item["player"]: item["role"] for item in knowledge["known_special_roles"]})
    result = []
    for world in enumerate_hypotheses([p["id"] for p in view["players"]], rules["role_counts"]):
        if (all(world.roles[p] == r for p, r in roles.items())
                and all(rules["role_alignments"][world.roles[p]] == "EVIL"
                        for p in knowledge["known_evil_players"])
                and all(rules["role_alignments"][world.roles[p]] == "GOOD"
                        for p in knowledge["known_good_players"])):
            result.append(world.key)
    if not result:
        raise ValueError("Initial knowledge has no legal role assignment")
    return tuple(result)


class BaselineBeliefs:
    """Frozen deterministic belief part of the last committed production Agent."""
    representation = "independent_marginals_product_projection"

    def __init__(self, view):
        self.pid, self.role = view["self"], view["role"]
        self.ids = tuple(p["id"] for p in view["players"])
        self.known_evil = set(view["known_evil"])
        self.knowledge = deepcopy(view["private_knowledge"])
        self.universe = authorized_worlds(view)
        self.estimates = {p: {"evil": 2 / (len(self.ids) - 1), "merlin": 0.1} for p in self.ids}
        self.seen_seq = 0
        self._lock_facts()

    def _lock_facts(self):
        # Keep these clamps and priors faithful to the old implementation.
        for pid, belief in self.estimates.items():
            belief["evil"] = max(0.0, min(1.0, belief["evil"]))
            if pid in self.known_evil:
                belief["evil"], belief["merlin"] = 1.0, 0.0
            elif self.known_evil:
                belief["evil"] = 0.0
            if self.role == "MERLIN":
                belief["merlin"] = float(pid == self.pid)
            if pid == self.pid:
                belief["evil"] = float(self.role in EVIL_ROLES)
                belief["merlin"] = float(self.role == "MERLIN")
            belief["merlin"] = max(0.0, min(1 - belief["evil"], belief["merlin"]))

    def marginals(self):
        return deepcopy(self.estimates)

    def observe(self, event):
        if event["kind"] not in PUBLIC_KINDS or event["seq"] <= self.seen_seq:
            return False
        self.seen_seq = event["seq"]
        before = self.marginals()
        beliefs, kind = self.estimates, event["kind"]
        if kind in SOCIAL_EVENTS and "card" in event:
            actor, target = event["actor"], event["target"]
            delta = BASELINE_CONFIG["social_deltas"].get(event["card"], 0)
            beliefs[target]["evil"] += delta * (1 - beliefs[actor]["evil"])
        elif kind == "TEAM_VOTE":
            risk = sum(beliefs[p]["evil"] for p in event["team"]) / len(event["team"])
            for pid, approved in event["votes"].items():
                if self.role in EVIL_ROLES and pid not in self.known_evil:
                    dirty = bool(set(event["team"]) & self.known_evil)
                    beliefs[pid]["merlin"] += 0.06 if approved != dirty else -0.025
                elif risk > 0.6 and approved:
                    beliefs[pid]["evil"] += 0.02
        elif kind == "MISSION":
            for pid in event["team"]:
                beliefs[pid]["evil"] += -0.09 if event["success"] else 0.25 / len(event["team"])
        self._lock_facts()
        return before != self.estimates

    def team_risk(self, team):
        """Independent approximation to the same event: at least one Evil."""
        return 1 - math.prod(1 - self.estimates[p]["evil"] for p in team)

    def distribution(self):
        logs = []
        for world in self.universe:
            value = 0.0
            for pid, role in world:
                b = self.estimates[pid]
                q = (float(role == self.role) if pid == self.pid else
                     b["evil"] / 2 if role in EVIL_ROLES else
                     b["merlin"] if role == "MERLIN" else max(0, 1 - b["evil"] - b["merlin"]))
                value += math.log(q) if q else -math.inf
            logs.append(value)
        maximum = max(logs)
        if maximum == -math.inf:
            return {}  # Expose collapse; do not replace it with a uniform prior.
        weights = [math.exp(value - maximum) for value in logs]
        total = math.fsum(weights)
        return {world: weight / total for world, weight in zip(self.universe, weights)}


class JointBeliefs:
    representation = "native_joint"

    def __init__(self, view, likelihood=None):
        self.pid, self.role = view["self"], view["role"]
        self.ids = tuple(p["id"] for p in view["players"])
        self.knowledge = deepcopy(view["private_knowledge"])
        self.universe = authorized_worlds(view)
        self.engine = BeliefEngine(deepcopy(view), likelihood_config=likelihood or LikelihoodConfig())

    def observe(self, event):
        prior = self.engine.beliefs.update_records[-1]
        self.engine.observe(deepcopy(event))
        return self.engine.beliefs.update_records[-1] is not prior

    def marginals(self):
        return self.engine.marginals()

    def distribution(self):
        return {h.key: h.probability for h in self.engine.beliefs.hypotheses}

    def team_risk(self, team):
        return 1 - self.engine.P_joint({p: {"alignment": "GOOD"} for p in team})


class ReferenceBeliefs(BaselineBeliefs):
    """Static private-knowledge controller used only to generate frozen replays."""

    def observe(self, event):
        return False


def make_beliefs(variant, view, likelihood=None):
    if variant == "baseline":
        return BaselineBeliefs(view)
    if variant == "joint_belief":
        return JointBeliefs(view, likelihood)
    if variant == "reference":
        return ReferenceBeliefs(view)
    raise ValueError(f"Unknown belief variant: {variant}")


def score_beliefs(beliefs, truth, previous=None):
    """Host-side scoring. Truth is never an input to an observer or a policy.

    Binary scores average over OTHER seats. Unknown-seat scores use the initially
    unknown alignments, so knowledge from later events cannot change denominators.
    Ranks are midranks for ties; an eliminated truth ranks universe_size + 1.
    """
    marginals = beliefs.marginals()
    distribution = beliefs.distribution()
    if distribution and (any(not math.isfinite(p) or p < 0 for p in distribution.values())
                         or not math.isclose(math.fsum(distribution.values()), 1, abs_tol=1e-10)):
        raise ValueError("Belief distribution is not normalized")
    known = set(beliefs.knowledge["known_good_players"]) | set(beliefs.knowledge["known_evil_players"])
    others = [p for p in beliefs.ids if p != beliefs.pid]
    unknown = [p for p in others if p not in known]
    errors, losses = {}, {}
    for pid in others:
        p, actual = marginals[pid]["evil"], float(truth[pid] in EVIL_ROLES)
        if not math.isfinite(p) or not 0 <= p <= 1:
            raise ValueError("Invalid marginal probability")
        errors[pid] = (p - actual) ** 2
        losses[pid] = -math.log(max(EPSILON, p if actual else 1 - p))
    mean = lambda values: math.fsum(values) / len(values) if values else None
    true_p = distribution.get(tuple(sorted(truth.items())), 0.0) if distribution else None
    rank = None
    if true_p is not None:
        if true_p == 0:
            rank = len(beliefs.universe) + 1.0
        else:
            tied = sum(math.isclose(p, true_p, rel_tol=1e-12, abs_tol=0) for p in distribution.values())
            higher = sum(p > true_p and not math.isclose(p, true_p, rel_tol=1e-12, abs_tol=0)
                         for p in distribution.values())
            rank = 1 + higher + (tied - 1) / 2
    entropy = -math.fsum(p * math.log(p) for p in distribution.values() if p) if distribution else None
    result = {
        "joint_representation": beliefs.representation,
        "true_hypothesis_probability": true_p, "true_hypothesis_rank": rank,
        "brier_score": mean(list(errors.values())), "log_loss": mean(list(losses.values())),
        "unknown_brier_score": mean([errors[p] for p in unknown]),
        "unknown_log_loss": mean([losses[p] for p in unknown]), "unknown_targets": len(unknown),
        "joint_log_loss": -math.log(max(EPSILON, true_p)) if true_p is not None else None,
        "entropy": entropy, "remaining_hypotheses": sum(p > 0 for p in distribution.values()),
        "max_hypothesis_probability": max(distribution.values()) if distribution else None,
        "distribution_collapsed": int(not distribution),
        "truth_probability_collapsed": int(true_p is not None and true_p <= EPSILON),
        "overconfident_wrong_world": int(bool(distribution) and max(distribution.values()) >= .95 and true_p < .05),
        "overconfident_wrong_marginals": sum(loss > -math.log(.05) for loss in losses.values()),
        "evil_count_error": abs(sum(v["evil"] for v in marginals.values()) - 2),
        "merlin_count_error": abs(sum(v["merlin"] for v in marginals.values()) - 1),
        "entropy_down_truth_down": int(previous is not None and entropy is not None
            and previous.get("entropy") is not None and previous.get("true_hypothesis_probability") is not None
            and entropy < previous["entropy"] - 1e-12
            and true_p < previous["true_hypothesis_probability"] - 1e-12),
    }
    for pid, values in marginals.items():
        result[f"evil_probability_{pid}"] = values["evil"]
        result[f"merlin_probability_{pid}"] = values["merlin"]
    return result
