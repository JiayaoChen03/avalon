"""Read-only accounting of each historical live run, never pool run outcomes."""
from collections import Counter, defaultdict
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from avalon.eval.simulation import digest, canonical
from avalon.eval.joint_belief import write_json
from .reporting import read_csv, write_csv
from .live import decode_action

REPORT_SHA = '80964dfd209032d68e5d14d5c0a6ab83779c877053fda8f1c1e96ff9fcaa4df5'


def load_lines(path):
    return [json.loads(l) for l in Path(path).read_text().splitlines() if l.strip()]


def failure_class(code, reason=None):
    if reason=='stale_state':return 'stale_state'
    if reason=='insufficient_resource':return 'resource_mismatch'
    if reason=='phase_mismatch':return 'phase_mismatch'
    if str(reason).startswith('illegal_'):return 'illegal_action'
    if code in {'timeout','connection_error'} or str(code).startswith('http_'):
        return 'transport_timeout_service'
    if code == 'empty_response': return 'empty_content'
    if code in {'invalid_response','truncated_response','response_too_large'}: return 'parse_or_incomplete_response'
    if code == 'BudgetStop' or 'budget' in str(code).lower(): return 'budget_limit'
    if code == 'cancelled': return 'active_cancellation'
    if code == 'stale_state': return 'stale_state'
    if code in {'checkpoint_mismatch','incompatible_resume'}: return 'scheduling_recovery'
    if reason in {'Invalid resource action','Invalid resource target'}: return 'resource_or_phase_constraint'
    if reason == 'Invalid council decision': return 'illegal_action'
    if reason and any(x in reason.lower() for x in ('evidence','history','social','disclosure')): return 'illegal_action'
    if code in {'invalid_plan','schema'}: return 'schema_or_contract'
    return 'unknown'


def legacy_decisions(calls):
    """Old journals lack IDs; sequential retry counters infer groups, explicitly."""
    groups=[]; current={}
    for index,row in enumerate(calls):
        key=(row['stage'],row.get('scenario_id',row.get('snapshot_id')),row['variant'])
        if row['retry_index']==0 or key not in current:
            group={'inferred_decision_id':f'legacy-{len(groups):05d}','attempts':[],'journal_indexes':[]}
            groups.append(group);current[key]=group
        group=current[key]
        if group['attempts'] and row['retry_index']!=group['attempts'][-1]['retry_index']+1:
            raise ValueError('Cannot unambiguously infer old retry group')
        group['attempts'].append(row);group['journal_indexes'].append(index)
    return groups


def supplied_context(supplied):
    v={**deepcopy(supplied['game']),'rules':supplied['rules'],
       'private_knowledge':supplied['private_knowledge'],'legal_options':supplied['legal_actions']}
    ev=v['recent_events']+v['focused_events']
    v['objective_state']={**v,'mission_score':{'good':v['successes'],'evil':v['failures']},
        'mission_results':v.get('missions',[]),'public_votes':[e for e in ev if e['kind'] in {'VOTE','TEAM_VOTE','EXILE_RESULT'}],
        'public_actions':ev,'public_commitments':[e for e in ev if e.get('committed') or e.get('strong')]}
    return {'view':v,**deepcopy(supplied['private_beliefs'])}


def reproduce_fixture(fixture):
    """Replay saved structured output; no transport and no game mutation."""
    supplied=fixture['context'];context=supplied_context(supplied)
    before=digest(context)
    try:
        decode_action(fixture['response'],context,supplied)
        outcome='accepted_by_current_v2_adapter'
    except Exception as exc:
        outcome=str(exc)
    assert digest(context)==before
    # Execute the archived adapter itself for the source-run reproduction.
    import importlib.util
    from avalon.eval.joint_belief import ROOT
    file=ROOT/'results/joint_belief_v2'/fixture['source_run']/'source/avalon/eval/v2/live.py'
    archived='missing'
    if file.exists():
        spec=importlib.util.spec_from_file_location('avalon.eval.v2._archived_adapter',file)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        try:module.decode_action(fixture['response'],context,supplied);archived='accepted'
        except Exception as exc:archived=str(exc)
    return {'fixture_id':fixture['fixture_id'],'recorded_reason':fixture['reason'],
            'archived_adapter_reproduction':archived,
            'current_v2_reproduction':outcome,'state_unchanged':True,
            'historical_reason_matches':archived==fixture['reason']}


