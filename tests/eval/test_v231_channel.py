import copy

import pytest

from avalon.engine import Game, Player
from avalon.eval.simulation import digest
from avalon.eval.v2.v231_channel import (
    _merlin_stats,
    action_to_event,
    diff_actions,
    validate_recorded_action,
)
from avalon.eval.v2.v23_merlin import build_merlin_disclosure_context


def _view():
    game = Game([
        Player("P1", "YOU", "MERLIN"), Player("P2", "NOVA", "ASSASSIN"),
        Player("P3", "ATLAS", "EVIL"), Player("P4", "ECHO", "GOOD"),
        Player("P5", "SAGE", "GOOD"),
    ], seed=231001, direction="clockwise")
    game.propose(game.leader, [game.leader, "P4"])
    view = game.view("P1")
    return game, view


def _social(card="HEDGE", target="P3", text="x"):
    return {"kind": "SOCIAL", "social": {"card": card, "target": target,
            "reason": "observe", "public_writing": text, "citations": []}}


def test_team_order_is_the_only_presentation_normalization():
    left = {"team": ["P1", "P4"]}
    right = {"team": ["P4", "P1"]}
    diff = diff_actions(left, right)
    assert diff["semantic_action_changed"] == 0
    assert diff["action_category"] == "NO_CHANGE"


def test_text_only_change_is_explicit():
    diff = diff_actions(_social(text="one"), _social(text="two"))
    assert diff["public_text_changed"] == 1
    assert diff["semantic_action_changed"] == 0
    assert diff["action_category"] == "TEXT_ONLY"


def test_structured_card_change_is_not_formatting():
    diff = diff_actions(_social("HEDGE"), _social("ACCUSE"))
    assert diff["card_changed"] == 1
    assert diff["semantic_action_changed"] == 1
    assert diff["action_category"] == "STRUCTURED_ACTION_CHANGE"


def test_mechanical_resource_change_is_separate():
    diff = diff_actions({"kind": "PASS"}, _social())
    assert diff["resource_use_changed"] == 1
    assert diff["action_category"] == "MECHANICAL_CHANGE"


def test_production_validator_accepts_and_rejects_recorded_actions():
    game, view = _view()
    record = {"events": game.events}
    valid, error = validate_recorded_action({"kind": "PROPOSE"},
                                             {"view": view, "observer_id": "P1"}, record)
    # PROPOSE is a menu label, not a transaction action; this must be rejected
    # rather than repaired by the audit.
    assert not valid and error
    valid, error = validate_recorded_action(_social(target="P3"),
                                             {"view": {**view, "phase": "discussion",
                                                       "legal_actions": ["SOCIAL"]},
                                              "observer_id": "P1"}, record)
    assert valid and error is None


def test_immediate_event_does_not_copy_future_events():
    action = _social("ACCUSE", target="P3")
    event = action_to_event(action, {"observer_id": "P1", "round": 1, "attempt": 1}, 7)
    assert event["seq"] == 7
    assert event["kind"] == "SOCIAL"
    assert "success" not in event and "winner" not in event


def test_cloned_predecision_view_is_identical_before_intervention():
    _, view = _view()
    clone = copy.deepcopy(view)
    assert digest(view) == digest(clone)


def test_assassin_private_state_never_enters_merlin_aid():
    _, view = _view()
    view = {**view, "phase": "discussion", "recent_events": [], "focused_events": []}
    aid = build_merlin_disclosure_context({"view": view, "public_event_history": []})
    encoded = repr(aid)
    assert "assassin_posterior" not in encoded
    assert "truth" not in encoded


def test_exact_top_set_and_rank_match_decoder_equality_rule():
    marginals = {
        "P1": {"merlin": 0.25}, "P2": {"merlin": 0.5},
        "P3": {"merlin": 0.5}, "P4": {"merlin": 0.0},
    }
    stats = _merlin_stats(marginals, "P2", ["P1", "P2", "P3"])
    assert stats["top_candidate_set"] == '["P2", "P3"]'
    assert stats["tie_size"] == 2
    assert stats["true_merlin_rank"] == 1


def test_true_role_is_not_needed_for_action_diff_or_event():
    left = _social("DEFEND", "P3")
    right = _social("DEFEND", "P3", "changed")
    before = digest(diff_actions(left, right))
    event = action_to_event(right, {"observer_id": "P1", "round": 2, "attempt": 1}, 4)
    assert before
    assert "role" not in event and "marginal" not in event


def test_missing_action_is_preserved_as_incomplete():
    diff = diff_actions(_social(), None, pre_state_equal=False)
    assert diff["mechanical_state_diverged"] == 1
    assert diff["action_category"] == "MECHANICAL_CHANGE"
