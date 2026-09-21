"""Deterministic rules and public events. This module never calls an LLM."""

from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
import random

from .chronicle import (Chronicle, ChronicleReader, EVIDENCE_KINDS, PUBLIC_KINDS,
                        context_record, involves, record_id)


CARDS = ("ACCUSE", "DEFEND", "HEDGE", "PRESSURE", "BAIT")
MAX_RESOLVE = 3
RESOLVE_COSTS = {
    "PASS": 0, "SOCIAL": 1, "COMMITTED_SOCIAL": 2, "CHALLENGE": 1,
    "RESPOND": 1, "DECLINE": 0, "CITE": 1, "HOLD": 1, "REACT": 0,
    "SKIP": 0, "LOCK": 0, "REVISE": 1, "VOTE": 0, "STRONG_VOTE": 1,
}
SOCIAL_EVENTS = {"SOCIAL", "REACT", "CHALLENGE_RESPONSE"}
DISCUSSION_ACTIONS = ("PASS", "SOCIAL", "COMMITTED_SOCIAL", "CHALLENGE", "CITE", "HOLD")
EXILE_CHOICES = ("APPROVE", "REJECT", "ABSTAIN")
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


def mission_rules(player_count, mission_round):
    """The same public rules drive resolution and epistemic constraints."""
    if player_count not in TEAM_SIZES or not 1 <= mission_round <= 5:
        raise ValueError("Unsupported mission rules")
    return {"fail_threshold": 1, "good_may_fail": False, "evil_may_succeed": True}


def filter_worlds_by_mission_result(worlds, mission_team, fail_count, rules, *, success=None):
    """An aggregate count constrains card capacity, never identifies the saboteur.

    When evil may pass, f FAIL cards imply AT LEAST f evil members. The threshold
    decides the mission outcome, not the exact number of evil players aboard.
    """
    constraints = mission_result_constraints(mission_team, fail_count, rules, success=success)
    return [deepcopy(w) for w in worlds if constraints["min_evil"] <=
            len(set(w["evil_team"]) & set(mission_team)) <= constraints["max_evil"]]


def mission_result_constraints(mission_team, fail_count, rules, *, success=None):
    """Public mechanical bounds shared by alignment and full-role consumers."""
    if (not isinstance(mission_team, list) or any(not isinstance(p, str) for p in mission_team)
            or type(fail_count) is not int or not 0 <= fail_count <= len(mission_team)
            or len(set(mission_team)) != len(mission_team)
            or type(rules.get("fail_threshold")) is not int or rules["fail_threshold"] < 1
            or any(type(rules.get(k)) is not bool for k in ("good_may_fail", "evil_may_succeed"))
            or success is not None and (type(success) is not bool
                or success != (fail_count < rules["fail_threshold"]))):
        raise ValueError("Inconsistent public mission result")
    return {"min_evil": 0 if rules["good_may_fail"] else fail_count,
            "max_evil": len(mission_team) if rules["evil_may_succeed"] else fail_count,
            "fail_threshold": rules["fail_threshold"]}


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
    if not (type(seq) is int and seq > 0 or isinstance(seq, str)):
        raise ValueError("Invalid public evidence references")
    event = (events.get_record(seq) if isinstance(events, ChronicleReader) else
             next((e for e in events if (e["seq"] == seq or isinstance(seq, str) and "round" in e and record_id(e) == seq)
                   and e["kind"] in EVIDENCE_KINDS), None))
    if event is None:
        raise ValueError("Evidence must refer to existing public actions")
    if target is not None and not involves(event, target):
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
    written = basic | {"public_writing", "citations"}
    if (not isinstance(action, dict) or set(action) not in (basic, extended, written)
            or require_statement and set(action) == basic
            or not isinstance(action["card"], str) or action["card"] not in CARDS
            or not isinstance(action["target"], str) or action["target"] not in ids
            or not isinstance(action["reason"], str) or action["reason"] not in REASONS):
        raise ValueError("Invalid social action")
    if set(action) == basic:
        return
    modern = set(action) == written
    for key in (("public_writing",) if modern else ("statement", "rationale")):
        value = action[key]
        if not isinstance(value, str) or not value.strip() or len(value) > 240 or not value.isprintable():
            raise ValueError("Public statements must be short printable text")
    refs = action["citations"] if modern else action["evidence"]
    if (not isinstance(refs, list) or len(refs) > 3
            or any(not isinstance(n, str) if modern else type(n) is not int or n < 1 for n in refs)
            or len(set(refs)) != len(refs)):
        raise ValueError("Invalid public evidence references")
    if events is not None:
        public = {ref: public_evidence(events, ref) for ref in refs}
        needed = {"mission_record": {"MISSION"}, "vote_pattern": {"VOTE", "TEAM_VOTE", "STRONG_VOTE", "EXILE_VOTE", "EXILE_RESULT"}}.get(action["reason"])
        if needed and not any(public[n]["kind"] in needed for n in refs):
            raise ValueError("The reason must cite matching public history")


