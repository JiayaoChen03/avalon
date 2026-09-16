"""Deterministic rules and public events. This module never calls an LLM."""

from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
import random


CARDS = ("ACCUSE", "DEFEND", "HEDGE", "PRESSURE", "BAIT")
MAX_RESOLVE = 3
RESOLVE_COSTS = {
    "PASS": 0, "SOCIAL": 1, "COMMITTED_SOCIAL": 2, "CHALLENGE": 1,
    "RESPOND": 1, "DECLINE": 0, "CITE": 1, "HOLD": 1, "REACT": 0,
    "SKIP": 0, "LOCK": 0, "REVISE": 1, "VOTE": 0, "STRONG_VOTE": 1,
}
SOCIAL_EVENTS = {"SOCIAL", "REACT", "CHALLENGE_RESPONSE"}
EVIDENCE_KINDS = {"TEAM", "SOCIAL", "PASS", "VOTE", "TEAM_VOTE", "MISSION",
                  "STRONG_VOTE", "CHALLENGE", "CHALLENGE_RESPONSE", "CITE",
                  "HOLD", "REACT", "TEAM_REVISE"}
DISCUSSION_ACTIONS = ("PASS", "SOCIAL", "COMMITTED_SOCIAL", "CHALLENGE", "CITE", "HOLD")
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


@dataclass(frozen=True)
class ChallengeWindow:
    actor: str
    target: str
    evidence: int
    seq: int


def public_evidence(events, seq, target=None):
    """Only actual public actions qualify; receipts and role reveals never do."""
    if type(seq) is not int or seq < 1:
        raise ValueError("Invalid public evidence references")
    event = next((e for e in events if e["seq"] == seq and e["kind"] in EVIDENCE_KINDS), None)
    if event is None:
        raise ValueError("Evidence must refer to existing public actions")
    if target is not None and not (target in (event.get("actor"), event.get("target"),
                                              event.get("removed"), event.get("added"))
                                   or target in event.get("team", []) or target in event.get("votes", {})):
        raise ValueError("Challenge evidence must involve its target")
    return event


