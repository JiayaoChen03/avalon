"""Human input, public event rendering, and the complete terminal game loop."""

import argparse
from contextlib import ExitStack
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
import sys

from .agents import Agent
from .engine import CARDS, DIRECTIONS, EVIL_ROLES, Game, REASONS, RESOLVE_COSTS, make_players
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
        self._view = deepcopy(view)

    def update_view(self, view):
        self._view = deepcopy(view)

    def show_resolve(self):
        current, maximum = self._view["resolve"][self.id], self._view["max_resolve"]
        self.write(f"[{self.id}] RESOLVE {'●' * current}{'○' * (maximum-current)} ({current}/{maximum})")

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
                           "PASS [0]；SOCIAL [1]；COMMIT ACCUSE P3 [2]；CHALLENGE P3 #编号 [1]；"
                           "CITE #编号 [1]；HOLD [1]，之后 REACT 卡牌 座位 [0] 或 SKIP [0]；"
                           "挑战回应 RESPOND 卡牌 座位 [1] / DECLINE [0]；"
                           "LOCK [0] / REVISE P3 P2 [1]；投票 A/R 或 y/n [0]，SA/SR [1]；"
                           "任务 s/f；回车始终免费（PASS / SKIP / DECLINE / LOCK / 普通赞成）；q 退出。"
                           "每任务轮 3 Resolve，提案否决不恢复。")
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
        self.show_resolve()
        default = [self.id] + [p for p in self.ids if p != self.id][:size-1]
        while True:
            value = self._ask(f"[{self.id}] 选队 {size} 人（回车={' '.join(default)}）> ")
            team = [self._seat(p) for p in value.replace(",", " ").replace("，", " ").split()] if value else default
            if len(team) == size and len(set(team)) == size and all(p in self.ids for p in team):
                return team
            self.write(f"请输入 {size} 个不同的有效座位，例如 {' '.join(default)}。")

    def social_action(self):
        """Explicit card input retained for callers; empty input means no action."""
        menu = (f"SOCIAL [1] {'/'.join(CARDS)} + 目标"
                if self._view["resolve"][self.id] >= RESOLVE_COSTS["SOCIAL"] else "PASS [0]")
        while True:
            value = self._ask(f"[{self.id}] {menu}（回车=PASS [0]）> ")
            if not value or value in {"PASS", "SILENCE"}:
                return None
            social = self._parse_social(value.split())
            if social and self._view["resolve"][self.id] >= RESOLVE_COSTS["SOCIAL"]:
                return social
            self.write("输入卡牌和有效座位，例如 PRESSURE P3。")

    def _parse_social(self, parts):
        if len(parts) == 2 and parts[0] in CARDS and self._seat(parts[1]) in self.ids:
            return {"card": parts[0], "target": self._seat(parts[1]), "reason": "human_choice"}
        return None

    def discussion_action(self):
        self.show_resolve()
        legal = self._view["legal_actions"]
        labels = {"COMMITTED_SOCIAL": "COMMIT"}
        menu = " / ".join(f"{labels.get(k, k)} [{RESOLVE_COSTS[k]}]" for k in legal)
        while True:
            value = self._ask(f"[{self.id}] {menu}（回车=PASS）> ")
            parts = value.split()
            if not parts or value in {"PASS", "SILENCE"}:
                return {"kind": "PASS"}
            kind = {"COMMIT": "COMMITTED_SOCIAL"}.get(parts[0], parts[0])
            social_parts = parts[1:]
            if parts[0] in CARDS:
                kind, social_parts = "SOCIAL", parts
            if kind not in legal:
                self.write("请选择当前可用行动；回车免费 PASS。")
                continue
            if kind in {"SOCIAL", "COMMITTED_SOCIAL"}:
                social = self._parse_social(social_parts)
                if social:
                    return {"kind": kind, "social": social}
            elif kind == "HOLD" and len(parts) == 1:
                return {"kind": kind}
            elif kind in {"CITE", "CHALLENGE"} and len(parts) == (2 if kind == "CITE" else 3):
                try:
                    seq = int(parts[-1].lstrip("#"))
                except ValueError:
                    pass
                else:
                    action = {"kind": kind, "evidence": seq}
                    if kind == "CHALLENGE":
                        action["target"] = self._seat(parts[1])
                    return action
            self.write("示例：ACCUSE P3 / COMMIT DEFEND P2 / CHALLENGE P3 #7 / CITE #7 / HOLD。")

    def window_action(self):
        self.show_resolve()
        legal = self._view["legal_actions"]
        free = "DECLINE" if self._view["phase"] == "challenge" else "SKIP"
        paid = "RESPOND" if free == "DECLINE" else "REACT"
        menu = " / ".join(f"{k} [{RESOLVE_COSTS[k]}]" for k in legal)
        while True:
            value = self._ask(f"[{self.id}] {menu} + 卡牌 目标（回车={free}）> ")
            if not value or value == free:
                return {"kind": free}
            parts = value.split()
            if paid in legal and parts[0] == paid:
                social = self._parse_social(parts[1:])
                if social:
                    return {"kind": paid, "social": social}
            self.write(f"输入 {free} 或可用的 {paid} PRESSURE P2。")

    def revise_team(self):
        self.show_resolve()
        can_revise = "REVISE" in self._view["legal_actions"]
        menu = "LOCK [0] / REVISE 移除座位 加入座位 [1]" if can_revise else "LOCK [0]"
        while True:
            value = self._ask(f"[{self.id}] {menu}（回车=LOCK）> ")
            if not value or value == "LOCK":
                return {"kind": "LOCK"}
            parts = value.split()
            if can_revise and len(parts) == 3 and parts[0] == "REVISE":
                return {"kind": "REVISE", "removed": self._seat(parts[1]), "added": self._seat(parts[2])}
            self.write("请输入 LOCK 或合法的单人替换。")

    def vote(self, team, attempt):
        return self.ballot(team, attempt)["approve"]

    def ballot(self, team, attempt):
        self.show_resolve()
        can_strong = self._view["resolve"][self.id] >= RESOLVE_COSTS["STRONG_VOTE"]
        menu = "A 赞成 / R 反对 [0]" + (" / SA 强赞成 / SR 强反对 [1]" if can_strong else "")
        while True:
            value = self._ask(f"[{self.id}] 队伍 {' '.join(team)}：{menu}（回车=A）> ")
            if value in {"", "Y", "YES", "A", "APPROVE"}:
                return {"approve": True, "strong": False}
            if value in {"N", "NO", "R", "REJECT"}:
                return {"approve": False, "strong": False}
            if can_strong and value in {"SA", "SR", "STRONG APPROVE", "STRONG REJECT"}:
                return {"approve": value in {"SA", "STRONG APPROVE"}, "strong": True}
            self.write("请选择当前可用投票；普通赞成 / 反对免费。")

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
    payment = (f" | Resolve -{event['resolve_cost']} → {event['resolve_after']}"
               if "resolve_cost" in event else "")
    if kind == "RESOLVE_REFRESH":
        return f"[RESOLVE REFRESH] 全员恢复 {event['max_resolve']} Resolve"
    if kind == "PASS":
        return f"[PASS] {tag}{payment}"
    if kind == "HOLD":
        return f"[HOLD] {tag} 预留一次稍后回应{payment}"
    if kind == "CITE":
        return f"[CITE] {tag} 提请关注 #{event['evidence']}{payment}"
    if kind == "CHALLENGE":
        return f"[CHALLENGE] {tag} 要求 {event['target']} 回应公开记录 #{event['evidence']}{payment}"
    if kind == "CHALLENGE_RESPONSE" and event["declined"]:
        return f"[CHALLENGE_RESPONSE] {tag} DECLINED CHALLENGE from {event['challenger']}{payment}"
    if kind == "REACTION_SKIP":
        return f"[REACTION_SKIP] {tag} 暂不回应 #{event['trigger']}{payment}"
    if kind == "DISCUSSION_END":
        expired = " ".join(event["expired_reactions"])
        return "[DISCUSSION END] 讨论结束" + (f"；未用 HOLD 到期：{expired}" if expired else "")
    if kind == "TEAM_LOCK":
        return f"[TEAM_LOCK] {tag} {' '.join(event['team'])}{payment}"
    if kind == "TEAM_REVISE":
        return (f"[TEAM_REVISE] {tag} {event['removed']} -> {event['added']} | "
                f"{' '.join(event['team'])}{payment}")
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
    if kind in {"SOCIAL", "REACT", "CHALLENGE_RESPONSE"}:
        commit = "COMMITTED " if event.get("committed") else ""
        label = f"[{kind}] {tag} {commit}{event['card']} {event['target']}{payment}"
        if "statement" not in event:
            return f"{label} | reason: {REASONS[event['reason']]}"
        return (f"{label}\n"
                f"  表态：{event['statement']}\n"
                f"  理由摘要：{event['rationale']}")
    if kind == "VOTE":
        strong = "STRONG " if event.get("strong") else ""
        return f"[VOTE] {tag} votes {strong}{'APPROVE' if event['approve'] else 'REJECT'} | reason: {REASONS[event['reason']]}{payment}"
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
        seat = human if human is not None and pid == human.id else agents[pid]
        seat.update_view(game.view(pid))
        return seat

    def prepare_agent(pid, *, window=False):
        def report_retry(error, retry_no, delay):
            write(f"[RETRY] [{game.players[pid].name}/{pid}] 调用失败（{error.public_code}），"
                  f"{delay:g} 秒后重试（{retry_no}/{agents[pid].max_retries}）…")
            if debug_write is not None:
                debug_write(f"[PRIVATE DEBUG] LLM RETRY {pid}: {error.diagnostic}")
        view = game.view(pid)
        if pid in controlled_evil:
            tactic = manager.tactical_context(view, phase="discussion" if window else None).to_dict()
            planned = {key: tactic[key] for key in
                       ("strategy_mode", "role", "primary_objective", "secondary_objective", "primary_target")}
            debug_strategy("EVIL TACTICAL PLAN", {"status": "planned", "agent_id": pid,
                           "round": game.round, "attempt": game.attempt, "phase": game.phase, **planned})
        try:
            if window:
                return controller(pid).window_action(on_retry=report_retry)
            agents[pid].prepare(view, on_retry=report_retry)
        except LLMError as error:
            if debug_write is not None:
                debug_write(f"[PRIVATE DEBUG] LLM STOP {pid}: {error.diagnostic}")
            raise

    def take_action(pid, choose):
        while True:
            action = choose()
            try:
                game.act(pid, action)
            except ValueError as error:
                if pid in agents:
                    raise LLMError("invalid_plan") from None
                write(f"[INVALID] {error}；未消耗 Resolve。")
            else:
                flush()
                return

    flush()
    if human is not None:
        human.reveal()
    while game.winner is None:
        round_no = game.round
        while game.phase in {"team", "discussion", "challenge", "reaction", "revision", "vote", "mission"} and game.round == round_no:
            leader = game.leader
            if game.phase == "team":
                if leader in agents:
                    write(f"[AGENT] [{game.players[leader].name}/{leader}] 正在准备队伍…")
                    if leader not in controlled_evil:
                        prepare_agent(leader)
                game.propose(leader, controller(leader).choose_team(game.team_size, game.attempt))
                flush()
            elif game.phase == "discussion":
                pid = game.next_actor
                if pid in agents:
                    write(f"[TURN] [{game.players[pid].name}/{pid}] 正在调用 LLM 准备发言…")
                    prepare_agent(pid)
                take_action(pid, lambda: controller(pid).discussion_action())
            elif game.phase in {"challenge", "reaction"}:
                pid = game.next_actor
                take_action(pid, lambda: prepare_agent(pid, window=True) if pid in agents else controller(pid).window_action())
            elif game.phase == "revision":
                take_action(leader, lambda: controller(leader).revise_team())
            elif game.phase == "vote":
                # No engine mutation or public flush until EVERY sealed ballot is collected.
                ballots = {pid: controller(pid).ballot(list(game.team), game.attempt) for pid in game.ids}
                reasons = {pid: "human_choice" if human and pid == human.id else
                           "last_chance" if game.attempt == 5 else "team_risk" for pid in game.ids}
                game.vote({p: b["approve"] for p, b in ballots.items()}, reasons,
                          strong={p: b["strong"] for p, b in ballots.items()})
                flush()
            elif game.phase == "mission":
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
                action = snapshot["discussion"]
                action_text = (f"{social['card']} {social['target']}" if not action or action["kind"] == "SOCIAL"
                               else action["kind"])
                if action and action.get("committed"):
                    action_text = "COMMITTED " + action_text
                strategy_text = f"strategy={snapshot['strategy']} | " if agent.evil_strategy is None else ""
                write(f"[DOSSIER] {game.players[pid].name}/{pid} R{snapshot['round']} | "
                      f"P1 evil={belief['evil']:.2f} | aggression={profile['aggression']:.2f} "
                      f"retaliation={profile['retaliation']:.2f} approval={profile['approval']:.2f} | "
                      f"{strategy_text}{action_text}")
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
                        help="开发者专用：将内部战略和校验原因输出到 stderr；会显示隐藏信息")
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
        if error.public_code == "invalid_plan":
            write("[ERROR] 模型返回内容未通过行动校验（invalid_plan），对局已停止。"
                  "开发排查可使用 --debug-strategy 查看校验原因。")
        else:
            write(f"[ERROR] LLM 调用失败（{error.public_code}），对局已停止。请检查模型配置或网络后重新启动。")
        return 1
    except OSError:
        write("[ERROR] 无法写入公开日志，请检查 --log 路径与权限。")
        return 1
    return 0
