"""Joint Belief v2.3: Merlin disclosure candidate, offline first, paid opt-in."""
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import datetime, timezone
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import xml.etree.ElementTree as ET

from avalon.chronicle import PUBLIC_KINDS, context_record
from avalon.engine import EVIL_ROLES
from avalon.eval.joint_belief import ROOT, git_info
from avalon.eval.simulation import canonical, digest, play_game, policy_context
from avalon.eval.v2.adapters import make_version
from avalon.eval.v2.experiments import scenario_players
from avalon.eval.v2.v21_data import population
from avalon.eval.v2.v21_contract import (ADAPTER_REVISION, POLICY_CURRENT, enrich_context,
                                          legal_menu, menu_context)
from avalon.eval.v2.v21_data import input_for as v21_input_for
from avalon.eval.v2.v21_runtime import (Cancelled, DurableBudget, Session, atomic_json,
                                         json_read, BudgetStop)
from avalon.eval.v2.v21_runner import compatible as v21_compatible
from avalon.eval.v2.v23_data import generate_source, write_plan
from avalon.eval.v2.v23_diagnostics import (analyze_assassin_signals, sha256, verify_source,
                                             read_jsonl)
from avalon.eval.v2.v23_merlin import (MERLIN_DISCLOSURE_REVISION, Journal, MerlinMenuClient,
                                       menu_context_v23)
from avalon.llm import ChatClient, Settings


V22_RUN = ROOT / "results/joint_belief_v2_2/20260918-v22-r7-offline"
R7_RUN = ROOT / "results/joint_belief_v2_1/20260918-v21-r7-live-75"
ATTACHMENT = Path("/Users/jiayaochen/Desktop/codex_joint_belief_v2_3_merlin_concealment.md")
TOTAL_BUDGET = 20.0
PILOT_CAP = 5.0
MAX_HTTP_ATTEMPTS = 1500
MODEL_MAX_TOKENS = 900


def _json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_csv(path, rows, fields=None):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    rows = list(rows)
    if fields is None:
        fields = list(rows[0]) if rows else []
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader(); writer.writerows(rows)


def _current_hashes():
    paths = [
        "avalon/engine.py", "avalon/chronicle.py", "avalon/evidence.py", "avalon/cognition.py",
        "avalon/joint_beliefs.py", "avalon/mission_likelihood.py", "avalon/eval/simulation.py",
        "avalon/eval/v2/adapters.py", "avalon/eval/v2/v21_contract.py", "avalon/eval/v2/v21_runtime.py",
        "avalon/eval/v2/v21_data.py", "avalon/eval/v2/v23_merlin.py", "avalon/eval/v2/v23_data.py",
        "avalon/eval/v2/v23_diagnostics.py", "avalon/eval/v2/v23_runner.py",
        "prompts/corrupted_castle_system.md", "docs/joint-belief-v21.md", "docs/joint-belief-v22.md",
        "codex_joint_belief_v2_3_merlin_concealment.md",
    ]
    result = {}
    for name in paths:
        path = ROOT / name
        if path.exists(): result[name] = sha256(path)
    return result


def _source_and_dataset(out):
    return list(read_jsonl(Path(out) / "v23_source_replays.jsonl")), _json(Path(out) / "dataset_manifest.json")


def prepare(args):
    out = args.run_dir.resolve()
    out.mkdir(parents=True, exist_ok=False)
    if not V22_RUN.exists() or not R7_RUN.exists():
        raise FileNotFoundError("v2.2/r7 source run is missing")
    source_audit = verify_source(V22_RUN, R7_RUN, ATTACHMENT)
    records = generate_source(out)
    plan = write_plan(out, records)
    cfg = {
        "run_id": out.name, "created_utc": datetime.now(timezone.utc).isoformat(), "status": "prepared",
        "source_run_id": source_audit["source_run_id"], "diagnostic_source_run": V22_RUN.name,
        "source_split": {"r7": "development/diagnostic", "v22": "diagnostic reuse", "v23": "new controlled scenes"},
        "live": False, "budget_cny": TOTAL_BUDGET, "pilot_cumulative_cap_cny": PILOT_CAP,
        "api_permission": "limited_deepseek_testing", "candidate_enabled_by_default": False,
        "experiment_candidate_enabled": True, "vote_v22_candidate_enabled": False,
        "recursive_tom_enabled": False, "language_belief_factors_enabled": False,
        "cross_game_memory_enabled": False, "max_http_attempts": MAX_HTTP_ATTEMPTS,
        "max_concurrency": 2, "model_max_tokens": MODEL_MAX_TOKENS,
        "adapter_revision": ADAPTER_REVISION, "belief_revision": "joint_v2",
        "policy_revision": POLICY_CURRENT, "context_revision": "r7-base-menu-context",
        "candidate_context_revision": MERLIN_DISCLOSURE_REVISION,
        "rules_and_assassin_frozen": True, "settings_source": "v2.1/r7 redacted config; live uses current DeepSeek env after preflight",
        "opponent_mode": "controlled_population_pilot",
        "opponent_mode_reason": "Non-focal seats use the existing reproducible controlled population in both arms; this is not equivalent to r7 all-seat model configuration.",
        "source_manifest_hashes": source_audit["hashes"], "source_current_hashes": _current_hashes(),
        "git": git_info(), "tests": {}, "new_model_samples": 0,
        "new_effect_primary": "focal Merlin GOOD alignment win, paired by scenario",
        "history_not_counted_as_new_samples": True,
    }
    atomic_json(out / "config.json", cfg)
    atomic_json(out / "source_manifest.json", {"git": git_info(), "hashes": _current_hashes(),
        "source_hashes": source_audit, "AGENTS_found": [], "production_default_changed": False,
        "source_role": "v2.2/r7 read-only; v2.3 controlled source scenes generated without model calls"})
    atomic_json(out / "dataset_manifest.json", plan)
    atomic_json(out / "budget_preflight.json", {"status": "not_run_until_live_preflight",
        "total_cap_cny": TOTAL_BUDGET, "pilot_cap_cny": PILOT_CAP, "known_usage_cny": 0.0,
        "unknown_usage_reserve_cny": None, "in_flight_reserve_cny": None,
        "network_calls": 0, "sample_plan_frozen": True})
    (out / "codex_joint_belief_v2_3_merlin_concealment.md").write_text(ATTACHMENT.read_text(encoding="utf-8"), encoding="utf-8")
    (out / "candidate_spec.md").write_text(
        "# MerlinDisclosureContext v2.3\n\n"
        "The production candidate is off by default. When enabled it adds one compact\n"
        "private context field only for a Merlin `discussion` or `council_discussion`\n"
        "decision. The field is generated from public event IDs, public mechanical\n"
        "constraints and the Merlin seat's legal view. Claims remain claims; a failed\n"
        "team is not converted into a named evil player, and a successful mission is\n"
        "not proof that the team is clean. The joint_v2 posterior, evidence factors,\n"
        "legal menu, Game transaction, Assassin argmax/tie handling and all other seats\n"
        "remain unchanged. The host never rewrites a legal model action.\n\n"
        "Vote DecisionContext v2.2 is disabled. Language evidence, recursive ToM and\n"
        "cross-game memory remain disabled.\n",
        encoding="utf-8")
    (out / "prechange_audit.md").write_text(
        "# v2.3 prechange audit\n\n"
        f"Primary diagnostic: `{V22_RUN}` (run_id `{V22_RUN.name}`), exact r7 source `{R7_RUN}`.\n\n"
        "Verified requested v2.2 tables, summary/config/source hashes and the r7 model\n"
        "request/replay archives. No AGENTS.md was present in the repository or parents.\n"
        "The v2.2 report describes a development/diagnostic corpus and does not prove a\n"
        "Merlin phrase cause. Code review found that Assassin action decoding uses the\n"
        "native Merlin marginal argmax; the submitted permutation only resolves exact\n"
        "ties. Public writing is present in the public context, but action-only requests\n"
        "do not submit language evidence to the posterior.\n\n"
        "Frozen main comparison: joint_v2 + current menu policy, with the candidate off\n"
        "versus the same arm with only MerlinDisclosureContext enabled during public\n"
        "SOCIAL stages. v2.2 vote candidate remains disabled.\n",
        encoding="utf-8")
    # Keep the full audit table tied to the immutable source before any live run.
    analyze_assassin_signals(V22_RUN, R7_RUN, out)
    return cfg


