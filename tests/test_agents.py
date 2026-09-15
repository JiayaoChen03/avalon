from copy import deepcopy
import json
import unittest

from avalon.agents import Agent, validate_plan
from avalon.llm import LLMError
from test_engine import fixed_game


class FixedClient:
    """The only fake boundary is the external model response."""
    def __init__(self, response=None, error=None):
        self.response, self.error = response, error
        self.contexts = []

    def complete(self, context):
        self.contexts.append(deepcopy(context))
        if self.error:
            raise self.error
        return deepcopy(self.response)


def valid_plan(view):
    ids = [p["id"] for p in view["players"]]
    return {
        "beliefs": {p: {"evil": 0.3, "merlin": 0.2} for p in ids},
        "profiles": {p: {"aggression": 0.4, "retaliation": 0.3,
                         "approval": 0.5, "consensus": 0.5} for p in ids},
        "strategy": "probe", "team_rank": list(reversed(ids)),
        "vote_threshold": 0.9, "approve_last": True, "mission": "FAIL",
        "social": {"card": "BAIT", "target": "P1", "reason": "test_reaction"},
        "assassin_rank": ids,
    }


class AgentTests(unittest.TestCase):
    def test_one_call_per_mission_even_on_reproposals_and_assassination(self):
        game = fixed_game()
        view = game.view("P3")
        client = FixedClient(valid_plan(view))
        agent = Agent(view, client)
        for attempt in range(1, 6):
            view["attempt"] = attempt
            agent.prepare(view)
            agent.choose_team(2, attempt)
            agent.social_action()
            agent.vote(["P1", "P3"], attempt)
            agent.mission()
        agent.assassinate()
        self.assertEqual(agent.calls, {1: 1})
        self.assertEqual(len(client.contexts), 1)
        view["round"] = 2
        agent.prepare(view)
        self.assertEqual(agent.calls, {1: 1, 2: 1})
        self.assertEqual(agent.social_action()["card"], "BAIT")

    def test_invalid_or_failed_api_falls_back_once(self):
        view = fixed_game().view("P1")
        for client in (FixedClient(error=LLMError("http_401")), FixedClient({"bad": 1})):
            agent = Agent(view, client)
            self.assertTrue(agent.prepare(view).startswith("fallback"))
            agent.prepare(view)
            self.assertEqual(agent.calls, {1: 1})
            self.assertEqual(len(agent.choose_team(2)), 2)
            self.assertEqual(agent.mission(), "SUCCESS")

    def test_known_facts_cannot_be_overwritten_by_model(self):
        view = fixed_game().view("P2")
        agent = Agent(view, FixedClient(valid_plan(view)))
        agent.prepare(view)
        self.assertEqual(agent.memory["beliefs"]["P3"]["evil"], 1.0)
        self.assertEqual(agent.memory["beliefs"]["P1"]["evil"], 0.0)
        self.assertEqual(agent.memory["beliefs"]["P2"]["merlin"], 1.0)
        self.assertEqual(agent.mission(), "SUCCESS")

    def test_private_memories_and_request_context_are_isolated(self):
        game = fixed_game()
        one = Agent(game.view("P1"))
        two = Agent(game.view("P5"))
        before = deepcopy(two.memory)
        one.memory["profiles"]["P3"]["aggression"] = 0.99
        self.assertEqual(two.memory, before)
        client = FixedClient(valid_plan(game.view("P5")))
        two.client = client
        two.prepare(game.view("P5"))
        sent = client.contexts[0]
        self.assertEqual(sent["game"]["known_evil"], [])
        self.assertNotIn("role", json.dumps(sent["game"]["players"]))
        self.assertLessEqual(len(sent["game"]["recent_events"]), 20)
        self.assertNotIn("0.99", json.dumps(sent["memory"]))

    def test_observations_change_beliefs_profiles_and_vote(self):
        game = fixed_game()
        agent = Agent(game.view("P1"))
        agent.prepare(game.view("P1"))
        agent.plan["vote_threshold"] = 0.49
        before = agent.memory["beliefs"]["P3"]["evil"]
        for seq in range(1, 4):
            agent.observe({"seq": seq, "kind": "MISSION", "round": seq,
                           "team": ["P3", "P4"], "success": False, "fail_count": 1})
        self.assertGreater(agent.memory["beliefs"]["P3"]["evil"], before)
        self.assertFalse(agent.vote(["P3", "P4"], 1))
        agent.observe({"seq": 4, "kind": "SOCIAL", "round": 3, "actor": "P2",
                       "target": "P1", "card": "PRESSURE"})
        agent.observe({"seq": 5, "kind": "SOCIAL", "round": 3, "actor": "P1",
                       "target": "P2", "card": "ACCUSE"})
        self.assertGreater(agent.memory["profiles"]["P1"]["retaliation"], 0.5)
        self.assertGreater(agent.memory["profiles"]["P1"]["aggression"], 0.5)
        snapshot = deepcopy(agent.memory)
        agent.observe({"seq": 5, "kind": "SOCIAL", "round": 3, "actor": "P1",
                       "target": "P2", "card": "ACCUSE"})
        self.assertEqual(agent.memory, snapshot)

    def test_plan_rejects_invalid_numbers_ids_and_free_text(self):
        view = fixed_game().view("P1")
        valid = valid_plan(view)
        bad_plans = []
        for field, value in (("vote_threshold", float("nan")), ("vote_threshold", True),
                             ("vote_threshold", 10 ** 400),
                             ("approve_last", "true"), ("team_rank", ["P1"] * 5),
                             ("strategy", "secret chain of thought")):
            bad = deepcopy(valid)
            bad[field] = value
            bad_plans.append(bad)
        bad = deepcopy(valid)
        bad["social"]["reason"] = "I know P3 is EVIL"
        bad_plans.append(bad)
        bad = deepcopy(valid)
        bad["chain_of_thought"] = "private"
        bad_plans.append(bad)
        bad = deepcopy(valid)
        bad["beliefs"]["P1"]["evil"] = float("inf")
        bad_plans.append(bad)
        for bad in bad_plans:
            with self.assertRaises(ValueError):
                validate_plan(bad, [p["id"] for p in view["players"]])

    def test_mock_is_reproducible_and_assassin_has_legal_target(self):
        view = fixed_game().view("P3")
        one, two = Agent(view), Agent(view)
        one.prepare(view)
        two.prepare(view)
        self.assertEqual(one.plan, two.plan)
        self.assertEqual(one.calls, {})
        self.assertIn(one.assassinate(), ["P1", "P2", "P5"])


if __name__ == "__main__":
    unittest.main()
