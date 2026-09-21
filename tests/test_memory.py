"""Deterministic full memory loop; only the external model boundary is substituted."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from avalon.agents import Agent
from avalon.chronicle import Chronicle, EVIDENCE_KINDS, record_id
from avalon.engine import Game, Player, validate_social
from avalon.gui import GameSession
from avalon.evil_strategy import EvilStrategyManager
from avalon.llm import LLMError
from avalon.memory import LIFE_LIMIT, SCAR_LIMIT, WORKING_LIMIT
from avalon.terminal import format_event
from test_agents import FixedClient, SequenceClient, valid_plan
from test_engine import approve, fixed_game, finish_council


def writing(card="ACCUSE", target="P5", text="这份名单有风险。", citations=()):
    return {"card": card, "target": target, "reason": "observe",
            "public_writing": text, "citations": list(citations)}


def past_life():
    game = fixed_game()
    agent = Agent(game.view("P5"), chronicle=game.chronicle.reader(), max_retries=0)
    game.propose(game.leader, ["P3", "P5"])
    accusation = None
    for pid in game.speaking_order:
        if pid == "P1":
            game.social(pid, writing(text="P5 的名单说明前后不一致；尚需核查。"))
            accusation = game.events[-1]
        elif pid == "P5":
            game.social(pid, writing("DEFEND", "P2", "我承诺支持 P2。"), committed=True)
        else:
            game.act(pid, {"kind": "PASS"})
    game.act(game.leader, {"kind": "LOCK"})
    game.vote({pid: True for pid in game.ids})
    for event in game.events:
        agent.observe(event)
    beliefs = deepcopy(agent.memory)
    game.resolve_mission({"P3": "FAIL", "P5": "SUCCESS"})
    finish_council(game)
    for event in game.events:
        agent.observe(event)
    return game, agent, accusation, beliefs


class ChronicleTests(unittest.TestCase):
    def test_round_one_record_survives_disk_reload_and_hundreds_of_rounds(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "chronicle.jsonl"
            archive = Chronicle(path)
            first = archive.append_record({"seq": 1, "round": 1, "kind": "SOCIAL", "actor": "P1",
                                           **writing(text="保留这份手稿。")})
            for seq in range(2, 401):
                archive.append_record({"seq": seq, "round": seq, "kind": "PASS", "actor": "P2"})
            restored = Chronicle(path)
            self.assertEqual(first["record_id"], "R1-001")
            self.assertEqual(restored.reader().get_record("R1-001")["public_writing"], "保留这份手稿。")
            self.assertEqual(restored.records, archive.records)
            self.assertEqual(restored.get_record(400)["record_id"], "R400-400")

    def test_detached_reads_cannot_rewrite_original_history(self):
        game = fixed_game()
        game.propose(game.leader, ["P1", "P2"])
        original = game.events[-1]
        game.events[-1]["team"].clear()
        game.chronicle.get_record(original["record_id"])["actor"] = "P99"
        reader = game.chronicle.reader()
        reader.search_records(target="P1")[0]["team"].clear()
        self.assertEqual(game.events[-1], original)
        self.assertFalse(hasattr(reader, "append_record"))
        with self.assertRaises(ValueError):
            game.chronicle.append_record(original)

    def test_journal_rejects_changed_ids_and_reordered_sequences(self):
        for change in ({"seq": 2}, {"record_id": "R2-001"}, {"seq": True}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                Chronicle().append_record({"seq": 1, "round": 1, "kind": "PASS", **change})

    def test_search_prioritizes_old_cited_target_evidence_and_excludes_role_reveals(self):
        game = fixed_game()
        game.propose(game.leader, ["P1", "P2"])
        game.social("P1", writing(target="P2", text="独特药箱失踪，需要核查。"))
        old = game.events[-1]
        for _ in range(40):
            game._emit("PASS", actor="P3")
        game._emit("REVEAL", roles={"P2": "PRIVATE_ROLE_SENTINEL"})
        reader = game.chronicle.reader()
        result = reader.search_records(target="P2", record_ids=[old["record_id"]], limit=1000)
        self.assertEqual(result[0]["record_id"], old["record_id"])
        self.assertLessEqual(len(result), 5)
        self.assertEqual(reader.search_records("药箱")[0]["record_id"], old["record_id"])
        self.assertEqual(reader.search_records("PRIVATE_ROLE_SENTINEL"), [])
        with self.assertRaises(ValueError):
            reader.get_record(game.events[-1]["record_id"])
        self.assertEqual(reader.search_records("unmatchedword"), [])

    def test_unknown_or_private_citations_are_rejected_without_spending_or_recording(self):
        game = fixed_game()
        game.propose(game.leader, ["P1", "P2"])
        before = game.events, dict(game.resolve), set(game.spoken)
        for refs in (["R88-999"], ["R1-001"], [True], [1], ["R1-006"] * 2):
            with self.subTest(refs=refs), self.assertRaises(ValueError):
                game.social(game.leader, writing(citations=refs))
            self.assertEqual((game.events, game.resolve, game.spoken), before)

    def test_new_and_legacy_citations_resolve_to_same_immutable_record(self):
        game = fixed_game()
        game.propose(game.leader, ["P1", "P2"])
        original = game.events[-1]
        game.social("P1", writing(citations=[original["record_id"]]))
        self.assertEqual(game.events[-1]["evidence"], [original["seq"]])
        self.assertEqual(game.events[-1]["citations"], [original["record_id"]])
        game.act("P2", {"kind": "CITE", "evidence": original["record_id"]})
        self.assertEqual(game.view("P3")["focused_events"], [original])
        self.assertEqual(game.chronicle.get_record(original["seq"]), original)


class PersistentMemoryTests(unittest.TestCase):
    def test_death_reflection_rebirth_preserves_identity_beliefs_promises_and_scars(self):
        game, agent, accusation, before = past_life()
        self.assertEqual((agent.id, agent.role, agent.long_term.life), ("P5", "GOOD", 2))
        self.assertTrue(agent.long_term.alive)
        self.assertEqual(game.lives["P5"], {"life": 2, "alive": True})
        self.assertEqual(agent.memory["profiles"], before["profiles"])
        self.assertLess(agent.long_term.relationships["P1"]["trust"], 0)
        self.assertIn(accusation["record_id"], agent.long_term.lives[-1]["important_records"])
        self.assertIn("P1 accused_before_death", agent.long_term.lives[-1]["summary"])
        self.assertEqual(agent.long_term.commitments[0]["target"], "P2")
        self.assertEqual(agent.long_term.unresolved[0]["actor"], "P1")
        self.assertTrue(any(s["source_character"] == "P1" for s in agent.long_term.scars))
        self.assertEqual([e["kind"] for e in agent.evidence], ["REBIRTH"])
        self.assertEqual(game.successes, 0)
        self.assertEqual(game.failures, 1)
        self.assertEqual(game.resolve, dict.fromkeys(game.ids, 3))
        snapshot = agent.long_term.snapshot()
        for event in game.events:
            agent.observe(event)
        self.assertEqual(agent.long_term.snapshot(), snapshot)

    def test_reborn_agent_can_choose_and_publish_accusation_citing_previous_life(self):
        game, agent, old, _ = past_life()
        game.propose(game.leader, ["P2", "P3", "P5"])
        while game.next_actor != agent.id:
            game.act(game.next_actor, {"kind": "PASS"})
        for event in game.events:
            agent.observe(event)
        contexts = []

        class Model:
            def complete(self, context):
                contexts.append(deepcopy(context))
                plan = valid_plan(context["game"])
                previous = next(e for e in context["retrieved_chronicle"] if e["record_id"] == old["record_id"])
                plan["social"] = writing(target=previous["actor"], text="死亡没有让我忘记。你的指控仍需依据。",
                                         citations=[previous["record_id"]])
                return plan

        agent.client = Model()
        agent.prepare(game.view(agent.id))
        game.act(agent.id, agent.discussion_action())
        self.assertEqual(game.events[-1]["card"], "ACCUSE")
        self.assertEqual(game.events[-1]["citations"], [old["record_id"]])
        self.assertEqual(game.chronicle.get_record(old["record_id"]), old)
        self.assertEqual(contexts[0]["agent_memory"]["life"], 2)
        self.assertLessEqual(len(contexts[0]["retrieved_chronicle"]), 5)

    def test_invalid_citation_retries_internally_without_rewriting_memory(self):
        game, agent, old, _ = past_life()
        invalid = valid_plan(game.view("P5"))
        invalid["social"] = writing(citations=["R99-999"])
        valid = deepcopy(invalid)
        valid["social"] = writing(target="P1", citations=[old["record_id"]])
        client = SequenceClient([invalid, valid])
        agent.client, agent.max_retries, agent.retry_delay = client, 1, 0
        before = game.events, agent.long_term.snapshot()
        agent.prepare(game.view("P5"))
        self.assertEqual(len(client.contexts), 2)
        self.assertIn("validation_feedback", client.contexts[1])
        self.assertEqual((game.events, agent.long_term.snapshot()), before)

    def test_exact_old_record_can_be_requested_before_a_final_decision(self):
        game = fixed_game()
        game.propose(game.leader, ["P1", "P2"])
        game.social("P1", writing(target="P2", text="蓝色药箱交给 P2 保管。"))
        old = game.events[-1]
        for _ in range(50):
            game._emit("PASS", actor="P4")
        view = game.view("P5")
        plan = valid_plan(view)
        plan["social"] = writing(target="P2", citations=[old["record_id"]])
        client = SequenceClient([{"memory_query": ["蓝色药箱"]}, plan])
        agent = Agent(view, client, chronicle=game.chronicle.reader(), max_retries=0)
        agent.prepare(view)
        self.assertEqual(len(client.contexts), 2)
        self.assertTrue(client.contexts[1]["retrieval_complete"])
        self.assertEqual(client.contexts[1]["retrieved_chronicle"][0]["record_id"], old["record_id"])
        self.assertEqual(len(game.events), 57)

    def test_query_loops_and_arbitrary_memory_rewrites_are_not_accepted(self):
        view = fixed_game().view("P5")
        for raw in ({"memory_query": ["P1"]}, {**valid_plan(view), "life_memories": ["invented"]}):
            agent = Agent(view, FixedClient(raw), max_retries=0)
            before = deepcopy(agent.memory), agent.long_term.snapshot()
            with self.assertRaises(LLMError):
                agent.prepare(view)
            self.assertEqual((agent.memory, agent.long_term.snapshot()), before)
            self.assertLessEqual(agent.calls[1], 2)

    def test_new_evidence_and_model_interpretation_can_overcome_a_scar(self):
        from test_cognition import envelope, language_update
        game, agent, old, _ = past_life()
        initial_trust = agent.long_term.relationships["P1"]["trust"]
        scar = next(s for s in agent.long_term.scars if s["type"] == "accused_before_death")
        strength = scar["strength"]
        original = game.chronicle.get_record(old["record_id"])
        for _ in range(6):
            event = game._emit("MISSION", team=["P1", "P2"], success=True, fail_count=0)
            agent.observe(event)
        self.assertGreater(agent.long_term.relationships["P1"]["trust"], initial_trust)
        self.assertLess(scar["strength"], strength)
        plan = valid_plan(game.view("P5"))
        plan["social"] = writing("DEFEND", "P1", "后续记录让我改变判断。")
        event = game._emit("SOCIAL", actor="P2", target="P1", card="HEDGE",
                           public_writing="P1 的说法前后一致，我愿意重新考虑。")
        agent.observe(event)
        before_belief = agent.memory["beliefs"]["P1"]["evil"]
        agent.client = SequenceClient([{"language_evidence": [language_update(event, target="P1", signal="decrease_suspicion")]},
                                       envelope(plan)])
        agent.prepare(game.view("P5"))
        self.assertEqual(agent.social_action()["card"], "DEFEND")
        self.assertLess(agent.memory["beliefs"]["P1"]["evil"], before_belief)
        self.assertGreater(agent.memory["beliefs"]["P1"]["evil"], 0)
        self.assertEqual(agent.state.private_beliefs.updates[-1]["evidence"], [event["record_id"]])
        self.assertEqual(game.chronicle.get_record(old["record_id"]), original)

    def test_context_stays_bounded_after_one_thousand_lives(self):
        game = fixed_game()
        archive = Chronicle()
        view = game.view("P5")
        agent = Agent(view, chronicle=archive.reader(), max_retries=0)
        agent.client = FixedClient(valid_plan(view))

        def emit(round_no, kind, **fields):
            event = archive.append_record({"seq": len(archive) + 1, "round": round_no, "kind": kind, **fields})
            agent.observe(event)
            return event

        sizes = []
        for round_no in range(1, 1001):
            emit(round_no, "SOCIAL", actor="P1", **writing())
            mission = emit(round_no, "MISSION", team=["P3", "P5"], success=False, fail_count=1)
            death = emit(round_no, "DEATH", target="P5", cause="failed_expedition", life=round_no,
                         related_records=[mission["record_id"]], origin_record=mission["record_id"])
            emit(round_no, "REBIRTH", target="P5", life=round_no+1, origin_record=death["record_id"])
            if round_no in (20, 1000):
                current = dict(view, round=round_no, recent_events=archive.recent(20))
                agent.prepare(current)
                context = agent.client.contexts[-1]
                sizes.append(len(json.dumps(context)))
                self.assertLessEqual(len(context["game"]["recent_events"]), WORKING_LIMIT)
                self.assertLessEqual(len(context["agent_memory"]["working_memory"]), WORKING_LIMIT)
                self.assertLessEqual(len(context["agent_memory"]["life_memories"]), LIFE_LIMIT)
                self.assertLessEqual(len(context["agent_memory"]["memory_scars"]), SCAR_LIMIT)
                self.assertLessEqual(len(context["retrieved_chronicle"]), 5)
        self.assertLess(sizes[-1], 22000)
        self.assertLess(sizes[-1] - sizes[0], 1800)
        self.assertEqual(len(archive), 4000)
        self.assertEqual(agent.long_term.older_lives["count"], 997)
        self.assertEqual(archive.get_record("R1-001")["public_writing"], "这份名单有风险。")

    def test_knowledge_isolation_includes_retrieval_and_reflections(self):
        game, _, _, _ = past_life()
        game._emit("REVEAL", roles={pid: "PRIVATE_ROLE_SENTINEL" for pid in game.ids})
        for pid in game.ids:
            agent = Agent(game.view(pid), chronicle=game.chronicle.reader())
            for event in game.events:
                agent.observe(event)
            context = agent._context(game.view(pid))
            encoded = json.dumps(context)
            self.assertNotIn("PRIVATE_ROLE_SENTINEL", encoded)
            self.assertNotIn('"true_roles"', encoded)
            self.assertNotIn('"REVEAL"', encoded)
            self.assertNotIn("MISSION_SUBMIT", encoded)
            self.assertEqual(context["game"]["known_evil"], [] if pid in {"P1", "P5"} else ["P3", "P4"])
            self.assertTrue(all(e["kind"] in EVIDENCE_KINDS for e in context["retrieved_chronicle"]))

    def test_failed_mission_deaths_do_not_identify_secret_saboteur(self):
        histories = []
        for saboteur in ("P3", "P4"):
            game = fixed_game()
            approve(game, ["P3", "P4"])
            game.resolve_mission({pid: "FAIL" if pid == saboteur else "SUCCESS" for pid in game.team})
            histories.append(game.events)
        self.assertEqual(*histories)

    def test_new_output_is_short_public_writing_only_and_rejects_reasoning(self):
        game = fixed_game()
        game.propose(game.leader, ["P1", "P2"])
        plan = valid_plan(game.view("P1"))
        plan["social"] = writing(target="P2", text="P2——解释这次表决。")
        agent = Agent(game.view("P1"), FixedClient(plan), max_retries=0)
        agent.prepare(game.view("P1"))
        game.act("P1", agent.discussion_action())
        shown = format_event(game.events[-1], game.players)
        self.assertIn("手写：P2——解释这次表决。", shown)
        self.assertNotIn("rationale", game.events[-1])
        for extra in ({"private_reasoning": "secret"}, {"public_writing": "x" * 241}):
            with self.assertRaises(ValueError):
                validate_social({**writing(), **extra}, game.ids, game.events, True)

    def test_strategic_silence_needs_no_generated_public_text(self):
        game = fixed_game()
        game.propose(game.leader, ["P1", "P2"])
        plan = valid_plan(game.view("P1"))
        plan.update(social=None, discussion={"kind": "PASS"}, revision={"kind": "LOCK"}, strong_vote=False)
        agent = Agent(game.view("P1"), FixedClient(plan), max_retries=0)
        agent.prepare(game.view("P1"))
        game.act("P1", agent.discussion_action())
        self.assertEqual(game.events[-1]["kind"], "PASS")
        self.assertNotIn("public_writing", game.events[-1])
        self.assertEqual(game.resolve["P1"], 3)

    def test_managed_evil_keeps_personal_life_memory_with_new_writing_protocol(self):
        game, _, _, _ = past_life()
        manager = EvilStrategyManager(game.ids, {"P3", "P4"}, seed=0)
        contexts = []

        class Model:
            def complete(self, context):
                contexts.append(deepcopy(context))
                tactic = context["tactical"]
                return {"social": writing(tactic["allowed_cards"][0], tactic["primary_target"], "先核对旧手稿。"),
                        "discussion": {"kind": "SOCIAL"}, "revision": {"kind": "LOCK"}, "strong_vote": False}

        agent = Agent(game.view("P3"), Model(), evil_strategy=manager, chronicle=game.chronicle.reader())
        game.propose(game.leader, ["P2", "P3", "P5"])
        game.act("P2", {"kind": "PASS"})
        for event in game.events:
            manager.observe(event)
            agent.observe(event)
        agent.prepare(game.view("P3"))
        game.act("P3", agent.discussion_action())
        self.assertEqual(contexts[0]["agent_memory"]["life"], 2)
        self.assertTrue(contexts[0]["agent_memory"]["life_memories"])
        self.assertNotIn("memory", contexts[0])
        self.assertEqual(game.events[-1]["public_writing"], "先核对旧手稿。")

    def test_ui_attaches_original_handwriting_without_private_memory(self):
        game, agent, old, _ = past_life()
        game.propose(game.leader, ["P2", "P3", "P5"])
        game.social(game.leader, writing(target="P1", citations=[old["record_id"]]))
        session = GameSession(lambda: None)
        session.game = game
        message = session._dialogue()[-1]
        self.assertEqual(message["citation_records"][0]["public_writing"], old["public_writing"])
        self.assertEqual(message["citation_records"][0]["record_id"], old["record_id"])
        self.assertNotIn("beliefs", json.dumps(message))
        self.assertNotIn("rationale", json.dumps(message))


if __name__ == "__main__":
    unittest.main()