def _contexts_for_snapshot(spec, records):
    record = records[spec["source_game_id"]]
    decision = record["decisions"][spec["decision_index"]]
    # v21's reconstruction owns role-authorized posterior replay; the v2.3
    # context builder is layered only after this frozen legal input.
    contexts, truth, observers = v21_input_for(spec, records)
    return contexts["joint_v2"], truth, observers["joint_v2"], record, decision


def offline(out):
    out = Path(out); records, plan = _source_and_dataset(out)
    by_id = {r["game_id"]: r for r in records}
    rows = []
    for spec in plan["fixed"]:
        context, truth, observer, record, decision = _contexts_for_snapshot(spec, by_id)
        base = menu_context_v23(context, POLICY_CURRENT, enabled=False)
        candidate = menu_context_v23(context, POLICY_CURRENT, enabled=True)
        rows.append({"snapshot_id": spec["snapshot_id"], "source_game_id": spec["source_game_id"],
                     "experiment": spec["experiment"], "phase": spec["phase"], "observer_role": "MERLIN",
                     "arm": "reference", "status": "not_run", "legal_view_hash": digest(context["view"]),
                     "posterior_hash": context["posterior_hash"], "base_context_hash": digest(base),
                     "candidate_context_hash": digest(candidate), "aid_present": False,
                     "menu_hash": digest(base["action_menu"]), "same_menu": True,
                     "aid_bytes": 0, "split": spec["split"]})
        aid = candidate.get("merlin_disclosure_context")
        rows.append({"snapshot_id": spec["snapshot_id"], "source_game_id": spec["source_game_id"],
                     "experiment": spec["experiment"], "phase": spec["phase"], "observer_role": "MERLIN",
                     "arm": "candidate", "status": "not_run", "legal_view_hash": digest(context["view"]),
                     "posterior_hash": context["posterior_hash"], "base_context_hash": digest(base),
                     "candidate_context_hash": digest(candidate), "aid_present": bool(aid),
                     "menu_hash": digest(candidate["action_menu"]), "same_menu": candidate["action_menu"] == base["action_menu"],
                     "aid_bytes": len(canonical(aid).encode("utf-8")) if aid else 0, "split": spec["split"]})
    _write_csv(out / "snapshot_results.csv", rows)
    atomic_json(out / "offline_validation.json", {
        "status": "passed" if all(r["same_menu"] for r in rows) else "failed",
        "snapshots": len(rows) // 2, "arms": len(rows), "candidate_actions": "not_run",
        "posterior_unchanged": True, "vote_v22_candidate_enabled": False,
        "network_calls": 0, "new_model_samples": 0,
    })
    return rows


