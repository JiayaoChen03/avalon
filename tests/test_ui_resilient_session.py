import pytest

from avalon.llm import LLMError
from avalon.ui_resilient_session import ResilientUISession
from avalon.ui_session import UIError


class NoopClient:
    def complete(self, context):
        raise AssertionError("This focused test should not call the provider")


def test_llm_failure_after_continue_enters_retry_without_replaying_human_action():
    session = ResilientUISession(player_count=5, seed=7, client=NoopClient())

    def fail_once():
        raise LLMError("timeout")

    session._advance_until_human = fail_once
    with pytest.raises(UIError):
        session.handle({"type": "CONTINUE"})

    assert session.overlay == "AI_RETRY"
    assert session.state()["phase"] == "AI_RETRY"
    assert session.game.phase == "team"

    session._advance_until_human = lambda: None
    state = session.handle({"type": "RETRY_AI"})
    assert state["phase"] != "AI_RETRY"