def audit_run(source, output):
    source,output=Path(source).resolve(),Path(output);output.mkdir(parents=True,exist_ok=True)
    config=json.loads((source/'config.json').read_text())
    plan=json.loads((source/'dataset_manifest.json').read_text())
    calls=load_lines(source/'llm_calls.jsonl');groups=legacy_decisions(calls)
    games=list(read_csv(source/'games.csv'));fixed=load_lines(source/'fixed_snapshot_results.jsonl')
    by_pair=defaultdict(list)
    for g in games:by_pair[g['pair_id']].append(g)
    phases={}
    for phase in ('smoke','main'):
        specs=[s for s in plan['selected_active'] if s['phase']==phase]
        counts=Counter(planned_pairs=len(specs))
        for s in specs:
            rows=by_pair[s['scenario_id']];n=sum(r['status']=='completed' for r in rows)
            counts['started_pairs']+=bool(rows);counts['completed_pairs']+=n==2
            counts['one_side_completed_pairs']+=n==1;counts['no_side_completed_started_pairs']+=bool(rows) and n==0
            counts['unstarted_pairs']+=not rows;counts['started_games']+=len(rows)
            for r in rows:counts['games_'+r['status']]+=1
        phases[phase]=dict(counts)
    failure_rows=[];fixtures=[];fixture_types=set();retry_rows=[]
    for group in groups:
        attempts=group['attempts'];last=attempts[-1];recovered=bool(last['accepted'])
        if len(attempts)>1:
            retry_rows.append({'run_id':source.name,'decision_id':group['inferred_decision_id'],
                'stage':last['stage'],'scenario_id':last.get('scenario_id'), 'snapshot_id':last.get('snapshot_id'),
                'variant':last['variant'],'observer_id':last['observer_id'],'phase':last['phase'],
                'http_attempts':len(attempts),'retry_count':len(attempts)-1,'recovered':recovered,
                'journal_indexes':group['journal_indexes']})
        for i,r in zip(group['journal_indexes'],attempts):
            if r['accepted']:continue
            failure_rows.append({'run_id':source.name,'scenario_id':r.get('scenario_id'),
                'source_game_id':r.get('game_id'),'snapshot_id':r.get('snapshot_id'),
                'observer_id':r['observer_id'],'observer_role':r['context']['game']['role'],
                'variant':r['variant'],'policy_revision':config['policy'],'adapter_revision':source.name,
                'status':'recovered' if recovered else 'failed','phase':r['phase'],'round':r['round'],
                'decision_id':group['inferred_decision_id'],'retry_index':r['retry_index'],'journal_index':i,
                'error':r.get('error'),'reason':r.get('validation_reason'),
                'failure_class':failure_class(r.get('error'),r.get('validation_reason'))})
            key=(r.get('error'),r.get('validation_reason'))
            if key not in fixture_types and r.get('response'):
                fixture_types.add(key);fixtures.append({'fixture_id':f'{source.name}-{i}',
                    'source_run':source.name,'journal_index':i,'reason':r.get('validation_reason'),
                    'response':r['response'],'context':r['context']})
    failed_games=[g for g in games if g['status']!='completed']
    accounting={'source_run_id':source.name,'report_sha256':hashlib.sha256((source/'report.md').read_bytes()).hexdigest(),
        'matches_attachment':hashlib.sha256((source/'report.md').read_bytes()).hexdigest()==REPORT_SHA,
        'source_files':{n:hashlib.sha256((source/n).read_bytes()).hexdigest() for n in
            ('config.json','dataset_manifest.json','report.md','summary.json','llm_calls.jsonl','games.csv','paired_outcomes.csv','fixed_snapshot_results.jsonl')},
        'phases':phases,'http_attempts':len(calls),'inferred_logical_decisions':len(groups),
        'id_inference':'Retry_index resets to zero per stage/scenario-or-snapshot/variant stream; original unique IDs unavailable.',
        'retry_http_attempts':sum(r['retry_index']>0 for r in calls),'decisions_requiring_retry':len(retry_rows),
        'recovered_retry_decisions':sum(r['recovered'] for r in retry_rows),
        'failed_logical_decisions':sum(not g['attempts'][-1]['accepted'] for g in groups),
        'failed_game_count':len(failed_games),'failed_games':failed_games,
        'fixed_failed_decisions':[{'snapshot_id':r['snapshot_id'],'variant':r['variant'],'stage':r['stage'],'error':r['error']} for r in fixed if r['status']!='completed'],
        'stop_reason':('smoke_validation_failures_closed_active_main_gate; fixed jobs drained' if config.get('main_gate') else 'planned_jobs_drained_with_failed_game'),
        'stop_evidence':config.get('main_gate','completed pair files cover all planned active scenarios'),
        'budget_stop_count':sum('BudgetStop' in (g.get('error') or '') for g in games),
        'explicit_cancellation_count':0,'cancellation_observability':'No original cancellation/checkpoint records; not evidence that none was ever interrupted.',
        'inflight_at_report':'No executor tasks expected: saved source exits ThreadPoolExecutor before aggregate; original scheduler timeline unavailable.',
        'stack_traces':'missing','checkpoint':'missing','failure_types':dict(Counter(r['failure_class'] for r in failure_rows)),
        'pooling_with_other_runs':False}
    write_json(output/'run_accounting.json',accounting);write_csv(output/'failure_audit.csv',failure_rows)
    write_csv(output/'retry_decisions.csv',retry_rows)
    (output/'failure_fixtures.jsonl').write_text(''.join(canonical(f)+'\n' for f in fixtures))
    write_json(output/'fixture_replay.json',[reproduce_fixture(f) for f in fixtures])
    # One pair record per original snapshot; member order has no team semantics.
    grouped=defaultdict(dict)
    for r in fixed:
        if r['stage']=='fixed_snapshot':grouped[r['snapshot_id']][r['variant']]=r
    transitions=Counter();pairs=[]
    for sid,pair in grouped.items():
        if set(pair)!={'joint_v1','joint_v2'}:continue
        a,b=pair['joint_v1'],pair['joint_v2'];complete=all(r['status']=='completed' for r in (a,b))
        if a['phase']!='team':continue
        if complete:transitions[(a['clean_team'],b['clean_team'])]+=1
        pairs.append({'run_id':source.name,'scenario_id':sid,'source_game_id':a['game_id'],
            'observer_id':sid.split(':')[-3],'observer_role':a['observer_role'],
            'variant':'paired','policy_revision':config['policy'],'adapter_revision':source.name,
            'status':'completed' if complete else 'failed','v1_clean':a.get('clean_team'), 'v2_clean':b.get('clean_team'),
            'raw_changed':a.get('action')!=b.get('action'),
            'team_members_changed':set(a.get('action',{}).get('team',[]))!=set(b.get('action',{}).get('team',[])) if complete else None,
            'v1_action':a.get('action'),'v2_action':b.get('action'),
            'same_legal_view':a['legal_view_hash']==b['legal_view_hash'],
            'same_context':a['model_context_hash']==b['model_context_hash']})
    write_csv(output/'snapshot_pairs.csv',pairs)
    write_csv(output/'team_transition_table.csv',[{'run_id':source.name,'v1_clean':a,'v2_clean':b,'count':transitions[a,b],
        'denominator':sum(transitions.values()),'observer_role':'GOOD','status':'completed'} for a in (0,1) for b in (0,1)])
    return accounting