class V23Budget(DurableBudget):
    """Shared durable budget with a cumulative pilot cap and no reset on phase."""
    def __init__(self, folder, cny, max_calls):
        super().__init__(folder, cny, max_calls)
        self.phase_lock = threading.Lock()
        self.phase = None; self.phase_cap = None
        self.phase_charged = 0.0; self.phase_pending = 0.0
        self._reload_phase("pilot")

    def _reload_phase(self, phase):
        charged = pending = 0.0
        for req in self.requests.glob("*.request.json"):
            item = json_read(req)
            # `phase` in a request is the production view phase (discussion,
            # vote, ...).  `run_phase` is the durable pilot/main accounting
            # boundary and survives process restart.
            meta = item.get("run_phase") or item.get("budget_phase")
            # Requests created by the first offline/live smoke implementation
            # predate run_phase.  They all belong to this run's pilot because
            # main was never entered before this migration.
            if meta is None:
                meta = "pilot"
            if meta != phase: continue
            response = req.with_name(req.name.replace(".request.json", ".response.json"))
            if response.exists():
                charged += float(json_read(response).get("budget_charged_cny", item["reservation"]["cny"]))
            else:
                pending += float(item["reservation"]["cny"])
        self.phase_charged, self.phase_pending = charged, pending

    def _phase_totals(self, phase):
        charged = pending = 0.0
        for req in self.requests.glob("*.request.json"):
            item = json_read(req)
            item_phase = item.get("run_phase") or item.get("budget_phase") or "pilot"
            if item_phase != phase:
                continue
            response = req.with_name(req.name.replace(".request.json", ".response.json"))
            if response.exists():
                charged += float(json_read(response).get("budget_charged_cny", item["reservation"]["cny"]))
            else:
                pending += float(item["reservation"]["cny"])
        return charged, pending

    def set_phase(self, phase, cap=None):
        with self.phase_lock:
            self.phase, self.phase_cap = phase, cap
            self._reload_phase(phase)

    def begin(self, payload, metadata):
        phase = metadata.get("run_phase") or metadata.get("budget_phase") or metadata.get("phase") or self.phase
        tokens = sum(len(m["content"].encode("utf-8")) for m in payload["messages"]) + 1024
        output = payload.get("max_tokens", payload.get("max_completion_tokens"))
        bound = (tokens * 2.0 + output * 8.0) / 1e6
        with self.phase_lock:
            if phase == self.phase and self.phase_cap is not None and self.phase_charged + self.phase_pending + bound > self.phase_cap:
                raise BudgetStop("v2.3 phase budget cap reached; no request sent")
            # Preserve the production view phase in the request metadata and
            # add the durable run phase as a separate field.
            uid, reservation = super().begin(payload, {**metadata, "run_phase": phase})
            if phase == self.phase: self.phase_pending += reservation["cny"]
            return uid, reservation

    def finish(self, uid, row):
        super().finish(uid, row)
        phase = row.get("run_phase") or row.get("budget_phase") or self.phase
        with self.phase_lock:
            if phase == self.phase:
                self.phase_pending = max(0.0, self.phase_pending - float(row.get("reservation", {}).get("cny", 0.0)))
                self.phase_charged += float(row.get("budget_charged_cny", row.get("reservation", {}).get("cny", 0.0)))

    def snapshot(self):
        row = super().snapshot()
        pilot_charged, pilot_pending = self._phase_totals("pilot")
        main_charged, main_pending = self._phase_totals("main")
        row.update({"current_phase": self.phase, "phase_cap_cny": self.phase_cap,
                    "phase_charged_cny": self.phase_charged, "phase_pending_cny": self.phase_pending,
                    "pilot_cumulative_cap_cny": PILOT_CAP,
                    "pilot_phase_charged_cny": pilot_charged,
                    "pilot_phase_pending_cny": pilot_pending,
                    "main_phase_charged_cny": main_charged,
                    "main_phase_pending_cny": main_pending})
        return row


class HybridV23:
    def __init__(self, spec, live):
        self.spec, self.live = spec, live
        self.other = population(spec["seed"], spec["profile"])
        self.calls = self.context_bytes = 0

    def bind(self, binding): self.live.bind(binding)

    def complete(self, context):
        self.calls += 1; self.context_bytes += len(canonical(context).encode("utf-8"))
        return self.live.complete(context) if context["view"]["self"] == self.spec["focal"] else self.other.complete(context)


def _meta(out, spec, arm, stage, run_phase=None):
    return {"run_id": out.name, "experiment": spec.get("experiment", "A"),
            "scenario_id": spec.get("scenario_id") or spec.get("snapshot_id"),
            "source_game_id": spec.get("source_game_id"),
            "observer_id": spec.get("observer_id", spec.get("focal")), "variant": arm,
            "arm": arm, "stage": stage, "policy_revision": POLICY_CURRENT,
            "adapter_revision": ADAPTER_REVISION, "candidate_context_revision":
                MERLIN_DISCLOSURE_REVISION if arm == "candidate" else "r7-base-menu-context",
            "scope": spec.get("scope"), "snapshot_id": spec.get("snapshot_id"),
            "repeat_index": spec.get("repeat_index", 0), "phase": spec.get("phase"),
            "run_phase": run_phase or spec.get("run_phase") or spec.get("phase")}


def _arm_enabled(arm): return arm == "candidate"


def _job_id(spec, arm): return digest([spec.get("experiment"), spec.get("scenario_id"), arm,
                                       spec.get("snapshot_id"), spec.get("repeat_index", 0)])[:24]


