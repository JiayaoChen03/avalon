"""Local UI session adapter for Godot 4.

This module does not reimplement Resolve, discussion windows, revision, voting,
or mission rules.  The authoritative :class:`avalon.engine.Game` owns all of
those mechanics.  The session only pauses the engine at human decisions,
automates AI seats, and projects a bounded state object for the frontend.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from .agents import Agent
from .engine import CARDS, EVIDENCE_KINDS, EVIL_ROLES, Game, MAX_RESOLVE, make_players
from .evil_strategy import EvilStrategyManager
from .llm import ChatClient, LLMError, Settings
from .terminal import format_event


class UIError(RuntimeError):
    """Safe error that may be shown directly in the local frontend."""


class UISession:
    """One local 1-human + AI game exposed as request/response state."""

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
        human_name = "".join(c for c in str(human_name) if c.isprintable()).strip()[:24] or "YOU"
        self.human_id = "P1"
        self.seed = seed
        self.game = Game(make_players(player_count, seed, human_name), seed=seed)
        self.overlay: str | None = "ROLE_REVEAL"
        self.last_error = ""
        self.latest_mission_result: dict[str, Any] | None = None
        self.latest_vote_result: dict[str, Any] | None = None
        self._event_cursor = 0

        if client is None:
            try:
                settings = settings or Settings.load(env_file)
            except (ValueError, OSError) as exc:
                raise UIError("Invalid LLM configuration.") from exc
            if not settings.ready:
                raise UIError("Missing LLM API key/model configuration in the project .env.")
            try:
                client = ChatClient(settings)
            except LLMError as exc:
                raise UIError(f"LLM backend unavailable: {exc.public_code}") from exc
        self.client = client
        self.settings = settings

        self.agents = {
            pid: Agent(
                self.game.view(pid),
                client,
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

    # ------------------------------------------------------------------
    # Public request API
    # ------------------------------------------------------------------

    def handle(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise UIError("Action payload must be an object.")
        action_type = str(payload.get("type", "")).upper()
        self.last_error = ""
        try:
            if action_type == "CONTINUE":
                self._continue()
            elif action_type == "SUBMIT_TEAM":
                self._submit_team(payload)
            elif action_type == "DISCUSSION":
                self._discussion(payload)
            elif action_type == "CHALLENGE_RESPONSE":
                self._challenge_response(payload)
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
        except UIError:
            raise
        except ValueError as exc:
            self.last_error = str(exc)
            raise UIError(str(exc)) from None
        except LLMError as exc:
            self.last_error = f"LLM action failed: {exc.public_code}"
            raise UIError(self.last_error) from None
        return self.state()

    def state(self) -> dict[str, Any]:
        view = self.game.view(self.human_id)
        phase = self._ui_phase()
        active = view.get("next_actor")
        players = []
        for pid in self.game.ids:
            p = self.game.players[pid]
            players.append({
                "id": pid,
                "name": p.name,
                "is_human": pid == self.human_id,
                "resolve": self.game.resolve[pid],
                "is_leader": pid == self.game.leader,
                "is_on_team": pid in self.game.team,
                "is_active": pid == active,
                "discussion_done": view["discussion_status"].get(pid) == "completed",
            })

        public_events = [self._event_projection(e) for e in self.game.events if e["kind"] != "MISSION_SUBMIT"]
        evidence = [e for e in public_events[-30:] if e["kind"] in EVIDENCE_KINDS]
        challenge = self._challenge_projection(view)
        reaction = self._reaction_projection(view)

        human = self.game.players[self.human_id]
        return {
            "ok": True,
            "phase": phase,
            "engine_phase": self.game.phase,
            "mission_round": self.game.round,
            "proposal_attempt": self.game.attempt,
            "leader": self.game.leader,
            "team_size": self.game.team_size,
            "proposed_team": list(self.game.team),
            "good_wins": self.game.successes,
            "evil_wins": self.game.failures,
            "max_resolve": MAX_RESOLVE,
            "players": players,
            "human": {
                "id": self.human_id,
                "role": human.role,
                "known_evil": list(view["known_evil"]),
                "is_evil": human.role in EVIL_ROLES,
            },
            "active_player": active,
            "legal_actions": self._ui_legal_actions(view, phase),
            "social_cards": list(CARDS),
            "public_events": public_events[-100:],
            "evidence_options": evidence,
            "challenge_trigger": challenge,
            "reaction_trigger": reaction,
            "latest_vote_result": deepcopy(self.latest_vote_result),
            "latest_mission_result": deepcopy(self.latest_mission_result),
            "assassination_targets": self._assassination_targets(),
            "game_result": self._game_result(),
            "last_error": self.last_error,
        }

    # ------------------------------------------------------------------
    # Human commands: all mutations go through Game
    # ------------------------------------------------------------------

    def _continue(self) -> None:
        if self.overlay == "ROLE_REVEAL":
            self.overlay = None
            self._advance_until_human()
            return
        if self.overlay == "ROUND_RESULT":
            self.overlay = None
            self.latest_mission_result = None
            self._advance_until_human()
            return
        raise UIError("Continue is not available now.")

    def _submit_team(self, payload: dict[str, Any]) -> None:
        self._require_ui("TEAM_DRAFT")
        team = payload.get("team")
        if not isinstance(team, list):
            raise UIError("Team must be a player list.")
        self.game.propose(self.human_id, team)
        self._flush_events()
        self._advance_until_human()

    def _discussion(self, payload: dict[str, Any]) -> None:
        self._require_ui("DISCUSSION")
        action_name = str(payload.get("action", "")).upper()
        if action_name == "PASS":
            action = {"kind": "PASS"}
        elif action_name == "SOCIAL":
            action = {
                "kind": "COMMITTED_SOCIAL" if bool(payload.get("commit", False)) else "SOCIAL",
                "social": self._human_social(payload),
            }
        elif action_name == "CHALLENGE":
            action = {
                "kind": "CHALLENGE",
                "target": self._player_id(payload.get("target")),
                "evidence": self._event_seq(payload.get("evidence")),
            }
        elif action_name == "CITE":
            action = {"kind": "CITE", "evidence": self._event_seq(payload.get("evidence"))}
        elif action_name == "HOLD":
            action = {"kind": "HOLD"}
        else:
            raise UIError("Unknown discussion action.")
        self.game.act(self.human_id, action)
        self._flush_events()
        self._advance_until_human()

    def _challenge_response(self, payload: dict[str, Any]) -> None:
        self._require_ui("CHALLENGE_RESPONSE")
        choice = str(payload.get("action", "")).upper()
        if choice == "DECLINE":
            action = {"kind": "DECLINE"}
        elif choice == "RESPOND":
            action = {"kind": "RESPOND", "social": self._human_social(payload)}
        else:
            raise UIError("Challenge response must be RESPOND or DECLINE.")
        self.game.act(self.human_id, action)
        self._flush_events()
        self._advance_until_human()

    def _reaction(self, payload: dict[str, Any]) -> None:
        self._require_ui("REACTION")
        choice = str(payload.get("action", "")).upper()
        if choice in {"KEEP_WAITING", "SKIP"}:
            action = {"kind": "SKIP"}
        elif choice == "REACT":
            action = {"kind": "REACT", "social": self._human_social(payload)}
        else:
            raise UIError("Reaction must be REACT or SKIP.")
        self.game.act(self.human_id, action)
        self._flush_events()
        self._advance_until_human()

    def _team_confirm(self, payload: dict[str, Any]) -> None:
        self._require_ui("TEAM_CONFIRM")
        choice = str(payload.get("action", "")).upper()
        if choice in {"LOCK", "LOCK_TEAM"}:
            action = {"kind": "LOCK"}
        elif choice in {"REVISE", "REVISE_TEAM"}:
            action = {
                "kind": "REVISE",
                "removed": self._player_id(payload.get("remove")),
                "added": self._player_id(payload.get("add")),
            }
        else:
            raise UIError("Choose LOCK or REVISE.")
        self.game.act(self.human_id, action)
        self._flush_events()
        self._advance_until_human()

    def _vote(self, payload: dict[str, Any]) -> None:
        self._require_ui("VOTE")
        approve = payload.get("approve")
        strong = bool(payload.get("strong", False))
        if type(approve) is not bool:
            raise UIError("Vote must be approve or reject.")

        ballots: dict[str, dict[str, bool]] = {
            self.human_id: {"approve": approve, "strong": strong}
        }
        for pid, agent in self.agents.items():
            agent.update_view(self.game.view(pid))
            ballots[pid] = agent.ballot(list(self.game.team), self.game.attempt)
        reasons = {
            pid: "human_choice" if pid == self.human_id else
            "last_chance" if self.game.attempt == 5 else "team_risk"
            for pid in self.game.ids
        }
        self.game.vote(
            {pid: ballot["approve"] for pid, ballot in ballots.items()},
            reasons,
            strong={pid: ballot["strong"] for pid, ballot in ballots.items()},
        )
        self._flush_events()
        self.latest_vote_result = {
            "team": list(self.game.team),
            "votes": {pid: ballot["approve"] for pid, ballot in ballots.items()},
            "strong": {pid: ballot["strong"] for pid, ballot in ballots.items()},
            "approve_count": sum(ballot["approve"] for ballot in ballots.values()),
            "reject_count": sum(not ballot["approve"] for ballot in ballots.values()),
        }
        self.latest_vote_result["approved"] = self.latest_vote_result["approve_count"] > len(self.game.ids) / 2
        self._advance_until_human()

    def _mission(self, payload: dict[str, Any]) -> None:
        self._require_ui("MISSION")
        card = str(payload.get("card", "")).upper()
        if card not in {"SUCCESS", "FAIL"}:
            raise UIError("Mission action must be SUCCESS or FAIL.")
        self._resolve_mission(card)

    def _assassinate(self, payload: dict[str, Any]) -> None:
        self._require_ui("ASSASSINATION")
        target = self._player_id(payload.get("target"))
        self.game.assassinate(self.human_id, target)
        self._flush_events()
        self._advance_until_human()

    # ------------------------------------------------------------------
    # AI driver
    # ------------------------------------------------------------------

    def _advance_until_human(self) -> None:
        while self.overlay is None and self.game.winner is None:
            phase = self.game.phase
            if phase == "team":
                if self.game.leader == self.human_id:
                    return
                leader = self.game.leader
                agent = self.agents[leader]
                if leader not in self.controlled_evil:
                    agent.prepare(self.game.view(leader))
                else:
                    agent.update_view(self.game.view(leader))
                self.game.propose(leader, agent.choose_team(self.game.team_size, self.game.attempt))
                self._flush_events()
                continue

            if phase == "discussion":
                pid = self.game.next_actor
                if pid == self.human_id:
                    return
                agent = self.agents[pid]
                agent.prepare(self.game.view(pid))
                agent.update_view(self.game.view(pid))
                self.game.act(pid, agent.discussion_action())
                self._flush_events()
                continue

            if phase in {"challenge", "reaction"}:
                pid = self.game.next_actor
                if pid == self.human_id:
                    return
                agent = self.agents[pid]
                agent.update_view(self.game.view(pid))
                self.game.act(pid, agent.window_action())
                self._flush_events()
                continue

            if phase == "revision":
                leader = self.game.leader
                if leader == self.human_id:
                    return
                agent = self.agents[leader]
                agent.update_view(self.game.view(leader))
                self.game.act(leader, agent.revise_team())
                self._flush_events()
                continue

            if phase == "vote":
                return

            if phase == "mission":
                if self.human_id in self.game.team:
                    return
                self._resolve_mission(None)
                return

            if phase == "assassination":
                assassin = next(p.id for p in self.game.players.values() if p.role == "ASSASSIN")
                if assassin == self.human_id:
                    return
                agent = self.agents[assassin]
                agent.update_view(self.game.view(assassin))
                self.game.assassinate(assassin, agent.assassinate())
                self._flush_events()
                continue

            if phase == "ended":
                return
            raise UIError(f"Unsupported game phase: {phase}")

    def _resolve_mission(self, human_card: str | None) -> None:
        if self.game.phase != "mission":
            raise UIError("Mission action is unavailable now.")
        if human_card is not None and self.human_id not in self.game.team:
            raise UIError("Human player is not on this mission.")

        external: dict[str, str] = {}
        if human_card is not None and self.game.players[self.human_id].role in EVIL_ROLES:
            external[self.human_id] = human_card

        managed: dict[str, str] = {}
        controlled_on_team = self.controlled_evil.intersection(self.game.team)
        if controlled_on_team:
            sample = next(iter(controlled_on_team))
            managed = self.strategy.mission_cards(self.game.view(sample), external_cards=external)

        cards: dict[str, str] = {}
        for pid in self.game.team:
            if pid == self.human_id:
                cards[pid] = human_card or "SUCCESS"
            elif pid in managed:
                cards[pid] = managed[pid]
            else:
                agent = self.agents[pid]
                agent.update_view(self.game.view(pid))
                cards[pid] = agent.mission()

        mission_round = self.game.round
        self.game.resolve_mission(cards)
        self._flush_events()
        event = next(e for e in reversed(self.game.events) if e["kind"] == "MISSION")
        self.latest_mission_result = {
            "round": mission_round,
            "success": event["success"],
            "fail_count": event["fail_count"],
            "success_count": len(event["team"]) - event["fail_count"],
            "good_wins": event["successes"],
            "evil_wins": event["failures"],
        }
        self.overlay = "ROUND_RESULT"

    def _flush_events(self) -> None:
        for event in self.game.events[self._event_cursor:]:
            self.strategy.observe(deepcopy(event))
            for agent in self.agents.values():
                agent.observe(deepcopy(event))
        self._event_cursor = len(self.game.events)

    # ------------------------------------------------------------------
    # Projection / validation helpers
    # ------------------------------------------------------------------

    def _ui_phase(self) -> str:
        if self.overlay:
            return self.overlay
        if self.game.winner is not None or self.game.phase == "ended":
            return "GAME_OVER"
        mapping = {
            "team": "TEAM_DRAFT",
            "discussion": "DISCUSSION",
            "challenge": "CHALLENGE_RESPONSE",
            "reaction": "REACTION",
            "revision": "TEAM_CONFIRM",
            "vote": "VOTE",
            "mission": "MISSION",
            "assassination": "ASSASSINATION",
        }
        return mapping.get(self.game.phase, self.game.phase.upper())

    def _ui_legal_actions(self, view: dict[str, Any], phase: str) -> list[str]:
        if phase == "ROLE_REVEAL" or phase == "ROUND_RESULT":
            return ["CONTINUE"]
        if phase == "TEAM_DRAFT":
            return ["SUBMIT_TEAM"] if self.game.leader == self.human_id else []
        if phase == "MISSION":
            result = ["SUCCESS"]
            if self.game.players[self.human_id].role in EVIL_ROLES:
                result.append("FAIL")
            return result
        if phase == "ASSASSINATION":
            return ["ASSASSINATE"]
        if phase == "GAME_OVER":
            return ["PLAY_AGAIN", "QUIT"]
        return list(view.get("legal_actions", []))

    def _require_ui(self, phase: str) -> None:
        if self._ui_phase() != phase:
            raise UIError(f"This action requires UI phase {phase}.")

    def _human_social(self, payload: dict[str, Any]) -> dict[str, str]:
        card = str(payload.get("card", "")).upper()
        if card not in CARDS:
            raise UIError("Invalid Social Action card.")
        target = self._player_id(payload.get("target"))
        return {"card": card, "target": target, "reason": "human_choice"}

    def _player_id(self, value: Any) -> str:
        if not isinstance(value, str) or value not in self.game.players:
            raise UIError("Invalid player target.")
        return value

    @staticmethod
    def _event_seq(value: Any) -> int:
        if type(value) is not int or value < 1:
            raise UIError("Choose a valid public event.")
        return value

    def _event_projection(self, event: dict[str, Any]) -> dict[str, Any]:
        try:
            text = format_event(event, self.game.players).lstrip()
        except Exception:
            text = event["kind"]
        return {"seq": event["seq"], "kind": event["kind"], "text": text}

    def _challenge_projection(self, view: dict[str, Any]) -> dict[str, Any] | None:
        challenge = view.get("challenge")
        if not challenge:
            return None
        event = next((e for e in self.game.events if e["seq"] == challenge["seq"]), None)
        return {
            **deepcopy(challenge),
            "text": self._event_projection(event)["text"] if event else "Challenge",
        }

    def _reaction_projection(self, view: dict[str, Any]) -> dict[str, Any] | None:
        seq = view.get("reaction_trigger")
        if not seq:
            return None
        event = next((e for e in self.game.events if e["seq"] == seq), None)
        if event is None:
            return {"seq": seq, "text": "Public action"}
        return self._event_projection(event)

    def _assassination_targets(self) -> list[str]:
        if self._ui_phase() != "ASSASSINATION" or self.game.players[self.human_id].role != "ASSASSIN":
            return []
        evil = set(self.game.view(self.human_id)["known_evil"])
        return [pid for pid in self.game.ids if pid not in evil and pid != self.human_id]

    def _game_result(self) -> dict[str, Any] | None:
        if self.game.winner is None:
            return None
        result = next((e for e in reversed(self.game.events) if e["kind"] == "RESULT"), None)
        return {"winner": self.game.winner, "reason": result.get("reason", "") if result else ""}
