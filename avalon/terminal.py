"""Human input, public event rendering, and the complete terminal game loop."""

import argparse
from contextlib import ExitStack
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
import sys

from .agents import Agent
from .engine import CARDS, DIRECTIONS, EVIL_ROLES, Game, REASONS, make_players
from .evil_strategy import EvilStrategyManager
from .llm import ChatClient, LLMError, Settings


class QuitGame(Exception):
    pass


class Human:
    def __init__(self, view, input_fn=input, write=print):
        self.id, self.role = view["self"], view["role"]
        self.ids = [p["id"] for p in view["players"]]
        self.known_evil = set(view["known_evil"])
        self.input_fn, self.write = input_fn, write

    def _ask(self, prompt):
        while True:
            try:
                value = self.input_fn(prompt).strip().upper()
            except (EOFError, KeyboardInterrupt):
                raise QuitGame from None
            if value in {"Q", "QUIT", "EXIT"}:
                raise QuitGame
            if value in {"HELP", "?"}:
                self.write("选队：1 3 或 P1 P3；出牌：ACCUSE/DEFEND/HEDGE/PRESSURE/BAIT + 座位；"
                           "投票：y/n；任务：s/f；回车采用提示默认值；q 退出。")
                continue
            return value

    @staticmethod
    def _seat(value):
        return value if value.startswith("P") else "P" + value

    def reveal(self):
        side = "邪恶" if self.role in EVIL_ROLES else "善良"
        self.write(f"[PRIVATE · 仅你可见] {self.id} 身份：{self.role}（{side}阵营）")
        if self.known_evil:
            self.write("[PRIVATE · 仅你可见] 已知邪恶座位：" + " ".join(sorted(self.known_evil)))
        self.write("输入 help 查看操作；输入 q 可随时退出。")

    def choose_team(self, size, attempt=1):
        default = [self.id] + [p for p in self.ids if p != self.id][:size-1]
        while True:
            value = self._ask(f"[{self.id}] 选队 {size} 人（回车={' '.join(default)}）> ")
            team = [self._seat(p) for p in value.replace(",", " ").replace("，", " ").split()] if value else default
            if len(team) == size and len(set(team)) == size and all(p in self.ids for p in team):
                return team
            self.write(f"请输入 {size} 个不同的有效座位，例如 {' '.join(default)}。")

    def social_action(self):
        default_target = next(p for p in self.ids if p != self.id)
        while True:
            value = self._ask(f"[{self.id}] 出牌 {'/'.join(CARDS)} + 目标（回车=HEDGE {default_target}）> ")
            parts = value.split() if value else ["HEDGE", default_target]
            if len(parts) == 2 and parts[0] in CARDS and self._seat(parts[1]) in self.ids:
                return {"card": parts[0], "target": self._seat(parts[1]), "reason": "human_choice"}
            self.write("输入卡牌和有效座位，例如 PRESSURE P3。")

    def vote(self, team, attempt):
        while True:
            value = self._ask(f"[{self.id}] 赞成队伍 {' '.join(team)}？y/n（回车=y）> ")
            if value in {"", "Y", "YES", "A", "APPROVE"}:
                return True
            if value in {"N", "NO", "R", "REJECT"}:
                return False
            self.write("请输入 y（赞成）或 n（反对）。")

    def mission(self):
        if self.role not in EVIL_ROLES:
            self.write("[PRIVATE · 仅你可见] 善良阵营自动提交 SUCCESS。")
            return "SUCCESS"
        while True:
            value = self._ask(f"[PRIVATE/{self.id}] 秘密任务票 s=成功 / f=失败（回车=s）> ")
            if value in {"", "S", "SUCCESS"}:
                return "SUCCESS"
            if value in {"F", "FAIL"}:
                return "FAIL"
            self.write("请输入 s 或 f。")

    def assassinate(self):
        candidates = [p for p in self.ids if p not in self.known_evil and p != self.id]
        while True:
            value = self._ask(f"[{self.id}] 刺杀 Merlin：{'/'.join(candidates)}（回车={candidates[0]}）> ")
            target = self._seat(value) if value else candidates[0]
            if target in candidates:
                return target
            self.write("请选择一个合法的善良阵营座位。")