def active_job(out, spec, arm, settings, budget, cancel, run_phase=None):
    meta = _meta(out, spec, arm, "active", run_phase=run_phase)
    key = _job_id(spec, arm); job_path = out / "jobs" / (key + ".json")
    if job_path.exists() and _json(job_path).get("status") in {"completed", "failed", "budget_stopped"}:
        return _json(job_path)
    job_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(job_path, {**meta, "status": "running", "started_utc": datetime.now(timezone.utc).isoformat()})
    journal = Journal(out / "llm_calls.jsonl")
    disclosure = Journal(out / "disclosure_trace.jsonl")
    client = MerlinMenuClient(settings, budget, meta, POLICY_CURRENT, _arm_enabled(arm), cancel, journal, disclosure)
    hybrid = HybridV23(spec, client)
    session = Session(out / "checkpoints" / key / "state.json",
                      {"game_id": f"{out.name}:{key}", "config": _json(out / "config.json")["run_id"], "metadata": meta})
    def factory(variant, view, _=None):
        return make_version("joint_v2" if variant in {"reference", "candidate"} else variant, view)
    row, _, record = play_game(spec["seed"], arm, phase=f"{spec['experiment']}-{spec['phase']}-{spec['scope']}",
        model=settings.model, temperature=settings.temperature or 0., player_setup=scenario_players(spec),
        focal=spec["focal"], all_seats=False, belief_factory=factory,
        client_factory=lambda _: hybrid, capture_decisions=True, session=session,
        context_enricher=enrich_context)
    row.update(meta, belief_variant="joint_v2", pair_id=spec["scenario_id"], policy_revision=POLICY_CURRENT,
               candidate_enabled=_arm_enabled(arm), external_model_calls=client.external_calls,
               pair_signature=digest({"spec": spec, "arm_settings": _json(out / "config.json").get("settings", {}),
                                      "candidate": _arm_enabled(arm)}))
    if row["status"] != "completed":
        row["status"] = "budget_stopped" if "BudgetStop" in row.get("error", "") else row["status"]
    record.update(meta, status=row["status"], error=row["error"], candidate_enabled=_arm_enabled(arm))
    (out / "active_replays").mkdir(exist_ok=True)
    atomic_json(out / "active_replays" / (key + ".json"), record)
    atomic_json(job_path, row)
    return row


def fixed_job(out, spec, arm, settings, budget, cancel, records, repeat=False, run_phase=None):
    meta = _meta(out, spec, arm, "fixed_repeat" if repeat else "fixed_snapshot", run_phase=run_phase)
    key = _job_id(spec, arm); job_path = out / "jobs" / (key + ".json")
    if job_path.exists() and _json(job_path).get("status") in {"completed", "failed", "budget_stopped"}:
        return _json(job_path)
    context, truth, observer, record, decision = _contexts_for_snapshot(spec, records)
    context["public_event_history"] = [context_record(e) for e in record["events"]
                                        if e["kind"] in PUBLIC_KINDS and e["seq"] <= decision["after_seq"]]
    context = enrich_context(context, observer)
    base = menu_context_v23(context, POLICY_CURRENT, enabled=False)
    supplied = menu_context_v23(context, POLICY_CURRENT, enabled=_arm_enabled(arm))
    journal = Journal(out / "llm_calls.jsonl"); disclosure = Journal(out / "disclosure_trace.jsonl")
    client = MerlinMenuClient(settings, budget, meta, POLICY_CURRENT, _arm_enabled(arm), cancel, journal, disclosure)
    job_path.parent.mkdir(parents=True, exist_ok=True)
    row = {**meta, "status": "completed", "error": None, "observer_role": "MERLIN",
           "belief_variant": "joint_v2", "candidate_enabled": _arm_enabled(arm),
           "legal_view_hash": digest(context["view"]), "posterior_hash": context["posterior_hash"],
           "base_context_hash": digest(base), "model_context_hash": digest(supplied),
           "menu_hash": digest(supplied["action_menu"]), "aid_present": "merlin_disclosure_context" in supplied,
           "aid_bytes": len(canonical(supplied.get("merlin_disclosure_context", {})).encode("utf-8")),
           "reference_action": decision.get("action"), "action": None,
           "counterfactual_execution": "not_run; frozen legal snapshot only"}
    session = Session(out / "checkpoints" / key / "state.json",
                      {"game_id": f"{out.name}:{key}", "config": _json(out / "config.json")["run_id"], "metadata": meta})
    try:
        row["action"] = session.choose(context, client)
        row["action_changed_from_source"] = int(row["action"] != decision.get("action"))
        row["same_menu_reference"] = supplied["action_menu"] == base["action_menu"]
    except (RuntimeError, ValueError, TypeError, KeyError) as exc:
        row.update(status="budget_stopped" if isinstance(exc, BudgetStop) or "BudgetStop" in str(exc) else "failed",
                   error=f"{type(exc).__name__}: {exc}")
    atomic_json(job_path, row)
    return row


def _run_batch(out, specs, settings, budget, workers, records, stage, cancel, repeat=False):
    rows = []
    def one(spec):
        result = []
        for arm in spec.get("order", spec.get("arms", ["reference", "candidate"])):
            if cancel.is_set(): break
            result.append(fixed_job(out, spec, arm, settings, budget, cancel, records, repeat=repeat,
                                    run_phase=stage)
                          if spec.get("scope", "").startswith("fixed") else
                          active_job(out, spec, arm, settings, budget, cancel, run_phase=stage))
        return result
    with ThreadPoolExecutor(max_workers=max(1, min(workers, 2))) as pool:
        futures = [pool.submit(one, s) for s in specs]
        for future in as_completed(futures):
            batch = future.result(); rows.extend(batch)
            atomic_json(out / "budget_ledger.json", budget.snapshot())
            if any(r.get("status") == "budget_stopped" for r in batch): cancel.set()
    return rows


def _settings_from_config(out):
    cfg = _json(out / "config.json")
    redacted = _json(V22_RUN / "config.json").get("settings", {})
    loaded = Settings.load()
    if not loaded.ready or not loaded.base_url.rstrip("/").endswith("api.deepseek.com"):
        raise ValueError("Valid DeepSeek credentials/configuration required after budget preflight")
    if loaded.model not in {"deepseek-v4-flash", "deepseek-flash"}:
        raise ValueError("Configured model is not the frozen DeepSeek Flash mapping")
    settings = replace(loaded, temperature=0.0, max_tokens=MODEL_MAX_TOKENS,
                       token_field=redacted.get("token_field", "max_tokens"), json_mode=True,
                       max_retries=2)
    cfg["settings"] = {k: v for k, v in asdict(settings).items() if k != "api_key"}
    cfg["settings_hash"] = digest(cfg["settings"])
    atomic_json(out / "config.json", cfg)
    return settings


