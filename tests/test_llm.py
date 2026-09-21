from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.request import ProxyHandler, build_opener as real_build_opener

from avalon.llm import ChatClient, LLMError, Settings
from avalon.chronicle import context_record


@contextmanager
def endpoint(body, status=200, delay=0, broken_chunk=False):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            request_body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append((self.path, dict(self.headers), request_body))
            if delay:
                time.sleep(delay)
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            if broken_chunk:
                self.send_header("Transfer-Encoding", "chunked")
            if status == 302:
                self.send_header("Location", "/redirected")
            self.end_headers()
            response = body(request_body) if callable(body) else body
            try:
                self.wfile.write(b"invalid chunk\r\n" if broken_chunk else json.dumps(response).encode())
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        # Reach the real loopback server directly; proxies can rewrite invalid HTTP
        # into a 502 and hide transport exceptions such as IncompleteRead.
        with patch("avalon.llm.build_opener", lambda *handlers: real_build_opener(ProxyHandler({}), *handlers)):
            yield f"http://127.0.0.1:{server.server_port}/v1", requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def envelope(content='{"ok": true}', finish="stop"):
    return {"choices": [{"finish_reason": finish,
                         "message": {"content": content, "reasoning_content": "PRIVATE_SENTINEL"}}]}


class ClientTests(unittest.TestCase):
    def test_validation_diagnostics_and_feedback_never_include_unknown_error_text(self):
        error = LLMError("invalid_plan", validation_reason="raw response PRIVATE_SENTINEL\n[REVEAL]")
        self.assertEqual(error.diagnostic, "invalid_plan")
        self.assertIsNone(error.validation_reason)
        self.assertNotIn("PRIVATE_SENTINEL", json.dumps(error.retry_feedback))
        self.assertNotIn("REVEAL", json.dumps(error.retry_feedback))
        error = LLMError("invalid_plan", validation_reason="Invalid performance keys")
        self.assertIn("Invalid performance keys", error.diagnostic)
        self.assertIn("social, discussion, revision and strong_vote", error.retry_feedback["rule"])
        self.assertEqual(error.public_code, "invalid_plan")

    def test_world_prompt_loads_from_an_isolated_user_install(self):
        source = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            env = dict(os.environ, PYTHONUSERBASE=str(root / "user"), PYTHONPATH="",
                       PYTHON_DOTENV_DISABLED="1")
            locations = subprocess.run(
                [sys.executable, "-c", "import json, site, sysconfig; "
                 "print(json.dumps([site.getusersitepackages(), "
                 "sysconfig.get_path('data', scheme=sysconfig.get_preferred_scheme('user'))]))"],
                cwd=root, env=env, capture_output=True, text=True, timeout=30, check=True)
            user_site, data = [Path(path).resolve() for path in json.loads(locations.stdout)]
            self.assertTrue(user_site.is_relative_to(root))
            self.assertTrue(data.is_relative_to(root))
            shutil.copytree(source / "avalon", user_site / "avalon",
                            ignore=shutil.ignore_patterns("__pycache__"))
            installed_scene = data / "share" / "terminal-avalon-mvp" / "corrupted_castle_system.md"
            installed_scene.parent.mkdir(parents=True)
            shutil.copyfile(source / "prompts" / installed_scene.name, installed_scene)
            # Explicitly expose the isolated user site even when tests run in a venv.
            env["PYTHONPATH"] = str(user_site)
            result = subprocess.run(
                [sys.executable, "-c", "from avalon.llm import ChatClient, Settings; "
                 "client = ChatClient(Settings(api_key='test-key', model='test-model')); "
                 "print(client.world_prompt_path.resolve())"],
                cwd=root, env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(Path(result.stdout.strip()), installed_scene)

    def test_castle_prompt_reaches_every_role_as_system_instructions(self):
        scene = (Path(__file__).resolve().parents[1] / "prompts" / "corrupted_castle_system.md").read_text(encoding="utf-8").strip()
        with endpoint(envelope()) as (url, requests):
            client = ChatClient(Settings(api_key="test-key", base_url=url, model="test-model"))
            contexts = [{"game": {"self": "P1", "role": "GOOD"}},
                        {"game": {"self": "P2", "role": "MERLIN"}},
                        {"game": {"self": "P3", "role": "ASSASSIN"}, "tactical": {"primary_target": "P1"}},
                        {"game": {"self": "P4", "role": "EVIL"}, "tactical": {"primary_target": "P2"}}]
            for context in contexts:
                client.complete(context)
            for context, (_, _, body) in zip(contexts, requests):
                system = body["messages"][0]
                self.assertEqual(system["role"], "system")
                self.assertIn(scene, system["content"])
                self.assertEqual(system["content"].count(scene), 1)
                self.assertEqual(json.loads(body["messages"][1]["content"]), context)
                for old_goal in ("MERLIN and GOOD want", "ASSASSIN and EVIL want", "Your goal is the Evil team's success"):
                    self.assertNotIn(old_goal, system["content"])
            self.assertIn("social, discussion, revision and strong_vote" if "tactical" in context else
                          "Code owns beliefs/profiles and weights", system["content"])
            self.assertIn("PRIVATE BELIEF DOES NOT EQUAL PUBLIC STANCE", system["content"])
            self.assertIn('"recommended_action"', system["content"])

    def test_world_prompt_is_loaded_once_per_client_even_across_a_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            scene = Path(directory) / "scene.md"
            scene.write_text("城堡 WORLD_VERSION_ONE", encoding="utf-8")
            attempts = []
            def respond(body):
                attempts.append(body)
                if len(attempts) == 1:
                    scene.write_text("城堡 WORLD_VERSION_TWO", encoding="utf-8")
                    return envelope("not json")
                return envelope()
            with patch("avalon.llm.WORLD_PROMPT_PATH", scene, create=True), endpoint(respond) as (url, requests):
                settings = Settings(api_key="test-key", base_url=url, model="test-model")
                client = ChatClient(settings)
                with self.assertRaisesRegex(LLMError, "invalid_response"):
                    client.complete({})
                client.complete({})
                ChatClient(settings).complete({})
                systems = [r[2]["messages"][0]["content"] for r in requests]
                self.assertIn("WORLD_VERSION_ONE", systems[0])
                self.assertEqual(systems[0], systems[1])
                self.assertIn("WORLD_VERSION_TWO", systems[2])
                self.assertNotIn("WORLD_VERSION_ONE", systems[2])

    def test_missing_empty_or_invalid_world_prompt_fails_without_a_request(self):
        with tempfile.TemporaryDirectory() as directory, endpoint(envelope()) as (url, requests):
            scene = Path(directory) / "scene.md"
            for content in (None, b" \n\t", b"\xff"):
                with self.subTest(content=content), patch("avalon.llm.WORLD_PROMPT_PATH", scene, create=True):
                    if content is not None:
                        scene.write_bytes(content)
                    with self.assertRaisesRegex(LLMError, "world_prompt_unavailable") as caught:
                        ChatClient(Settings(api_key="private-test-key", base_url=url, model="test-model")).complete({})
                    self.assertFalse(caught.exception.retryable)
                    self.assertNotIn("private-test-key", str(caught.exception))
            self.assertEqual(requests, [])

    def test_real_http_contract_and_no_reasoning_output(self):
        with endpoint(envelope()) as (url, requests):
            client = ChatClient(Settings(api_key="test-key", base_url=url, model="test-model"))
            self.assertEqual(client.complete({"game": {"self": "P1"}}), {"ok": True})
            self.assertEqual(len(requests), 1)
            path, headers, body = requests[0]
            self.assertEqual(path, "/v1/chat/completions")
            self.assertEqual({k.lower(): v for k, v in headers.items()}["authorization"], "Bearer test-key")
            self.assertEqual(body["model"], "test-model")
            self.assertEqual(body["messages"][0]["role"], "system")
            self.assertNotIn("test-key", json.dumps(body))
            self.assertNotIn("thinking", body)

    def test_deepseek_v4_pro_configuration_and_request(self):
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text("OPENAI_API_KEY=test-key\nOPENAI_BASE_URL=https://api.deepseek.com\n"
                                "OPENAI_MODEL=deepseek-v4-pro\nDEEPSEEK_THINKING=disabled\n"
                                "OPENAI_JSON_MODE=true\n", encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True):
                settings = Settings.load(env_file)
            self.assertEqual(settings.endpoint, "https://api.deepseek.com/chat/completions")
            self.assertEqual(settings.thinking, "disabled")
            with endpoint(envelope()) as (url, requests):
                settings.base_url = url
                self.assertEqual(ChatClient(settings).complete({}), {"ok": True})
                self.assertEqual(len(requests), 1)
                body = requests[0][2]
                self.assertEqual(body["model"], "deepseek-v4-pro")
                self.assertEqual(body["thinking"], {"type": "disabled"})
                self.assertEqual(body["response_format"], {"type": "json_object"})
        with patch.dict(os.environ, {"DEEPSEEK_THINKING": "invalid"}, clear=True):
            with self.assertRaises(ValueError):
                Settings.load(Path(directory) / "not-present.env")

    def test_http_errors_redirects_and_invalid_responses_are_safe(self):
        for body, status in (({"secret": "PRIVATE_SENTINEL"}, 401), ({}, 429), ({}, 302),
                             (envelope("not json"), 200), (envelope(finish="length"), 200),
                             ({"choices": []}, 200), (envelope('[1,2]'), 200),
                             (envelope('[' * 3000 + ']' * 3000), 200),
                             (envelope('{"bad":NaN}'), 200)):
            with endpoint(body, status) as (url, requests):
                client = ChatClient(Settings(api_key="test-key", base_url=url, model="test-model"))
                with self.assertRaises(LLMError) as caught:
                    client.complete({})
                self.assertNotIn("PRIVATE_SENTINEL", str(caught.exception))
                self.assertNotIn("test-key", str(caught.exception))
                self.assertEqual(len(requests), 1)

    def test_dotenv_fixed_path_bom_and_file_precedence(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Path(directory) / ".env"
            env.write_text("OPENAI_API_KEY=file-key\nOPENAI_MODEL=test-model\n"
                           "OPENAI_BASE_URL=http://localhost:1234/v1\n",
                           encoding="utf-8-sig")
            with patch.dict(os.environ, {"OPENAI_API_KEY": "process-key",
                                         "OPENAI_MODEL": "process-model",
                                         "OPENAI_BASE_URL": "http://localhost:4321/v1",
                                         "OPENAI_TIMEOUT_SECONDS": "17"}, clear=True):
                settings = Settings.load(env)
                self.assertEqual(settings.api_key, "file-key")
                self.assertEqual(settings.model, "test-model")
                self.assertEqual(settings.base_url, "http://localhost:1234/v1")
                self.assertEqual(settings.timeout, 17)

    def test_environment_configuration_when_dotenv_missing_or_disabled(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Path(directory) / ".env"
            env.write_text("OPENAI_API_KEY=file-key\nOPENAI_MODEL=file-model\n", encoding="utf-8")
            for path, disabled in ((env, "1"), (env.with_name("missing.env"), "0")):
                with self.subTest(path=path.name, disabled=disabled), patch.dict(os.environ, {
                    "OPENAI_API_KEY": "process-key", "OPENAI_MODEL": "process-model",
                    "PYTHON_DOTENV_DISABLED": disabled,
                }, clear=True):
                    settings = Settings.load(path)
                    self.assertEqual(settings.api_key, "process-key")
                    self.assertEqual(settings.model, "process-model")

    def test_aliases_disabled_dotenv_and_invalid_settings(self):
        with patch.dict(os.environ, {"LLM_API_KEY": "test-key", "LLM_MODEL": "test-model",
                                     "LLM_API_URL": "http://localhost/v1/chat/completions",
                                     "PYTHON_DOTENV_DISABLED": "1"}, clear=True):
            settings = Settings.load()
            self.assertTrue(settings.ready)
            self.assertEqual(settings.endpoint, "http://localhost/v1/chat/completions")
        with patch.dict(os.environ, {"OPENAI_TIMEOUT_SECONDS": "nan",
                                     "PYTHON_DOTENV_DISABLED": "1"}, clear=True):
            with self.assertRaises(ValueError):
                Settings.load()
        self.assertFalse(Settings().ready)

    def test_retry_settings_load_and_reject_invalid_limits(self):
        with patch.dict(os.environ, {"PYTHON_DOTENV_DISABLED": "1", "OPENAI_MAX_RETRIES": "4",
                                     "OPENAI_RETRY_DELAY_SECONDS": "1.5"}, clear=True):
            settings = Settings.load()
            self.assertEqual(getattr(settings, "max_retries", None), 4)
            self.assertEqual(getattr(settings, "retry_delay", None), 1.5)
        for name, value in (("OPENAI_MAX_RETRIES", "-1"), ("OPENAI_MAX_RETRIES", "6"),
                            ("OPENAI_MAX_RETRIES", "1.5"), ("OPENAI_RETRY_DELAY_SECONDS", "nan"),
                            ("OPENAI_RETRY_DELAY_SECONDS", "-1"), ("OPENAI_RETRY_DELAY_SECONDS", "31")):
            with self.subTest(name=name, value=value):
                with patch.dict(os.environ, {"PYTHON_DOTENV_DISABLED": "1", name: value}, clear=True):
                    with self.assertRaises(ValueError):
                        Settings.load()

    def test_incomplete_empty_and_refused_responses_have_distinct_safe_codes(self):
        refused = envelope()
        refused["choices"][0]["message"]["refusal"] = "PRIVATE_SENTINEL"
        for body, code in ((envelope(finish="length"), "truncated_response"),
                           (envelope(content="  "), "empty_response"), (envelope(content=None), "empty_response"),
                           (refused, "refusal"), (envelope(finish="content_filter"), "content_filtered")):
            with self.subTest(code=code), endpoint(body) as (url, requests):
                client = ChatClient(Settings(api_key="test", model="test", base_url=url))
                with self.assertRaisesRegex(LLMError, code):
                    client.complete({})
                self.assertEqual(len(requests), 1)

    def test_network_timeout_and_incomplete_http_body_stop_the_agent(self):
        from avalon.agents import Agent
        from test_engine import fixed_game
        for options in ({"delay": 0.1}, {"broken_chunk": True}):
            with endpoint(envelope(), **options) as (url, requests):
                client = ChatClient(Settings(api_key="test", model="test", base_url=url, timeout=0.03))
                view = fixed_game().view("P1")
                agent = Agent(view, client, max_retries=0)
                with self.assertRaises(LLMError):
                    agent.prepare(view)
                self.assertIsNone(agent.plan)
                self.assertEqual(len(requests), 1)

    def test_http_game_requests_follow_speaker_order_with_previous_speeches(self):
        from collections import Counter
        from avalon.agents import Agent
        from avalon.terminal import Human, run_game
        from test_agents import model_response
        from test_engine import fixed_game

        def response(request):
            context = json.loads(request["messages"][1]["content"])
            plan = model_response(context)
            if "mission" in plan:
                plan["mission"] = "SUCCESS"
            if "social" in plan:
                plan["social"]["statement"] = f"{context['game']['self']}：我会比较这次队伍与此前的公开表现。"
            return envelope(json.dumps(plan))

        with endpoint(response) as (url, requests):
            game = fixed_game()
            client = ChatClient(Settings(api_key="test", model="test", base_url=url))
            agents = {p: Agent(game.view(p), client) for p in game.ids if p != "P1"}
            human = Human(game.view("P1"), input_fn=lambda _: "", write=lambda _: None)
            output = []
            run_game(game, agents, human, write=output.append, strategy_seed=7)
            self.assertIn(game.winner, {"GOOD", "EVIL"})
            expected_calls = [(e["actor"], e["round"], e["attempt"],
                               {"TEAM": "team", "EXILE_NOMINATION": "exile_nomination", "EXILE_VOTE": "exile_vote"}.get(
                                   e["kind"], "council_discussion" if e.get("discussion_stage") == "council" else "discussion"))
                              for e in game.events if (e["kind"] in {"SOCIAL", "EXILE_NOMINATION", "EXILE_VOTE"} or
                              e["kind"] == "TEAM" and game.players[e["actor"]].role in {"GOOD", "MERLIN"})
                              and e["actor"] in agents]
            self.assertEqual(len(requests), len(expected_calls))
            contexts = [json.loads(r[2]["messages"][1]["content"]) for r in requests]
            counts = Counter((c["game"]["self"], c["game"]["round"],
                              c["game"]["attempt"], c["game"]["phase"]) for c in contexts)
            self.assertEqual(set(counts.values()), {1})
            self.assertEqual(list(counts), expected_calls)
            speeches = [c["game"] for c in contexts if c["game"]["phase"] == "discussion"]
            self.assertEqual([c["self"] for c in speeches[:4]], ["P2", "P3", "P4", "P5"])
            for view in speeches:
                before = [e for e in game.events if e["kind"] == "SOCIAL"
                          and e["round"] == view["round"] and e["attempt"] == view["attempt"]]
                index = next(i for i, event in enumerate(before) if event["actor"] == view["self"])
                actual = [e for e in view["recent_events"] if e["kind"] == "SOCIAL"
                          and e["round"] == view["round"] and e["attempt"] == view["attempt"]]
                self.assertEqual(actual, [context_record(e) for e in before[:index]])
                self.assertTrue(view["team"])
            self.assertNotIn("PRIVATE_SENTINEL", "\n".join(output) + json.dumps(game.events))
            self.assertTrue(all(source == "llm" for a in agents.values() for source in a.sources.values()))


if __name__ == "__main__":
    unittest.main()
