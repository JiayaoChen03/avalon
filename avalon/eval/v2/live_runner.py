"""Opt-in DeepSeek action experiment; frozen replay and scenario reuse, not new held-out data."""
import argparse
from collections import Counter,defaultdict
from concurrent.futures import ProcessPoolExecutor,ThreadPoolExecutor,as_completed
from copy import deepcopy
from dataclasses import asdict,replace
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time

from avalon.chronicle import PUBLIC_KINDS,context_record
from avalon.engine import EVIL_ROLES
from avalon.llm import Settings,ChatClient
from avalon.eval.joint_belief import ROOT,CSVOutput,write_json,git_info,snapshot_sources
from avalon.eval.simulation import canonical,digest,play_game,validate_replay,policy_context
from .adapters import make_version,configuration,VARIANTS
from .experiments import scenario_players,replay_to_files
from .population import PROFILES
from .runner import tests,merge_replay_files,package
from . import reporting as rp
from .additional_analyses import direct_ablation_contrasts
from .live import BudgetLedger,BudgetStop,Journal,LiveClient,HybridClient,PRICING,model_context

REFERENCE=ROOT/'results/joint_belief_v2/20260917-v2-numerical-fix'


def freeze_plan(reference):
    old=json.loads((reference/'dataset_manifest.json').read_text())
    smoke=[]
    for s in old['active']:
        if s['phase']=='smoke' and s['profile'] not in {x['profile'] for x in smoke}:smoke.append(s)
    main=[s for s in old['active'] if s['phase']=='main' and s['scope']=='single_seat'][:40]
    whole=[s for s in old['active'] if s['phase']=='main' and s['scope']=='whole_table'][:4]
    return {'reference':str(reference),'selected_active':smoke+main+whole,'planned_pairs':len(smoke+main+whole),
            'planned_main_single_pairs':40,'planned_main_whole_pairs':4,'planned_smoke_pairs':6,
            'selection':'First manifest order; no result-dependent selection. Ten focal scenarios per role, both heldout profiles.',
            'scenario_reuse':'Previously analyzed scenarios; not newly unseen test data. No pooling with offline run.',
            'policy_parameters':old['policy_parameters'],'bootstrap_resamples':2000,
            'snapshot_selection':'One first post-success GOOD team decision (else vote) per heldout game; all heldout assassination opportunities',
            'repeat_selection':'First 10 fixed snapshots, joint_v1 requested a second time',
            'replays_sha256':hashlib.sha256((reference/'replays.jsonl').read_bytes()).hexdigest()}


def select_snapshots(records):
    out=[]
    for r in records:
        if r['split']!='held_out_test':continue
        success=[e['seq'] for e in r['events'] if e['kind']=='MISSION' and e['success']]
        options=[d for d in r['decisions'] if d['view']['role']=='GOOD' and d['phase'] in {'team','vote'}
                 and any(seq<=d['after_seq'] for seq in success)]
        teams=[d for d in options if d['phase']=='team']
        chosen=([teams[0] if teams else options[0]] if options else [])
        chosen += [d for d in r['decisions'] if d['phase']=='assassination']
        for d in chosen:
            out.append({'snapshot_id':f"{r['game_id']}:{d['observer_id']}:{d['after_seq']}:{d['phase']}",
                        'record':r,'decision':d})
    return out


def snapshot_inputs(item):
    record,d=item['record'],item['decision']
    game,truth=validate_replay(record); pid=d['observer_id']; initial=game.view(pid)
    observers={v:make_version(v,deepcopy(initial)) for v in ('joint_v1','joint_v2')}
    events=[context_record(e) for e in record['events'] if e['kind'] in PUBLIC_KINDS and e['seq']<=d['after_seq']]
    for event in events:
        for b in observers.values():b.observe(deepcopy(event))
    return {v:policy_context(deepcopy(d['view']),b) for v,b in observers.items()},truth,observers