def _preflight(out, plan):
    # Use the frozen r7 reservation distribution only as a conservative estimate;
    # actual atomic reservations remain the hard gate. No credentials are loaded.
    r7_rows = []
    for item in read_jsonl(R7_RUN / "llm_calls.jsonl"):
        if item.get("observer_role") == "MERLIN" and item.get("phase") in {"discussion", "council_discussion"}:
            r7_rows.append(float(item.get("reservation", {}).get("cny", 0.0)))
    per_request = max(r7_rows or [0.05])
    pilot_calls = len(plan["development_snapshots"]) * 2 + len(plan["repeats"]) + len(plan["smoke"]) * 2 * 18
    main_calls = len(plan["sealed_snapshots"]) * 2 + len(plan["active"]) * 2 * 18
    estimate = {"per_request_peak_reserve_cny": per_request, "pilot_expected_calls": pilot_calls,
                "main_expected_calls": main_calls, "pilot_bound_cny": pilot_calls * per_request,
                "total_bound_cny": (pilot_calls + main_calls) * per_request,
                "pilot_cap_cny": PILOT_CAP, "total_cap_cny": TOTAL_BUDGET,
                "unknown_usage_reserve_policy": "DurableBudget charges full reservation; never writes unknown usage as zero",
                "network_calls": 0, "target_plan_frozen_before_response": True}
    estimate["status"] = "within_plan" if estimate["pilot_bound_cny"] <= PILOT_CAP and estimate["total_bound_cny"] <= TOTAL_BUDGET else "blocked_by_conservative_estimate"
    atomic_json(out / "budget_preflight.json", estimate)
    if estimate["status"] != "within_plan":
        raise ValueError("Budget preflight cannot contain the already frozen sample plan")
    return estimate


def live(args):
    out = args.run_dir.resolve(); cfg = _json(out / "config.json")
    if not args.live or args.budget_cny != TOTAL_BUDGET:
        raise ValueError("Explicit --live --budget-cny 20 required; historical budget is not inherited")
    if cfg.get("budget_cny") != TOTAL_BUDGET:
        raise ValueError("Run config budget mismatch")
    plan = _json(out / "dataset_manifest.json"); records, _ = _source_and_dataset(out)
    by_id = {r["game_id"]: r for r in records}
    _preflight(out, plan)
    tests = cfg.get("tests", {})
    if not tests.get("unit", {}).get("exit_code") == 0 or not tests.get("regression", {}).get("exit_code") == 0:
        raise ValueError("Unit and regression gates must pass before live requests")
    settings = _settings_from_config(out)
    # _settings_from_config persists the redacted settings hash.  Reload here
    # so the final status update cannot overwrite it with the preflight copy.
    cfg = _json(out / "config.json")
    budget = V23Budget(out, TOTAL_BUDGET, MAX_HTTP_ATTEMPTS)
    cancel = threading.Event()
    cfg.update(status="running", live=True, live_started_utc=datetime.now(timezone.utc).isoformat())
    atomic_json(out / "config.json", cfg)
    try:
        budget.set_phase("pilot", PILOT_CAP)
        pilot_specs = []
        pilot_specs += plan["fixed"][:len(plan["development_snapshots"])]
        pilot_specs += plan["repeats"]
        pilot_specs += plan["smoke"]
        _run_batch(out, pilot_specs, settings, budget, 2, by_id, "pilot", cancel)
        report_only(out)
        gate = smoke_gate(out, plan)
        atomic_json(out / "smoke_gate.json", gate)
        if not gate["passed"] or args.mode == "smoke":
            cfg["stop_reason"] = "smoke_gate_failed" if not gate["passed"] else "requested_smoke_only"
            return
        budget.set_phase("main", None)
        main_specs = plan["fixed"][len(plan["development_snapshots"]):] + plan["active"]
        _run_batch(out, main_specs, settings, budget, 2, by_id, "main", cancel)
        cfg["stop_reason"] = "planned_jobs_drained" if not cancel.is_set() else "budget_or_failure_stop"
    except (BudgetStop, KeyboardInterrupt) as exc:
        cfg["stop_reason"] = "budget_stopped" if isinstance(exc, BudgetStop) else "cancelled"
    finally:
        cfg.update(status="stopped", live_ended_utc=datetime.now(timezone.utc).isoformat(),
                   new_model_samples=sum(1 for _ in read_jsonl(out / "llm_calls.jsonl")) if (out / "llm_calls.jsonl").exists() else 0)
        atomic_json(out / "config.json", cfg); atomic_json(out / "budget_ledger.json", budget.snapshot())
        report_only(out)


def smoke_gate(out, plan):
    rows = [_json(p) for p in (Path(out) / "jobs").glob("*.json")]
    smoke = [r for r in rows if r.get("stage") == "active" and str(r.get("scenario_id", "")).startswith("smoke-")]
    by_pair = defaultdict(list)
    for row in smoke: by_pair[row.get("scenario_id")].append(row)
    pair_status = []
    for sid in sorted(by_pair):
        arms = by_pair[sid]
        pair_status.append({"scenario_id": sid, "arms": len(arms),
                            "complete": len(arms) == 2 and all(r.get("status") == "completed" for r in arms),
                            "menu_and_state_check": all(r.get("error") in (None, "") for r in arms)})
    passed = len(pair_status) == len(plan["smoke"]) and all(x["complete"] and x["menu_and_state_check"] for x in pair_status)
    return {"passed": passed, "criterion": "all planned smoke arms complete, legal, and transaction-consistent; win rate is not used",
            "planned_pairs": len(plan["smoke"]), "observed_pairs": len(pair_status), "pairs": pair_status,
            "failure_classification": dict(Counter(r.get("status") for r in smoke))}


def _job_rows(out):
    return [_json(p) for p in sorted((Path(out) / "jobs").glob("*.json"))]


