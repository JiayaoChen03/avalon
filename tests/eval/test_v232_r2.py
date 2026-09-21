import json
from pathlib import Path
from copy import deepcopy
from unittest.mock import patch
import pytest

from avalon.eval.v2.v232_r2 import (
    ResponseJournal,
    _prefix_checks,
    _public_text_only_diff,
    _safe_response_content,
    _schema_diagnostic,
    classify_failure,
)
from avalon.llm import LLMError
from avalon.llm import ChatClient, Settings, SYSTEM
from avalon.eval.v2.v232_persistence import RecordedAttempt, configured_client
from avalon.eval.v2.v21_contract import menu_context, decode_menu, MENU_PROTOCOL
from avalon.eval.v2.v21_runtime import DurableBudget, atomic_json
from tests.eval.test_v21 import context, response
from tests.test_llm import endpoint


def synthetic_envelope(content, usage=True, finish='stop'):
    body={'id':'synthetic-provider','model':'synthetic-model',
          'choices':[{'finish_reason':finish,'message':{'content':content,'reasoning_content':'SECRET_REASONING'}}]}
    if usage: body['usage']={'prompt_tokens':10,'completion_tokens':5,'total_tokens':15}
    return body


def synthetic_meta(logical='A1'):
    return {'run_id':'synthetic-fixture','logical_request_id':logical,
            'source_run_id':'synthetic','scenario_id':'synthetic','snapshot_id':'synthetic',
            'condition':logical,'replicate_id':logical,'requested_model':'synthetic-model',
            'decoder_version':'existing-production-menu'}


def _meta(tmp_path):
    return {
        "run_id": "synthetic-r2",
        "logical_request_id": "synthetic:A1",
        "attempt_id": "attempt-1",
        "attempt_index": 0,
        "requested_model": "synthetic-model",
    }


def test_rejected_json_is_persisted_before_validation(tmp_path):
    journal = ResponseJournal(tmp_path)
    entry = journal.persist(
        _meta(tmp_path),
        {"response_content": '{"recommended_action":', "usage": {"prompt_tokens": 4}, "model": "synthetic"},
        ValueError("schema"),
        decoded=None,
    )
    assert entry["content_available"] == 1
    assert entry["accepted"] == 0
    assert (tmp_path / entry["response_content_ref"]).read_text() == '{"recommended_action":'
    assert len((tmp_path / "validation_failures.jsonl").read_text().splitlines()) == 1


def test_reasoning_content_is_redacted_without_accepting_action():
    content, redacted, reason = _safe_response_content(
        json.dumps({"recommended_action": {}, "reasoning_content": "secret"}, ensure_ascii=False)
    )
    assert redacted is True
    assert reason == "reasoning_content_key"
    assert "secret" not in content
    assert "REDACTED_REASONING_CONTENT" in content


def test_malformed_reasoning_marker_is_fail_closed_redaction():
    content, redacted, reason = _safe_response_content('{"reasoning_content":"secret"')
    assert redacted is True
    assert reason == "embedded_reasoning_marker_unparsed"
    assert "secret" not in content


def test_failure_classes_separate_transport_empty_and_schema():
    assert classify_failure(LLMError("empty_response"), {}, phase="transport")["error_class"] == "empty_response"
    assert classify_failure(LLMError("http_500"), {}, phase="transport")["error_class"] == "http_provider_error"
    assert classify_failure(ValueError("schema"), {}, phase="decoder")["error_class"] == "schema_contract_mismatch"


def test_schema_diagnostic_reports_extra_root_fields_without_repairing_body():
    raw = {"belief_updates": [], "interpretation": [], "public_stance_change": None,
           "recommended_action": {"action_id": "x", "parameters": {}},
           "short_rationale": "ok", "assassin_rank": ["P1"]}
    detail = _schema_diagnostic(raw, {})
    assert detail["error_code"] == "schema_envelope_fields"
    assert detail["error_field"] == "$"
    assert detail["error_detail"]["extra_fields"] == ["assassin_rank"]
    assert "assassin_rank" in raw


