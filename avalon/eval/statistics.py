"""Seed-clustered paired bootstrap comparisons; never treat trace rows as games."""

from collections import defaultdict
from dataclasses import dataclass
import math

import numpy as np


BELIEF_METRICS = ("brier_score", "log_loss", "unknown_brier_score", "unknown_log_loss",
                  "joint_log_loss", "true_hypothesis_probability", "true_hypothesis_rank",
                  "entropy", "remaining_hypotheses", "evil_count_error", "merlin_count_error")
LOWER_BETTER = {"brier_score", "log_loss", "unknown_brier_score", "unknown_log_loss",
                "joint_log_loss", "true_hypothesis_rank", "evil_count_error", "merlin_count_error"}
PATHOLOGIES = ("entropy_down_truth_down", "overconfident_wrong_world", "overconfident_wrong_marginals",
               "distribution_collapsed", "truth_probability_collapsed")


@dataclass(frozen=True)
class Metric:
    numerator: str
    denominator: str | None = None
    condition: tuple | None = None
    direction: str = "descriptive"

    def values(self, row):
        if self.condition and row.get(self.condition[0]) != self.condition[1]:
            return 0.0, 0.0
        value = row.get(self.numerator)
        denominator = row.get(self.denominator) if self.denominator else 1
        if value is None or denominator is None:
            return 0.0, 0.0
        if not math.isfinite(value) or not math.isfinite(denominator) or denominator < 0:
            raise ValueError("Non-finite metric or invalid denominator")
        return float(value), float(denominator)


GAME_METRICS = {
    "overall_win_rate": Metric("focal_win", direction="higher"),
    "good_win_rate": Metric("focal_win", condition=("focal_alignment", "GOOD"), direction="higher"),
    "evil_win_rate": Metric("focal_win", condition=("focal_alignment", "EVIL"), direction="higher"),
    "table_good_win_rate": Metric("good_win"), "table_evil_win_rate": Metric("evil_win"),
    "merlin_assassination_rate": Metric("merlin_assassinated"),
    "assassin_merlin_identification_accuracy": Metric("merlin_assassinated", "assassination_opportunities"),
    "focal_assassin_identification_accuracy": Metric("merlin_assassinated", "assassination_opportunities",
                                                     ("focal_role", "ASSASSIN"), "higher"),
    "good_proportion_in_proposed_teams": Metric("good_proposed_slots", "proposed_team_slots", direction="higher"),
    "evil_inclusion_in_good_led_teams": Metric("evil_in_good_led_slots", "good_led_slots", direction="lower"),
    "dirty_good_led_team_rate": Metric("dirty_good_led_teams", "good_led_teams", direction="lower"),
    "evil_inclusion_in_focal_good_led_teams": Metric("focal_good_led_evil_slots", "focal_good_led_slots", direction="lower"),
    "successful_quest_rate": Metric("successful_quests", "quest_count"),
    "failed_quest_rate": Metric("failed_quests", "quest_count"),
    "invalid_actions_per_game": Metric("invalid_actions", direction="lower"),
    "belief_engine_failures_per_game": Metric("belief_engine_failures", direction="lower"),
    "average_game_length": Metric("game_length_rounds"),
    "average_game_length_events": Metric("game_length_events"),
    "belief_latency_ms_per_observation": Metric("belief_update_ms", "belief_observations", direction="lower"),
    "average_game_seconds": Metric("game_seconds", direction="lower"),
    "average_mock_calls": Metric("mock_calls"), "average_context_bytes": Metric("context_bytes"),
}
GAME_METRICS.update({f"win_rate_role_{role}": Metric("focal_win", condition=("focal_role", role), direction="higher")
                     for role in ("GOOD", "MERLIN", "EVIL", "ASSASSIN")})
GAME_METRICS.update({f"final_{name}": Metric(f"final_{name}", direction="lower" if name in LOWER_BETTER else
                                            "higher" if name == "true_hypothesis_probability" else "descriptive")
                     for name in BELIEF_METRICS})


