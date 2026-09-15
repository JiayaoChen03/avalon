"""Deterministic rules and public events. This module never calls an LLM."""

from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
import random


CARDS = ("ACCUSE", "DEFEND", "HEDGE", "PRESSURE", "BAIT")
EVIL_ROLES = {"ASSASSIN", "EVIL"}
TEAM_SIZES = {5: (2, 3, 2, 3, 3), 6: (2, 3, 4, 3, 4)}
DIRECTIONS = ("clockwise", "counterclockwise")
REASONS = {
    "observe": "保留判断，观察后续行动",
    "mission_record": "参考公开任务记录",
    "vote_pattern": "参考公开投票与站队",
    "support": "公开支持这位玩家",
    "test_reaction": "试探目标的公开反应",
    "team_risk": "根据当前队伍判断风险",
    "last_chance": "已到第五次提案，需要作出选择",
    "strategy": "执行本轮行动策略",
    "human_choice": "人类玩家选择",
}


@dataclass(frozen=True)
class Player:
    id: str
    name: str
    role: str


def validate_social(action, ids, events=None, require_statement=False):
    basic = {"card", "target", "reason"}
    extended = basic | {"statement", "rationale", "evidence"}
    if (not isinstance(action, dict) or set(action) not in (basic, extended)
            or require_statement and set(action) != extended
            or not isinstance(action["card"], str) or action["card"] not in CARDS
            or not isinstance(action["target"], str) or action["target"] not in ids
            or not isinstance(action["reason"], str) or action["reason"] not in REASONS):
        raise ValueError("Invalid social action")
    if set(action) == basic:
        return
    for key in ("statement", "rationale"):
        value = action[key]
        if not isinstance(value, str) or not value.strip() or len(value) > 240 or not value.isprintable():
            raise ValueError("Public statements must be short printable text")
    refs = action["evidence"]
    if (not isinstance(refs, list) or len(refs) > 3 or any(type(n) is not int or n < 1 for n in refs)
            or len(set(refs)) != len(refs)):
        raise ValueError("Invalid public evidence references")
    if events is not None:
        public = {e["seq"]: e for e in events if e["kind"] in {"TEAM", "SOCIAL", "VOTE", "TEAM_VOTE", "MISSION"}}
        if not set(refs) <= public.keys():
            raise ValueError("Evidence must refer to existing public actions")
        needed = {"mission_record": {"MISSION"}, "vote_pattern": {"VOTE", "TEAM_VOTE"}}.get(action["reason"])
        if needed and not any(public[n]["kind"] in needed for n in refs):
            raise ValueError("The reason must cite matching public history")


def make_players(count=5, seed=None, human_name="YOU"):
    if count not in TEAM_SIZES:
        raise ValueError("Only 5 or 6 players are supported.")
    roles = ["MERLIN", "ASSASSIN", "EVIL"] + ["GOOD"] * (count - 3)
    random.Random(seed).shuffle(roles)
    names = [human_name, "NOVA", "ATLAS", "ECHO", "SAGE", "LYRA"]
    return [Player(f"P{i+1}", names[i], role) for i, role in enumerate(roles)]


