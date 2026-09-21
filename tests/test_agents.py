from copy import deepcopy
import json
import unittest
from unittest.mock import call, patch

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
        if context.get("decision") in {"exile_nomination", "exile_vote"} and isinstance(self.response, dict) and "beliefs" in self.response:
            return model_response(context)
        if "tactical" in context and isinstance(self.response, dict) and set(self.response) == {
                "beliefs", "profiles", "strategy", "team_rank", "vote_threshold", "approve_last",
                "mission", "social", "assassin_rank"}:
            return model_response(context, self.response)
        return deepcopy(self.response)


class SequenceClient:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.contexts = []

    def complete(self, context):
        self.contexts.append(deepcopy(context))
        response = next(self.responses)
        if isinstance(response, BaseException):
            raise response
        return deepcopy(response)


def valid_plan(view):
    ids = [p["id"] for p in view["players"]]
    return {
        "beliefs": {p: {"evil": 0.3, "merlin": 0.2} for p in ids},
        "profiles": {p: {"aggression": 0.4, "retaliation": 0.3,
                         "approval": 0.5, "consensus": 0.5} for p in ids},
        "strategy": "probe", "team_rank": list(reversed(ids)),
        "vote_threshold": 0.9, "approve_last": True, "mission": "FAIL",
        "social": {"card": "BAIT", "target": "P1", "reason": "test_reaction",
                   "statement": "P1，请解释你对当前队伍的看法，我暂时保留判断。",
                   "rationale": "目前公开证据有限，需要结合发言与后续投票再判断。", "evidence": []},
        "assassin_rank": ids,
    }


def model_response(context, plan=None):
    """Provider fixture follows the separate good-policy and evil-performance protocols."""
    if context.get("decision") == "exile_nomination":
        return {"target": context["game"]["exile_candidates"][0]}
    if context.get("decision") == "exile_vote":
        return {"choice": "ABSTAIN"}
    plan = deepcopy(plan) if plan is not None else valid_plan(context["game"])
    if "tactical" not in context:
        return plan
    plan["social"]["target"] = context["tactical"]["primary_target"]
    plan["social"]["card"] = context["tactical"]["allowed_cards"][0]
    return {"social": plan["social"]}


