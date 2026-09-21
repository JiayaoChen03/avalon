"""Private evil tactics and core policies; agents choose use of the public Resolve budget."""

from collections import Counter
from copy import deepcopy
from dataclasses import asdict, dataclass, replace
from itertools import combinations
import random

from .engine import EVIDENCE_KINDS, EVIL_ROLES, SOCIAL_EVENTS, TEAM_SIZES
from .evil_state import EvilSharedState, PublicEvidence, bounded


MODES = ("NORMAL_DECEPTION", "FAKE_CONFLICT", "CONSENSUS_SEEDING", "AGENDA_CAPTURE",
         "MERLIN_HUNT", "SACRIFICE", "CRISIS_RECOVERY")
PHASES = {"team", "discussion", "vote", "mission", "assassination",
          "council_discussion", "exile_nomination", "exile_vote"}


@dataclass(frozen=True)
class TacticalContext:
    strategy_mode: str
    role: str
    primary_objective: str
    secondary_objective: str | None
    primary_target: str
    evil_partner: str
    distance_strength: float
    active_narratives: list
    agenda_topic: str | None
    constraints: list
    relevant_public_events: list
    allowed_cards: list

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class StrategyDecision:
    round: int
    attempt: int
    phase: str
    agent_id: str
    strategy_mode: str
    primary_objective: str
    secondary_objective: str | None
    target: str
    confidence: float
    role: str
    action: dict