def _ratio(numerator, denominator):
    return float(numerator / denominator) if denominator > 0 else None


def _interval(values):
    finite = np.asarray(values)[np.isfinite(values)]
    return [float(x) for x in np.quantile(finite, [.025, .975])] if len(finite) else None


def paired_comparisons(rows, metrics, *, resamples=2000, seed=1000):
    groups = defaultdict(dict)
    for row in rows:
        if row["variant"] not in {"baseline", "joint_belief"}:
            continue
        pair = groups[row["pair_id"]]
        if row["variant"] in pair:
            raise ValueError("Duplicate variant in a pair")
        pair[row["variant"]] = row
    if not groups:
        return {}
    if any(set(pair) != {"baseline", "joint_belief"} for pair in groups.values()):
        raise ValueError("Paired comparisons require both variants for every pair")
    pairs = [groups[key] for key in sorted(groups)]
    for pair in pairs:
        if pair["baseline"].get("pair_signature") != pair["joint_belief"].get("pair_signature"):
            raise ValueError("A compared pair has different controls")
    # Identical sampled cluster indexes are used on both sides and all metrics.
    indexes = np.random.default_rng(seed % 2 ** 64).integers(0, len(pairs), size=(resamples, len(pairs)))
    result = {}
    for name, metric in metrics.items():
        a = np.asarray([metric.values(p["baseline"]) for p in pairs])
        b = np.asarray([metric.values(p["joint_belief"]) for p in pairs])
        # Missing scalar scores (e.g. projection collapse) use a common complete
        # subset. Event-rate denominators may legitimately differ by treatment.
        if metric.denominator is None:
            both = (a[:, 1] > 0) & (b[:, 1] > 0)
            a[~both] = b[~both] = 0
        av, bv = _ratio(*a.sum(axis=0)), _ratio(*b.sum(axis=0))
        ar, br = a[indexes].sum(axis=1), b[indexes].sum(axis=1)
        with np.errstate(divide="ignore", invalid="ignore"):
            boot_a, boot_b = ar[:, 0] / ar[:, 1], br[:, 0] / br[:, 1]
            boot_delta = boot_b - boot_a
        # No inferential interval is justified by one independent unit.
        eligible = int(((a[:, 1] > 0) | (b[:, 1] > 0)).sum())
        ci = _interval(boot_delta) if eligible >= 2 else None
        delta = bv - av if av is not None and bv is not None else None
        label = "unavailable"
        if ci is not None:
            sign = 1 if metric.direction == "higher" else -1
            if metric.direction == "descriptive":
                label = "descriptive"
            elif min(sign * ci[0], sign * ci[1]) > 0:
                label = "improvement_supported"
            elif max(sign * ci[0], sign * ci[1]) < 0:
                label = "decline_supported"
            else:
                label = "inconclusive"
        result[name] = {
            "baseline": av, "joint_belief": bv, "absolute_delta": delta,
            "relative_delta": delta / abs(av) if delta is not None and av != 0 else None,
            "delta_ci95": ci, "baseline_ci95": _interval(boot_a) if eligible >= 2 else None,
            "joint_belief_ci95": _interval(boot_b) if eligible >= 2 else None,
            "paired_clusters": len(pairs), "eligible_clusters": eligible,
            "baseline_denominator": float(a[:, 1].sum()), "joint_belief_denominator": float(b[:, 1].sum()),
            "valid_bootstrap_resamples": int(np.isfinite(boot_delta).sum()),
            "direction": metric.direction, "interpretation": label,
        }
    return result


