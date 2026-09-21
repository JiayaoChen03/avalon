"""Future, explicitly triggered second-order estimates; no estimator runs today.

An implementation receives the observer's supplied summary and legal public
observations, never another Agent, its private knowledge or its belief engine.
Estimates cannot feed back into first-order probabilities as observed evidence.
"""

from copy import deepcopy
from dataclasses import dataclass
from enum import Enum
import math
from typing import Protocol, Sequence

from .evidence import Observation


MAX_MODELED_DEPTH = 1


class ToMTrigger(str, Enum):
    INFORMATION_LEAKAGE = "information_leakage"
    MERLIN_SEARCH = "merlin_search"
    ROLE_AMBIGUITY = "role_ambiguity"
    DECEPTION_CHECK = "deception_check"
    HIGH_IMPACT_ACCUSATION = "high_impact_accusation"
    STRONG_CERTAINTY = "strong_certainty"


@dataclass(frozen=True)
class ToMRequest:
    observer_id: str
    modeled_agent_id: str
    trigger: ToMTrigger

    def __post_init__(self):
        if (not isinstance(self.observer_id, str) or not self.observer_id
                or not isinstance(self.modeled_agent_id, str) or not self.modeled_agent_id
                or self.observer_id == self.modeled_agent_id or not isinstance(self.trigger, ToMTrigger)):
            raise ValueError("A ToM request requires one other agent and an explicit trigger")


@dataclass(frozen=True)
class ModeledBelief:
    observer_id: str
    modeled_agent_id: str
    # Player -> role -> estimated probability. No recursive modeled beliefs.
    estimated_marginals: dict[str, dict[str, float]]
    updated_at: int

    def __post_init__(self):
        ToMRequest(self.observer_id, self.modeled_agent_id, ToMTrigger.DECEPTION_CHECK)
        if (type(self.updated_at) is not int or self.updated_at < 0 or not isinstance(self.estimated_marginals, dict)
                or any(not isinstance(pid, str) or not isinstance(roles, dict) or not roles
                       or any(not isinstance(role, str) or type(p) not in (int, float)
                              or not math.isfinite(p) or not 0 <= p <= 1 for role, p in roles.items())
                       or not math.isclose(math.fsum(roles.values()), 1, abs_tol=1e-9)
                       for pid, roles in self.estimated_marginals.items())):
            raise ValueError("Invalid bounded modeled marginals")
        object.__setattr__(self, "estimated_marginals", deepcopy(self.estimated_marginals))


class BoundedTheoryOfMind(Protocol):
    def estimate(self, request: ToMRequest, *, observer_summary: dict,
                 public_observations: Sequence[Observation]) -> ModeledBelief:
        """Estimate one selected agent on demand; no recursion or background loop."""
        ...