def fixed_job(item,settings,budget,journal,repeat=False):
    inputs,truth,observers=snapshot_inputs(item)
    order=['joint_v1'] if repeat else (['joint_v1','joint_v2'] if item['record']['seed']%2==0 else ['joint_v2','joint_v1'])
    out=[]
    for variant in order:
        context=inputs[variant];phase=context['view']['phase']
        meta={'stage':'fixed_repeat' if repeat else 'fixed_snapshot','snapshot_id':item['snapshot_id'],
              'game_id':item['record']['game_id'],'variant':variant}
        client=LiveClient(settings,budget,journal,meta)
        row={**meta,'profile':item['record']['profile'],'phase':phase,'observer_role':context['view']['role'],
             'legal_view_hash':digest(context['view']),'model_context_hash':digest(model_context(context)),
             'marginals':context['marginals'],'joint_state':observers[variant].snapshot(),
             'reference_action':item['decision']['action'],'status':'completed','error':None}
        try:
            action=client.complete(context);row['action']=action
            row['same_as_original_controlled_action']=action==item['decision']['action']
            if phase=='team':
                row['clean_team']=int(all(truth[p] not in EVIL_ROLES for p in action['team']))
                row['chosen_joint_risk']=observers[variant].team_risk(action['team'])
            if phase=='assassination':row['merlin_hit']=int(truth[action['target']]=='MERLIN')
            if phase=='vote':
                row['approve']=int(action['approve']);row['proposed_team_clean']=int(all(truth[p] not in EVIL_ROLES for p in context['view']['team']))
        except (RuntimeError,ValueError,TypeError,KeyError) as e:
            row.update(status='budget_stopped' if isinstance(e,BudgetStop) else 'failed',error=type(e).__name__+': '+str(e))
        out.append(row)
    return out


def live_scenario(spec,variant,settings,budget,journal):
    meta={'stage':'active','scenario_id':spec['scenario_id'],'variant':variant}
    live=LiveClient(settings,budget,journal,meta)
    hybrid=HybridClient(spec['seed'],spec['profile'],spec['focal'],spec['scope']=='whole_table',live)
    row,trace,record=play_game(spec['seed'],variant,phase=spec['phase'],model=settings.model,temperature=settings.temperature,
        player_setup=scenario_players(spec),focal=spec['focal'],all_seats=spec['scope']=='whole_table',
        belief_factory=make_version,client_factory=lambda _:hybrid,capture_decisions=True)
    safe={k:v for k,v in asdict(settings).items() if k!='api_key'}
    for data in (row,record):data.update({k:spec[k] for k in ('scenario_id','profile','split','scope')})
    row['pair_id']=spec['scenario_id']
    row['pair_signature']=digest({'game_signature':row['pair_signature'],'spec':spec,'model_settings':safe,
                                 'prompt_hash':digest(live.transport._system_prompts[False]),'opponents':PROFILES[spec['profile']]})
    row.update(external_model_calls=live.external_calls,model_tokens=live.usage.get('total_tokens'),
               model_cost=live.estimated_cost if not live.usage_unknown else None,
               model_cost_currency='CNY_estimate',mock_calls=hybrid.population.calls,forced_legal_actions=live.forced,
               model_retries=live.retries,usage_missing_calls=live.usage_unknown)
    row['failure_class']='none'
    if row['status']!='completed':
        row['failure_class']='budget' if 'BudgetStop' in row['error'] else 'model' if 'LLMError' in row['error'] else 'engine'
        if row['failure_class']=='budget':
            row['status']='budget_stopped';row['invalid_actions']=0
    record['status'],record['error']=row['status'],row['error']
    truth={p['id']:p['role'] for p in record['players']}
    for label,events in [('proposed',[e for e in record['events'] if e['kind'] in {'TEAM','TEAM_REVISE'}]),
                         ('approved',[e for e in record['events'] if e['kind']=='TEAM_VOTE' and e['approved']]),
                         ('executed',[e for e in record['events'] if e['kind']=='MISSION'])]:
        row[label+'_clean_teams']=sum(all(truth[p] not in EVIL_ROLES for p in e['team']) for e in events)
        row[label+'_team_count']=len(events)
    return row,trace,record


