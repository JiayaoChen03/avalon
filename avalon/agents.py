"""Independent private state and a cached per-mission LLM action policy."""

from collections import deque
from copy import deepcopy
import math

from .engine import CARDS, EVIL_ROLES, REASONS
from .llm import LLMError


PROFILE_FIELDS = {"aggression", "retaliation", "approval", "consensus"}
STRATEGIES = {"observe", "probe", "protect", "misdirect"}


def _probability(value):
    return type(value) in (int, float) and 0 <= value <= 1 and math.isfinite(value)


def validate_plan(raw, ids):
    """Reject malformed model output atomically; no partial private-state updates."""
    fields = {"beliefs", "profiles", "strategy", "team_rank", "vote_threshold",
              "approve_last", "mission", "social", "assassin_rank"}
    if not isinstance(raw, dict) or set(raw) != fields:
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
    social = raw["social"]
    if (not isinstance(social, dict) or set(social) != {"card", "target", "reason"}
            or not isinstance(social["card"], str) or social["card"] not in CARDS
            or not isinstance(social["target"], str) or social["target"] not in ids
            or not isinstance(social["reason"], str) or social["reason"] not in REASONS):
        raise ValueError("Invalid social action")
    return deepcopy(raw)


class Agent:
    def __init__(self, view, client=None):
        self.id, self.role = view["self"], view["role"]
        self.ids = [p["id"] for p in view["players"]]
        self.known_evil = set(view["known_evil"])
        self.client = client
        self.memory = {
            "beliefs": {p: {"evil": 2 / (len(self.ids) - 1), "merlin": 0.1} for p in self.ids},
            "profiles": {p: {key: 0.5 for key in sorted(PROFILE_FIELDS)} for p in self.ids},
        }
        self.plan = None
        self.plans, self.sources, self.calls = {}, {}, {}
        self.seen_seq = 0
        self.attacks = {}
        self.evidence = deque(maxlen=6)
        self.snapshots = []
        self._lock_facts()

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

    def _mock_plan(self, view):
        beliefs = self.memory["beliefs"]
        seat = self.ids.index(self.id)
        # Tie breaks depend on this seat, never the referee's shuffle seed/other roles.
        tie = lambda p: (self.ids.index(p) - seat) % len(self.ids)
        rank = sorted(self.ids, key=lambda p: (beliefs[p]["evil"], tie(p)))
        if self.role in EVIL_ROLES:
            rank = [self.id] + [p for p in rank if p != self.id]
        others = [p for p in self.ids if p != self.id]
        target = max(others, key=lambda p: (beliefs[p]["evil"], -tie(p)))
        card = CARDS[(view["round"] + seat) % len(CARDS)]
        if card in {"PRESSURE", "BAIT"}:
            target = max(others, key=lambda p: self.memory["profiles"][p]["retaliation"])
        elif card == "DEFEND":
            target = min(others, key=lambda p: (beliefs[p]["evil"], tie(p)))
        return {
            **deepcopy(self.memory),
            "strategy": "probe" if card in {"PRESSURE", "BAIT"} else "observe",
            "team_rank": rank, "vote_threshold": 0.56, "approve_last": True,
            "mission": "FAIL" if self.role in EVIL_ROLES and (view["round"] > 1 or seat % 2 == 0)
            else "SUCCESS",
            "social": {"card": card, "target": target,
                       "reason": "test_reaction" if card in {"PRESSURE", "BAIT"} else "vote_pattern"},
            "assassin_rank": sorted(self.ids, key=lambda p: (-beliefs[p]["merlin"], tie(p))),
        }

    def prepare(self, view):
        round_no = view["round"]
        if round_no in self.plans:
            self.plan = deepcopy(self.plans[round_no])
            return self.sources[round_no]
        plan, source = self._mock_plan(view), "mock"
        if self.client is not None:
            self.calls[round_no] = 1  # Reserve budget before I/O, including failed requests.
            context = {"game": deepcopy(view), "memory": deepcopy(self.memory),
                       "evidence": list(self.evidence)}
            try:
                plan = validate_plan(self.client.complete(context), self.ids)
                source = "llm"
            except LLMError as error:
                source = f"fallback:{error}"
            except (ValueError, TypeError):
                source = "fallback:invalid_plan"
        self.memory = {key: deepcopy(plan[key]) for key in ("beliefs", "profiles")}
        self._lock_facts()
        self.plan = plan
        self.plans[round_no] = deepcopy(plan)
        self.sources[round_no] = source
        return source

    def observe(self, event):
        """Update from public facts only; repeated delivery is harmless."""
        if event["seq"] <= self.seen_seq:
            return
        self.seen_seq = event["seq"]
        kind = event["kind"]
        beliefs, profiles = self.memory["beliefs"], self.memory["profiles"]

        def update(pid, field, observed):
            profiles[pid][field] = round(0.75 * profiles[pid][field] + 0.25 * observed, 4)

        if kind == "SOCIAL":
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
            self.evidence.append({k: event[k] for k in ("round", "kind", "actor", "target", "card")})
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
            self.evidence.append({k: event[k] for k in ("round", "kind", "team", "success", "fail_count")})
        self._lock_facts()

    def choose_team(self, size, attempt=1):
        rank = self.plan["team_rank"]
        ordered = sorted(rank, key=lambda p: rank.index(p) / len(rank)
                         + 0.3 * self.memory["beliefs"][p]["evil"])
        candidates = ordered[size-1:]
        return ordered[:size-1] + [candidates[(attempt - 1) % len(candidates)]]

    def social_action(self):
        return deepcopy(self.plan["social"])

    def vote(self, team, attempt):
        if attempt == 5 and self.plan["approve_last"]:
            return True
        if self.role in EVIL_ROLES:
            risk = 0.0 if set(team) & self.known_evil else 1.0
        else:
            risk = sum(self.memory["beliefs"][p]["evil"] for p in team) / len(team)
        return risk <= self.plan["vote_threshold"]

    def mission(self):
        return self.plan["mission"] if self.role in EVIL_ROLES else "SUCCESS"

    def assassinate(self):
        rank = self.plan["assassin_rank"]
        candidates = [p for p in rank if p not in self.known_evil and p != self.id]
        return max(candidates, key=lambda p: self.memory["beliefs"][p]["merlin"]
                   - 0.04 * rank.index(p))

    def record_snapshot(self, round_no, human_id="P1"):
        self.snapshots.append({"round": round_no,
                               "belief": deepcopy(self.memory["beliefs"][human_id]),
                               "profile": deepcopy(self.memory["profiles"][human_id]),
                               "strategy": self.plan["strategy"],
                               "social": self.social_action(), "evidence": deepcopy(list(self.evidence))})

    def dossier(self):
        return {"agent": self.id, "snapshots": deepcopy(self.snapshots),
                "calls_by_round": dict(self.calls), "sources": dict(self.sources)}
