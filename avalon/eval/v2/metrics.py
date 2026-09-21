"""Host-only scores. The evaluator's truth never enters an inference adapter."""
from collections import defaultdict
import math
from avalon.eval.beliefs import score_beliefs, EPSILON
from avalon.eval.simulation import canonical

TIE_REL, TIE_ABS = 1e-9, 1e-12


def tied(a,b):
    return math.isclose(a,b,rel_tol=TIE_REL,abs_tol=TIE_ABS)


def rank_metrics(distribution, actual, prefix):
    if not distribution:
        return {prefix+k:None for k in ("probability","midrank","top_ties","in_top","unique_correct","tie_expected_hit","log_loss")}
    p = distribution.get(actual,0.0)
    highest = max(distribution.values())
    top = [k for k,v in distribution.items() if tied(v,highest)]
    equals = sum(tied(v,p) for v in distribution.values())
    higher = sum(v>p and not tied(v,p) for v in distribution.values())
    rank = 1+higher+(equals-1)/2 if actual in distribution else len(distribution)+1
    hit = actual in top
    return {prefix+"probability":p,prefix+"midrank":rank,prefix+"top_ties":len(top),
            prefix+"in_top":int(hit),prefix+"unique_correct":int(hit and len(top)==1),
            prefix+"tie_expected_hit":float(hit)/len(top),prefix+"log_loss":-math.log(max(EPSILON,p))}


def score(observer, truth, previous=None):
    result = score_beliefs(observer,truth,previous)
    worlds = observer.distribution()
    alignments = observer.rules["role_alignments"]
    evilsets = defaultdict(float)
    merlin = {p:0.0 for p in observer.ids}
    for world, mass in worlds.items():
        evilsets[tuple(p for p,r in world if alignments[r]=="EVIL")] += mass
        for p,r in world:
            if r=="MERLIN": merlin[p]+=mass
    actualevil = tuple(sorted(p for p,r in truth.items() if alignments[r]=="EVIL"))
    actualmerlin = next((p for p,r in truth.items() if r=="MERLIN"),None)
    result.update(rank_metrics(worlds,tuple(sorted(truth.items())),"configuration_"))
    result.update(rank_metrics(evilsets,actualevil,"evil_set_"))
    result.update(rank_metrics(merlin if worlds and actualmerlin else {},actualmerlin,"merlin_"))
    result["merlin_brier"] = math.fsum((v-float(p==actualmerlin))**2 for p,v in merlin.items()) if actualmerlin and worlds else None
    result["merlin_probability_source"] = "scoring_projection" if observer.legacy else "native_joint"
    result["merlin_top_set"] = canonical(sorted(p for p,v in merlin.items() if tied(v,max(merlin.values())))) if worlds else None
    result["merlin_top_set_changed"] = int(previous is not None and previous.get("merlin_top_set") != result["merlin_top_set"])
    result["role_marginals_json"] = canonical(observer.role_marginals())
    result["raw_marginals_json"] = canonical(observer.marginals())
    result["merlin_distribution_json"] = canonical(merlin)
    raw = {p:b["merlin"] for p,b in observer.marginals().items()}
    total = math.fsum(raw.values())
    result["legacy_normalized_raw_merlin_log_loss"] = (-math.log(max(EPSILON,raw[actualmerlin]/total))
            if observer.legacy and actualmerlin and total>0 else None)
    result["legacy_raw_merlin_sum"] = total if observer.legacy else None
    result["scoring_epsilon"] = EPSILON
    result["configuration_floor_hit"] = int(result["configuration_probability"] is not None and result["configuration_probability"]<EPSILON)
    result["merlin_floor_hit"] = int(result["merlin_probability"] is not None and result["merlin_probability"]<EPSILON)
    known = set(observer.knowledge["known_good_players"])|set(observer.knowledge["known_evil_players"])|{observer.pid}
    result["unknown_target_ids"] = canonical([p for p in observer.ids if p not in known])
    result["truth_roles_json"] = canonical(truth)
    result["binary_floor_hits"] = sum((b["evil"] if alignments[truth[p]]=="EVIL" else 1-b["evil"])<EPSILON
                                         for p,b in observer.marginals().items() if p not in known)
    for name in ("unknown_brier_score","unknown_log_loss"):
        result[name+"_denominator"] = result["unknown_targets"]
        result[name+"_numerator"] = result[name]*result["unknown_targets"] if result[name] is not None else None
    result["evil_count_error"] = abs(sum(b["evil"] for b in observer.marginals().values())-
                                  sum(n for r,n in observer.rules["role_counts"].items() if alignments[r]=="EVIL"))
    return result
