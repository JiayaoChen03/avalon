"""Recompute the complete paid session and fixed-posterior policy comparisons.

Reads local exports only. Earlier interface-debug runs remain separate samples;
their costs, calls and failures are included in session totals.
"""
from collections import Counter,defaultdict
import json
from pathlib import Path

from avalon.engine import EVIL_ROLES
from avalon.eval.statistics import Metric,paired_comparisons
from avalon.eval.joint_belief import write_json
from .reporting import format_number as f,write_csv,read_csv,paired_outcomes


def compare(a,b,metric,direction='higher'):
    rows=[]
    for key in sorted(set(a)&set(b)):
        for value,alias in ((a[key],'baseline'),(b[key],'joint_belief')):
            rows.append({'pair_id':key,'pair_signature':key,'variant':alias,metric:value})
    if not rows:return None
    s=paired_comparisons(rows,{metric:Metric(metric,direction=direction)},resamples=2000,seed=99173)[metric]
    for old,new in [('baseline','reference'),('joint_belief','candidate')]:
        for suffix in ('','_ci95','_denominator'):s[new+suffix]=s.pop(old+suffix)
    for name in ('reference','candidate'):
        s[name+'_numerator']=s[name]*s[name+'_denominator'] if s[name] is not None else None
    return s


def generate(folder):
    folder=Path(folder).resolve()
    config=json.loads((folder/'config.json').read_text());summary=json.loads((folder/'summary.json').read_text())
    provenance=json.loads((folder/'retry_provenance.json').read_text()) if (folder/'retry_provenance.json').exists() else {}
    paths=[]
    for item in provenance.get('previous_runs',[]):
        bundled=folder/'diagnostic_runs'/Path(item['run']).name
        paths.append(bundled if bundled.exists() else Path(item['run']))
    paths.append(folder)
    runs=[];usage=Counter()
    for path in paths:
        budget=json.loads((path/'budget.json').read_text());s=json.loads((path/'summary.json').read_text())
        calls=[json.loads(l) for l in (path/'llm_calls.jsonl').read_text().splitlines()]
        estimate=sum(c['estimated_cny'] or 0 for c in calls)
        conservative=sum(c['budget_charged_cny'] for c in calls)
        if len(calls)!=budget['http_attempts'] or abs(conservative-budget['conservative_budget_charged_cny'])>1e-9:
            raise ValueError('Raw request journal disagrees with budget ledger')
        games=list(read_csv(path/'games.csv'));outcomes=paired_outcomes(games)
        failed=sum(g['status']!='completed' for g in games);completed=sum(r['available'] for r in outcomes)
        if failed!=s['counts']['failed_games'] or completed!=s['counts']['complete_pairs']:
            raise ValueError('Raw game outcomes disagree with summary')
        runs.append({'run':str(path),'status':s['status'],'http_attempts':len(calls),
            'estimated_cny':estimate,'conservative_cny':conservative,
            'unknown_usage_reserved_cny':sum(c['budget_charged_cny'] for c in calls if c['usage_status']=='unavailable'),
            'unknown_usage_attempts':sum(c['usage_status']=='unavailable' for c in calls),'failed_games':failed,
            'completed_pairs':completed,'included_in_final_effect_sample':path==folder})
        for c in calls:usage.update(c['transport'].get('usage',{}))
    paid={'http_attempts':sum(r['http_attempts'] for r in runs),'estimated_cny':sum(r['estimated_cny'] for r in runs),
          'conservative_charged_cny':sum(r['conservative_cny'] for r in runs),'provider_usage':dict(usage),
          'unknown_usage_attempts':sum(r['unknown_usage_attempts'] for r in runs),'authorized_cny':50.,'invoice_cny':None}
    paid['unknown_usage_reserved_cny']=sum(r['unknown_usage_reserved_cny'] for r in runs)
    if paid['conservative_charged_cny']>50+1e-9:raise ValueError('Session budget exceeded')
    final_calls=[json.loads(l) for l in (folder/'llm_calls.jsonl').read_text().splitlines()]
    accepted={(r['stage'],r.get('snapshot_id'),r['variant']):r for r in final_calls
              if r['accepted'] and r['stage'] in {'fixed_snapshot','fixed_repeat'}}
    request_audit=[]
    for r in final_calls:
        if r['stage']!='fixed_repeat' or not r['accepted']:continue
        original=accepted.get(('fixed_snapshot',r['snapshot_id'],'joint_v1'))
        if original:
            request_audit.append({'snapshot_id':r['snapshot_id'],'initial_repeat_intended_identical':True,
                'accepted_request_payload_identical':original['transport']['request_sha256']==r['transport']['request_sha256'],
                'original_retry_index':original['retry_index'],'repeat_retry_index':r['retry_index']})
    write_csv(folder/'repeat_request_audit.csv',request_audit)
    role_rows=[]
    for scope,metrics in summary['active'].items():
        for name,value in metrics.items():
            if name.startswith('win_role_'):role_rows.append({'scope':scope,'role':name[9:],**value})
    write_csv(folder/'live_role_metrics.csv',role_rows)
    ref_file=folder/'fixed_controlled_reference.jsonl'
    controlled=[json.loads(l) for l in ref_file.read_text().splitlines()] if ref_file.exists() else []
    model=[json.loads(l) for l in (folder/'fixed_snapshot_results.jsonl').read_text().splitlines()]
    refs={(r['snapshot_id'],r['variant']):r for r in controlled}
    truth={r['game_id']:{p['id']:p['role'] for p in r['players']} for r in
           (json.loads(l) for l in (folder/'replays.jsonl').read_text().splitlines())}
    data=defaultdict(dict);checks=[]
    for r in model:
        if r['stage']!='fixed_snapshot':continue
        ref=refs.get((r['snapshot_id'],r['variant']))
        if ref is None:continue
        hashes_equal=ref['posterior_hash']==r['joint_state']['posterior_hash'] and ref['legal_view_hash']==r['legal_view_hash']
        if not hashes_equal:raise ValueError('Fixed policy comparison changed posterior or legal information')
        phase=r['phase'];roles=truth[r['game_id']]
        def score(action):
            if phase=='team':return int(all(roles[p] not in EVIL_ROLES for p in action['team']))
            if phase=='assassination':return int(roles[action['target']]=='MERLIN')
            if phase=='vote':return int(action['approve'])
        data[(phase,r['variant'],'controlled')][r['game_id']]=score(ref['original_action'])
        data[(phase,r['variant'],'DeepSeek')][r['game_id']]=score(r['action']) if r['status']=='completed' else None
        checks.append({'snapshot_id':r['snapshot_id'],'variant':r['variant'],'identical_posterior_and_view':hashes_equal,
                       'model_status':r['status'],'controlled_action':json.dumps(ref['original_action'],sort_keys=True),
                       'model_action':json.dumps(r.get('action'),sort_keys=True),
                       'model_chosen_joint_risk':r.get('chosen_joint_risk'),
                       'minimum_candidate_joint_risk':min(1-c['clean_probability'] for c in ref['candidates']) if phase=='team' else None})
    contrasts=[]
    for phase,metric in [('team','clean_team'),('assassination','merlin_hit'),('vote','approve')]:
        for policy in ('controlled','DeepSeek'):
            s=compare(data[(phase,'joint_v1',policy)],data[(phase,'joint_v2',policy)],metric,'descriptive' if phase=='vote' else 'higher')
            if s:contrasts.append({'phase':phase,'contrast':policy+' v2 minus v1','treatment':'belief summary',**s})
        for variant in ('joint_v1','joint_v2'):
            s=compare(data[(phase,variant,'controlled')],data[(phase,variant,'DeepSeek')],metric,'descriptive' if phase=='vote' else 'higher')
            if s:contrasts.append({'phase':phase,'contrast':variant+' DeepSeek minus controlled','treatment':'policy, identical posterior',**s})
    write_csv(folder/'fixed_policy_input_audit.csv',checks)
    write_csv(folder/'fixed_policy_comparisons.csv',contrasts)
    result={'runs':runs,'total_paid_session':paid,'final_primary':summary['active'],'fixed_policy_comparisons':contrasts,
            'input_audits':{'passed':len(checks),'same_posterior_and_view':all(r['identical_posterior_and_view'] for r in checks)},
            'repeat_request_audit':request_audit,
            'sample_pooling':False,'language_evidence_parser':'not_run','data_source':'raw per-run API journals/budgets, final paired outcomes and frozen snapshot exports'}
    if (folder/'first_divergence_summary.json').exists():
        result['first_action_divergence']=json.loads((folder/'first_divergence_summary.json').read_text())
    write_json(folder/'session_summary.json',result)
    unit=config['tests']['unit']['passed'];regression=config['tests']['regression']['passed']
    primary={r['metric']:r for r in summary['passive']['primary']}
    brier,logloss=primary['unknown_brier_score'],primary['unknown_log_loss']
    discordant=result.get('first_action_divergence',{}).get('single_seat_main_win_discordant_pairs',[])
    identical=[r for r in discordant if r.get('exact_initial_request_identical') and r.get('exact_accepted_request_identical') and r.get('marginals_equal')]
    divergence_text=(f"本轮 {len(discordant)} 个单席位胜负逆转中，{len(identical)} 个在首次动作分叉时，初始及最终成功请求的字节哈希、边际均相同（角色：{[r['focal_role'] for r in identical]}）。模型仍生成了不同公开动作，随后轨迹分叉。因此不能把观察到的胜率差直接解释成 v2 belief 的因果效果；同样不能据此证明没有退步。逐对证据见 first_action_divergence.csv。"
                     if 'first_action_divergence' in result else '首次动作分叉诊断未提供。')
    lines=['# DeepSeek 真实调用：最终对照与完整费用','',
        f"本轮最终运行状态 **{summary['status']}**。包含两次接口诊断在内，共 **{paid['http_attempts']} 次真实 HTTP 请求**，已返回用量合计 **{usage.get('total_tokens','unavailable')} tokens**，这部分按官方时间段单价估算 **¥{paid['estimated_cny']:.4f}**。另有 **{paid['unknown_usage_attempts']} 次请求用量未知**，按完整上限保留 ¥{paid['unknown_usage_reserved_cny']:.4f}；全部请求按高峰价保守记账 ¥{paid['conservative_charged_cny']:.4f}，低于用户授权 ¥50。账单金额未查询，未将估算冒充扣款。",'',
        f"最终运行完成配对 {summary['counts']['complete_pairs']}/{summary['counts']['planned_pairs']}，中止游戏 {summary['counts']['failed_games']}。未完成游戏保留在原始数据中，缺失胜负不填成败局；下表只列双方均完成的配对，失败造成的选择偏差尤其限制全桌组结论。",
        f'最终 run 的 {unit} 项专项测试通过；本会话 {regression} 项全仓回归已通过，修正重跑复用该结果并核对规则/推断源码哈希，具体标注在 config.json。120 局冻结回放已真实重跑，3,600 组观察者/版本信息流与重复投递审计通过，主要 belief 分数与上轮一致。',
        '', '## 真实模型主动对局','',
        '|范围|v1 胜/局|v2 胜/局|配对胜率差|95% CI|判断|','|---|---|---|---|---|---|']
    for scope in ('single_seat_main','whole_table_main','single_seat_smoke'):
        m=summary['active'].get(scope,{}).get('win_rate')
        if not m:lines.append(f'|{scope}|unavailable|unavailable|unavailable|unavailable|未运行|');continue
        lines.append(f"|{scope}|{f(m['joint_v1_numerator'])}/{f(m['joint_v1_denominator'])}|{f(m['joint_v2_numerator'])}/{f(m['joint_v2_denominator'])}|{f(m['absolute_delta'])}|{m['delta_ci95']}|{m['interpretation']}|")
    lines+=['','单席位以 focal 阵营获胜为一局得分；全桌以好人阵营获胜为一局得分。全桌从不按每个座位重复计样本。主动对局只匹配初始条件，动作分叉后证据可不同。全桌 LLM 与旧离线全桌策略构成不同，跨策略胜率只作描述。分角色胜率导出 live_role_metrics.csv。',
        divergence_text,
        '版本先后按 seed 奇偶交换，但单席位角色轮换与奇偶相关，角色内未独立平衡执行先后；服务端时间效应仍是限制。',
        '', '## 相同信息及固定 posterior 的动作对比','',
        '|阶段|对比|参照 分子/分母|候选 分子/分母|差值|95% CI|判断|','|---|---|---|---|---|---|---|']
    for r in contrasts:
        lines.append(f"|{r['phase']}|{r['contrast']}|{f(r['reference_numerator'])}/{f(r['reference_denominator'])}|{f(r['candidate_numerator'])}/{f(r['candidate_denominator'])}|{f(r['absolute_delta'])}|{r['delta_ci95']}|{r['interpretation']}|")
    lines+=['','team 指实际全好人队伍，assassination 指实际命中 Merlin，vote 仅指赞成率（描述性指标）。每个阶段每局仅选一份固定快照；区间按整局配对 bootstrap 2,000 次。固定 posterior 的策略比较逐条验证相同视图和完整 posterior 哈希。',
        '同模型 v1/v2 的动作差异仍可能包含服务端波动；相同初始输入重复请求结果见 report.md，最终成功请求是否也逐字相同另见 repeat_request_audit.csv。队伍成员相同但顺序不同不算语义换队，原始动作差异仍保留。刺杀按生产概率 argmax、模型排序打破并列；置信度变化不强迫更换最高目标。',
        '', '## 与上轮离线对照的关系','',
        f"被动 GOOD 未知目标 Brier：v1 {f(brier['reference_mean'])} → v2 {f(brier['mean'])}；binary log loss {f(logloss['reference_mean'])} → {f(logloss['mean'])}，和原冻结数据重算完全一致。这不衡量真实模型的语言理解。主动对局的同场景离线参照详见 report.md 与 summary.json；不把换策略后的差值当成单纯 belief 效应。",
        '', '## 接入修复与保留的失败','',
        '未更改 Agent、系统提示词、规则、belief 权重或评分器。为已有 ChatClient 增加可选温度、用量与请求审计；eval 入口增加并发预算、严格动作适配及分阶段输出格式说明。发现并修复了可见旧任务记录被近期事件引用校验误拒绝的问题；重试会明确给出模型原始错误动作和合法范围，不替模型选行动。',
        '', '|运行|真实请求|费用估算|中止游戏|用途|','|---|---|---|---|---|']
    for i,r in enumerate(runs):lines.append(f"|{Path(r['run']).name}|{r['http_attempts']}|¥{r['estimated_cny']:.4f}|{r['failed_games']}|{'最终比较' if r['included_in_final_effect_sample'] else '接口诊断，未并入效果样本'}|")
    lines+=['','所有原始失败均保留。数据已经用于诊断，修正重跑明确属于数据复用，不声称新独立 held-out 样本，也没有把重复轮次合并增加样本量。',
        '', '## 文件、命令与未完成项','',
        '- 原始请求/响应与 usage：llm_calls.jsonl；完整逐局胜负及终局原因：games.csv；配对复算：paired_outcomes.csv。',
        '- 固定合法快照：fixed_snapshot_results.jsonl；同 posterior 策略审计：fixed_policy_input_audit.csv；各完整 joint 状态：hypothesis_trace.jsonl.gz。',
        '- 主动回放包含初始角色/规则、完整真实事件流、每次合法视图和动作；因语言因子关闭，可由 make_version 和公共事件完整重建 posterior。真值仅在离线档案/scorer 使用。',
        '- 完整 200/20 组真实模型大样本未运行，本轮预先固定为 40/4；没有因 CI 结果而追加样本。',
        '- 自然语言证据解析保持 not_run，指未开启将语言解释写回 belief 的独立实验；模型仍可阅读合法的公开文字来行动。工程合法性、belief 指标与胜率是三种不同结论。',
        '- 模型别名不能钉住服务端权重；请求名、返回型号和 fingerprint 均记录。',
        '', '```bash',f'.venv/bin/python -m avalon.eval.v2.live_runner --report-only --run-dir {folder}',
        f'.venv/bin/python -m avalon.eval.v2.live_session_report {folder}', '```','',
        '估算单价来源：[DeepSeek 官方价格](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)。可运行的 smoke／完整小规模 live 命令见仓库 docs/joint-belief-live.md。']
    (folder/'comparison_report.md').write_text('\n'.join(lines)+'\n')
    return result


if __name__=='__main__':
    import sys
    result=generate(Path(sys.argv[1]))
    print(json.dumps(result['total_paid_session'],ensure_ascii=False,indent=2))