def live_pair(spec,settings,budget,journal):
    order=['joint_v1','joint_v2'] if spec['seed']%2==0 else ['joint_v2','joint_v1']
    results={v:live_scenario(spec,v,settings,budget,journal) for v in order}
    if len({r[0]['pair_signature'] for r in results.values()})!=1:raise ValueError('Unequal pair configuration')
    return [results[v] for v in ('joint_v1','joint_v2')]


def passive_report(output):
    ends,episodes,count=rp.endpoints_and_episodes(output/'belief_trace.csv')
    roles=rp.group_comparisons(ends,resamples=2000)
    profiles=rp.group_comparisons(ends,True,2000)
    ablations=direct_ablation_contrasts(ends,rp.METRICS,rp.LOWER,rp.HIGHER,2000)
    rp.write_csv(output/'role_metrics.csv',roles);rp.write_csv(output/'opponent_profile_metrics.csv',profiles)
    rp.write_csv(output/'ablation_metrics.csv',ablations);rp.write_csv(output/'calibration.csv',rp.calibration_rows(ends))
    rp.write_csv(output/'pathology_episodes.csv',episodes)
    reference=output/'offline_reference'
    if not reference.exists():reference=Path(json.loads((output/'config.json').read_text())['reference'])
    prior=json.loads((reference/'summary.json').read_text())['primary']
    primary=[r for r in roles if r['split']=='held_out_test' and r['observer_role']=='GOOD' and r['variant']=='joint_v2'
             and r['metric'] in {'unknown_brier_score','unknown_log_loss'}]
    return {'trace_rows':count,'primary':primary,'primary_byte_values_equal_reference':primary==prior}


def fixed_summary(rows):
    grouped=defaultdict(dict);repeats=[]
    for r in rows:
        if r['stage']=='fixed_repeat':repeats.append(r)
        else:grouped[r['snapshot_id']][r['variant']]=r
    out={}
    for phase in ('team','vote','assassination'):
        pairs=[p for p in grouped.values() if len(p)==2 and all(r['status']=='completed' and r['phase']==phase for r in p.values())]
        out[phase]={'paired_snapshots':len(pairs),'action_changed':sum(p['joint_v1']['action']!=p['joint_v2']['action'] for p in pairs),
                    'legal_view_hashes_identical':all(p['joint_v1']['legal_view_hash']==p['joint_v2']['legal_view_hash'] for p in pairs),
                    'model_contexts_changed':sum(p['joint_v1']['model_context_hash']!=p['joint_v2']['model_context_hash'] for p in pairs)}
        for metric in ('clean_team','merlin_hit','approve'):
            vals={v:[p[v][metric] for p in pairs if metric in p[v]] for v in ('joint_v1','joint_v2')}
            if any(vals.values()):out[phase][metric]={v:{'numerator':sum(xs),'denominator':len(xs),'rate':sum(xs)/len(xs) if xs else None} for v,xs in vals.items()}
    valid=[r for r in repeats if r['status']=='completed' and grouped.get(r['snapshot_id'],{}).get('joint_v1',{}).get('status')=='completed']
    out['identical_input_repeat']={'denominator':len(valid),'action_changed':sum(r['action']!=grouped[r['snapshot_id']]['joint_v1']['action'] for r in valid),
                                 'context_hash_equal':all(r['model_context_hash']==grouped[r['snapshot_id']]['joint_v1']['model_context_hash'] for r in valid)}
    out['failures']=sum(r['status']!='completed' for r in rows)
    return out


