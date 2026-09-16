from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.request import ProxyHandler, build_opener as real_build_opener

from avalon.llm import ChatClient, LLMError, Settings


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

    def test_dotenv_fixed_path_bom_and_environment_precedence(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Path(directory) / ".env"
            env.write_text("OPENAI_API_KEY=file-key\nOPENAI_MODEL=test-model\n"
                           "OPENAI_BASE_URL=http://localhost:1234/v1\n",
                           encoding="utf-8-sig")
            with patch.dict(os.environ, {"OPENAI_API_KEY": "process-key"}, clear=True):
                settings = Settings.load(env)
                self.assertEqual(settings.api_key, "process-key")
                self.assertEqual(settings.model, "test-model")
                self.assertEqual(settings.base_url, "http://localhost:1234/v1")

    def test_aliases_disabled_dotenv_and_invalid_settings(self):
        with patch.dict(os.environ, {"LLM_API_KEY": "test-key", "LLM_MODEL": "test-model",
                                     "LLM_API_URL": "http://localhost/v1/chat/completions",
                                     "PYTHON_DOTENV_DISABLED": "1"}, clear=True):
            settings = Settings.load()
            self.assertTrue(settings.ready)
            self.assertEqual(settings.endpoint, "http://localhost/v1/chat/completions")
        with patch.dict(os.environ, {"OPENAI_TIMEOUT_SECONDS": "nan"}, clear=True):
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
        from test_agents import valid_plan
        from test_engine import fixed_game

        def response(request):
            context = json.loads(request["messages"][1]["content"])
            plan = valid_plan(context["game"])
            plan["mission"] = "SUCCESS"
            plan["social"]["statement"] = f"{context['game']['self']}：我会比较这次队伍与此前的公开表现。"
            return envelope(json.dumps(plan))

        with endpoint(response) as (url, requests):
            game = fixed_game()
            client = ChatClient(Settings(api_key="test", model="test", base_url=url))
            agents = {p: Agent(game.view(p), client) for p in game.ids if p != "P1"}
            human = Human(game.view("P1"), input_fn=lambda _: "", write=lambda _: None)
            output = []
            run_game(game, agents, human, write=output.append)
            self.assertEqual(game.successes, 3)
            self.assertTrue(any(e["kind"] == "ASSASSINATE" for e in game.events))
            self.assertEqual(len(requests), 14)  # R1 has a human leader; R2/R3 have agent leaders.
            contexts = [json.loads(r[2]["messages"][1]["content"]) for r in requests]
            counts = Counter((c["game"]["self"], c["game"]["round"],
                              c["game"]["attempt"], c["game"]["phase"]) for c in contexts)
            self.assertEqual(set(counts.values()), {1})
            speeches = [c["game"] for c in contexts if c["game"]["phase"] == "discussion"]
            self.assertEqual([c["self"] for c in speeches],
                             ["P2", "P3", "P4", "P5", "P2", "P3", "P4", "P5", "P3", "P4", "P5", "P2"])
            for view in speeches:
                before = [e for e in game.events if e["kind"] == "SOCIAL"
                          and e["round"] == view["round"] and e["attempt"] == view["attempt"]]
                index = next(i for i, event in enumerate(before) if event["actor"] == view["self"])
                actual = [e for e in view["recent_events"] if e["kind"] == "SOCIAL"
                          and e["round"] == view["round"] and e["attempt"] == view["attempt"]]
                self.assertEqual(actual, before[:index])
                self.assertTrue(view["team"])
            self.assertNotIn("PRIVATE_SENTINEL", "\n".join(output) + json.dumps(game.events))
            self.assertTrue(all(source == "llm" for a in agents.values() for source in a.sources.values()))


if __name__ == "__main__":
    unittest.main()
