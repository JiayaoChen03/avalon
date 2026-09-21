"""Small, deterministic boundaries for the v2.3 Merlin action aid."""
from copy import deepcopy
import json

from avalon.engine import Game, make_players
from avalon.eval.simulation import digest, policy_context
from avalon.eval.v2.adapters import make_version
from avalon.eval.v2.v21_contract import enrich_context, menu_context, POLICY_CURRENT, legal_menu
from avalon.eval.v2.v23_merlin import (MERLIN_DISCLOSURE_REVISION,
    build_merlin_disclosure_context, menu_context_v23)


def _merlin_context(seed=23101):
    game = Game(make_players(5, seed), seed=seed)
    merlin = next(p.id for p in game.players.values() if p.role == "MERLIN")
    game.propose(game.leader, game.ids[:game.team_size])
    while game.next_actor != merlin:
        game.act(game.next_actor, {"kind": "PASS"})
    observer = make_version("joint_v2", game.view(merlin))
    context = enrich_context(policy_context(game.view(merlin), observer), observer)
    context["public_event_history"] = [e for e in game.events if e["kind"] in {
        "TEAM", "PASS", "SOCIAL", "VOTE", "TEAM_VOTE", "MISSION"}]
    return game, context


def test_disabled_context_is_byte_identical_and_menu_unchanged():
    _, context = _merlin_context()
    base = menu_context(context, POLICY_CURRENT)
    assert menu_context_v23(context, POLICY_CURRENT, enabled=False) == base
    assert "merlin_disclosure_context" not in base
    enabled = menu_context_v23(context, POLICY_CURRENT, enabled=True)
    assert enabled["action_menu"] == base["action_menu"]
    assert enabled["response_contract"] == base["response_contract"]
    assert digest(context) == digest(context)


def test_only_merlin_public_social_phases_receive_aid():
    _, context = _merlin_context(23102)
    aid = build_merlin_disclosure_context(context)
    assert aid["status"] == "decision_aid_not_assassination_probability"
    assert aid["scope"] == "current_public_social_action_only"
    other = deepcopy(context)
    other["view"]["role"] = "GOOD"
    assert build_merlin_disclosure_context(other) is None
    other = deepcopy(context)
    other["view"]["phase"] = "vote"
    assert build_merlin_disclosure_context(other) is None
    other = deepcopy(context)
    other["view"]["phase"] = "assassination"
    assert build_merlin_disclosure_context(other) is None


def test_failed_team_is_set_constraint_and_success_is_not_clean_proof():
    _, context = _merlin_context(23103)
    events = context["public_event_history"]
    events.append({"record_id": "R1-999", "seq": 999, "round": 1, "attempt": 1,
                   "kind": "MISSION", "team": ["P1", "P2"], "success": False,
                   "fail_count": 1, "fail_threshold": 1})
    events.append({"record_id": "R2-999", "seq": 1000, "round": 2, "attempt": 1,
                   "kind": "MISSION", "team": ["P1", "P2"], "success": True,
                   "fail_count": 0, "fail_threshold": 1})
    aid = build_merlin_disclosure_context(context)
    failed = next(x for x in aid["public_support"] if x["event_ids"] == ["R1-999"])
    success = next(x for x in aid["public_support"] if x["event_ids"] == ["R2-999"])
    assert "至少有一名坏阵营成员" in failed["claim"]
    assert failed["does_not_establish"] == "任一特定成员的确定身份"
    assert success["does_not_establish"] == "全队好人或任一成员的确定身份"
    assert "确定身份" not in failed["claim"]


def test_claims_are_public_records_and_hidden_fields_do_not_flow():
    _, context = _merlin_context(23104)
    base = build_merlin_disclosure_context(context)
    hidden = deepcopy(context)
    hidden["referee_truth"] = {"P1": "ASSASSIN"}
    hidden["assassin_internal_posterior"] = {"P1": 1.0}
    hidden["future_events"] = [{"kind": "RESULT", "winner": "EVIL"}]
    assert build_merlin_disclosure_context(hidden) == base
    payload = json.dumps(base, ensure_ascii=False)
    assert "ASSASSIN" not in payload and "referee_truth" not in payload
    assert all(c["claim_status"] == "public_claim_not_role_fact" for c in base["public_claims"])
    assert all(c["event_id"].startswith("R") for c in base["public_claims"])


def test_aid_does_not_change_private_belief_or_legal_action_space():
    _, context = _merlin_context(23105)
    before = (context["posterior_hash"], legal_menu(context["view"]))
    on = menu_context_v23(context, POLICY_CURRENT, enabled=True)
    assert (context["posterior_hash"], legal_menu(context["view"])) == before
    assert on["action_menu"] == menu_context(context, POLICY_CURRENT)["action_menu"]
    assert MERLIN_DISCLOSURE_REVISION == "merlin-disclosure-v23-r1"
