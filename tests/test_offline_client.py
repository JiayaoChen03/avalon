from avalon.offline_client import OfflineClient


def _game(phase, self_id="P4", recent_events=None):
    return {
        "self": self_id,
        "phase": phase,
        "players": [{"id": pid, "name": pid} for pid in ("P1", "P2", "P3", "P4")],
        "recent_events": recent_events or [],
    }


def test_offline_client_uses_current_phase_and_bounded_self_field():
    client = OfflineClient()
    discussion = client.complete({
        "game": _game("discussion"),
        "legal_actions": [{"kind": "SOCIAL"}],
    })
    council_without_vote_history = client.complete({
        "game": _game("council_discussion"),
        "legal_actions": [{"kind": "PASS"}, {"kind": "SOCIAL"}],
    })
    council = client.complete({
        "game": _game("council_discussion", recent_events=[{"kind": "TEAM_VOTE", "seq": 8}]),
        "legal_actions": [{"kind": "PASS"}, {"kind": "SOCIAL"}],
    })

    assert discussion["social"]["target"] == "P1"
    assert council["social"]["target"] == "P1"
    assert discussion["social"]["statement"] != council["social"]["statement"]
    assert council["social"]["statement"] == council_without_vote_history["social"]["statement"]
    assert "后续投票判断" not in discussion["social"]["statement"]
    assert "后续投票判断" not in council["social"]["statement"]


def test_offline_client_tactical_branch_uses_the_same_phase_contract():
    result = OfflineClient().complete({
        "game": _game("discussion"),
        "legal_actions": [{"kind": "SOCIAL"}],
        "tactical": {"allowed_cards": ["HEDGE"], "primary_target": "P2"},
    })

    assert result["social"]["target"] == "P2"
    assert result["social"]["statement"] == "我先根据当前公开记录和队伍状态行动。"


def test_offline_client_window_returns_the_action_contract():
    client = OfflineClient()

    assert client.complete({
        "decision": "window",
        "game": {"legal_actions": ["DECLINE", "RESPOND"]},
    }) == {"action": {"kind": "DECLINE"}}
    assert client.complete({
        "decision": "window",
        "game": {"legal_actions": ["SKIP", "REACT"]},
    }) == {"action": {"kind": "SKIP"}}
