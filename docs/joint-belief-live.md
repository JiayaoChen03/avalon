# Opt-in DeepSeek action comparison

This is an independent, paid follow-up to the offline v2 suite. It reuses
`Settings.load`, `ChatClient`, the author's unchanged system prompt, production
plan/envelope/social validation and the actual `Game` loop. The current local
configuration is a DeepSeek Flash alias. The returned model/fingerprint is logged;
an alias does not pin immutable server weights. No credentials or reasoning text
are exported.

```bash
# Six predefined live smoke pairs after local tests and the frozen replay gate
.venv/bin/python -m avalon.eval.v2.live_runner --live --budget-cny 50 --max-calls 6000 --workers 8 --smoke-only --run-id deepseek-smoke-next

# Six smoke, 40 balanced single-seat pairs, four whole-table pairs,
# 117 paired fixed decisions and 10 identical-input repeats
.venv/bin/python -m avalon.eval.v2.live_runner --live --budget-cny 50 --max-calls 6000 --workers 8 --run-id deepseek-next

# No network: recompute summary, report and plots from raw exports
.venv/bin/python -m avalon.eval.v2.live_runner --report-only --run-dir results/joint_belief_v2/20260917-deepseek-v2-legal-context
```

Both `--live` and a positive `--budget-cny` are required. This run's authorization
is at most CNY 50; the CLI rejects larger ceilings. Every HTTP attempt reserves a
conservative UTF-8 byte bound plus framing allowance and the full output cap at
published peak prices. Concurrent requests share one locked ledger. Reported
usage releases unused reservations; unknown usage retains the whole reservation.
There is a separate call limit. Missing usage is unavailable, never fabricated
zero tokens. Costs are estimates from provider token counts, not account invoices.

Existing role permissions, hand/AP checks, game rules and belief versions are
unchanged. Forced single legal actions need no model request. Every other live
choice gets a fresh validated production plan. The model cannot supply numeric
beliefs or commit language factors. Bounded private inputs contain only that
observer's legitimate knowledge and the code's current marginals/joint team risk.
Truth and version/profile labels stay in the host-only export metadata. Invalid
responses get at most the configured retries; there is no scripted fallback.

Single-seat games retain the same multi-policy opponents as the earlier run.
Whole-table games use five LLM policies with either all v1 or all v2 observers;
this is distinct from the older offline table's one focal controlled policy and
four population policies. Offline-to-live differences change policy as well as
trajectories and therefore are descriptive, not belief-only treatment effects.

The first 40 main single-seat and first four table scenarios are frozen by prior
manifest order before any calls. Previously analyzed data are reused, not newly
unseen test data. The passive 120-game corpus is actually rerun for all six
belief versions and checked against the previous primary scores. Scenarios and
whole games are paired bootstrap units, never seats or event checkpoints.

`llm_calls.jsonl` records actual context/response hashes, final content, responses,
provider usage, timing, validation failures and retries. `games.csv` and
`paired_outcomes.csv` retain failures and real terminal outcomes. Full posterior
exports remain in `hypothesis_trace.jsonl.gz`. Fixed decision records additionally
include each posterior, legal input hashes and both actions; repeat requests
measure observed server variation at identical temperature-zero inputs. Even
with temperature zero, server determinism is not assumed.

This run tests the action dimension only. The separately specified natural
language interpretation experiment remains `not_run`; natural-language output
never becomes an extra belief factor. The 40/4 live sample does not replace the
200/20 offline evaluation and is not a power guarantee.

The legal input includes a phase-specific machine response contract, not a changed
system prompt. Visible mission summaries remain valid citation sources even when
the original mission event leaves the recent-event window. The validator projects
the summary back to its original canonical event ID; it never inserts evidence
into belief history. Retries show the rejected action, actual legal options and
visible citation IDs. No output is rewritten into a different model decision.

The September 17 session retains two earlier protocol diagnostic runs. The final
run caps additional spending at CNY 46.33 and 5,326 attempts after reserving prior
costs/calls, so the entire session remains below CNY 50 and 6,000 attempts. The
191-test unit gate reruns after the repairs. The passed 405-test full repository
gate and 120-game passive exports from the same session are reused only after
checking unchanged rule/inference source hashes, and this reuse is explicit in
config.json. Earlier failed games are never pooled into final effect samples.
