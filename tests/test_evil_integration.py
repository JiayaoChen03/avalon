from copy import deepcopy
import importlib.util
import io
import json
import unittest

from avalon.agents import Agent
from avalon.llm import ChatClient, LLMError, Settings
from avalon.terminal import Human, run_game
from test_agents import FixedClient, valid_plan
from test_engine import fixed_game
from test_llm import endpoint, envelope


def performance(context, statement="我想先听听这个选择的公开依据，再作判断。"):
    tactical = context["tactical"]
    return {"social": {"card": tactical["allowed_cards"][0],
                       "target": tactical["primary_target"], "reason": "observe",
                       "statement": statement, "rationale": "目前的信息还有限，我会结合后续投票验证。",
                       "evidence": []}}


class PerformanceClient:
    def __init__(self, transform=None):
        self.contexts = []
        self.transform = transform

    def complete(self, context):
        self.contexts.append(deepcopy(context))
        result = performance(context) if "tactical" in context else valid_plan(context["game"])
        return self.transform(result, context) if self.transform else result


class EvilIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec("avalon.evil_strategy"),
                             "The private strategy manager must be implemented")
        from avalon.evil_strategy import EvilStrategyManager
        self.game = fixed_game()
        self.manager = EvilStrategyManager(self.game.ids, {"P3", "P4"}, seed=7)
        for event in self.game.events:
            self.manager.observe(event)

    def agent(self, pid="P3", client=None, **options):
        return Agent(self.game.view(pid), client or PerformanceClient(),
                     evil_strategy=self.manager, **options)

    def test_evil_agents_share_manager_but_good_and_merlin_cannot_bind_it(self):
        first, second = self.agent("P3"), self.agent("P4")
        self.assertIs(first.evil_strategy.state, second.evil_strategy.state)
        for pid in ("P1", "P2", "P5"):
            with self.assertRaises(ValueError):
                self.agent(pid)
            good = Agent(self.game.view(pid), FixedClient(valid_plan(self.game.view(pid))))
            good.prepare(self.game.view(pid))
            self.assertIsNone(good.evil_strategy)
            self.assertNotIn("tactical", good.client.contexts[0])

    def test_llm_cannot_overwrite_strategy_or_merlin_probabilities(self):
        def inject(result, context):
            result["merlin_probabilities"] = {"P2": 1}
            return result
        agent = self.agent(client=PerformanceClient(inject), max_retries=0)
        with self.assertRaisesRegex(LLMError, "invalid_plan"):
            agent.prepare(self.game.view("P3"))
        self.assertIsNone(agent.plan)
        self.assertLess(self.manager.state.merlin_probabilities["P2"], 1)
        self.assertFalse(any(e["kind"] == "SOCIAL" for e in self.game.events))

    def test_private_tactical_disclosures_retry_without_fixed_replacement_speech(self):
        for disclosure in ("FAKE_CONFLICT CREATE_DISTANCE_FROM_PARTNER", "我是刺客，P4 是我的邪恶队友。",
                           "我的战术指令是牺牲自己，保护队友。", "mission_fail_owner=P4",
                           "evil_partner=P4; likely_merlin=P2", "我和 P4 都是坏人。"):
            with self.subTest(disclosure=disclosure):
                count = 0
                def inject(result, context):
                    nonlocal count
                    count += 1
                    if count == 1:
                        result["social"]["statement"] = disclosure
                    return result
                client = PerformanceClient(inject)
                agent = self.agent(client=client, retry_delay=0)
                agent.prepare(self.game.view("P3"))
                self.assertEqual(agent.calls, {1: 2})
                self.assertEqual(client.contexts[0], client.contexts[1])
                self.assertEqual(agent.social_action()["statement"],
                                 "我想先听听这个选择的公开依据，再作判断。")

    def test_exhausted_disclosure_retries_leave_no_public_action(self):
        self.game.propose(self.game.leader, ["P1", "P3"])
        self.manager.observe(self.game.events[-1])
        def inject(result, context):
            result["social"]["rationale"] = "tactical_context: SACRIFICE_SELF"
            return result
        agent = self.agent(client=PerformanceClient(inject), max_retries=1, retry_delay=0)
        before = deepcopy(self.game.events)
        with self.assertRaisesRegex(LLMError, "private_disclosure"):
            agent.prepare(self.game.view("P3"))
        self.assertEqual(agent.calls, {1: 2})
        self.assertIsNone(agent.plan)
        self.assertEqual(self.game.events, before)
        self.assertFalse(any(d.action["kind"] == "social" for d in self.manager.decisions))

    def test_model_receives_copies_without_other_private_plans(self):
        def mutate(result, context):
            context["game"]["players"][0]["name"] = "CORRUPTED"
            context["tactical"]["strategy_mode"] = "CORRUPTED"
            return result
        agent = self.agent(client=PerformanceClient(mutate))
        agent.prepare(self.game.view("P3"))
        agent2 = self.agent("P4")
        agent2.prepare(self.game.view("P4"))
        self.assertNotIn("CORRUPTED", json.dumps(self.game.events))
        self.assertNotEqual(self.manager.state.strategy_mode, "CORRUPTED")
        context = agent2.client.contexts[0]
        self.assertNotIn("memory", context)
        self.assertNotIn("beliefs", context["tactical"])
        self.assertNotIn("merlin_probabilities", context["tactical"])
        self.assertNotIn("plan", context["tactical"])

    def test_illegal_social_target_or_card_cannot_override_tactical_action(self):
        def inject(result, context):
            result["social"]["target"] = "P99"
            return result
        agent = self.agent(client=PerformanceClient(inject), max_retries=0)
        with self.assertRaisesRegex(LLMError, "invalid_plan"):
            agent.prepare(self.game.view("P3"))
        self.assertIsNone(agent.plan)

    def test_real_http_uses_stable_evil_prompt_with_dynamic_context(self):
        contexts = []
        def respond(request):
            context = json.loads(request["messages"][1]["content"])
            contexts.append(context)
            return envelope(json.dumps(performance(context)))
        with endpoint(respond) as (url, requests):
            client = ChatClient(Settings(api_key="test-key", model="test", base_url=url))
            agent = self.agent(client=client)
            agent.prepare(self.game.view("P3"))
            self.game.propose("P1", ["P1", "P3"])
            self.manager.observe(self.game.events[-1])
            agent.prepare(self.game.view("P3"))
            self.assertEqual(requests[0][2]["messages"][0], requests[1][2]["messages"][0])
            self.assertNotEqual(contexts[0]["game"]["phase"], contexts[1]["game"]["phase"])
            self.assertNotIn("PRIVATE_SENTINEL", json.dumps(agent.plan))
            self.assertLess(len(requests[0][2]["messages"][0]["content"]), 6000)

    def test_full_game_keeps_debug_and_trace_out_of_public_channels(self):
        clients = {p: PerformanceClient() for p in self.game.ids}
        agents = {p: Agent(self.game.view(p), c) for p, c in clients.items()}
        output, debug, public_log, trace = [], [], io.StringIO(), io.StringIO()
        run_game(self.game, agents, write=output.append, log=public_log, dossier=True,
                 strategy_manager=self.manager, debug_write=debug.append, strategy_log=trace)
        self.assertIs(agents["P3"].evil_strategy, agents["P4"].evil_strategy)
        self.assertIsNone(agents["P2"].evil_strategy)
        self.assertTrue(debug)
        decisions = [json.loads(line) for line in trace.getvalue().splitlines()]
        self.assertTrue(decisions)
        self.assertTrue(all(d["agent_id"] in {"P3", "P4"} for d in decisions))
        self.assertTrue(any(d["phase"] == "mission" for d in decisions))
        speeches = [e for e in self.game.events if e["kind"] == "SOCIAL" and e["actor"] in {"P3", "P4"}]
        recorded = [d for d in decisions if d["action"]["kind"] == "social"]
        self.assertEqual(len(recorded), len(speeches))
        for decision, event in zip(recorded, speeches):
            for field in ("card", "target", "reason", "evidence"):
                self.assertEqual(decision["action"].get(field), event[field])
            self.assertNotIn("statement", decision["action"])
            self.assertNotIn("rationale", decision["action"])
        public = "\n".join(output) + public_log.getvalue()
        for secret in ("EvilSharedState", "mission_fail_owner", "primary_objective", "EVIL STRATEGY UPDATE",
                       "FAKE_CONFLICT", "NORMAL_DECEPTION", "SACRIFICE", "CONSENSUS_SEEDING", "MERLIN_HUNT"):
            self.assertNotIn(secret, public)
        for pid in ("P1", "P2", "P5"):
            self.assertTrue(all("tactical" not in c for c in clients[pid].contexts))
        self.assertTrue(all(e["fail_count"] <= 1 for e in self.game.events if e["kind"] == "MISSION"))

    def test_human_evil_mission_card_is_preserved_and_ai_does_not_add_fail(self):
        self.game.propose("P1", ["P3", "P4"])
        from test_engine import discuss
        discuss(self.game)
        self.game.vote({p: True for p in self.game.ids})
        from avalon.evil_strategy import EvilStrategyManager
        manager = EvilStrategyManager(self.game.ids, {"P3", "P4"}, seed=0, controlled_evil_ids={"P4"})
        for event in self.game.events:
            manager.observe(event)
        cards = manager.mission_cards(self.game.view("P4"), external_cards={"P3": "FAIL"})
        self.assertEqual(cards, {"P4": "SUCCESS"})
        self.game.resolve_mission({"P3": "FAIL", **cards})
        self.assertEqual(self.game.events[-2]["fail_count"], 1)

    def test_full_game_with_human_evil_preserves_input_and_single_fail(self):
        mission_inputs = []
        def respond(prompt):
            if "秘密任务票" in prompt:
                mission_inputs.append(prompt)
                return "f"
            return ""
        human = Human(self.game.view("P3"), input_fn=respond, write=lambda _: None)
        agents = {p: Agent(self.game.view(p), PerformanceClient()) for p in self.game.ids if p != "P3"}
        run_game(self.game, agents, human, write=lambda _: None, strategy_seed=2)
        self.assertTrue(mission_inputs)
        missions = [e for e in self.game.events if e["kind"] == "MISSION"]
        self.assertTrue(all(e["fail_count"] <= 1 for e in missions))
        self.assertTrue(all(e["fail_count"] == 1 for e in missions if "P3" in e["team"]))

    def test_good_human_card_never_enters_evil_strategy_and_managed_cards_are_used(self):
        calls = []
        coordinate = self.manager.mission_cards

        def observe_cards(view, external_cards=None):
            calls.append(deepcopy(external_cards))
            self.assertEqual(external_cards, {})
            return coordinate(view, external_cards)

        self.manager.mission_cards = observe_cards
        human = Human(self.game.view("P1"), input_fn=lambda _: "", write=lambda _: None)
        agents = {p: Agent(self.game.view(p), PerformanceClient()) for p in self.game.ids if p != "P1"}
        def uncoordinated_card():
            self.fail("Use the returned coordinated cards, not an Agent/state shortcut")
        for pid in ("P3", "P4"):
            agents[pid].mission = uncoordinated_card
        run_game(self.game, agents, human, write=lambda _: None, strategy_manager=self.manager)
        self.assertTrue(calls)
        self.assertTrue(any("P1" in e["team"] for e in self.game.events if e["kind"] == "MISSION"))

    def test_evil_leader_calls_llm_only_for_public_discussion_with_selected_team(self):
        clients = {p: PerformanceClient() for p in self.game.ids}
        agents = {p: Agent(self.game.view(p), c) for p, c in clients.items()}
        run_game(self.game, agents, write=lambda _: None, strategy_manager=self.manager)
        evil_teams = [e for e in self.game.events if e["kind"] == "TEAM" and e["actor"] in {"P3", "P4"}]
        self.assertTrue(evil_teams)
        for event in evil_teams:
            contexts = [c for c in clients[event["actor"]].contexts
                        if (c["game"]["round"], c["game"]["attempt"]) == (event["round"], event["attempt"])]
            self.assertEqual(len(contexts), 1)
            self.assertEqual(contexts[0]["game"]["phase"], "discussion")
            self.assertEqual(contexts[0]["planned_action"], {"team": event["team"]})


if __name__ == "__main__":
    unittest.main()