class AgentTests(unittest.TestCase):
    def test_fresh_plan_for_each_proposal_and_speech_with_no_duplicate_requests(self):
        game = fixed_game()
        view = game.view("P3")
        client = FixedClient(valid_plan(view))
        agent = Agent(view, client)
        for attempt in range(1, 6):
            view["attempt"] = attempt
            view["phase"] = "team"
            agent.prepare(view)
            agent.choose_team(2, attempt)
            view["phase"] = "discussion"
            agent.prepare(view)
            agent.prepare(view)
            agent.social_action()
            agent.vote(["P1", "P3"], attempt)
            agent.mission()
        agent.assassinate()
        self.assertEqual(agent.calls, {1: 10})
        self.assertEqual(len(client.contexts), 10)
        view["round"] = 2
        agent.prepare(view)
        self.assertEqual(agent.calls, {1: 10, 2: 1})
        self.assertEqual(agent.social_action()["card"], "BAIT")

    def test_invalid_or_failed_api_stops_without_fabricating_a_plan(self):
        view = fixed_game().view("P1")
        for client, code in ((FixedClient(error=LLMError("http_401")), "http_401"),
                             (FixedClient({"bad": 1}), "invalid_plan")):
            agent = Agent(view, client, max_retries=0)
            memory = deepcopy(agent.memory)
            with self.assertRaisesRegex(LLMError, code):
                agent.prepare(view)
            self.assertEqual(agent.calls, {1: 1})
            self.assertIsNone(agent.plan)
            self.assertEqual(agent.plans, {})
            self.assertEqual(agent.memory, memory)

    def test_missing_client_never_creates_a_mock_plan(self):
        view = fixed_game().view("P1")
        agent = Agent(view)
        with self.assertRaisesRegex(LLMError, "missing_configuration"):
            agent.prepare(view)
        self.assertIsNone(agent.plan)
        self.assertEqual(agent.calls, {})

    def test_transient_errors_retry_the_same_turn_and_cache_only_success(self):
        view = fixed_game().view("P5")
        client = SequenceClient([LLMError("invalid_response"), LLMError("connection_error"), valid_plan(view)])
        agent = Agent(view, client)
        with patch("time.sleep") as sleep:
            try:
                self.assertEqual(agent.prepare(view), "llm")
            except LLMError as error:
                self.fail(f"A recoverable error should be retried: {error}")
            self.assertEqual(agent.calls, {1: 3})
            self.assertEqual(sleep.call_args_list, [call(2), call(4)])
        self.assertEqual(client.contexts[0], client.contexts[1])
        self.assertEqual(client.contexts[1], client.contexts[2])
        self.assertEqual(agent.social_action(), valid_plan(view)["social"])
        agent.prepare(view)
        self.assertEqual(agent.calls, {1: 3})

    def test_retry_exhaustion_leaves_private_state_and_plan_unchanged(self):
        view = fixed_game().view("P5")
        client = FixedClient({"bad": "PRIVATE_SENTINEL"})
        agent = Agent(view, client)
        memory = deepcopy(agent.memory)
        with patch("time.sleep") as sleep, self.assertRaisesRegex(LLMError, "invalid_plan"):
            agent.prepare(view)
        self.assertEqual(agent.calls, {1: 3})
        self.assertEqual(len(client.contexts), 3)
        self.assertEqual(sleep.call_args_list, [call(2), call(4)])
        self.assertIsNone(agent.plan)
        self.assertEqual(agent.plans, {})
        self.assertEqual(agent.memory, memory)

    def test_invalid_plan_retries_with_only_safe_validation_feedback(self):
        view = fixed_game().view("P5")
        contexts = []

        class RepairClient:
            def complete(self, context):
                contexts.append(deepcopy(context))
                if "validation_feedback" not in context:
                    return {"social.statement": "PRIVATE_SENTINEL"}
                return valid_plan(context["game"])

        agent = Agent(view, RepairClient(), retry_delay=0)
        errors = []
        agent.prepare(view, on_retry=lambda error, *_: errors.append(error))
        self.assertEqual(agent.calls, {1: 2})
        retried = deepcopy(contexts[1])
        feedback = retried.pop("validation_feedback")
        self.assertEqual(retried, contexts[0])
        self.assertIn("beliefs", feedback["rule"])
        self.assertIn("social", feedback["rule"])
        self.assertEqual(feedback["error"], "invalid_plan")
        self.assertNotIn("PRIVATE_SENTINEL", json.dumps(feedback))
        self.assertEqual(errors[0].diagnostic, "invalid_plan: Invalid plan keys")
        self.assertEqual(errors[0].public_code, "invalid_plan")
        self.assertEqual(agent.social_action(), valid_plan(view)["social"])

    def test_permanent_errors_do_not_retry(self):
        view = fixed_game().view("P5")
        for code in ("http_400", "http_401", "http_402", "http_403", "http_404", "http_422",
                     "refusal", "content_filtered", "missing_configuration"):
            with self.subTest(code=code), patch("time.sleep") as sleep:
                agent = Agent(view, FixedClient(error=LLMError(code)))
                with self.assertRaisesRegex(LLMError, code):
                    agent.prepare(view)
                self.assertEqual(agent.calls, {1: 1})
                self.assertEqual(sleep.call_args_list, [])

    def test_network_and_provider_failures_can_recover(self):
        view = fixed_game().view("P5")
        for code in ("timeout", "connection_error", "http_408", "http_429", "http_500", "http_502",
                     "http_503", "http_504", "empty_response", "truncated_response", "response_too_large"):
            with self.subTest(code=code), patch("time.sleep"):
                agent = Agent(view, SequenceClient([LLMError(code), valid_plan(view)]))
                try:
                    agent.prepare(view)
                except LLMError as error:
                    self.fail(f"A recoverable error should be retried: {error}")
                self.assertEqual(agent.calls, {1: 2})
                self.assertIsNotNone(agent.plan)

    def test_ctrl_c_during_retry_wait_stops_without_another_request(self):
        view = fixed_game().view("P5")
        agent = Agent(view, FixedClient(error=LLMError("timeout")))
        with patch("time.sleep", side_effect=KeyboardInterrupt), self.assertRaises(KeyboardInterrupt):
            agent.prepare(view)
        self.assertEqual(agent.calls, {1: 1})
        self.assertIsNone(agent.plan)

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
        agent = Agent(game.view("P1"), FixedClient(valid_plan(game.view("P1"))))
        agent.prepare(game.view("P1"))
        agent.plan["vote_threshold"] = 0.49
        before = agent.memory["beliefs"]["P3"]["evil"]
        start = agent.seen_seq + 1
        for seq in range(start, start + 3):
            agent.observe({"seq": seq, "kind": "MISSION", "round": seq,
                           "team": ["P3", "P4"], "success": False, "fail_count": 1})
        self.assertGreater(agent.memory["beliefs"]["P3"]["evil"], before)
        self.assertFalse(agent.vote(["P3", "P4"], 1))
        profile_before = deepcopy(agent.memory["profiles"]["P1"])
        agent.observe({"seq": start + 3, "kind": "SOCIAL", "round": 3, "actor": "P2",
                       "target": "P1", "card": "PRESSURE"})
        agent.observe({"seq": start + 4, "kind": "SOCIAL", "round": 3, "actor": "P1",
                       "target": "P2", "card": "ACCUSE"})
        self.assertGreater(agent.memory["profiles"]["P1"]["retaliation"], profile_before["retaliation"])
        self.assertGreater(agent.memory["profiles"]["P1"]["aggression"], profile_before["aggression"])
        snapshot = deepcopy(agent.memory)
        agent.observe({"seq": start + 4, "kind": "SOCIAL", "round": 3, "actor": "P1",
                       "target": "P2", "card": "ACCUSE"})
        self.assertEqual(agent.memory, snapshot)

    def test_plan_rejects_invalid_numbers_ids_and_private_reasoning_fields(self):
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

    def test_public_speech_requires_bounded_printable_text_and_summary(self):
        view = fixed_game().view("P1")
        ids = [p["id"] for p in view["players"]]
        for field in ("statement", "rationale"):
            for value in (None, "", "   ", "x" * 401, "text\x1b[2J", "text\n[RESULT]", "a\u202eb"):
                with self.subTest(field=field, value=value):
                    plan = valid_plan(view)
                    plan["social"][field] = value
                    with self.assertRaises(ValueError):
                        validate_plan(plan, ids)
            plan = valid_plan(view)
            del plan["social"][field]
            with self.assertRaises(ValueError):
                validate_plan(plan, ids)
        plan = valid_plan(view)
        self.assertEqual(validate_plan(plan, ids)["social"], plan["social"])

    def test_assassin_has_legal_target_from_llm_plan(self):
        view = fixed_game().view("P3")
        one, two = Agent(view, FixedClient(valid_plan(view))), Agent(view, FixedClient(valid_plan(view)))
        one.prepare(view)
        two.prepare(view)
        self.assertEqual(one.plan, two.plan)
        self.assertEqual(one.calls, {1: 1})
        self.assertIn(one.assassinate(), ["P1", "P2", "P5"])

    def test_new_proposal_uses_fresh_llm_ranking_without_rotating_its_choice(self):
        view = fixed_game().view("P1")
        view["attempt"] = 2
        agent = Agent(view, FixedClient(valid_plan(view)))
        agent.prepare(view)
        self.assertEqual(agent.choose_team(2, attempt=2), ["P5", "P4"])


if __name__ == "__main__":
    unittest.main()