def format_event(event, players):
    kind = event["kind"]
    actor = event.get("actor")
    tag = f"[{players[actor].name}/{actor}]" if actor else ""
    if kind == "START":
        return "[PLAYERS] " + " | ".join(f"{p['id']} {p['name']}" for p in event["players"])
    if kind == "LEADER":
        return f"[LEADER] {tag} 随机当选首任队长"
    if kind == "DIRECTION":
        direction = "顺时针（座位号递增）" if event["direction"] == "clockwise" else "逆时针（座位号递减）"
        return f"[DIRECTION] 本局{direction}发言；每次提案由队长开始。"
    if kind == "ROUND":
        return (f"\n[ROUND {event['round']}/5] 任务人数 {event['team_size']} | "
                f"善良 {event['successes']} : 邪恶 {event['failures']} | 队长 {event['leader']}")
    if kind == "TEAM":
        return (f"[TEAM] {tag} selects {' '.join(event['team'])} | 提案 {event['attempt']}/5\n"
                f"[SPEAKING ORDER] {' -> '.join(event['speaking_order'])}")
    if kind == "SOCIAL":
        label = f"[SOCIAL] {tag} {event['card']} {event['target']}"
        if "statement" not in event:
            return f"{label} | reason: {REASONS[event['reason']]}"
        evidence = ", ".join(f"#{seq}" for seq in event["evidence"]) or "试探性观点，未引用历史记录"
        return (f"{label} | 表态：{event['statement']}\n"
                f"  理由摘要：{event['rationale']} | 公开依据：{evidence}")
    if kind == "VOTE":
        return f"[VOTE] {tag} votes {'APPROVE' if event['approve'] else 'REJECT'} | reason: {REASONS[event['reason']]}"
    if kind == "TEAM_VOTE":
        yes = sum(event["votes"].values())
        return f"[TEAM VOTE] {yes}/{len(players)} 赞成 -> {'通过' if event['approved'] else '否决，队长轮换'}"
    if kind == "MISSION_SUBMIT":
        return f"[MISSION SUBMIT] {tag} 已提交秘密任务票"
    if kind == "MISSION":
        return (f"[MISSION] {' '.join(event['team'])} -> {'SUCCESS' if event['success'] else 'FAILED'} | "
                f"失败票 {event['fail_count']}，成功票 {len(event['team'])-event['fail_count']} | "
                f"善良 {event['successes']} : 邪恶 {event['failures']}")
    if kind == "ASSASSINATION_PHASE":
        return "[ASSASSIN] 三次任务成功；刺客现在选择 Merlin。身份尚未揭晓。"
    if kind == "ASSASSINATE":
        return f"[ASSASSIN] {tag} targets {event['target']}"
    if kind == "RESULT":
        reasons = {"five_rejections": "连续五次提案被否决", "three_failed_missions": "三次任务失败",
                   "merlin_assassinated": "Merlin 被刺杀", "merlin_survived": "Merlin 成功存活"}
        return f"\n[RESULT] {event['winner']} WINS | {reasons[event['reason']]}"
    if kind == "REVEAL":
        return "[REVEAL] " + " | ".join(f"{p} {role}" for p, role in event["roles"].items())
    raise ValueError(f"Unknown public event: {kind}")


