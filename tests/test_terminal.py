import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from avalon.agents import Agent
from avalon.engine import Game, make_players
from avalon.terminal import Human, QuitGame, run_game
from test_engine import fixed_game
from test_agents import FixedClient, model_response, valid_plan
from test_llm import endpoint, envelope


def cli_env(**settings):
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("OPENAI_", "LLM_", "DEEPSEEK_"))}
    return {**env, "PYTHON_DOTENV_DISABLED": "1", "NO_PROXY": "127.0.0.1,localhost", **settings}


def successful_response(request):
    context = json.loads(request["messages"][1]["content"])
    plan = model_response(context)
    if "mission" in plan:
        plan["mission"] = "SUCCESS"
    return envelope(json.dumps(plan))


def expected_llm_events(events):
    roles = next(e["roles"] for e in events if e["kind"] == "REVEAL")
    return [e for e in events if e["kind"] == "SOCIAL" or
            (e["kind"] == "TEAM" and roles[e["actor"]] in {"GOOD", "MERLIN"})]


class TerminalTests(unittest.TestCase):
    def test_human_reprompts_for_invalid_inputs_and_handles_quit(self):
        output = []
        answers = iter(["P1 P1", "P1 P9", "1,2", "blah", "BAIT P2", "maybe", "n"])
        human = Human(fixed_game().view("P1"), input_fn=lambda _: next(answers), write=output.append)
        self.assertEqual(human.choose_team(2), ["P1", "P2"])
        self.assertEqual(human.social_action(), {"card": "BAIT", "target": "P2", "reason": "human_choice"})
        self.assertFalse(human.vote(["P1", "P2"], 1))
        self.assertGreaterEqual(len(output), 4)
        human.input_fn = lambda _: "q"
        with self.assertRaises(QuitGame):
            human.vote(["P1", "P2"], 1)

    def test_scripted_human_plays_a_complete_game(self):
        game = fixed_game()
        human = Human(game.view("P1"), input_fn=lambda _: "", write=lambda _: None)
        agents = {pid: Agent(game.view(pid), FixedClient(valid_plan(game.view(pid))))
                  for pid in game.ids if pid != "P1"}
        output, log = [], io.StringIO()
        run_game(game, agents, human=human, write=output.append, log=log, dossier=True)
        self.assertIn(game.winner, {"GOOD", "EVIL"})
        text = "\n".join(output)
        for name in ("TEAM", "SOCIAL", "VOTE", "MISSION", "RESULT", "DOSSIER"):
            self.assertIn(f"[{name}]", text)
        events = [json.loads(line) for line in log.getvalue().splitlines()]
        self.assertEqual(events, game.events)
        self.assertTrue(any(e["kind"] == "SOCIAL" and e["actor"] == "P1" for e in events))
        self.assertTrue(all(sum(agent.calls.values()) > 0 for agent in agents.values()))
        self.assertIn("理由摘要", text)
        self.assertIn("目前公开证据有限", text)
        self.assertNotIn("beliefs", log.getvalue())
        self.assertNotIn("PRIVATE", log.getvalue())
        for event in events:
            if event["kind"] == "TEAM_VOTE":
                same_proposal = [e for e in events if e["round"] == event["round"]
                                 and e["attempt"] == event["attempt"]]
                self.assertEqual(sum(e["kind"] == "SOCIAL" for e in same_proposal), 5)
                self.assertEqual(sum(e["kind"] == "VOTE" for e in same_proposal), 5)

    def test_demo_many_seeds_always_terminates_and_is_reproducible(self):
        for count in (5, 6):
            for seed in range(20):
                game = Game(make_players(count, seed), seed=seed)
                agents = {p: Agent(game.view(p), FixedClient(valid_plan(game.view(p)))) for p in game.ids}
                run_game(game, agents, write=lambda _: None, strategy_seed=seed)
                self.assertIn(game.winner, {"GOOD", "EVIL"})
                self.assertLessEqual(len(game.missions), 5)
                self.assertEqual(game.events[-1]["kind"], "REVEAL")
        logs = []
        for _ in range(2):
            game = Game(make_players(6, 7), seed=7)
            log = io.StringIO()
            run_game(game, {p: Agent(game.view(p), FixedClient(valid_plan(game.view(p)))) for p in game.ids},
                     write=lambda _: None, log=log, strategy_seed=7)
            logs.append(log.getvalue())
        self.assertEqual(*logs)

    def test_cli_demo_and_eof_are_real_entrypoint_runs(self):
        cwd = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory, endpoint(successful_response) as (url, requests):
            log = Path(directory) / "demo.jsonl"
            env = cli_env(OPENAI_API_KEY="test-key", OPENAI_MODEL="test-model", OPENAI_BASE_URL=url)
            result = subprocess.run([sys.executable, "-X", "utf8", "-m", "avalon",
                                     "--demo", "--players", "6", "--seed", "7", "--log", str(log)],
                                    cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8", timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("[RESULT]", result.stdout)
            self.assertIn("[LYRA/P6]", result.stdout)
            self.assertLess(result.stdout.index("[LEADER]"), result.stdout.index("[ROUND 1/5]"))
            self.assertIn("[LEADER] [YOU/P1]", result.stdout)
            self.assertIn("演示", result.stdout)
            self.assertIn("[BACKEND] LLM", result.stdout)
            self.assertIn("[WORLD] 腐化城堡", result.stdout)
            self.assertIn("理由摘要", result.stdout)
            self.assertNotIn("fallback", result.stdout)
            self.assertNotIn("mock", result.stdout)
            self.assertNotIn("PRIVATE_SENTINEL", result.stdout)
            self.assertTrue(log.is_file())
            events = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
            self.assertTrue(all(e.get("statement") and e.get("rationale")
                                for e in events if e["kind"] == "SOCIAL"))
            self.assertEqual(len(requests), len(expected_llm_events(events)))
            scene = (cwd / "prompts" / "corrupted_castle_system.md").read_text(encoding="utf-8").strip()
            self.assertTrue(all(scene in request[2]["messages"][0]["content"] for request in requests))
        result = subprocess.run([sys.executable, "-X", "utf8", "-m", "avalon", "--seed", "7"],
                                cwd=cwd, env=env, input="", capture_output=True, text=True,
                                encoding="utf-8", timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("[EXIT]", result.stdout)
        self.assertNotIn("[RESULT]", result.stdout)

    def test_cli_missing_or_invalid_configuration_does_not_start_a_game(self):
        cwd = Path(__file__).resolve().parents[1]
        for settings in ({}, {"OPENAI_API_KEY": "private-test-key"},
                         {"OPENAI_BASE_URL": "not-a-url"}, {"OPENAI_TIMEOUT_SECONDS": "private-invalid"}):
            with self.subTest(settings=settings):
                result = subprocess.run([sys.executable, "-X", "utf8", "-m", "avalon", "--demo"],
                                        cwd=cwd, env=cli_env(**settings), capture_output=True,
                                        text=True, encoding="utf-8", timeout=15)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("[CONFIG]", result.stdout)
                self.assertNotIn("[PLAYERS]", result.stdout)
                self.assertNotIn("[RESULT]", result.stdout)
                self.assertNotIn("private-", result.stdout + result.stderr)

    def test_cli_missing_scene_stops_before_play_or_network(self):
        source = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory, endpoint(successful_response) as (url, requests):
            project = Path(directory)
            shutil.copytree(source / "avalon", project / "avalon", ignore=shutil.ignore_patterns("__pycache__"))
            shutil.copyfile(source / "pyproject.toml", project / "pyproject.toml")
            result = subprocess.run([sys.executable, "-X", "utf8", "-m", "avalon", "--demo"], cwd=project,
                                    env=cli_env(OPENAI_API_KEY="private-test-key", OPENAI_MODEL="test-model",
                                                OPENAI_BASE_URL=url),
                                    capture_output=True, text=True, encoding="utf-8", timeout=15)
            self.assertEqual(result.returncode, 1)
            self.assertIn("[CONFIG]", result.stdout)
            self.assertIn("corrupted_castle_system.md", result.stdout)
            self.assertNotIn("[PLAYERS]", result.stdout)
            self.assertNotIn("Traceback", result.stderr)
            self.assertNotIn("private-test-key", result.stdout + result.stderr)
            self.assertEqual(requests, [])

    def test_cli_log_cannot_overwrite_active_scene(self):
        source = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            shutil.copytree(source / "avalon", project / "avalon", ignore=shutil.ignore_patterns("__pycache__"))
            shutil.copytree(source / "prompts", project / "prompts")
            scene = project / "prompts" / "corrupted_castle_system.md"
            before = scene.read_bytes()
            for flag in ("--log", "--strategy-log"):
                result = subprocess.run([sys.executable, "-X", "utf8", "-m", "avalon", "--demo", flag, str(scene)],
                                        cwd=project, env=cli_env(OPENAI_API_KEY="test-key", OPENAI_MODEL="test-model"),
                                        capture_output=True, text=True, encoding="utf-8", timeout=15)
                self.assertEqual(result.returncode, 1)
                self.assertIn("[CONFIG]", result.stdout)
                self.assertNotIn("[PLAYERS]", result.stdout)
                self.assertEqual(scene.read_bytes(), before)

    def test_cli_provider_error_aborts_instead_of_playing_fallback_moves(self):
        cwd = Path(__file__).resolve().parents[1]
        with endpoint({"error": "PRIVATE_SENTINEL"}, status=401) as (url, requests):
            result = subprocess.run([sys.executable, "-X", "utf8", "-m", "avalon", "--demo"],
                                    cwd=cwd, env=cli_env(OPENAI_API_KEY="private-test-key",
                                                        OPENAI_MODEL="test-model", OPENAI_BASE_URL=url),
                                    capture_output=True, text=True, encoding="utf-8", timeout=15)
            self.assertEqual(result.returncode, 1)
            self.assertIn("http_401", result.stdout)
            self.assertNotIn("[SOCIAL]", result.stdout)
            self.assertNotIn("[RESULT]", result.stdout)
            self.assertNotIn("PRIVATE_SENTINEL", result.stdout + result.stderr)
            self.assertNotIn("private-test-key", result.stdout + result.stderr)
            self.assertEqual(len(requests), 1)

    def test_cli_retries_sage_speech_then_finishes_without_duplicate_events(self):
        contexts = []
        failed = False

        def response(request):
            nonlocal failed
            context = json.loads(request["messages"][1]["content"])
            contexts.append(context)
            if context["game"]["self"] == "P5" and context["game"]["phase"] == "discussion" and not failed:
                failed = True
                return envelope("not json: PRIVATE_SENTINEL")
            return successful_response(request)

        cwd = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory, endpoint(response) as (url, requests):
            log = Path(directory) / "retry-game.jsonl"
            result = subprocess.run([sys.executable, "-X", "utf8", "-m", "avalon", "--demo",
                                     "--seed", "7", "--direction", "clockwise", "--log", str(log)],
                                    cwd=cwd, env=cli_env(OPENAI_API_KEY="test-key", OPENAI_MODEL="test-model",
                                                        OPENAI_BASE_URL=url, OPENAI_RETRY_DELAY_SECONDS="0"),
                                    capture_output=True, text=True, encoding="utf-8", timeout=15)
            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertIn("[RETRY] [SAGE/P5]", result.stdout)
            self.assertIn("invalid_response", result.stdout)
            self.assertIn("[RESULT]", result.stdout)
            self.assertNotIn("PRIVATE_SENTINEL", result.stdout + result.stderr)
            retry_index = next(i for i, c in enumerate(contexts)
                               if c["game"]["self"] == "P5" and c["game"]["phase"] == "discussion")
            self.assertEqual(contexts[retry_index], contexts[retry_index + 1])
            events = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(requests), len(expected_llm_events(events)) + 1)
            self.assertEqual(sum(e["kind"] == "SOCIAL" for e in events),
                             5 * sum(e["kind"] == "TEAM" for e in events))
            self.assertEqual([e["actor"] for e in events if e["kind"] == "SOCIAL"][:5],
                             ["P1", "P2", "P3", "P4", "P5"])
            self.assertNotIn("PRIVATE_SENTINEL", log.read_text(encoding="utf-8"))
            sage_calls = next(line for line in result.stdout.splitlines() if line.startswith("[CALLS] [SAGE/P5]"))
            sage_round_one = sum(e["round"] == 1 and e["actor"] == "P5" for e in expected_llm_events(events))
            self.assertIn(f"R1={sage_round_one + 1}", sage_calls)

    def test_cli_stops_after_configured_retry_limit(self):
        cwd = Path(__file__).resolve().parents[1]
        with endpoint(envelope("not json")) as (url, requests):
            result = subprocess.run([sys.executable, "-X", "utf8", "-m", "avalon", "--demo", "--seed", "7"],
                                    cwd=cwd, env=cli_env(OPENAI_API_KEY="test-key", OPENAI_MODEL="test-model",
                                                        OPENAI_BASE_URL=url, OPENAI_MAX_RETRIES="1",
                                                        OPENAI_RETRY_DELAY_SECONDS="0"),
                                    capture_output=True, text=True, encoding="utf-8", timeout=15)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(len(requests), 2)
            self.assertIn("[RETRY]", result.stdout)
            self.assertIn("invalid_response", result.stdout)
            self.assertNotIn("[TEAM]", result.stdout)
            self.assertNotIn("[RESULT]", result.stdout)

    def test_cli_strategy_debug_and_trace_use_private_sinks(self):
        cwd = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory, endpoint(successful_response) as (url, requests):
            public = Path(directory) / "public.jsonl"
            private = Path(directory) / "strategy.jsonl"
            result = subprocess.run([sys.executable, "-X", "utf8", "-m", "avalon", "--demo", "--seed", "7",
                                     "--debug-strategy", "--strategy-log", str(private), "--log", str(public)],
                                    cwd=cwd, env=cli_env(OPENAI_API_KEY="test-key", OPENAI_MODEL="test-model",
                                                        OPENAI_BASE_URL=url, OPENAI_RETRY_DELAY_SECONDS="0"),
                                    capture_output=True, text=True, encoding="utf-8", timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("EVIL STRATEGY UPDATE", result.stderr)
            self.assertIn("mission_fail_owner", result.stderr)
            self.assertIn("[RESULT]", result.stdout)
            decisions = [json.loads(line) for line in private.read_text(encoding="utf-8").splitlines()]
            self.assertTrue(any(d["phase"] == "mission" for d in decisions))
            self.assertTrue(all("primary_objective" in d for d in decisions))
            for text in (result.stdout, public.read_text(encoding="utf-8")):
                for secret in ("EVIL STRATEGY UPDATE", "mission_fail_owner", "primary_objective", "PRIVATE_SENTINEL"):
                    self.assertNotIn(secret, text)
            self.assertTrue(requests)

    def test_cli_rejects_public_private_log_collision_without_overwriting(self):
        cwd = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "keep.jsonl"
            log.write_text("KEEP", encoding="utf-8")
            result = subprocess.run([sys.executable, "-X", "utf8", "-m", "avalon", "--demo",
                                     "--log", str(log), "--strategy-log", str(log)],
                                    cwd=cwd, env=cli_env(OPENAI_API_KEY="test-key", OPENAI_MODEL="test-model"),
                                    capture_output=True, text=True, encoding="utf-8", timeout=15)
            self.assertEqual(result.returncode, 1)
            self.assertIn("[CONFIG]", result.stdout)
            self.assertEqual(log.read_text(encoding="utf-8"), "KEEP")

    def test_cli_disclosure_retry_and_exhaustion_do_not_identify_evil_seats(self):
        cwd = Path(__file__).resolve().parents[1]
        for recover in (False, True):
            rejected = []
            def response(request):
                context = json.loads(request["messages"][1]["content"])
                plan = model_response(context)
                if "tactical" in context and (not recover or not rejected):
                    rejected.append(context)
                    plan["social"]["statement"] = "mission_fail_owner=P4"
                return envelope(json.dumps(plan))
            with self.subTest(recover=recover), tempfile.TemporaryDirectory() as directory, endpoint(response) as (url, _):
                log = Path(directory) / "public.jsonl"
                trace = Path(directory) / "private.jsonl"
                result = subprocess.run([sys.executable, "-X", "utf8", "-m", "avalon", "--demo", "--seed", "7",
                                         "--debug-strategy", "--log", str(log), "--strategy-log", str(trace)],
                                        cwd=cwd, env=cli_env(OPENAI_API_KEY="test-key", OPENAI_MODEL="test-model",
                                                            OPENAI_BASE_URL=url, OPENAI_MAX_RETRIES="1",
                                                            OPENAI_RETRY_DELAY_SECONDS="0"),
                                        capture_output=True, text=True, encoding="utf-8", timeout=15)
                self.assertEqual(result.returncode, 0 if recover else 1, result.stdout)
                self.assertTrue(rejected)
                self.assertIn("[RETRY]", result.stdout)
                self.assertIn("invalid_plan", result.stdout)
                self.assertIn("private_disclosure", result.stderr)
                for private in ("private_disclosure", "mission_fail_owner", "primary_objective", "FAKE_CONFLICT"):
                    self.assertNotIn(private, result.stdout + log.read_text(encoding="utf-8"))
                if not recover:
                    decisions = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
                    self.assertFalse(any(d["action"]["kind"] == "social" for d in decisions))


if __name__ == "__main__":
    unittest.main()
