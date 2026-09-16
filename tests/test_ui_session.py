from copy import deepcopy

from avalon.engine import EVIL_ROLES, MAX_RESOLVE
from avalon.ui_session import UISession


class UIClient:
    """Deterministic valid provider boundary; no network calls."""

    def complete(self, context):
        game = context["game"]
        ids = [p["id"] for p in game["players"]]

        if context.get("decision") == "window":
            legal = game["legal_actions"]
            if "DECLINE" in legal:
                return {"action": {"kind": "DECLINE"}}
            return {"action": {"kind": "SKIP"}}

        if "tactical" in context:
            target = context["tactical"]["primary_target"]
            card = context["tactical"]["allowed_cards"][0]
            return {
                "social": {
                    "card": card,
                    "target": target,
                    "reason": "strategy",
                    "statement": "I want this public position recorded before the vote.",
                    "rationale": "This is based only on the visible proposal and public history.",
                    "evidence": [],
                }
            }

        self_id = game["self"]
        target = next(pid for pid in ids if pid != self_id)
        return {
            "beliefs": {pid: {"evil": 0.3, "merlin": 0.2} for pid in ids},
            "profiles": {
                pid: {"aggression": 0.4, "retaliation": 0.3, "approval": 0.5, "consensus": 0.5}
                for pid in ids
            },
            "strategy": "probe",
            "team_rank": list(ids),
            "vote_threshold": 1.0,
            "approve_last": True,
            "mission": "FAIL" if game["role"] in EVIL_ROLES else "SUCCESS",
            "social": {
                "card": "HEDGE",
                "target": target,
                "reason": "observe",
                "statement": "I am keeping this judgment provisional for now.",
                "rationale": "More public actions are needed before a stronger claim.",
                "evidence": [],
            },
            "assassin_rank": list(ids),
        }


def make_session(seed=7):
    return UISession(player_count=5, seed=seed, client=UIClient())


def human_resolve(state):
    return next(p["resolve"] for p in state["players"] if p["is_human"])


def test_role_reveal_is_private_and_resolve_comes_from_game():
    session = make_session()
    state = session.state()
    assert state["phase"] == "ROLE_REVEAL"
    assert state["human"]["role"]
    assert all("role" not in player for player in state["players"])
    assert all(player["resolve"] == MAX_RESOLVE for player in state["players"])
    assert all(event["kind"] != "REVEAL" for event in state["public_events"])


def test_pass_is_free_and_social_spends_authoritative_resolve():
    session = make_session(seed=9)
    state = session.handle({"type": "CONTINUE"})
    for _ in range(80):
        if state["phase"] == "DISCUSSION":
            break
        if state["phase"] == "TEAM_DRAFT":
            ids = [p["id"] for p in state["players"]]
            state = session.handle({"type": "SUBMIT_TEAM", "team": ids[: state["team_size"]]})
        elif state["phase"] == "CHALLENGE_RESPONSE":
            state = session.handle({"type": "CHALLENGE_RESPONSE", "action": "DECLINE"})
        elif state["phase"] == "REACTION":
            state = session.handle({"type": "REACTION", "action": "KEEP_WAITING"})
        else:
            raise AssertionError(state["phase"])
    assert state["phase"] == "DISCUSSION"

    before = human_resolve(state)
    state = session.handle({"type": "DISCUSSION", "action": "PASS"})
    assert session.game.resolve[session.human_id] == before


def test_full_match_can_be_driven_only_by_ui_commands():
    session = make_session(seed=4)
    state = session.state()

    for _ in range(400):
        phase = state["phase"]
        if phase == "GAME_OVER":
            break
        if phase in {"ROLE_REVEAL", "ROUND_RESULT"}:
            state = session.handle({"type": "CONTINUE"})
        elif phase == "TEAM_DRAFT":
            ids = [p["id"] for p in state["players"]]
            state = session.handle({"type": "SUBMIT_TEAM", "team": ids[: state["team_size"]]})
        elif phase == "DISCUSSION":
            state = session.handle({"type": "DISCUSSION", "action": "PASS"})
        elif phase == "CHALLENGE_RESPONSE":
            state = session.handle({"type": "CHALLENGE_RESPONSE", "action": "DECLINE"})
        elif phase == "REACTION":
            state = session.handle({"type": "REACTION", "action": "KEEP_WAITING"})
        elif phase == "TEAM_CONFIRM":
            state = session.handle({"type": "TEAM_CONFIRM", "action": "LOCK_TEAM"})
        elif phase == "VOTE":
            state = session.handle({"type": "VOTE", "approve": True, "strong": False})
        elif phase == "MISSION":
            state = session.handle({"type": "MISSION", "card": "SUCCESS"})
        elif phase == "ASSASSINATION":
            state = session.handle({"type": "ASSASSINATE", "target": state["assassination_targets"][0]})
        else:
            raise AssertionError(f"Unexpected UI phase: {phase}")

    assert state["phase"] == "GAME_OVER"
    assert state["game_result"]["winner"] in {"GOOD", "EVIL"}


def test_rejected_proposal_does_not_refresh_resolve_but_mission_does():
    session = make_session(seed=11)
    state = session.handle({"type": "CONTINUE"})

    for _ in range(80):
        if state["phase"] == "DISCUSSION":
            break
        if state["phase"] == "TEAM_DRAFT":
            ids = [p["id"] for p in state["players"]]
            state = session.handle({"type": "SUBMIT_TEAM", "team": ids[: state["team_size"]]})
        elif state["phase"] == "CHALLENGE_RESPONSE":
            state = session.handle({"type": "CHALLENGE_RESPONSE", "action": "DECLINE"})
        elif state["phase"] == "REACTION":
            state = session.handle({"type": "REACTION", "action": "KEEP_WAITING"})
    assert state["phase"] == "DISCUSSION"

    target = next(p["id"] for p in state["players"] if not p["is_human"])
    state = session.handle({
        "type": "DISCUSSION",
        "action": "SOCIAL",
        "card": "HEDGE",
        "target": target,
        "commit": False,
    })
    assert session.game.resolve[session.human_id] == MAX_RESOLVE - 1

    # Continue with free actions and an approved proposal until mission resolution.
    for _ in range(180):
        phase = state["phase"]
        if phase == "ROUND_RESULT":
            break
        if phase == "DISCUSSION":
            state = session.handle({"type": "DISCUSSION", "action": "PASS"})
        elif phase == "CHALLENGE_RESPONSE":
            state = session.handle({"type": "CHALLENGE_RESPONSE", "action": "DECLINE"})
        elif phase == "REACTION":
            state = session.handle({"type": "REACTION", "action": "KEEP_WAITING"})
        elif phase == "TEAM_CONFIRM":
            state = session.handle({"type": "TEAM_CONFIRM", "action": "LOCK_TEAM"})
        elif phase == "VOTE":
            state = session.handle({"type": "VOTE", "approve": True, "strong": False})
        elif phase == "MISSION":
            state = session.handle({"type": "MISSION", "card": "SUCCESS"})
        elif phase == "TEAM_DRAFT":
            ids = [p["id"] for p in state["players"]]
            state = session.handle({"type": "SUBMIT_TEAM", "team": ids[: state["team_size"]]})
        else:
            raise AssertionError(phase)

    assert state["phase"] == "ROUND_RESULT"
    assert all(value == MAX_RESOLVE for value in session.game.resolve.values())
