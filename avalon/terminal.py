"""Human input, public event rendering, and the complete terminal game loop."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from copy import deepcopy
import json
from pathlib import Path
import sys

from .agents import Agent
from .engine import CARDS, EVIL_ROLES, Game, REASONS, make_players
from .llm import ChatClient, Settings


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
    if kind == "ROUND":
        return (f"\n[ROUND {event['round']}/5] 任务人数 {event['team_size']} | "
                f"善良 {event['successes']} : 邪恶 {event['failures']} | 队长 {event['leader']}")
    if kind == "TEAM":
        return f"[TEAM] {tag} selects {' '.join(event['team'])} | 提案 {event['attempt']}/5"
    if kind == "SOCIAL":
        return f"[SOCIAL] {tag} {event['card']} {event['target']} | reason: {REASONS[event['reason']]}"
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


def run_game(game, agents, human=None, write=print, log=None, concurrency=1, dossier=False):
    """Normal play has one Human. Passing only agents is explicit demo/test mode."""
    if set(agents) | ({human.id} if human else set()) != set(game.ids):
        raise ValueError("Every seat requires a controller.")
    cursor = 0

    def flush():
        nonlocal cursor
        for event in game.events[cursor:]:
            write(format_event(event, game.players))
            if log is not None:
                log.write(json.dumps(event, ensure_ascii=False, allow_nan=False) + "\n")
                log.flush()
            for agent in agents.values():
                agent.observe(deepcopy(event))
        cursor = len(game.events)

    def controller(pid):
        return human if human is not None and pid == human.id else agents[pid]

    flush()
    if human is not None:
        human.reveal()
    while game.winner is None:
        round_no = game.round
        jobs = [(pid, agent, game.view(pid)) for pid, agent in agents.items()]
        if any(agent.client is not None for agent in agents.values()):
            write(f"[SYSTEM] {len(agents)} 个 agent 正在形成本轮策略；每位最多一次请求。")
        # Each worker has a separate Agent, memory and input snapshot. Print in seat order.
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = [(pid, pool.submit(agent.prepare, view)) for pid, agent, view in jobs]
            for pid, future in futures:
                source = future.result()
                write(f"[AGENT] [{game.players[pid].name}/{pid}] 本轮决策来源：{source}")

        while game.phase in {"team", "discussion", "mission"} and game.round == round_no:
            leader = game.leader
            game.propose(leader, controller(leader).choose_team(game.team_size, game.attempt))
            flush()
            start = game.ids.index(leader)
            for pid in game.ids[start:] + game.ids[:start]:
                game.social(pid, controller(pid).social_action())
                flush()
            votes = {pid: controller(pid).vote(list(game.team), game.attempt) for pid in game.ids}
            reasons = {pid: "human_choice" if human and pid == human.id else
                       "last_chance" if game.attempt == 5 else "team_risk" for pid in game.ids}
            game.vote(votes, reasons)
            flush()
            if game.phase == "mission":
                cards = {pid: controller(pid).mission() for pid in game.team}
                game.resolve_mission(cards)
                flush()
        for agent in agents.values():
            agent.record_snapshot(round_no, human.id if human else "P1")
        if game.phase == "assassination":
            assassin = next(p.id for p in game.players.values() if p.role == "ASSASSIN")
            game.assassinate(assassin, controller(assassin).assassinate())
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
                write(f"[DOSSIER] {game.players[pid].name}/{pid} R{snapshot['round']} | "
                      f"P1 evil={belief['evil']:.2f} | aggression={profile['aggression']:.2f} "
                      f"retaliation={profile['retaliation']:.2f} approval={profile['approval']:.2f} | "
                      f"strategy={snapshot['strategy']} | {social['card']} {social['target']}")
                write("  近期公开依据：" + json.dumps(snapshot["evidence"][-2:], ensure_ascii=False))
    return game


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Terminal Avalon：1 位人类 + LLM agents，支持离线试玩。")
    parser.add_argument("--players", type=int, choices=(5, 6), default=5, help="总人数，默认 5")
    parser.add_argument("--name", default="YOU", help="人类 P1 昵称")
    parser.add_argument("--mock", action="store_true", help="强制 deterministic agents；不读 .env、不访问网络")
    parser.add_argument("--demo", action="store_true", help="自动演示：P1 也由 agent 控制，无人类输入")
    parser.add_argument("--seed", type=int, help="固定发牌与首任队长，便于复现；默认随机")
    parser.add_argument("--env-file", type=Path, help="显式 dotenv 文件路径")
    parser.add_argument("--log", type=Path, help="保存公开 JSONL 事件（包含赛后身份揭晓）")
    parser.add_argument("--dossier", action="store_true", help="结束后显示 AI 对 P1 的行为画像变化")
    args = parser.parse_args(argv)
    write = lambda value: print(value, flush=True)
    write("=== TERMINAL AVALON ===")
    write("[MODE] 自动演示（无真人）" if args.demo else "[MODE] 1 位人类 P1 + 其余 AI agents")
    settings = Settings()
    if not args.mock:
        try:
            settings = Settings.load(args.env_file)
        except (ValueError, OSError):
            write("[CONFIG] 配置无效，已切换 deterministic/mock；请检查 .env.example。")
    if settings.notice:
        write("[CONFIG] " + settings.notice)
    client = ChatClient(settings) if settings.ready and not args.mock else None
    write("[BACKEND] LLM；异常时自动 fallback" if client else "[BACKEND] deterministic/mock（无需 API）")
    name = "".join(c for c in args.name if c.isprintable()).strip()[:24] or "YOU"
    game = Game(make_players(args.players, args.seed, name), seed=args.seed)
    human = None if args.demo else Human(game.view("P1"), write=write)
    agents = {p: Agent(game.view(p), client) for p in game.ids if human is None or p != human.id}
    try:
        if args.log:
            args.log.parent.mkdir(parents=True, exist_ok=True)
        with args.log.open("w", encoding="utf-8") if args.log else nullcontext() as log:
            run_game(game, agents, human, write, log, settings.concurrency, args.dossier)
    except (QuitGame, KeyboardInterrupt):
        write("\n[EXIT] 已退出对局。")
    except OSError:
        write("[ERROR] 无法写入公开日志，请检查 --log 路径与权限。")
        return 1
    return 0
