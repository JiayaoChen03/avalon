"""P0 repair harness for Joint Belief v2.3.2.

This module is deliberately separate from the v2.3.2 result directory.  It
repairs the evaluation boundary only: provider response evidence is persisted
before decoding, every rejected attempt receives a structured diagnosis, and
historical replay/snapshot eligibility is verified record by record.  It does
not change production belief, rules, menus, or Assassin decoding.
"""

from __future__ import annotations

import argparse
import ast
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any

from avalon.chronicle import PUBLIC_KINDS, context_record
from avalon.eval.joint_belief import ROOT, git_info
from avalon.eval.simulation import canonical, digest, validate_replay
from avalon.eval.v2.adapters import make_version
from avalon.eval.v2.v21_contract import decode_menu
from avalon.eval.v2.v21_runtime import DurableBudget
from avalon.eval.v2.v232_channel import (
    EPSILON_DIAGNOSTIC,
    PRODUCTION_ASSASSIN_MAPPING,
    _legal_targets,
    _stats,
    r7_assassin_requests,
    sha256,
    text_ablate,
    tie_audit,
    write_csv,
    write_json,
)
from avalon.engine import Game, Player
from avalon.llm import ChatClient, LLMError, Settings


VERSION = "joint_belief_v2_3_2-r2-p0"
SCHEMA_VERSION = "v232-r2-1"
PRIMARY_SOURCE = ROOT / "results/joint_belief_v2_3/20260918-v23-r2-live20"
R1_SOURCE = ROOT / "results/joint_belief_v2_3_2/20260918-v232-r1-offline"
R7_SOURCE = ROOT / "results/joint_belief_v2_1/20260918-v21-r7-live-75"
V22_SOURCE = ROOT / "results/joint_belief_v2_2/20260918-v22-r7-offline"
V231_SOURCE = ROOT / "results/joint_belief_v2_3_1/20260918-v231-r1-offline"
ATTACHMENT = Path("/Users/jiayaochen/.codex/attachments/18da97e4-682a-4a19-a2fc-14cc6ff457f2/pasted-text.txt")
TOTAL_BUDGET_CNY = 20.0
PILOT_BUDGET_CNY = 5.0
MAX_SMOKE_ATTEMPTS = 3
PUBLIC_TEXT_KEYS = {"public_writing", "statement"}
REASONING_KEYS = {"reasoning_content"}
CONTRACT_ENVELOPE_FIELDS = {"belief_updates", "interpretation", "public_stance_change",
                            "recommended_action", "short_rationale"}
VERIFIED_STATUSES = {"BASELINE_VERIFIED", "BASELINE_VERIFIED_NO_SNAPSHOT",
                     "PREFIX_VALID_TERMINAL_MISSING", "PREFIX_VALID_TERMINAL_MISSING_NO_SNAPSHOT", "PARTIAL_ARCHIVE_VERIFIED_PREFIX"}


