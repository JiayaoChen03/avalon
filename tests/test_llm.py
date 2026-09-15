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

    def test_network_timeout_and_incomplete_http_body_fall_back(self):
        from avalon.agents import Agent
        from test_engine import fixed_game
        for options in ({"delay": 0.1}, {"broken_chunk": True}):
            with endpoint(envelope(), **options) as (url, requests):
                client = ChatClient(Settings(api_key="test", model="test", base_url=url, timeout=0.03))
                view = fixed_game().view("P1")
                agent = Agent(view, client)
                self.assertTrue(agent.prepare(view).startswith("fallback"))
                self.assertEqual(agent.mission(), "SUCCESS")
                self.assertEqual(len(requests), 1)

    def test_complete_human_game_over_real_http_uses_one_call_per_agent_per_round(self):
        from collections import Counter
        from avalon.agents import Agent
        from avalon.terminal import Human, run_game
        from test_agents import valid_plan
        from test_engine import fixed_game

        def response(request):
            context = json.loads(request["messages"][1]["content"])
            plan = valid_plan(context["game"])
            plan["mission"] = "SUCCESS"
            return envelope(json.dumps(plan))

        with endpoint(response) as (url, requests):
            game = fixed_game()
            client = ChatClient(Settings(api_key="test", model="test", base_url=url))
            agents = {p: Agent(game.view(p), client) for p in game.ids if p != "P1"}
            human = Human(game.view("P1"), input_fn=lambda _: "", write=lambda _: None)
            run_game(game, agents, human, write=lambda _: None, concurrency=3)
            self.assertEqual(game.successes, 3)
            self.assertTrue(any(e["kind"] == "ASSASSINATE" for e in game.events))
            self.assertEqual(len(requests), 12)
            contexts = [json.loads(r[2]["messages"][1]["content"]) for r in requests]
            counts = Counter((c["game"]["self"], c["game"]["round"]) for c in contexts)
            self.assertEqual(set(counts.values()), {1})
            self.assertTrue(all(source == "llm" for a in agents.values() for source in a.sources.values()))


if __name__ == "__main__":
    unittest.main()
