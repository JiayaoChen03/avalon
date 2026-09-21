"""Targeted, raw-only v2.3 diagnostics built from the frozen v2.2/r7 run."""
from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path

from avalon.eval.simulation import canonical, digest


ROOT = Path(__file__).resolve().parents[3]
V22_RUN_ID = "20260918-v22-r7-offline"
SOURCE_RUN_ID = "20260918-v21-r7-live-75"


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_jsonl(path):
    with Path(path).open(encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def _true_roles(record):
    return {p["id"]: p["role"] for p in record.get("players", [])}


def _social_features(context):
    events = context.get("game", {}).get("recent_events", [])
    cards = Counter(e.get("card") for e in events if e.get("kind") in {"SOCIAL", "REACT", "CHALLENGE_RESPONSE"})
    text = [e.get("public_writing", e.get("statement", "")) for e in events
            if e.get("kind") in {"SOCIAL", "REACT", "CHALLENGE_RESPONSE"}]
    return cards, text


def analyze_assassin_signals(v22_run, source_run, output):
    """Export every recorded r7 assassination input and a compact audit summary."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    records = {}
    for replay in read_jsonl(Path(source_run) / "active_replays.jsonl"):
        # The request journal and replay archive use different game-id namespaces
        # in r7; scenario plus variant is the frozen join key.
        records[(replay.get("scenario_id"), replay.get("variant"))] = replay
    rows = []
    for item in read_jsonl(Path(source_run) / "llm_calls.jsonl"):
        if item.get("phase") != "assassination" or item.get("observer_role") != "ASSASSIN":
            continue
        record = records.get((item.get("scenario_id"), item.get("variant")), {})
        truth = _true_roles(record)
        context = item.get("context", {})
        game = context.get("game", {})
        players = game.get("players", [])
        ids = [p["id"] for p in players]
        names = [p.get("name") for p in players]
        true_merlin = next((p for p, role in truth.items() if role == "MERLIN"), None)
        legal = []
        for option in context.get("action_menu", []):
            if "legal_targets" in option:
                legal = list(option["legal_targets"])
        marginals = context.get("private_beliefs", {}).get("marginals", {})
        probs = {p: float(marginals.get(p, {}).get("merlin", 0.0)) for p in legal}
        top_probability = max(probs.values()) if probs else None
        top = [p for p in legal if top_probability is not None and abs(probs[p] - top_probability) <= 1e-12]
        raw = item.get("parsed_action", {}).get("parameters", {})
        rank = raw.get("assassin_rank", []) if isinstance(raw, dict) else []
        target = item.get("validated_action", {}).get("target")
        second = sorted(set(probs.values()), reverse=True)[1] if len(set(probs.values())) > 1 else top_probability
        terminal = next((e.get("reason") for e in reversed(record.get("events", [])) if e.get("kind") == "RESULT"), None)
        cards, texts = _social_features(context)
        public_social = [e for e in game.get("recent_events", []) if e.get("kind") in {"SOCIAL", "REACT", "CHALLENGE_RESPONSE"}]
        rows.append({
            "source_run_id": SOURCE_RUN_ID,
            "game_id": item.get("game_id"),
            "scenario_id": item.get("scenario_id"),
            "variant": item.get("variant"),
            "assassin": item.get("observer_id"),
            "true_merlin_offline": true_merlin,
            "true_merlin_probability": probs.get(true_merlin) if true_merlin else None,
            "top_probability": top_probability,
            "top_merlin_candidates": json.dumps(top, ensure_ascii=False),
            "top_count": len(top),
            "top_gap": (top_probability - second) if top_probability is not None and second is not None else None,
            "true_merlin_rank": rank.index(true_merlin) + 1 if true_merlin in rank else None,
            "target": target,
            "target_probability": probs.get(target),
            "target_is_true_merlin": int(target == true_merlin),
            "target_in_native_argmax": int(target in top),
            "true_merlin_in_native_argmax": int(true_merlin in top) if true_merlin else 0,
            "rank_length": len(rank),
            "rank_is_id_permutation": int(len(rank) == len(ids) and set(rank) == set(ids)),
            "tie_break_used": int(len(top) > 1 and target in top),
            "id_order_position": ids.index(target) + 1 if target in ids else None,
            "name_order_position": names.index(next((p.get("name") for p in players if p.get("id") == target), None)) + 1
                if target in ids else None,
            "target_is_first_legal_target": int(bool(legal) and target == legal[0]),
            "public_social_count": len(public_social),
            "public_social_cards": json.dumps(dict(cards), ensure_ascii=False, sort_keys=True),
            "public_text_chars": sum(len(t) for t in texts),
            "public_text_hash": digest(texts),
            "assassin_input_hash": item.get("model_context_hash"),
            "request_payload_hash": item.get("transport", {}).get("request_sha256"),
            "provider_model": item.get("transport", {}).get("model"),
            "provider_fingerprint": item.get("transport", {}).get("system_fingerprint"),
            "policy_mapping": item.get("policy_mapping"),
            "terminal_reason_offline": terminal,
            "input_contains_merlin_disclosure_context": int("merlin_disclosure_context" in context),
            "source_evidence": "raw r7 request plus offline role mapping; not a policy input",
        })
    fields = list(rows[0]) if rows else ["source_run_id", "game_id"]
    with (output / "assassin_signal_trace.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader(); writer.writerows(rows)
    by_variant = defaultdict(list)
    for row in rows:
        by_variant[row["variant"]].append(row)
    summary = {
        "source_run_id": SOURCE_RUN_ID,
        "v22_diagnostic_run": V22_RUN_ID,
        "opportunities": len(rows),
        "by_variant": {},
        "public_text_in_assassin_input": {
            "rows_with_public_social": sum(r["public_social_count"] > 0 for r in rows),
            "rows_with_text": sum(r["public_text_chars"] > 0 for r in rows),
            "input_hash_available": sum(bool(r["assassin_input_hash"]) for r in rows),
        },
        "numeric_posterior_path": {
            "source": "joint_v1/joint_v2 marginals in legal private context",
            "action_rule": "native argmax; assassin_rank only breaks exact ties",
            "free_text_updates_posterior": False,
            "language_action_parser_run": False,
            "causal_explanation": "unknown: observed action paths do not isolate a phrase or card",
        },
        "seat_name_order": {
            "recorded_for_diagnostic": True,
            "used_to_choose_target": False,
            "role_mapping_source": "offline players role labels in source replay",
        },
    }
    for variant, subset in sorted(by_variant.items()):
        summary["by_variant"][variant] = {
            "opportunities": len(subset),
            "hits": sum(r["target_is_true_merlin"] for r in subset),
            "survived": sum(not r["target_is_true_merlin"] for r in subset),
            "top_contains_true_merlin": sum(r["true_merlin_in_native_argmax"] for r in subset),
            "tied_top": sum(r["top_count"] > 1 for r in subset),
            "unique_top": sum(r["top_count"] == 1 for r in subset),
            "model_tiebreak_rows": sum(r["tie_break_used"] for r in subset),
            "target_is_first_legal_target": sum(r["target_is_first_legal_target"] for r in subset),
        }
    (output / "assassin_signal_audit.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    lines = [
        "# Assassin signal audit",
        "",
        f"Source records: `{SOURCE_RUN_ID}`; v2.2 diagnostic directory: `{V22_RUN_ID}`.",
        f"The raw source contains {len(rows)} recorded assassination opportunities. The output table is an offline scorer export; true Merlin labels never enter a model context.",
        "",
        "## What the code actually consumes",
        "",
        "The `assassination` menu carries every legal GOOD target and an `assassin_rank` permutation. `decode_menu` selects the native maximum Merlin marginal; the submitted permutation only breaks an exact probability tie. This keeps target selection, tie handling, and legal visibility unchanged.",
        "",
        "The Assassin request contains the public event projection, including prior SOCIAL cards and public writing. The current `EvidenceExtractor` records structured actions and mechanical events; action-only requests return no language evidence, and free text is not fed into the numeric posterior. The table records text presence and hashes so this boundary can be rechecked without exporting prose.",
        "",
        "Seat and name order are recorded as diagnostics. They are not used by the decoder to select a unique target. A high hit rate is therefore not evidence by itself of a phrase leak or a causal role of one card.",
        "",
        "## Limits",
        "",
        "The r7 paths are development/diagnostic material. Posterior changes before and after a public action are descriptive; they do not identify the cause of the later assassination. No counterfactual replacement action or additional provider call is used here.",
        "",
        "See `assassin_signal_trace.csv` and `assassin_signal_audit.json` for per-opportunity hashes, probability/rank/tie fields, public event counts, and terminal labels.",
    ]
    (output / "assassin_signal_audit.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary


def verify_source(v22_run, source_run, attachment):
    """Freeze source hashes and explicitly reject accidental historical fill."""
    v22_run, source_run = Path(v22_run), Path(source_run)
    if json.loads((v22_run / "config.json").read_text())["run_id"] != V22_RUN_ID:
        raise ValueError("unexpected v2.2 run id")
    v22_cfg = json.loads((v22_run / "config.json").read_text())
    if v22_cfg.get("source_run_id") != SOURCE_RUN_ID:
        raise ValueError("v2.2 source run mismatch")
    source_cfg = json.loads((source_run / "config.json").read_text())
    if source_cfg.get("run_id") != SOURCE_RUN_ID:
        raise ValueError("r7 source run mismatch")
    requested = ["merlin_failure_paths.csv", "belief_action_link.csv", "case_review.csv",
                 "decision_diagnostics.csv", "cross_replay_metrics.csv", "fixed_vote_situations.csv",
                 "summary.json", "config.json", "source_manifest.json", "source_audit.json"]
    source_records = ["llm_calls.jsonl", "active_replays.jsonl", "fixed_snapshot_results.jsonl",
                      "dataset_manifest.json", "config.json", "source_manifest.json"]
    files = {}
    for name in requested:
        path = v22_run / name
        if not path.exists():
            raise FileNotFoundError(path)
        files[f"v22/{name}"] = sha256(path)
    for name in source_records:
        path = source_run / name
        if not path.exists():
            raise FileNotFoundError(path)
        files[f"r7/{name}"] = sha256(path)
    files["attachment"] = sha256(attachment)
    return {
        "v22_run_id": V22_RUN_ID,
        "source_run_id": SOURCE_RUN_ID,
        "source_root": str(source_run.resolve()),
        "v22_root": str(v22_run.resolve()),
        "attachment": str(Path(attachment).resolve()),
        "hashes": files,
        "r7_data_role": "development/diagnostic only",
        "v22_data_role": "diagnostic reuse; no historical fill",
        "network_calls": 0,
        "truth_input_boundary": "role labels are read only by offline scorer; never by MerlinMenuClient",
    }