def report_only(out):
    out = Path(out); cfg = _json(out / "config.json"); plan = _json(out / "dataset_manifest.json")
    jobs = _job_rows(out)
    games = [r for r in jobs if r.get("stage") == "active"]
    snapshots = [r for r in jobs if r.get("stage") in {"fixed_snapshot", "fixed_repeat"}]
    _write_csv(out / "games.csv", games)
    grouped = defaultdict(dict)
    for row in games: grouped[row.get("scenario_id")][row.get("arm")] = row
    plan_by_scenario = {s.get("scenario_id"): s for s in plan.get("smoke", []) + plan.get("active", [])}
    paired = []
    for sid, arms in sorted(grouped.items()):
        ref, cand = arms.get("reference"), arms.get("candidate")
        plan_spec = plan_by_scenario.get(sid, {})
        pair = {"scenario_id": sid, "reference_status": ref.get("status") if ref else "not_run",
                "candidate_status": cand.get("status") if cand else "not_run",
                "split": plan_spec.get("split", "unknown"),
                "phase": plan_spec.get("phase", "unknown"),
                "experiment": plan_spec.get("experiment", "A"),
                "reference_focal_win": ref.get("focal_win") if ref and ref.get("status") == "completed" else None,
                "candidate_focal_win": cand.get("focal_win") if cand and cand.get("status") == "completed" else None,
                "complete_pair": int(bool(ref and cand and ref.get("status") == cand.get("status") == "completed")),
                "focal_role": (ref or cand or {}).get("focal_role", "MERLIN"),
                "terminal_reference": ref.get("terminal_reason") if ref else None,
                "terminal_candidate": cand.get("terminal_reason") if cand else None}
        pair["cell"] = ("both_win" if pair["reference_focal_win"] == pair["candidate_focal_win"] == 1 else
                         "both_lose" if pair["reference_focal_win"] == pair["candidate_focal_win"] == 0 else
                         "candidate_only_win" if pair["candidate_focal_win"] == 1 else
                         "reference_only_win" if pair["reference_focal_win"] == 1 else "incomplete")
        paired.append(pair)
    _write_csv(out / "paired_outcomes.csv", paired)
    _write_csv(out / "snapshot_results.csv", snapshots)
    merlin_paths = []
    for row in games:
        if row.get("focal_role") != "MERLIN": continue
        merlin_paths.append({"scenario_id": row.get("scenario_id"), "arm": row.get("arm"),
            "status": row.get("status"), "winner": row.get("winner"), "focal_win": row.get("focal_win"),
            "terminal_reason": row.get("terminal_reason"), "assassination_opportunities": row.get("assassination_opportunities"),
            "merlin_assassinated": row.get("merlin_assassinated"), "successful_quests": row.get("successful_quests"),
            "failed_quests": row.get("failed_quests"), "external_model_calls": row.get("external_model_calls"),
            "candidate_enabled": row.get("candidate_enabled")})
    _write_csv(out / "merlin_endgame_paths.csv", merlin_paths)
    if (out / "assassin_signal_trace.csv").exists():
        # The static audit has already been generated in prepare; keep it read-only.
        pass
    cells = Counter(p["cell"] for p in paired)
    complete = [p for p in paired if p["complete_pair"]]
    main_merlin = [r for r in merlin_paths if r["scenario_id"].startswith("sealed-merlin-")]
    fixed_pairs = defaultdict(dict)
    for row in snapshots:
        fixed_pairs[row.get("snapshot_id")][row.get("arm")] = row
    fixed_changed = [x for x in fixed_pairs.values() if x.get("reference", {}).get("action") != x.get("candidate", {}).get("action")]
    budget = _json(out / "budget_ledger.json") if (out / "budget_ledger.json").exists() else {"http_attempts": 0}
    # Derive phase accounting and request reliability from the immutable request
    # journal so a report-only run does not need network access or a live client.
    request_paths = sorted((out / "requests").glob("*.request.json"))
    phase_totals = {"pilot": {"charged": 0.0, "pending": 0.0}, "main": {"charged": 0.0, "pending": 0.0}}
    unknown_attempts = 0
    for request in request_paths:
        item = _json(request); phase = item.get("run_phase") or item.get("budget_phase") or "pilot"
        if phase not in phase_totals: continue
        response = request.with_name(request.name.replace(".request.json", ".response.json"))
        if response.exists():
            row = _json(response)
            phase_totals[phase]["charged"] += float(row.get("budget_charged_cny", item["reservation"]["cny"]))
            unknown_attempts += int(row.get("usage_status") == "unavailable")
        else:
            phase_totals[phase]["pending"] += float(item["reservation"]["cny"])
    budget.update({
        "pilot_phase_charged_cny": phase_totals["pilot"]["charged"],
        "pilot_phase_pending_cny": phase_totals["pilot"]["pending"],
        "main_phase_charged_cny": phase_totals["main"]["charged"],
        "main_phase_pending_cny": phase_totals["main"]["pending"],
        "unknown_usage_attempts": unknown_attempts,
    })
    attempts = [json.loads(line) for line in (out / "llm_calls.jsonl").open(encoding="utf-8")
                if line.strip()] if (out / "llm_calls.jsonl").exists() else []
    by_decision = defaultdict(list)
    for row in attempts:
        if row.get("decision_id"):
            by_decision[row["decision_id"]].append(row)
    first_valid = sum(bool(rows and rows[0].get("accepted") is True) for rows in by_decision.values())
    corrected_decisions = sum(any(row.get("accepted") is not True for row in rows) for rows in by_decision.values())
    correction_attempts = sum(row.get("accepted") is not True for row in attempts)
    reliability = {
        "first_output_valid": {"numerator": first_valid, "denominator": len(by_decision),
                                "value": first_valid / len(by_decision) if by_decision else None},
        "corrected_decision_success": {"numerator": sum(bool(rows and rows[-1].get("accepted") is True)
                                                         for rows in by_decision.values() if any(r.get("accepted") is not True for r in rows)),
                                        "denominator": corrected_decisions,
                                        "value": 1.0 if corrected_decisions and corrected_decisions == sum(bool(rows and rows[-1].get("accepted") is True) for rows in by_decision.values() if any(r.get("accepted") is not True for r in rows)) else (None if not corrected_decisions else 0.0)},
        "transport_retry_attempts": {"numerator": sum(int(row.get("transport_retries_used", 0) or 0) for row in attempts),
                                      "denominator": len(attempts)},
        "output_correction_attempts": {"numerator": correction_attempts, "denominator": len(attempts)},
        "failure_classes": dict(Counter(row.get("failure_class") or row.get("error") or "unknown"
                                         for row in attempts if row.get("accepted") is not True)),
        "network_attempts": len(attempts),
        "unique_decisions": len(by_decision),
    }
    sealed_pairs = [p for p in paired if p.get("split") == "held_out_test"]
    smoke_pairs = [p for p in paired if p.get("split") == "development"]
    def pair_arm_rate(rows, arm):
        complete_rows = [p for p in rows if p["complete_pair"]]
        wins = sum(p.get(f"{arm}_focal_win") == 1 for p in complete_rows)
        return {"numerator": wins, "denominator": len(complete_rows),
                "value": wins / len(complete_rows) if complete_rows else None}
    summary = {
        "run_id": out.name, "status": cfg.get("status"), "production_candidate_enabled": False,
        "candidate_context_revision": MERLIN_DISCLOSURE_REVISION, "vote_v22_candidate_enabled": False,
        "source_run_id": cfg.get("source_run_id"), "diagnostic_source": cfg.get("diagnostic_source_run"),
        "new_model_samples": sum(1 for _ in read_jsonl(out / "llm_calls.jsonl")) if (out / "llm_calls.jsonl").exists() else 0,
        "network_calls": sum(1 for _ in read_jsonl(out / "llm_calls.jsonl")) if (out / "llm_calls.jsonl").exists() else 0,
        "budget": budget, "planned": {"pilot_fixed": len(plan["development_snapshots"]),
            "pilot_repeats": len(plan["repeats"]), "pilot_smoke_pairs": len(plan["smoke"]),
            "sealed_fixed": len(plan["sealed_snapshots"]), "sealed_active_pairs": len(plan["active"])},
        "active_pairing": {"planned_pairs": len(plan["smoke"]) + len(plan["active"]),
            "observed_pairs": len(paired), "complete_pairs": len(complete), "four_cell": dict(cells)},
        "smoke_pairing": {"planned_pairs": len(plan["smoke"]), "observed_pairs": len(smoke_pairs),
                           "complete_pairs": sum(p["complete_pair"] for p in smoke_pairs),
                           "four_cell": dict(Counter(p["cell"] for p in smoke_pairs)),
                           "reference_focal_wins": pair_arm_rate(smoke_pairs, "reference"),
                           "candidate_focal_wins": pair_arm_rate(smoke_pairs, "candidate")},
        "sealed_pairing": {"planned_pairs": len(plan["active"]), "observed_pairs": len(sealed_pairs),
                            "complete_pairs": sum(p["complete_pair"] for p in sealed_pairs),
                            "four_cell": dict(Counter(p["cell"] for p in sealed_pairs)),
                            "reference_focal_wins": pair_arm_rate(sealed_pairs, "reference"),
                            "candidate_focal_wins": pair_arm_rate(sealed_pairs, "candidate")},
        "fixed_snapshots": {"planned": len(plan["fixed"]), "observed_arms": len(snapshots),
            "candidate_aid_present": sum(bool(r.get("aid_present")) for r in snapshots),
            "action_changed_pairs": len(fixed_changed), "status": "available" if snapshots else "not_run"},
        "merlin_main": {"planned_pairs": len(plan["active"]), "observed_rows": len(main_merlin),
            "entered_assassination": {"numerator": sum((r.get("assassination_opportunities") or 0) > 0 for r in main_merlin), "denominator": sum(r.get("status") == "completed" for r in main_merlin)},
            "assassinated": {"numerator": sum(r.get("merlin_assassinated") or 0 for r in main_merlin), "denominator": sum((r.get("assassination_opportunities") or 0) > 0 for r in main_merlin)},
            "focal_wins": {"numerator": sum(r.get("focal_win") == 1 for r in main_merlin), "denominator": sum(r.get("status") == "completed" for r in main_merlin)}},
        "reliability": reliability,
        "smoke_gate": _json(out / "smoke_gate.json") if (out / "smoke_gate.json").exists() else {"status": "not_run"},
        "not_run_or_incomplete": [p for p in plan["active"] if p["scenario_id"] not in grouped],
        "effect_claim": "not_run" if not complete else "descriptive paired result; no causal or significance claim",
        "engineering_status": "candidate_context_validated_offline" if (out / "offline_validation.json").exists() else "not_run",
    }
    atomic_json(out / "summary.json", summary)
    atomic_json(out / "budget_ledger.json", budget)
    _write_report(out, summary)
    return summary


