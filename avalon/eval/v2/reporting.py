"""Deterministic raw-export aggregation; no inference, generation or API calls."""
from collections import Counter, defaultdict
import csv
import hashlib
import json
import math
from pathlib import Path

from avalon.eval.joint_belief import write_json
from avalon.eval.statistics import Metric, paired_comparisons, PATHOLOGIES
from avalon.eval.simulation import canonical, keyed_uniform
from .adapters import VARIANTS
from .additional_analyses import direct_ablation_contrasts, assassin_snapshot_scores, assassin_snapshot_comparisons

METRICS=("unknown_brier_score","unknown_log_loss","evil_set_probability","evil_set_midrank",
         "merlin_brier","merlin_log_loss","merlin_probability","merlin_midrank","merlin_top_ties",
         "configuration_log_loss","configuration_probability","configuration_midrank","configuration_top_ties",
         "configuration_in_top","configuration_unique_correct","configuration_tie_expected_hit",
         "merlin_top_set_diff_vs_v1","entropy")
LOWER={x for x in METRICS if "loss" in x or "brier" in x or "midrank" in x}
HIGHER={x for x in METRICS if "probability" in x or "correct" in x or "expected_hit" in x or "in_top" in x}


def write_csv(path, rows, fields=None):
    rows=list(rows)
    fields=fields or list(dict.fromkeys(k for r in rows for k in r)) or ["status"]
    with Path(path).open("w",newline="") as stream:
        writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader();writer.writerows(rows)


def read_csv(path):
    def decode(v):
        if v=="":return None
        if v in {"True","False"}:return v=="True"
        try:return float(v) if any(x in v.lower() for x in (".","e")) else int(v)
        except ValueError:return v
    with Path(path).open(newline="") as stream:
        for r in csv.DictReader(stream):yield {k:decode(v) for k,v in r.items()}


def endpoints_and_episodes(path):
    endpoints={}; active={}; episodes=[]; updates=Counter(); totalrows=0
    for row in read_csv(path):
        totalrows+=1
        if not row["decision_available"]:continue
        key=(row["game_id"],row["variant"],row["observer_id"])
        endpoints[key]=row
        for flag in PATHOLOGIES:
            k=(*key,flag)
            if row[flag]:
                updates[(row["variant"],flag)]+=1
                if k not in active:
                    active[k]={"game_id":key[0],"variant":key[1],"observer_id":key[2],"observer_role":row["observer_role"],
                      "split":row["split"],"profile":row["profile"],"pathology":flag,
                      "first_event_id":row["event_id"],"first_event_kind":row["event_kind"],"first_seq":row["event_seq"],
                      "last_event_id":row["event_id"],"last_seq":row["event_seq"],"update_count":0,"affected_target_updates":0}
                ep=active[k]; ep["update_count"]+=1;ep["affected_target_updates"]+=row[flag]
                ep["last_event_id"],ep["last_seq"]=row["event_id"],row["event_seq"]
            elif k in active:
                ep=active.pop(k);ep.update(recovered=1,endpoint_still_abnormal=0,recovery_event_id=row["event_id"],
                    duration_events=row["event_seq"]-ep["first_seq"])
                episodes.append(ep)
    for key,ep in active.items():
        end=endpoints[key[:3]]
        ep.update(recovered=0,endpoint_still_abnormal=1,recovery_event_id=None,
                  duration_events=end["event_seq"]-ep["first_seq"]+1)
        episodes.append(ep)
    return list(endpoints.values()),episodes,totalrows


