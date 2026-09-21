"""Small, preregistered full-game validation for MerlinVoteCamouflageV3.

This is an evaluation-only adapter.  It uses the existing DeepSeek transport
for the focal Merlin, a deterministic population policy for the other seats,
and intercepts only the candidate arm's Merlin vote.  It never changes the
production Agent or Game defaults.
"""

from __future__ import annotations

import csv
import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any

from avalon.chronicle import context_record
from avalon.engine import EVIL_ROLES, make_players
from avalon.eval.simulation import canonical, digest, play_game
from avalon.eval.v2.live import BudgetLedger, Journal, LiveClient
from avalon.eval.v2.population import PopulationClient
from avalon.eval.v2.adapters import make_version
from avalon.eval.v2.v232_candidate_v2 import PublicVoteState
from avalon.eval.v2.v232_candidate_v3 import CANDIDATE, candidate_vote_decision
from avalon.llm import Settings


ROOT = Path(__file__).resolve().parents[3]
SEEDS = (960001, 960002, 960003, 960004, 960005, 960006)
PROFILE_BY_SEED = {
    960001: "heldout_blend", 960002: "heldout_patient", 960003: "heldout_blend",
    960004: "heldout_patient", 960005: "heldout_blend", 960006: "heldout_patient",
}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def scenario_players(seed: int):
    players = make_players(5, seed)
    focal = next(player for player in players if player.id == "P1")
    merlin = next(player for player in players if player.role == "MERLIN")
    if focal.role != "MERLIN":
        players = [replace(player, role=merlin.role) if player.id == focal.id else
                   replace(player, role=focal.role) if player.id == merlin.id else player
                   for player in players]
    return players


class V3HybridClient:
    """API-backed focal Merlin with a deterministic V3 vote override."""

    def __init__(self, *, seed: int, profile: str, arm: str, settings: Settings,
                 budget: BudgetLedger, journal: Journal, pair_id: str, decisions: list[dict[str, Any]]):
        self.arm = arm
        self.pair_id = pair_id
        self.focal = "P1"
        self.population = PopulationClient(seed, profile, focal=None)
        self.live = LiveClient(settings, budget, journal, {
            "stage": "v3_full_game", "pair_id": pair_id, "arm": arm,
        })
        self.decisions = decisions
        self.calls = self.context_bytes = 0

    def complete(self, context):
        self.calls += 1
        self.context_bytes += len(canonical(context).encode())
        view = context["view"]
        if view["self"] != self.focal:
            return self.population.complete(context)
        if self.arm == "candidate" and view["phase"] == "vote" and view["role"] == "MERLIN":
            events = [context_record(event) for event in context.get("public_event_history", [])]
            public = PublicVoteState(team=list(view["team"]), events=events,
                                     failures=int(view["failures"]), attempt=int(view["attempt"]))
            vote, policy = candidate_vote_decision(public, view)
            self.decisions.append({
                "pair_id": self.pair_id, "arm": self.arm, "round": view["round"],
                "attempt": view["attempt"], "team": list(view["team"]), "candidate_vote": vote,
                "policy": policy, "legal_view_hash": digest(view), "api_call_for_vote": False,
            })
            return {"approve": vote, "strong": False}
        return self.live.complete(context)


def _enrich(context, _observer):
    # play_game inserts the detached public event history immediately before
    # calling this hook.  Keep the context unchanged after that insertion.
    return context