def test_rejected_entry_cannot_be_committed_by_journal(tmp_path):
    journal = ResponseJournal(tmp_path)
    entry = journal.persist(_meta(tmp_path), {"response_content": "{}", "usage": {}}, ValueError("schema"))
    assert entry["accepted"] == 0
    assert entry["committed"] == 0
    assert not (tmp_path / "commit.json").exists()


def test_display_ablation_only_removes_public_text():
    before = {"game": {"recent_events": [{"public_writing": "claim", "target": "P2", "citations": ["R1"]}]},
              "private_beliefs": {"marginals": {"P2": {"merlin": 0.5}}}}
    after = {"game": {"recent_events": [{"target": "P2", "citations": ["R1"]}]},
             "private_beliefs": {"marginals": {"P2": {"merlin": 0.5}}}}
    valid, diffs = _public_text_only_diff(before, after)
    assert valid is True
    assert diffs


def test_prefix_checks_marks_terminal_defect_without_rewriting_archive():
    record = {
        "schema_version": 1, "game_id": "synthetic", "seed": 1, "direction": "clockwise",
        "players": [{"id": "P1", "name": "A", "role": "ASSASSIN"},
                    {"id": "P2", "name": "B", "role": "MERLIN"}],
        "events": [{"seq": 1, "round": 1, "kind": "START", "record_id": "R1-001",
                    "players": [{"id": "P1", "name": "A"}, {"id": "P2", "name": "B"}]}],
    }
    ok, field, kind = _prefix_checks(record)
    assert ok is True
    assert field is None and kind is None


def test_configured_request_has_one_contract_and_identical_aa_payload():
    _,c=context(); supplied=menu_context(c)
    client=configured_client(Settings(api_key='unused',model='synthetic-model'))
    a=client.request_payload(supplied); b=client.request_payload(deepcopy(supplied))
    assert a==b and MENU_PROTOCOL in a['messages'][0]['content']
    assert SYSTEM not in a['messages'][0]['content']


@pytest.mark.parametrize('content,finish,usage,category',[
    ('{"broken":','stop',True,'json_parse_error'),
    ('','stop',True,'empty_response'),
    ('{"partial":','length',True,'output_truncated'),
    ('{}','stop',True,'schema_contract_mismatch'),
])
def test_transport_body_durable_before_parse_and_failure_halts(tmp_path,content,finish,usage,category):
    _,c=context(); supplied=menu_context(c)
    with endpoint(synthetic_envelope(content,usage,finish)) as (url,requests):
        client=configured_client(Settings(api_key='private-test-key',model='synthetic-model',base_url=url))
        store=RecordedAttempt(tmp_path,1)
        row=store.run(client,c,supplied,synthetic_meta())
        assert row['error_class']==category
        assert row['accepted']==0 and row['committed']==0
        assert (tmp_path/row['response_content_ref']).read_text()==content
        assert (tmp_path/row['response_content_ref']).stat().st_mode & 0o777==0o600
        assert row['http_status']==200 and row['usage_available']==1
        with pytest.raises(RuntimeError,match='halted'):
            store.run(client,c,supplied,synthetic_meta('A2'))
        assert len(requests)==1
    exports=''.join(f.read_text() for f in tmp_path.rglob('*') if f.is_file())
    assert 'private-test-key' not in exports and 'SECRET_REASONING' not in exports


def test_callback_runs_before_action_json_load(tmp_path):
    content='{"invalid":'; journal=ResponseJournal(tmp_path); called=[]
    with endpoint(synthetic_envelope(content)) as (url,requests):
        client=ChatClient(Settings(api_key='test',model='test',base_url=url))
        def sink(t):
            journal.persist(_meta(tmp_path),t,None); called.append(True)
        client.response_sink=sink
        original=json.loads
        def loads(value,*args,**kwargs):
            if value==content:
                assert called and list((tmp_path/'responses').glob('*.txt'))
            return original(value,*args,**kwargs)
        with patch('avalon.llm.json.loads',side_effect=loads),pytest.raises(LLMError):
            client.complete({})
    assert len(called)==1