def aggregate(output,passive=None):
    config=json.loads((output/'config.json').read_text());reference=output/'offline_reference'
    if not reference.exists():reference=Path(config['reference'])
    games=list(rp.read_csv(output/'games.csv')) if (output/'games.csv').exists() else []
    pairs=rp.paired_outcomes(games);rp.write_csv(output/'paired_outcomes.csv',pairs)
    fixed=[json.loads(l) for l in (output/'fixed_snapshot_results.jsonl').read_text().splitlines()] if (output/'fixed_snapshot_results.jsonl').exists() else []
    offline=[g for g in rp.read_csv(reference/'games.csv') if g.get('pair_id') in {r['pair_id'] for r in games}]
    calls=[json.loads(l) for l in (output/'llm_calls.jsonl').read_text().splitlines()] if (output/'llm_calls.jsonl').exists() else []
    active=rp.active_summary(games,2000)
    reference_active=rp.active_summary(offline,2000)
    for source in (output/'replays.jsonl',output/'active_replays.jsonl'):
        if source.exists():rp.write_csv(output/('behavior_coverage.csv' if source.name=='replays.jsonl' else 'active_behavior_coverage.csv'),rp.behavior_coverage(source))
    # report-only must recompute the passive scores from raw traces as well.
    passive=passive or passive_report(output)
    usage=Counter(); cost=charged=0.;unknown=0
    for call in calls:
        usage.update(call['transport'].get('usage',{}));cost+=call['estimated_cny'] or 0
        charged+=call['budget_charged_cny'];unknown+=call['usage_status']=='unavailable'
    plan=json.loads((output/'dataset_manifest.json').read_text())
    summary={'status':config['status'],'tests':config['tests'],'passive':passive,'active':active,
             'offline_same_selected_scenarios':reference_active,'fixed_snapshots':fixed_summary(fixed),
             'counts':{'planned_pairs':plan['planned_pairs'],'attempted_pairs':len(pairs),'complete_pairs':sum(r['available'] for r in pairs),
                       'games':len(games),'failed_games':sum(r['status']!='completed' for r in games),
                       'live_http_attempts':len(calls),'accepted_responses':sum(r['accepted'] for r in calls),
                       'retry_attempts':sum(r['retry_index']>0 for r in calls),'fallbacks':sum(r['fallback'] for r in calls)},
             'cost':{'budget_cny':config['budget_cny'],'provider_usage':dict(usage),'estimated_cny':cost,
                     'conservative_charged_cny':charged,'unknown_usage_attempts':unknown,'invoice_cny':None},
             'returned_models':dict(Counter(r['transport'].get('model','unavailable') for r in calls)),
             'system_fingerprints':dict(Counter(r['transport'].get('system_fingerprint','unavailable') for r in calls)),
             'language_parser':{'status':'not_run','reason':'independent action-only dimension; no language factors committed'},
             'limits':['Previously analyzed scenario reuse; no newly unseen evaluation claim.',
                       'Active actions may diverge; shared seed does not force identical evidence or server outputs.',
                       'Same prompts and provider settings across v1/v2; summaries differ only when beliefs differ.',
                       'Whole-table scope uses all five LLM decision policies and is separate from single-seat scope.',
                       'Offline-to-live changes both policy and trajectories; that difference is not a belief treatment effect.',
                       'Alias cannot pin immutable backend weights. Server metadata and repeated inputs are recorded.',
                       'Costs are measured tokens times published rates, not verified account invoices.',
                       'Validation/transport failures are retained; conditional completed-pair scores may be selected.']}
    write_json(output/'summary.json',summary)
    from .live_analysis import analyze
    analyze(output)
    write_report(output,summary,config)
    (output/'plots').mkdir(exist_ok=True)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    scopes=[k for k in active if k.endswith('_main')]
    if scopes:
        fig,axes=plt.subplots(1,len(scopes),figsize=(5*len(scopes),4),squeeze=False)
        for ax,scope in zip(axes[0],scopes):
            for x,v in enumerate(('joint_v1','joint_v2')):
                for pos,value,color,label in ((x-.16,reference_active[scope]['win_rate'][v],'#68778d','controlled'),
                                               (x+.16,active[scope]['win_rate'][v],'#137e91','DeepSeek')):
                    if value is not None:ax.bar(pos,value,.3,color=color,label=label if x==0 else None)
                    else:ax.text(pos,.03,'N/A',ha='center',rotation=90)
            cn=reference_active[scope]['win_rate']['joint_v1_denominator']
            ln=active[scope]['win_rate']['joint_v1_denominator']
            ax.set_xticks([0,1],['v1','v2']);ax.set_ylim(0,1);ax.set_ylabel('Win rate')
            ax.set_title(f'{scope}\ncompleted pairs: controlled {cn:g}, DeepSeek {ln:g}');ax.legend()
        fig.tight_layout();fig.savefig(output/'plots/active_win_rates.png',dpi=150);plt.close(fig)
    for r in pairs:
        if r['available'] and r['win_difference']!=r['joint_v2_win']-r['joint_v1_win']:raise ValueError('Pair export mismatch')
    write_json(output/'export_validation.json',{'paired_csv_matches_summary':True,'reaggregation_source':'raw CSV/JSONL only',
                                               'summary_sha256':hashlib.sha256((output/'summary.json').read_bytes()).hexdigest()})
    return summary


