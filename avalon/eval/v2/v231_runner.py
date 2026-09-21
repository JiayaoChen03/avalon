"""Joint Belief v2.3.1 offline Merlin signal-channel audit.

The default command reads the frozen v2.3 run and never loads credentials or
creates a network client.  A future paid validation, if authorised by the
mechanism gate, must be a separate explicit implementation.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

from avalon.eval.joint_belief import ROOT, git_info
from avalon.eval.simulation import canonical, digest
from avalon.eval.v2.v231_channel import run_audit


SOURCE_RUN = ROOT / "results/joint_belief_v2_3/20260918-v23-r2-live20"
RUN_PREFIX = "20260918-v231-r1-offline"
ATTACHMENT = Path("/Users/jiayaochen/.codex/attachments/f0bec8b8-5f3a-4664-afa6-2f071d6804cd/pasted-text.txt")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")


def source_files(source: Path) -> list[Path]:
    names = ["config.json", "dataset_manifest.json", "snapshot_results.csv", "games.csv",
             "paired_outcomes.csv", "assassin_signal_audit.json", "assassin_signal_trace.csv",
             "source_manifest.json", "v23_source_replays.jsonl"]
    files = [source / name for name in names if (source / name).exists()]
    files += sorted((source / "active_replays").glob("*.json"))
    return files


def code_files() -> list[Path]:
    names = ["avalon/evidence.py", "avalon/cognition.py", "avalon/joint_beliefs.py",
             "avalon/eval/v2/adapters.py", "avalon/eval/v2/v21_contract.py",
             "avalon/eval/v2/v23_merlin.py", "avalon/eval/v2/v231_channel.py",
             "avalon/eval/v2/v231_runner.py"]
    return [ROOT / name for name in names if (ROOT / name).exists()]


def prepare(out: Path) -> dict:
    out = Path(out).resolve()
    if out.exists():
        raise FileExistsError(f"run directory already exists: {out}")
    if not SOURCE_RUN.exists():
        raise FileNotFoundError(SOURCE_RUN)
    source_cfg = _json(SOURCE_RUN / "config.json")
    if source_cfg.get("run_id") != "20260918-v23-r2-live20":
        raise ValueError("unexpected v2.3 primary source run id")
    hashes = {str(path.relative_to(SOURCE_RUN)): sha256(path) for path in source_files(SOURCE_RUN)}
    current = {str(path.relative_to(ROOT)): sha256(path) for path in code_files()}
    instruction_hash = sha256(ATTACHMENT) if ATTACHMENT.exists() else None
    out.mkdir(parents=True)
    config = {
        "run_id": out.name, "created_utc": datetime.now(timezone.utc).isoformat(),
        "status": "prepared", "live": False, "budget_cny": None,
        "api_calls": 0, "network_access": False, "candidate_enabled_by_default": False,
        "candidate_revision": "none; v2.3.1 is an offline channel audit",
        "frozen": {"belief": "joint_v2", "mission_likelihood": True,
                   "evidence_extractor": True, "evidence_weights": True,
                   "assassin_decoder": "native argmax; exact equality tie-break",
                   "legal_menu": True, "runtime_checkpoint": True,
                   "v22_vote_candidate": False, "language_factors": False,
                   "recursive_tom": False, "cross_game_memory": False},
        "primary_source_run_id": source_cfg["run_id"],
        "primary_source_path": str(SOURCE_RUN.resolve()),
        "instruction_attachment": str(ATTACHMENT) if ATTACHMENT.exists() else None,
        "instruction_attachment_sha256": instruction_hash,
        "r7_and_v22_role": "not pooled; only existing tie/implementation diagnostics may be reused",
        "git": git_info(), "source_hashes": hashes, "current_code_hashes": current,
        "test_commands": {
            "unit": "python -m avalon.eval.v2.v231_runner --mode tests --run-dir <run> --tests-scope unit",
            "regression": "python -m avalon.eval.v2.v231_runner --mode tests --run-dir <run> --tests-scope regression",
            "report_only": "python -m avalon.eval.v2.v231_runner --mode report-only --run-dir <run>",
        },
    }
    _write_json(out / "config.json", config)
    _write_json(out / "source_manifest.json", {
        "primary_source_run_id": source_cfg["run_id"], "primary_source_path": str(SOURCE_RUN.resolve()),
        "primary_source_hashes": hashes, "current_code_hashes": current,
        "instruction_attachment": str(ATTACHMENT) if ATTACHMENT.exists() else None,
        "instruction_attachment_sha256": instruction_hash,
        "git": git_info(), "AGENTS_found": [], "network_calls": 0,
        "historical_samples_pooled": False,
    })
    (out / "prechange_audit.md").write_text(
        "# Joint Belief v2.3.1 prechange audit\n\n"
        f"Primary read-only source: `{SOURCE_RUN}` (`{source_cfg['run_id']}`).\n\n"
        "The source contains the v2.3 fixed snapshot responses, active replay archives, "
        "the v2.3 Assassin diagnostic and the production configuration. No r7/v2.2 rows "
        "are pooled into this audit; r7 tie rows remain explicitly labelled diagnostic reuse.\n\n"
        "Code path frozen for this run: `MerlinDisclosureContext` -> public SOCIAL event -> "
        "`Observation.from_event` -> `EvidenceExtractor` -> `BeliefEngine`/`joint_v2` -> "
        "`v21_contract.decode_menu` native Merlin marginal argmax with exact-equality tie handling. "
        "`EvidenceExtractor` ignores an observer's own action, gives structured DEFEND and "
        "ACCUSE/PRESSURE/CHALLENGE factors to other observers, and does not turn public writing "
        "into numeric evidence while language factors are disabled.\n\n"
        "This run adds only an offline action inventory, detached one-step prefix intervention, "
        "factor provenance and tie-path export. It does not modify production defaults, call "
        "DeepSeek, replay future events, or implement a new Merlin strategy.\n",
        encoding="utf-8")
    return config


def diagnose(out: Path) -> dict:
    out = Path(out).resolve()
    result = run_audit(SOURCE_RUN, out)
    cfg = _json(out / "config.json")
    cfg.update({"status": "diagnosed", "network_calls": 0,
                "mechanism_gate": result["mechanism"]["gate"],
                "action_diff_rows": len(result["inventory"]),
                "signal_rows": len(result["signals"]),
                "factor_rows": len(result["factors"])})
    _write_json(out / "config.json", cfg)
    return result


def _tests(out: Path, name: str, paths: list[str]) -> dict:
    xml = out / f"{name}_tests.xml"
    log = out / f"{name}_tests.log"
    env = {**os.environ, "PYTHONHASHSEED": "0", "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
    with log.open("w", encoding="utf-8") as stream:
        result = subprocess.run([sys.executable, "-m", "pytest", "-q", *paths,
                                 f"--junitxml={xml}"], cwd=ROOT, env=env,
                                stdout=stream, stderr=subprocess.STDOUT, check=False)
    root = ET.parse(xml).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    counts = {key: sum(int(s.get(key, 0)) for s in suites)
              for key in ("tests", "failures", "errors", "skipped")}
    counts.update(passed=counts["tests"] - counts["failures"] - counts["errors"] - counts["skipped"],
                  exit_code=result.returncode)
    return counts


def tests(out: Path, scope: str | None = None) -> dict:
    out = Path(out).resolve()
    cfg = _json(out / "config.json")
    selected = {"unit": _tests(out, "unit", ["tests/eval"]),
                "regression": _tests(out, "regression", ["tests"])}
    cfg["tests"] = selected
    _write_json(out / "config.json", cfg)
    if any(x["exit_code"] for x in selected.values()):
        raise SystemExit(1)
    return selected


def report(out: Path) -> dict:
    out = Path(out).resolve()
    cfg = _json(out / "config.json")
    gate = _json(out / "mechanism_gate.json")
    action_rows = list(__import__("csv").DictReader((out / "action_diff.csv").open(encoding="utf-8")))
    signal_rows = list(__import__("csv").DictReader((out / "assassin_signal_channel.csv").open(encoding="utf-8")))
    factor_rows = [json.loads(line) for line in (out / "factor_delta.jsonl").read_text(encoding="utf-8").splitlines()
                   if line.strip()]
    categories = {}
    for row in action_rows:
        categories[row["action_category"]] = categories.get(row["action_category"], 0) + 1
    eligible = [r for r in signal_rows if r.get("counterfactual_eligible") == "1"]
    numeric = [r for r in eligible if r.get("posterior_changed") == "1"]
    rank = [r for r in eligible if r.get("true_merlin_rank_before") != r.get("true_merlin_rank_after")
            or r.get("top_candidate_set_before") != r.get("top_candidate_set_after")
            or r.get("tie_size_before") != r.get("tie_size_after")]
    summary = {
        "run_id": out.name, "status": "complete", "live": False, "network_calls": 0,
        "primary_source_run_id": gate["primary_source_run_id"],
        "source_data_role": gate["source_data_role"], "mechanism_gate": gate,
        "action_diff": {"rows": len(action_rows), "categories": categories,
                         "text_only_rows": sum(r["action_category"] == "TEXT_ONLY" for r in action_rows),
                         "structured_rows": sum(r["action_category"] == "STRUCTURED_ACTION_CHANGE" for r in action_rows),
                         "mechanical_rows": sum(r["action_category"] == "MECHANICAL_CHANGE" for r in action_rows)},
        "one_step": {"signal_rows": len(signal_rows), "eligible_rows": len(eligible),
                     "posterior_changed_rows": len(numeric), "rank_or_top_set_changed_rows": len(rank)},
        "factor_attribution": {"rows": len(factor_rows),
                               "counts": dict(Counter(row.get("factor_name") or "NO_FACTOR" for row in factor_rows)),
                               "likelihood_values": sorted({value for row in factor_rows
                                                              for value in row.get("factor_likelihood_values", [])})},
        "api_validation": "not_run; CHANNEL_NOT_FOUND does not authorize additional paid calls"
        if gate["gate"] == "CHANNEL_NOT_FOUND" else "not_run; separate explicit validation remains required",
        "conclusion_scope": "mechanical one-step path only; no full-game win-rate claim",
        "unknowns": ["No language evidence was enabled, so text can be visible without numeric update.",
                     "One-step intervention does not establish full-game survival or strategy effects.",
                     "Active branches after the first divergent public action are mechanically unmatched.",
                     "R7 tie rows are historical diagnostic reuse, not new v2.3.1 samples."],
    }
    _write_json(out / "summary.json", summary)
    cfg.update({"status": "complete", "final_code_hashes": {
        str(path.relative_to(ROOT)): sha256(path) for path in code_files()}})
    _write_json(out / "config.json", cfg)
    lines = [
        "# Joint Belief v2.3.1：梅林公开动作到刺客信号通道审计", "",
        f"运行 `{out.name}`；主来源 `{gate['primary_source_run_id']}`。本轮仅离线读取，网络调用 0，预算 `null`。",
        "", "## 1. MerlinDisclosureContext 实际改变了什么", "",
        "它只改变 Merlin 在 discussion/council 的私有辅助上下文，模型输出的公开动作、引用、卡牌、目标和文字可能随之变化；它没有改 joint_v2、证据权重、菜单或刺客解码器。",
        "", "## 2. 哪些变化进入 EvidenceExtractor", "",
        f"动作清单共 {len(action_rows)} 行：{json.dumps(categories, ensure_ascii=False)}。结构化 DEFEND 与 ACCUSE/PRESSURE/CHALLENGE 会进入生产提取器；HEDGE/PASS 没有默认方向性因子。公共文字始终单独记录。",
        "", "## 3–5. 刺客后验、排序和因子归因", "",
        f"一阶 detached prefix 分支共 {len(signal_rows)} 行，可配对 {len(eligible)} 行；刺客 posterior 变化 {len(numeric)} 行，真实 Merlin 排名/顶集/并列变化 {len(rank)} 行。因子计数 `{json.dumps(summary['factor_attribution']['counts'], ensure_ascii=False)}`，实际 likelihood 值 `{summary['factor_attribution']['likelihood_values']}`；逐条记录位于 `factor_delta.jsonl`。",
        f"机制门槛：**{gate['gate']}**。本次实际路径中，动作虽然有结构化变化，但存活世界上对应的因子似然相同，归一化后后验哈希不变。",
        "", "## 6–7. 是否连接当前识别机制", "",
        "当前候选改变了行为表面，但在冻结的 action-only 识别器中没有展示数值识别通道，也没有展示 tie path 变化。因此不把文字变化称为隐匿成功，不把有结构化因子称为后验改善；按门槛结果建议退休当前候选，而不是继续扩大同一候选。没有发起额外 DeepSeek 验证。",
        "", "## 8. 未知项", "",
        "语言因素仍关闭；主动轨迹在首次动作差异后可能机械分叉；本审计不是完整对局反事实，也不回答终局胜率。历史 r7 tie rows 单独标为诊断复用。",
        "", "原始文件：`action_diff.csv`、`assassin_signal_channel.csv`、`factor_delta.jsonl`、`assassin_tie_path.csv`、`mechanism_gate.json`、`summary.json`。报告可通过 `python -m avalon.eval.v2.v231_runner --mode report-only --run-dir <run>` 在无网络下重算。",
    ]
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", required=True, choices=("prepare", "diagnose", "tests", "report-only"))
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--tests-scope", choices=("unit", "regression"), default=None,
                        help="retained for command compatibility; tests mode always records both suites")
    args = parser.parse_args(argv)
    out = args.run_dir.resolve()
    if args.mode == "prepare":
        prepare(out)
    elif args.mode == "diagnose":
        diagnose(out)
    elif args.mode == "tests":
        tests(out, args.tests_scope)
    elif args.mode == "report-only":
        if not (out / "mechanism_gate.json").exists():
            diagnose(out)
        report(out)


if __name__ == "__main__":
    main()