def test_valid_aa_independent_then_resume_does_not_resend(tmp_path):
    _,c=context(); supplied=menu_context(c); raw=response(supplied)
    with endpoint(synthetic_envelope(json.dumps(raw))) as (url,requests):
        client=configured_client(Settings(api_key='test',model='test',base_url=url))
        store=RecordedAttempt(tmp_path,1)
        first=store.run(client,c,supplied,synthetic_meta())
        again=store.run(client,c,supplied,synthetic_meta())
        second=store.run(client,c,supplied,synthetic_meta('A2'))
        assert len(requests)==2 and first==again
        assert first['attempt_id']!=second['attempt_id'] and first['accepted']==second['accepted']==1
        assert requests[0][2]==requests[1][2]
    restored=DurableBudget(tmp_path,1,3)
    assert restored.calls==2 and restored.unknown==0


def test_unknown_usage_keeps_reserve_and_stops_next_logical(tmp_path):
    _,c=context(); supplied=menu_context(c)
    with endpoint(synthetic_envelope(json.dumps(response(supplied)),usage=False)) as (url,requests):
        client=configured_client(Settings(api_key='test',model='test',base_url=url))
        store=RecordedAttempt(tmp_path,1); row=store.run(client,c,supplied,synthetic_meta())
        assert row['usage'] is None and row['usage_available']==0
        assert row['estimated_cost'] is None and row['settled_cost']==row['reserved_cost']>0
        with pytest.raises(RuntimeError,match='halted'):store.run(client,c,supplied,synthetic_meta('B'))
        assert len(requests)==1
    assert DurableBudget(tmp_path,1,3).unknown==1


def test_storage_failure_blocks_decode_commit_and_future_http(tmp_path):
    _,c=context(); supplied=menu_context(c)
    with endpoint(synthetic_envelope(json.dumps(response(supplied)))) as (url,requests):
        client=configured_client(Settings(api_key='test',model='test',base_url=url))
        store=RecordedAttempt(tmp_path,1)
        with patch('avalon.eval.v2.v232_r2._atomic_bytes',side_effect=OSError('disk unavailable')):
            with pytest.raises(RuntimeError,match='persistence'):
                store.run(client,c,supplied,synthetic_meta())
        assert not list((tmp_path/'requests').glob('*.response.json'))
        with pytest.raises(RuntimeError):store.run(client,c,supplied,synthetic_meta('A2'))
        assert len(requests)==1
    restored=DurableBudget(tmp_path,1,3)
    assert restored.unknown==1 and restored.charged>0


def test_received_body_resumes_locally_without_second_http(tmp_path):
    _,c=context(); supplied=menu_context(c)
    with endpoint(synthetic_envelope(json.dumps(response(supplied)))) as (url,requests):
        client=configured_client(Settings(api_key='test',model='test',base_url=url));store=RecordedAttempt(tmp_path,1)
        with patch.object(store,'_finish_received',side_effect=RuntimeError('synthetic crash')):
            with pytest.raises(RuntimeError,match='synthetic crash'):store.run(client,c,supplied,synthetic_meta())
        assert list((tmp_path/'responses').glob('*.receipt.json'))
        row=store.run(client,c,supplied,synthetic_meta())
        assert row['accepted']==1 and len(requests)==1
    assert DurableBudget(tmp_path,1,3).unknown==0


def test_unsent_release_requires_durable_reserved_state(tmp_path):
    _,c=context(); supplied=menu_context(c);client=configured_client(Settings(api_key='test',model='test'))
    budget=DurableBudget(tmp_path,1,3)
    uid,reservation=budget.begin(client.request_payload(supplied),synthetic_meta())
    atomic_json(tmp_path/'attempt_states'/f'{uid}.json',{'status':'reserved'})
    RecordedAttempt(tmp_path,1).release_confirmed_unsent(uid)
    assert DurableBudget(tmp_path,1,3).charged==0
    with pytest.raises(RuntimeError):RecordedAttempt(tmp_path,1).release_confirmed_unsent(uid)