def write_report(output,s,c):
    f=rp.format_number
    lines=['# DeepSeek Joint Belief v2 本地真实调用对照','',f"运行状态：{s['status']}。模型请求名 `{c['settings']['model']}`；返回型号 {s['returned_models']}。",
        f"本轮费用上限 ¥{c['budget_cny']}；实际 {s['counts']['live_http_attempts']} 次 HTTP 尝试，用量 {s['cost']['provider_usage']}；按公布单价估算 ¥{s['cost']['estimated_cny']:.6f}，非账单金额。未知用量请求 {s['cost']['unknown_usage_attempts']}。",'',
        '## 范围与可归因性','',
        '沿用上一轮冻结回放、场景、规则、资源与评分器。先运行全部本地测试、120 局 × 6 版本 × 5 观察者的被动回放，再运行六组真实模型 smoke。主真实模型计划为 40 组单席位（每角色 10 组）与 4 组全桌；属于小规模后续实验，不替代完整 200 组离线结论。',
        '系统提示词原文沿用，模型配置固定；用户输入包含合法视图、代码计算的边际及联合队伍风险。所有概率由冻结引擎更新。语言解释单独标记 not_run，生成文字不产生额外软证据。主动轨迹允许分叉，服务端也可能非确定。',
        '全桌真实模型组采用五席同一 LLM 策略；原离线全桌仍是一个受控 focal 与四个群体策略，因此只作描述对照，不将两种全桌策略的差归因于 belief。',
        '', '## 工程检查','',f"专项：{c['tests'].get('unit')}；全仓：{c['tests'].get('regression')}。",
        f"完成配对 {s['counts']['complete_pairs']}/{s['counts']['planned_pairs']}；失败游戏 {s['counts']['failed_games']}；重试请求 {s['counts']['retry_attempts']}；脚本降级 {s['counts']['fallbacks']}。",
        f"冻结被动主要指标与上一轮完全一致：{s['passive']['primary_byte_values_equal_reference']}。这验证重放一致性，不代表语言理解改善。",'',
        '## 主动胜率（按场景配对 bootstrap，2,000 次）','',
        '|组别|策略|v1 分子/分母|v2 分子/分母|v2−v1|95% CI|结论|','|---|---|---|---|---|---|---|']
    for k,metrics in s['active'].items():
        for policy,data in [('DeepSeek',metrics),('原受控策略，同场景',s['offline_same_selected_scenarios'][k])]:
            m=data['win_rate'];ci=m['delta_ci95']
            lines.append(f"|{k}|{policy}|{f(m['joint_v1_numerator'])}/{f(m['joint_v1_denominator'])}|{f(m['joint_v2_numerator'])}/{f(m['joint_v2_denominator'])}|{f(m['absolute_delta'])}|{ci}|{m['interpretation']}|")
    lines += ['', '分角色胜率、队伍提出/获批/执行质量及条件刺杀命中率详见 summary.json。条件刺杀率受机会集合变化影响，优先结合固定刺杀快照。区间包含零均标记不确定，工程通过不能当作效果成立。',
        '', '## 固定合法快照与服务端重复性','', '```json',json.dumps(s['fixed_snapshots'],ensure_ascii=False,indent=2),'```','',
        '刺杀遵循生产策略：优先最大 Merlin 概率，仅用模型排序打破并列；不因置信度改变而强迫随机。固定快照动作差异还需结合相同输入重复请求的波动，不能全部归于 belief。',
        '', '## 限制与未完成项','', *['- '+l for l in s['limits']],
        '- 完整 200 组单席位/20 组全桌真实模型大样本未运行；当前真实模型样本是事前固定子集。',
        '- 自然语言证据解析独立实验 not_run；没有把结构化 SOCIAL 因子收益写成语言理解能力。',
        '', '## 重算与运行','', '```bash',
        '.venv/bin/python -m avalon.eval.v2.live_runner --live --budget-cny 50 --max-calls 6000 --workers 8 --run-id deepseek-next',
        f'.venv/bin/python -m avalon.eval.v2.live_runner --report-only --run-dir {output}', '```','',
        '费用及别名依据：[DeepSeek 官方价格](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)。所有输入、响应、重试与实际 usage 保存在 llm_calls.jsonl；无凭据及 reasoning_content。完整 joint 状态在 hypothesis_trace.jsonl.gz，固定快照还存各自 joint_state。']
    (output/'report.md').write_text('\n'.join(lines)+'\n')