def _row_metrics(record: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    truth = {player["id"]: player["role"] for player in record["players"]}
    candidate_rows = [event for event in record["events"] if event.get("kind") == "TEAM_VOTE"]
    clean_rejections = 0
    actual_clean_rejections = 0
    for event in candidate_rows:
        if event.get("approved"):
            continue
        team = event.get("team", [])
        if all(truth.get(pid) not in EVIL_ROLES for pid in team):
            actual_clean_rejections += 1
    row = dict(row)
    row["actual_clean_team_rejections"] = actual_clean_rejections
    row["full_game_completed"] = int(row.get("status") == "completed")
    row["good_win"] = row.get("good_win")
    return row


def run(out: Path, *, budget_cny: float = 20.0, max_calls: int = 600) -> dict[str, Any]:
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=False)
    settings = Settings.load()
    if not settings.ready:
        raise RuntimeError("configured API settings are not ready")
    if settings.base_url.rstrip("/") != "https://api.deepseek.com":
        raise RuntimeError("full-game validation requires the configured DeepSeek endpoint")
    settings.temperature = 0.0
    plan = {
        "run_id": out.name, "candidate": CANDIDATE, "frozen_before_execution": True,
        "seeds": list(SEEDS), "profiles": PROFILE_BY_SEED, "pairs": len(SEEDS),
        "focal": "P1 forced to Merlin", "other_seats": "deterministic PopulationClient",
        "baseline_arm": "DeepSeek focal Merlin action policy", "candidate_arm": "same API policy except V3 boolean vote override",
        "single_changed_variable": "Merlin boolean vote", "api_authorized_by_user": True,
        "full_game_authorized_by_user": True, "production_enablement": "blocked until outcome gate",
        "future_event_injection": False, "candidate_default": "OFF",
    }
    _write_json(out / "preregistered_full_game_plan.json", plan)
    budget = BudgetLedger(budget_cny, max_calls)
    journal = Journal(out / "llm_calls.jsonl")
    games: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    records_path = out / "full_game_replays.jsonl"
    with records_path.open("w", encoding="utf-8") as records:
        for seed in SEEDS:
            profile = PROFILE_BY_SEED[seed]
            pair_id = f"v3-full-{seed}"
            pair_rows = {}
            for arm in ("baseline", "candidate"):
                local_decisions: list[dict[str, Any]] = []
                client = V3HybridClient(seed=seed, profile=profile, arm=arm, settings=settings,
                                        budget=budget, journal=journal, pair_id=pair_id, decisions=local_decisions)
                row, _trace, record = play_game(
                    seed, "joint_v2", phase=f"v3_full_{arm}", model=settings.model, temperature=0.0,
                    player_setup=scenario_players(seed), focal="P1", all_seats=False,
                    belief_factory=make_version,
                    client_factory=lambda _seed, client=client: client,
                    capture_decisions=True, context_enricher=_enrich,
                )
                row = _row_metrics(record, row)
                row.update({"pair_id": pair_id, "profile": profile, "arm": arm,
                            "external_model_calls": client.live.external_calls,
                            "model_retries": client.live.retries,
                            "model_tokens": client.live.usage.get("total_tokens"),
                            "model_cost": client.live.estimated_cost,
                            "usage_missing_calls": client.live.usage_unknown,
                            "candidate_vote_override_count": len(local_decisions)})
                pair_rows[arm] = row
                decisions.extend(local_decisions)
                record.update({"pair_id": pair_id, "profile": profile, "arm": arm,
                               "status": row["status"], "error": row["error"]})
                records.write(canonical(record) + "\n")
                records.flush()
            if pair_rows["baseline"]["pair_signature"] != pair_rows["candidate"]["pair_signature"]:
                raise RuntimeError(f"pair controls differ for {pair_id}")
            games.extend(pair_rows.values())
    _write_csv(out / "games.csv", games)
    _write_json(out / "budget.json", budget.snapshot())
    _write_json(out / "candidate_decisions.json", decisions)
    complete = [row for row in games if row["status"] == "completed"]
    candidate_rows = [row for row in games if row["arm"] == "candidate"]
    baseline_rows = [row for row in games if row["arm"] == "baseline"]
    candidate_clean_rejections = sum(row["actual_clean_team_rejections"] for row in candidate_rows)
    baseline_clean_rejections = sum(row["actual_clean_team_rejections"] for row in baseline_rows)
    paired = []
    for seed in SEEDS:
        base = next(row for row in baseline_rows if row["seed"] == seed)
        cand = next(row for row in candidate_rows if row["seed"] == seed)
        paired.append({"pair_id": base["pair_id"], "seed": seed,
                       "baseline_status": base["status"], "candidate_status": cand["status"],
                       "baseline_winner": base["winner"], "candidate_winner": cand["winner"],
                       "baseline_good_win": base["good_win"], "candidate_good_win": cand["good_win"],
                       "baseline_merlin_assassinated": base["merlin_assassinated"],
                       "candidate_merlin_assassinated": cand["merlin_assassinated"],
                       "candidate_actual_clean_team_rejections": cand["actual_clean_team_rejections"]})
    hard_unsafe = candidate_clean_rejections > 0 or any(row["status"] != "completed" for row in candidate_rows)
    gate = "FULL_GAME_EFFECT_BUT_UNSAFE" if hard_unsafe else "FULL_GAME_VALIDATION_INCONCLUSIVE"
    result = {
        "run_id": out.name, "candidate": CANDIDATE, "gate": gate,
        "pairs": len(SEEDS), "games": len(games), "completed_games": len(complete),
        "candidate_completed": sum(row["status"] == "completed" for row in candidate_rows),
        "baseline_completed": sum(row["status"] == "completed" for row in baseline_rows),
        "candidate_actual_clean_team_rejections": candidate_clean_rejections,
        "baseline_actual_clean_team_rejections": baseline_clean_rejections,
        "candidate_good_wins": sum(row.get("good_win") == 1 for row in candidate_rows),
        "baseline_good_wins": sum(row.get("good_win") == 1 for row in baseline_rows),
        "candidate_merlin_assassinated": sum(row.get("merlin_assassinated") == 1 for row in candidate_rows),
        "baseline_merlin_assassinated": sum(row.get("merlin_assassinated") == 1 for row in baseline_rows),
        "network_calls": budget.calls, "budget": budget.snapshot(),
        "production_enablement": False, "candidate_default": "OFF",
        "future_events_injected": False, "paired_outcomes": paired,
        "full_game_effect_claim": "NOT_ESTABLISHED",
    }
    _write_json(out / "full_game_gate.json", result)
    _write_text(out / "report.md", f"""# V3 full-game validation

Run `{out.name}` used `{len(SEEDS)}` preregistered pairs (`{len(games)}` physical games) with the focal seat fixed to Merlin. The baseline and candidate arms used the configured DeepSeek transport for focal Merlin actions; the candidate arm intercepted only Merlin's boolean vote with `{CANDIDATE}`. Other seats used the deterministic population policy. Network/API attempts: `{budget.calls}`.

Gate: `{gate}`. Candidate actual clean-team rejections: `{candidate_clean_rejections}`; baseline: `{baseline_clean_rejections}`. Candidate good wins: `{sum(row.get('good_win') == 1 for row in candidate_rows)}`; baseline good wins: `{sum(row.get('good_win') == 1 for row in baseline_rows)}`. This is a small paired validation and does not establish a general win-rate or production-safety claim.

The candidate remains OFF. Production enablement was not performed because the offline V3 gate was unsafe and this run is outcome validation only.
""")
    return result


def _write_text(path: Path, value: str) -> None:
    path.write_text(value, encoding="utf-8")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--budget-cny", type=float, default=20.0)
    parser.add_argument("--max-calls", type=int, default=600)
    args = parser.parse_args()
    print(json.dumps(run(Path(args.run_dir), budget_cny=args.budget_cny, max_calls=args.max_calls), ensure_ascii=False, indent=2, sort_keys=True))