def group_comparisons(endpoints, by_profile=False, resamples=2000):
    groups=defaultdict(list)
    for r in endpoints:
        groups[(r["split"],r["observer_role"],r["profile"] if by_profile else "all")].append(r)
    output=[]
    specs={m:Metric(m,direction="lower" if m in LOWER else "higher" if m in HIGHER else "descriptive") for m in METRICS}
    for (split,role,profile),rows in sorted(groups.items()):
        reference_tops={(r["game_id"],r["observer_id"]):r["merlin_top_set"] for r in rows if r["variant"]=="joint_v1"}
        rows=[{**r,"merlin_top_set_diff_vs_v1":int(r["merlin_top_set"]!=reference_tops[(r["game_id"],r["observer_id"])])} for r in rows]
        gamegroups=defaultdict(list)
        for r in rows:gamegroups[(r["game_id"],r["variant"])].append(r)
        reduced={}
        for (g,v),seats in gamegroups.items():
            record={"pair_id":g,"pair_signature":g,"variant":v}
            for m in METRICS:
                vals=[s[m] for s in seats if s.get(m) is not None]
                record[m]=math.fsum(vals)/len(vals) if vals else None
            reduced[(g,v)]=record
        for variant in VARIANTS:
            pair=[]
            for (g,v),r in reduced.items():
                if v==variant:pair.append({**r,"variant":"joint_belief"})
                if v=="joint_v1":pair.append({**r,"variant":"baseline"})
            results=paired_comparisons(pair,specs,resamples=resamples,seed=61051)
            selected=[r for r in rows if r["variant"]==variant]
            for metric,value in results.items():
                output.append({"split":split,"observer_role":role,"profile":profile,"variant":variant,"reference":"joint_v1",
                    "metric":metric,"mean":value["joint_belief"],"reference_mean":value["baseline"],
                    "delta":value["absolute_delta"],"ci_low":value["delta_ci95"][0] if value["delta_ci95"] else None,
                    "ci_high":value["delta_ci95"][1] if value["delta_ci95"] else None,
                    "interpretation":value["interpretation"],"game_clusters":value["eligible_clusters"],
                    "observers":len(selected),"unknown_targets":sum(r["unknown_targets"] for r in selected),
                    "numerator":value["joint_belief"]*value["joint_belief_denominator"] if value["joint_belief"] is not None else None,
                    "denominator":value["joint_belief_denominator"],"reference_denominator":value["baseline_denominator"],
                    "aggregation":"observer mean within game, then equal game mean; paired game bootstrap",
                    "direction":value["direction"],"probability_source":"raw_marginals" if metric.startswith("unknown_") else
                        "scoring_projection" if variant=="legacy_baseline" else "native_joint"})
    return output


def calibration_rows(endpoints):
    groups=defaultdict(list)
    for r in endpoints:
        truth=json.loads(r["truth_roles_json"]);raw=json.loads(r["raw_marginals_json"])
        for pid in json.loads(r["unknown_target_ids"]):
            prob=raw[pid]["evil"];actual=int(truth[pid] in {"EVIL","ASSASSIN"})
            groups[(r["split"],r["variant"],r["observer_role"],"unknown_alignment",min(9,int(prob*10)))].append((prob,actual,r["game_id"]))
        # An unavailable scoring projection is not an all-zero categorical forecast.
        for pid,prob in (json.loads(r["merlin_distribution_json"]).items() if r.get("merlin_brier") is not None else []):
            groups[(r["split"],r["variant"],r["observer_role"],"merlin_projection" if r["variant"]=="legacy_baseline" else "merlin_native",min(9,int(prob*10)))].append((prob,int(truth[pid]=="MERLIN"),r["game_id"]))
    return [{"split":s,"variant":v,"observer_role":r,"target":t,"bin_lower":b/10,"bin_upper":(b+1)/10,
             "prediction_sum":math.fsum(x[0] for x in vals),"positive_count":sum(x[1] for x in vals),
             "sample_count":len(vals),"game_count":len({x[2] for x in vals}),
             "mean_prediction":math.fsum(x[0] for x in vals)/len(vals),"observed_frequency":sum(x[1] for x in vals)/len(vals)}
            for (s,v,r,t,b),vals in sorted(groups.items())]


def paired_outcomes(games):
    pairs=defaultdict(dict)
    for r in games:
        if r["scope"]!="generation":pairs[r["pair_id"]][r["variant"]]=r
    rows=[]
    for pair,byv in sorted(pairs.items()):
        a,b=byv.get("joint_v1"),byv.get("joint_v2")
        if a is None or b is None:raise ValueError("Missing active pair")
        if a["pair_signature"]!=b["pair_signature"]:raise ValueError("Pair mismatch")
        metric="good_win" if a["scope"]=="whole_table" else "focal_win"
        x,y=a[metric],b[metric]
        available=x is not None and y is not None
        rows.append({"pair_id":pair,"scenario_id":pair,"scope":a["scope"],"phase":a["phase"],"profile":a["profile"],
          "focal_role":a["focal_role"],"focal_id":a["focal_id"],"metric":metric,
          "joint_v1_game_id":a["game_id"],"joint_v2_game_id":b["game_id"],"joint_v1_win":x,"joint_v2_win":y,
          "joint_v1_status":a["status"],"joint_v2_status":b["status"],"available":int(available),
          "both_win":int(x==y==1) if available else None,"only_v1_win":int(x==1 and y==0) if available else None,
          "only_v2_win":int(x==0 and y==1) if available else None,"both_lose":int(x==y==0) if available else None,
          "win_difference":y-x if available else None,"denominator":int(available),"pair_signature":a["pair_signature"]})
    return rows