def execute(args):
    if args.report_only:
        output=args.run_dir.resolve();old=(output/'summary.json').read_bytes();aggregate(output)
        same=old==(output/'summary.json').read_bytes()
        validation=json.loads((output/'export_validation.json').read_text());validation['summary_byte_identical_after_reaggregation']=same
        write_json(output/'export_validation.json',validation)
        if not same:raise ValueError('Raw reaggregation changed summary')
        package(output);print('Report reproduced',output,flush=True);return
    if not args.live:raise ValueError('Paid calls require --live and --budget-cny')
    if args.budget_cny is None or args.budget_cny>50:raise ValueError('This authorized run requires 0 < budget-cny <= 50')
    settings=replace(Settings.load(),temperature=0.)
    if not settings.ready or settings.base_url.rstrip('/')!='https://api.deepseek.com':raise ValueError('Expected configured official DeepSeek endpoint')
    if settings.model not in {'deepseek-v4-flash','deepseek-flash'}:raise ValueError('Pricing guard supports configured Flash model only')
    if settings.thinking!='disabled':raise ValueError('This frozen action experiment requires configured thinking disabled')
    reference=args.reference.resolve();plan=freeze_plan(reference)
    records=[json.loads(l) for l in (reference/'replays.jsonl').read_text().splitlines()]
    selected=select_snapshots(records)
    if args.smoke_only:
        plan['selected_active']=[s for s in plan['selected_active'] if s['phase']=='smoke']
        plan.update(planned_pairs=6,planned_main_single_pairs=0,planned_main_whole_pairs=0)
        selected=[]
    plan['fixed_snapshots']=[{'snapshot_id':x['snapshot_id'],'source_game':x['record']['game_id'],
                              'legal_view_sha256':digest(x['decision']['view'])} for x in selected]
    output=(ROOT/'results/joint_belief_v2'/args.run_id).resolve();output.mkdir(exist_ok=False,parents=True)
    started=time.perf_counter();ledger=BudgetLedger(args.budget_cny,args.max_calls);journal=Journal(output/'llm_calls.jsonl')
    safe={k:v for k,v in asdict(settings).items() if k!='api_key'}
    config={'status':'running','started_utc':datetime.now(timezone.utc).isoformat(),'reference':str(reference),'command':sys.argv,
            'settings':safe,'budget_cny':args.budget_cny,'max_calls':args.max_calls,'workers':args.workers,
            'pricing':PRICING,'tests':{},'variants':{v:asdict(configuration(v)) for v in VARIANTS},
            'policy':'existing production plan/envelope validation and action semantics; fresh plan for each non-forced decision',
            'language_parser':'not_run','smoke_only':args.smoke_only,'system_sha256':digest(ChatClient(settings)._system_prompts[False])}
    write_json(output/'config.json',config);write_json(output/'dataset_manifest.json',plan)
    hashes=snapshot_sources(output)
    prompt=ROOT/'prompts/corrupted_castle_system.md';target=output/'source/prompts'/prompt.name;target.parent.mkdir(exist_ok=True)
    shutil.copy2(prompt,target);hashes[str(prompt.relative_to(ROOT))]=hashlib.sha256(prompt.read_bytes()).hexdigest()
    write_json(output/'source_manifest.json',{'git':git_info(),'sha256':hashes,'reference_source_manifest':str(reference/'source_manifest.json')})
    shutil.copy2(ROOT/'results/joint_belief_v2/20260917-deepseek-prechange/prechange_audit.md',output/'prechange_audit.md')
    shutil.copy2(reference/'replays.jsonl',output/'replays.jsonl')
    (output/'offline_reference').mkdir()
    for name in ('games.csv','summary.json','config.json','dataset_manifest.json','source_manifest.json'):
        shutil.copy2(reference/name,output/'offline_reference'/name)
    games=CSVOutput(output/'games.csv',['game_id','variant']);activefile=(output/'active_replays.jsonl').open('w')
    fixedfile=(output/'fixed_snapshot_results.jsonl').open('w')
    try:
        config['tests']['unit']=tests(output,'unit_tests',['tests/test_joint_beliefs.py','tests/test_cognition.py','tests/eval','tests/test_llm.py'])
        if config['tests']['unit']['exit_code']:raise RuntimeError('Unit gate failed')
        if args.reuse_local_gates_from:
            gate=args.reuse_local_gates_from.resolve()
            prior_config=json.loads((gate/'config.json').read_text())
            prior_sources=json.loads((gate/'source_manifest.json').read_text())['sha256']
            allowed={'avalon/llm.py','avalon/eval/v2/live.py','avalon/eval/v2/live_runner.py','avalon/eval/v2/live_analysis.py'}
            mismatches=[name for name,h in prior_sources.items() if name.startswith('avalon/') and name not in allowed
                        and hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=h]
            if mismatches:raise ValueError('Reused inference/rules gate source changed: '+str(mismatches))
            if prior_config['tests']['regression']['exit_code']:raise ValueError('Prior full regression gate did not pass')
            if hashlib.sha256((gate/'replays.jsonl').read_bytes()).hexdigest()!=plan['replays_sha256']:
                raise ValueError('Reused replay corpus changed')
            config['tests']['regression']={**prior_config['tests']['regression'],'reused_from':str(gate),
                'reason':'Full repository gate already passed this session; unchanged rule/inference sources. Updated live adapter covered by newly rerun unit gate.'}
            shutil.copy2(gate/'regression_tests.xml',output/'regression_tests.xml')
            shutil.copy2(gate/'regression_tests.log',output/'regression_tests.log')
            for name in ('belief_trace.csv','mission_update_audit.csv','hypothesis_trace.jsonl.gz','replay_audit.json'):
                shutil.copy2(gate/name,output/name)
            config['passive_reused_from']=str(gate)
            print('Reused this session\'s verified full regression and passive exports; inference/rules hashes match',flush=True)
        else:
            config['tests']['regression']=tests(output,'regression_tests',['tests'])
            if config['tests']['regression']['exit_code']:raise RuntimeError('Regression gate failed')
            print(f'Passive rerun: {len(records)} frozen games, no API needed',flush=True)
            with ProcessPoolExecutor(max_workers=min(4,args.workers)) as pool:
                folders=[]
                for folder in pool.map(replay_to_files,[(r,str(output/'_work'/str(i))) for i,r in enumerate(records)]):
                    folders.append(folder)
                    if len(folders)%20==0:print(f'Passive {len(folders)}/{len(records)}',flush=True)
            merge_replay_files(folders,output);shutil.rmtree(output/'_work')
        write_json(output/'config.json',config)
        passive=passive_report(output);write_json(output/'passive_summary.json',passive)
        if not passive['primary_byte_values_equal_reference']:raise RuntimeError('Frozen passive scores changed')
        # Both variants of a scenario are always attempted and all failures retained.
        any_failures=0;smoke_failed=False
        for phase in ('smoke','main'):
            if phase=='main' and smoke_failed:
                config['main_gate']='closed: smoke had failed games; fixed-snapshot action diagnostics still run independently'
                continue
            specs=[s for s in plan['selected_active'] if s['phase']==phase]
            print(f'Live {phase}: {len(specs)} pairs',flush=True);failed=0
            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                futures=[pool.submit(live_pair,s,settings,ledger,journal) for s in specs]
                for i,future in enumerate(as_completed(futures)):
                    for row,trace,record in future.result():
                        games.append([row]);activefile.write(canonical(record)+'\n');activefile.flush()
                        failed+=row['status']!='completed'
                    write_json(output/'budget.json',ledger.snapshot())
                    print(f'{phase} {i+1}/{len(specs)} pairs; calls={ledger.calls}, conservative CNY={ledger.charged:.4f}, failed games={failed}',flush=True)
            any_failures+=failed
            if failed and phase=='smoke':
                smoke_failed=True
                print('Live smoke gate closed for active main; retaining failures and continuing fixed legal snapshot diagnostics',flush=True)
        print(f'Fixed snapshots: {len(selected)} paired plus 10 repeats',flush=True)
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            jobs=[pool.submit(fixed_job,x,settings,ledger,journal) for x in selected]
            jobs += [pool.submit(fixed_job,x,settings,ledger,journal,True) for x in selected[:10]]
            for i,future in enumerate(as_completed(jobs)):
                for row in future.result():
                    fixedfile.write(canonical(row)+'\n');any_failures+=row['status']!='completed'
                fixedfile.flush()
                if (i+1)%20==0:print(f'Snapshot jobs {i+1}/{len(jobs)}',flush=True)
        config['status']='partial' if any_failures else 'completed'
    except Exception as e:
        config.update(status='partial',error=type(e).__name__+': '+str(e));print(config['error'],flush=True)
    finally:
        games.close();activefile.close();fixedfile.close()
        config['wall_seconds']=time.perf_counter()-started
        write_json(output/'config.json',config);write_json(output/'budget.json',ledger.snapshot())
    if (output/'passive_summary.json').exists():aggregate(output)
    package(output);print('Exported',output,flush=True)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--live',action='store_true');p.add_argument('--budget-cny',type=float);p.add_argument('--max-calls',type=int,default=6000)
    p.add_argument('--workers',type=int,default=8);p.add_argument('--reference',type=Path,default=REFERENCE)
    p.add_argument('--run-id',default=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-deepseek')
    p.add_argument('--report-only',action='store_true');p.add_argument('--run-dir',type=Path)
    p.add_argument('--smoke-only',action='store_true',help='Only six predeclared live smoke pairs after local gates and passive replay')
    p.add_argument('--reuse-local-gates-from',type=Path,help='Reuse this session\'s passed full regression and passive exports only after checking unchanged inference/rule hashes; rerun live unit tests')
    args=p.parse_args(argv)
    if args.workers<1 or args.workers>16:raise ValueError('workers must be 1..16')
    if not args.run_id.replace('-','').replace('_','').isalnum():raise ValueError('Invalid run-id')
    execute(args)

if __name__=='__main__':main()
