"""Human-readable results and standalone plots for an offline evaluation run."""

import json
from pathlib import Path


LIMITATIONS = [
    "This is a controlled local policy ablation on the current production Game rules. It does not establish live-LLM effectiveness.",
    "Only P1 changes belief architecture in paired games. The other seats use fixed baseline beliefs and the same decision policy. Role assignments and semantic random draws are matched.",
    "The baseline is the deterministic belief component from commit 74fd078; neither variant receives model-written probability replacements. The intervening uncommitted alignment-world prototype is not a historical baseline in Git.",
    "The baseline has no native joint distribution. Its joint scores use a normalized product of its independent role estimates, restricted by initial private knowledge and public role counts. This scoring projection never feeds back into its policy or marginal scores.",
    "Brier score and binary log loss average over other seats. Unknown-target scores use initially unknown alignments; uninformed replay scores include only ordinary GOOD observers. Scores after ASSASSINATE/RESULT are excluded from final and round comparisons.",
    "True-world rank uses midranks for ties and initial legal-world-count + 1 for an eliminated truth. Entropy is in nats; lower entropy alone is not improvement. Log scores use a 1e-15 numerical floor; exported probabilities retain exact zeros.",
    "Replay gives both variants the same complete public stream, detached per observer. Terminal role reveals and individual mission submissions are excluded. There are no language interpretations in the main local evaluation; semantic-update correctness is covered by deterministic tests.",
    "Bootstrap samples whole paired seeds/games, never individual updates or seats. Conditional rates resample their numerators and denominators together. Intervals are exploratory and unadjusted for multiple comparisons. Correlated belief metrics are not independent confirmations.",
    "Round curves use each observer's last pre-terminal update in that round, average observers within games, then games. Later rounds contain surviving games only; no post-game forward filling. Smoke and reference-generation games are excluded from the larger tournament estimates.",
    "Real model tokens, inference cost, and provider latency are unmeasured. Mock calls, context bytes, game duration and focal belief-update latency are measured; scoring and duplicate audits are excluded from belief latency.",
]


def fmt(value):
    return "unavailable" if value is None else f"{value:.5f}"


def comparison_table(comparisons, keys=None):
    lines = ["| Metric | Baseline | Joint belief | Delta (joint − baseline) | 95% CI of delta | Relative delta | Evidence |",
             "|---|---:|---:|---:|---|---:|---|"]
    for key in keys or comparisons:
        if key not in comparisons:
            continue
        m = comparisons[key]
        ci = m["delta_ci95"]
        interval = f"[{fmt(ci[0])}, {fmt(ci[1])}]" if ci else "unavailable"
        relative = f"{m['relative_delta']:+.1%}" if m["relative_delta"] is not None else "unavailable"
        lines.append(f"| {key} | {fmt(m['baseline'])} | {fmt(m['joint_belief'])} | {fmt(m['absolute_delta'])} "
                     f"| {interval} | {relative} | {m['interpretation']} |")
    return lines


def interpretation(summary):
    if summary.get("status") != "completed":
        return "Evaluation incomplete: no effectiveness conclusion is justified. See phase status and errors below."
    replay, game = summary.get("replay", {}), summary.get("gameplay", {})
    improvements = [k for k, v in replay.items() if v["interpretation"] == "improvement_supported" and not k.startswith("uninformed_")]
    declines = [k for k, v in replay.items() if v["interpretation"] == "decline_supported" and not k.startswith("uninformed_")]
    lines = ["Passing correctness tests is a prerequisite, not evidence that the agents are more effective."]
    if improvements:
        lines.append("Replay intervals support improvement in: " + ", ".join(improvements) + ".")
    if declines:
        lines.append("Replay intervals support deterioration in: " + ", ".join(declines) + ".")
    if not improvements and not declines:
        lines.append("Replay comparisons do not resolve a reliable improvement or deterioration at this sample size.")
    win = game.get("overall_win_rate")
    if win:
        if win["interpretation"] == "improvement_supported":
            lines.append("The paired interval supports a higher focal-seat win rate under this controlled policy.")
        elif win["interpretation"] == "decline_supported":
            lines.append("The paired interval supports a lower focal-seat win rate under this controlled policy.")
        else:
            lines.append("The paired win-rate interval includes zero; a raw mean difference is not evidence of a win-rate improvement.")
    composition = [k for k in ("good_proportion_in_proposed_teams", "evil_inclusion_in_good_led_teams",
                              "evil_inclusion_in_focal_good_led_teams")
                   if game.get(k, {}).get("interpretation") == "improvement_supported"]
    if composition:
        lines.append("Team-composition intervals support improvement in: " + ", ".join(composition) + ".")
    adverse = [k for k in ("overall_win_rate", "good_win_rate", "evil_win_rate", "win_rate_role_MERLIN",
                          "win_rate_role_GOOD", "win_rate_role_ASSASSIN", "win_rate_role_EVIL")
               if game.get(k, {}).get("interpretation") == "decline_supported"]
    if adverse:
        lines.append("Adverse gameplay outcomes: " + ", ".join(adverse) + ".")
    lines.append("Assess the role outcomes, calibration, confidence failures and latency together. These results do not justify an unconditional claim that joint belief is better.")
    return " ".join(lines)


