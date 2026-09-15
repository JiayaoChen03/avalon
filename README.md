# Terminal Avalon MVP

一个可以直接在终端玩的 **1 名人类 + 4/5 个 AI agent** 社交推理游戏。保留 Avalon 基础规则，以五种 social cards 代替长篇发言。AI 在单局内维护独立的身份判断与行为画像。

**Python 3.10+。没有 API、没有额外依赖也能离线玩。**

## 30 秒开始

进入本 README 所在目录，然后运行：

```sh
python -m avalon --mock --dossier
```

你是 **P1**。程序只向你显示自己的身份及规则允许知道的信息。每个输入都有提示；回车接受默认选项，`help` 查看帮助，`q` 或 Ctrl+C 退出。Windows 如使用 Python Launcher，可将 `python` 换成 `py -3`。

```sh
# 6 人局，1 位人类 + 5 个 agent
python -m avalon --players 6 --mock

# 无人值守演示；只有 --demo 会把人类席位交给 agent
python -m avalon --demo --mock --seed 7 --dossier

# 人类试玩，同时记录公开事件
python -m avalon --mock --log public-game.jsonl

# 所有选项
python -m avalon --help
```

`--seed` 固定发牌与首任队长，便于复现；两者使用独立随机序列。普通游戏不传它，每局随机；相同 seed + 相同人类输入 + mock 模式可复现。公开日志和 agent 上下文不包含 seed。

## 怎么操作

| 环节 | 输入示例 | 行为 |
| --- | --- | --- |
| 队长选队 | `1 3` 或 `P1,P3` | 选择指定人数，不允许重复座位 |
| 社交出牌 | `ACCUSE P3` | 公开指控 P3 |
| 社交出牌 | `DEFEND P2` | 公开支持 P2，也可以为自己辩护 |
| 社交出牌 | `HEDGE P4` | 保留判断 |
| 社交出牌 | `PRESSURE P2` | 施压并观察目标的反应 |
| 社交出牌 | `BAIT P5` | 诱导并观察目标的反应 |
| 全员投票 | `y` / `n` | 赞成 / 反对队伍；收齐后一起公开 |
| 邪恶执行任务 | `s` / `f` | 秘密提交成功 / 失败牌 |
| 刺客行动 | `P2` | 三次任务成功后选择 Merlin |

每次提案，每人打一张社交牌；牌可重复使用。社交牌会影响 AI 对身份和行为的估计，不直接改变任务分数。MVP 使用固定卡牌输入，不做自然语言解析。

## 基础规则

| 人数 | 身份配置 | 五轮任务人数 |
| --- | --- | --- |
| 5 | Merlin、Good × 2、Assassin、Evil | 2 / 3 / 2 / 3 / 3 |
| 6 | Merlin、Good × 3、Assassin、Evil | 2 / 3 / 4 / 3 / 4 |

- Merlin 属于善良，知道邪恶座位；Assassin 与 Evil 属于邪恶，互相认识；普通 Good 不知道其他人的身份。
- 第一轮开始前，从所有玩家中等概率随机选一名首任队长，终端先打印 `[LEADER]`，再开始任务轮。之后队长按座位顺序轮换选队。
- **超过半数赞成**才通过，平票否决。被否决后队长轮换，同一任务连续五次否决，邪恶直接获胜。
- 只有队员提交任务牌。善良必须出 SUCCESS；邪恶可出 SUCCESS 或 FAIL。5/6 人局所有任务都是一张 FAIL 即失败。
- 三次任务失败，邪恶获胜；三次任务成功，Assassin 获得一次刺杀机会。刺中 Merlin 邪恶翻盘，否则善良获胜。
- 在最终结果产生后揭晓全部身份。任务日志只有提交回执与汇总票数，不公布个人任务牌。

