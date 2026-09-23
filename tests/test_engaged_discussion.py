"""Local engaged discussion is a model-output policy, never an action repair."""

from copy import deepcopy
import unittest
from unittest.mock import patch

from avalon.agents import Agent
from avalon.engine import Player
from avalon.evil_strategy import EvilStrategyManager
from avalon.gui import GameSession
from avalon.llm import LLMError
from test_agents import valid_plan
from test_engine import fixed_game


PUBLIC_LINE = "这支队伍值得先讨论，我会观察每个人公开给出的理由。"


def discussion_game(actor="P1", *, council=False, zero_resolve=False):
    game = fixed_game()
    game.propose(game.leader, ["P1", "P3"])
    if council:
        game.phase = "council_discussion"
        game.discussion_stage = "council"
    for pid in game.speaking_order:
        if pid == actor:
            break
        game.act(pid, {"kind": "PASS"})
    if zero_resolve:
        game.resolve[actor] = 0
    return game


def modern_response(context, kind="SOCIAL", *, draft=False, bad_target=False,
                    private_disclosure=False):
    ids = [p["id"] for p in context["game"]["players"]]
    actor = context["game"]["self"]
    tactical = context.get("tactical")
    target = (tactical["primary_target"] if tactical else
              next(pid for pid in ids if pid != actor))
    if bad_target:
        target = next(pid for pid in ids if pid != target)
    social = {
        "card": tactical["allowed_cards"][0] if tactical else "HEDGE",
        "target": target, "reason": "observe",
        "public_writing": "我是刺客。" if private_disclosure else PUBLIC_LINE,
        "citations": [],
    }
    if tactical:
        action = {"social": social if kind == "SOCIAL" or draft else None,
                  "discussion": {"kind": kind}, "revision": {"kind": "LOCK"},
                  "strong_vote": False}
    else:
        action = valid_plan(context["game"])
        action.pop("beliefs")
        action.pop("profiles")
        action.update(mission="SUCCESS",
                      social=social if kind == "SOCIAL" or draft else None,
                      discussion={"kind": kind}, revision={"kind": "LOCK"},
                      strong_vote=False)
    return {"belief_updates": [], "interpretation": [],
            "public_stance_change": None, "recommended_action": action,
            "short_rationale": "根据当前公开信息选择本次合法行动。"}


class ScriptedClient:
    def __init__(self, steps):
        self.steps = list(steps)
        self.contexts = []

    def complete(self, context):
        self.contexts.append(deepcopy(context))
        if context["game"]["phase"] == "team":
            return modern_response(context)
        if not self.steps:
            raise AssertionError("Unexpected model call")
        step = self.steps.pop(0)
        return modern_response(context, **step)


def acting_agent(game, pid, client, *, policy="engaged_v1", retries=1):
    view = game.view(pid)
    manager = None
    if pid in {"P3", "P4"}:
        manager = EvilStrategyManager(game.ids, {"P3", "P4"}, seed=0)
        for event in game.events:
            manager.observe(event)
    return Agent(view, client, evil_strategy=manager, max_retries=retries,
                 retry_delay=0, discussion_policy=policy)


