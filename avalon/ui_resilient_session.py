"""Recovery layer for transient AI/provider failures in the local UI."""

from __future__ import annotations

from typing import Any

from .llm import LLMError
from .ui_playable_session import PlayableUISession
from .ui_session import UIError


class ResilientUISession(PlayableUISession):
    """Keep an in-progress match operable after a failed AI transition."""

    def handle(self, payload: dict[str, Any]) -> dict[str, Any]:
        action_type = str(payload.get("type", "")).upper() if isinstance(payload, dict) else ""
        if action_type == "RETRY_AI":
            if self.pending != "AI_RETRY":
                raise UIError("There is no failed AI transition to retry.")
            self.last_error = ""
            self.pending = ""
            try:
                self._advance()
            except LLMError as exc:
                if not self.pending and self.game.winner is None:
                    self.pending = "AI_RETRY"
                self.last_error = f"LLM action failed: {exc.public_code}"
                raise UIError(self.last_error) from None
            except UIError:
                if not self.pending and self.game.winner is None:
                    self.pending = "AI_RETRY"
                raise
            return self.state()
        try:
            return super().handle(payload)
        except UIError:
            # Human validation errors retain their original pending phase. Only
            # transitions that had already accepted the human action can arrive
            # here with no pending UI phase.
            if not self.pending and self.game.winner is None:
                self.pending = "AI_RETRY"
            raise

    def _legal_actions(self) -> list[str]:
        if self.pending == "AI_RETRY":
            return ["RETRY_AI"]
        return super()._legal_actions()