def test_response_fields_missing_not_json_failure(tmp_path):
    _,c=context(); supplied=menu_context(c)
    with endpoint({'id':'synthetic','usage':{'prompt_tokens':1,'completion_tokens':1},'choices':[]}) as (url,requests):
        client=configured_client(Settings(api_key='test',model='test',base_url=url))
        row=RecordedAttempt(tmp_path,1).run(client,c,supplied,synthetic_meta())
        assert row['error_class']=='response_missing_fields' and not row['content_available']
        assert row['usage_available']==1


def test_display_diff_rejects_private_text_or_numeric_change():
    before={'private_beliefs':{'public_writing':'private'},'game':{'recent_events':[]}}
    assert not _public_text_only_diff(before,{'private_beliefs':{},'game':{'recent_events':[]}})[0]


def test_report_cli_cannot_load_settings_or_access_network(tmp_path):
    from avalon.eval.v2.v22_runner import offline_guard
    from avalon.eval.v2.v232_r2 import _init_outputs, report
    _init_outputs(tmp_path)
    with offline_guard():
        result=report(tmp_path)
    assert result['network_calls']==0


def test_reasoning_word_without_private_field_retains_exact_bytes():
    body=' { "short_rationale" : "the word reasoning_content" } '
    saved,redacted,reason=_safe_response_content(body)
    assert saved==body and not redacted and reason is None


@pytest.mark.parametrize('rank', [['P1','P1'],['P1','P9'],[{},'P2'],None])
def test_ranking_diagnostic_handles_missing_duplicate_illegal_and_unhashable_items(rank):
    supplied={'action_menu':[{'action_id':'x','parameters':{'assassin_rank':{'permutation_of':['P1','P2']}}}]}
    raw=response(supplied,params={'assassin_rank':rank});before=deepcopy(raw)
    diagnosis=_schema_diagnostic(raw,supplied)
    assert diagnosis['error_class']=='invalid_ranking' and raw==before


@pytest.mark.parametrize('code,category',[
    ('illegal_target','illegal_seat_or_enum'),('stale_state','stale_menu_state'),
    ('unknown_or_stale_action_id','stale_or_unknown_action'),
])
def test_production_decoder_errors_retained_with_usage(tmp_path,code,category):
    _,c=context();supplied=menu_context(c)
    def reject(raw,ctx,sup):raise ValueError(code)
    with endpoint(synthetic_envelope(json.dumps(response(supplied)))) as (url,requests):
        client=configured_client(Settings(api_key='test',model='test',base_url=url))
        row=RecordedAttempt(tmp_path,1).run(client,c,supplied,synthetic_meta(),decoder=reject)
    assert row['error_class']==category and row['usage_available'] and not row['accepted']
    assert row['content_available'] and len(requests)==1


def test_sent_unknown_never_resends_or_releases(tmp_path):
    _,c=context();supplied=menu_context(c);client=configured_client(Settings(api_key='test',model='test'))
    from avalon.eval.simulation import digest
    budget=DurableBudget(tmp_path,1,3)
    uid,_=budget.begin(client.request_payload(supplied),{**synthetic_meta(),'payload_hash':digest(client.request_payload(supplied))})
    atomic_json(tmp_path/'attempt_states'/f'{uid}.json',{'status':'sent'})
    with patch.object(client,'complete',side_effect=AssertionError('must never resend')):
        with pytest.raises(RuntimeError,match='no_automatic_resend'):
            RecordedAttempt(tmp_path,1).run(client,c,supplied,synthetic_meta())
    with pytest.raises(RuntimeError):RecordedAttempt(tmp_path,1).release_confirmed_unsent(uid)
    assert DurableBudget(tmp_path,1,3).unknown==1


