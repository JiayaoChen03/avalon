"""Run correctness → frozen replay → paired smoke → larger paired tournament.

python -m avalon.eval.joint_belief --games 500 --seed 1000 \
    --variants baseline,joint_belief --output-dir results/joint_belief
"""

import argparse
from concurrent.futures import ProcessPoolExecutor
import csv
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

from avalon.evidence import LikelihoodConfig
from avalon.engine import CARDS, MAX_RESOLVE, RESOLVE_COSTS, TEAM_SIZES, mission_rules
from dataclasses import asdict

from .beliefs import BASELINE_COMMIT, BASELINE_CONFIG
from .reporting import interpretation, write_plots, write_report
from .simulation import POLICY_CONFIG, canonical, load_replays, play_game, replay_game, run_pair
from .statistics import summarize


ROOT = Path(__file__).resolve().parents[2]
CORRECTNESS_TESTS = ("tests/test_joint_beliefs.py", "tests/test_cognition.py",
                     "tests/eval/test_eval_correctness.py", "tests/eval/test_eval_harness.py")


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


class CSVOutput:
    def __init__(self, path, minimum_fields):
        self.path, self.fields = Path(path), list(minimum_fields)
        self.stream, self.writer = None, None
        # Even a gated failure has readable, empty artifacts.
        with self.path.open("w", newline="") as stream:
            csv.writer(stream).writerow(self.fields)

    def append(self, rows):
        for row in rows:
            if self.writer is None:
                self.fields = list(dict.fromkeys(self.fields + list(row)))
                self.stream = self.path.open("w", newline="")
                self.writer = csv.DictWriter(self.stream, fieldnames=self.fields)
                self.writer.writeheader()
            extra = [key for key in row if key not in self.fields]
            if extra:
                # A replay corpus may mix 5/6 seats or use custom player IDs.
                # Extend marginal columns without losing earlier checkpoints.
                self.stream.close()
                with self.path.open(newline="") as old:
                    previous = list(csv.DictReader(old))
                self.fields.extend(extra)
                self.stream = self.path.open("w", newline="")
                self.writer = csv.DictWriter(self.stream, fieldnames=self.fields)
                self.writer.writeheader()
                self.writer.writerows(previous)
            self.writer.writerow(row)
        if self.stream:
            self.stream.flush()

    def close(self):
        if self.stream:
            self.stream.close()


def git_info():
    def git(*args):
        result = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False)
        return result.stdout.strip() if result.returncode == 0 else None
    return {"commit": git("rev-parse", "HEAD"), "dirty_status": git("status", "--short")}


def snapshot_sources(output):
    paths = sorted(set(ROOT.glob("avalon/**/*.py")) | set(ROOT.glob("tests/**/*.py")) |
                   {ROOT / "pyproject.toml", ROOT / "requirements.txt"})
    hashes = {}
    for source in paths:
        if not source.is_file():
            continue
        relative = source.relative_to(ROOT)
        hashes[str(relative)] = hashlib.sha256(source.read_bytes()).hexdigest()
        target = output / "source" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    return hashes


