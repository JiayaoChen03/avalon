"""Local Godot adapter. Rules, cognition, and evil strategy remain in their modules.

Only the external model client is injectable for tests. Normal play always uses
the existing configured ChatClient; failures never invent replacement AI moves.
"""

from collections import OrderedDict
from copy import deepcopy

from .agents import Agent
from .chronicle import new_chronicle_path
from .engine import (CARDS, DISCUSSION_ACTIONS, EVIDENCE_KINDS, EVIL_ROLES, EXILE_CHOICES,
                     MAX_RESOLVE, RESOLVE_COSTS, Game, make_players, public_evidence)
from .evil_strategy import EvilStrategyManager
from .llm import ChatClient, LLMError, Settings


PHASES = {"team": "TEAM_DRAFT", "discussion": "DISCUSSION", "challenge": "CHALLENGE_RESPONSE",
          "reaction": "REACTION", "revision": "TEAM_CONFIRM", "vote": "VOTE",
          "mission": "MISSION", "assassination": "ASSASSINATION", "ended": "GAME_OVER",
          "council_discussion": "COUNCIL_DISCUSSION", "exile_nomination": "EXILE_NOMINATION",
          "exile_vote": "EXILE_VOTE", "council_result": "EXILE_RESULT"}
# Public action summaries exclude prose and private objects. Accepted public speech
# has its own narrow projection below, never a serialized Agent plan.
PUBLIC_FIELDS = {"seq", "kind", "round", "attempt", "actor", "target", "team", "card",
                 "committed", "evidence", "resolve_cost", "resolve_after", "approve", "strong",
                 "votes", "approved", "success", "fail_count", "successes", "failures",
                 "removed", "added", "trigger", "challenger", "challenge", "declined",
                 "expired_reactions", "resolve", "max_resolve", "leader", "team_size",
                 "direction", "speaking_order", "order", "winner", "reason", "record_id",
                 "public_writing", "citations", "life", "cause", "origin_record", "related_records", "nominated_by",
                 "safe_round", "discussion_stage", "choice", "counts", "exiled", "required_approvals", "mission_record"}
EXILE_LABELS = {"APPROVE": "赞成", "REJECT": "反对", "ABSTAIN": "弃票"}
CARD_LABELS = {"ACCUSE": "指控", "DEFEND": "辩护", "HEDGE": "保留判断",
               "PRESSURE": "施压", "BAIT": "试探"}
WIN_REASONS = {"three_failed_missions": "三次任务失败。",
               "five_rejections": "连续五次提案被否决。",
               "merlin_assassinated": "梅林被刺杀。", "merlin_survived": "梅林躲过了刺杀。"}
AI_ERRORS = {"invalid_plan": "AI 返回了无效行动", "timeout": "AI 请求超时",
             "connection_error": "无法连接 AI 服务", "invalid_response": "AI 返回格式无效",
             "empty_response": "AI 返回了空内容", "truncated_response": "AI 回复不完整",
             "response_too_large": "AI 回复过长", "refusal": "AI 服务未生成行动",
             "content_filtered": "AI 服务未生成行动", "world_prompt_unavailable": "无法读取游戏提示词",
             "http_401": "AI 服务认证失败，请检查密钥配置", "http_403": "没有访问 AI 服务的权限",
             "http_404": "找不到配置的 AI 服务或模型", "http_429": "AI 服务请求过于频繁或额度不足"}


