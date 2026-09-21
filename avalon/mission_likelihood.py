"""Conservative mission evidence from public rules, never referee state.

Flexible saboteurs are conditionally independent Bernoulli(q). This is a
modeling assumption, not knowledge of the opponents' actual policy. Tempering
is applied once, after summing counts for a coarsened public observation.
"""

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class MissionLikelihoodConfig:
    enabled: bool = False
    success_enabled: bool = True
    q: float = .5
    gamma: float = .5

    def __post_init__(self):
        if (type(self.enabled) is not bool or type(self.success_enabled) is not bool
                or type(self.q) not in (int, float) or not 0 < self.q < 1
                or type(self.gamma) not in (int, float) or not 0 < self.gamma <= 1):
            raise ValueError("Mission likelihood requires 0 < q < 1 and 0 < gamma <= 1")


def public_outcome(payload, rules):
    """Validate and project only public outcome fields and production rule flags."""
    team = list(payload["team"])
    tau = payload.get("fail_threshold", rules["fail_threshold"])
    count, success = payload.get("fail_count"), payload.get("success")
    if (not team or len(set(team)) != len(team) or type(tau) is not int or tau < 1
            or count is not None and (type(count) is not int or not 0 <= count <= len(team))
            or success is not None and type(success) is not bool
            or count is None and success is None
            or count is not None and success is not None and success != (count < tau)
            or any(type(rules[k]) is not bool for k in ("good_may_fail", "evil_may_succeed"))):
        raise ValueError("Invalid public mission outcome")
    return {"team": team, "fail_threshold": tau, "fail_count": count,
            "success": (count < tau) if success is None else success,
            "good_may_fail": rules["good_may_fail"], "evil_may_succeed": rules["evil_may_succeed"],
            "outcome_observation_type": "exact_count" if count is not None else "boolean"}


def compatible_counts(outcome):
    if outcome["fail_count"] is not None:
        return (outcome["fail_count"],)
    return tuple(f for f in range(len(outcome["team"]) + 1)
                 if (f < outcome["fail_threshold"]) == outcome["success"])


def possible_counts(evil_count, outcome):
    forced = 0 if outcome["evil_may_succeed"] else evil_count
    maximum = len(outcome["team"]) if outcome["good_may_fail"] else evil_count
    return range(forced, maximum + 1)


class MissionOutcomeLikelihood:
    version = "independent-sabotage-v2-tempered"

    def __init__(self, config=None):
        self.config = config or MissionLikelihoodConfig()

    @staticmethod
    def feasible(evil_count, outcome):
        return bool(set(compatible_counts(outcome)) & set(possible_counts(evil_count, outcome)))

    def skip_reason(self, outcome):
        if not self.config.enabled:
            return "configuration_disabled"
        if outcome["success"] and not self.config.success_enabled:
            return "success_soft_disabled"
        if outcome["good_may_fail"]:
            return "unsupported_good_sabotage_semantics"
        return None

    def count_distribution(self, evil_count, outcome):
        if outcome["good_may_fail"]:
            raise ValueError("Good sabotage policy is not modeled")
        if not outcome["evil_may_succeed"]:
            return {evil_count: 1.0}
        q = self.config.q
        return {f: math.comb(evil_count, f) * q ** f * (1 - q) ** (evil_count - f)
                for f in range(evil_count + 1)}

    def probability(self, evil_count, outcome):
        distribution = self.count_distribution(evil_count, outcome)
        return math.fsum(distribution.get(f, 0.0) for f in compatible_counts(outcome))

    def evaluate(self, evil_count, outcome):
        if self.skip_reason(outcome):
            return 1.0
        if not self.feasible(evil_count, outcome):
            raise ValueError("Hard mission support must precede its soft factor")
        # q is strictly interior. Floor guards arithmetic, never hard-eliminates.
        return math.exp(self.config.gamma * math.log(max(1e-300, self.probability(evil_count, outcome))))

    def team_failure_probability(self, evil_count, rules, team):
        outcome = public_outcome({"team": list(team), "success": False}, rules)
        return self.probability(evil_count, outcome)
