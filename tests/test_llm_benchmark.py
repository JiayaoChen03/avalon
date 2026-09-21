"""Benchmark checks use a local HTTP endpoint; they never call a paid API."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from avalon.llm import Settings
from scripts.benchmark_llm_concurrency import fixtures, record_transport, run_batch, summarize
from test_agents import valid_plan
from test_llm import endpoint, envelope


def response(body):
    context = json.loads(body["messages"][1]["content"])
    plan = valid_plan(context["game"])
    plan.update(discussion={"kind": "SOCIAL"}, revision={"kind": "LOCK"}, strong_vote=False)
    if "tactical" in context:
        plan["social"].update(target=context["tactical"]["primary_target"],
                             card=context["tactical"]["allowed_cards"][0])
        plan = {k: plan[k] for k in ("social", "discussion", "revision", "strong_vote")}
    result = envelope(json.dumps(plan, ensure_ascii=False))
    result.update(model="test-model", usage={"prompt_tokens": 100, "completion_tokens": 50,
                                             "total_tokens": 150, "prompt_cache_hit_tokens": 80,
                                             "prompt_cache_miss_tokens": 20})
    return result


class BenchmarkTests(unittest.TestCase):
    def test_concurrent_requests_preserve_inputs_validation_and_private_boundaries(self):
        cases = fixtures()
        original_events = [deepcopy(c["game"].events) for c in cases]
        with tempfile.TemporaryDirectory() as directory, endpoint(response) as (url, requests):
            settings = Settings(api_key="TEST_KEY_MUST_NOT_APPEAR", model="test-model", base_url=url)
            with record_transport():
                batch = run_batch(cases, settings, 4, 1, Path(directory))
            self.assertEqual(batch["valid_jobs"], 4)
            self.assertEqual(len(requests), 4)
            for row, case in zip(batch["jobs"], cases):
                self.assertEqual(row["attempts"][0]["context_sha256"], case["context_sha256"])
                self.assertEqual(row["attempts"][0]["usage"]["total_tokens"], 150)
                self.assertEqual(row["http_attempts"], 1)
            self.assertEqual(original_events, [c["game"].events for c in cases])
            saved = (Path(directory) / "requests.jsonl").read_text()
            for forbidden in ("TEST_KEY_MUST_NOT_APPEAR", "PRIVATE_SENTINEL", "known_evil", '"beliefs"', '"profiles"'):
                self.assertNotIn(forbidden, saved)
            self.assertEqual(summarize([batch])["4"]["usage_totals"]["total_tokens"], 600)

    def test_retry_latency_and_usage_are_included(self):
        counts = {}

        def invalid_then_valid(body):
            context = json.loads(body["messages"][1]["content"])
            pid = context["game"]["self"]
            counts[pid] = counts.get(pid, 0) + 1
            result = response(body)
            if counts[pid] == 1:
                result["choices"][0]["message"]["content"] = '{"wrong": true}'
            return result

        with tempfile.TemporaryDirectory() as directory, endpoint(invalid_then_valid) as (url, requests):
            settings = Settings(api_key="test", model="test", base_url=url, max_retries=1, retry_delay=0)
            with record_transport():
                batch = run_batch(fixtures(), settings, 2, 1, Path(directory))
            self.assertEqual(batch["valid_jobs"], 4)
            self.assertEqual(len(requests), 8)
            for row in batch["jobs"]:
                self.assertEqual(row["retries"], 1)
                self.assertEqual(row["attempts"][0]["error"], "invalid_plan")
                self.assertGreaterEqual(row["job_wall_s"] + 0.00001,
                                        sum(a["http_wall_s"] for a in row["attempts"]))
            self.assertEqual(summarize([batch])["2"]["usage_totals"]["total_tokens"], 1200)


if __name__ == "__main__":
    unittest.main()