class EngagedDiscussionTests(unittest.TestCase):
    def test_all_role_paths_retry_authored_pass_then_publish_authored_social(self):
        for pid, role in (("P1", "GOOD"), ("P2", "MERLIN"),
                          ("P3", "ASSASSIN"), ("P4", "EVIL")):
            with self.subTest(role=role):
                game = discussion_game(pid)
                self.assertEqual(game.players[pid].role, role)
                client = ScriptedClient([{"kind": "PASS"}, {"kind": "SOCIAL"}])
                agent = acting_agent(game, pid, client)
                before = deepcopy(game.events)

                self.assertEqual(agent.prepare(game.view(pid)), "llm")
                self.assertEqual(game.events, before)
                self.assertEqual(agent.calls[1], 2)
                self.assertIn("validation_feedback", client.contexts[1])
                self.assertIn("SOCIAL", client.contexts[0]["current_turn_instruction"])
                action_schema = client.contexts[0]["response_contract"]["schema"]["properties"]["recommended_action"]
                self.assertEqual(action_schema["properties"]["discussion"]["properties"]["kind"],
                                 {"const": "SOCIAL"})
                if pid in {"P3", "P4"}:
                    self.assertEqual(action_schema["properties"]["social"]["properties"]["target"]["enum"],
                                     [client.contexts[0]["tactical"]["primary_target"]])
                self.assertEqual(agent.discussion_action()["kind"], "SOCIAL")
                game.act(pid, agent.discussion_action())
                self.assertEqual(game.events[-1]["kind"], "SOCIAL")
                self.assertEqual(game.events[-1]["public_writing"], PUBLIC_LINE)

    def test_pass_with_unused_social_draft_is_rejected_without_publication(self):
        game = discussion_game()
        client = ScriptedClient([{"kind": "PASS", "draft": True}])
        agent = acting_agent(game, "P1", client, retries=0)
        before = deepcopy(game.events)

        with self.assertRaisesRegex(LLMError, "invalid_plan"):
            agent.prepare(game.view("P1"))
        self.assertEqual(game.events, before)
        self.assertIsNone(agent.plan)
        self.assertEqual(agent.plans, {})

    def test_zero_resolve_accepts_null_social_pass(self):
        game = discussion_game(zero_resolve=True)
        self.assertEqual(game.view("P1")["legal_actions"], ["PASS"])
        client = ScriptedClient([{"kind": "PASS"}])
        agent = acting_agent(game, "P1", client, retries=0)

        self.assertEqual(agent.prepare(game.view("P1")), "llm")
        self.assertEqual(agent.discussion_action(), {"kind": "PASS"})
        game.act("P1", agent.discussion_action())
        self.assertEqual(game.events[-1]["kind"], "PASS")
        self.assertEqual(game.events[-1]["resolve_after"], 0)

    def test_council_discussion_uses_same_engagement_policy(self):
        game = discussion_game(council=True)
        client = ScriptedClient([{"kind": "PASS"}, {"kind": "SOCIAL"}])
        agent = acting_agent(game, "P1", client)

        agent.prepare(game.view("P1"))
        self.assertEqual(agent.calls[1], 2)
        self.assertEqual(agent.discussion_action()["kind"], "SOCIAL")
        game.act("P1", agent.discussion_action())
        self.assertEqual(game.events[-1]["kind"], "SOCIAL")
        self.assertEqual(game.events[-1]["discussion_stage"], "council")

    def test_retry_exhaustion_keeps_public_events_and_plan_cache_unchanged(self):
        game = discussion_game()
        client = ScriptedClient([{"kind": "PASS"}, {"kind": "PASS"}])
        agent = acting_agent(game, "P1", client)
        before = deepcopy(game.events)

        with self.assertRaisesRegex(LLMError, "invalid_plan"):
            agent.prepare(game.view("P1"))
        self.assertEqual(agent.calls[1], 2)
        self.assertEqual(game.events, before)
        self.assertIsNone(agent.plan)
        self.assertEqual(agent.plans, {})
        self.assertFalse(any(event["kind"] == "SOCIAL" for event in game.events))

    def test_tactical_and_privacy_validation_still_reject_authored_social(self):
        for step, code in (({"kind": "SOCIAL", "bad_target": True}, "invalid_plan"),
                           ({"kind": "SOCIAL", "private_disclosure": True}, "private_disclosure")):
            with self.subTest(code=code):
                game = discussion_game("P3")
                client = ScriptedClient([step])
                agent = acting_agent(game, "P3", client, retries=0)
                before = deepcopy(game.events)
                with self.assertRaisesRegex(LLMError, code):
                    agent.prepare(game.view("P3"))
                self.assertEqual(game.events, before)
                self.assertEqual(agent.plans, {})

    def test_baseline_default_still_accepts_affordable_pass(self):
        game = discussion_game()
        client = ScriptedClient([{"kind": "PASS"}])
        agent = Agent(game.view("P1"), client, max_retries=0)

        self.assertEqual(agent.prepare(game.view("P1")), "llm")
        self.assertEqual(agent.discussion_action(), {"kind": "PASS"})
        self.assertEqual(len(client.contexts), 1)
        self.assertNotIn("current_turn_instruction", client.contexts[0])
        self.assertNotIn("response_contract", client.contexts[0])

    def test_restart_keeps_engaged_policy_without_fabricating_speech(self):
        client = ScriptedClient([{"kind": "PASS"}, {"kind": "PASS"},
                                 {"kind": "PASS"}, {"kind": "SOCIAL"}])
        session = GameSession(lambda: client, discussion_policy="engaged_v1")
        players = [Player(f"P{i+1}", f"Seat{i+1}", role) for i, role in enumerate(
            ["MERLIN", "ASSASSIN", "EVIL", "GOOD", "GOOD", "GOOD"])]
        with patch("avalon.gui.make_players", return_value=players):
            session.start(6, 34)

        def command(name):
            return session.dispatch({"request_id": f"{name}-{session.revision}-{len(client.contexts)}",
                                     "revision": session.revision,
                                     "command": name, "payload": {}})

        self.assertTrue(command("continue")["ok"])
        self.assertTrue(command("advance")["ok"])
        self.assertEqual(session.game.phase, "discussion")
        self.assertEqual(session.game.next_actor, "P5")
        session.agents["P5"].max_retries = 1
        session.agents["P5"].retry_delay = 0
        session.agent_options.update(max_retries=1, retry_delay=0)
        public_before = deepcopy(session.snapshot()["public_events"])
        dialogue_before = deepcopy(session.snapshot()["dialogue"])
        revision_before = session.revision

        failed = command("advance")
        self.assertFalse(failed["ok"])
        self.assertEqual(session.revision, revision_before)
        self.assertEqual(failed["state"]["public_events"], public_before)
        self.assertEqual(failed["state"]["dialogue"], dialogue_before)
        self.assertNotIn((1, 1, "discussion"), session.agents["P5"].plans)

        recovered = command("restart_round")
        self.assertTrue(recovered["ok"], recovered["error"])
        self.assertEqual(session.game.events[-1]["kind"], "SOCIAL")
        self.assertEqual(session.game.events[-1]["public_writing"], PUBLIC_LINE)
        self.assertEqual(recovered["state"]["public_events"][:-1], public_before)
        self.assertEqual(len(recovered["state"]["dialogue"]), len(dialogue_before) + 1)


if __name__ == "__main__":
    unittest.main()