def _json(path: Path, default=None):
    path = Path(path)
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _write_text(path: Path, value: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def _atomic_bytes(path: Path, value: bytes) -> None:
    """Durably write a restricted artifact before it is referenced."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temp.open("wb") as stream:
        os.chmod(temp, 0o600)
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def _append_jsonl(path: Path, value: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(canonical(value) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _code_paths() -> list[Path]:
    return sorted({*ROOT.joinpath('avalon').rglob('*.py'), *ROOT.joinpath('tests').rglob('*.py'),
                   *ROOT.joinpath('scripts').rglob('*.py'),
                   *ROOT.joinpath('prompts').glob('*.md'), ROOT/'pyproject.toml'})


def _find_agents() -> list[str]:
    return [str(parent / "AGENTS.md") for parent in [ROOT, *ROOT.parents]
            if (parent / "AGENTS.md").exists()]


def _source_files(root: Path) -> list[Path]:
    names = [
        "config.json", "dataset_manifest.json", "snapshot_results.csv", "games.csv",
        "paired_outcomes.csv", "assassin_signal_audit.json", "assassin_signal_trace.csv",
        "source_manifest.json", "v23_source_replays.jsonl", "llm_calls.jsonl",
    ]
    files = [root / name for name in names if (root / name).exists()]
    files += sorted((root / "active_replays").glob("*.json"))
    files += sorted((root / "requests").glob("*.request.json"))
    files += sorted((root / "requests").glob("*.response.json"))
    return files


def _source_hash_manifest() -> dict[str, str]:
    result = {}
    for label, root in (("primary_v23", PRIMARY_SOURCE), ("r1", R1_SOURCE),
                        ("r7", R7_SOURCE), ("v22", V22_SOURCE), ("v231", V231_SOURCE)):
        if not root.exists():
            continue
        for path in _source_files(root):
            result[f"{label}/{path.relative_to(root)}"] = sha256(path)
    return result


def _records() -> list[tuple[str, str, dict[str, Any], Path]]:
    rows: list[tuple[str, str, dict[str, Any], Path]] = []
    for path in sorted((R7_SOURCE / "active_replays").glob("*.json")):
        rows.append(("20260918-v21-r7-live-75", "development_diagnostic", _json(path, {}), path))
    for path in sorted((PRIMARY_SOURCE / "active_replays").glob("*.json")):
        rows.append(("20260918-v23-r2-live20", "v23_active_diagnostic", _json(path, {}), path))
    source = PRIMARY_SOURCE / "v23_source_replays.jsonl"
    if source.exists():
        for index, line in enumerate(source.read_text(encoding="utf-8").splitlines()):
            if line.strip():
                rows.append(("20260918-v23-r2-live20", "v23_source_diagnostic",
                             json.loads(line), source))
    return rows


def _prefix_checks(record: dict[str, Any]) -> tuple[bool, str | None, str | None]:
    """Check the archive up to its last legal public boundary without terminal assumptions."""
    if record.get("schema_version") != 1 or not isinstance(record.get("game_id"), str):
        return False, "schema_version/game_id", "archive_corrupt"
    if type(record.get("seed")) is not int:
        return False, "seed", "archive_corrupt"
    events = record.get("events")
    if not isinstance(events, list) or not events or events[0].get("kind") != "START":
        return False, "events[0]", "event_missing_or_order_changed"
    seqs = [e.get("seq") for e in events]
    if seqs != list(range(1, len(events) + 1)):
        first = next((i for i, value in enumerate(seqs, 1) if value != i), None)
        return False, f"events[{first - 1 if first else 0}].seq", "event_missing_or_order_changed"
    for event in events:
        try:
            expected = event.get("record_id")
            actual = context_record(event).get("record_id")
        except Exception:
            return False, f"events[{event.get('seq')}].record_id", "archive_corrupt"
        if expected != actual:
            return False, f"events[{event.get('seq')}].record_id", "event_record_id_mismatch"
    roles = {p.get("id"): p.get("role") for p in record.get("players", [])}
    if not roles or any(not key or not value for key, value in roles.items()):
        return False, "players", "archive_corrupt"
    for event in events:
        if event.get("kind") == "MISSION":
            team = event.get("team", [])
            capacity = sum(roles.get(pid) in {"EVIL", "ASSASSIN"} for pid in team)
            fail_count = event.get("fail_count")
            if type(fail_count) is not int or not 0 <= fail_count <= capacity:
                return False, f"events[{event.get('seq')}].fail_count", "legal_projection_mismatch"
    return True, None, None


def _assassination_decision(record: dict[str, Any]) -> dict[str, Any] | None:
    truth = {p.get("id"): p.get("role") for p in record.get("players", [])}
    assassin = next((pid for pid, role in truth.items() if role == "ASSASSIN"), None)
    choices = [d for d in record.get("decisions", [])
               if d.get("phase") == "assassination" and d.get("observer_id") == assassin]
    return choices[-1] if choices else None


def _request_snapshot_rows(verification: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from .v21_contract import legal_menu, menu_context
    from .v232_replay_verification import equal, Mismatch
    by_game = {(r['source_run_id'], r['game_id']): r for r in verification}
    rows = []
    for item in r7_assassin_requests(R7_SOURCE):
        req = item['request']; response = item['response']; context = req['context']
        source_key = str(req.get('game_id')).split(':')[-1]
        path = R7_SOURCE / 'active_replays' / f'{source_key}.json'
        record = _json(path, {})
        evidence = by_game.get((R7_SOURCE.name, record.get('game_id')), {})
        sid = req.get('snapshot_id') or f"{req.get('scenario_id')}:{req.get('game_id')}:{req.get('variant')}"
        row = {'snapshot_id':sid,'source_run_id':R7_SOURCE.name,'scenario_id':req.get('scenario_id'),
               'game_id':req.get('game_id'),'source_file':str(path),'source_sha256':sha256(path) if path.exists() else None,
               'observer_id':req.get('observer_id'),'verification_status':evidence.get('verification_status'),
               'eligible':0,'source_verified':0,'exclusion_reason':None,'request_path':item['request_path'],
               'request_sha256':sha256(Path(item['request_path'])), 'decoder_version':sha256(ROOT/'avalon/eval/v2/v21_contract.py')}
        try:
            if evidence.get('verification_status') not in VERIFIED_STATUSES:
                raise Mismatch('source_unverified','source_status','verified source',evidence.get('verification_status'))
            index = req['index']
            proof = next((c for c in evidence.get('cutoffs',[]) if c['decision_index']==index and c['phase']=='assassination'),None)
            if not proof or not proof['full_posterior_verified']:
                raise Mismatch('snapshot_unverified','cutoff','verified original posterior',proof)
            cp = R7_SOURCE/'checkpoints'/source_key/'contexts'/f'{index:04d}.json'
            saved = _json(cp)
            if saved is None:
                raise Mismatch('archive_missing','source_context','original context',None)
            equal(proof['legal_view_hash'],digest(saved['view']),'legal_projection_mismatch','saved_view')
            equal(proof['posterior_hash'],saved['posterior_hash'],'posterior_mismatch','saved_posterior')
            equal(proof['legal_menu_hash'],digest(context['action_menu']),'legal_projection_mismatch','action_menu')
            equal(proof['marginals_hash'],digest(context['private_beliefs']['marginals']),'posterior_mismatch','model_marginals')
            equal(saved['view'] and digest(saved['view']), context['state_version'],'stale_state','state_version')
            equal(req['model_context_hash'], digest(context),'archive_corrupt','model_context_hash')
            # Assassination has no vote DecisionContext in either policy arm.
            equal(menu_context(saved), {k:v for k,v in context.items() if k!='validation_feedback'},
                  'legal_projection_mismatch','full_model_projection')
            raw = response.get('raw_response')
            if raw is None:
                raise Mismatch('archive_missing','raw_response','original accepted response',None)
            action, details = decode_menu(raw,saved,context)
            equal(record['decisions'][index]['action'],action,'decoder_result_mismatch','decoded_action')
            legal = next(o['legal_targets'] for o in context['action_menu'] if 'assassin_rank' in o.get('parameters',{}))
            values = {pid:saved['marginals'][pid]['merlin'] for pid in legal}
            top = sorted(pid for pid in values if values[pid]==max(values.values()))
            public_text = int(any(any(k in e for k in PUBLIC_TEXT_KEYS) for e in context['game']['recent_events']))
            row.update(source_verified=1, cutoff_seq=proof['cutoff_seq'], source_context_sha256=sha256(cp),
                       legal_menu_hash=proof['legal_menu_hash'], public_prefix_hash=proof['public_prefix_hash'],
                       posterior_hash=proof['posterior_hash'], model_context_hash=digest(context),
                       exact_tie=int(len(top)>1), native_exact_top=top, public_text_in_model_input=public_text,
                       decoder_verified=True, expected_target=record['decisions'][index]['action']['target'],
                       actual_target=action['target'], native_variant=proof['native_variant'])
            row['eligible'] = int(len(top)>1 and public_text)
            if not row['eligible']: row['exclusion_reason']='not_exact_tie_or_no_public_text'
        except Mismatch as exc:
            row.update(exclusion_reason=str(exc), verification_error=exc.detail)
        except Exception as exc:
            row.update(exclusion_reason=f'{type(exc).__name__}: {exc}')
        rows.append(row)
    return rows


def _json_diff(before: Any, after: Any, path: str = "$") -> list[dict[str, Any]]:
    if type(before) is not type(after):
        return [{"path": path, "kind": "type", "before": type(before).__name__, "after": type(after).__name__}]
    if isinstance(before, dict):
        changes = []
        for key in sorted(set(before) | set(after)):
            if key not in before or key not in after:
                changes.append({"path": f"{path}.{key}", "kind": "field_presence"})
            else:
                changes.extend(_json_diff(before[key], after[key], f"{path}.{key}"))
        return changes
    if isinstance(before, list):
        changes = []
        for index in range(max(len(before), len(after))):
            if index >= len(before) or index >= len(after):
                changes.append({"path": f"{path}[{index}]", "kind": "length"})
            else:
                changes.extend(_json_diff(before[index], after[index], f"{path}[{index}]"))
        return changes
    return [] if before == after else [{"path": path, "kind": "value"}]


def _public_text_only_diff(before: dict[str, Any], after: dict[str, Any]) -> tuple[bool, list[dict[str, Any]]]:
    diffs = _json_diff(before, after)
    # The recursive diff can report list index paths for nested data.  Verify
    # by applying the exact public-text projection rather than trusting a path.
    return bool(diffs) and text_ablate(before) == after and all(
        diff['path'].rsplit('.',1)[-1] in PUBLIC_TEXT_KEYS and
        diff['path'].startswith(('$.game.recent_events[','$.game.focused_events[','$.retrieved_chronicle['))
        for diff in diffs), diffs


def _safe_response_content(content: Any) -> tuple[str | None, bool, str | None]:
    if content is None:
        return None, False, None
    if not isinstance(content, str):
        content = json.dumps(content, ensure_ascii=False, separators=(",", ":"))
    redacted = False
    reason = None
    # ChatClient already excludes provider-level reasoning_content.  This
    # defensive branch handles a compatible provider that embeds that field in
    # the action JSON while preserving all other bytes when possible.
    if "reasoning_content" in content:
        try:
            parsed = json.loads(content)
            def scrub(value):
                nonlocal redacted
                if isinstance(value, dict):
                    result = {}
                    for key, item in value.items():
                        if key in REASONING_KEYS:
                            redacted = True
                            result[key] = "[REDACTED_REASONING_CONTENT]"
                        else:
                            result[key] = scrub(item)
                    return result
                if isinstance(value, list):
                    return [scrub(item) for item in value]
                return value
            scrubbed = scrub(parsed)
            if redacted:
                content = json.dumps(scrubbed, ensure_ascii=False, separators=(",", ":"))
                reason = "reasoning_content_key"
        except (TypeError, json.JSONDecodeError):
            # A malformed body containing this key might still contain private
            # reasoning.  Do not retain it verbatim; the existence of a body
            # and its hash remain in the journal for diagnosis.
            redacted = True
            reason = "embedded_reasoning_marker_unparsed"
            content = "[REDACTED_UNPARSED_RESPONSE_WITH_REASONING_MARKER]"
    return content, redacted, reason


def classify_failure(exc: Exception | None, telemetry: dict[str, Any], *, phase: str) -> dict[str, Any]:
    if exc is None:
        return {"error_class": None, "error_code": None, "error_field": None,
                "parse_status": "json_parsed", "validation_status": "accepted"}
    code = str(exc)
    if isinstance(exc, LLMError):
        if code.startswith("http_"):
            category = "http_provider_error"
        elif code in {"timeout", "connection_error"}:
            category = "network_timeout_or_transport"
        elif code == "empty_response":
            category = "empty_response"
        elif code in {"truncated_response", "response_too_large"} or telemetry.get("finish_reason") == "length":
            category = "output_truncated"
        elif code == "invalid_response":
            category = 'response_missing_fields' if telemetry.get('envelope_error') else 'json_parse_or_response_shape'
            if isinstance(telemetry.get('response_content'),str):
                try:
                    json.loads(telemetry['response_content'])
                except json.JSONDecodeError:
                    category = 'json_parse_error'
        else:
            category = "provider_error"
        parse_status = "no_content" if not telemetry.get("response_content") else "provider_parse_failed"
    elif isinstance(exc, (json.JSONDecodeError,)):
        category, parse_status = "json_parse_error", "json_parse_failed"
    else:
        parse_status = "json_parsed"
        if code in {"schema", "unknown_or_stale_action_id"}:
            category = "schema_contract_mismatch" if code == "schema" else "stale_or_unknown_action"
        elif code == "stale_state":
            category = "stale_menu_state"
        elif code in {'illegal_target','illegal_mission_card','illegal_ballot'}:
            category = 'illegal_seat_or_enum'
        elif code.startswith(("illegal_", "Invalid ", "The reason ")) or code in {"insufficient_resource", "invalid_action"}:
            category = "legal_action_rejected"
        else:
            category = "decoder_error"
    field = None
    if "assassin" in code or "rank" in code:
        field = "$.recommended_action.parameters.assassin_rank"
    elif "action_id" in code:
        field = "$.recommended_action.action_id"
    elif category == "schema_contract_mismatch":
        field = "$"
    return {"error_class": category, "error_code": code, "error_field": field,
            "parse_status": parse_status, "validation_status": "rejected"}


def _schema_diagnostic(raw: Any, supplied: dict[str, Any]) -> dict[str, Any]:
    """Add non-mutating field-level detail to the production schema error."""
    if not isinstance(raw, dict):
        return {"error_code": "schema_non_object", "error_field": "$",
                "error_detail": {"actual_type": type(raw).__name__}}
    fields = set(raw)
    if raw.get("type") == "json_object":
        fields.discard("type")
    extra = sorted(fields - CONTRACT_ENVELOPE_FIELDS)
    missing = sorted(CONTRACT_ENVELOPE_FIELDS - fields)
    if extra or missing:
        return {"error_code": "schema_envelope_fields", "error_field": "$",
                "error_detail": {"extra_fields": extra, "missing_fields": missing}}
    selected = raw.get("recommended_action")
    if not isinstance(selected, dict):
        return {"error_code": "schema_recommended_action_object", "error_field": "$.recommended_action",
                "error_detail": {"actual_type": type(selected).__name__}}
    action_extra = sorted(set(selected) - {"action_id", "parameters"})
    action_missing = sorted({"action_id", "parameters"} - set(selected))
    if action_extra or action_missing:
        return {"error_code": "schema_recommended_action_fields", "error_field": "$.recommended_action",
                "error_detail": {"extra_fields": action_extra, "missing_fields": action_missing}}
    params = selected.get("parameters")
    if not isinstance(params, dict):
        return {"error_code": "schema_parameters_object", "error_field": "$.recommended_action.parameters",
                "error_detail": {"actual_type": type(params).__name__}}
    option = next((item for item in supplied.get("action_menu", [])
                   if item.get("action_id") == selected.get("action_id")), None)
    if option is not None:
        expected = set(option.get("parameters") or {})
        actual = set(params)
        if actual != expected:
            return {"error_code": "schema_action_parameters", "error_field": "$.recommended_action.parameters",
                    "error_detail": {"extra_fields": sorted(actual - expected),
                                      "missing_fields": sorted(expected - actual),
                                      "action_id": selected.get("action_id")}}
        if 'assassin_rank' in params:
            rank=params['assassin_rank']; ids=option['parameters']['assassin_rank']['permutation_of']
            if not isinstance(rank,list):
                detail={'actual_type':type(rank).__name__}
            else:
                detail={'unknown_items':[p for p in rank if p not in ids],
                        'missing_items':[p for p in ids if p not in rank],
                        'duplicate_items':[p for p in ids if rank.count(p)>1]}
            if (not isinstance(rank,list) or len(rank)!=len(ids)
                or any(not isinstance(p,str) for p in rank) or set(rank)!=set(ids)):
                return {'error_class':'invalid_ranking','error_code':'ranking_not_permutation',
                        'error_field':'$.recommended_action.parameters.assassin_rank','error_detail':detail}
    return {"error_code": "schema_contract_mismatch", "error_field": "$",
            "error_detail": {"reason": "production decoder rejected the envelope"}}


class ResponseJournal:
    """Durable response evidence kept outside public logs and Agent context."""

    def __init__(self, out: Path):
        self.out = Path(out)
        self.responses = self.out / "responses"
        self.responses.mkdir(parents=True, exist_ok=True)
        os.chmod(self.out, 0o700)
        os.chmod(self.responses, 0o700)
        self.path = self.out / "response_journal.jsonl"
        self.failures = self.out / "validation_failures.jsonl"
        self.attempts = self.out / "api_attempts.jsonl"

    def persist(self, meta: dict[str, Any], telemetry: dict[str, Any], exc: Exception | None,
                *, decoded: Any = None, phase: str = "response") -> dict[str, Any]:
        content, redacted, redaction_reason = _safe_response_content(telemetry.get("response_content"))
        ref = None
        content_hash = None
        content_available = False
        if content is not None:
            ref = f"responses/{meta['attempt_id']}.content.txt"
            content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
            try:
                _atomic_bytes(self.out / ref, content.encode("utf-8"))
                content_available = True
            except OSError as error:
                meta = {**meta, "persistence_error": f"{type(error).__name__}: {error}"}
                raise RuntimeError("response_persistence_failed") from error
        diagnosis = classify_failure(exc, telemetry, phase=phase)
        if exc is None and decoded is None:
            # The body is durable, but the action has not crossed the decoder
            # boundary yet.  Do not label this intermediate journal row as an
            # accepted decision; the later validated row is authoritative.
            diagnosis = {"error_class": None, "error_code": None,
                         "error_field": None, "parse_status": "json_received",
                         "validation_status": "pending_validation"}
        entry = {"run_id": meta.get("run_id"), "schema_version": SCHEMA_VERSION,
                 **meta, "provider_request_id": telemetry.get("id"),
                 "transport_status": "transport_error" if telemetry.get('transport_error') else ("response_received" if telemetry.get('http_status') or telemetry.get('response_content') is not None else "unknown"),
                 "http_status": telemetry.get("http_status"), "finish_reason": telemetry.get("finish_reason"),
                 "requested_model": meta.get("requested_model"), "returned_model": telemetry.get("model"),
                 "response_content_ref": ref, "response_content_hash": content_hash,
                 "content_available": int(content_available), "redaction_applied": int(redacted),
                 "redaction_reason": redaction_reason, "usage_available": int(bool(telemetry.get("usage"))),
                 "usage": telemetry.get("usage") or None,
                 "content_status": ("empty" if content_available and not content.strip() else
                    "available" if content_available else "not_received" if telemetry.get('transport_error') else
                    "response_field_missing" if telemetry.get('http_status') else "unavailable"),
                 "phase": phase, **diagnosis,
                 "accepted": int(exc is None and decoded is not None),
                 "committed": 0, "commit_id": None}
        try:
            _append_jsonl(self.path, entry)
            _append_jsonl(self.attempts, entry)
            if entry["validation_status"] == "rejected":
                _append_jsonl(self.failures, entry)
        except OSError as error:
            raise RuntimeError("response_journal_persistence_failed") from error
        return entry


def _required_fields() -> dict[str, list[str]]:
    return {
        "replay_verification.csv": ["source_run_id", "source_file", "source_sha256", "game_id", "observer_id",
                                    "source_variant", "replay_variant", "config_hash", "verification_mode",
                                    "verification_status", "first_mismatch_event_id", "first_mismatch_field",
                                    "mismatch_kind", "expected_hash", "actual_hash", "max_abs_raw_delta",
                                    "expected_exact_top", "actual_exact_top", "expected_target", "actual_target",
                                    "legal_cutoff_verified", "affected_snapshot_ids", "exclusion_reason", "checks", "last_verified_seq", "cutoff_seq"],
        "contract_smoke_results.csv": ["run_id", "logical_request_id", "attempt_id", "condition", "replicate_id",
                                        "scenario_id", "snapshot_id", "payload_hash", "payload_equal_to_A1",
                                        "display_ablation_valid", "response_content_ref", "content_available",
                                        "usage_available", "usage", "requested_model", "returned_model",
                                        "parse_status", "validation_status", "error_class", "error_code", "error_field",
                                        "error_detail", "accepted", "committed", "stop_reason"],
    }


def _init_outputs(out: Path) -> None:
    for name, fields in _required_fields().items():
        write_csv(out / name, [], fields)
    for name in ("response_journal.jsonl", "validation_failures.jsonl", "api_attempts.jsonl", "replay_mismatches.jsonl"):
        _write_text(out / name, "")
    write_json(out / "cost_summary.json", {"status": "NOT_RUN", "budget_cny": TOTAL_BUDGET_CNY,
                                             "pilot_budget_cny": PILOT_BUDGET_CNY, "prior_run_conservative_cny": None,
                                             "remaining_total_cny": None, "remaining_pilot_cny": None,
                                             "attempts": 0, "logical_requests": 0, "accepted": 0,
                                             "failed": 0, "unknown_usage": None, "in_flight_reserved_cny": None})
    write_json(out / "p0_gates.json", {"response_persistence": "NOT_RUN", "failure_diagnostics": "NOT_RUN",
                                        "accounting_recovery": "NOT_RUN", "baseline_verification": "NOT_RUN",
                                        "sample_exclusion": "NOT_RUN", "contract_smoke": "NOT_RUN",
                                        "labels": []})
    write_json(out / "summary.json", {"run_id": out.name, "status": "prepared", "network_calls": 0})
    _write_text(out / "p0_report.md", "# Avalon V2.3.2-r2 P0\n\nPrepared; no network request was sent.\n")


def prepare(out: Path) -> dict[str, Any]:
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=False)
    if not R1_SOURCE.exists() or not R7_SOURCE.exists() or not PRIMARY_SOURCE.exists():
        raise FileNotFoundError("required read-only v2.3.2/v2.3/r7 source is missing")
    source_hashes = _source_hash_manifest()
    current = {str(path.relative_to(ROOT)): sha256(path) for path in _code_paths()}
    attachment_hash = sha256(ATTACHMENT) if ATTACHMENT.exists() else None
    prior_cost = _json(R1_SOURCE / "cost_summary.json", {})
    cfg = {"run_id": out.name, "version": VERSION, "created_utc": datetime.now(timezone.utc).isoformat(),
           "status": "prepared", "live": False, "network_access": False, "network_calls": 0,
           "total_budget_cny": TOTAL_BUDGET_CNY, "pilot_budget_cny": PILOT_BUDGET_CNY,
           "prior_run_id": R1_SOURCE.name, "prior_run_cost": prior_cost,
           "candidate_enabled_by_default": False, "production_changes": False,
           "frozen": {"belief": "joint_v2", "rules": True, "evidence": True,
                      "assassin_decoder": PRODUCTION_ASSASSIN_MAPPING, "tie_equality": "exact Python == max",
                      "v22_vote_candidate": False, "merlin_disclosure": False, "language_belief": False,
                      "recursive_tom": False, "cross_game_memory": False},
           "source_paths": {"r1": str(R1_SOURCE), "r7": str(R7_SOURCE), "v23": str(PRIMARY_SOURCE),
                            "v22": str(V22_SOURCE), "v231": str(V231_SOURCE)},
           "attachment": str(ATTACHMENT), "attachment_sha256": attachment_hash,
           "source_hashes": source_hashes, "current_code_hashes": current, "git": git_info(),
           "AGENTS_found": _find_agents(), "tests": {},
           "commands": {"prepare": "python -m avalon.eval.v2.v232_r2 --mode prepare --run-dir <run>",
                        "verify": "python -m avalon.eval.v2.v232_r2 --mode verify --run-dir <run>",
                        "smoke": "python -m avalon.eval.v2.v232_r2 --mode smoke --run-dir <run>",
                        "tests": "python -m avalon.eval.v2.v232_r2 --mode tests --run-dir <run>",
                        "report_only": "python -m avalon.eval.v2.v232_r2 --mode report-only --run-dir <run>"}}
    write_json(out / "p0_config.json", cfg)
    write_json(out / "p0_source_manifest.json", {"run_id": out.name, "source_hashes": source_hashes,
        "current_code_hashes": current, "git": git_info(), "AGENTS_found": _find_agents(),
        "read_sources": cfg["source_paths"], "historical_samples_pooled": False,
        "prior_run_cost_file": str(R1_SOURCE / "cost_summary.json"), "network_calls": 0})
    _write_text(out / "p0_prechange_audit.md", f"""# Avalon V2.3.2-r2 P0 prechange audit

This is a new read-only diagnostic run `{out.name}`. The previous run `{R1_SOURCE.name}` remains untouched. No production rule, belief, menu, validator, Assassin decoder, prompt, policy or strategy is changed.

The repaired path is `budget reservation -> ChatClient transport -> response evidence persistence -> JSON/action decoding -> validation diagnosis -> accepted-only commit`. The old v2.3.2 pilot persisted usage but not 30 rejected response bodies; this run never treats those bodies as recoverable.

Source hashes, current code hashes, dirty git state and the attachment hash are in `p0_source_manifest.json` and `p0_config.json`. No `AGENTS.md` was found. Historical r7/v2.3/v2.3.1/v2.2 data are diagnostic only.
""")
    _init_outputs(out)
    return cfg


def verify(out: Path) -> dict[str, Any]:
    out = Path(out).resolve()
    cfg = _json(out / "p0_config.json", {})
    previous_gates = _json(out / "p0_gates.json", {})
    paid_exists = any((out / 'requests').glob('*.request.json'))
    if not cfg:
        raise FileNotFoundError(out / "p0_config.json")
    _write_text(out / "replay_mismatches.jsonl", "")
    from concurrent.futures import ProcessPoolExecutor
    from .v232_replay_verification import verify_record
    tasks = [(src, cohort, record, source_file, R7_SOURCE if 'r7' in src else PRIMARY_SOURCE)
             for src, cohort, record, source_file in _records()]
    with ProcessPoolExecutor(max_workers=4) as pool:
        verification = list(pool.map(verify_record, tasks))
    mismatch_rows = [r for r in verification if r['verification_status'] == 'UNVERIFIABLE']
    _write_text(out / 'replay_cutoffs.jsonl', '')
    for row in verification:
        for cutoff in row.get('cutoffs', []):
            _append_jsonl(out / 'replay_cutoffs.jsonl', cutoff)
        if row['verification_status'] != 'BASELINE_VERIFIED':
            _append_jsonl(out / 'replay_mismatches.jsonl', row)
    write_json(out / 'replay_verification_details.json', verification)
    fields = _required_fields()["replay_verification.csv"]
    write_csv(out / "replay_verification.csv", verification, fields)
    snapshots = _request_snapshot_rows(verification)
    write_json(out / "eligible_snapshot_manifest.json", {
        "run_id": out.name, "source_role": "historical_r7_diagnostic_only",
        "selection_rule": "baseline/prefix verified + legal cutoff + native exact tie + public text",
        "planned": len(snapshots), "verified_source_rows": sum(r.get("verification_status") in VERIFIED_STATUSES for r in verification),
        "eligible": sum(r.get("eligible") == 1 for r in snapshots),
        "excluded": sum(r.get("eligible") != 1 for r in snapshots),
        "unresolved_source_rows": sum(r.get("verification_status") == "UNVERIFIABLE" for r in verification),
        "snapshots": snapshots,
    })
    statuses = Counter(row.get("verification_status") for row in verification)
    eligible = [row for row in snapshots if row.get("eligible") == 1]
    prior_cost = _json(R1_SOURCE / "cost_summary.json", {})
    prior_conservative = (prior_cost.get("budget_snapshot") or {}).get("conservative_budget_charged_cny")
    prior_unknown = (prior_cost.get("budget_snapshot") or {}).get("unknown_usage_attempts")
    prior_pending = (prior_cost.get("budget_snapshot") or {}).get("pending_reserved_cny")
    if isinstance(prior_conservative, (int, float)):
        remaining_total = max(0.0, TOTAL_BUDGET_CNY - float(prior_conservative))
        remaining_pilot = max(0.0, PILOT_BUDGET_CNY - float(prior_conservative))
    else:
        remaining_total = remaining_pilot = None
    partial_terminal = any(row["verification_status"] == "PARTIAL_ARCHIVE_VERIFIED_PREFIX" for row in verification)
    gates = {"response_persistence": "READY_OFFLINE", "failure_diagnostics": "READY_OFFLINE",
             "accounting_recovery": "PASS" if prior_unknown == 0 and prior_pending == 0 else "BLOCKED_UNKNOWN_PRIOR_COST",
             "baseline_verification": "PASS_WITH_PARTIAL_ARCHIVE" if partial_terminal and not mismatch_rows else ("PARTIAL" if mismatch_rows else "PASS"),
             "sample_exclusion": "PASS" if snapshots else "BLOCKED_NO_SNAPSHOTS",
             "contract_smoke": "BLOCKED_UNTIL_OFFLINE_TESTS",
             "source_rows": len(verification), "source_status_counts": dict(statuses),
             "verified_rows": sum(row.get("verification_status") in VERIFIED_STATUSES for row in verification),
             "excluded_rows": len(mismatch_rows), "unresolved_rows": sum(row.get("verification_status") == "UNVERIFIABLE" for row in verification),
             "snapshot_planned": len(snapshots), "snapshot_eligible": len(eligible),
             "snapshot_excluded": len(snapshots) - len(eligible),
             "prior_run_unknown_usage": prior_unknown, "prior_run_pending_reserve_cny": prior_pending,
             "remaining_total_cny": remaining_total, "remaining_pilot_cny": remaining_pilot,
             "labels": (["REPLAY_MISMATCH"] if mismatch_rows else (["PARTIAL_TERMINAL_ARCHIVE"] if partial_terminal else []))}
    if paid_exists:
        for key in ('contract_smoke','smoke_attempts','smoke_accepted','smoke_failed','repository_regression'):
            if key in previous_gates: gates[key] = previous_gates[key]
        gates['labels'] = list(dict.fromkeys(gates['labels'] + previous_gates.get('labels',[])))
    write_json(out / "p0_gates.json", gates)
    if not paid_exists:
        write_json(out / "cost_summary.json", {"status": "PRECHECKED", "budget_cny": TOTAL_BUDGET_CNY,
        "pilot_budget_cny": PILOT_BUDGET_CNY, "prior_run_conservative_cny": prior_conservative,
        "remaining_total_cny": remaining_total, "remaining_pilot_cny": remaining_pilot,
        "attempts": 0, "logical_requests": 0, "accepted": 0, "failed": 0,
            "unknown_usage": None if prior_unknown else 0, "in_flight_reserved_cny": prior_pending})
    cfg.update({"status": "verified", "source_rows": len(verification), "verified_rows": gates["verified_rows"],
                "unresolved_rows": gates["unresolved_rows"], "eligible_snapshots": len(eligible),
                "stage_a_gate": gates["baseline_verification"], "stage_b_gate": gates["contract_smoke"],
                "remaining_total_cny": remaining_total, "remaining_pilot_cny": remaining_pilot})
    write_json(out / "p0_config.json", cfg)
    return {"verification": verification, "snapshots": snapshots, "gates": gates}


def _load_selected_snapshot(out: Path) -> dict[str, Any] | None:
    manifest = _json(out / "eligible_snapshot_manifest.json", {})
    eligible = [row for row in manifest.get("snapshots", []) if row.get("eligible") == 1]
    return sorted(eligible, key=lambda row: (str(row.get("scenario_id")), str(row.get("snapshot_id"))))[0] if eligible else None


def _snapshot_context(snapshot: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    request_rows = r7_assassin_requests(R7_SOURCE)
    wanted = snapshot.get("snapshot_id")
    for item in request_rows:
        request = item["request"]
        sid = request.get("snapshot_id") or f"{request.get('scenario_id')}:{request.get('game_id')}:{request.get('variant')}"
        if sid != wanted:
            continue
        record_path = R7_SOURCE / "active_replays" / f"{str(request.get('game_id')).split(':')[-1]}.json"
        record = _json(record_path, {})
        decision = _assassination_decision(record) or {}
        return request.get("context") or {}, record, decision
    raise KeyError(f"snapshot not found: {wanted}")


def _settings_for_smoke() -> Settings:
    settings = Settings.load()
    source_cfg = _json(PRIMARY_SOURCE / "config.json", {}).get("settings", {})
    for field in ("base_url", "model", "max_tokens", "token_field", "json_mode", "thinking", "temperature", "timeout", "max_retries", "retry_delay"):
        if field in source_cfg:
            setattr(settings, field, source_cfg[field])
    return settings


def _smoke_row(entry: dict[str, Any], condition: str, snapshot: dict[str, Any], payload_equal: bool,
               display_valid: bool, stop_reason: str | None = None) -> dict[str, Any]:
    return {"run_id": entry.get("run_id"), "logical_request_id": entry.get("logical_request_id"),
            "attempt_id": entry.get("attempt_id"), "condition": condition, "replicate_id": entry.get("replicate_id"),
            "scenario_id": snapshot.get("scenario_id"), "snapshot_id": snapshot.get("snapshot_id"),
            "payload_hash": entry.get("payload_hash"), "payload_equal_to_A1": int(payload_equal),
            "display_ablation_valid": int(display_valid), "response_content_ref": entry.get("response_content_ref"),
            "content_available": entry.get("content_available"), "usage_available": entry.get("usage_available"),
            "usage": json.dumps(entry.get("usage") or {}, ensure_ascii=False, sort_keys=True),
            "requested_model": entry.get("requested_model"), "returned_model": entry.get("returned_model"),
            "parse_status": entry.get("parse_status"), "validation_status": entry.get("validation_status"),
            "error_class": entry.get("error_class"), "error_code": entry.get("error_code"),
            "error_field": entry.get("error_field"), "error_detail": json.dumps(entry.get("error_detail") or {}, ensure_ascii=False, sort_keys=True),
            "accepted": entry.get("accepted"),
            "committed": entry.get("committed"), "stop_reason": stop_reason}


def smoke(out: Path) -> dict[str, Any]:
    """Only a freshly authorized/configured run can dispatch. Never reuse r0."""
    from .v232_persistence import RecordedAttempt, configured_client
    out = Path(out).resolve(); cfg = _json(out/'p0_config.json', {}); gates = _json(out/'p0_gates.json', {})
    if any((out/'requests').glob('*.request.json')) or (out/'paid_halt.json').exists():
        raise RuntimeError('existing_paid_block_is_closed; local recovery/report only')
    if not cfg.get('live_authorized_after_contract_freeze', False):
        raise RuntimeError('corrected_configuration_not_authorized_for_new_live_block')
    if gates.get('contract_smoke') != 'READY_OFFLINE' or gates.get('repository_regression') != 'PASS':
        raise RuntimeError('offline_tests_not_passed')
    if gates.get('accounting_recovery') != 'PASS':
        raise RuntimeError('budget_not_verified')
    if cfg.get('tested_code_hashes') != {str(p.relative_to(ROOT)):sha256(p) for p in _code_paths()}:
        raise RuntimeError('tested_source_hash_mismatch')
    snapshot = _load_selected_snapshot(out)
    if not snapshot or not snapshot.get('decoder_verified') or not snapshot.get('source_verified'):
        raise RuntimeError('no_verified_snapshot')
    context, record, decision = _snapshot_context(snapshot)
    client = configured_client(_settings_for_smoke())
    a = client.request_payload(context); bcontext = text_ablate(context)
    allowed, diffs = _public_text_only_diff(context,bcontext)
    if not allowed or a != client.request_payload(deepcopy(context)):
        raise RuntimeError('payload_contract_mismatch')
    write_json(out/'frozen_smoke_plan.json',{'snapshot':snapshot,'A_payload_hash':digest(a),
               'B_payload_hash':digest(client.request_payload(bcontext)), 'B_diff':diffs,
               'conditions':['A1','A2','B_DISPLAY_ABLATION'],'max_attempts':3,'retry_limit':0})
    store = RecordedAttempt(out, min(cfg['remaining_pilot_cny'],cfg['remaining_total_cny']), 3)
    rows=[]
    for condition in ('A1','A2','B_DISPLAY_ABLATION'):
        supplied = bcontext if condition=='B_DISPLAY_ABLATION' else deepcopy(context)
        meta={'run_id':out.name,'logical_request_id':f"{snapshot['snapshot_id']}:{condition}",
              'source_run_id':snapshot['source_run_id'],'scenario_id':snapshot['scenario_id'],
              'snapshot_id':snapshot['snapshot_id'],'condition':condition,'replicate_id':condition,
              'requested_model':client.settings.model,'decoder_version':sha256(ROOT/'avalon/eval/v2/v21_contract.py')}
        entry=store.run(client,{'view':decision['view'],'marginals':decision['marginals']},supplied,meta)
        rows.append(_smoke_row(entry,condition,snapshot,condition!='B_DISPLAY_ABLATION',True))
        write_csv(out/'contract_smoke_results.csv',rows,_required_fields()['contract_smoke_results.csv'])
        if not entry['accepted'] or entry.get('billing_error_class'):
            break
    return {'status':'complete' if len(rows)==3 and all(r['accepted'] for r in rows) else 'STOPPED_FAIL_CLOSED','rows':rows}


def run_tests(out: Path) -> dict[str, Any]:
    """Run targeted tests and the complete repository suite, without paid calls."""
    import xml.etree.ElementTree as ET
    out = Path(out).resolve()
    env = {**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTHONHASHSEED": "0"}
    code_before = {str(p.relative_to(ROOT)):sha256(p) for p in _code_paths()}
    results = {}
    for name, targets in (("unit", ["tests/eval/test_v232_r2.py"]), ("regression", ["tests"])):
        xml, log = out/f"{name}_tests.xml", out/f"{name}_tests.log"
        command = [sys.executable,"-m","pytest","-q",*targets,f"--junitxml={xml}"]
        started = datetime.now(timezone.utc).isoformat()
        with log.open("w",encoding="utf-8") as stream:
            completed = subprocess.run(command,cwd=ROOT,env=env,stdout=stream,stderr=subprocess.STDOUT,check=False)
        cases = ET.parse(xml).findall('.//testcase') if xml.exists() else []
        failures = sum(c.find('failure') is not None for c in cases)
        errors = sum(c.find('error') is not None for c in cases)
        skipped = sum(c.find('skipped') is not None for c in cases)
        result = {'test_run_id':f'{out.name}:{name}:{started}', 'command':command,
                  'scope':targets,'started_utc':started,'ended_utc':datetime.now(timezone.utc).isoformat(),
                  'exit_code':completed.returncode,'executed_test_count':len(cases),
                  'unique_test_id_count':len({(c.get('classname'),c.get('name')) for c in cases}),
                  'failures':failures,'errors':errors,'skipped':skipped,
                  'status':'PASS' if completed.returncode==0 and cases and not failures+errors else 'FAIL',
                  'code_hashes':code_before,'xml_sha256':sha256(xml) if xml.exists() else None,
                  'log_sha256':sha256(log)}
        results[name] = result
        write_json(out/'test_execution.json',results)
    code_after = {str(p.relative_to(ROOT)):sha256(p) for p in _code_paths()}
    stable = code_before == code_after
    cfg = _json(out/'p0_config.json',{})
    cfg.update(tests=results,tested_code_hashes=code_before,tested_code_unchanged=stable)
    write_json(out/'p0_config.json',cfg)
    gates = _json(out/'p0_gates.json',{})
    gates['repository_regression'] = results['regression']['status'] if stable else 'FAIL_CODE_CHANGED_DURING_TEST'
    gates['offline_contract_tests'] = results['unit']['status']
    # A passing local test must never overwrite a failed/closed live gate.
    if not any((out/'requests').glob('*.request.json')) and not (out/'paid_halt.json').exists():
        gates['contract_smoke'] = 'READY_OFFLINE' if all(r['status']=='PASS' for r in results.values()) and stable else 'BLOCKED_TEST_FAILURE'
    write_json(out/'p0_gates.json',gates)
    if not stable or any(r['status']!='PASS' for r in results.values()):
        raise SystemExit(1)
    return results


def report(out: Path) -> dict[str, Any]:
    from .v22_runner import offline_guard
    with offline_guard():
        return _report_data(Path(out).resolve())


def _report_data(out: Path) -> dict[str, Any]:
    """Rebuild every summary from immutable requests/receipts and verification."""
    from .v232_persistence import safe_transport
    from .live import token_cost, PRICING, price_period
    from .v21_reporting import ratio
    import csv
    import xml.etree.ElementTree as ET
    cfg = _json(out/'p0_config.json', {})
    verification = _json(out/'replay_verification_details.json', [])
    if not verification and (out/'replay_verification.csv').exists():
        with (out/'replay_verification.csv').open() as stream: verification=list(csv.DictReader(stream))
    snapshots = _json(out/'eligible_snapshot_manifest.json', {})
    adapter = _json(out/'request_adapter_audit.json', {})
    attempts=[]; known_estimate=0.; known_upper=0.; unknown_reserve=0.; pending=0.; known_count=0
    for request_path in sorted((out/'requests').glob('*.request.json')):
        req=_json(request_path); uid=req.get('attempt_uid') or request_path.name.split('.')[0]
        response_path=request_path.with_name(f'{uid}.response.json'); saved=_json(response_path,{})
        row={**{k:v for k,v in req.items() if k not in {'context','payload','reservation'}},
             **{k:v for k,v in saved.items() if k not in {'context','payload','transport','raw_response'}},
             'attempt_id':uid,'attempt_index':req.get('attempt_index',0),'schema_version':SCHEMA_VERSION,
             'reserved_cost':req['reservation']['cny']}
        telemetry=saved.get('transport',{})
        usage=saved.get('usage') or telemetry.get('usage')
        row.update(usage=usage or None,usage_available=int(bool(usage)))
        if saved:
            if saved.get('usage_status')=='reported':
                known_count+=1;known_upper+=saved['budget_charged_cny'];known_estimate+=saved['estimated_cny']
            elif saved.get('usage_status')!='not_sent':unknown_reserve+=saved['budget_charged_cny']
        else:
            pending+=req['reservation']['cny']
            row.update(accepted=0,committed=0,validation_status='not_run',parse_status='unavailable',
                       error_class='billing_unknown',error_code='sent_response_unknown',settlement_status='pending_reserved')
        ref=row.get('response_content_ref'); body=out/ref if ref else None
        if body and body.exists():
            row['content_available']=1
            row['content_integrity_verified']=sha256(body)==row.get('response_content_hash')
            if row.get('error_class')=='schema_contract_mismatch':
                try:row.update(_schema_diagnostic(json.loads(body.read_text()), req.get('context',{})))
                except json.JSONDecodeError:pass
        else:
            row['content_available']=0
            row['content_integrity_verified']=False
        # One final row per attempt is the report projection. The event journal
        # and original response files remain append-only/read-only evidence.
        attempts.append(row)
    attempts.sort(key=lambda r:r.get('sent_at',''))
    for name,rows in [('api_attempts.jsonl',attempts),('validation_failures.jsonl',[r for r in attempts if r.get('validation_status')=='rejected'])]:
        _write_text(out/name,''.join(canonical(r)+'\n' for r in rows))
    a1 = next((r for r in attempts if r.get('condition')=='A1'), {})
    request_rows = [_json(p) for p in sorted((out/'requests').glob('*.request.json'))]
    aa_context = next((r.get('context') for r in request_rows if r.get('condition')=='A1'), None)
    bb_context = next((r.get('context') for r in request_rows if r.get('condition')=='B_DISPLAY_ABLATION'), None)
    display_valid, display_diff = _public_text_only_diff(aa_context,bb_context) if aa_context and bb_context else (False,[])
    write_json(out/'payload_contract_audit.json',{
        'A1_A2_payload_equal': len([r for r in attempts if r.get('condition') in {'A1','A2'}])==2 and
            all(r.get('payload_hash')==a1.get('payload_hash') for r in attempts if r.get('condition')=='A2'),
        'B_public_text_only':display_valid,'B_diff':display_diff,'raw_requests_are_source':True})
    smoke_rows=[_smoke_row(r,r.get('condition'),{'scenario_id':r.get('scenario_id'),'snapshot_id':r.get('snapshot_id')},
                           r.get('payload_hash')==a1.get('payload_hash') and bool(a1),display_valid) for r in attempts]
    write_csv(out/'contract_smoke_results.csv',smoke_rows,_required_fields()['contract_smoke_results.csv'])
    prior=_json(R1_SOURCE/'cost_summary.json',{})
    prior_reported=prior.get('budget_snapshot',{}).get('conservative_budget_charged_cny')
    prior_upper=0.;prior_unknown=0;prior_attempts=0
    for path in sorted((R1_SOURCE/'requests').glob('*.request.json')):
        prior_request=_json(path);prior_attempts+=1
        prior_response=_json(path.with_name(path.name.replace('.request.json','.response.json')),{})
        if prior_response:
            prior_upper+=prior_response['budget_charged_cny']
            prior_unknown+=prior_response.get('usage_status')=='unavailable'
        else:
            prior_upper+=prior_request['reservation']['cny'];prior_unknown+=1
    prior_verified=bool(prior_attempts and prior_reported is not None and abs(prior_upper-prior_reported)<1e-10)
    if not prior_attempts:prior_upper=None
    charged=known_upper+unknown_reserve
    current_exposure=charged+pending
    cost={'budget_cny':TOTAL_BUDGET_CNY,'pilot_budget_cny':PILOT_BUDGET_CNY,
          'prior_run_id':R1_SOURCE.name,'prior_run_conservative_cny':prior_upper,
          'prior_attempts_recomputed':prior_attempts,'prior_unknown_or_pending_attempts':prior_unknown,
          'prior_summary_matches_raw_ledger':prior_verified,
          'logical_requests':len({r.get('logical_request_id') for r in attempts}),'attempts':len(attempts),
          'known_usage_attempts':known_count,'estimated_cny_from_reported_usage':known_estimate if known_count else None,
          'known_usage_conservative_cny':known_upper,'rate_difference_buffer_cny':known_upper-known_estimate,
          'unknown_usage_reserved_cny':unknown_reserve,'in_flight_reserved_cny':pending,
          'current_run_conservative_cny':current_exposure,
          'unknown_usage':sum(r.get('usage_status')=='unavailable' for r in attempts),
          'invoice_cost_cny':None,'prices_source':'https://api-docs.deepseek.com/zh-cn/quick_start/pricing/',
          'remaining_total_cny_after_run':max(0.,TOTAL_BUDGET_CNY-prior_upper-current_exposure) if prior_upper is not None else None,
          'remaining_pilot_cny_after_run':max(0.,PILOT_BUDGET_CNY-prior_upper-current_exposure) if prior_upper is not None else None,
          'note':'Known cost estimate, rate buffer, unknown reservation and in-flight reservation are disjoint; not an invoice.'}
    write_json(out/'cost_summary.json',cost)
    test_results={}; unique=set(); executed=0
    test_execution=_json(out/'test_execution.json',{})
    for kind,name in [('unit','unit_tests.xml'),('full_regression','regression_tests.xml')]:
        path=out/name
        if not path.exists():test_results[kind]={'status':'NOT_RUN'};continue
        tree=ET.parse(path); cases=tree.findall('.//testcase'); ids={f"{c.get('classname')}::{c.get('name')}" for c in cases}
        failures=sum(c.find('failure') is not None for c in cases);errors=sum(c.find('error') is not None for c in cases)
        skipped=sum(c.find('skipped') is not None for c in cases)
        execution=test_execution.get('unit' if kind=='unit' else 'regression',{})
        bound=execution.get('xml_sha256')==sha256(path)
        test_results[kind]={'executed_test_count':len(cases),'unique_test_id_count':len(ids),
            'failures':failures,'errors':errors,'skipped':skipped,'status':'PASS' if not failures+errors else 'FAIL',
            'artifact':name,'sha256':sha256(path),
            'test_run_id':execution.get('test_run_id'),'exit_code':execution.get('exit_code'),
            'command':execution.get('command'),'scope':execution.get('scope'),
            'execution_metadata_bound':bound}
        if not bound or execution.get('exit_code')!=0:
            test_results[kind]['status']='UNVERIFIED_EXECUTION' if not bound else 'FAIL'
        executed+=len(cases);unique|=ids
    statuses=Counter(r.get('verification_status') for r in verification)
    history=[]; history_executed=executed; history_unique=set(unique)
    for folder in sorted((out/'validation_history').glob('*')):
        metadata=_json(folder/'test_execution.json',{})
        if not metadata:continue
        entry={'path':str(folder.relative_to(out)),'results':metadata}
        for filename in ('unit_tests.xml','regression_tests.xml'):
            path=folder/filename
            if not path.exists():continue
            cases=ET.parse(path).findall('.//testcase');history_executed+=len(cases)
            history_unique|={f"{c.get('classname')}::{c.get('name')}" for c in cases}
        history.append(entry)
    accepted=sum(int(r.get('accepted') or 0) for r in attempts)
    content=sum(r.get('content_available',0) for r in attempts)
    source_pass=statuses['BASELINE_VERIFIED']; partial=statuses['PARTIAL_ARCHIVE_VERIFIED_PREFIX']
    excluded=statuses['UNVERIFIABLE']
    gates={'response_persistence':'PASS_LOCAL_RECEIPT_TESTS' if test_results.get('unit',{}).get('status')=='PASS' else 'NOT_VERIFIED',
           'failure_diagnostics':'PASS_LOCAL_AND_OBSERVED' if attempts else 'PASS_LOCAL_ONLY',
           'accounting_recovery':'PASS' if not pending+unknown_reserve and not prior_unknown and prior_verified else 'BLOCKED_UNKNOWN_COST',
           'baseline_verification':'PARTIAL_VERIFIED_PREFIX' if partial or excluded else 'PASS',
           'sample_exclusion':'PASS' if snapshots.get('snapshots') else 'NOT_RUN',
           'repository_regression':test_results.get('full_regression',{}).get('status','NOT_RUN'),
           'contract_smoke':('FAIL_REQUEST_PROTOCOL_CONFLICT' if adapter and attempts else
                ('PASS' if len(attempts)==3 and accepted==3 else 'STOPPED_OR_FAILED' if attempts else 'NOT_RUN')),
           'corrected_adapter_live':'NOT_RUN','paid_block_closed':(out/'paid_halt.json').exists(),
           'evidence':{'response_persistence':{'numerator':content,'denominator':len(attempts),'path':'response_journal.jsonl','observed_revision':'r0 body saved after ChatClient parse, before decode; r1 callback tested locally'},
                       'failure_diagnostics':{'numerator':sum(bool(r.get('error_class')) for r in attempts if not r.get('accepted')),'denominator':len(attempts)-accepted,'path':'validation_failures.jsonl'},
                       'baseline':{'complete':source_pass,'partial':partial,'excluded':excluded,'total':len(verification),'path':'replay_verification_details.json'},
                       'snapshots':{'verified_source':sum(r.get('source_verified',0) for r in snapshots.get('snapshots',[])),
                                    'eligible_exact_tie':snapshots.get('eligible',0),'planned':snapshots.get('planned',0),'path':'eligible_snapshot_manifest.json'}}}
    labels=(['PARTIAL_TERMINAL_ARCHIVE'] if partial else [])+(['CONTRACT_SMOKE_FAILED','INCONCLUSIVE','PROTOCOL_DEVIATION_RECORDED'] if attempts and accepted<len(attempts) else [])
    gates['labels']=labels
    write_json(out/'p0_gates.json',gates)
    summary={'run_id':out.name,'version':VERSION,'status':'offline_repair_complete_live_gate_failed' if attempts and not accepted else 'offline_report',
             'network_calls':len(attempts),'new_effect_samples':0,
             'sources':{'total':len(verification),'passed':source_pass,'partial_verified_prefix':partial,'excluded':excluded,
                        'unresolved':excluded,'status_counts':dict(statuses)},
             'snapshots':{'planned':snapshots.get('planned',0),
                          'source_verified':sum(r.get('source_verified',0) for r in snapshots.get('snapshots',[])),
                          'eligible_exact_tie':snapshots.get('eligible',0),'excluded':snapshots.get('excluded',0),
                          'unresolved':sum(not r.get('source_verified') for r in snapshots.get('snapshots',[]))},
             'api':{'logical_requests':cost['logical_requests'],'attempts':len(attempts),'accepted':accepted,'failed':len(attempts)-accepted,
                    'content_retention':ratio(content,len(attempts)),'usage_retention':ratio(known_count,len(attempts)),
                    'failure_classes':dict(Counter(r.get('error_code') for r in attempts if not r.get('accepted'))),
                    'transport_retries':0,'schema_retries':0,'committed':sum(int(r.get('committed') or 0) for r in attempts)},
             'language_effect':{'value':None,'status':'UNAVAILABLE','reason':'no valid B output; contract smoke not an effect experiment'},
             'corrected_adapter_live':'NOT_RUN','historical_missing_response_bodies':{'run_id':R1_SOURCE.name,'count':30,'status':'UNRECOVERABLE'},
             'tests':test_results,'executed_test_count_including_overlap':executed,'unique_test_id_count_union':len(unique),
             'test_count_scope':'final-code targeted + complete regression; exploratory shell checks are not presented as independent coverage',
             'preserved_validation_history':history,
             'formal_validation_history_including_final':{'executed_test_count':history_executed,'unique_test_id_count':len(history_unique)},
             'cost':cost,'gates':gates,'labels':labels,'request_adapter_audit':adapter,
             'p1_usable_source':'replay_cutoffs.jsonl verified cutoffs only; 10 exact-tie snapshots in eligible_snapshot_manifest.json; partial tail is excluded',
             'not_run':['corrected-configuration live retest','large pilot','candidate intervention','full live games','production deployment']}
    write_json(out/'summary.json',summary)
    root_cause=adapter.get('root_cause','No paid contract diagnosis in this run.')
    report_lines=['# Avalon V2.3.2-r2 P0 修复报告','',f"运行 `{out.name}`。离线工程修复与真实合同门槛分开报告。",'',
        f"**结论：{gates['contract_smoke']}；修正请求适配后的真实复测 NOT_RUN。**",'',
        f"根因与证据：{root_cause}。三份正文包含旧式完整计划字段；`request_adapter_audit.json` 逐条重建的原 payload 与实际 transport SHA-256 相同。`request_adapter_before_after.diff` 仅展示现有菜单协议的接入差异，世界提示词和 decoder 未改。旧 r1 的 30 份丢失正文不能据此倒推原因。",'',
        '留存缺口已由旧 pilot 源码确认：先调用动作 decoder，异常分支只结算 usage 并保存粗分类，没有写下安全动作正文。修复将持久化前移到动作 JSON 解析前；持久化失败停止派发，未知 usage 保留预留。', '',
        '本轮实际修改：评估响应持久化/恢复、逐来源回放、报告；ChatClient 增加默认关闭的 evidence sink，在动作 JSON 解析前调用。生产 belief、证据、规则、菜单、原子提交、刺客 exact argmax 均保持不变。', '',
        f"来源 {len(verification)}：完整通过 {source_pass}、部分前缀通过 {partial}、排除 {excluded}、未解 {excluded}。r7 `A-main-single_seat-940004-joint_v2` 在 seq 87 后缺终局，已执行 43 笔事务、64 个决策可核验，之后的未提交决定不解锁快照。不是全量 PASS。",'',
        f"快照计划 {snapshots.get('planned',0)}、exact-tie 合格 {snapshots.get('eligible',0)}、排除 {snapshots.get('excluded',0)}。逐 cutoff 核对生产 Game、完整原始私有视图、saved marginals、可用完整 posterior 哈希、菜单及实际 decoder。生成语料只有边际和事件可交叉核验，不能声称有历史完整 posterior 存档。所有跨 variant 投影属于诊断，不要求与源 posterior 相同。",'',
        f"API：逻辑请求 {cost['logical_requests']}、attempt {len(attempts)}、accepted {accepted}、failed {len(attempts)-accepted}、已提交 0。正文留存 {content}/{len(attempts)}，usage {known_count}/{len(attempts)}。A1/A2 实际 payload 相同；B 只删授权公开文字。B 有效数为 0 时效应为 null / UNAVAILABLE。",'',
        '执行偏差：初版 smoke 首次合同失败后仍发了后两次，共 3 次；未按附件及时停止。修正后已增加 durable halt，当前运行永久关闭付费派发。三次失败均保留，不计为通过，不自动补跑。价格在本轮请求后才重新核对官方文档，复核与冻结账本费率一致；不能宣称请求前完成了这次复核。', '',
        '初版三条 HTTP status 未记录，保持缺失；修正版新增记录且兼容没有 status 的测试传输包装器。初版 dispatch 源码没有另存完整独立快照；当时哈希、原始请求及之后的 r0 副本保留，最终修正版源码快照不冒充 dispatch 版本。', '',
        f"本轮 usage 估算 ¥{known_estimate:.8f}；保守已知费率占用 ¥{known_upper:.8f}（其中费率差额 ¥{known_upper-known_estimate:.8f}）；未知预留 ¥{unknown_reserve:.8f}；在途 ¥{pending:.8f}。历史 r1 保守占用 ¥{prior_upper}；共享总额剩余 ¥{cost['remaining_total_cny_after_run']}，pilot 剩余 ¥{cost['remaining_pilot_cny_after_run']}。这些是 token 估算，不是账单。费率来源：[DeepSeek 官方价格](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)。",'',
        f"测试（不把重叠相加为独立覆盖）：{json.dumps(test_results,ensure_ascii=False)}。执行数含重叠 {executed}；unique ID 并集 {len(unique)}。真实 smoke 的已观察 revision 与最终离线修复的代码哈希分开保留。",'',
        f"此前完整回归的 2 项传输包装器兼容性失败已保存在 `validation_history/`，没有覆盖成通过。计入已留档前版和最终版的正式验证共执行 {history_executed} 项，unique ID 并集 {len(history_unique)}；最终门槛只由最终代码的结果决定。", '',
        'P1 只可使用 `replay_cutoffs.jsonl` 中 verified=true 的截止点；这不要求真实语言合同通过。真实语言实验仍需重新规划，不自动恢复大 pilot。', '',
        '旧 r1 30 份正文不可恢复；修复版没有新模型样本。没有启动候选、整局真实对照或生产部署。', '',
        '无网络复算命令：', '```sh', 'cd /Users/jiayaochen/Desktop/avalon',
        f'python -m avalon.eval.v2.v232_runner --mode p0-report-only --run-dir {out}', '```', '',
        '证据：`response_journal.jsonl`、`requests/`、`responses/`；一行一 attempt 的 `api_attempts.jsonl` 和 `validation_failures.jsonl` 是从这些原始记录重算的视图。`replay_verification_details.json`、`replay_cutoffs.jsonl` 保留逐来源检查。所有 API key、Authorization、供应商独立推理字段均不进入导出。']
    _write_text(out/'p0_report.md','\n'.join(report_lines)+'\n')
    final_hashes={str(p.relative_to(ROOT)):sha256(p) for p in _code_paths()}
    cfg.update(status=summary['status'],network_calls=len(attempts),live=bool(attempts),network_access=bool(attempts),
               live_authorized_after_contract_freeze=False,final_code_hashes=final_hashes,tests=test_results,
               stage_b_gate=gates['contract_smoke'])
    write_json(out/'p0_config.json',cfg)
    manifest=_json(out/'p0_source_manifest.json',{})
    manifest.update(version=VERSION,schema_version=SCHEMA_VERSION,final_code_hashes=final_hashes,
                    network_calls=len(attempts),report_generated_utc=datetime.now(timezone.utc).isoformat(),
                    live_revision='r0 unconfigured; raw logs retained',delivery_revision='r1 configured; offline tested only')
    write_json(out/'p0_source_manifest.json',manifest)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", required=True, choices=("prepare", "verify", "tests", "smoke", "report-only"))
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    out = args.run_dir.resolve()
    if args.mode == "prepare": prepare(out)
    elif args.mode == "verify": verify(out)
    elif args.mode == "tests": run_tests(out)
    elif args.mode == "smoke": smoke(out)
    elif args.mode == "report-only": report(out)


if __name__ == "__main__":
    main()