class GameSession:
    human = "P1"

    def __init__(self, client_factory=None, *, developer_mode=False, merlin_vote_policy="baseline",
                 ai_diagnostic_sink=None):
        if merlin_vote_policy not in {"baseline", "v5"}:
            raise ValueError("Unknown Merlin vote policy")
        self.client_factory = client_factory
        self.developer_mode = developer_mode
        self.merlin_vote_policy = merlin_vote_policy
        self.ai_diagnostic_sink = ai_diagnostic_sink
        self.game = None
        self.client = None
        self.agent_options = {}
        self.seed = None
        self.player_count = None
        self.revision = 0
        self.gate = None
        self.result = None
        self.error = ""
        self.ai_error = False
        self.notice = ""
        self.requests = OrderedDict()

    def start(self, count=5, seed=None):
        if type(count) is not int or count not in (5, 6):
            raise ValueError("Choose 5 or 6 players")
        if seed is not None and (type(seed) is not int or abs(seed) > 2147483647):
            raise ValueError("Seed must be a whole number between -2147483647 and 2147483647")
        if self.client_factory is None:
            settings = Settings.load()
            if not settings.ready:
                raise LLMError("missing_configuration")
            client = ChatClient(settings)
            options = {"max_retries": settings.max_retries, "retry_delay": settings.retry_delay}
        else:
            client, options = self.client_factory(), {"max_retries": 0, "retry_delay": 0}
        game = Game(make_players(count, seed), seed=seed,
                    chronicle_path=new_chronicle_path() if self.client_factory is None else None)
        evil = {p.id for p in game.players.values() if p.role in EVIL_ROLES}
        manager = EvilStrategyManager(game.ids, evil, seed=seed,
                                      controlled_evil_ids=evil - {self.human})
        self.client, self.agent_options = client, options
        self.seed, self.player_count = seed, count
        self.game, self.manager = game, manager
        self._build_agents()
        self.cursor = 0
        self.ballots = {}
        self.exile_ballots = {}
        self.mission_card = None
        self.gate = "ROLE_REVEAL"
        self.result = None
        self.ai_error = False
        self._flush()

    def _build_agents(self):
        """Create fresh private AI state against the current authoritative game."""
        if self.game is None or self.manager is None or self.client is None:
            raise ValueError("The game is not ready")
        self.agents = {
            pid: Agent(self.game.view(pid), self.client,
                       chronicle=self.game.chronicle.reader(), **self.agent_options)
            for pid in self.game.ids if pid != self.human
        }
        for pid in self.manager.controlled_evil_ids:
            self.agents[pid].bind_evil_strategy(self.manager)

    def _restart_ai_turn(self):
        """Discard failed private AI state while preserving the public game state.

        An invalid/failed model response is rejected before the engine commits a
        public action. Replaying the existing Chronicle into fresh agents gives
        the next attempt the same legal state without retaining the failed plan.
        """
        if self.game is None:
            raise ValueError("Start a game first")
        if self.gate or self.game.winner:
            raise ValueError("The current game is waiting at a result gate")
        evil = {p.id for p in self.game.players.values() if p.role in EVIL_ROLES}
        self.manager = EvilStrategyManager(
            self.game.ids, evil, seed=self.seed,
            controlled_evil_ids=(evil & set(self.game.ids)) - {self.human},
        )
        self._build_agents()
        self.cursor = 0
        self._flush()
        self.ai_error = False
        self.error = ""
        self.notice = "本回合 AI 状态已重置，正在重新执行当前行动。"

    def _flush(self):
        for event in self.game.chronicle.since(self.cursor):
            self.manager.observe(deepcopy(event))
            for agent in self.agents.values():
                agent.observe(deepcopy(event))
            if event["kind"] == "DISCUSSION_END" and self.human in event["expired_reactions"]:
                self.notice = "讨论已结束，你尚未使用的反应机会已到期。"
        self.cursor = len(self.game.chronicle)
        for agent in self.agents.values():
            agent.update_view(self.game.view(agent.id))

    def cognition_debug_view(self):
        """Separate developer read surface; never merged into a player snapshot."""
        if not self.developer_mode:
            raise ValueError("Developer mode is required")
        if self.game is None:
            return {"agents": {}}
        return {"agents": {pid: agent.cognition_debug_view() for pid, agent in self.agents.items()}}

    def _agent(self, pid):
        agent = self.agents[pid]
        agent.update_view(self.game.view(pid))
        return agent

    def _safe_ai_call_metadata(self):
        """Project provider metadata without response content or private plans."""
        call = getattr(self.client, "last_call", None)
        call = call if isinstance(call, dict) else {}
        response_id = call.get("id")
        if not (isinstance(response_id, str) and 1 <= len(response_id) <= 128
                and all(c.isascii() and (c.isalnum() or c in "._:-") for c in response_id)):
            response_id = None
        response_hash = call.get("response_sha256")
        if not (isinstance(response_hash, str) and len(response_hash) == 64
                and all(c in "0123456789abcdef" for c in response_hash)):
            response_hash = None
        finish_reason = call.get("finish_reason")
        if not isinstance(finish_reason, str) or finish_reason not in {
                "stop", "length", "content_filter", "tool_calls"}:
            finish_reason = None
        raw_usage = call.get("usage")
        usage = {k: v for k, v in (raw_usage if isinstance(raw_usage, dict) else {}).items()
                 if k in {"prompt_tokens", "completion_tokens", "total_tokens",
                          "prompt_cache_hit_tokens", "prompt_cache_miss_tokens"}
                 and type(v) is int and v >= 0}
        return {"response_id": response_id, "response_sha256": response_hash,
                "finish_reason": finish_reason, "usage": usage}

    def _record_ai_failure(self, view, error, attempt_index, *, will_retry):
        """Send only allowlisted failure metadata to an optional local sink."""
        if self.ai_diagnostic_sink is None:
            return
        decision_kind = view.get("decision_kind")
        if not (isinstance(decision_kind, str) and decision_kind in {
                "team", "discussion", "council_discussion", "challenge", "reaction",
                "revision", "vote", "mission", "assassination", "exile_nomination",
                "exile_vote"}):
            decision_kind = None
        diagnostic = {
            "phase": view["phase"], "decision_kind": decision_kind,
            "actor_id": view["self"], "legal_actions": list(view["legal_actions"]),
            "legal_action_kinds": sorted({option["kind"] for option in view["legal_options"]}),
            "attempt_index": attempt_index, "will_retry": will_retry,
            "public_code": error.public_code, "validation_reason": error.validation_reason,
            "mock_response_id": None, **self._safe_ai_call_metadata(),
        }
        try:
            self.ai_diagnostic_sink(diagnostic)
        except Exception:
            # Diagnostic storage must not turn an otherwise valid game action
            # into a failure or replace the original model error.
            pass

    def _record_ai_discussion_action(self, view, agent, action, retry_count, action_seq):
        """Record only a committed action kind and whether the plan held unused prose."""
        if self.ai_diagnostic_sink is None:
            return
        diagnostic = {
            "event_type": "accepted_discussion_action", "phase": view["phase"],
            "decision_kind": view.get("decision_kind"), "actor_id": view["self"],
            "action_seq": action_seq, "mock_response_id": None,
            "legal_actions": list(view["legal_actions"]),
            "legal_action_kinds": sorted({option["kind"] for option in view["legal_options"]}),
            "action_kind": action["kind"],
            "plan_social_present": isinstance(agent.plan, dict) and agent.plan.get("social") is not None,
            "retry_count": retry_count, **self._safe_ai_call_metadata(),
        }
        try:
            self.ai_diagnostic_sink(diagnostic)
        except Exception:
            # Observability must not change a committed game action.
            pass

    def _prepare_ai(self, agent, view):
        failure_count = 0

        def on_retry(error, attempt_index, _delay):
            nonlocal failure_count
            failure_count = attempt_index
            self._record_ai_failure(view, error, attempt_index, will_retry=True)

        try:
            source = agent.prepare(view, on_retry=on_retry)
            return source, failure_count
        except LLMError as error:
            self._record_ai_failure(view, error, failure_count + 1, will_retry=False)
            raise

    def _decision_actor(self):
        game = self.game
        if self.gate or game.winner:
            return None
        if game.phase == "vote":
            return next((p for p in game.ids if p not in self.ballots), None)
        if game.phase == "exile_vote":
            return next((p for p in game.ids if p not in self.exile_ballots), None)
        if game.phase == "mission":
            return self.human if self.human in game.team and self.mission_card is None else None
        if game.phase == "assassination":
            return next(p.id for p in game.players.values() if p.role == "ASSASSIN")
        return game.next_actor

    def _can_advance(self):
        return bool(self.game and not self.gate and not self.game.winner
                    and self._decision_actor() != self.human)

    def _finish_vote(self):
        game = self.game
        if len(self.ballots) != len(game.ids):
            return
        leader = game.leader
        reasons = {p: "human_choice" if p == self.human else
                   "last_chance" if game.attempt == 5 else "team_risk" for p in game.ids}
        game.vote({p: b["approve"] for p, b in self.ballots.items()}, reasons,
                  strong={p: b["strong"] for p, b in self.ballots.items()})
        event = next(e for e in reversed(game.events) if e["kind"] == "TEAM_VOTE")
        self.result = dict(event, leader=leader, ballots=[dict(player=p, **self.ballots[p]) for p in game.ids])
        self.ballots = {}
        self.gate = "VOTE_RESULT"

    def _finish_exile_vote(self):
        game = self.game
        if len(self.exile_ballots) != len(game.ids):
            return
        game.vote_exile(self.exile_ballots)
        event = next(e for e in reversed(game.events) if e["kind"] == "EXILE_RESULT")
        self.result = dict(event, leader=game.leader, team=list(game.team), safe_round=game.safe_round,
                           ballots=[{"player": p, "choice": self.exile_ballots[p]} for p in game.ids])
        self.exile_ballots = {}
        self.gate = "EXILE_RESULT"

    def _v5_merlin_ballot(self, view):
        """Apply the frozen V5 vote only to this Merlin's legal view and public history."""
        if view["phase"] != "vote" or view["role"] != "MERLIN":
            raise ValueError("V5 requires an acting Merlin vote")
        from .eval.v2.v232_candidate_v2 import PublicVoteState
        from .eval.v2.v232_candidate_v5 import CANDIDATE, candidate_vote_decision

        public_state = PublicVoteState(
            team=list(view["team"]),
            events=self.game.chronicle.reader().observations_since(0),
            failures=int(view["failures"]),
            attempt=int(view["attempt"]),
        )
        approve, policy = candidate_vote_decision(public_state, view)
        if type(approve) is not bool or policy.get("policy_version") != CANDIDATE:
            raise ValueError("Invalid V5 vote decision")
        return {"approve": approve, "strong": False}

    def advance(self):
        if not self._can_advance():
            raise ValueError("Waiting for your decision")
        game, pid = self.game, self._decision_actor()
        if game.phase == "team":
            agent = self._agent(pid)
            if pid not in self.manager.controlled_evil_ids:
                self._prepare_ai(agent, game.view(pid))
            game.propose(pid, agent.choose_team(game.team_size, game.attempt))
        elif game.phase in {"discussion", "council_discussion"}:
            agent = self._agent(pid)
            view = game.view(pid)
            _, retry_count = self._prepare_ai(agent, view)
            action = agent.discussion_action()
            event_count = len(game.events)
            game.act(pid, action)
            self._record_ai_discussion_action(view, agent, action, retry_count,
                                              game.events[event_count]["seq"])
        elif game.phase in {"challenge", "reaction"}:
            game.act(pid, self._agent(pid).window_action())
        elif game.phase == "revision":
            game.act(pid, self._agent(pid).revise_team())
        elif game.phase == "vote":
            agent = self._agent(pid)
            ballot = (self._v5_merlin_ballot(game.view(pid))
                      if self.merlin_vote_policy == "v5" and agent.role == "MERLIN"
                      else agent.ballot(list(game.team), game.attempt))
            game.validate_ballot(pid, ballot["approve"], ballot["strong"])
            self.ballots[pid] = ballot
            self._finish_vote()
        elif game.phase == "mission":
            leader = game.leader
            external = ({self.human: self.mission_card} if self.human in game.team
                        and game.players[self.human].role in EVIL_ROLES else {})
            evil_pid = next(p for p in game.ids if p in self.manager.controlled_evil_ids)
            managed = self.manager.mission_cards(game.view(evil_pid), external_cards=external)
            cards = {p: self.mission_card if p == self.human else
                     managed[p] if p in managed else self._agent(p).mission() for p in game.team}
            game.resolve_mission(cards)
            self.mission_card = None
            self.result = deepcopy(next(e for e in reversed(game.events) if e["kind"] == "MISSION"))
            self.result["leader"] = leader
            self.gate = "ROUND_RESULT"
        elif game.phase == "assassination":
            game.assassinate(pid, self._agent(pid).assassinate())
        elif game.phase == "exile_nomination":
            game.nominate_exile(pid, self._agent(pid).council_decision()["target"])
        elif game.phase == "exile_vote":
            choice = self._agent(pid).council_decision()["choice"]
            game.validate_exile_ballot(pid, choice)
            self.exile_ballots[pid] = choice
            self._finish_exile_vote()
        self._flush()

    def _apply(self, command, payload):
        if command == "start":
            self.start(payload.get("players", 5), payload.get("seed"))
            return
        if command == "reset_game":
            count = payload.get("players", self.player_count or 5)
            self.start(count, payload.get("seed"))
            return
        if self.game is None:
            raise ValueError("Start a game first")
        if command == "restart_round":
            self._restart_ai_turn()
            if self._can_advance():
                self.advance()
            return
        if command == "continue":
            if not self.gate:
                raise ValueError("There is no result to dismiss")
            previous = self.gate
            if previous == "EXILE_RESULT":
                self.game.finish_council()
                self._flush()
            self.gate, self.result = None, None
            if previous == "EXILE_RESULT" and self.game.phase == "team":
                self.notice = "进入安全任务轮：失败不导致队员死亡；等待重生者已归来，决心已恢复至 3 / 3。"
            elif previous == "ROUND_RESULT":
                self.notice = "任务后议会：每人讨论一次，再由本次任务队长提名，全员投票决定是否出局。"
            return
        if command in {"advance", "retry"}:
            self.advance()
            self.ai_error = False
            return
        if self.gate or self._decision_actor() != self.human:
            raise ValueError("This is not your decision")
        game = self.game
        if command == "team":
            game.propose(self.human, payload.get("team"))
        elif command == "action":
            game.act(self.human, payload.get("action"))
        elif command == "vote":
            approve, strong = payload.get("approve"), payload.get("strong", False)
            game.validate_ballot(self.human, approve, strong)
            self.ballots[self.human] = {"approve": approve, "strong": strong}
            self.notice = "投票已提交，等待其他玩家。所有选票收齐后一起公开。"
            self._finish_vote()
        elif command == "mission":
            game.validate_mission_card(self.human, payload.get("card"))
            self.mission_card = payload["card"]
            self.notice = "任务牌已提交，正在等待其他队员。"
        elif command == "assassinate":
            game.assassinate(self.human, payload.get("target"))
        elif command == "nominate_exile":
            game.nominate_exile(self.human, payload.get("target"))
        elif command == "exile_vote":
            choice = payload.get("choice")
            game.validate_exile_ballot(self.human, choice)
            self.exile_ballots[self.human] = choice
            self.notice = "出局票已提交，所有选票收齐后一起公开。"
            self._finish_exile_vote()
        else:
            raise ValueError("Unknown command")
        self._flush()

    def dispatch(self, request):
        """One versioned, idempotent command. Rejected commands return a fresh view."""
        if not isinstance(request, dict):
            return {"ok": False, "error": "操作指令无效。", "state": self.snapshot()}
        request_id = request.get("request_id")
        if not isinstance(request_id, str) or not 1 <= len(request_id) <= 100:
            return {"ok": False, "error": "操作请求缺少有效编号，请重试。", "state": self.snapshot()}
        if request_id in self.requests:
            # A replay must not return an obsolete state after later commands.
            cached = self.requests[request_id]
            return dict(cached, state=self.snapshot())
        self.error = ""
        command = request.get("command")
        try:
            if request.get("revision") != self.revision:
                raise ValueError("The game has advanced. Review the updated state and try again.")
            payload = request.get("payload", {})
            if not isinstance(payload, dict):
                raise ValueError("Invalid command payload")
            self.notice = ""
            self._apply(command, payload)
            self.revision += 1
            ok = True
        except LLMError as error:
            self.error = ("尚未配置 AI 服务。请完成项目的 .env 配置，然后重新开始游戏。"
                          if error.public_code == "missing_configuration" else
                          AI_ERRORS.get(error.public_code, "AI 服务请求失败") + "。请重新开始回合，或重置游戏。")
            self.ai_error = command in {"advance", "retry", "restart_round"}
            ok = False
        except (ValueError, TypeError, KeyError, OSError):
            # Never put arbitrary provider/configuration/strategy exception text on the wire.
            self.error = ("AI 暂时无法行动。请重新开始回合，或重置游戏。"
                          if command in {"advance", "retry", "restart_round"} else
                          "当前无法执行此操作，请检查游戏阶段、选择和决心余额后重试。")
            self.ai_error = command in {"advance", "retry", "restart_round"}
            ok = False
        response = {"ok": ok, "error": self.error, "state": self.snapshot()}
        self.requests[request_id] = {"ok": ok, "error": self.error}
        if len(self.requests) > 64:
            self.requests.popitem(last=False)
        return response

    def _event(self, event):
        safe = {k: deepcopy(v) for k, v in event.items() if k in PUBLIC_FIELDS}
        safe["text"] = self._event_text(safe)
        return safe

    def _name(self, pid):
        if pid not in self.game.players:
            return str(pid)
        name = "你" if pid == self.human else self.game.players[pid].name
        return f"{name}（{pid}）"

    def _dialogue(self):
        """Only speech attached to completed public actions reaches the dialogue box.

        No extra model call, draft plan, rationale, or inferred line is displayed.
        Sequence IDs make refreshes/retries refer to the same original utterance.
        """
        return [{"seq": e["seq"], "actor": e["actor"], "round": e["round"],
                 "attempt": e["attempt"], "kind": e["kind"], "card": e["card"],
                 "target": e["target"], "committed": e.get("committed", False),
                 "statement": e["statement"], "record_id": e["record_id"],
                 "discussion_stage": e.get("discussion_stage", "proposal"),
                 **({"reply_to": self.game.chronicle.reader().get_record(
                     e["challenge" if e["kind"] == "CHALLENGE_RESPONSE" else "trigger"])["record_id"]}
                    if e["kind"] in {"CHALLENGE_RESPONSE", "REACT"} else {}),
                 "citations": list(e.get("citations", [])),
                 "citation_records": [self._event(self.game.chronicle.reader().get_record(rid))
                                      for rid in e.get("citations", [])]}
                for e in self.game.events
                if e["kind"] in {"SOCIAL", "REACT", "CHALLENGE_RESPONSE"}
                and isinstance(e.get("statement"), str) and e["statement"].strip()]

    def _event_text(self, event):
        kind = event["kind"]
        who = self._name
        actor = who(event.get("actor", ""))
        team = " / ".join(event.get("team", []))
        if kind == "START":
            return "游戏开始。你将与 AI 玩家一起进行对局。"
        if kind == "LEADER":
            return f"{actor} 成为队长"
        if kind == "TEAM":
            return f"{actor} 提议队伍：{team}"
        if kind in {"SOCIAL", "REACT", "CHALLENGE_RESPONSE"} and "card" in event:
            prefix = "加强承诺 · " if event.get("committed") else ""
            action = {"SOCIAL": "落笔", "REACT": "补记", "CHALLENGE_RESPONSE": "书面回应质询"}[kind]
            return f"{actor} {prefix}{action}：{CARD_LABELS[event['card']]} {who(event['target'])}"
        if kind == "CHALLENGE_RESPONSE":
            return f"{actor} 拒绝回应质询"
        if kind == "CHALLENGE":
            return f"{actor} 依据 #{event['evidence']} 质询 {who(event['target'])}"
        if kind == "CITE":
            return f"{actor} 引用公开记录 #{event['evidence']}"
        if kind == "PASS":
            return f"{actor} 选择沉默"
        if kind == "HOLD":
            return f"{actor} 预付 1 点决心，保留一次反应机会"
        if kind == "VOTE":
            return f"{actor}：{'强烈' if event['strong'] else ''}{'赞成' if event['approve'] else '反对'}"
        if kind == "TEAM_VOTE":
            yes = sum(event["votes"].values())
            return f"提案{'通过' if event['approved'] else '被否决'}：{yes} 票赞成 / {len(event['votes'])-yes} 票反对"
        if kind == "MISSION":
            safety = "（安全轮，失败不致死）" if event.get("safe_round") else ""
            return f"第 {event['round']} 次任务{'成功' if event['success'] else '失败'}{safety}：{len(event['team'])-event['fail_count']} 张成功 / {event['fail_count']} 张失败"
        if kind == "COUNCIL_START":
            return f"任务后议会开始：全员讨论，再提名和投出局票；须 {event['required_approvals']} 票赞成"
        if kind == "EXILE_NOMINATION":
            return f"{actor} 提名 {who(event['target'])} 出局"
        if kind == "EXILE_VOTE":
            return f"{actor} 对 {who(event['target'])} 出局投下{EXILE_LABELS[event['choice']]}票"
        if kind == "EXILE_RESULT":
            c = event["counts"]
            return f"{who(event['target'])} {'出局' if event['exiled'] else '未出局'}：{c['APPROVE']} 赞成 / {c['REJECT']} 反对 / {c['ABSTAIN']} 弃票"
        if kind == "TEAM_REVISE":
            return f"{actor} 调整 {event['removed']} → {event['added']}；队伍：{team}"
        if kind == "TEAM_LOCK":
            return f"{actor} 确认队伍：{team}"
        if kind == "RESOLVE_REFRESH":
            return "所有玩家的决心已恢复至 3 / 3"
        if kind == "ROUND":
            return f"第 {event['round']} 次{'安全' if event.get('safe_round') else '危险'}任务开始，需要选择 {event['team_size']} 名队员"
        if kind == "DISCUSSION_END":
            expired = event.get("expired_reactions", [])
            return "讨论结束" + (f"；反应机会已到期：{' / '.join(expired)}" if expired else "")
        if kind == "REACTION_SKIP":
            return f"{actor} 继续等待反应机会"
        if kind == "ASSASSINATION_PHASE":
            return "三次任务成功，进入刺杀阶段"
        if kind == "ASSASSINATE":
            return f"{actor} 刺杀了 {who(event['target'])}"
        if kind == "DEATH":
            cause = {"failed_expedition": "失败远征", "exile": "议会出局", "assassination": "刺杀"}[event["cause"]]
            return f"{who(event['target'])} 的第 {event['life']} 次生命止于{cause}；等待下一轮重生"
        if kind == "REBIRTH":
            return f"{who(event['target'])} 归来，进入第 {event['life']} 次生命；重要记忆仍在"
        if kind == "RESULT":
            return f"{'善良' if event['winner'] == 'GOOD' else '邪恶'}阵营获胜。{WIN_REASONS.get(event['reason'], '')}"
        if kind == "DIRECTION":
            direction = "顺时针" if event["direction"] == "clockwise" else "逆时针"
            return f"手写行动从队长开始，按{direction}顺序进行"
        return "公开记录已更新"

    def snapshot(self):
        if self.game is None:
            return {"phase": "START", "revision": self.revision, "error": self.error,
                    "can_advance": False, "players": [], "public_events": [], "dialogue": []}
        game, pid = self.game, self.human
        view = game.view(pid)
        phase = self.gate or PHASES[game.phase]
        # Results describe the resolved proposal, even when Game has already rotated.
        display = self.result if self.gate in {"VOTE_RESULT", "ROUND_RESULT", "EXILE_RESULT"} else {}
        display_team = display.get("team", game.team)
        display_leader = display.get("leader", game.leader)
        actor = self._decision_actor()
        human_turn = not self.gate and actor == pid
        actions = view["legal_actions"] if human_turn else []
        evidence = [e for e in game.events if e["kind"] in EVIDENCE_KINDS][-40:]
        challenge_evidence = {}
        for target in game.ids:
            if target == pid:
                continue
            refs = []
            for event in evidence:
                try:
                    public_evidence(game.events, event["seq"], target)
                except ValueError:
                    continue
                refs.append(event["seq"])
            if refs:
                challenge_evidence[target] = refs
        if not evidence:
            actions = [a for a in actions if a != "CITE"]
        if not challenge_evidence:
            actions = [a for a in actions if a != "CHALLENGE"]
        if human_turn and game.phase == "team":
            actions = ["PROPOSE"]
        if human_turn and game.phase == "mission":
            actions = game.legal_mission_cards(pid)
        if human_turn and game.phase == "assassination":
            actions = ["ASSASSINATE"]
        if human_turn and game.phase == "exile_nomination":
            actions = ["NOMINATE_EXILE"]
        if human_turn and game.phase == "exile_vote":
            actions = list(EXILE_CHOICES)
        if self.gate:
            actions = ["CONTINUE"]
        if game.winner and not self.gate:
            actions = ["RESTART"]
        candidates = {"discussion": DISCUSSION_ACTIONS, "council_discussion": DISCUSSION_ACTIONS,
                      "challenge": ("RESPOND", "DECLINE"),
                      "reaction": ("REACT", "SKIP"), "revision": ("LOCK", "REVISE"),
                      "vote": ("VOTE", "STRONG_VOTE")}.get(game.phase, ()) if human_turn else ()
        options = [{"kind": a, "cost": RESOLVE_COSTS[a], "enabled": a in actions,
                    "reason": "" if a in actions else
                    "决心不足" if view["resolve"][pid] < RESOLVE_COSTS[a] else
                    "没有符合条件的公开证据"} for a in candidates]
        public = [self._event(e) for e in game.events if e["kind"] not in {"REVEAL", "MISSION_SUBMIT"}]
        # An AI assassin's identity is not disclosed before its public action.
        shown_actor = None if game.phase == "assassination" and actor != pid else actor
        players = [dict(p, name="你" if p["id"] == pid else p["name"],
                        life=game.lives[p["id"]]["life"], alive=game.lives[p["id"]]["alive"],
                        is_human=p["id"] == pid, resolve=view["resolve"][p["id"]],
                        is_leader=p["id"] == display_leader, is_on_team=p["id"] in display_team,
                        is_active=p["id"] == shown_actor,
                        discussion_status="waiting" if phase == "TEAM_DRAFT" else view["discussion_status"][p["id"]],
                        reaction_ready=p["id"] in view["pending_reactions"]) for p in view["players"]]
        result_event = next((e for e in reversed(public) if e["kind"] == "RESULT"), {})
        prompt = "轮到你了" if human_turn else ""
        if self._can_advance():
            prompt = ("任务进行中，正在等待队员。" if game.phase == "mission" else
                      "刺客正在选择目标…" if game.phase == "assassination" else
                      f"{game.players[actor].name} 正在思考…")
        if self.ai_error:
            prompt = "AI 已暂停，请重试当前行动。"
        return {"revision": self.revision, "phase": phase, "engine_phase": game.phase,
                "human_id": pid, "private": {"role": view["role"], "known_evil": view["known_evil"]},
                "mission_round": display.get("round", game.round), "proposal_attempt": display.get("attempt", game.attempt), "leader": display_leader,
                "successes": game.successes, "failures": game.failures, "team_size": game.team_size,
                "safe_round": display.get("safe_round", game.safe_round), "discussion_stage": game.discussion_stage,
                "exile_nominee": game.exile_nominee, "required_approvals": len(game.ids) // 2 + 1,
                "players": players, "max_resolve": MAX_RESOLVE, "proposed_team": list(display_team),
                "speaking_order": game.speaking_order, "current_actor": shown_actor,
                "legal_actions": list(actions), "action_options": options, "social_cards": list(CARDS),
                "selection_targets": (game.assassination_targets(pid) if game.phase == "assassination" else
                                      game.exile_candidates() if game.phase == "exile_nomination" else list(game.ids)),
                "evidence": [self._event(e) for e in reversed(evidence)],
                "challenge_evidence": challenge_evidence, "challenge": view["challenge"],
                "focused_events": [self._event(e) for e in view["focused_events"]],
                "reaction_trigger": view["reaction_trigger"], "public_events": public,
                "dialogue": self._dialogue(),
                "result": deepcopy(self.result), "winner": game.winner,
                "win_reason": WIN_REASONS.get(result_event.get("reason", ""), ""),
                "can_advance": self._can_advance() and not self.ai_error,
                "human_turn": human_turn, "prompt": prompt, "notice": self.notice,
                "error": self.error, "retry_ai": self.ai_error,
                "vote_submitted": pid in self.ballots or pid in self.exile_ballots,
                "mission_submitted": self.mission_card is not None}