def active_summary(games,resamples):
    result={}
    for scope in ("single_seat","whole_table"):
        for phase in ("smoke","main"):
            selected=[r for r in games if r["scope"]==scope and r["phase"]==phase]
            if not selected:continue
            metrics={"win_rate":Metric("good_win" if scope=="whole_table" else "focal_win",direction="higher"),
                     "latency_ms_per_observation":Metric("belief_update_ms","belief_observations",direction="lower"),
                     "game_seconds":Metric("game_seconds",direction="lower"),
                     "conditional_assassin_hit":Metric("merlin_assassinated","assassination_opportunities",direction="higher")}
            if scope=="single_seat":
                metrics.update({"win_role_"+r:Metric("focal_win",condition=("focal_role",r),direction="higher")
                                for r in sorted({x["focal_role"] for x in selected})})
            metrics.update({stage+"_clean_rate":Metric(stage+"_clean_teams",stage+"_team_count",direction="higher")
                            for stage in ("proposed","approved","executed")})
            stats=paired_comparisons([{**r,"variant":"baseline" if r["variant"]=="joint_v1" else "joint_belief"} for r in selected],
                                    metrics,resamples=resamples,seed=74119)
            # Clear version names replace the legacy helper's internal labels.
            for value in stats.values():
                for old,new in (("baseline","joint_v1"),("joint_belief","joint_v2")):
                    for suffix in ("","_ci95","_denominator"):
                        value[new+suffix]=value.pop(old+suffix)
                for v in ("joint_v1","joint_v2"):
                    value[v+"_numerator"] = value[v]*value[v+"_denominator"] if value[v] is not None else None
            result[scope+"_"+phase]=stats
    return result


def behavior_coverage(path):
    counts=Counter(); denominators=Counter(); games=defaultdict(set)
    def add(record,role,metric,value=1,denom=1):
        k=(record["split"],record["profile"],role,metric)
        counts[k]+=value;denominators[k]+=denom;games[k].add(record["game_id"])
    with Path(path).open() as stream:
        for line in stream:
            rec=json.loads(line);truth={p["id"]:p["role"] for p in rec["players"]}
            for pid,r in truth.items():add(rec,r,"role_games")
            attacks=[e for e in rec["events"] if e["kind"]=="ASSASSINATE"]
            add(rec,"MERLIN","entered_assassination",int(bool(attacks)))
            add(rec,"MERLIN","survived_assassination_unconditional",int(not any(truth[e["target"]]=="MERLIN" for e in attacks)))
            for e in rec["events"]:
                r=truth.get(e.get("actor"),"table")
                if e["kind"]=="SOCIAL":
                    add(rec,r,"social_"+e["card"]);add(rec,r,"social_target_"+truth[e["target"]])
                if e["kind"]=="TEAM_REVISE":add(rec,r,"revised_proposals")
                if e["kind"]=="TEAM" and e.get("attempt",1)>1:add(rec,r,"reproposal_after_rejection")
                if e["kind"]=="TEAM_VOTE":
                    add(rec,"table","rejected_proposal_rate",int(not e["approved"]))
                    for pid,approved in e["votes"].items():
                        add(rec,truth[pid],"approve_rate",int(approved))
                        if all(truth[p] not in {"EVIL","ASSASSIN"} for p in e["team"]):
                            add(rec,truth[pid],"clean_team_approval",int(approved))
                if e["kind"]=="MISSION":
                    dirty=any(truth[p] in {"EVIL","ASSASSIN"} for p in e["team"])
                    add(rec,"table","dirty_success_rate",int(dirty and e["success"]))
                    for p in e["team"]:add(rec,truth[p],"mission_success_contribution",int(e["success"]))
                if e["kind"]=="ASSASSINATE":add(rec,"MERLIN","assassinated_given_attempt",int(truth[e["target"]]=="MERLIN"))
            for d in rec.get("decisions",[]):
                r=truth[d["observer_id"]];v=d["view"]
                add(rec,r,"style_quartile_decisions_"+str(int(keyed_uniform(rec['seed'],'style',d['observer_id'])*4)))
                if d["phase"] in {"discussion","council_discussion","revision"}:
                    add(rec,r,"zero_resource_decision",int(v["resolve"][d["observer_id"]]==0))
                    for o in v["legal_options"]:add(rec,r,"available_"+o["kind"])
                    if 'SOCIAL' in v['legal_actions']:
                        from avalon.engine import CARDS
                        for card in CARDS:add(rec,r,"available_card_"+card)
                if d["phase"]=="mission" and r in {"EVIL","ASSASSIN"}:
                    add(rec,r,"evil_SUCCESS_card_rate",int(d["action"]["card"]=="SUCCESS"))
    return [{"split":k[0],"profile":k[1],"role":k[2],"metric":k[3],"numerator":counts[k],"denominator":denominators[k],
             "rate":counts[k]/denominators[k] if denominators[k] else None,"game_count":len(games[k])} for k in sorted(counts)]


