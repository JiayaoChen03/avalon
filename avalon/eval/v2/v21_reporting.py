"""Raw journals/checkpoints/manifest -> v2.1 denominators and clustered metrics."""
from collections import Counter,defaultdict
import json
import math
from pathlib import Path
import numpy as np

from avalon.eval.simulation import canonical,digest
from .reporting import write_csv
from .v21_runtime import json_read,atomic_json
from .v21_audit import load_lines,failure_class


def ratio(n,d):return {'numerator':n,'denominator':d,'value':n/d if d else None,'status':'available' if d else 'unavailable'}


def independent_repeat(original,repeat):
    return bool(original and repeat and not original.get('client_cache_hit',True) and not repeat.get('client_cache_hit',True)
        and original.get('attempt_uid')!=repeat.get('attempt_uid') and original.get('attempt_uid') and repeat.get('attempt_uid')
        and original.get('transport',{}).get('request_sha256')
        and original['transport']['request_sha256']==repeat.get('transport',{}).get('request_sha256'))


def cluster_delta(records):
    """Records=(source cluster, reference, candidate); resample whole clusters."""
    groups=defaultdict(list)
    for cluster,a,b in records:
        if a is not None and b is not None:groups[cluster].append((a,b))
    keys=sorted(groups);n=sum(map(len,groups.values()))
    an=sum(a for rows in groups.values() for a,b in rows);bn=sum(b for rows in groups.values() for a,b in rows)
    out={'reference':ratio(an,n),'candidate':ratio(bn,n),'paired_clusters':len(keys),
        'delta':(bn-an)/n if n else None,'ci95':None,'status':'unavailable','equivalence_test':'not_run'}
    if len(keys)<2:out['status']='insufficient_sample' if keys else 'unavailable';return out
    values=np.array([(sum(a for a,b in groups[k]),sum(b for a,b in groups[k]),len(groups[k])) for k in keys],float)
    indexes=np.random.default_rng(21871).integers(0,len(keys),(2000,len(keys)))
    total=values[indexes].sum(axis=1);dist=(total[:,1]-total[:,0])/total[:,2]
    out['ci95']=np.quantile(dist,[.025,.975]).tolist()
    if np.allclose(values[:,1]-values[:,0],0,atol=0,rtol=0):out['status']='degenerate_resampling'
    elif len(keys)<8:out['status']='insufficient_sample'
    elif out['ci95'][0]>0:out['status']='increase_supported'
    elif out['ci95'][1]<0:out['status']='decrease_supported'
    else:out['status']='inconclusive'
    return out


def pairing(plan,jobs):
    lookup={(r['experiment'],r['scenario_id'],r['variant']):r for r in jobs}
    rows=[]
    for spec in plan['active']+plan['fixed']+plan['repeats']:
        arms=spec['order'];states=[lookup.get((spec['experiment'],spec['scenario_id'],arm),{}).get('status','not_run') for arm in arms]
        complete=sum(s=='completed' for s in states);started=sum(s!='not_run' for s in states)
        rows.append({'experiment':spec['experiment'],'scenario_id':spec['scenario_id'],'source_game_id':spec.get('source_game_id'),
            'observer_id':spec.get('observer_id',spec.get('focal')),'phase':spec['phase'],'scope':spec['scope'],
            'planned_order':arms,'arm_statuses':dict(zip(arms,states)),'started_arms':started,'completed_arms':complete,
            'status':'completed' if complete==len(arms) else 'not_run' if not started else 'partial',
            'fully_paired':len(arms)==2 and complete==2,'one_side_completed':len(arms)==2 and complete==1})
    return rows