def write_plots(root, summary):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plot_dir = Path(root) / "plots"
    plot_dir.mkdir(exist_ok=True)
    colors = ("#66758c", "#137f78")
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False,
                         "figure.dpi": 130, "savefig.bbox": "tight"})

    def save(fig, name):
        fig.tight_layout()
        fig.savefig(plot_dir / f"{name}.png")
        plt.close(fig)

    for name, metric, section, title, ylabel in (
        ("win_rate_comparison", "overall_win_rate", "gameplay", "Paired gameplay · focal-seat win rate", "Win rate"),
        ("brier_score_comparison", "brier_score", "replay", "Fixed replay · final Brier score", "Brier score · lower is better"),
        ("log_loss_comparison", "log_loss", "replay", "Fixed replay · final binary log loss", "Log loss · lower is better"),
    ):
        fig, ax = plt.subplots(figsize=(7, 4.5))
        item = summary.get(section, {}).get(metric)
        if item and item["baseline"] is not None and item["joint_belief"] is not None:
            values = [item["baseline"], item["joint_belief"]]
            ax.bar(["Baseline", "Joint belief"], values, color=colors, width=.52)
            for i, variant in enumerate(("baseline", "joint_belief")):
                ci = item[f"{variant}_ci95"]
                if ci:
                    ax.plot([i, i], ci, color="#202b38", linewidth=1.5)
                    ax.plot([i - .06, i + .06], [ci[0]] * 2, color="#202b38")
                    ax.plot([i - .06, i + .06], [ci[1]] * 2, color="#202b38")
                label_height = max(values[i], ci[1]) if ci else values[i]
                ax.annotate(f"{values[i]:.4f}", (i, label_height), xytext=(0, 8),
                            textcoords="offset points", ha="center")
            ci = item["delta_ci95"]
            label = f"Δ = {item['absolute_delta']:+.4f}; paired 95% CI " + (f"[{ci[0]:+.4f}, {ci[1]:+.4f}]" if ci else "unavailable")
            ax.set_xlabel(label)
            ax.set_ylim(0, max(values) * 1.3 + .03)
        else:
            ax.text(.5, .5, "No completed paired data", ha="center", transform=ax.transAxes)
        ax.set_title(title, pad=16)
        ax.set_ylabel(ylabel)
        save(fig, name)

    for name, metric, title, ylabel in (
        ("true_hypothesis_probability", "true_hypothesis_probability", "True-world probability over rounds", "Probability · higher is better"),
        ("true_hypothesis_rank", "true_hypothesis_rank", "True-world rank over rounds", "Midrank · lower is better"),
        ("entropy", "entropy", "Joint entropy over rounds", "Entropy (nats) · descriptive"),
    ):
        fig, ax = plt.subplots(figsize=(7, 4.5))
        for variant, color in zip(("baseline", "joint_belief"), colors):
            rows = [r for r in summary.get("trajectories", []) if r["variant"] == variant and r[metric] is not None]
            if rows:
                ax.plot([r["round"] for r in rows], [r[metric] for r in rows], "o-", color=color,
                        label=variant.replace("_", " "))
                if variant == "joint_belief":
                    for row in rows:
                        ax.annotate(f"n={row['games']}", (row["round"], row[metric]),
                                    xytext=(0, 10), textcoords="offset points", ha="center", fontsize=8)
        ax.set_title("Fixed replay · " + title, pad=18)
        ax.set_xlabel("Round (0 = initial private knowledge); surviving games only")
        ax.set_ylabel(ylabel)
        if ax.lines:
            ax.legend()
        else:
            ax.text(.5, .5, "No completed replay data", ha="center", transform=ax.transAxes)
        ax.grid(alpha=.15)
        save(fig, name)


