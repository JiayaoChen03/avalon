"""Production UI session refinements for the Godot playable client."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .engine import EVIL_ROLES, validate_social
from .llm import LLMError
from .ui_session import PUBLIC_EVIDENCE_KINDS, UIError, UISession


class PlayableUISession(UISession):
    """UISession with challenge-response support and safer user transactions."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.challenge_trigger: dict[str, Any] | None = None

    def handle(self, payload: dict[str, Any]) -> dict[str, Any]:
        action_type = str(payload.get("type", "")).upper() if isinstance(payload, dict) else ""
        if action_type != "CHALLENGE_RESPONSE":
            return super().handle(payload)
        self.last_error = ""
        try:
            self._challenge_response(payload)
        except (UIError, ValueError) as exc:
            self.last_error = str(exc)
            raise UIError(str(exc)) from None
        except LLMError as exc:
            self.last_error = f"LLM action failed: {exc.public_code}"
            raise UIError(self.last_error) from None
        return self.state()

    def state(self) -> dict[str, Any]:
        state = super().state()
        state["challenge_trigger"] = deepcopy(self.challenge_trigger)
        return state

    def _legal_actions(self) -> list[str]:
        if self.pending == "CHALLENGE_RESPONSE":
            actions = ["DECLINE"]
            if self.resolve[self.human_id] >= 1:
                actions.append("RESPOND")
            return actions
        return super()._legal_actions()

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
                        continue

                    self._prepare_agent(speaker)
                    action = self.agents[speaker].social_action()
                    evidence = self._latest_challenge_evidence()
                    should_challenge = (
                        action.get("target") == self.human_id
                        and action.get("card") in {"ACCUSE", "PRESSURE", "BAIT"}
                        and evidence is not None
                    )
                    if should_challenge:
                        self._spend(speaker, 1)
                        self._consume_discussion_turn(
                            speaker,
                            "CHALLENGE",
                            target=self.human_id,
                            evidence=evidence,
                        )
                        event = self.game.events[-1]
                        self.challenge_trigger = self._public_event(event)
                        self.pending = "CHALLENGE_RESPONSE"
                        return

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

    def _latest_challenge_evidence(self) -> int | None:
        for event in reversed(self.game.events):
            if event["kind"] in PUBLIC_EVIDENCE_KINDS and event["kind"] != "CHALLENGE":
                return event["seq"]
        return None

    def _challenge_response(self, payload: dict[str, Any]) -> None:
        self._require_pending("CHALLENGE_RESPONSE")
        action_name = str(payload.get("action", "")).upper()
        challenge = deepcopy(self.challenge_trigger)
        if action_name == "DECLINE":
            self._emit_custom(
                "CHALLENGE_RESPONSE",
                actor=self.human_id,
                responded=False,
                challenge_seq=challenge.get("seq") if challenge else None,
            )
        elif action_name == "RESPOND":
            self._require_resolve(self.human_id, 1)
            action = self._social_payload(payload)
            validate_social(action, self.game.ids, self.game.events)
            self._spend(self.human_id, 1)
            self._emit_custom(
                "CHALLENGE_RESPONSE",
                actor=self.human_id,
                responded=True,
                challenge_seq=challenge.get("seq") if challenge else None,
                **action,
            )
        else:
            raise UIError("Challenge response must be RESPOND or DECLINE.")
        self.challenge_trigger = None
        self.pending = ""
        self._advance()

    def _vote(self, payload: dict[str, Any]) -> None:
        self._require_pending("VOTE")
        approve = payload.get("approve")
        strong = bool(payload.get("strong", False))
        if type(approve) is not bool:
            raise UIError("Vote must be approve or reject.")
        if strong:
            self._require_resolve(self.human_id, 1)

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
        if strong:
            self._spend(self.human_id, 1)
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
        self._resolve_mission(card)

    def _format_event(self, event: dict[str, Any]) -> str:
        if event["kind"] == "CHALLENGE_RESPONSE":
            if event.get("responded"):
                return (
                    f"{self._name(event['actor'])} RESPOND {event['card']} {event['target']} "
                    f"to challenge #{event.get('challenge_seq')}"
                )
            return f"{self._name(event['actor'])} DECLINE challenge #{event.get('challenge_seq')}"
        return super()._format_event(event)