class EvilStrategyManager:
    def __init__(self, player_ids, evil_ids, *, seed=None, controlled_evil_ids=None):
        ids = list(player_ids)
        if (len(ids) not in TEAM_SIZES or any(not isinstance(p, str) or not p for p in ids)
                or len(set(ids)) != len(ids)):
            raise ValueError("Expected five or six distinct player IDs")
        evil = set(evil_ids)
        controlled = set(evil if controlled_evil_ids is None else controlled_evil_ids)
        if len(evil) != 2 or not evil <= set(ids) or not controlled <= evil:
            raise ValueError("Expected two evil IDs and a controlled subset")
        self.player_ids = tuple(ids)
        self.evil_ids, self.controlled_evil_ids = evil, controlled
        self.good_ids = tuple(p for p in ids if p not in evil)
        self._random = random.Random(seed)
        aggressor = self._random.choice(sorted(evil))
        roles = {p: "Aggressor" if p == aggressor else "Sleeper" for p in sorted(evil)}
        self._evidence = PublicEvidence(ids, evil, roles)
        self.state: EvilSharedState = self._evidence.state
        self.decisions: list[StrategyDecision] = []
        self._phases, self._contexts, self._teams, self._votes, self._missions = {}, {}, {}, {}, {}
        self._assassinations, self._recorded = {}, set()
        self._latest_view = None

    def observe(self, event):
        if self._evidence.observe(event):
            # Score refreshes are independent of frozen phase/turn commitments.
            view = self._latest_view or {"round": self._evidence.round,
                "attempt": self._evidence.attempt, "phase": "discussion",
                "successes": self._evidence.successes, "failures": self._evidence.failures}
            view = dict(view, successes=self._evidence.successes, failures=self._evidence.failures)
            self.state.mode_scores = self._scores(view)
            if (event["kind"] in SOCIAL_EVENTS | {"PASS", "HOLD", "CHALLENGE", "CITE", "TEAM_REVISE"}
                    and event.get("actor") in self.controlled_evil_ids):
                phase = "council_discussion" if event.get("discussion_stage") == "council" else "discussion"
                key = (event.get("round"), event.get("attempt"), phase, event["actor"])
                context = self._contexts.get(key)
                if context is not None:
                    refs = event.get("evidence", [])
                    refs = [seq for seq in refs if type(seq) is int and seq > 0][:3] if isinstance(refs, list) else []
                    fields = ("card", "target", "reason", "committed", "resolve_cost", "resolve_after",
                              "challenger", "challenge", "declined", "trigger", "removed", "added", "team")
                    action = {"kind": event["kind"].lower(), "seq": event["seq"],
                              **{k: deepcopy(event[k]) for k in fields if k in event}}
                    if "evidence" in event:
                        action["evidence"] = refs if isinstance(event["evidence"], list) else event["evidence"]
                    accepted = {"round": event["round"], "attempt": event["attempt"], "self": event["actor"]}
                    self._record(accepted, phase, context, action)

    def _validate_view(self, view):
        if not isinstance(view, dict) or view.get("self") not in self.evil_ids or view.get("role") not in EVIL_ROLES:
            raise ValueError("Only an authorized evil seat may use the strategy manager")
        players = view.get("players")
        if (not isinstance(players, list) or len(players) != len(self.player_ids)
                or any(not isinstance(p, dict) for p in players)
                or {p.get("id") for p in players} != set(self.player_ids)
                or set(view.get("known_evil", [])) != self.evil_ids):
            raise ValueError("View does not belong to this game")
        for key in ("round", "attempt"):
            if type(view.get(key)) is not int or not 1 <= view[key] <= 5:
                raise ValueError("Invalid proposal coordinates")
        size = view.get("team_size")
        if type(size) is not int or not 1 <= size <= len(self.player_ids):
            raise ValueError("Invalid team size")
        team = view.get("team", [])
        if (not isinstance(team, list) or any(p not in self.player_ids for p in team)
                or len(set(team)) != len(team)):
            raise ValueError("Invalid selected team")
        for score in ("successes", "failures"):
            if type(view.get(score)) is not int or not 0 <= view[score] <= 3:
                raise ValueError("Invalid mission score")

    def _distance(self, view):
        state = self.state
        suspicion = [state.public_suspicion[p] for p in self.evil_ids]
        trust = [state.public_trust[p] for p in self.evil_ids]
        return bounded(.10 + .12 * (view["round"] - 1) / 4 + .40 * state.pair_suspicion
                       + .18 * sum(suspicion) / 2 + .12 * max(suspicion)
                       + .14 * (1 - sum(trust) / 2)
                       + .10 * min(state.partner_agreement_streak / 4, 1)
                       + .08 * min(len(state.partner_defense_history) / 3, 1))

    def _sacrifice_candidate(self):
        state = self.state
        for target in sorted(self.evil_ids):
            partner = next(p for p in self.evil_ids if p != target)
            if (state.public_suspicion[target] >= .78 and state.public_suspicion[partner] <= .4
                    and state.public_trust[partner] >= .60
                    and state.public_suspicion[target] - state.public_suspicion[partner] >= .35):
                return target
        return None

    def _social_events(self, view):
        return [e for e in self._evidence.events if e["kind"] in SOCIAL_EVENTS and "card" in e
                and e.get("round") == view["round"] and e.get("attempt") == view["attempt"]]

    def _partner_seed(self, view, pid):
        # A public suspicion can persist across a proposal; no invented "seed"
        # is needed when the previous proposal already contains the argument.
        events = [e for e in self._evidence.events if e["kind"] in SOCIAL_EVENTS and "card" in e
                  and view["round"] - 1 <= e.get("round", 0) <= view["round"]][-12:]
        partner = next(p for p in self.evil_ids if p != pid)
        for index in range(len(events) - 1, -1, -1):
            event = events[index]
            if (event["actor"] == partner and event["target"] in self.good_ids
                    and event["card"] in {"ACCUSE", "PRESSURE", "BAIT"}):
                separated = any(e["actor"] not in self.evil_ids for e in events[index+1:])
                return event, separated
        return None, False

    def _scores(self, view, merlin_probabilities=None):
        state = self.state
        sus = [state.public_suspicion[p] for p in self.evil_ids]
        trust = [state.public_trust[p] for p in self.evil_ids]
        events = self._social_events(view)
        outside_pressure = [e for e in events if e["actor"] in self.good_ids
                            and e["target"] in self.evil_ids and e["card"] in {"ACCUSE", "PRESSURE", "BAIT"}]
        pressure = len({e["actor"] for e in outside_pressure}) / len(self.good_ids)
        seeds = [self._partner_seed(view, pid) for pid in sorted(self.evil_ids)]
        seeded = any(seed is not None for seed, _ in seeds)
        separated = any(seed is not None and gap for seed, gap in seeds)
        probabilities = merlin_probabilities if merlin_probabilities is not None else state.merlin_probabilities
        concentration = max(probabilities[p] for p in self.good_ids) - 1 / len(self.good_ids)
        sacrifice = self._sacrifice_candidate()
        scores = {
            "NORMAL_DECEPTION": .65 + .15 * sum(trust) / 2 - .15 * max(sus),
            "FAKE_CONFLICT": .10 + 1.65 * state.pair_suspicion
                + 1.2 * max(0, min(sus)-.4)
                + .12 * min(state.partner_agreement_streak, 4) + .08 * min(len(state.partner_defense_history), 3),
            "CONSENSUS_SEEDING": .10 + (.95 if separated else .38 if seeded else 0) + .15 * sum(trust) / 2,
            "AGENDA_CAPTURE": .12 + 1.30 * pressure + .20 * max(sus),
            "MERLIN_HUNT": .08 + 2.45 * max(0, concentration) + .18 * view["successes"],
            "SACRIFICE": 2.55 if sacrifice else .05,
            "CRISIS_RECOVERY": (.30 + 2.1 * min(sus) + .4 * (1-max(trust))) if min(sus) >= .65 else .08,
        }
        if view.get("phase") == "assassination":
            scores["MERLIN_HUNT"] += 4
        recent = Counter(item["strategy_mode"] for item in state.mode_history[-6:])
        return {mode: round(value - .055 * recent[mode], 6) for mode, value in scores.items()}

    def _phase(self, view, phase, merlin_probabilities=None):
        key = (view["round"], view["attempt"], phase)
        current = dict(view, phase=phase)
        self._latest_view = {k: current[k] for k in ("round", "attempt", "phase", "successes", "failures")}
        self.state.mode_scores = self._scores(current, merlin_probabilities)
        if key not in self._phases:
            state = self.state
            exposure = {p: state.public_suspicion[p] - state.public_trust[p] for p in self.evil_ids}
            high, low = sorted(self.evil_ids, key=lambda p: (exposure[p], p), reverse=True)
            if exposure[high] - exposure[low] >= .30:
                state.roles = {high: "Aggressor", low: "Sleeper"}
            noisy = {mode: score + self._random.uniform(-.025, .025) for mode, score in state.mode_scores.items()}
            mode = max(MODES, key=lambda name: noisy[name])
            sacrifice = self._sacrifice_candidate() if mode == "SACRIFICE" else None
            self._phases[key] = {"strategy_mode": mode, "roles": dict(state.roles),
                                 "sacrifice_target": sacrifice, "distance_strength": self._distance(view)}
            state.mode_history.append({"round": view["round"], "attempt": view["attempt"],
                                       "phase": phase, "strategy_mode": mode})
            state.mode_history = state.mode_history[-25:]
        selection = self._phases[key]
        self.state.strategy_mode = selection["strategy_mode"]
        self.state.roles = dict(selection["roles"])
        self.state.sacrifice_target = selection["sacrifice_target"]
        self.state.distance_strength = selection["distance_strength"]
        return selection

    def _target(self, *, exclude=(), merlin=False, merlin_probabilities=None):
        candidates = [p for p in self.good_ids if p not in exclude] or list(self.good_ids)
        state = self.state
        def score(pid):
            if merlin:
                probabilities = merlin_probabilities if merlin_probabilities is not None else state.merlin_probabilities
                return probabilities[pid] + self._random.uniform(0, .005)
            tags = set(state.public_tags[pid])
            return (.45 * state.public_suspicion[pid] + .25 * (1-state.public_trust[pid])
                    + .12 * ("emotional" in tags) + .10 * ("follows_consensus" in tags)
                    - .05 * ("independent" in tags) + self._random.uniform(-.015, .015))
        return max(candidates, key=score)

    def _merlin_projection(self, view, joint_beliefs):
        if joint_beliefs is None:
            return self.state.merlin_probabilities
        if (getattr(joint_beliefs, "observer_id", None) != view["self"]
                or set(joint_beliefs.player_ids) != set(self.player_ids)
                or joint_beliefs.P_role(view["self"], view["role"]) < 1 - 1e-12
                or any(joint_beliefs.P_alignment(p, "EVIL") < 1 - 1e-12 for p in self.evil_ids)):
            raise ValueError("Strategy requires this seat's legal joint beliefs")
        return {p: joint_beliefs.P_role(p, "MERLIN") for p in self.player_ids}

    def tactical_context(self, view, phase=None, *, joint_beliefs=None):
        self._validate_view(view)
        phase = phase or view["phase"]
        if phase not in PHASES:
            raise ValueError("Unknown strategy phase")
        probabilities = self._merlin_projection(view, joint_beliefs)
        selection = self._phase(view, phase, probabilities)
        pid = view["self"]
        key = (view["round"], view["attempt"], phase, pid)
        if key in self._contexts:
            if joint_beliefs is not None and self._contexts[key].primary_objective == "PROBE_MERLIN":
                # Refresh a target after semantic evidence without storing or
                # sharing the caller's private distribution in the manager.
                target = max(self.good_ids, key=lambda p: (probabilities[p], p))
                self._contexts[key] = replace(self._contexts[key], primary_target=target)
            return deepcopy(self._contexts[key])
        mode, role = selection["strategy_mode"], selection["roles"][pid]
        partner = next(p for p in self.evil_ids if p != pid)
        seed, separated = self._partner_seed(view, pid)
        adjacent_target = [seed["target"]] if seed is not None and not separated else []
        target = self._target(exclude=adjacent_target)
        objective, secondary, cards, topic = "SEED_NARRATIVE", None, ["BAIT", "HEDGE", "PRESSURE"], None
        if role == "Sleeper":
            objective, cards = "BUILD_TRUST", ["HEDGE", "DEFEND"]
        if mode == "NORMAL_DECEPTION":
            if role == "Aggressor" and self.state.public_suspicion[target] >= .60:
                objective, cards = "INCREASE_TARGET_SUSPICION", ["ACCUSE", "PRESSURE", "BAIT"]
            if self.state.public_suspicion[pid] >= .60:
                objective, secondary, cards = "REDUCE_SELF_SUSPICION", "CAUSE_UNCERTAINTY", ["HEDGE", "BAIT"]
            defenses = sum(e["actor"] == pid for e in self.state.partner_defense_history)
            recent = self._social_events(view)
            partner_pressed = (recent and recent[-1]["actor"] in self.good_ids
                               and recent[-1]["target"] == partner
                               and recent[-1]["card"] in {"ACCUSE", "PRESSURE"})
            if (role == "Sleeper" and partner_pressed and not defenses and self.state.pair_suspicion < .25
                    and self.state.public_suspicion[partner] < .62 and self.state.public_trust[partner] >= .45):
                objective, target, cards = "REDUCE_PARTNER_SUSPICION", partner, ["HEDGE", "DEFEND"]
            if seed is not None and not separated:
                objective, cards = "MAINTAIN_INDEPENDENCE", ["HEDGE", "BAIT"]
        elif mode == "FAKE_CONFLICT":
            if role == "Aggressor":
                objective, target, cards = "CREATE_DISTANCE_FROM_PARTNER", partner, ["PRESSURE", "ACCUSE"]
            else:
                objective, cards = "MAINTAIN_INDEPENDENCE", ["HEDGE", "BAIT", "PRESSURE"]
        elif mode == "SACRIFICE":
            if pid == selection["sacrifice_target"]:
                objective, secondary, cards = "SACRIFICE_SELF", "CAUSE_UNCERTAINTY", ["DEFEND", "HEDGE"]
            else:
                objective, target, cards = "SACRIFICE_PARTNER", selection["sacrifice_target"], ["ACCUSE", "PRESSURE"]
        elif mode == "CONSENSUS_SEEDING":
            if seed is not None and separated:
                objective, target, cards = "REINFORCE_NARRATIVE", seed["target"], ["PRESSURE", "BAIT"]
            elif seed is not None:
                objective, cards = "MAINTAIN_INDEPENDENCE", ["HEDGE", "BAIT"]
            else:
                objective, cards = "SEED_NARRATIVE", ["BAIT", "PRESSURE"]
        elif mode == "AGENDA_CAPTURE":
            objective, cards, topic = "CONTROL_AGENDA", ["BAIT", "PRESSURE"], "TEAM_SELECTION_CRITERIA"
            if self.state.mission_history:
                topic = "MISSION_ACCOUNTABILITY"
        elif mode == "MERLIN_HUNT":
            objective, target, cards = "PROBE_MERLIN", self._target(merlin=True, merlin_probabilities=probabilities), ["BAIT", "PRESSURE", "HEDGE"]
        elif mode == "CRISIS_RECOVERY":
            objective, secondary, cards = "REDUCE_SELF_SUSPICION", "CAUSE_UNCERTAINTY", ["HEDGE", "BAIT"]
            if role == "Aggressor":
                objective, cards, topic = "CONTROL_AGENDA", ["PRESSURE", "BAIT"], "VOTE_ACCOUNTABILITY"
        constraints = ["PUBLIC_EVIDENCE_ONLY", "NO_PRIVATE_DISCLOSURE", "NO_ROLE_CLAIM", "NO_INVENTED_FACTS"]
        defenses = sum(e["actor"] == pid for e in self.state.partner_defense_history)
        if defenses or self.state.pair_suspicion >= .35:
            constraints.append("NO_PARTNER_DEFENSE")
            if target == partner:
                cards = [card for card in cards if card != "DEFEND"]
        if seed is not None and not separated:
            constraints.append("NO_ADJACENT_PARTNER_REINFORCEMENT")
        context = TacticalContext(mode, role, objective, secondary, target, partner,
            selection["distance_strength"], deepcopy(self.state.active_narratives), topic,
            constraints, self._relevant_events(target), cards)
        self._contexts[key] = context
        self.state.primary_objectives[pid] = objective
        self.state.secondary_objectives[pid] = secondary
        self.state.targets[pid] = target
        self.state.primary_target = target
        if target in self.good_ids and objective in {"SACRIFICE_SELF", "SEED_NARRATIVE", "REINFORCE_NARRATIVE", "INCREASE_TARGET_SUSPICION"}:
            self.state.framed_players = list(dict.fromkeys(self.state.framed_players + [target]))
        self.state.agenda_topic = topic
        return deepcopy(context)

    def _relevant_events(self, target):
        refs = {seq for narrative in self.state.active_narratives for seq in narrative["evidence"]}
        candidates = [e for e in self._evidence.events if e["kind"] in EVIDENCE_KINDS]
        important = [e for e in candidates if e["seq"] in refs]
        related = [e for e in candidates if e not in important and
                   (e.get("target") == target or e.get("actor") == target or target in e.get("team", []))]
        selected = important[-4:] + related[-(8-len(important[-4:])):]
        return deepcopy(sorted(selected, key=lambda e: e["seq"]))

    def _record(self, view, phase, context, action, *, role_confidence=None):
        key = (view["round"], view["attempt"], phase, view["self"], action["kind"], action.get("seq"))
        if key in self._recorded:
            return
        self._recorded.add(key)
        scores = self.state.mode_scores
        high = scores.get(context.strategy_mode, 0)
        other = max((v for k, v in scores.items() if k != context.strategy_mode), default=0)
        confidence = bounded(.5 + .20 * (high-other))
        if phase == "assassination":
            confidence = self.state.merlin_probabilities[context.primary_target] if role_confidence is None else role_confidence
        self.decisions.append(StrategyDecision(view["round"], view["attempt"], phase, view["self"],
            context.strategy_mode, context.primary_objective, context.secondary_objective,
            context.primary_target, confidence, context.role, deepcopy(action)))

    def choose_team(self, view):
        context = self.tactical_context(view, phase="team")
        key = (view["round"], view["attempt"])
        if key not in self._teams:
            state = self.state
            def score(team):
                members = self.evil_ids.intersection(team)
                value = 3.0 if len(members) == 1 else -3.0 if not members else 1.0-state.pair_suspicion
                if view["successes"] >= 2 or view["failures"] >= 2:
                    value += 3 if members else -3
                value += sum(state.public_trust[p] - .55 * state.public_suspicion[p] for p in team)
                if state.sacrifice_target in team:
                    value -= 4
                return value + self._random.uniform(-.04, .04)
            candidates = combinations(self.player_ids, view["team_size"])
            self._teams[key] = list(max(candidates, key=score))
            self._record(view, "team", context, {"kind": "team", "team": self._teams[key]})
        return list(self._teams[key])

    def vote(self, view):
        context = self.tactical_context(view, phase="vote")
        key = (view["round"], view["attempt"])
        fingerprint = (tuple(sorted(view["team"])), view["successes"], view["failures"])
        if key in self._votes and self._votes[key][0] != fingerprint:
            raise ValueError("Proposal changed after voting policy was committed")
        if key not in self._votes:
            dirty = bool(self.evil_ids.intersection(view["team"]))
            ballots = {p: dirty for p in sorted(self.evil_ids)}
            if view["attempt"] == 5:
                ballots = dict.fromkeys(sorted(self.evil_ids), False)
            elif view["successes"] >= 2 or view["failures"] >= 2:
                ballots = dict.fromkeys(sorted(self.evil_ids), dirty)
            elif context.strategy_mode == "SACRIFICE":
                sacrifice = self.state.sacrifice_target
                if sacrifice in view["team"]:
                    ballots = {p: p == sacrifice for p in sorted(self.evil_ids)}
                elif dirty:
                    ballots = {p: p != sacrifice for p in sorted(self.evil_ids)}
            elif context.strategy_mode == "FAKE_CONFLICT" or context.distance_strength >= .65:
                aggressor = next(p for p, role in self.state.roles.items() if role == "Aggressor")
                sleeper = next(p for p in self.evil_ids if p != aggressor)
                ballots[aggressor] = aggressor in view["team"] and sleeper not in view["team"]
                ballots[sleeper] = not ballots[aggressor]
            self._votes[key] = (fingerprint, ballots)
        result = self._votes[key][1][view["self"]]
        self._record(view, "vote", context, {"kind": "vote", "approve": result})
        return result

    def mission_cards(self, view, external_cards=None):
        self._validate_view(view)
        external = {} if external_cards is None else external_cards
        if not isinstance(external, dict):
            raise ValueError("External mission cards must be a player map")
        uncontrolled = self.evil_ids.intersection(view["team"]) - self.controlled_evil_ids
        for pid, card in external.items():
            if pid not in uncontrolled or card not in ("SUCCESS", "FAIL"):
                raise ValueError("Invalid external mission card or membership")
        key = (view["round"], view["attempt"])
        fingerprint = (tuple(sorted(view["team"])), tuple(sorted(external.items())))
        if key in self._missions:
            if self._missions[key][0] != fingerprint:
                raise ValueError("External mission cards or team changed after assignment")
            return deepcopy(self._missions[key][1])
        members = sorted(self.controlled_evil_ids.intersection(view["team"]))
        if members and not uncontrolled <= external.keys():
            raise ValueError("External evil mission cards are required before AI assignment")
        cards = dict.fromkeys(members, "SUCCESS")
        self.state.mission_fail_owner = None
        if members:
            context = self.tactical_context(view, phase="mission")
            decisive = view["successes"] >= 2 or view["failures"] >= 2
            cover = (not decisive and view["successes"] + view["failures"] == 0
                     and context.strategy_mode in {"NORMAL_DECEPTION", "CONSENSUS_SEEDING"}
                     and self._random.random() < .18)
            if "FAIL" not in external.values() and (decisive or not cover):
                counts = Counter(e["owner"] for e in self.state.sabotage_history)
                def exposure(pid):
                    return (self.state.public_suspicion[pid] + .4 * (1-self.state.public_trust[pid])
                            + .10 * (self.state.roles[pid] == "Aggressor") - .28 * counts[pid]
                            + self._random.uniform(-.08, .08))
                owner = max(members, key=exposure)
                cards[owner] = "FAIL"
                self.state.mission_fail_owner = owner
                self.state.sabotage_history.append({"round": view["round"], "attempt": view["attempt"], "owner": owner})
                self.state.sabotage_history = self.state.sabotage_history[-5:]
            for pid in members:
                seat = dict(view, self=pid)
                tactical = self.tactical_context(seat, phase="mission")
                self._record(seat, "mission", tactical, {"kind": "mission", "card": cards[pid]})
        self._missions[key] = (fingerprint, deepcopy(cards))
        return cards

    def assassinate(self, view, *, joint_beliefs=None):
        self._validate_view(view)
        if view["role"] != "ASSASSIN":
            raise ValueError("Only the assassin may select an assassination target")
        context = self.tactical_context(view, phase="assassination", joint_beliefs=joint_beliefs)
        key = (view["round"], view["attempt"], view["self"])
        if key not in self._assassinations:
            target = context.primary_target
            self._assassinations[key] = target
            probability = self._merlin_projection(view, joint_beliefs)[target]
            self._record(view, "assassination", context, {"kind": "assassinate", "target": target}, role_confidence=probability)
        return self._assassinations[key]

    def debug_snapshot(self):
        snapshot = asdict(self.state)
        snapshot["evil_ids"] = sorted(self.evil_ids)
        snapshot["controlled_evil_ids"] = sorted(self.controlled_evil_ids)
        snapshot["likely_merlin"] = max(self.good_ids, key=self.state.merlin_probabilities.get)
        snapshot["merlin_probabilities"] = self.state.merlin_probabilities
        snapshot["merlin_probability_source"] = "STANDALONE_ROLE_PRIOR; live decisions use the acting agent's joint beliefs"
        snapshot["public_suspicion_status"] = "PUBLIC_REPUTATION_HEURISTIC_NOT_ROLE_PROBABILITY"
        snapshot["narratives"] = deepcopy(snapshot["active_narratives"])
        snapshot["decisions"] = [asdict(decision) for decision in self.decisions]
        return snapshot