def run_game(game, agents, human=None, write=print, log=None, dossier=False, *,
             strategy_manager=None, strategy_seed=None, debug_write=None, strategy_log=None):
    """Normal play has one Human. Passing only agents is explicit demo/test mode."""
    if set(agents) | ({human.id} if human else set()) != set(game.ids):
        raise ValueError("Every seat requires a controller.")
    evil_ids = {p.id for p in game.players.values() if p.role in EVIL_ROLES}
    controlled_evil = evil_ids & set(agents)
    manager = strategy_manager or EvilStrategyManager(game.ids, evil_ids, seed=strategy_seed,
                                                       controlled_evil_ids=controlled_evil)
    if set(manager.evil_ids) != evil_ids or set(manager.controlled_evil_ids) != controlled_evil:
        raise ValueError("The strategy manager must match this game's evil AI seats")
    for pid in controlled_evil:
        agents[pid].bind_evil_strategy(manager)
    cursor = 0
    strategy_cursor = 0

    def debug_strategy(label, record):
        if debug_write is None:
            return
        snapshot = manager.debug_snapshot()
        fields = ("strategy_mode", "aggressor_agent_id", "sleeper_agent_id", "roles",
                  "primary_target", "secondary_target", "sacrifice_target", "mission_fail_owner",
                  "likely_merlin", "merlin_probabilities", "pair_suspicion", "distance_strength",
                  "active_narratives", "agenda_topic")
        summary = {key: snapshot[key] for key in fields if key in snapshot}
        debug_write(f"[PRIVATE DEBUG] {label}\n"
                    + json.dumps({"decision": record, "state": summary}, ensure_ascii=False,
                                 allow_nan=False, indent=2))

    def flush_strategy():
        nonlocal strategy_cursor
        for decision in manager.decisions[strategy_cursor:]:
            record = asdict(decision)
            if strategy_log is not None:
                strategy_log.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
                strategy_log.flush()
            # Development output has a separate sink and is never broadcast to agents.
            debug_strategy("EVIL STRATEGY UPDATE", record)
        strategy_cursor = len(manager.decisions)

    def flush():
        nonlocal cursor
        for event in game.events[cursor:]:
            write(f"[#{event['seq']}] {format_event(event, game.players).lstrip()}")
            if log is not None:
                log.write(json.dumps(event, ensure_ascii=False, allow_nan=False) + "\n")
                log.flush()
            manager.observe(deepcopy(event))
            for agent in agents.values():
                agent.observe(deepcopy(event))
        cursor = len(game.events)
        # Accepted SOCIAL events, not model attempts, create discussion decisions.
        flush_strategy()

    def controller(pid):
        if pid in agents:
            agents[pid].update_view(game.view(pid))
        return human if human is not None and pid == human.id else agents[pid]

    def prepare_agent(pid):
        def report_retry(error, retry_no, delay):
            write(f"[RETRY] [{game.players[pid].name}/{pid}] 调用失败（{error.public_code}），"
                  f"{delay:g} 秒后重试（{retry_no}/{agents[pid].max_retries}）…")
            if debug_write is not None:
                debug_write(f"[PRIVATE DEBUG] LLM RETRY {pid}: {error}")
        view = game.view(pid)
        if pid in controlled_evil:
            tactic = manager.tactical_context(view).to_dict()
            planned = {key: tactic[key] for key in
                       ("strategy_mode", "role", "primary_objective", "secondary_objective", "primary_target")}
            debug_strategy("EVIL TACTICAL PLAN", {"status": "planned", "agent_id": pid,
                           "round": game.round, "attempt": game.attempt, "phase": game.phase, **planned})
        try:
            agents[pid].prepare(view, on_retry=report_retry)
        except LLMError as error:
            if debug_write is not None:
                debug_write(f"[PRIVATE DEBUG] LLM STOP {pid}: {error}")
            raise

    flush()
    if human is not None:
        human.reveal()
    while game.winner is None:
        round_no = game.round
        while game.phase in {"team", "discussion", "mission"} and game.round == round_no:
            leader = game.leader
            if leader in agents:
                write(f"[AGENT] [{game.players[leader].name}/{leader}] 正在准备队伍…")
                if leader not in controlled_evil:
                    prepare_agent(leader)
            game.propose(leader, controller(leader).choose_team(game.team_size, game.attempt))
            flush_strategy()
            flush()
            for pid in game.speaking_order:
                if pid in agents:
                    write(f"[TURN] [{game.players[pid].name}/{pid}] 正在调用 LLM 准备发言…")
                    # The previous speaker's event is flushed before taking this fresh view.
                    prepare_agent(pid)
                game.social(pid, controller(pid).social_action())
                flush()
            votes = {pid: controller(pid).vote(list(game.team), game.attempt) for pid in game.ids}
            flush_strategy()
            reasons = {pid: "human_choice" if human and pid == human.id else
                       "last_chance" if game.attempt == 5 else "team_risk" for pid in game.ids}
            game.vote(votes, reasons)
            flush()
            if game.phase == "mission":
                external_cards = ({human.id: human.mission()}
                                  if human and human.role in EVIL_ROLES and human.id in game.team else {})
                evil_view = game.view(next(p for p in game.ids if p in controlled_evil))
                managed_cards = manager.mission_cards(evil_view, external_cards=external_cards)
                cards = {pid: external_cards[pid] if pid in external_cards else
                         managed_cards[pid] if pid in managed_cards else controller(pid).mission()
                         for pid in game.team}
                flush_strategy()
                game.resolve_mission(cards)
                flush()
        for agent in agents.values():
            agent.record_snapshot(round_no, human.id if human else "P1")
        if game.phase == "assassination":
            assassin = next(p.id for p in game.players.values() if p.role == "ASSASSIN")
            game.assassinate(assassin, controller(assassin).assassinate())
            flush_strategy()
            flush()

    for pid, agent in agents.items():
        counts = ", ".join(f"R{r}={agent.calls.get(r, 0)}" for r in sorted(agent.sources))
        write(f"[CALLS] [{game.players[pid].name}/{pid}] HTTP 尝试 {sum(agent.calls.values())} | {counts}")
    if dossier:
        write("\n[DOSSIER] 赛后模型摘要：仅本局行为估计，不包含模型内部思维。P1 是观察对象。")
        for pid, agent in agents.items():
            for snapshot in agent.snapshots:
                profile, belief = snapshot["profile"], snapshot["belief"]
                social = snapshot["social"]
                strategy_text = f"strategy={snapshot['strategy']} | " if agent.evil_strategy is None else ""
                write(f"[DOSSIER] {game.players[pid].name}/{pid} R{snapshot['round']} | "
                      f"P1 evil={belief['evil']:.2f} | aggression={profile['aggression']:.2f} "
                      f"retaliation={profile['retaliation']:.2f} approval={profile['approval']:.2f} | "
                      f"{strategy_text}{social['card']} {social['target']}")
                write("  近期公开依据：" + json.dumps(snapshot["evidence"][-2:], ensure_ascii=False))
    return game


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Terminal Avalon：1 位人类 + LLM agents，自动读取模型配置并轮流发言。")
    parser.add_argument("--players", type=int, choices=(5, 6), default=5, help="总人数，默认 5")
    parser.add_argument("--name", default="YOU", help="人类 P1 昵称")
    parser.add_argument("--demo", action="store_true", help="自动演示：P1 也由 agent 控制，无人类输入")
    parser.add_argument("--seed", type=int, help="固定发牌、首任队长与发言方向，便于复现；默认随机")
    parser.add_argument("--direction", choices=DIRECTIONS, help="顺时针 clockwise / 逆时针 counterclockwise；默认开局随机决定")
    parser.add_argument("--env-file", type=Path, help="显式 dotenv 文件路径")
    parser.add_argument("--log", type=Path, help="保存公开 JSONL 事件（包含赛后身份揭晓）")
    parser.add_argument("--dossier", action="store_true", help="结束后显示 AI 对 P1 的行为画像变化")
    parser.add_argument("--debug-strategy", action="store_true",
                        help="开发者专用：将邪恶内部战略输出到 stderr；会显示隐藏信息")
    parser.add_argument("--strategy-log", type=Path, help="开发者专用：另存私有结构化战略 JSONL")
    args = parser.parse_args(argv)
    write = lambda value: print(value, flush=True)
    write("=== TERMINAL AVALON ===")
    write("[MODE] 自动演示（无真人）" if args.demo else "[MODE] 1 位人类 P1 + 其余 AI agents")
    try:
        settings = Settings.load(args.env_file)
    except (ValueError, OSError):
        write("[CONFIG] 配置无效，无法启动。请检查 .env.example 中的地址和参数格式。")
        return 1
    if settings.notice:
        write("[CONFIG] " + settings.notice)
    if not settings.ready:
        missing = [name for name, value in (("OPENAI_API_KEY", settings.api_key),
                                            ("OPENAI_MODEL", settings.model)) if not value]
        write("[CONFIG] 缺少 " + "、".join(missing)
              + "。请复制 .env.example 为 .env 并填入配置，或设置对应环境变量后重新启动。")
        return 1
    try:
        client = ChatClient(settings)
    except LLMError:
        write("[CONFIG] 无法加载腐化城堡提示词，请检查 prompts/corrupted_castle_system.md 是否存在且为非空 UTF-8 文本。")
        return 1
    write("[BACKEND] LLM；每位 agent 按发言顺序实时生成回应")
    write("[WORLD] 腐化城堡；角色为自身存活交涉，外出寻找生存物资")
    name = "".join(c for c in args.name if c.isprintable()).strip()[:24] or "YOU"
    game = Game(make_players(args.players, args.seed, name), seed=args.seed, direction=args.direction)
    human = None if args.demo else Human(game.view("P1"), write=write)
    agents = {p: Agent(game.view(p), client, max_retries=settings.max_retries, retry_delay=settings.retry_delay)
              for p in game.ids if human is None or p != human.id}
    try:
        protected_envs = {Path(__file__).resolve().parents[1] / ".env"}
        protected_envs.add(client.world_prompt_path.resolve())
        if args.env_file:
            protected_envs.add(args.env_file.resolve())
        paths = [path.resolve() for path in (args.log, args.strategy_log) if path]
        if len(paths) != len(set(paths)) or any(path in protected_envs for path in paths):
            write("[CONFIG] 公开日志、私有战略日志、环境配置和场景提示词必须使用不同文件。")
            return 1
        with ExitStack() as stack:
            logs = []
            for path in (args.log, args.strategy_log):
                if path:
                    path.parent.mkdir(parents=True, exist_ok=True)
                logs.append(stack.enter_context(path.open("w", encoding="utf-8")) if path else None)
            debug_write = (lambda value: print(value, file=sys.stderr, flush=True)) if args.debug_strategy else None
            run_game(game, agents, human, write, logs[0], dossier=args.dossier,
                     strategy_seed=args.seed, debug_write=debug_write, strategy_log=logs[1])
    except (QuitGame, KeyboardInterrupt):
        write("\n[EXIT] 已退出对局。")
    except LLMError as error:
        write(f"[ERROR] LLM 调用失败（{error.public_code}），对局已停止。请检查模型配置或网络后重新启动。")
        return 1
    except OSError:
        write("[ERROR] 无法写入公开日志，请检查 --log 路径与权限。")
        return 1
    return 0
