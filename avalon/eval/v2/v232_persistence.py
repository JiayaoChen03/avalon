"""Evaluation-only, single-attempt durable boundary; no game/strategy changes."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path

from avalon.eval.simulation import digest
from .live import BudgetStop, PRICING, token_cost, price_period
from .v21_contract import configure_transport, decode_menu
from .v21_runtime import DurableBudget, atomic_json, json_read


def now():
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def exclusive(folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    os.chmod(folder, 0o700)
    with (folder / '.p0.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def safe_transport(telemetry):
    names = {'http_status', 'id', 'model', 'created', 'system_fingerprint',
             'finish_reason', 'response_sha256', 'request_sha256',
             'transport_error', 'envelope_error', 'refusal_present', 'usage'}
    return {k: deepcopy(v) for k, v in telemetry.items() if k in names}


class RecordedAttempt:
    """One logical request is sent at most once. Resumption is local only.

    A/A use different logical IDs and therefore make independent requests.
    No transport/schema retry is hidden here. A failed or unknown attempt
    halts the entire block. Game commits remain exclusively owned by Session.
    """
    def __init__(self, folder, limit, max_calls=3):
        self.folder = Path(folder)
        self.limit, self.max_calls = limit, max_calls
        self.folder.mkdir(parents=True, exist_ok=True)

    def _halt(self, reason, attempt_id):
        atomic_json(self.folder / 'paid_halt.json', {'reason': reason,
                    'attempt_id': attempt_id, 'at': now(), 'new_requests_allowed': False})

    def _accounting(self, request, receipt):
        usage = receipt.get('usage') or {}
        reservation = request['reservation']
        upper = token_cost(usage, PRICING['peak'])
        estimate = token_cost(usage, PRICING[price_period(request['sent_at'])])
        if upper is None:
            self._halt('billing_unknown', request['attempt_uid'])
        return {'budget_charged_cny': reservation['cny'] if upper is None else upper,
                'estimated_cny': estimate, 'usage_status': 'unavailable' if upper is None else 'reported',
                'settlement_status': 'unknown_usage_retained_reservation' if upper is None else 'usage_estimated',
                'reserved_cost': reservation['cny'], 'estimated_cost': estimate,
                'settled_cost': reservation['cny'] if upper is None else upper,
                'billing_error_class': 'billing_unknown' if upper is None else None}

    def _finish_received(self, uid, request, receipt, context, supplied, decoder):
        from .v232_r2 import classify_failure, _schema_diagnostic, _append_jsonl
        budget = DurableBudget(self.folder, self.limit, self.max_calls)
        row = deepcopy(receipt)
        if row.get('response_content_ref'):
            body = self.folder / row['response_content_ref']
            if not body.is_file() or hashlib.sha256(body.read_bytes()).hexdigest() != row['response_content_hash']:
                self._halt('body_missing_or_hash_mismatch', uid)
                raise RuntimeError('body_missing_or_hash_mismatch')
        raw = None
        try:
            telemetry = row.get('transport', {})
            from avalon.llm import LLMError
            if telemetry.get('transport_error'):
                raise LLMError(telemetry['transport_error'])
            if telemetry.get('envelope_error'):
                raise LLMError('invalid_response')
            if telemetry.get('refusal_present'):
                raise LLMError('refusal')
            if row.get('finish_reason') == 'length':
                raise LLMError('truncated_response')
            if not row.get('response_content_ref'):
                raise LLMError('empty_response')
            content = body.read_text(encoding='utf-8')
            if not content.strip():
                raise LLMError('empty_response')
            if row.get('redaction_applied'):
                raise ValueError('redacted_body_not_eligible_for_execution')
            if content.startswith('```json\n') and content.rstrip().endswith('```'):
                content = content.strip()[8:-3].strip()
            from avalon.llm import _reject_constant
            raw = json.loads(content, parse_constant=_reject_constant)
            if row.get('finish_reason') != 'stop':
                raise LLMError('invalid_response')
            action, details = decoder(raw, context, supplied)
            row.update(details)
            row.update(accepted=1, parse_status='json_parsed', validation_status='accepted',
                       validated_action=action, error_class=None, error_code=None, error_field=None)
        except (ValueError, TypeError, KeyError, LLMError) as exc:
            row.update(classify_failure(exc, row.get('transport', {}), phase='decoder'), accepted=0)
            if isinstance(exc, LLMError):
                row['parse_status'] = 'not_parsed' if row.get('content_available') else 'no_content'
            if str(exc) == 'schema' or isinstance(exc, TypeError):
                row.update(_schema_diagnostic(raw, supplied))
            self._halt(row['error_class'], uid)
        row.update(self._accounting(request, receipt), phase='validated', committed=0, commit_id=None)
        _append_jsonl(self.folder / 'response_journal.jsonl', row)
        if not row['accepted']:
            _append_jsonl(self.folder / 'validation_failures.jsonl', row)
        budget.finish(uid, row)
        atomic_json(self.folder / 'attempt_states' / f'{uid}.json',
                    {'status': 'validated', 'accepted': row['accepted'], 'attempt_id': uid})
        return row

    def run(self, client, context, supplied, meta, *, decoder=decode_menu):
        from .v232_r2 import ResponseJournal
        logical = meta['logical_request_id']
        with exclusive(self.folder):
            matches = [p for p in (self.folder / 'requests').glob('*.request.json')
                       if json_read(p).get('logical_request_id') == logical]
            if matches:
                if len(matches) != 1:
                    raise RuntimeError('duplicate_logical_request')
                p = matches[0]; request = json_read(p); uid = request['attempt_uid']
                if request['payload_hash'] != digest(client.request_payload(supplied)):
                    raise RuntimeError('resume_configuration_mismatch_new_run_required')
                result = p.with_name(f'{uid}.response.json')
                if result.exists():
                    return json_read(result)
                rp = self.folder / 'responses' / f'{uid}.receipt.json'
                if rp.exists():
                    return self._finish_received(uid, request, json_read(rp), context, supplied, decoder)
                state = self.folder / 'attempt_states' / f'{uid}.json'
                status = json_read(state).get('status') if state.exists() else 'unknown'
                self._halt('sent_response_or_billing_unknown' if status != 'reserved' else 'reserved_not_sent', uid)
                raise RuntimeError('pending_attempt_no_automatic_resend')
            if (self.folder / 'paid_halt.json').exists():
                raise RuntimeError('paid_block_halted')
            budget = DurableBudget(self.folder, self.limit, self.max_calls)
            if budget.unknown:
                self._halt('prior_usage_unknown', None)
                raise BudgetStop('prior_usage_unknown')
            payload = client.request_payload(supplied)
            binding = {**meta, 'payload_hash': digest(payload),
                       'prompt_hash': digest(payload['messages']),
                       'model_config_hash': digest({k: v for k, v in payload.items() if k != 'messages'}),
                       'attempt_index': 0, 'sent_at': now(), 'context': supplied,
                       'payload': payload, 'adapter_revision': 'r2-configured-menu-receipt-before-parse'}
            uid, reservation = budget.begin(payload, binding)
            request = json_read(self.folder / 'requests' / f'{uid}.request.json')
            state = self.folder / 'attempt_states' / f'{uid}.json'
            atomic_json(state, {'status': 'reserved', 'attempt_id': uid})
            journal = ResponseJournal(self.folder)

            def sink(telemetry):
                receipt = journal.persist({**binding, 'context': None, 'payload': None,
                    'attempt_id': uid, 'reserved_cost': reservation['cny'],
                    'received_at': now(), 'settlement_status': 'pending_usage_settlement',
                    'estimated_cost': None, 'settled_cost': None,
                    'retry_of_attempt_id': None, 'retry_reason': None}, telemetry, None)
                receipt['transport'] = safe_transport(telemetry)
                atomic_json(self.folder / 'responses' / f'{uid}.receipt.json', receipt)
                atomic_json(state, {'status': 'received', 'attempt_id': uid})

            client.response_sink = sink
            atomic_json(state, {'status': 'sent', 'attempt_id': uid, 'sent_at': binding['sent_at']})
            try:
                # ChatClient persists via sink before attempting action JSON.
                # The return value is deliberately not a commit or repair path.
                client.complete(supplied)
            except RuntimeError as exc:
                from avalon.llm import LLMError
                if not isinstance(exc, LLMError):
                    self._halt('response_persistence_failed', uid)
                    raise
                # LLMError inherits RuntimeError; persisted failures are decoded
                # locally and remain failed. No second provider request occurs.
            finally:
                client.response_sink = None
            receipt_path = self.folder / 'responses' / f'{uid}.receipt.json'
            if not receipt_path.exists():
                self._halt('response_evidence_missing', uid)
                raise RuntimeError('response_evidence_missing')
            return self._finish_received(uid, request, json_read(receipt_path), context, supplied, decoder)

    def release_confirmed_unsent(self, uid):
        """An explicit local transition, allowed only before the send marker."""
        with exclusive(self.folder):
            state = self.folder/'attempt_states'/f'{uid}.json'
            if not state.exists() or json_read(state).get('status') != 'reserved':
                raise RuntimeError('cannot_confirm_request_was_not_sent')
            budget = DurableBudget(self.folder,self.limit,self.max_calls)
            budget.finish(uid,{'attempt_id':uid,'accepted':0,'committed':0,'transport':{},
                              'budget_charged_cny':0.0,'estimated_cny':0.0,
                              'usage_status':'not_sent','settlement_status':'confirmed_unsent_release'})
            atomic_json(state,{'status':'cancelled_before_send','attempt_id':uid})


def configured_client(settings):
    from avalon.llm import ChatClient
    return configure_transport(ChatClient(settings))
