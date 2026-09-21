"""Frozen v2.3 source scenes and Merlin SOCIAL snapshot selection."""
from collections import Counter, defaultdict
from copy import deepcopy
import json
from pathlib import Path

from avalon.eval.simulation import canonical, digest
from avalon.eval.v2.v21_data import source_game


PROFILES = ("v21_heldout_a", "v21_heldout_b")
# These counts are frozen before any model response.  The smaller exploratory
# batch is required by the shared ¥20 cap when the r7 maximum reservation is
# used as the conservative per-request bound.
DEVELOPMENT_SNAPSHOT_TARGET = 1
SEALED_SNAPSHOT_TARGET = 4
SMOKE_PAIR_TARGET = 1
ACTIVE_PAIR_TARGET = 3


def source_specs():
    specs = []
    for i in range(12):
        specs.append({"seed": 1131000 + i, "profile": "v21_development",
                      "split": "development", "phase": "v23_source", "scope": "generation",
                      "focal": "P1", "scenario_id": f"v23-source-dev-{i:02d}"})
    for i in range(20):
        profile = PROFILES[i % len(PROFILES)]
        specs.append({"seed": 1133000 + i, "profile": profile,
                      "split": "held_out_test", "phase": "v23_source", "scope": "generation",
                      "focal": "P1", "scenario_id": f"v23-source-heldout-{i:02d}"})
    return specs


def generate_source(output):
    output = Path(output)
    specs = source_specs()
    records = [source_game(spec) for spec in specs]
    (output / "v23_source_replays.jsonl").write_text(
        "".join(canonical(r) + "\n" for r in records), encoding="utf-8")
    return records


def _tags(record, decision):
    view = decision["view"]
    events = [e for e in record["events"] if e["seq"] <= decision["after_seq"]]
    mission = [e for e in events if e["kind"] == "MISSION"]
    social = [e for e in events if e["kind"] == "SOCIAL"]
    if mission and mission[-1].get("success") is False:
        evidence = "after_failure"
    elif mission:
        evidence = "after_mission"
    else:
        evidence = "sparse_public_evidence"
    urgency = "score_tied" if view.get("successes") == view.get("failures") else \
        "evil_ahead" if view.get("failures", 0) > view.get("successes", 0) else "good_ahead"
    stance = "prior_public_stance" if any(e.get("actor") == decision["observer_id"] for e in social) else "no_prior_stance"
    return [evidence, urgency, stance, f"stage:{view.get('discussion_stage')}"]


def select_snapshots(records, split, limit):
    candidates = []
    for record in records:
        if record.get("split") != split:
            continue
        for index, decision in enumerate(record.get("decisions", [])):
            if decision.get("view", {}).get("role") != "MERLIN":
                continue
            if decision.get("phase") not in {"discussion", "council_discussion"}:
                continue
            candidates.append({
                "snapshot_id": f"{record['game_id']}:{decision['observer_id']}:{decision['after_seq']}:social",
                "source_game_id": record["game_id"], "decision_index": index,
                "phase": decision["phase"], "observer_role": "MERLIN",
                "observer_id": decision["observer_id"], "split": split,
                "profile": record.get("profile"), "tags": _tags(record, decision),
            })
    selected, used, counts, game_counts = [], set(), Counter(), Counter()
    while len(selected) < min(limit, len(candidates)):
        available = [c for c in candidates if c["snapshot_id"] not in used and game_counts[c["source_game_id"]] < 2]
        if not available:
            break
        best = max(available, key=lambda c: (sum(1 / (1 + counts[t]) for t in c["tags"]), digest(c["snapshot_id"])))
        selected.append(best); used.add(best["snapshot_id"]); game_counts[best["source_game_id"]] += 1
        counts.update(best["tags"])
    return selected


def build_plan(records):
    development = select_snapshots(records, "development", DEVELOPMENT_SNAPSHOT_TARGET)
    heldout = select_snapshots(records, "held_out_test", SEALED_SNAPSHOT_TARGET)
    fixed = []
    for corpus, rows in (("development", development), ("held_out_test", heldout)):
        for row in rows:
            fixed.append({**row, "experiment": "development_snapshot" if corpus == "development" else "sealed_snapshot",
                          "scope": "fixed", "arms": ["reference", "candidate"],
                          "order": ["reference", "candidate"] if int(digest(row["snapshot_id"])[0], 16) % 2 == 0
                          else ["candidate", "reference"]})
    # Repeats are omitted in this budget-constrained batch; they are not
    # silently counted as independent scenarios.
    repeats = []
    smoke = []
    for i in range(SMOKE_PAIR_TARGET):
        smoke.append({"scenario_id": f"smoke-merlin-single-{1170000+i}", "seed": 1170000 + i,
                      "profile": PROFILES[i % 2], "split": "development", "phase": "smoke",
                      "scope": "single_seat", "focal": f"P{(i % 5) + 1}", "focal_role": "MERLIN",
                      "experiment": "A", "order": ["reference", "candidate"] if i % 2 == 0
                      else ["candidate", "reference"]})
    active = []
    # Three pairs are deliberately frozen before any result is inspected.  This
    # is the conservative size under the ¥20 total cap after the pilot reserve.
    for i in range(ACTIVE_PAIR_TARGET):
        active.append({"scenario_id": f"sealed-merlin-single-{1171000+i}", "seed": 1171000 + i,
                       "profile": PROFILES[i % 2], "split": "held_out_test", "phase": "main",
                       "scope": "single_seat", "focal": f"P{(i % 5) + 1}", "focal_role": "MERLIN",
                       "experiment": "A", "order": ["reference", "candidate"] if i % 2 == 0
                       else ["candidate", "reference"]})
    return {"frozen_before_live": True, "source_splits": {"development": len(development), "held_out_test": len(heldout)},
            "development_snapshots": development, "sealed_snapshots": heldout,
            "fixed": fixed, "repeats": repeats, "smoke": smoke, "active": active,
            "vote_v22_candidate_enabled": False,
            "selection": "Controlled population source scenes; Merlin SOCIAL only; max two snapshots per source game; no model outputs used",
            "opponent_mode": "controlled_population_pilot",
            "opponent_arms_equal": True,
            "opponent_mode_note": "Non-focal seats use the existing reproducible population in both arms; do not merge this pilot with r7 all-seat model results.",
            "active_pair_target": ACTIVE_PAIR_TARGET,
            "active_pair_size_reason": "Conservative pre-response estimate under the shared ¥20 cap and ¥5 pilot cap; 1 development snapshot, 1 smoke pair, 4 sealed snapshots, no repeats",
            "statistics": "Source-game clustered fixed descriptions; scenario-paired active focal GOOD wins; incomplete arms retained"}


def write_plan(output, records):
    output = Path(output)
    plan = build_plan(records)
    plan["source_replays_sha256"] = digest(records)
    (output / "dataset_manifest.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n")
    return plan