class Game:
    def __init__(self, players, seed=None, direction=None):
        count = len(players)
        if count not in TEAM_SIZES:
            raise ValueError("Only 5 or 6 players are supported.")
        if Counter(p.role for p in players) != Counter(
                ["MERLIN", "ASSASSIN", "EVIL"] + ["GOOD"] * (count - 3)):
            raise ValueError("Invalid role composition.")
        if len({p.id for p in players}) != count:
            raise ValueError("Player IDs must be unique.")
        self.players = {p.id: p for p in players}
        self.ids = list(self.players)
        # Keep the public draw independent of the hidden role shuffle, also in seeded games.
        leader_seed = None if seed is None else f"leader:{seed}"
        self.leader_index = random.Random(leader_seed).randrange(count)
        if direction is not None and direction not in DIRECTIONS:
            raise ValueError("Unknown speaking direction")
        direction_seed = None if seed is None else f"direction:{seed}"
        self.direction = direction or random.Random(direction_seed).choice(DIRECTIONS)
        self.round = 1
        self.attempt = 1
        self.successes = self.failures = 0
        self.phase = "team"
        self.team = []
        self.spoken = set()
        self.winner = None
        self.events = []
        self.missions = []
        self._emit("START", players=self.public_players())
        self._emit("LEADER", actor=self.leader, reason="random_draw")
        self._emit("DIRECTION", direction=self.direction, order=self.speaking_order)
        self._round_event()

    @property
    def leader(self):
        return self.ids[self.leader_index]

    @property
    def team_size(self):
        return TEAM_SIZES[len(self.ids)][self.round - 1]

    @property
    def speaking_order(self):
        step = 1 if self.direction == "clockwise" else -1
        return [self.ids[(self.leader_index + step * i) % len(self.ids)] for i in range(len(self.ids))]

    def public_players(self):
        return [{"id": p.id, "name": p.name} for p in self.players.values()]

    def _emit(self, kind, **data):
        self.events.append({"seq": len(self.events) + 1, "kind": kind,
                            "round": self.round, "attempt": self.attempt, **deepcopy(data)})

    def _round_event(self):
        self._emit("ROUND", leader=self.leader, team_size=self.team_size,
                   successes=self.successes, failures=self.failures)

    def _require(self, phase):
        if self.phase != phase:
            raise ValueError(f"This action requires phase {phase}.")

    def _rotate(self):
        self.leader_index = (self.leader_index + 1) % len(self.ids)

    def propose(self, actor, team):
        self._require("team")
        if actor != self.leader:
            raise ValueError("Only the current leader can choose a team.")
        if (not isinstance(team, list) or len(team) != self.team_size
                or any(not isinstance(p, str) or p not in self.players for p in team)
                or len(set(team)) != len(team)):
            raise ValueError(f"Choose {self.team_size} distinct valid players.")
        self.team = list(team)
        self.spoken.clear()
        self.phase = "discussion"
        self._emit("TEAM", actor=actor, team=team, speaking_order=self.speaking_order)

    def social(self, actor, action):
        self._require("discussion")
        if actor not in self.players or actor in self.spoken:
            raise ValueError("Each player may play one social card per proposal.")
        if actor != self.speaking_order[len(self.spoken)]:
            raise ValueError("Wait for this player's speaking turn.")
        validate_social(action, self.ids, self.events)
        self.spoken.add(actor)
        self._emit("SOCIAL", actor=actor, **action)

    def vote(self, votes, reasons=None):
        self._require("discussion")
        if self.spoken != set(self.ids):
            raise ValueError("Every player must play a social card before voting.")
        if set(votes) != set(self.ids) or any(type(v) is not bool for v in votes.values()):
            raise ValueError("Every player must submit one boolean vote.")
        reasons = reasons or {p: "team_risk" for p in self.ids}
        if set(reasons) != set(self.ids) or any(r not in REASONS for r in reasons.values()):
            raise ValueError("Invalid vote reason codes.")
        # All ballots are received before any are made public.
        approved = sum(votes.values()) > len(self.ids) / 2
        for pid in self.ids:
            self._emit("VOTE", actor=pid, approve=votes[pid], reason=reasons[pid])
        self._emit("TEAM_VOTE", team=self.team, votes=votes, approved=approved)
        if approved:
            self.phase = "mission"
        elif self.attempt == 5:
            self._finish("EVIL", "five_rejections")
        else:
            self.attempt += 1
            self._rotate()
            self.phase = "team"

    def resolve_mission(self, cards):
        self._require("mission")
        if set(cards) != set(self.team):
            raise ValueError("Only the selected team must submit mission cards.")
        for pid, card in cards.items():
            if card not in ("SUCCESS", "FAIL"):
                raise ValueError("Mission card must be SUCCESS or FAIL.")
            if card == "FAIL" and self.players[pid].role not in EVIL_ROLES:
                raise ValueError("Good players must submit SUCCESS.")
        # Never log an individual ballot, including a good player's automatic card.
        for pid in self.team:
            self._emit("MISSION_SUBMIT", actor=pid)
        fail_count = sum(card == "FAIL" for card in cards.values())
        success = fail_count == 0
        self.successes += int(success)
        self.failures += int(not success)
        result = {"team": list(self.team), "success": success, "fail_count": fail_count,
                  "successes": self.successes, "failures": self.failures}
        self.missions.append({"round": self.round, **deepcopy(result)})
        self._emit("MISSION", **result)
        self._rotate()
        if self.failures == 3:
            self._finish("EVIL", "three_failed_missions")
        elif self.successes == 3:
            self.phase = "assassination"
            self._emit("ASSASSINATION_PHASE")
        else:
            self.round += 1
            self.attempt = 1
            self.team = []
            self.phase = "team"
            self._round_event()

    def assassinate(self, actor, target):
        self._require("assassination")
        if actor not in self.players or self.players[actor].role != "ASSASSIN":
            raise ValueError("Only the Assassin can assassinate.")
        if target not in self.players or self.players[target].role in EVIL_ROLES:
            raise ValueError("The Assassin must choose a good player.")
        self._emit("ASSASSINATE", actor=actor, target=target)
        hit = self.players[target].role == "MERLIN"
        self._finish("EVIL" if hit else "GOOD", "merlin_assassinated" if hit else "merlin_survived")

    def _finish(self, winner, reason):
        self.winner = winner
        self.phase = "ended"
        self._emit("RESULT", winner=winner, reason=reason)
        self._emit("REVEAL", roles={p.id: p.role for p in self.players.values()})

    def view(self, pid):
        """A fresh, bounded view: only this seat's role-authorized information."""
        player = self.players[pid]
        knows_evil = player.role == "MERLIN" or player.role in EVIL_ROLES
        return deepcopy({
            "self": pid, "role": player.role,
            "known_evil": [p.id for p in self.players.values() if p.role in EVIL_ROLES]
            if knows_evil else [],
            "players": self.public_players(), "round": self.round, "attempt": self.attempt,
            "leader": self.leader, "team_size": self.team_size, "team": self.team,
            "speaking_direction": self.direction, "speaking_order": self.speaking_order,
            "phase": self.phase, "successes": self.successes, "failures": self.failures,
            "missions": self.missions, "recent_events": self.events[-20:],
        })