def p2_summary(path):
    counts=Counter();groups=defaultdict(set);assassin={}
    with Path(path).open() as stream:
        for line in stream:
            r=json.loads(line)
            if "experiment" not in r:continue
            k=(r["experiment"],r["split"],r["variant"],r["phase"])
            counts[(*k,"n")]+=1;counts[(*k,"changed")]+=r["action_changed"]
            counts[(*k,"correlation_changed")]+=r["marginal_vs_joint_changed"]
            groups[k].add(r["game_id"])
            if r["phase"]=="assassination":
                counts[(*k,"hits")]+=r["assassin_hit_offline"]
                assassin[(r["game_id"],r["observer_id"],r["after_seq"],r["variant"])]=r
    return [{"experiment":k[0],"split":k[1],"variant":k[2],"phase":k[3],"snapshot_count":counts[(*k,"n")],
             "game_count":len(gs),"quest_policy_action_changes":counts[(*k,"changed")],
             "marginal_vs_original_joint_action_changes":counts[(*k,"correlation_changed")],
             "assassin_hits":counts[(*k,"hits")] if k[3]=="assassination" else None,
             "denominator":counts[(*k,"n")],"execution":"counterfactual choices; no policy win-rate claim"} for k,gs in sorted(groups.items())]


def aggregate(folder,make_plots=True):
    folder=Path(folder);config=json.loads((folder/"config.json").read_text())
    endpoints,episodes,trace_rows=endpoints_and_episodes(folder/"belief_trace.csv")
    resamples=config["bootstrap_resamples"]
    roles=group_comparisons(endpoints,resamples=resamples)
    profiles=group_comparisons(endpoints,True,resamples)
    ablations=direct_ablation_contrasts(endpoints,METRICS,LOWER,HIGHER,resamples)
    assassin_scores=assassin_snapshot_scores(folder)
    assassin_comparisons=assassin_snapshot_comparisons(assassin_scores,resamples)
    calibration=calibration_rows(endpoints)
    games=list(read_csv(folder/"games.csv"));pairs=paired_outcomes(games)
    coverage=behavior_coverage(folder/"replays.jsonl")
    write_csv(folder/"role_metrics.csv",roles);write_csv(folder/"ablation_metrics.csv",ablations)
    write_csv(folder/"assassin_snapshot_metrics.csv",assassin_scores)
    write_csv(folder/"opponent_profile_metrics.csv",profiles);write_csv(folder/"calibration.csv",calibration)
    write_csv(folder/"pathology_episodes.csv",episodes, list(episodes[0]) if episodes else
              ["game_id","variant","observer_id","pathology","first_event_id","first_event_kind","duration_events","recovered","endpoint_still_abnormal"])
    write_csv(folder/"paired_outcomes.csv",pairs);write_csv(folder/"behavior_coverage.csv",coverage)
    audits=json.loads((folder/"replay_audit.json").read_text())
    pathology=[]
    for v in VARIANTS:
        for flag in PATHOLOGIES:
            es=[e for e in episodes if e["variant"]==v and e["pathology"]==flag]
            pathology.append({"variant":v,"pathology":flag,"updates":sum(e["update_count"] for e in es),
                "episodes":len(es),"unique_games":len({e["game_id"] for e in es}),"recovered":sum(e["recovered"] for e in es),
                "endpoint_ongoing":sum(e["endpoint_still_abnormal"] for e in es)})
    mission=Counter();tv=defaultdict(list)
    for r in read_csv(folder/"mission_update_audit.csv"):
        if r["duplicate_delivery"]:continue
        key=(r["variant"],r["split"],r["skip_reason"])
        mission[key]+=1
        if r["success"]:tv[(r["variant"],r["split"])].append(r["posterior_tv"])
    summary={"status":config["status"],"primary_comparison":"joint_v2 minus frozen joint_v1",
      "primary":[r for r in roles if r["split"]=="held_out_test" and r["observer_role"]=="GOOD" and r["variant"]=="joint_v2"
                 and r["metric"] in {"unknown_brier_score","unknown_log_loss"}],
      "roles":roles,"profiles":profiles,"ablations":ablations,"assassin_snapshots":assassin_comparisons,
      "active":active_summary(games,resamples),"pathologies":pathology,
      "mission_updates":[{"variant":v,"split":s,"reason":r,"count":n} for (v,s,r),n in sorted(mission.items())],
      "successful_mission_tv":[{"variant":v,"split":s,"mean_tv":sum(vals)/len(vals),"events":len(vals),
          "changed":sum(t>1e-12 for t in vals)} for (v,s),vals in sorted(tv.items())],
      "p2":p2_summary(folder/"decisions.jsonl"),"tests":config.get("tests"),
      "correctness_rerun":config.get("correctness_rerun"),
      "counts":{"trace_rows":trace_rows,"replay_games":len({r["game_id"] for r in audits}),"replay_observer_variants":len(audits),
        "physical_games":len(games),"failed_games":sum(r["status"]!="completed" for r in games),"active_pairs":len(pairs),
        "same_stream_audits":len(audits)},
      "cost":{"external_model_calls":0,"tokens":None,"external_cost":None,"live_belief_to_action":"not_run: no explicit opt-in",
              "language_evidence_parser":"not_run: structured action facts only","wall_seconds":config.get("wall_seconds")},
      "score_floor_hits":{v:{k:sum(r[k] for r in endpoints if r["variant"]==v) for k in
                          ("configuration_floor_hit","merlin_floor_hit","binary_floor_hits")} for v in VARIANTS}}
    write_json(folder/"summary.json",summary)
    write_report(folder,summary)
    if make_plots:plots(folder,roles,profiles,calibration,pathology,summary)
    # Independent sums from paired CSV must agree with the active summary.
    for scope in ("single_seat","whole_table"):
        p=[r for r in pairs if r["scope"]==scope and r["phase"]=="main" and r["available"]]
        if p:
            expected=sum(r["win_difference"] for r in p)/len(p)
            if not math.isclose(expected,summary["active"][scope+"_main"]["win_rate"]["absolute_delta"],abs_tol=1e-14):
                raise ValueError("Paired raw outcomes disagree with summary")
    write_json(folder/"export_validation.json",{"status":"passed","paired_csv_matches_summary":True,
        "report_primary_values_from_summary":True,"raw_reaggregation":"read exported CSV/JSONL only",
        "summary_sha256":hashlib.sha256((folder/"summary.json").read_bytes()).hexdigest()})
    return summary