def run_correctness(output):
    xml = output / "unit_tests.xml"
    command = [sys.executable, "-m", "pytest", "-q", *CORRECTNESS_TESTS, f"--junitxml={xml}"]
    env = {**os.environ, "PYTHONHASHSEED": "0", "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
    with (output / "unit_tests.log").open("w") as log:
        result = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, env=env, check=False)
    if not xml.exists():
        suite = ET.Element("testsuite", name="evaluation", tests="1", errors="1", failures="0", skipped="0")
        case = ET.SubElement(suite, "testcase", name="pytest_execution")
        ET.SubElement(case, "error", message="pytest failed to produce JUnit XML; see unit_tests.log")
        ET.ElementTree(suite).write(xml, encoding="utf-8", xml_declaration=True)
    document = ET.parse(xml).getroot()
    suites = [document] if document.tag == "testsuite" else list(document.iter("testsuite"))
    counts = {key: sum(int(s.get(key, 0)) for s in suites) for key in ("tests", "failures", "errors", "skipped")}
    counts["passed"] = counts["tests"] - counts["failures"] - counts["errors"] - counts["skipped"]
    counts["exit_code"] = result.returncode
    return counts


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--games", type=int, default=500, help="Number of pairs in the larger tournament (2 games each)")
    parser.add_argument("--seed", type=int, default=1000)
    parser.add_argument("--variants", default="baseline,joint_belief", help="Both variants; order may be reversed")
    parser.add_argument("--model", choices=("controlled-v1", "fixture-v1"), default="controlled-v1")
    parser.add_argument("--temperature", type=float, default=0)
    parser.add_argument("--output-dir", type=Path, default=Path("results/joint_belief"))
    parser.add_argument("--run-id", help="Optional unique run directory name")
    parser.add_argument("--players", type=int, choices=(5, 6), default=5)
    parser.add_argument("--smoke-games", type=int, default=20, help="Smoke pairs, with disjoint seeds")
    parser.add_argument("--replay-games", type=int, default=20, help="Frozen reference games generated before replay")
    parser.add_argument("--replay-file", type=Path, help="Completed game envelopes in JSONL; see docs/joint-belief-evaluation.md")
    parser.add_argument("--mode", choices=("all", "replay"), default="all")
    parser.add_argument("--responses", type=Path, help="JSON mapping of decision keys to controlled responses for fixture-v1")
    parser.add_argument("--likelihood-config", type=Path, help="JSON with language, behavioral and confidence dictionaries")
    parser.add_argument("--bootstrap-resamples", type=int, default=2000)
    parser.add_argument("--workers", type=int, default=1, help="Independent local pair workers; 1 gives cleaner timing measurements")
    return parser


def validate_args(args, parser):
    args.variants = args.variants.split(",")
    if len(args.variants) != 2 or set(args.variants) != {"baseline", "joint_belief"}:
        parser.error("--variants must contain baseline and joint_belief exactly once")
    if min(args.games, args.smoke_games, args.replay_games, args.workers, args.bootstrap_resamples) < 1:
        parser.error("Game counts, workers, and bootstrap resamples must be positive")
    if not 0 <= args.temperature < float("inf"):
        parser.error("--temperature must be finite and nonnegative")
    if bool(args.responses) != (args.model == "fixture-v1"):
        parser.error("fixture-v1 requires --responses; controlled-v1 does not consume a response file")
    if args.run_id and (not re.fullmatch(r"[A-Za-z0-9_.-]+", args.run_id) or args.run_id in {".", ".."}):
        parser.error("--run-id must be a simple directory name")