def final_replay_rows(traces):
    latest = {}
    for row in traces:
        if row["phase"] == "replay" and row["decision_available"]:
            latest[(row["game_id"], row["variant"], row["observer_id"])] = row
    groups = defaultdict(list)
    for (game_id, variant, _), row in latest.items():
        groups[(game_id, variant)].append(row)
    result = []
    for (game_id, variant), rows in groups.items():
        entry = {"pair_id": game_id, "variant": variant, "seed": rows[0]["seed"], "pair_signature": game_id}
        for name in BELIEF_METRICS:
            for prefix, selected in (("", rows), ("uninformed_", [r for r in rows if r["observer_role"] == "GOOD"])):
                values = [r[name] for r in selected if r[name] is not None]
                entry[prefix + name] = math.fsum(values) / len(values) if values else None
        result.append(entry)
    return result


def trajectories(traces):
    latest = {}
    for row in traces:
        if row["phase"] == "replay" and row["decision_available"]:
            latest[(row["game_id"], row["variant"], row["observer_id"], row["round"])] = row
    buckets = defaultdict(lambda: defaultdict(list))
    for (game, variant, _, round_no), row in latest.items():
        buckets[(variant, round_no)][game].append(row)
    result = []
    for (variant, round_no), games in sorted(buckets.items()):
        entry = {"variant": variant, "round": round_no, "games": len(games)}
        for metric in BELIEF_METRICS:
            values = []
            for rows in games.values():
                x = [r[metric] for r in rows if r[metric] is not None]
                if x:
                    values.append(math.fsum(x) / len(x))
            entry[metric] = math.fsum(values) / len(values) if values else None
        result.append(entry)
    return result


def summarize(games, traces, audits, *, resamples=2000, seed=1000):
    replay_metrics = {prefix + k: Metric(prefix + k, direction="lower" if k in LOWER_BETTER else
                                       "higher" if k == "true_hypothesis_probability" else "descriptive")
                      for prefix in ("", "uninformed_") for k in BELIEF_METRICS}
    main = [r for r in games if r["phase"] == "tournament"]
    smoke = [r for r in games if r["phase"] == "smoke"]
    comparisons = paired_comparisons(main, GAME_METRICS, resamples=resamples, seed=seed)
    pathologies = {}
    for phase in ("replay", "smoke", "tournament"):
        pathologies[phase] = {}
        for variant in ("baseline", "joint_belief"):
            selected = [r for r in traces if r["phase"] == phase and r["variant"] == variant and r["decision_available"]]
            pathologies[phase][variant] = {flag: sum(r[flag] for r in selected) for flag in PATHOLOGIES}
            pathologies[phase][variant]["scored_updates"] = len(selected)
    latency = comparisons.get("belief_latency_ms_per_observation", {})
    return {
        "statistical_method": "Paired percentile bootstrap; same seed/game cluster resampled on both sides; 95% CIs",
        "bootstrap_resamples": resamples, "bootstrap_seed": seed,
        "multiple_comparisons": "Exploratory, unadjusted intervals; correlated metrics are not independent confirmations",
        "game_counts": {phase: {v: sum(r["phase"] == phase and r["variant"] == v for r in games)
                                for v in ("baseline", "joint_belief", "reference")}
                        for phase in ("replay_source", "smoke", "tournament")},
        "total_games": len(games), "failed_games": sum(r["status"] != "completed" for r in games),
        "gameplay": comparisons,
        "smoke": paired_comparisons(smoke, GAME_METRICS, resamples=resamples, seed=seed),
        "replay": paired_comparisons(final_replay_rows(traces), replay_metrics, resamples=resamples, seed=seed),
        "trajectories": trajectories(traces), "pathologies": pathologies,
        "replay_audit": {"observer_variant_checks": len(audits), "equal_streams": bool(audits),
                         "duplicate_delivery_checks_passed": bool(audits)},
        "major_latency_increase": bool(latency.get("baseline") is not None and latency.get("joint_belief") is not None
                                       and latency["joint_belief"] > max(2 * latency["baseline"], latency["baseline"] + .1)),
        "model_usage": {"external_calls": 0, "tokens": None, "cost": None,
                        "note": "Mock calls/context bytes measured; real token cost and provider latency not measured"},
    }
