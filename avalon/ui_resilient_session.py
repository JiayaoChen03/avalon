"""Failure-safe wrapper for the Godot session.

If an accepted human action is followed by an LLM failure, the engine mutation is
kept and the UI enters AI_RETRY rather than inviting the human to submit the
same action again.
"""

from __future__ import annotations

from typing import Any

from .llm import LLMError
from .ui_session import UIError, UISession


class ResilientUISession(UISession):
    def handle(self, payload: dict[str, Any]) -> dict[str, Any]:
        action_type = str(payload.get("type", "")).upper() if isinstance(payload, dict) else ""
        if action_type == "RETRY_AI":
            if self.overlay != "AI_RETRY":
                raise UIError("There is no interrupted AI transition to retry.")
            self.last_error = ""
            self.overlay = None
            try:
                self._advance_until_human()
            except LLMError as exc:
                self.overlay = "AI_RETRY"
                self.last_error = f"LLM action failed: {exc.public_code}"
                raise UIError(self.last_error) from None
            return self.state()

        try:
            return super().handle(payload)
        except UIError:
            if self.last_error.startswith("LLM action failed:"):
                self.overlay = "AI_RETRY"
            raise

    def _ui_legal_actions(self, view: dict[str, Any], phase: str) -> list[str]:
        if phase == "AI_RETRY":
            return ["RETRY_AI"]
        return super()._ui_legal_actions(view, phase)