def format_number(value):return "unavailable" if value is None else f"{value:.6g}"


def write_report(folder,s):
    lines=["# Avalon Joint Belief v2 — 实际离线评估", "", "主对照：joint_v2 − 冻结的 joint_v1；legacy_baseline 仅为历史独立边际与评分投影参照。",
      "", "## 根因与实现", "",
      "历史成功任务只产生机械硬约束。复核 70 个普通 GOOD 成功任务 checkpoint，完整 posterior TV 全部为 0；不是边际导出遮蔽了相关性变化。",
      "候选使用公开规则与结果、q=0.5、gamma=0.5 的独立破坏假设和 tempered update。公开精确计数只应用一次计数似然；隐藏计数按阈值求和。坏人成功始终可行。",
      "恒定似然、已确定信念、关闭开关和重复投递均有可区分审计。good_may_fail 的软策略语义明确不支持，机械约束仍保留。生产默认未启用 v2。",
      "", "## 预先冻结的主要指标", "", "held_out_test，普通 GOOD，终局动作/揭示前最后 checkpoint；同局观察者先平均，再对整局配对 bootstrap。", "",
      "| 指标 | joint_v1 | joint_v2 | 差值 | 95% CI | 判断 | 游戏 N |",
      "|---|---:|---:|---:|---|---|---:|"]
    for r in s["primary"]:
        lines.append(f"| {r['metric']} | {format_number(r['reference_mean'])} | {format_number(r['mean'])} | {format_number(r['delta'])} | [{format_number(r['ci_low'])}, {format_number(r['ci_high'])}] | {r['interpretation']} | {r['game_clusters']} |")
    if s.get('correctness_rerun'):
        lines += ["", "正确性复跑声明：首轮 P2 暴露恒定任务因子改变浮点精确 argmax 平局的问题。本轮仅让恒定软似然解析抵消，保留因子溯源；q/gamma、策略、角色配置、评分、主指标和 seed 全部不变。",
                  "复用了已经看过结果的同一测试场景，不能称为新的独立盲测，也不能与首轮合并增加样本量。首轮结果完整保留，dataset_manifest 验证回放语料逐字相同。",
                  f"首轮位置：{s['correctness_rerun']['prior_run']}"]
    lines += ["", "CI 跨零表示不确定；工程通过不证明效果改善。Brier 下降不代表完成校准，entropy 不设改善方向。", "", "## 行动对照（固定策略）", "",
      "配对共享初始角色、资源、环境与语义随机源。动作分叉后证据轨迹可以不同。单席位与全桌分别以整局/场景计样本；全桌指标是好人阵营胜率。", "",
      "| 实验 | 指标 | v1 | v2 | 差值 | 95% CI | 判断 |", "|---|---|---:|---:|---:|---|---|"]
    for name,stats in s["active"].items():
        if not name.endswith("main"):continue
        for metric,r in stats.items():
            lines.append(f"| {name} | {metric} | {format_number(r['joint_v1'])} | {format_number(r['joint_v2'])} | {format_number(r['absolute_delta'])} | {r['delta_ci95']} | {r['interpretation']} |")
    lines += ["", "## 消融、角色与泛化", "",
      "六版本接收逐字相同的合法初始视图及公共流，哈希和重复投递检查见 replay_audit.json。hard_only 保留知识与机械约束；no_success 仅关闭成功软因子；no_social 仅关闭 SOCIAL/REACT/CHALLENGE_RESPONSE 行为权重，未删事件或机械牌效。",
      "角色表区分 GOOD 角色与 good alignment，完整配置的 top-group、unique-correct、tie expected hit 单列。并列第一不能写为精确识别。legacy 原始边际不被评分投影替换，投影从不驱动行动。",
      "role_metrics.csv / ablation_metrics.csv 给出分角色和 split 的实际消融、分子分母和配对区间；opponent_profile_metrics.csv 给出行为族结果。未见的是策略组合，不能外推所有对手。", "",
      "| held-out 普通 GOOD 对照 | Brier 差值 | 95% CI | 判断 |", "|---|---:|---|---|"]
    for r in s["profiles"]:
        if r["split"]=="held_out_test" and r["observer_role"]=="GOOD" and r["variant"]=="joint_v2" and r["metric"]=="unknown_brier_score":
            lines.append(f"| {r['profile']} | {format_number(r['delta'])} | [{format_number(r['ci_low'])}, {format_number(r['ci_high'])}] | {r['interpretation']} |")
    lines += ["", "| held-out 消融（相对 v1） | GOOD Brier | 差值 |", "|---|---:|---:|"]
    for r in s["roles"]:
        if r["split"]=="held_out_test" and r["observer_role"]=="GOOD" and r["metric"]=="unknown_brier_score":
            lines.append(f"| {r['variant']} | {format_number(r['mean'])} | {format_number(r['delta'])} |")
    lines += ["", "以下直接消融差值统一为 full v2 − 对照；它们是探索性归因比较，未改变主要指标或测试集。", "",
              "| 直接对照 | GOOD Brier 差值 | 95% CI | 判断 |", "|---|---:|---|---|"]
    for r in s["ablations"]:
        if r["split"]=="held_out_test" and r["observer_role"]=="GOOD" and r["metric"]=="unknown_brier_score":
            lines.append(f"| {r['reference']} | {format_number(r['delta'])} | [{format_number(r['ci_low'])}, {format_number(r['ci_high'])}] | {r['interpretation']} |")
    lines += ["", "| held-out 角色 | 梅林 log loss v1 | v2 | 差值 | 95% CI |", "|---|---:|---:|---:|---|"]
    for r in s["roles"]:
        if r["split"]=="held_out_test" and r["observer_role"] in {"EVIL","ASSASSIN"} and r["variant"]=="joint_v2" and r["metric"]=="merlin_log_loss":
            lines.append(f"| {r['observer_role']} | {format_number(r['reference_mean'])} | {format_number(r['mean'])} | {format_number(r['delta'])} | [{format_number(r['ci_low'])}, {format_number(r['ci_high'])}] |")
    lines += ["", "## P2：固定 posterior 的策略诊断", "",
      "原 controlled-v1 已按 joint clean-team 概率选队。本轮另比较独立边际乘积、原 joint 策略、joint 任务失败风险策略；每个比较固定同一 posterior，记录全部合法候选、资源和最后机会。只做快照反事实选择，未把未执行的替代队伍算成胜局。实际 proposed/approved/executed 队伍质量见主动表。",
      "刺杀使用合法候选的 Merlin 概率 argmax。同一最高候选可保持相同动作，不人为随机化。固定刺杀前快照结果如下；不能和主动进入刺杀的条件集合混算。", "",
      "| 实验 / split / version / phase | 快照 N | 游戏 N | joint 任务策略动作变化 | 边际 vs 原 joint 变化 | 刺杀命中 |", "|---|---:|---:|---:|---:|---:|"]
    for r in s["p2"]:
        lines.append(f"| {r['experiment']} / {r['split']} / {r['variant']} / {r['phase']} | {r['snapshot_count']} | {r['game_count']} | {r['quest_policy_action_changes']} | {r['marginal_vs_original_joint_action_changes']} | {r['assassin_hits']} |")
    lines += ["", "| 固定刺杀机会 / split | 指标 | v1 | v2 | 差值 | 95% CI | 游戏 N |", "|---|---|---:|---:|---:|---|---:|"]
    for r in s["assassin_snapshots"]:
        lines.append(f"| {r['split']} | {r['metric']} | {format_number(r['joint_v1'])} | {format_number(r['joint_v2'])} | {format_number(r['delta'])} | {r['ci95']} | {r['game_clusters']} |")
    lines += ["", "已知坏人集合的观察者，对同一任务的所有存活假设通常具有相同破坏者人数，因此任务因子不会区分梅林候选；同一最高候选保持同一刺杀选择是合理结果。",
              "固定刺杀机会的完整候选分布、log loss/Brier、最高候选变化和实际 argmax 命中见 assassin_snapshot_metrics.csv。"]
    lines += ["", "梅林诊断见 behavior_coverage：公开动作、目标、投票、任务贡献、刺杀与生存；无精确暴露概率模型，也未污染梅林内部知识。", "", "## 完整性、成本与限制", "",
      f"实际规模：{canonical(s['counts'])}",f"测试：{canonical(s['tests'])}",f"运行成本：{canonical(s['cost'])}",
      "完整世界、原生 log probability、硬排除世界及证据因子保存于 hypothesis_trace.jsonl.gz；不是 Top-K 导出。病理 episode 记录首次事件、持续与恢复，summary 同时给更新数和去重游戏数。所有失败局保留。",
      "独立破坏假设不描述多坏人的真实协作；SOCIAL 权重沿用旧启发式。新对手有行为重叠，但仍只是有限受控策略族。未运行真实 LLM 的行动或语言解析；token/cost 为 unavailable。未实现完整递归 ToM 或在线学习。",
      "旧追加分析文件未找到；可用历史原始数据已独立复核。旧回放只作历史诊断。P2 未运行替代策略的额外主动胜率试验；快照比较不证明策略强度。",
      "source/ 保存本轮实际执行源码，source_manifest.json 记录哈希。原始评估与正确性修复复跑保留独立目录，不能混合增加样本量。",
      "", "## 重现", "", "```bash",
      ".venv/bin/python -m avalon.eval.joint_belief --suite joint_v2 --profile smoke --run-id <new-smoke-id>",
      ".venv/bin/python -m avalon.eval.joint_belief --suite joint_v2 --profile offline_full --run-id <new-full-id>",
      f".venv/bin/python -m avalon.eval.joint_belief --suite joint_v2 --profile report_only --run-dir {folder.resolve()}","```",
      "仅报告重算读取本目录原始 CSV/JSONL，无重新对局或模型调用。导出校验见 export_validation.json。"]
    (folder/"report.md").write_text("\n".join(lines)+"\n")