规则核对依据：[The Resistance: Avalon 原版规则书](https://avalon.fun/pdfs/rules.pdf)。五种社交牌属于本 MVP 基于用户概念文档增加的交流方式。

## 接入 LLM

先安装唯一依赖（仅用于读取 `.env`）：

```sh
python -m pip install -r requirements.txt
```

`.env.example` 已配置 **DeepSeek V4 Pro**。首次使用时复制为 `.env`：PowerShell 使用 `Copy-Item .env.example .env`，macOS/Linux 使用 `cp .env.example .env`。已有 `.env` 时直接编辑，填入自己的密钥：

```dotenv
OPENAI_API_KEY=你的密钥
OPENAI_BASE_URL=https://api.deepseek.com
OPENAI_MODEL=deepseek-v4-pro
OPENAI_JSON_MODE=true
DEEPSEEK_THINKING=disabled
OPENAI_TIMEOUT_SECONDS=60
```

模型名称仍由配置决定。这里使用 DeepSeek 的非思考模式与 JSON object 输出，一次请求生成结构化行动计划；不会打印或保存 `reasoning_content`。`DEEPSEEK_THINKING` 可设为 `enabled`、`disabled` 或留空，留空时不发送此参数。参数依据：[DeepSeek 官方思考模式文档](https://api-docs.deepseek.com/guides/thinking_mode/)。

切换其他 OpenAI-compatible 服务时，修改 base URL 和 model，并清空 `DEEPSEEK_THINKING`。如果地址已以 `/chat/completions` 结尾，也可直接使用。`.env` 被 Git 忽略，仓库仅提供不含密钥的 `.env.example`。

```sh
python -m avalon --dossier
python -m avalon --env-file /path/to/your.env
```

配置方式参考了 **zhilu/packages/zhihu/zhihu_m2/config.py**：

- 默认仅加载本项目根目录 `.env`，不会向上搜索其他项目。
- 进程已有的同名环境变量优先；`override=False`。
- 支持 Windows UTF-8 BOM；`encoding="utf-8-sig"`。
- 不展开 `${...}`；`interpolate=False`。
- `PYTHON_DOTENV_DISABLED=1` 禁止加载配置文件。导入模块不会读取密钥或调用网络。

兼容别名按优先级读取：

| 项目 | 优先级 |
| --- | --- |
| key | `OPENAI_API_KEY` → `LLM_API_KEY` → `DEEPSEEK_API_KEY` |
| base URL | `OPENAI_BASE_URL` → `LLM_BASE_URL` → `LLM_API_URL` |
| model | `OPENAI_MODEL` → `LLM_MODEL` → `DEEPSEEK_MODEL` |

只有 DeepSeek key 时，默认 base URL 为 `https://api.deepseek.com`，仍需配置模型。其他情况默认 OpenAI base URL。混用不同前缀时，以表中的优先级为准。

请求使用 OpenAI-compatible Chat Completions。`OPENAI_TOKEN_LIMIT_FIELD` 可设置 `max_completion_tokens`，以适配要求该字段的模型；默认 `max_tokens` 便于兼容其他服务。可用 `OPENAI_JSON_MODE=true` 开启 JSON object 模式。参数依据：[OpenAI API 官方文档](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)。

**没有 key/model 时自动 mock。** 超时、连接失败、HTTP 错误、拒答、截断输出或非法计划会让该 agent 本轮使用 deterministic fallback，终端显示来源，例如 `fallback:http_401`。不自动重试或增加“修复 JSON”的调用；下一任务轮可重新尝试。`--mock` 强制完全离线并跳过 `.env`。

## 每轮一次调用怎么做到

这里的“一轮”指 **一个任务轮**，包括最多五次选队提案。进入任务轮时，每位 agent 一次性生成：

1. 各玩家 evil/Merlin likelihood。
2. 各玩家 aggression、retaliation、approval、consensus 行为估计。
3. 本轮策略、选队排名、投票阈值、第五次提案策略。
4. 社交牌及目标、秘密任务牌、刺杀候选排名。

之后由本地规则执行策略，社交行动与投票仍会更新本地记忆。重选队、投票、任务和刺杀都不增加 LLM 调用。每轮计划缓存，失败请求也计入预算。默认最多 3 个并发请求，每个 agent 都有独立状态与输入副本。结束时 `[CALLS]` 列出每位 agent 每轮实际 HTTP 尝试数。

因此 agent 不会每打一张牌都重新调用模型；同一任务轮的社交计划会复用。投票使用最新身份估计，之后的任务轮再让 LLM重新评估整体策略。这是控制 MVP 调用量的明确取舍。

## 私有记忆和公开日志

- 裁判广播公开结构化事件；每个 agent 只看到自己的角色、合法已知座位和最近 **20 条事件**。
- 最多 5 条任务汇总、最多 6 条近期证据，加上各自压缩后的 belief/profile 进入下一轮上下文；不会重发完整聊天记录。
- 社交牌更新公开信任信号与攻击倾向；被施压后的反击更新 retaliation；投票更新 approval/consensus；任务结果更新身份估计。这些值影响后续选队、投票与 probe 目标。
- 模型输出只接受指定字段、有限数值、有效座位和枚举。公开行动理由由固定 reason code 翻译，任意模型文本和 `reasoning_content` 不会打印或保存。
- `[PRIVATE]` 只用于本地人类的角色与秘密输入提示，**不会**进入 JSONL，也不会发送给其他 agent。
- `--log` 保存完整公开事件，包含赛后身份揭晓。`--dossier` 仅在比赛结束后打印有限的画像、策略和公开证据摘要，不包含 chain-of-thought。
- 画像是单局内的游戏状态；MVP 没有数据库、跨局记忆、自然语言聊天或外部 agent 框架。mock 是可复现的启发式对手，不代表真实 LLM 的推理质量。

## 目录

```text
terminal-avalon/
├── avalon/
│   ├── __main__.py     # python -m avalon
│   ├── engine.py       # 规则、隐藏身份、公开事件、胜负
│   ├── agents.py       # 独立私有记忆、计划校验、行动策略
│   ├── llm.py          # dotenv、一次 HTTP 请求、响应解析
│   └── terminal.py     # 人类输入、公开打印、对局循环
├── tests/              # 标准库 unittest，含本地 HTTP 契约测试
├── examples/           # 实际运行的 smoke test 记录
├── .env.example
├── requirements.txt
├── pyproject.toml
└── README.md
```

也可安装为命令；较旧的 Python 自带 pip 需要先升级，才能识别此项目的 editable 安装配置：

```sh
python -m pip install --upgrade pip
python -m pip install -e .
avalon --mock
```

## 验证

```sh
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python -m avalon --demo --mock --players 5 --seed 7 --dossier
python -m avalon --demo --mock --players 6 --seed 7
```

测试覆盖规则、首任队长随机抽签与后续轮换、随机序列隔离、秘密信息隔离、非法输入、每轮调用预算、错误降级、本地 HTTP 请求、真人输入路径，以及多个 seed 的整局结束。实际 mock 与 DeepSeek V4 Pro smoke test 结果、运行命令见 [examples/README.md](examples/README.md)。