def test_validated_and_committed_recovery_uses_existing_session_once(tmp_path):
    from avalon.eval.v2.v21_runtime import Session
    g,c=context();supplied=menu_context(c);identity={'game_id':'synthetic','configuration':'frozen'}
    with endpoint(synthetic_envelope(json.dumps(response(supplied)))) as (url,requests):
        transport=configured_client(Settings(api_key='test',model='test',base_url=url))
        store=RecordedAttempt(tmp_path/'evidence',1)
        class Client:
            def complete(self,ctx):
                row=store.run(transport,ctx,menu_context(ctx),synthetic_meta())
                assert row['accepted'];return row['validated_action']
        first=Session(tmp_path/'session/state.json',identity)
        action=first.choose(c,Client()) # crash after accepted, before commit
        second=Session(tmp_path/'session/state.json',identity)
        assert second.choose(c,Client())==action
        assert second.submit(g,'stable-commit','propose',(g.leader,action['team']),{})
        before=Session.game_hash(g)
        assert not second.submit(g,'stable-commit','propose',(g.leader,action['team']),{})
        assert before==Session.game_hash(g)
        g2,c2=context();third=Session(tmp_path/'session/state.json',identity)
        assert third.choose(c2,Client())==action
        third.submit(g2,'stable-commit','propose',(g2.leader,action['team']),{})
        assert Session.game_hash(g2)==before and len(requests)==1


@pytest.fixture
def synthetic_replay_source(tmp_path):
    from avalon.eval.simulation import play_game
    from avalon.eval.v2.adapters import make_version
    from avalon.eval.v2.v232_channel import sha256
    from avalon.eval.joint_belief import ROOT
    row,_,record=play_game(117,'joint_v2',belief_factory=make_version,all_seats=True,capture_decisions=True)
    assert row['status']=='completed'
    record['scope']='generation';record['variant']='joint_v2'
    source=tmp_path/'synthetic.jsonl';source.write_text(json.dumps(record)+'\n')
    atomic_json(tmp_path/'config.json',{'run_id':'synthetic-fixture'})
    names=('avalon/engine.py','avalon/evidence.py','avalon/cognition.py','avalon/joint_beliefs.py',
           'avalon/mission_likelihood.py','avalon/eval/v2/adapters.py','avalon/eval/v2/v21_contract.py')
    atomic_json(tmp_path/'source_manifest.json',{'hashes':{n:sha256(ROOT/n) for n in names}})
    return 'synthetic-fixture','synthetic_fixture',record,source,tmp_path


def test_source_replay_checks_original_baseline_and_probe_invariance(synthetic_replay_source):
    from avalon.eval.v2.v232_replay_verification import verify_record
    result=verify_record(synthetic_replay_source)
    assert result['verification_status']=='BASELINE_VERIFIED',result['exclusion_reason']
    assert result['checks']['probe_checks']>0 and all(c['verified'] for c in result['cutoffs'])


def test_source_replay_reports_first_event_mismatch(synthetic_replay_source):
    from avalon.eval.v2.v232_replay_verification import verify_record
    task=list(deepcopy(synthetic_replay_source));task[2]['events'][0]['round']=999
    result=verify_record(task)
    assert result['verification_status']=='UNVERIFIABLE'
    assert result['first_mismatch_event_id']==task[2]['events'][0]['record_id']
    assert result['expected_hash']!=result['actual_hash'] and not result['cutoffs']


def test_source_missing_config_does_not_infer_from_other_run(synthetic_replay_source):
    from avalon.eval.v2.v232_replay_verification import verify_record
    synthetic_replay_source[-1].joinpath('config.json').unlink()
    result=verify_record(synthetic_replay_source)
    assert result['mismatch_kind']=='configuration_missing' and not result['cutoffs']


def test_unverified_snapshot_blocks_smoke_before_settings_or_http(tmp_path):
    from avalon.eval.v2 import v232_r2 as repair
    from avalon.eval.v2.v232_channel import sha256
    atomic_json(tmp_path/'p0_config.json',{'live_authorized_after_contract_freeze':True,
         'tested_code_hashes':{str(p.relative_to(repair.ROOT)):sha256(p) for p in repair._code_paths()}})
    atomic_json(tmp_path/'p0_gates.json',{'contract_smoke':'READY_OFFLINE','repository_regression':'PASS','accounting_recovery':'PASS'})
    atomic_json(tmp_path/'eligible_snapshot_manifest.json',{'snapshots':[{'eligible':1,'source_verified':0,'decoder_verified':False}]})
    with patch.object(Settings,'load',side_effect=AssertionError('must not read credentials')):
        with pytest.raises(RuntimeError,match='no_verified_snapshot'):repair.smoke(tmp_path)