def plots(folder,roles,profiles,calibration,pathology,summary):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    dest=folder/"plots";dest.mkdir(exist_ok=True)
    def bars(name,labels,values,ylabel):
        fig,ax=plt.subplots(figsize=(10,5));ax.bar(range(len(values)),values)
        ax.set_xticks(range(len(labels)),labels,rotation=40,ha="right");ax.set_ylabel(ylabel)
        fig.tight_layout();fig.savefig(dest/(name+".png"),dpi=140);plt.close(fig)
    for metric in ("unknown_brier_score","merlin_log_loss"):
        r=[r for r in roles if r["split"]=="held_out_test" and r["variant"] in {"joint_v1","joint_v2"} and r["metric"]==metric and r["mean"] is not None]
        bars("role_"+metric,[x["observer_role"]+" / "+x["variant"] for x in r],[x["mean"] for x in r],metric)
    r=[r for r in roles if r["split"]=="held_out_test" and r["observer_role"]=="GOOD" and r["metric"]=="unknown_brier_score"]
    bars("ablation",[x["variant"] for x in r],[x["mean"] for x in r],"GOOD unknown Brier (lower is better)")
    r=[r for r in profiles if r["split"]=="held_out_test" and r["observer_role"]=="GOOD" and r["metric"]=="unknown_brier_score" and r["variant"] in {"joint_v1","joint_v2"}]
    bars("opponent_profiles",[x["profile"]+" / "+x["variant"] for x in r],[x["mean"] for x in r],"Unknown Brier")
    r=[r for r in summary["successful_mission_tv"] if r["split"]=="held_out_test"]
    bars("mission_update_tv",[x["variant"] for x in r],[x["mean_tv"] for x in r],"Mean full posterior TV on successful missions")
    fig,ax=plt.subplots(figsize=(6,5));ax.plot([0,1],[0,1],"k--",label="ideal reference")
    for v in ("joint_v1","joint_v2"):
        r=sorted([r for r in calibration if r["split"]=="held_out_test" and r["observer_role"]=="GOOD" and r["target"]=="unknown_alignment" and r["variant"]==v],key=lambda r:r["bin_lower"])
        ax.plot([x["mean_prediction"] for x in r],[x["observed_frequency"] for x in r],"o-",label=v)
        for x in r:ax.annotate(str(x["sample_count"]),(x["mean_prediction"],x["observed_frequency"]),fontsize=7)
    ax.set(xlabel="Predicted evil probability (labels = target N)",ylabel="Observed frequency");ax.legend();fig.tight_layout();fig.savefig(dest/"calibration.png",dpi=140);plt.close(fig)
    r=[r for r in pathology if r["pathology"]=="overconfident_wrong_marginals"]
    bars("pathology_games",[x["variant"] for x in r],[x["unique_games"] for x in r],"Distinct games, high-confidence wrong marginal")
    stats=summary["active"].get("single_seat_main",{})
    labels=[];vals=[]
    for k,r in stats.items():
        if k.startswith("win_role_"):
            for v in ("joint_v1","joint_v2"):labels.append(k[9:]+" / "+v);vals.append(r[v])
    if vals:bars("role_win_rates",labels,vals,"Actual focal role win rate")