def validate_action(action, ids, events, *, require_statement=False):
    """Shared action grammar; Game separately enforces turn permission and payment."""
    if not isinstance(action, dict) or not isinstance(action.get("kind"), str):
        raise ValueError("Invalid resource action")
    kind = action["kind"]
    fields = {"SOCIAL": {"social"}, "COMMITTED_SOCIAL": {"social"},
              "RESPOND": {"social"}, "REACT": {"social"},
              "CHALLENGE": {"target", "evidence"}, "CITE": {"evidence"},
              "REVISE": {"removed", "added"}}
    if kind not in RESOLVE_COSTS or kind in {"VOTE", "STRONG_VOTE"} or set(action) != {"kind"} | fields.get(kind, set()):
        raise ValueError("Invalid resource action")
    if "social" in action:
        validate_social(action["social"], ids, events, require_statement=require_statement)
    for field in ("target", "removed", "added"):
        if field in action and (not isinstance(action[field], str) or action[field] not in ids):
            raise ValueError("Invalid resource target")
    if kind in {"CITE", "CHALLENGE"}:
        public_evidence(events, action["evidence"], action.get("target"))
    return RESOLVE_COSTS[kind]


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
        public = {e["seq"]: e for e in events if e["kind"] in EVIDENCE_KINDS}
        if not set(refs) <= public.keys():
            raise ValueError("Evidence must refer to existing public actions")
        needed = {"mission_record": {"MISSION"}, "vote_pattern": {"VOTE", "TEAM_VOTE", "STRONG_VOTE"}}.get(action["reason"])
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
        self.resolve = dict.fromkeys(self.ids, MAX_RESOLVE)
        self.pending_reactions = set()
        self.reaction_queue = []
        self.reaction_trigger = None
        self.challenge_window = None
        self.focused_evidence = []
        self.winner = None
        self.events = []
        self.missions = []
        self._emit("START", players=self.public_players())
        self._emit("LEADER", actor=self.leader, reason="random_draw")
        self._emit("DIRECTION", direction=self.direction, order=self.speaking_order)
        self._round_event()
        self._refresh_resolve()

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

    def _can_spend(self, actor, amount):
        if not isinstance(actor, str) or actor not in self.players:
            raise ValueError("Invalid Resolve owner")
        if type(amount) is not int or amount < 0:
            raise ValueError("Resolve costs must be nonnegative integers")
        if type(self.resolve[actor]) is not int or not 0 <= self.resolve[actor] <= MAX_RESOLVE:
            raise ValueError("Invalid Resolve balance")
        return self.resolve[actor] >= amount

    def _spend_resolve(self, actor, amount):
        if not self._can_spend(actor, amount):
            raise ValueError("Insufficient Resolve")
        self.resolve[actor] -= amount
        return {"resolve_cost": amount, "resolve_after": self.resolve[actor]}

    def _refresh_resolve(self):
        self.resolve = dict.fromkeys(self.ids, MAX_RESOLVE)
        self._emit("RESOLVE_REFRESH", resolve=self.resolve, max_resolve=MAX_RESOLVE)

    @property
    def next_actor(self):
        if self.phase == "discussion":
            return self.speaking_order[len(self.spoken)]
        if self.phase == "challenge":
            return self.challenge_window.target
        if self.phase == "reaction":
            return self.reaction_queue[0]
        if self.phase in {"team", "revision"}:
            return self.leader
        return None

    def legal_actions(self, actor):
        if self.phase == "vote":
            kinds = ("VOTE", "STRONG_VOTE")
        elif actor != self.next_actor:
            return []
        else:
            kinds = {"discussion": DISCUSSION_ACTIONS, "challenge": ("DECLINE", "RESPOND"),
                     "reaction": ("SKIP", "REACT"), "revision": ("LOCK", "REVISE")}.get(self.phase, ())
        return [kind for kind in kinds if self._can_spend(actor, RESOLVE_COSTS[kind])]

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
        self.pending_reactions.clear()
        self.reaction_queue.clear()
        self.reaction_trigger = None
        self.challenge_window = None
        self.focused_evidence.clear()
        self.phase = "discussion"
        self._emit("TEAM", actor=actor, team=team, speaking_order=self.speaking_order)

    def social(self, actor, action, *, committed=False):
        if type(committed) is not bool:
            raise ValueError("Commitment must be boolean")
        self.act(actor, {"kind": "COMMITTED_SOCIAL" if committed else "SOCIAL", "social": action})

    def act(self, actor, action):
        """One atomic public action. No controller can bypass the proposal lifecycle."""
        cost = validate_action(action, self.ids, self.events)
        kind = action["kind"]
        if kind not in self.legal_actions(actor):
            raise ValueError("Action is not legal for this turn or Resolve balance")
        if kind == "CHALLENGE" and action["target"] == actor:
            raise ValueError("A challenge must target another player")
        if kind == "REVISE" and (action["removed"] not in self.team or action["added"] in self.team):
            raise ValueError("Revision must replace exactly one team member")
        payment = self._spend_resolve(actor, cost)
        if self.phase == "discussion":
            self.spoken.add(actor)
            if kind in {"SOCIAL", "COMMITTED_SOCIAL"}:
                self._emit("SOCIAL", actor=actor, committed=kind == "COMMITTED_SOCIAL",
                           **action["social"], **payment)
            else:
                self._emit(kind, actor=actor, **{k: v for k, v in action.items() if k != "kind"}, **payment)
            trigger = self.events[-1]["seq"]
            if kind == "HOLD":
                self.pending_reactions.add(actor)
            if kind == "CITE":
                self.focused_evidence.append(action["evidence"])
            # Only a normal turn opens windows. Responses/reactions never recurse.
            self.reaction_trigger = trigger
            self.reaction_queue = [p for p in self.speaking_order if p in self.pending_reactions and p != actor]
            if kind == "CHALLENGE":
                self.challenge_window = ChallengeWindow(actor, action["target"], action["evidence"], trigger)
                self.phase = "challenge"
            else:
                self._continue_discussion()
        elif self.phase == "challenge":
            window = self.challenge_window
            self._emit("CHALLENGE_RESPONSE", actor=actor, challenger=window.actor, challenge=window.seq,
                       declined=kind == "DECLINE", **action.get("social", {}), **payment)
            self.challenge_window = None
            self._continue_discussion()
        elif self.phase == "reaction":
            self.reaction_queue.pop(0)
            if kind == "REACT":
                self.pending_reactions.remove(actor)
            self._emit("REACT" if kind == "REACT" else "REACTION_SKIP", actor=actor,
                       trigger=self.reaction_trigger, **action.get("social", {}), **payment)
            self._continue_discussion()
        elif self.phase == "revision":
            if kind == "REVISE":
                self.team = [action["added"] if p == action["removed"] else p for p in self.team]
                self._emit("TEAM_REVISE", actor=actor, removed=action["removed"], added=action["added"],
                           team=self.team, **payment)
            else:
                self._emit("TEAM_LOCK", actor=actor, team=self.team, **payment)
            self.phase = "vote"

    def _continue_discussion(self):
        if self.reaction_queue:
            self.phase = "reaction"
        elif len(self.spoken) < len(self.ids):
            self.reaction_trigger = None
            self.phase = "discussion"
        else:
            self._emit("DISCUSSION_END", expired_reactions=[p for p in self.speaking_order if p in self.pending_reactions])
            self.pending_reactions.clear()
            self.reaction_trigger = None
            self.phase = "revision"

    def vote(self, votes, reasons=None, *, strong=None):
        self._require("vote")
        if not isinstance(votes, dict):
            raise ValueError("Every player must submit one boolean vote.")
        if set(votes) != set(self.ids) or any(type(v) is not bool for v in votes.values()):
            raise ValueError("Every player must submit one boolean vote.")
        reasons = {p: "team_risk" for p in self.ids} if reasons is None else reasons
        if (not isinstance(reasons, dict) or set(reasons) != set(self.ids)
                or any(not isinstance(r, str) or r not in REASONS for r in reasons.values())):
            raise ValueError("Invalid vote reason codes.")
        strong = dict.fromkeys(self.ids, False) if strong is None else strong
        if (not isinstance(strong, dict) or set(strong) != set(self.ids)
                or any(type(v) is not bool for v in strong.values())):
            raise ValueError("Every ballot needs a boolean strong modifier")
        costs = {p: RESOLVE_COSTS["STRONG_VOTE" if strong[p] else "VOTE"] for p in self.ids}
        if not all(self._can_spend(p, costs[p]) for p in self.ids):
            raise ValueError("Insufficient Resolve for Strong Vote")
        # All ballots are received before any are made public.
        approved = sum(votes.values()) > len(self.ids) / 2
        for pid in self.ids:
            self._emit("VOTE", actor=pid, approve=votes[pid], reason=reasons[pid], strong=strong[pid],
                       **self._spend_resolve(pid, costs[pid]))
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
            self._refresh_resolve()

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
        focused = set(self.focused_evidence)
        if self.challenge_window:
            focused.add(self.challenge_window.evidence)
        if self.reaction_trigger:
            focused.add(self.reaction_trigger)
        return deepcopy({
            "self": pid, "role": player.role,
            "known_evil": [p.id for p in self.players.values() if p.role in EVIL_ROLES]
            if knows_evil else [],
            "players": self.public_players(), "round": self.round, "attempt": self.attempt,
            "leader": self.leader, "team_size": self.team_size, "team": self.team,
            "speaking_direction": self.direction, "speaking_order": self.speaking_order,
            "phase": self.phase, "successes": self.successes, "failures": self.failures,
            "missions": self.missions, "recent_events": self.events[-20:],
            "resolve": self.resolve, "max_resolve": MAX_RESOLVE, "resolve_costs": RESOLVE_COSTS,
            "next_actor": self.next_actor, "legal_actions": self.legal_actions(pid),
            "pending_reactions": [p for p in self.speaking_order if p in self.pending_reactions],
            "reaction_queue": self.reaction_queue, "reaction_trigger": self.reaction_trigger,
            "challenge": vars(self.challenge_window) if self.challenge_window else None,
            "discussion_status": {p: "completed" if p in self.spoken else "waiting" for p in self.ids},
            "focused_events": [e for e in self.events if e["seq"] in focused],
        })
