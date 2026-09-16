"""Stateful backend adapter for the local Godot UI.

Godot is intentionally a presentation layer.  This module owns the human-facing
phase machine, Resolve economy, and UI-only public actions while delegating core
Avalon rules, hidden roles, mission resolution, agents, and evil strategy to the
existing Python engine.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from .agents import Agent
from .engine import CARDS, EVIL_ROLES, Game, make_players, validate_social
from .evil_strategy import EvilStrategyManager
from .llm import ChatClient, LLMError, Settings


MAX_RESOLVE = 3
PUBLIC_EVIDENCE_KINDS = {
    "TEAM", "SOCIAL", "PASS", "CHALLENGE", "CITE", "HOLD", "REACTION",
    "TEAM_REVISE", "BALLOT_RESULT", "MISSION",
}


class UIError(RuntimeError):
    """Safe validation/configuration error for the local UI."""


class UISession:
    """One local 1-human + AI match exposed as a request/response state machine."""

    def __init__(
        self,
        *,
        player_count: int = 5,
        seed: int | None = None,
        human_name: str = "YOU",
        env_file: str | Path | None = None,
        client: Any | None = None,
        settings: Settings | None = None,
    ):
        human_name = "".join(c for c in human_name if c.isprintable()).strip()[:24] or "YOU"
        self.game = Game(make_players(player_count, seed, human_name), seed=seed)
        self.human_id = "P1"
        self.resolve = dict.fromkeys(self.game.ids, MAX_RESOLVE)
        self.pending = "ROLE_REVEAL"
        self.last_error = ""
        self.latest_vote_result: dict[str, Any] | None = None
        self.latest_mission_result: dict[str, Any] | None = None
        self.pending_reaction = False
        self.reaction_trigger: dict[str, Any] | None = None
        self._event_cursor = 0

        if client is None:
            try:
                settings = settings or Settings.load(env_file)
            except (ValueError, OSError) as exc:
                raise UIError("Invalid LLM configuration.") from exc
            if not settings.ready:
                raise UIError("Missing OPENAI_API_KEY/LLM_API_KEY and OPENAI_MODEL/LLM_MODEL configuration.")
            try:
                client = ChatClient(settings)
            except LLMError as exc:
                raise UIError(f"LLM backend unavailable: {exc.public_code}") from exc
        self.client = client
        self.settings = settings

        self.agents = {
            pid: Agent(
                self.game.view(pid),
                self.client,
                max_retries=(settings.max_retries if settings else 2),
                retry_delay=(settings.retry_delay if settings else 0.0),
            )
            for pid in self.game.ids
            if pid != self.human_id
        }
        evil_ids = {p.id for p in self.game.players.values() if p.role in EVIL_ROLES}
        self.controlled_evil = evil_ids & set(self.agents)
        self.strategy = EvilStrategyManager(
            self.game.ids,
            evil_ids,
            seed=seed,
            controlled_evil_ids=self.controlled_evil,
        )
        for pid in self.controlled_evil:
            self.agents[pid].bind_evil_strategy(self.strategy)
        self._flush_events()

    # ---------- public API ----------

    def handle(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise UIError("Action payload must be an object.")
        action_type = str(payload.get("type", "")).upper()
        self.last_error = ""
        try:
            if action_type == "CONTINUE":
                self._continue()
            elif action_type == "SUBMIT_TEAM":
                self._submit_team(payload.get("team"))
            elif action_type == "DISCUSSION":
                self._discussion(payload)
            elif action_type == "REACTION":
                self._reaction(payload)
            elif action_type == "TEAM_CONFIRM":
                self._team_confirm(payload)
            elif action_type == "VOTE":
                self._vote(payload)
            elif action_type == "MISSION":
                self._mission(payload)
            elif action_type == "ASSASSINATE":
                self._assassinate(payload)
            else:
                raise UIError("Unknown action type.")
        except (UIError, ValueError) as exc:
            self.last_error = str(exc)
            raise UIError(str(exc)) from None
        except LLMError as exc:
            self.last_error = f"LLM action failed: {exc.public_code}"
            raise UIError(self.last_error) from None
        return self.state()

    def state(self) -> dict[str, Any]:
        game = self.game
        human = game.players[self.human_id]
        active = self._active_player()
        public_events = [item for item in (self._public_event(e) for e in game.events) if item is not None]
        legal = self._legal_actions()
        players = []
        for pid in game.ids:
            p = game.players[pid]
            players.append({
                "id": pid,
                "name": p.name,
                "is_human": pid == self.human_id,
                "resolve": self.resolve[pid],
                "is_leader": pid == game.leader,
                "is_on_team": pid in game.team,
                "is_active": pid == active,
                "discussion_done": pid in game.spoken,
            })
        known_evil = game.view(self.human_id)["known_evil"]
        return {
            "ok": True,
            "phase": self.pending,
            "engine_phase": game.phase,
            "mission_round": game.round,
            "proposal_attempt": game.attempt,
            "leader": game.leader,
            "team_size": game.team_size,
            "proposed_team": list(game.team),
            "good_wins": game.successes,
            "evil_wins": game.failures,
            "max_resolve": MAX_RESOLVE,
            "players": players,
            "human": {
                "id": self.human_id,
                "role": human.role,
                "known_evil": list(known_evil),
                "is_evil": human.role in EVIL_ROLES,
            },
            "active_player": active,
            "legal_actions": legal,
            "social_cards": list(CARDS),
            "public_events": public_events[-80:],
            "evidence_options": [e for e in public_events[-20:] if e["kind"] in PUBLIC_EVIDENCE_KINDS],
            "latest_vote_result": deepcopy(self.latest_vote_result),
            "latest_mission_result": deepcopy(self.latest_mission_result),
            "reaction_trigger": deepcopy(self.reaction_trigger),
            "assassination_targets": self._assassination_targets(),
            "game_result": self._game_result(),
            "last_error": self.last_error,
        }

    # ---------- progression ----------

    def _continue(self) -> None:
        if self.pending == "ROLE_REVEAL":
            self.pending = ""
            self._advance()
            return
        if self.pending == "ROUND_RESULT":
            self.pending = ""
            self.latest_mission_result = None
            self._advance()
            return
        raise UIError("Continue is not available in the current phase.")

    def _advance(self) -> None:
        while not self.pending:
            if self.game.winner is not None or self.game.phase == "ended":
                self.pending = "GAME_OVER"
                return

            if self.game.phase == "team":
                if self.game.leader == self.human_id:
                    self.pending = "TEAM_DRAFT"
                    return
                leader = self.game.leader
                if leader not in self.controlled_evil:
                    self._prepare_agent(leader)
                else:
                    self.agents[leader].update_view(self.game.view(leader))
                team = self.agents[leader].choose_team(self.game.team_size, self.game.attempt)
                self.game.propose(leader, team)
                self._flush_events()
                continue

            if self.game.phase == "discussion":
                if len(self.game.spoken) < len(self.game.ids):
                    speaker = self._current_speaker()
                    if speaker == self.human_id:
                        self.pending = "DISCUSSION"
                        return
                    if self.resolve[speaker] <= 0:
                        self._consume_discussion_turn(speaker, "PASS")
                    else:
                        self._prepare_agent(speaker)
                        action = self.agents[speaker].social_action()
                        self._spend(speaker, 1)
                        self.game.social(speaker, action)
                        self._flush_events()
                        if self.pending_reaction:
                            trigger = self.game.events[-1]
                            if trigger.get("kind") == "SOCIAL":
                                self.reaction_trigger = self._public_event(trigger)
                                self.pending = "REACTION"
                                return
                    continue

                if self.pending_reaction:
                    self.pending_reaction = False
                    self.reaction_trigger = None
                    self._emit_custom("REACTION_EXPIRED", actor=self.human_id)
                if self.game.leader == self.human_id:
                    self.pending = "TEAM_CONFIRM"
                else:
                    self.pending = "VOTE"
                return

            if self.game.phase == "mission":
                if self.human_id in self.game.team:
                    self.pending = "MISSION"
                    return
                self._resolve_mission(None)
                return

            if self.game.phase == "assassination":
                assassin = next(p.id for p in self.game.players.values() if p.role == "ASSASSIN")
                if assassin == self.human_id:
                    self.pending = "ASSASSINATION"
                    return
                self.agents[assassin].update_view(self.game.view(assassin))
                target = self.agents[assassin].assassinate()
                self.game.assassinate(assassin, target)
                self._flush_events()
                continue

            raise UIError(f"Unsupported engine phase: {self.game.phase}")

    # ---------- human actions ----------

    def _submit_team(self, team: Any) -> None:
        self._require_pending("TEAM_DRAFT")
        if self.game.leader != self.human_id:
            raise UIError("Only the current leader can choose a team.")
        if not isinstance(team, list):
            raise UIError("Team must be a player list.")
        self.game.propose(self.human_id, team)
        self._flush_events()
        self.pending = ""
        self._advance()

    def _discussion(self, payload: dict[str, Any]) -> None:
        self._require_pending("DISCUSSION")
        if self._current_speaker() != self.human_id:
            raise UIError("It is not the human player's discussion turn.")
        action_name = str(payload.get("action", "")).upper()

        if action_name == "PASS":
            self._consume_discussion_turn(self.human_id, "PASS")
        elif action_name == "SOCIAL":
            commit = bool(payload.get("commit", False))
            cost = 2 if commit else 1
            self._require_resolve(self.human_id, cost)
            action = self._social_payload(payload)
            validate_social(action, self.game.ids, self.game.events)
            self._spend(self.human_id, cost)
            self.game.social(self.human_id, action)
            if commit:
                self.game.events[-1]["committed"] = True
            self._flush_events()
        elif action_name == "CHALLENGE":
            self._require_resolve(self.human_id, 1)
            target = self._valid_target(payload.get("target"), allow_self=False)
            evidence = self._valid_evidence(payload.get("evidence"))
            self._spend(self.human_id, 1)
            self._consume_discussion_turn(self.human_id, "CHALLENGE", target=target, evidence=evidence)
        elif action_name == "CITE":
            self._require_resolve(self.human_id, 1)
            evidence = self._valid_evidence(payload.get("evidence"))
            self._spend(self.human_id, 1)
            self._consume_discussion_turn(self.human_id, "CITE", evidence=evidence)
        elif action_name == "HOLD":
            self._require_resolve(self.human_id, 1)
            self._spend(self.human_id, 1)
            self.pending_reaction = True
            self._consume_discussion_turn(self.human_id, "HOLD")
        else:
            raise UIError("Unknown discussion action.")

        self.pending = ""
        self._advance()

    def _reaction(self, payload: dict[str, Any]) -> None:
        self._require_pending("REACTION")
        action_name = str(payload.get("action", "")).upper()
        if action_name == "KEEP_WAITING":
            self.reaction_trigger = None
            self.pending = ""
            self._advance()
            return
        if action_name != "REACT":
            raise UIError("Unknown reaction action.")
        action = self._social_payload(payload)
        validate_social(action, self.game.ids, self.game.events)
        trigger_seq = self.reaction_trigger["seq"] if self.reaction_trigger else None
        self._emit_custom("REACTION", actor=self.human_id, trigger_seq=trigger_seq, **action)
        self.pending_reaction = False
        self.reaction_trigger = None
        self.pending = ""
        self._advance()

    def _team_confirm(self, payload: dict[str, Any]) -> None:
        self._require_pending("TEAM_CONFIRM")
        if self.game.leader != self.human_id:
            raise UIError("Only the leader may lock or revise the team.")
        action_name = str(payload.get("action", "")).upper()
        if action_name == "LOCK_TEAM":
            self._emit_custom("TEAM_LOCK", actor=self.human_id, team=list(self.game.team))
        elif action_name == "REVISE_TEAM":
            self._require_resolve(self.human_id, 1)
            remove = self._valid_target(payload.get("remove"))
            add = self._valid_target(payload.get("add"))
            if remove not in self.game.team or add in self.game.team or remove == add:
                raise UIError("Revision must replace exactly one team member with one non-member.")
            self._spend(self.human_id, 1)
            old_team = list(self.game.team)
            self.game.team = [add if pid == remove else pid for pid in self.game.team]
            self._emit_custom(
                "TEAM_REVISE",
                actor=self.human_id,
                removed=remove,
                added=add,
                previous_team=old_team,
                team=list(self.game.team),
            )
        else:
            raise UIError("Unknown team confirmation action.")
        self.pending = "VOTE"

    def _vote(self, payload: dict[str, Any]) -> None:
        self._require_pending("VOTE")
        approve = payload.get("approve")
        strong = bool(payload.get("strong", False))
        if type(approve) is not bool:
            raise UIError("Vote must be approve or reject.")
        if strong:
            self._require_resolve(self.human_id, 1)
            self._spend(self.human_id, 1)

        round_no, attempt_no = self.game.round, self.game.attempt
        team = list(self.game.team)
        votes = {self.human_id: approve}
        reasons = {self.human_id: "human_choice"}
        for pid, agent in self.agents.items():
            agent.update_view(self.game.view(pid))
            votes[pid] = bool(agent.vote(team, self.game.attempt))
            reasons[pid] = "last_chance" if self.game.attempt == 5 else "team_risk"
        approved = sum(votes.values()) > len(votes) / 2
        self.game.vote(votes, reasons)
        self._flush_events()
        strong_map = {pid: bool(strong and pid == self.human_id) for pid in self.game.ids}
        self._emit_at(
            "BALLOT_RESULT",
            round_no,
            attempt_no,
            team=team,
            votes=deepcopy(votes),
            strong=strong_map,
            approved=approved,
        )
        self.latest_vote_result = {
            "team": team,
            "votes": deepcopy(votes),
            "strong": strong_map,
            "approve_count": sum(votes.values()),
            "reject_count": len(votes) - sum(votes.values()),
            "approved": approved,
        }
        self.pending = ""
        self._advance()

    def _mission(self, payload: dict[str, Any]) -> None:
        self._require_pending("MISSION")
        if self.human_id not in self.game.team:
            raise UIError("The human player is not on this mission.")
        card = str(payload.get("card", "")).upper()
        if card not in {"SUCCESS", "FAIL"}:
            raise UIError("Mission card must be SUCCESS or FAIL.")
        if card == "FAIL" and self.game.players[self.human_id].role not in EVIL_ROLES:
            raise UIError("Good players cannot submit FAIL.")
        self.pending = ""
        self._resolve_mission(card)

    def _assassinate(self, payload: dict[str, Any]) -> None:
        self._require_pending("ASSASSINATION")
        if self.game.players[self.human_id].role != "ASSASSIN":
            raise UIError("Only the Assassin may choose an assassination target.")
        target = self._valid_target(payload.get("target"), allow_self=False)
        if target not in self._assassination_targets():
            raise UIError("Invalid assassination target.")
        self.game.assassinate(self.human_id, target)
        self._flush_events()
        self.pending = ""
        self._advance()

    # ---------- AI / mission helpers ----------

    def _prepare_agent(self, pid: str) -> None:
        agent = self.agents[pid]
        agent.prepare(self.game.view(pid))

    def _resolve_mission(self, human_card: str | None) -> None:
        team = list(self.game.team)
        external: dict[str, str] = {}
        if human_card is not None and self.game.players[self.human_id].role in EVIL_ROLES:
            external[self.human_id] = human_card

        managed: dict[str, str] = {}
        controlled_on_team = self.controlled_evil.intersection(team)
        if controlled_on_team:
            sample = next(iter(controlled_on_team))
            managed = self.strategy.mission_cards(self.game.view(sample), external_cards=external)

        cards: dict[str, str] = {}
        for pid in team:
            if pid == self.human_id:
                cards[pid] = human_card or "SUCCESS"
            elif pid in managed:
                cards[pid] = managed[pid]
            else:
                self.agents[pid].update_view(self.game.view(pid))
                cards[pid] = self.agents[pid].mission()

        self.game.resolve_mission(cards)
        self._flush_events()
        self.resolve = dict.fromkeys(self.game.ids, MAX_RESOLVE)
        event = next(e for e in reversed(self.game.events) if e["kind"] == "MISSION")
        self.latest_mission_result = {
            "round": event["round"],
            "success": event["success"],
            "fail_count": event["fail_count"],
            "success_count": len(event["team"]) - event["fail_count"],
            "good_wins": event["successes"],
            "evil_wins": event["failures"],
        }
        self.pending_reaction = False
        self.reaction_trigger = None
        self.pending = "ROUND_RESULT"

    # ---------- validation / events ----------

    def _require_pending(self, phase: str) -> None:
        if self.pending != phase:
            raise UIError(f"This action requires UI phase {phase}.")

    def _current_speaker(self) -> str:
        if self.game.phase != "discussion" or len(self.game.spoken) >= len(self.game.ids):
            raise UIError("There is no active discussion speaker.")
        return self.game.speaking_order[len(self.game.spoken)]

    def _consume_discussion_turn(self, actor: str, kind: str, **data: Any) -> None:
        if self.game.phase != "discussion":
            raise UIError("Discussion action is unavailable outside discussion.")
        if actor in self.game.spoken or actor != self._current_speaker():
            raise UIError("Wait for this player's discussion turn.")
        self.game.spoken.add(actor)
        self._emit_custom(kind, actor=actor, **data)

    def _spend(self, pid: str, cost: int) -> None:
        self._require_resolve(pid, cost)
        self.resolve[pid] -= cost

    def _require_resolve(self, pid: str, cost: int) -> None:
        if cost < 0 or self.resolve[pid] < cost:
            raise UIError("Not enough Resolve.")

    def _valid_target(self, value: Any, *, allow_self: bool = True) -> str:
        if not isinstance(value, str) or value not in self.game.players:
            raise UIError("Invalid player target.")
        if not allow_self and value == self.human_id:
            raise UIError("Choose another player.")
        return value

    def _valid_evidence(self, value: Any) -> int:
        if type(value) is not int:
            raise UIError("Choose one public evidence event.")
        allowed = {e["seq"] for e in self.game.events if e["kind"] in PUBLIC_EVIDENCE_KINDS}
        if value not in allowed:
            raise UIError("Evidence must reference an eligible public event.")
        return value

    def _social_payload(self, payload: dict[str, Any]) -> dict[str, str]:
        card = str(payload.get("card", "")).upper()
        target = self._valid_target(payload.get("target"))
        if card not in CARDS:
            raise UIError("Invalid Social Action card.")
        return {"card": card, "target": target, "reason": "human_choice"}

    def _emit_custom(self, kind: str, **data: Any) -> None:
        self.game._emit(kind, **data)  # package-level backend extension; Godot never mutates rules/state
        self._flush_events()

    def _emit_at(self, kind: str, round_no: int, attempt_no: int, **data: Any) -> None:
        self.game.events.append({
            "seq": len(self.game.events) + 1,
            "kind": kind,
            "round": round_no,
            "attempt": attempt_no,
            **deepcopy(data),
        })
        self._flush_events()

    def _flush_events(self) -> None:
        for event in self.game.events[self._event_cursor:]:
            self.strategy.observe(deepcopy(event)) if hasattr(self, "strategy") else None
            for agent in getattr(self, "agents", {}).values():
                agent.observe(deepcopy(event))
        self._event_cursor = len(self.game.events)

    # ---------- state projection ----------

    def _legal_actions(self) -> list[str]:
        r = self.resolve[self.human_id]
        if self.pending == "ROLE_REVEAL":
            return ["CONTINUE"]
        if self.pending == "TEAM_DRAFT":
            return ["SUBMIT_TEAM"]
        if self.pending == "DISCUSSION":
            actions = ["PASS"]
            if r >= 1:
                actions += ["SOCIAL", "CHALLENGE", "CITE", "HOLD"]
            if r >= 2:
                actions.append("COMMIT")
            return actions
        if self.pending == "REACTION":
            return ["REACT", "KEEP_WAITING"]
        if self.pending == "TEAM_CONFIRM":
            actions = ["LOCK_TEAM"]
            if r >= 1:
                actions.append("REVISE_TEAM")
            return actions
        if self.pending == "VOTE":
            actions = ["APPROVE", "REJECT"]
            if r >= 1:
                actions += ["STRONG_APPROVE", "STRONG_REJECT"]
            return actions
        if self.pending == "MISSION":
            actions = ["SUCCESS"]
            if self.game.players[self.human_id].role in EVIL_ROLES:
                actions.append("FAIL")
            return actions
        if self.pending == "ROUND_RESULT":
            return ["CONTINUE"]
        if self.pending == "ASSASSINATION":
            return ["ASSASSINATE"]
        if self.pending == "GAME_OVER":
            return ["PLAY_AGAIN", "QUIT"]
        return []

    def _active_player(self) -> str | None:
        if self.pending == "DISCUSSION":
            return self.human_id
        if self.game.phase == "discussion" and len(self.game.spoken) < len(self.game.ids):
            return self.game.speaking_order[len(self.game.spoken)]
        if self.pending in {"TEAM_DRAFT", "TEAM_CONFIRM"}:
            return self.game.leader
        return None

    def _assassination_targets(self) -> list[str]:
        if self.pending != "ASSASSINATION" or self.game.players[self.human_id].role != "ASSASSIN":
            return []
        known_evil = set(self.game.view(self.human_id)["known_evil"])
        return [pid for pid in self.game.ids if pid not in known_evil and pid != self.human_id]

    def _game_result(self) -> dict[str, Any] | None:
        if self.game.winner is None:
            return None
        event = next((e for e in reversed(self.game.events) if e["kind"] == "RESULT"), None)
        return {"winner": self.game.winner, "reason": event.get("reason") if event else ""}

    def _public_event(self, event: dict[str, Any]) -> dict[str, Any] | None:
        kind = event["kind"]
        if kind == "MISSION_SUBMIT":
            return None
        if kind == "REVEAL" and self.game.winner is None:
            return None
        return {"seq": event["seq"], "kind": kind, "text": self._format_event(event)}

    def _name(self, pid: str | None) -> str:
        if not pid or pid not in self.game.players:
            return str(pid or "")
        p = self.game.players[pid]
        return f"{p.name}/{pid}"

    def _format_event(self, e: dict[str, Any]) -> str:
        kind = e["kind"]
        if kind == "START":
            return "Players seated: " + ", ".join(f"{p['name']}/{p['id']}" for p in e["players"])
        if kind == "LEADER":
            return f"Leader: {self._name(e.get('actor'))}"
        if kind == "DIRECTION":
            return f"Speaking direction: {e['direction']}"
        if kind == "ROUND":
            return f"Mission {e['round']}/5 begins — team size {e['team_size']}"
        if kind == "TEAM":
            return f"{self._name(e['actor'])} proposed {' / '.join(e['team'])}"
        if kind == "SOCIAL":
            suffix = " + COMMIT" if e.get("committed") else ""
            return f"{self._name(e['actor'])} {e['card']} {e['target']}{suffix}"
        if kind == "PASS":
            return f"{self._name(e['actor'])} PASS"
        if kind == "CHALLENGE":
            return f"{self._name(e['actor'])} CHALLENGE {e['target']} using #{e['evidence']}"
        if kind == "CITE":
            return f"{self._name(e['actor'])} CITE #{e['evidence']}"
        if kind == "HOLD":
            return f"{self._name(e['actor'])} HOLD — reaction ready"
        if kind == "REACTION":
            return f"{self._name(e['actor'])} REACT {e['card']} {e['target']} to #{e.get('trigger_seq')}"
        if kind == "REACTION_EXPIRED":
            return f"{self._name(e['actor'])} reaction expired"
        if kind == "TEAM_LOCK":
            return f"{self._name(e['actor'])} locked {' / '.join(e['team'])}"
        if kind == "TEAM_REVISE":
            return f"{self._name(e['actor'])} revised {e['removed']} → {e['added']}"
        if kind == "VOTE":
            return f"{self._name(e['actor'])} voted {'APPROVE' if e['approve'] else 'REJECT'}"
        if kind == "TEAM_VOTE":
            yes = sum(e["votes"].values())
            return f"Team vote: {yes} approve / {len(e['votes']) - yes} reject"
        if kind == "BALLOT_RESULT":
            labels = []
            for pid in self.game.ids:
                vote = "APPROVE" if e["votes"][pid] else "REJECT"
                if e["strong"].get(pid):
                    vote = "STRONG " + vote
                labels.append(f"{pid} {vote}")
            return ("Ballots: " + " | ".join(labels)
                    + (" — TEAM APPROVED" if e["approved"] else " — TEAM REJECTED"))
        if kind == "MISSION":
            return (f"Mission {'SUCCESS' if e['success'] else 'FAILED'} — "
                    f"SUCCESS {len(e['team']) - e['fail_count']} / FAIL {e['fail_count']}")
        if kind == "ASSASSINATION_PHASE":
            return "Three mission successes — assassination phase"
        if kind == "ASSASSINATE":
            return f"{self._name(e['actor'])} assassinated {e['target']}"
        if kind == "RESULT":
            return f"{e['winner']} WINS — {e['reason']}"
        if kind == "REVEAL":
            return "Roles revealed: " + " | ".join(f"{pid} {role}" for pid, role in e["roles"].items())
        return kind