def public_social_text(action):
    return [action[key] for key in ("public_writing", "statement", "rationale")
            if isinstance(action, dict) and key in action]


def make_players(count=5, seed=None, human_name="YOU"):
    if count not in TEAM_SIZES:
        raise ValueError("Only 5 or 6 players are supported.")
    roles = ["MERLIN", "ASSASSIN", "EVIL"] + ["GOOD"] * (count - 3)
    random.Random(seed).shuffle(roles)
    names = [human_name, "NOVA", "ATLAS", "ECHO", "SAGE", "LYRA"]
    return [Player(f"P{i+1}", names[i], role) for i, role in enumerate(roles)]


class Game:
    def __init__(self, players, seed=None, direction=None, *, chronicle_path=None):
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
        self.safe_round = False
        self.discussion_stage = "proposal"
        self.exile_nominee = None
        self.team = []
        self.spoken = set()
        self.resolve = dict.fromkeys(self.ids, MAX_RESOLVE)
        self.pending_reactions = set()
        self.reaction_queue = []
        self.reaction_trigger = None
        self.challenge_window = None
        self.focused_evidence = []
        self.winner = None
        self.chronicle = Chronicle(chronicle_path)
        if len(self.chronicle):
            raise ValueError("A new game requires an empty Chronicle")
        self.lives = {pid: {"life": 1, "alive": True} for pid in self.ids}
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

    @property
    def events(self):
        """Compatibility snapshot. Mutating a returned event cannot change history."""
        return self.chronicle.records

    def _emit(self, kind, **data):
        if kind in SOCIAL_EVENTS and "card" in data:
            refs = data.get("citations", data.get("evidence", []))
            records = [self.chronicle.reader().get_record(ref) for ref in refs]
            data = {**data, "citations": [e["record_id"] for e in records],
                    "evidence": [e["seq"] for e in records]}
            writing = data.get("public_writing", data.get("statement"))
            if writing is not None:
                data.update(public_writing=writing, statement=writing)
        elif kind in {"CITE", "CHALLENGE"}:
            data["citations"] = [self.chronicle.reader().get_record(data["evidence"])["record_id"]]
        return self.chronicle.append_record({"seq": len(self.chronicle) + 1, "kind": kind,
                                            "round": self.round, "attempt": self.attempt, **deepcopy(data)})

    def _round_event(self):
        self._emit("ROUND", leader=self.leader, team_size=self.team_size,
                   successes=self.successes, failures=self.failures, safe_round=self.safe_round)

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
        if self.phase in {"discussion", "council_discussion"}:
            return self.speaking_order[len(self.spoken)]
        if self.phase == "challenge":
            return self.challenge_window.target
        if self.phase == "reaction":
            return self.reaction_queue[0]
        if self.phase in {"team", "revision", "exile_nomination"}:
            return self.leader
        return None

    def legal_actions(self, actor):
        if self.phase == "vote":
            kinds = ("VOTE", "STRONG_VOTE")
        elif actor != self.next_actor:
            return []
        else:
            kinds = {"discussion": DISCUSSION_ACTIONS, "council_discussion": DISCUSSION_ACTIONS,
                     "challenge": ("DECLINE", "RESPOND"),
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
        self.discussion_stage = "proposal"
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
        reader = self.chronicle.reader()
        cost = validate_action(action, self.ids, reader)
        action = deepcopy(action)
        kind = action["kind"]
        if kind in {"CITE", "CHALLENGE"}:
            action["evidence"] = public_evidence(reader, action["evidence"])["seq"]
        if kind not in self.legal_actions(actor):
            raise ValueError("Action is not legal for this turn or Resolve balance")
        if kind == "CHALLENGE" and action["target"] == actor:
            raise ValueError("A challenge must target another player")
        if kind == "REVISE" and (action["removed"] not in self.team or action["added"] in self.team):
            raise ValueError("Revision must replace exactly one team member")
        payment = self._spend_resolve(actor, cost)
        if self.phase in {"discussion", "council_discussion"}:
            self.spoken.add(actor)
            if kind in {"SOCIAL", "COMMITTED_SOCIAL"}:
                self._emit("SOCIAL", actor=actor, committed=kind == "COMMITTED_SOCIAL",
                           discussion_stage=self.discussion_stage, **action["social"], **payment)
            else:
                self._emit(kind, actor=actor, discussion_stage=self.discussion_stage,
                           **{k: v for k, v in action.items() if k != "kind"}, **payment)
            trigger = len(self.chronicle)
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
                       declined=kind == "DECLINE", discussion_stage=self.discussion_stage,
                       **action.get("social", {}), **payment)
            self.challenge_window = None
            self._continue_discussion()
        elif self.phase == "reaction":
            self.reaction_queue.pop(0)
            if kind == "REACT":
                self.pending_reactions.remove(actor)
            self._emit("REACT" if kind == "REACT" else "REACTION_SKIP", actor=actor,
                       trigger=self.reaction_trigger, discussion_stage=self.discussion_stage,
                       **action.get("social", {}), **payment)
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
            self.phase = "council_discussion" if self.discussion_stage == "council" else "discussion"
        else:
            self._emit("DISCUSSION_END", discussion_stage=self.discussion_stage,
                       expired_reactions=[p for p in self.speaking_order if p in self.pending_reactions])
            self.pending_reactions.clear()
            self.reaction_trigger = None
            self.phase = "exile_nomination" if self.discussion_stage == "council" else "revision"

    def validate_ballot(self, actor, approve, strong=False):
        """Validate one sealed ballot without spending or publishing it."""
        self._require("vote")
        if actor not in self.players or type(approve) is not bool or type(strong) is not bool:
            raise ValueError("A ballot needs a valid player and boolean choices")
        if not self._can_spend(actor, RESOLVE_COSTS["STRONG_VOTE" if strong else "VOTE"]):
            raise ValueError("Insufficient Resolve for Strong Vote")

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
        for pid in self.ids:
            self.validate_ballot(pid, votes[pid], strong[pid])
        # All ballots are received before any are made public.
        approved = sum(votes.values()) > len(self.ids) / 2
        for pid in self.ids:
            self._emit("VOTE", actor=pid, team=self.team, approve=votes[pid], reason=reasons[pid], strong=strong[pid],
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

    def legal_mission_cards(self, actor):
        if self.phase != "mission" or actor not in self.team:
            return []
        return ["SUCCESS", "FAIL"] if self.players[actor].role in EVIL_ROLES else ["SUCCESS"]

    def validate_mission_card(self, actor, card):
        self._require("mission")
        if card not in self.legal_mission_cards(actor):
            raise ValueError("Mission card is not permitted for this player")

    def resolve_mission(self, cards):
        self._require("mission")
        if set(cards) != set(self.team):
            raise ValueError("Only the selected team must submit mission cards.")
        for pid, card in cards.items():
            self.validate_mission_card(pid, card)
        # Never log an individual ballot, including a good player's automatic card.
        for pid in self.team:
            self._emit("MISSION_SUBMIT", actor=pid)
        fail_count = sum(card == "FAIL" for card in cards.values())
        rules = mission_rules(len(self.ids), self.round)
        success = fail_count < rules["fail_threshold"]
        self.successes += int(success)
        self.failures += int(not success)
        result = {"team": list(self.team), "success": success, "fail_count": fail_count,
                  "successes": self.successes, "failures": self.failures, "safe_round": self.safe_round,
                  "fail_threshold": rules["fail_threshold"]}
        mission = self._emit("MISSION", **result)
        self.missions.append({"round": self.round, "attempt": self.attempt,
                              "record_id": mission["record_id"], **deepcopy(result)})
        if not success and not self.safe_round:
            nomination = next(e for e in reversed(self.events) if e["kind"] in {"TEAM", "TEAM_REVISE"})
            for pid in self.team:
                self._die(pid, cause="failed_expedition", origin=mission,
                          related=[nomination["record_id"]], nominated_by=nomination["actor"])
        # The council belongs to this mission, before leader rotation or victory.
        # Every seat retains council rights, including characters awaiting rebirth.
        self.spoken.clear()
        self.pending_reactions.clear()
        self.reaction_queue.clear()
        self.reaction_trigger = None
        self.challenge_window = None
        self.focused_evidence = [mission["seq"]]
        self.discussion_stage = "council"
        self.exile_nominee = None
        self.phase = "council_discussion"
        self._emit("COUNCIL_START", leader=self.leader, speaking_order=self.speaking_order,
                   required_approvals=len(self.ids) // 2 + 1, mission_record=mission["record_id"])

    def exile_candidates(self):
        return [pid for pid in self.ids if self.lives[pid]["alive"]]

    def nominate_exile(self, actor, target):
        self._require("exile_nomination")
        if actor != self.leader or not isinstance(target, str) or target not in self.exile_candidates():
            raise ValueError("The mission leader must nominate one living character")
        self.exile_nominee = target
        nomination = self._emit("EXILE_NOMINATION", actor=actor, target=target)
        self.focused_evidence.append(nomination["seq"])
        self.phase = "exile_vote"

    def validate_exile_ballot(self, actor, choice):
        self._require("exile_vote")
        if (not isinstance(actor, str) or actor not in self.players
                or not isinstance(choice, str) or choice not in EXILE_CHOICES):
            raise ValueError("An exile ballot must be APPROVE, REJECT or ABSTAIN")

    def vote_exile(self, votes):
        self._require("exile_vote")
        if not isinstance(votes, dict) or set(votes) != set(self.ids):
            raise ValueError("Every player must submit one exile ballot")
        for pid, choice in votes.items():
            self.validate_exile_ballot(pid, choice)
        counts = {choice: sum(v == choice for v in votes.values()) for choice in EXILE_CHOICES}
        required = len(self.ids) // 2 + 1
        passed = counts["APPROVE"] >= required
        for pid in self.ids:
            self._emit("EXILE_VOTE", actor=pid, target=self.exile_nominee, choice=votes[pid])
        result = self._emit("EXILE_RESULT", target=self.exile_nominee, votes=votes,
                            counts=counts, exiled=passed, required_approvals=required)
        if passed:
            nomination = next(e for e in reversed(self.events) if e["kind"] == "EXILE_NOMINATION")
            self._die(self.exile_nominee, cause="exile", origin=result,
                      related=[nomination["record_id"]], nominated_by=nomination["actor"])
        self.phase = "council_result"

    def finish_council(self):
        """Leave the visible exile result before advancing/rebirthing or ending play."""
        self._require("council_result")
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
            self.safe_round = True
            self.discussion_stage = "proposal"
            self.exile_nominee = None
            self.spoken.clear()
            self.focused_evidence.clear()
            self.phase = "team"
            self._round_event()
            self._rebirth()
            self._refresh_resolve()

    def _die(self, target, *, cause, origin, related=(), nominated_by=None, actor=None):
        if not self.lives[target]["alive"]:
            raise ValueError("Character is already awaiting rebirth")
        self.lives[target]["alive"] = False
        self._emit("DEATH", target=target, cause=cause, origin_record=origin["record_id"],
                   related_records=[origin["record_id"], *related], life=self.lives[target]["life"],
                   **({"actor": actor} if actor else {}),
                   **({"nominated_by": nominated_by} if nominated_by else {}))

    def _rebirth(self):
        for pid, life in self.lives.items():
            if not life["alive"]:
                death = next(e for e in reversed(self.events) if e["kind"] == "DEATH" and e["target"] == pid)
                life.update(alive=True, life=life["life"] + 1)
                self._emit("REBIRTH", target=pid, life=life["life"], origin_record=death["record_id"])

    def assassination_targets(self, actor):
        if (self.phase != "assassination" or actor not in self.players
                or self.players[actor].role != "ASSASSIN"):
            return []
        return [pid for pid in self.ids if self.players[pid].role not in EVIL_ROLES]

    def assassinate(self, actor, target):
        self._require("assassination")
        if actor not in self.players or self.players[actor].role != "ASSASSIN":
            raise ValueError("Only the Assassin can assassinate.")
        if target not in self.assassination_targets(actor):
            raise ValueError("The Assassin must choose a good player.")
        event = self._emit("ASSASSINATE", actor=actor, target=target)
        # The final role check still applies to exiled characters; do not die twice.
        if self.lives[target]["alive"]:
            self._die(target, cause="assassination", origin=event, actor=actor)
        hit = self.players[target].role == "MERLIN"
        self._finish("EVIL" if hit else "GOOD", "merlin_assassinated" if hit else "merlin_survived")

    def _finish(self, winner, reason):
        self.winner = winner
        self.phase = "ended"
        self._emit("RESULT", winner=winner, reason=reason)
        self._emit("REVEAL", roles={p.id: p.role for p in self.players.values()})

    def view(self, pid):
        return build_agent_view(pid, self)

    def _agent_view(self, pid):
        """A fresh, bounded view: only this seat's role-authorized information."""
        player = self.players[pid]
        knows_evil = player.role == "MERLIN" or player.role in EVIL_ROLES
        focused = set(self.focused_evidence)
        if self.challenge_window:
            focused.add(self.challenge_window.evidence)
        if self.reaction_trigger:
            focused.add(self.reaction_trigger)
        public = [context_record(e) for e in self.events if e["kind"] in PUBLIC_KINDS]
        rules = {**mission_rules(len(self.ids), self.round), "evil_count": 2,
                 "team_sizes": list(TEAM_SIZES[len(self.ids)]), "max_proposals": 5,
                 # Sorted composition is public. Role-table insertion order is not.
                 "role_counts": dict(sorted(Counter(p.role for p in self.players.values()).items())),
                 "role_alignments": {r: "EVIL" if r in EVIL_ROLES else "GOOD"
                                     for r in sorted({p.role for p in self.players.values()})}}
        knowledge = {"self_role": player.role, "self_alignment": "EVIL" if player.role in EVIL_ROLES else "GOOD",
                     "known_evil_players": [p.id for p in self.players.values() if p.role in EVIL_ROLES] if knows_evil else [],
                     "known_good_players": [p.id for p in self.players.values() if p.role not in EVIL_ROLES]
                     if knows_evil else [pid], "known_special_roles": []}
        objective = {"mission_round": self.round, "proposal_number": self.attempt,
                     "leader": self.leader, "proposed_team": list(self.team), "team_size": self.team_size,
                     "phase": self.phase, "mission_score": {"good": self.successes, "evil": self.failures},
                     "rules": rules, "resolve": self.resolve, "lives": self.lives,
                     "safe_round": self.safe_round, "discussion_stage": self.discussion_stage,
                     "exile_nominee": self.exile_nominee,
                     "public_votes": [e for e in public if e["kind"] in {"TEAM_VOTE", "EXILE_RESULT"}],
                     "mission_results": self.missions,
                     "public_actions": [e for e in public if e["kind"] in EVIDENCE_KINDS][-8:],
                     "public_commitments": [e for e in public if e.get("committed") or e.get("strong")]}
        options = [{"kind": kind, "cost": RESOLVE_COSTS[kind]} for kind in self.legal_actions(pid)]
        for option in options:
            if option["kind"] == "CHALLENGE":
                option["targets"] = [p for p in self.ids if p != pid and
                                     any(involves(e, p) for e in public if e["kind"] in EVIDENCE_KINDS)]
                option["requires_target_evidence"] = True
            elif option["kind"] == "CITE":
                option["requires_public_evidence"] = True
            elif option["kind"] == "REVISE":
                option["remove_from"] = list(self.team)
                option["add_from"] = [p for p in self.ids if p not in self.team]
            elif option["kind"] in {"VOTE", "STRONG_VOTE"}:
                option["choices"] = [True, False]
        options = [o for o in options if o["kind"] != "CHALLENGE" or o["targets"]]
        if self.phase == "team" and pid == self.leader:
            options = [{"kind": "PROPOSE", "team_size": self.team_size, "candidates": self.ids}]
        elif self.phase == "mission" and pid in self.team:
            options = [{"kind": "MISSION", "cards": self.legal_mission_cards(pid)}]
        elif self.phase == "assassination" and player.role == "ASSASSIN":
            options = [{"kind": "ASSASSINATE", "targets": self.assassination_targets(pid)}]
        elif self.phase == "exile_nomination" and pid == self.leader:
            options = [{"kind": "NOMINATE_EXILE", "targets": self.exile_candidates()}]
        elif self.phase == "exile_vote":
            options = [{"kind": "EXILE_VOTE", "choices": list(EXILE_CHOICES)}]
        return deepcopy({
            "self": pid, "role": player.role,
            "known_evil": [p.id for p in self.players.values() if p.role in EVIL_ROLES]
            if knows_evil else [],
            "players": self.public_players(), "round": self.round, "attempt": self.attempt,
            "leader": self.leader, "team_size": self.team_size, "team": self.team,
            "speaking_direction": self.direction, "speaking_order": self.speaking_order,
            "phase": self.phase, "successes": self.successes, "failures": self.failures,
            "safe_round": self.safe_round, "discussion_stage": self.discussion_stage,
            "exile_nominee": self.exile_nominee, "exile_candidates": self.exile_candidates(),
            "exile_choices": list(EXILE_CHOICES), "required_approvals": len(self.ids) // 2 + 1,
            "missions": self.missions[-5:], "recent_events": public[-20:],
            "rules": rules, "private_knowledge": knowledge, "objective_state": objective,
            "legal_options": options,
            "lives": self.lives,
            "resolve": self.resolve, "max_resolve": MAX_RESOLVE, "resolve_costs": RESOLVE_COSTS,
            "next_actor": self.next_actor, "legal_actions": self.legal_actions(pid),
            "pending_reactions": [p for p in self.speaking_order if p in self.pending_reactions],
            "reaction_queue": self.reaction_queue, "reaction_trigger": self.reaction_trigger,
            "challenge": vars(self.challenge_window) if self.challenge_window else None,
            "discussion_status": {p: "completed" if p in self.spoken else "waiting" for p in self.ids},
            "focused_events": [context_record(self.chronicle.get_record(seq)) for seq in sorted(focused)[-5:]
                               if self.chronicle.get_record(seq)["kind"] in PUBLIC_KINDS],
        })


def build_agent_view(agent_id, game_state):
    """The single host boundary. Never serialize Game, roles, cards, or debug state."""
    return game_state._agent_view(agent_id)