def write_report(root, config, summary):
    root = Path(root)
    (root / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    tests = summary.get("unit_tests", {})
    lines = ["# Joint-belief local evaluation", "", interpretation(summary), "",
             f"Run: `{root.name}` · status: **{summary.get('status', 'incomplete')}** · model: `{config['model']}` · temperature: {config['temperature']}",
             f"Correctness: {tests.get('passed', 0)} passed, {tests.get('failures', 0)} failed, {tests.get('errors', 0)} errors, {tests.get('skipped', 0)} skipped.",
             "", "## Phase results", "", "| Phase | Status | Details |", "|---|---|---|"]
    for phase in summary.get("phases", []):
        lines.append(f"| {phase['name']} | {phase['status']} | {phase.get('detail', '')} |")
    if summary.get("error"):
        lines += ["", "Error: " + summary["error"]]
    lines += ["", "## Paired gameplay", "",
              "`--games` counts pairs. Overall/Good/Evil and role win rates refer to the evaluated P1 seat against fixed opponents. "
              "Table-wide faction wins are separate descriptive metrics. A team containing both variants does not define a treatment win.",
              "", "Main-tournament game counts: `" + json.dumps(summary.get("game_counts", {}).get("tournament", {})) + "`.", ""]
    lines += comparison_table(summary.get("gameplay", {}))
    lines += ["", "Assassin accuracy is correct target / actual assassination opportunities; those opportunities can differ after treatment. "
              "Merlin assassination rate uses all games. Good/Evil slot proportions count all proposals including revisions and rejected teams. "
              "Undefined rates are unavailable, never zero. Every metric's denominators and eligible clusters are in summary.json.",
              "", "## Passive replay", "",
              "Final scores average seats within each frozen game, then games. Uninformed rows isolate ordinary GOOD observers. "
              "Joint metrics for the baseline are scoring projections; binary scores use its original marginal estimates.", ""]
    lines += comparison_table(summary.get("replay", {}))
    lines += ["", "## Confidence and failure diagnostics", "",
              "Counts below refer to pre-terminal scored checkpoints, not independent trials. Repeated confidence flags can describe the same unresolved mistake.",
              "", "| Phase / variant | Checkpoints | Entropy ↓ and truth ↓ | Confident wrong world | Confident wrong marginals | Distribution collapse | Truth ≤ 1e-15 |",
              "|---|---:|---:|---:|---:|---:|---:|"]
    for phase, variants in summary.get("pathologies", {}).items():
        for variant, values in variants.items():
            lines.append(f"| {phase} / {variant} | " + " | ".join(str(values[k]) for k in (
                "scored_updates", "entropy_down_truth_down", "overconfident_wrong_world", "overconfident_wrong_marginals",
                "distribution_collapsed", "truth_probability_collapsed")) + " |")
    lines += ["", f"- Replay equal-stream and duplicate-delivery audits: {summary.get('replay_audit', {})}.",
              f"- Failed games: {summary.get('failed_games', 0)}. Failures are retained and block phase promotion.",
              f"- Major measured belief-latency increase (>2× and >0.1 ms): {summary.get('major_latency_increase', False)}.",
              "- Private-information and post-game-reveal isolation: see named deterministic tests in unit_tests.xml. These test the harness boundaries; they cannot certify arbitrary model behavior.",
              "- Projection collapse is retained as missing joint scores and flagged; it never resets a baseline prior. Exact zero truth probability is retained and penalized in log scoring.",
              "", "## Scope and definitions", ""]
    lines += [f"- {item}" for item in LIMITATIONS]
    lines += ["", "## Reproduction", "", "```sh", config["reproduce_command"], "```", "",
              "config.json records source hashes, the Git commit and dirty state, dependency versions, seed lists, all likelihood values, "
              "the baseline rules, policy settings, and response/replay inputs. source/ contains the evaluated Python sources; "
              "replays.jsonl preserves the exact frozen corpus. Stage-specific seeds and outputs are separate.", "",
              "## Plots", ""]
    for name in ("win_rate_comparison", "brier_score_comparison", "log_loss_comparison", "true_hypothesis_probability",
                 "true_hypothesis_rank", "entropy"):
        lines += [f"![{name.replace('_', ' ')}](plots/{name}.png)", ""]
    (root / "report.md").write_text("\n".join(lines) + "\n")
