from avalon.engine import EVIL_ROLES
from avalon.ui_playable_session import PlayableUISession
from avalon.ui_session import MAX_RESOLVE


class FakeClient:
    """Deterministic valid policy output; no network calls."""

    def complete(self, context):
        game = context["game"]
        ids = [p["id"] for p in game["players"]]
        if "tactical" in context:
            tactical = context["tactical"]
            return {
                "social": {
                    "card": tactical["allowed_cards"][0],
                    "target": tactical["primary_target"],
                    "reason": "observe",
                    "statement": "I want to test this seat's public position.",
                    "rationale": "This is based only on the public discussion so far.",
                    "evidence": [],
                }
            }
        self_id = game["self"]
        social_target = next(pid for pid in ids if pid != self_id)
        beliefs = {
            pid: {
                "evil": 1.0 if pid in game["known_evil"] else 0.0 if game["known_evil"] else 0.25,
                "merlin": 1.0 if game["role"] == "MERLIN" and pid == self_id else 0.0,
            }
            for pid in ids
        }
        profiles = {
            pid: {"aggression": 0.5, "approval": 0.5, "consensus": 0.5, "retaliation": 0.5}
            for pid in ids
        }
        return {
            "beliefs": beliefs,
            "profiles": profiles,
            "strategy": "observe",
            "team_rank": list(ids),
            "vote_threshold": 1.0,
            "approve_last": True,
            "mission": "FAIL" if game["role"] in EVIL_ROLES else "SUCCESS",
            "social": {
                "card": "HEDGE",
                "target": social_target,
                "reason": "observe",
                "statement": "I am keeping this judgment provisional.",
                "rationale": "I want more public actions before making a stronger claim.",
                "evidence": [],
            },
            "assassin_rank": list(ids),
        }


def make_session(seed=7):
    return PlayableUISession(player_count=5, seed=seed, client=FakeClient())


def advance_nonchoice_interrupts(session, state):
    """Decline AI challenges/reactions until a normal player choice is required."""
    for _ in range(30):
        if state["phase"] == "CHALLENGE_RESPONSE":
            state = session.handle({"type": "CHALLENGE_RESPONSE", "action": "DECLINE"})
        elif state["phase"] == "REACTION":
            state = session.handle({"type": "REACTION", "action": "KEEP_WAITING"})
        else:
            return state
    raise AssertionError("Too many interrupt phases")


def test_role_reveal_is_private_and_start_state_is_complete():
    session = make_session()
    state = session.state()
    assert state["phase"] == "ROLE_REVEAL"
    assert state["human"]["role"]
    assert all("role" not in player for player in state["players"])
    assert all(event["kind"] != "REVEAL" for event in state["public_events"])
    assert all(player["resolve"] == MAX_RESOLVE for player in state["players"])


def test_pass_is_free_when_human_turn_arrives():
    session = make_session(seed=9)
    state = session.handle({"type": "CONTINUE"})
    for _ in range(50):
        state = advance_nonchoice_interrupts(session, state)
        if state["phase"] == "DISCUSSION":
            break
        if state["phase"] == "TEAM_DRAFT":
            team = [p["id"] for p in state["players"][: state["team_size"]]]
            state = session.handle({"type": "SUBMIT_TEAM", "team": team})
        else:
            raise AssertionError(state["phase"])
    assert state["phase"] == "DISCUSSION"
    before = next(p["resolve"] for p in state["players"] if p["is_human"])
    state = session.handle({"type": "DISCUSSION", "action": "PASS"})
    after = next(p["resolve"] for p in state["players"] if p["is_human"])
    assert before == after


def test_challenge_decline_is_free_and_response_costs_one():
    session = make_session(seed=9)
    session.pending = "CHALLENGE_RESPONSE"
    session.challenge_trigger = {"seq": 99, "kind": "CHALLENGE", "text": "ATLAS challenged YOU"}
    before = session.resolve[session.human_id]
    # Keep the engine in a non-advancing state after response for this focused cost test.
    session._advance = lambda: None
    state = session.handle({"type": "CHALLENGE_RESPONSE", "action": "DECLINE"})
    assert session.resolve[session.human_id] == before
    assert state["challenge_trigger"] is None


def test_full_match_can_be_completed_through_ui_commands_only():
    session = make_session(seed=4)
    state = session.state()
    for _ in range(300):
        phase = state["phase"]
        if phase == "GAME_OVER":
            break
        if phase == "ROLE_REVEAL":
            state = session.handle({"type": "CONTINUE"})
        elif phase == "TEAM_DRAFT":
            ids = [p["id"] for p in state["players"]]
            state = session.handle({"type": "SUBMIT_TEAM", "team": ids[: state["team_size"]]})
        elif phase == "DISCUSSION":
            state = session.handle({"type": "DISCUSSION", "action": "PASS"})
        elif phase == "REACTION":
            state = session.handle({"type": "REACTION", "action": "KEEP_WAITING"})
        elif phase == "CHALLENGE_RESPONSE":
            state = session.handle({"type": "CHALLENGE_RESPONSE", "action": "DECLINE"})
        elif phase == "TEAM_CONFIRM":
            state = session.handle({"type": "TEAM_CONFIRM", "action": "LOCK_TEAM"})
        elif phase == "VOTE":
            state = session.handle({"type": "VOTE", "approve": True, "strong": False})
        elif phase == "MISSION":
            state = session.handle({"type": "MISSION", "card": "SUCCESS"})
        elif phase == "ROUND_RESULT":
            state = session.handle({"type": "CONTINUE"})
        elif phase == "ASSASSINATION":
            state = session.handle({"type": "ASSASSINATE", "target": state["assassination_targets"][0]})
        else:
            raise AssertionError(f"Unexpected UI phase: {phase}")
    assert state["phase"] == "GAME_OVER"
    assert state["game_result"]["winner"] in {"GOOD", "EVIL"}


def test_resolve_refreshes_after_mission_resolution():
    session = make_session(seed=11)
    state = session.handle({"type": "CONTINUE"})
    for _ in range(60):
        state = advance_nonchoice_interrupts(session, state)
        if state["phase"] == "DISCUSSION":
            break
        if state["phase"] == "TEAM_DRAFT":
            ids = [p["id"] for p in state["players"]]
            state = session.handle({"type": "SUBMIT_TEAM", "team": ids[: state["team_size"]]})
    assert state["phase"] == "DISCUSSION"
    target = next(p["id"] for p in state["players"] if not p["is_human"])
    state = session.handle({
        "type": "DISCUSSION",
        "action": "SOCIAL",
        "card": "HEDGE",
        "target": target,
        "commit": False,
    })
    spent = next(p["resolve"] for p in state["players"] if p["is_human"])
    assert spent == MAX_RESOLVE - 1

    for _ in range(150):
        phase = state["phase"]
        if phase == "ROUND_RESULT":
            break
        if phase == "DISCUSSION":
            state = session.handle({"type": "DISCUSSION", "action": "PASS"})
        elif phase == "REACTION":
            state = session.handle({"type": "REACTION", "action": "KEEP_WAITING"})
        elif phase == "CHALLENGE_RESPONSE":
            state = session.handle({"type": "CHALLENGE_RESPONSE", "action": "DECLINE"})
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
    assert all(player["resolve"] == MAX_RESOLVE for player in state["players"])