def aggregate(out):
    out=Path(out);config=json_read(out/'config.json');plan=json_read(out/'dataset_manifest.json')
    jobs=[json_read(p) for p in sorted((out/'jobs').glob('*.json'))] if (out/'jobs').exists() else []
    if any(r['run_id']!=out.name for r in jobs):raise ValueError('Cannot mix runs')
    if any(r['adapter_revision']!=config['adapter_revision'] for r in jobs):raise ValueError('Cannot mix adapter revisions')
    calls=[]
    for p in sorted((out/'requests').glob('*.request.json')):
        request=json_read(p);response=p.with_name(p.name.replace('.request.json','.response.json'))
        if response.exists():calls.append(json_read(response))
        else:calls.append({**request,'accepted':False,'status':'outcome_unknown','error':'interrupted_request_unknown',
            'transport':{},'usage_status':'unavailable','estimated_cny':None,'budget_charged_cny':request['reservation']['cny'],
            'client_cache_hit':False})
    calls.sort(key=lambda r:(r['started_utc'],r['attempt_uid']))
    (out/'llm_calls.jsonl').write_text(''.join(canonical(c)+'\n' for c in calls))
    decision_rows=[]
    for path in sorted((out/'checkpoints').glob('*/state.json')):
        state=json_read(path)
        for d in state['decisions']:
            decision_rows.append({'run_id':out.name,**state['identity'].get('metadata',{}),**d['binding'],**d,'checkpoint':str(path)})
    (out/'decision_attempts.jsonl').write_text(''.join(canonical(c)+'\n' for c in decision_rows))
    pairs=pairing(plan,jobs)
    (out/'pair_manifest.jsonl').write_text(''.join(canonical({'run_id':out.name,**p})+'\n' for p in pairs))
    accounting={}
    for key in sorted({(p['experiment'],p['scope'],p['phase']) for p in pairs}):
        selected=[p for p in pairs if (p['experiment'],p['scope'],p['phase'])==key]
        states=Counter(s for p in selected for s in p['arm_statuses'].values())
        accounting['/'.join(key)]={'planned_scenarios':len(selected),'started_scenarios':sum(p['started_arms']>0 for p in selected),
            'fully_completed_scenarios':sum(p['status']=='completed' for p in selected),
            'complete_pairs':sum(p['fully_paired'] for p in selected),'one_side_completed_pairs':sum(p['one_side_completed'] for p in selected),
            'planned_arms':sum(len(p['planned_order']) for p in selected),'arm_states':dict(states)}
    atomic_json(out/'run_accounting.json',{'run_id':out.name,'counts_by_experiment_scope_phase':accounting,
        'stop_reason':config.get('stop_reason','not_started'),'report_inflight_jobs':sum(r['status']=='running' for r in jobs),
        'http_attempts':len(calls),'logical_decisions':len(decision_rows),
        'original_scenarios':len({p['source_game_id'] or p['scenario_id'] for p in pairs}),
        'missing_status_is_not_run':True,'historical_accounting':'historical_audit/*/run_accounting.json, separate runs'})
    by_decision=defaultdict(list)
    for c in calls:by_decision[c['decision_id']].append(c)
    first=sum(rows[0].get('accepted',False) for rows in by_decision.values())
    eventual=sum(any(r.get('accepted') for r in rows) for rows in by_decision.values())
    retries=sum(len(rows)>1 for rows in by_decision.values())
    latency=[c['elapsed_seconds'] for c in calls if 'elapsed_seconds' in c]
    unknown=sum(c['usage_status']=='unavailable' for c in calls)
    usage=Counter()
    for c in calls:usage.update(c['transport'].get('usage',{}))
    reliability={'http_attempts':len(calls),'logical_model_decisions':len(by_decision),
        'first_legal_response':ratio(first,len(by_decision)),'eventually_legal_response':ratio(eventual,len(by_decision)),
        'decision_retry_rate':ratio(retries,len(by_decision)),'retry_http_attempts':sum(c.get('retry_index',0)>0 for c in calls),
        'failure_categories':dict(Counter(c.get('failure_class',failure_class(c.get('error'),c.get('validation_reason'))) for c in calls if not c.get('accepted'))),
        'latency_seconds':{'median':float(np.median(latency)) if latency else None,'p95':float(np.quantile(latency,.95)) if latency else None,'n':len(latency)},
        'provider_usage':dict(usage),'estimated_cny_from_returned_usage':math.fsum(c['estimated_cny'] or 0 for c in calls),
        'conservative_charged_cny':math.fsum(c['budget_charged_cny'] for c in calls),'unknown_usage_attempts':unknown,
        'invoice_cny':None,'fallbacks':sum(bool(c.get('fallback')) for c in calls),
        'returned_models':dict(Counter(c['transport'].get('model','unavailable') for c in calls)),
        'fingerprints':dict(Counter(c['transport'].get('system_fingerprint','unavailable') for c in calls))}
    if config['budget_cny'] is not None and reliability['conservative_charged_cny']>config['budget_cny']+1e-9:raise ValueError('Budget exceeded')
    atomic_json(out/'reliability_metrics.json',reliability)
    failures=[{k:c.get(k) for k in ('run_id','experiment','scenario_id','source_game_id','observer_id','variant','policy_revision','adapter_revision',
        'phase','decision_id','attempt_uid','retry_index','error','validation_reason','failure_class','usage_status')}|
        {'status':'recovered' if any(r.get('accepted') for r in by_decision[c['decision_id']]) else 'failed_or_unresolved'}
        for c in calls if not c.get('accepted')]
    write_csv(out/'failure_audit.csv',failures or [{'run_id':out.name,'status':'no_recorded_failures','count':0}])
    active=[r for r in jobs if r['scope'] in {'single_seat','whole_table'}]
    for r in active:
        own=[c for c in calls if c['experiment']==r['experiment'] and c['scenario_id']==r['scenario_id'] and c['variant']==r['variant']]
        r['external_model_calls']=len(own)
        r['model_tokens']=sum(c['transport'].get('usage',{}).get('total_tokens',0) for c in own) if own and all(c['usage_status']=='reported' for c in own) else None
        r['model_cost']=math.fsum(c['estimated_cny'] for c in own) if own and all(c['estimated_cny'] is not None for c in own) else None
    write_csv(out/'games.csv',active or [{'run_id':out.name,'status':'not_run'}])
    grouped=defaultdict(dict)
    for r in jobs:grouped[(r['experiment'],r['scenario_id'])][r['variant']]=r
    outcomes=[];fixed_pairs=[];transitions=Counter();votes=[];comparisons={};buckets=defaultdict(list)
    for pair in pairs:
        rows=grouped[pair['experiment'],pair['scenario_id']]
        if len(pair['planned_order'])!=2:continue
        arm_a,arm_b=('joint_v1','joint_v2') if pair['experiment']=='A' else ('policy_current','policy_candidate')
        a,b=rows.get(arm_a,{}),rows.get(arm_b,{})
        base={'run_id':out.name,**pair,'reference_arm':arm_a,'candidate_arm':arm_b,
            'variant':'paired','adapter_revision':config['adapter_revision'],
            'policy_revision':'same_current' if pair['experiment']=='A' else 'vote_only_candidate'}
        if pair['scope'].startswith('fixed'):
            if a and b:
                if a.get('legal_view_hash')!=b.get('legal_view_hash') or a.get('menu_hash')!=b.get('menu_hash'):raise ValueError('Different legal menus in fixed pair')
                if pair['experiment']=='B' and a.get('posterior_hash')!=b.get('posterior_hash'):raise ValueError('Policy experiment changed posterior')
            base.update(reference_action=a.get('action'),candidate_action=b.get('action'),observer_role=a.get('observer_role',b.get('observer_role')),
                same_view_and_menu=(a.get('menu_hash')==b.get('menu_hash')) if a.get('menu_hash') and b.get('menu_hash') else None,
                same_posterior=(a.get('posterior_hash')==b.get('posterior_hash')) if a.get('posterior_hash') and b.get('posterior_hash') else None,
                raw_action_changed=a.get('action')!=b.get('action') if pair['fully_paired'] else None)
            if pair['phase']=='team' and pair['fully_paired']:
                base.update(reference_clean=a['clean_team'],candidate_clean=b['clean_team'],
                    team_members_changed=set(a['action']['team'])!=set(b['action']['team']))
                transitions[pair['experiment'],a['observer_role'],a['clean_team'],b['clean_team']]+=1
                buckets[(pair['experiment'],'fixed_team',a['observer_role'])].append((pair['source_game_id'],a['clean_team'],b['clean_team']))
            if pair['phase']=='vote' and pair['fully_paired']:
                va=a['context']['view'];phase=f"attempt_{va['attempt']}_score_{va['successes']}_{va['failures']}"
                for arm,r in ((arm_a,a),(arm_b,b)):
                    votes.append({'run_id':out.name,'experiment':pair['experiment'],'scenario_id':pair['scenario_id'],'source_game_id':pair['source_game_id'],
                        'observer_id':r['observer_id'],'observer_role':r['observer_role'],'variant':arm,'policy_revision':r['policy_revision'],
                        'adapter_revision':r['adapter_revision'],'status':r['status'],'stage':phase,'approve':r['approve'],'strong':r['strong'],
                        'denominator':1,'last_chance':r['last_chance'],'counterfactual_mission_outcome':'unavailable'})
                buckets[(pair['experiment'],'fixed_vote_approval_descriptive',a['observer_role'])].append((pair['source_game_id'],a['approve'],b['approve']))
            fixed_pairs.append(base)
        else:
            metric='good_win' if pair['scope']=='whole_table' else 'focal_win'
            av=a.get(metric) if a.get('status')=='completed' else None;bv=b.get(metric) if b.get('status')=='completed' else None
            outcomes.append({**base,'reference_win':av,'candidate_win':bv,'win_difference':bv-av if pair['fully_paired'] else None})
            for role in ('ALL',a.get('focal_role',b.get('focal_role','unknown'))):
                buckets[(pair['experiment'],pair['scope']+'_'+pair['phase'],role)].append((pair['scenario_id'],av,bv))
    for key,items in sorted(buckets.items()):comparisons['/'.join(key)]=cluster_delta(items)
    write_csv(out/'paired_outcomes.csv',outcomes)
    write_csv(out/'snapshot_pairs.csv',fixed_pairs)
    write_csv(out/'team_transition_table.csv',[{'run_id':out.name,'experiment':exp,'observer_role':role,'reference_clean':a,'candidate_clean':b,'count':n,
        'denominator':sum(v for (e,r,_,_),v in transitions.items() if e==exp and r==role),'status':'completed'} for (exp,role,a,b),n in sorted(transitions.items())])
    # Physical vote consequences come only from actual active Game events.
    for path in sorted((out/'active_replays').glob('*.json')):
        record=json_read(path);truth={p['id']:p['role'] for p in record['players']}
        for e in record['events']:
            if e['kind']!='VOTE':continue
            coord=(e['round'],e['attempt'])
            vote=next((x for x in record['events'] if x['kind']=='TEAM_VOTE' and (x['round'],x['attempt'])==coord),None)
            mission=next((x for x in record['events'] if x['kind']=='MISSION' and (x['round'],x['attempt'])==coord),None)
            votes.append({k:record.get(k) for k in ('run_id','experiment','scenario_id','source_game_id','variant','policy_revision','adapter_revision')}|
                {'scope':'active','observer_id':e['actor'],'observer_role':truth[e['actor']],
                 'status':record['status'],'stage':f"round_{e['round']}_attempt_{e['attempt']}",
                 'approve':int(e['approve']),'strong':int(e.get('strong',False)),'denominator':1,
                 'last_chance':e['attempt']==5,'proposal_approved':vote['approved'] if vote else None,
                 'actual_mission_success':mission['success'] if mission else None,
                 'action_source':'model_or_forced' if record['scope']=='whole_table' or e['actor']==record['observer_id'] else 'controlled_opponent'})
    write_csv(out/'vote_phase_metrics.csv',votes or [{'run_id':out.name,'status':'not_run'}])
    fixed=[r for r in jobs if r['scope'].startswith('fixed')]
    (out/'fixed_snapshot_results.jsonl').write_text(''.join(canonical(r)+'\n' for r in fixed))
    replay_files=sorted((out/'active_replays').glob('*.json'))
    (out/'active_replays.jsonl').write_text(''.join(p.read_text().strip()+'\n' for p in replay_files))
    repeats=[]
    for r in fixed:
        if r['experiment']!='repeat':continue
        ref=next((x for x in fixed if x['experiment']=='A' and x['snapshot_id']==r['snapshot_id'] and x['variant']=='joint_v2'),None)
        rc=[c for c in calls if c.get('scenario_id')==r['scenario_id'] and c.get('retry_index')==0]
        ac=[c for c in calls if ref and c.get('scenario_id')==ref['scenario_id'] and c['variant']=='joint_v2' and c.get('retry_index')==0]
        real=bool(rc and ac and not rc[0].get('client_cache_hit') and rc[0]['attempt_uid']!=ac[0]['attempt_uid'])
        equal=independent_repeat(ac[0],rc[0]) if real else False
        repeats.append({'snapshot_id':r['snapshot_id'],'source_game_id':r['source_game_id'],'repeat_index':r['repeat_index'],
            'independent_http_requests':real,'identical_initial_payload':equal,'status':r['status'],
            'action_changed':r.get('action')!=ref.get('action') if ref and r['status']==ref['status']=='completed' else None})
    write_csv(out/'repeat_input_audit.csv',repeats or [{'status':'not_run'}])
    summary={'run_id':out.name,'status':'completed' if all(p['status']=='completed' for p in pairs) else 'partial',
        'stop_reason':config.get('stop_reason','not_started'),'accounting':accounting,'reliability':reliability,
        'comparisons':comparisons,'repeat_observations':repeats,'tests':config['tests'],
        'experiments_separate':True,'belief_and_rules_frozen':True,'language_evidence':'not_run',
        'limitations':['Historical active A scenarios are reused diagnostics, not unseen tests.',
            'Fixed snapshots use source-game clusters; approval rate is descriptive, not accuracy.',
            'Eight B active pairs and four A whole-table pairs are small samples.',
            'Degenerate bootstrap is not equivalence or absence of risk.',
            'DeepSeek alias/fingerprint is recorded; backend weights cannot be pinned.',
            'Incomplete pairs are excluded only from conditional effect estimates, retained in completion accounting.']}
    atomic_json(out/'summary.json',summary)
    lines=['# Joint Belief v2.1：真实调用稳定性与投票策略','',f"运行 `{out.name}`，状态 **{summary['status']}**；停止原因 `{summary['stop_reason']}`。",'',
        'A 使用同一个新动作适配器和 policy_current 比较 joint_v1 / joint_v2。B 固定 joint_v2，仅增加投票 DecisionContext；两者分别报告。原 Agent、规则、概率更新均冻结。',
        '附件指定报告对应旧 contract 运行，不是后续 legal-context 运行。前者 6 个 smoke 配对中 3 对完整、1 对单侧完成、2 对两侧失败；44 个主实验配对未启动。34 次重试归属 28 个逻辑决策，其中 22 个恢复，6 个失败（5 个主动游戏与 1 个独立快照）。停止门槛与费用无关。详细旧运行账目及逐条 fixture 位于 historical_audit/，不并入新效果样本。','',
        '## 调用与完成情况','',f"真实 HTTP {len(calls)} 次；逻辑模型决策 {len(by_decision)} 个；首次合法 {first}/{len(by_decision)}，最终合法 {eventual}/{len(by_decision)}。", 
        f"已返回 usage 估算 ¥{reliability['estimated_cny_from_returned_usage']:.4f}；未知 usage {unknown} 次；保守记账 ¥{reliability['conservative_charged_cny']:.4f}，授权上限 {config['budget_cny']}。未查询账单。",'',
        '|实验 / 范围 / 阶段|计划场景|启动|完整|单侧完成|各臂状态|','|---|---:|---:|---:|---:|---|']
    for name,a in accounting.items():lines.append(f"|{name}|{a['planned_scenarios']}|{a['started_scenarios']}|{a['fully_completed_scenarios']}|{a['one_side_completed_pairs']}|{a['arm_states']}|")
    lines+=['','## 分离的效果比较','', '|实验 / 指标 / 角色|参照 分子/分母|候选 分子/分母|差值|95% 聚类区间|判断|','|---|---|---|---|---|---|']
    for name,m in comparisons.items():
        a,b=m['reference'],m['candidate'];lines.append(f"|{name}|{a['numerator']}/{a['denominator']}|{b['numerator']}/{b['denominator']}|{m['delta']}|{m['ci95']}|{m['status']}|")
    lines+=['','固定投票只描述同局面动作差异，赞成增多不表示更好；中间队伍质量不等于所有角色的统一效用。主动对局允许轨迹分叉。置信区间含零时不声称改善，退化区间不声称等效。',
        '', '## 实现、测试与重建','',
        '新 legal-menu adapter 不要求无关阶段的 full plan。菜单来自合法视图，保留全部合法队伍、投票和资源选项；发言使用可校验参数。action_id 绑定当前私有视图摘要；版本标签不进入模型输入。',
        f"本次预先声明的格式规范化：{config['contract_normalization']}；逐次实际处理保存在 llm_calls.jsonl 的 normalization 字段。非法动作由模型修正，不由主机替换。",
        '传输重试最多 2 次，格式/合法性修正最多 2 次，全部计费尝试写入持久请求记录。未返回 usage 的在途请求恢复后继续保留额度。没有脚本降级。',
        '动作先在脱离的真实 Game 事务中校验，原子 checkpoint 保存后提交；密封投票/任务牌收齐后统一推进。恢复从原始初始合法视图、已接受动作及公共事件重建新的内存游戏，逐项核对上下文与状态哈希，不再次调用模型、不在已有状态重复扣资源。源代码/config/contract 不兼容时拒绝恢复。',
        f"测试：{config['tests']}。离线快照审核见 offline_snapshot_audit.json，故障重放见 fixture_replay.json。",'',
        '## 限制与文件','',*['- '+x for x in summary['limitations']],
        '- llm_calls.jsonl：每次真实尝试及 usage；decision_attempts.jsonl：接受/执行分离；checkpoints/：可重建状态。',
        '- pair_manifest.jsonl 包含全部计划及未运行项。games.csv / paired_outcomes.csv 可独立复算逐局/配对结果。',
        '- fixed_snapshot_results.jsonl 保存完整 joint 状态、合法上下文、菜单和动作；truth 标注仅在主机离线评分出现。',
        '- 模型内部 reasoning_content 与凭据均不导出。自然语言因子、递归 ToM、跨局记忆关闭。',
        '- 运行命令见 docs/joint-belief-v21.md；report-only 不访问网络。',
        '', '本实验不预设 v2.1 更强。稳定性门槛与行动效果是独立结论。']
    (out/'report.md').write_text('\n'.join(lines)+'\n')
    return summary