def execute(args):
    timestamp = datetime.now(timezone.utc)
    run_id = args.run_id or timestamp.strftime("%Y%m%dT%H%M%S%fZ") + f"-seed{args.seed}"
    output = args.output_dir.resolve() / run_id
    output.mkdir(parents=True, exist_ok=False)
    (output / "plots").mkdir()
    games_file = CSVOutput(output / "games.csv", ("game_id", "seed", "phase", "variant", "status"))
    trace_file = CSVOutput(output / "belief_trace.csv", ("game_id", "seed", "round", "event_id", "variant",
        "true_hypothesis_probability", "true_hypothesis_rank", "brier_score", "log_loss", "entropy", "remaining_hypotheses"))
    games, traces, audits, phases = [], [], [], []
    tests, status, error = {}, "failed", None
    # Contiguous nonoverlapping seed ranges, even for very large requested runs.
    seeds = list(range(args.seed, args.seed + args.games))
    smoke_seeds = list(range(args.seed + args.games, args.seed + args.games + args.smoke_games))
    replay_seeds = list(range(args.seed + args.games + args.smoke_games,
                              args.seed + args.games + args.smoke_games + args.replay_games))
    hashes = snapshot_sources(output)
    config = {
        "schema_version": 1, "timestamp": timestamp.isoformat(), "run_id": run_id, "git": git_info(),
        "model": args.model, "temperature": args.temperature, "game_count": args.games,
        "game_count_unit": "paired seeds (two physical games per seed)", "players": args.players,
        "seeds": seeds, "smoke_seeds": smoke_seeds, "replay_seeds": replay_seeds,
        "variants": args.variants, "mode": args.mode, "workers": args.workers,
        "bootstrap_resamples": args.bootstrap_resamples, "bootstrap_seed": args.seed,
        "policy": POLICY_CONFIG, "baseline": {"source_commit": BASELINE_COMMIT, **BASELINE_CONFIG},
        "game_rules": {**mission_rules(args.players, 1), "team_sizes": TEAM_SIZES[args.players], "max_proposals": 5,
                       "role_counts": {"GOOD": args.players - 3, "MERLIN": 1, "ASSASSIN": 1, "EVIL": 1}},
        "resources": {"cards": CARDS, "max_resolve": MAX_RESOLVE, "costs": RESOLVE_COSTS},
        "joint_belief": {"class": "avalon.cognition.BeliefEngine", "likelihoods_tuned_on_evaluation": False},
        "python": sys.version, "platform": platform.platform(),
        "dependencies": {p: version(p) for p in ("pytest", "matplotlib", "numpy", "python-dotenv")},
        "source_sha256": hashes, "unit_test_files": list(CORRECTNESS_TESTS),
        "reproduce_command": shlex.join([sys.executable, "-m", "avalon.eval.joint_belief", "--games", str(args.games),
            "--seed", str(args.seed), "--variants", ",".join(args.variants), "--model", args.model,
            "--temperature", str(args.temperature), "--players", str(args.players), "--smoke-games", str(args.smoke_games),
            "--replay-games", str(args.replay_games), "--bootstrap-resamples", str(args.bootstrap_resamples),
            "--workers", str(args.workers), "--mode", args.mode, "--output-dir", str(args.output_dir.resolve())]
            + (["--replay-file", str(output / "replays.jsonl")] if args.replay_file else [])
            + (["--responses", str(output / "responses.json")] if args.responses else [])
            + (["--likelihood-config", str(output / "likelihood_config.json")] if args.likelihood_config else [])),
    }
    write_json(output / "config.json", config)
    settings = None

    def phase(name, detail):
        phases.append({"name": name, "status": "running", "detail": detail})
        print(f"{name}: {detail}", flush=True)

    def completed(detail):
        phases[-1].update(status="passed", detail=detail)
        print(f"  passed: {detail}", flush=True)

    def tournament(name, selected_seeds):
        phase(name, f"{len(selected_seeds)} paired seeds")
        tasks = [(seed, name, settings) for seed in selected_seeds]
        pool = ProcessPoolExecutor(max_workers=args.workers) if args.workers > 1 else None
        results = pool.map(run_pair, tasks) if pool else map(run_pair, tasks)
        try:
            for index, pair in enumerate(results, 1):
                for game_row, game_trace in pair:
                    games.append(game_row)
                    traces.extend(game_trace)
                    games_file.append([game_row])
                    trace_file.append(game_trace)
                if any(row["status"] != "completed" for row, _ in pair):
                    raise ValueError(f"{name} pair {index} failed: " + "; ".join(row["error"] for row, _ in pair if row["error"]))
                if index % 10 == 0 or index == len(tasks):
                    print(f"  {name}: {index}/{len(tasks)} pairs completed", flush=True)
        finally:
            if pool:
                pool.shutdown(wait=True, cancel_futures=True)
        completed(f"{len(selected_seeds)} pairs; no invalid actions or belief-engine failures")

    try:
        likelihood = LikelihoodConfig(**json.loads(args.likelihood_config.read_text())) if args.likelihood_config else LikelihoodConfig()
        responses = json.loads(args.responses.read_text()) if args.responses else None
        if responses is not None and not isinstance(responses, dict):
            raise ValueError("Controlled responses must be a JSON object")
        config["likelihood_parameters"] = asdict(likelihood)
        write_json(output / "likelihood_config.json", asdict(likelihood))
        if responses is not None:
            write_json(output / "responses.json", responses)
            config["responses_sha256"] = hashlib.sha256(args.responses.read_bytes()).hexdigest()
        settings = {"variants": args.variants, "players": args.players, "temperature": args.temperature,
                    "model": args.model, "responses": responses, "likelihood": likelihood}
        write_json(output / "config.json", config)
        phase("correctness", "deterministic pytest suite; no live LLM calls")
        tests = run_correctness(output)
        if tests["exit_code"] != 0 or tests["failures"] or tests["errors"]:
            raise ValueError("Deterministic tests failed; later phases were not started (see unit_tests.log)")
        completed(f"{tests['passed']} tests passed; {tests['skipped']} skipped")

        phase("replay", "completed games, equal observations for both variants")
        records = load_replays(args.replay_file) if args.replay_file else []
        if not records:
            for seed in replay_seeds:
                row, _, record = play_game(seed, "reference", phase="replay_source", players=args.players,
                                          temperature=args.temperature, likelihood=likelihood)
                games.append(row)
                games_file.append([row])
                if row["status"] != "completed":
                    raise ValueError("Frozen reference game failed: " + row["error"])
                records.append(record)
        with (output / "replays.jsonl").open("w") as stream:
            for record in records:
                stream.write(canonical(record) + "\n")
        config["replay_game_count"] = len(records)
        config["replay_seeds"] = [r["seed"] for r in records]
        config["replay_corpus_sha256"] = hashlib.sha256((output / "replays.jsonl").read_bytes()).hexdigest()
        config["replay_origin"] = str(args.replay_file.resolve()) if args.replay_file else "static-knowledge controlled-v1 reference policy"
        write_json(output / "config.json", config)
        for index, record in enumerate(records, 1):
            replay_trace, checks = replay_game(record, args.variants, likelihood)
            traces.extend(replay_trace)
            trace_file.append(replay_trace)
            audits.extend(checks)
            print(f"  replay: {index}/{len(records)} games completed", flush=True)
        write_json(output / "replay_audit.json", audits)
        completed(f"{len(records)} frozen games; {len(audits)} equal-stream/duplicate checks")
        if args.mode == "all":
            tournament("smoke", smoke_seeds)
            tournament("tournament", seeds)
        changed = [p for p, sha in hashes.items() if not (ROOT / p).exists()
                   or hashlib.sha256((ROOT / p).read_bytes()).hexdigest() != sha]
        if changed:
            raise ValueError("Sources changed during evaluation; use archived source/: " + ", ".join(changed))
        status = "completed"
    except (ValueError, TypeError, KeyError, RuntimeError, OSError) as exc:
        error = f"{type(exc).__name__}: {exc}"
        if phases:
            phases[-1]["status"] = "failed"
        print(error, file=sys.stderr, flush=True)
    finally:
        games_file.close()
        trace_file.close()
    if not (output / "unit_tests.xml").exists():
        suite = ET.Element("testsuite", name="evaluation", tests="1", errors="0", failures="0", skipped="1")
        case = ET.SubElement(suite, "testcase", name="correctness_phase_not_started")
        ET.SubElement(case, "skipped", message=error or "Correctness phase was not started")
        ET.ElementTree(suite).write(output / "unit_tests.xml", encoding="utf-8", xml_declaration=True)
    # Summary/report always survive a deterministic gate or a recorded game failure.
    summary = summarize(games, traces, audits, resamples=args.bootstrap_resamples, seed=args.seed)
    summary.update(status=status, error=error, phases=phases, unit_tests=tests,
                   elapsed_seconds=(datetime.now(timezone.utc) - timestamp).total_seconds())
    summary["interpretation"] = interpretation(summary)
    write_plots(output, summary)
    write_report(output, config, summary)
    print(f"Tests: {tests.get('passed', 0)} passed, {tests.get('failures', 0)} failed, {tests.get('errors', 0)} errors", flush=True)
    for filename in ("report.md", "games.csv", "belief_trace.csv", "summary.json"):
        print(f"{filename}: {output / filename}", flush=True)
    for section, metrics in (("gameplay", ("overall_win_rate", "good_win_rate", "evil_win_rate")),
                             ("replay", ("brier_score", "log_loss", "true_hypothesis_probability"))):
        for name in metrics:
            if name in summary[section]:
                m = summary[section][name]
                print(f"{section}/{name}: baseline={m['baseline']} joint={m['joint_belief']} "
                      f"delta={m['absolute_delta']} CI95={m['delta_ci95']}", flush=True)
    return output, summary


def main(argv=None):
    supplied = list(sys.argv[1:] if argv is None else argv)
    if "--suite" in supplied:
        index = supplied.index("--suite")
        if index + 1 >= len(supplied) or supplied[index + 1] != "joint_v2":
            raise SystemExit("Supported explicit suite: joint_v2 (omit --suite for the historical CLI)")
        del supplied[index:index + 2]
        from .v2.runner import main as v2_main
        v2_main(supplied)
        return 0
    parser = build_parser()
    args = parser.parse_args(argv)
    validate_args(args, parser)
    _, summary = execute(args)
    return 0 if summary["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