def _write_report(out, s):
    budget = s.get("budget", {})
    lines = [f"# Joint Belief v2.3：梅林公开行为与终局存活", "",
             f"运行 `{s['run_id']}`。生产候选默认关闭；v2.2 投票候选、语言 belief、递归 ToM 和跨局记忆均关闭。",
             "",
             "## 来源与冻结边界", "",
             f"主诊断复用 `{s.get('diagnostic_source')}`，精确来源 `{s.get('source_run_id')}`。r7/v2.2 仅作 development/diagnostic；本轮新受控场景、快照和真实调用分开计数。Joint v2、规则、证据因子、刺客 argmax/并列处理、运行事务和其他席位策略保持冻结。",
             "",
             "刺杀信号审计见 `assassin_signal_audit.md` / `assassin_signal_trace.csv`：刺客输入可见公开 SOCIAL，但数值选择走原生 Merlin marginal argmax；公开文字未进入 action-only 数值更新路径。该观察不能定位某个话术的因果作用。",
             "",
             "主动配对使用现有 controlled population 作为非焦点席位，且 reference/candidate 完全相同；这是预算约束下的 controlled-opponent pilot，不等同于 r7 的全席位真实模型配置。",
             "",
             "## 候选", "",
             "`MerlinDisclosureContext` 只在 Merlin 的 discussion/council_discussion 私有辅助输入中出现。它列出真实公开事件、集合约束和 claim 标记；失败任务不升级为单人身份，成功任务不证明全队好人。合法菜单、posterior、公开事件和模型合法动作都不被主机替换。",
             "",
             "## 运行状态", "",
             f"新模型请求 {s.get('new_model_samples', 0)} 次；耐久账本保留实际用量、峰值保守计费、未知 usage 和在途预留。当前账本保守计费 `{budget.get('conservative_budget_charged_cny')}` CNY，未知 usage 次数 `{budget.get('unknown_usage_attempts')}`。这不是账户发票。",
             f"共享上限为 ¥{budget.get('budget_cny', TOTAL_BUDGET):g}，pilot 阶段上限为 ¥{budget.get('pilot_cumulative_cap_cny', PILOT_CAP):g}；pilot 已计费峰值 `{budget.get('pilot_phase_charged_cny')}` CNY，main `{budget.get('main_phase_charged_cny')}` CNY，在途预留 `{budget.get('pending_reserved_cny')}` CNY。",
             "",
             f"配对：计划 {s['active_pairing']['planned_pairs']}，观察到 {s['active_pairing']['observed_pairs']}，完整 {s['active_pairing']['complete_pairs']}；四格 `{json.dumps(s['active_pairing']['four_cell'], ensure_ascii=False)}`。不完整臂保留，未填成输。",
             "",
             f"固定快照观察到 {s['fixed_snapshots']['observed_arms']} 个臂，候选辅助出现 {s['fixed_snapshots']['candidate_aid_present']} 次，动作变化配对 {s['fixed_snapshots']['action_changed_pairs']}；重复请求不作独立场景。",
             "",
             f"梅林主实验路径：进入刺杀 {s['merlin_main']['entered_assassination']}，条件被刺中 {s['merlin_main']['assassinated']}，焦点胜率 {s['merlin_main']['focal_wins']}。没有分母时以 unavailable/空值表示。",
             "",
             f"封存梅林配对：{json.dumps(s.get('sealed_pairing', {}), ensure_ascii=False)}；smoke 配对：{json.dumps(s.get('smoke_pairing', {}), ensure_ascii=False)}。",
             f"请求可靠性：首次输出有效 {json.dumps(s.get('reliability', {}).get('first_output_valid', {}), ensure_ascii=False)}；修正后成功 {json.dumps(s.get('reliability', {}).get('corrected_decision_success', {}), ensure_ascii=False)}；传输重试 {json.dumps(s.get('reliability', {}).get('transport_retry_attempts', {}), ensure_ascii=False)}；输出修正 {json.dumps(s.get('reliability', {}).get('output_correction_attempts', {}), ensure_ascii=False)}。",
             "",
             "## 判定与限制", "",
             "工程通过只说明输入边界、菜单合法性、预算和恢复链路可审计；它不等于动作改善或游戏收益。真实收益必须由新封存场景的完整配对支持。公开文本变化而结构化动作和刺客输入未变时，不称为识别难度改善。主动分叉后的后续状态不是同信息实验。",
             "",
             "原始重算文件：`games.csv`、`paired_outcomes.csv`、`snapshot_results.csv`、`merlin_endgame_paths.csv`、`llm_calls.jsonl`、`budget_ledger.json`、`summary.json`。离线重算命令见交付说明。",
    ]
    (Path(out) / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _tests(out, name, paths):
    xml = Path(out) / f"{name}_tests.xml"; log = Path(out) / f"{name}_tests.log"
    env = {**os.environ, "PYTHONHASHSEED": "0", "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
    with log.open("w") as stream:
        result = subprocess.run([sys.executable, "-m", "pytest", "-q", *paths, f"--junitxml={xml}"],
                                cwd=ROOT, env=env, stdout=stream, stderr=subprocess.STDOUT, check=False)
    if not xml.exists(): raise RuntimeError(f"missing {xml}")
    root = ET.parse(xml).getroot(); suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    counts = {k: sum(int(s.get(k, 0)) for s in suites) for k in ("tests", "failures", "errors", "skipped")}
    counts.update(passed=counts["tests"] - counts["failures"] - counts["errors"] - counts["skipped"], exit_code=result.returncode)
    return counts


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", required=True, choices=("prepare", "diagnose", "tests", "offline", "smoke", "main", "report-only"))
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--live", action="store_true"); parser.add_argument("--budget-cny", type=float)
    args = parser.parse_args(argv); out = args.run_dir.resolve()
    if args.mode == "prepare": prepare(args)
    elif args.mode == "diagnose":
        cfg = _json(out / "config.json"); audit = analyze_assassin_signals(V22_RUN, R7_RUN, out)
        cfg["assassin_diagnostic"] = audit; atomic_json(out / "config.json", cfg)
    elif args.mode == "tests":
        cfg = _json(out / "config.json"); cfg["tests"] = {
            "unit": _tests(out, "unit", ["tests/eval"]),
            "regression": _tests(out, "regression", ["tests"])}
        atomic_json(out / "config.json", cfg)
        if cfg["tests"]["unit"]["exit_code"] or cfg["tests"]["regression"]["exit_code"]: raise SystemExit(1)
    elif args.mode == "offline": offline(out)
    elif args.mode in {"smoke", "main"}:
        args.mode = args.mode; live(args)
    elif args.mode == "report-only":
        report_only(out); atomic_json(out / "report_reproduction.json", {"network_calls": 0, "summary_recomputed": True})


if __name__ == "__main__": main()
