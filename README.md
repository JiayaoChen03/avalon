# Terminal Avalon MVP

一个可以直接在终端玩的 **1 名人类 + 4/5 个 LLM agent** 社交推理游戏。保留 Avalon 基础规则，AI 依次给出自然语言发言、简短判断依据和一张 social card。每位 AI 在单局内维护独立的身份判断与行为画像。

**Python 3.10+，需要配置真实 LLM 服务。启动时自动读取配置，不使用 mock 或失败回退。**

## 快速开始

进入本 README 所在目录，安装依赖，复制 `.env.example` 为 `.env`（PowerShell：`Copy-Item .env.example .env`），填入 API key 和模型名称。配置细节见下方「接入 LLM」。然后运行：

```sh
python -m pip install -r requirements.txt
python -m avalon --dossier
```

你是 **P1**。程序只向你显示自己的身份及规则允许知道的信息。每个输入都有提示；回车接受默认选项，`help` 查看帮助，`q` 或 Ctrl+C 退出。Windows 如使用 Python Launcher，可将 `python` 换成 `py -3`。

```sh
# 6 人局，1 位人类 + 5 个 agent
python -m avalon --players 6

# 无人值守演示；只有 --demo 会把人类席位交给 agent
python -m avalon --demo --seed 7 --dossier

# 人类试玩，同时记录公开事件
python -m avalon --log public-game.jsonl

# 指定本局逆时针发言；不指定时在开局随机决定方向
python -m avalon --direction counterclockwise

# 所有选项
python -m avalon --help
```

`--seed` 固定发牌、首任队长和发言方向，三者使用独立随机序列。普通游戏不传它，每局随机；相同 seed 不保证 LLM 发言或整局结果相同。公开日志和 agent 上下文不包含 seed。`--demo` 同样调用真实 LLM。

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

每次提案，从队长开始按座位顺序轮流发言、每人打一张社交牌；牌可重复使用。AI 会阅读此前的公开发言，再生成自己的回应和判断摘要。社交牌会影响 AI 对身份和行为的估计，不直接改变任务分数。人类玩家仍使用表中的固定卡牌输入。

开局通过 `[DIRECTION]` 公布本局发言方向：`clockwise` 为顺时针（座位号递增），`counterclockwise` 为逆时针（座位号递减）。每次提案均从当前队长开始，终端打印完整 `[SPEAKING ORDER]`，所有人依次表态后才投票。方向整局固定，队长仍按座位号递增轮换。

每位 agent 的社交行动包括 **卡牌、自由表态、简短理由摘要、公开依据编号**。后发言的 agent 能看到先前的真实表态，并在自己的发言中回应。理由摘要是对其他玩家说的公开解释，不展示模型内部完整思维链。没有历史依据时可以自由开场、提出问题或试探，不会因此切换 mock。

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

**没有 key/model 或配置无效时，程序会说明缺失项并退出，不会开始模拟对局。** 超时、连接失败、限流、常见服务端错误、空响应、格式错误、截断输出或非法计划会自动重试。默认最多重试 2 次，加上首次调用共 3 次；重试前分别等待 2 秒、4 秒。终端会显示当前玩家、错误代码和重试进度，例如 `[RETRY] [SAGE/P5] 调用失败（invalid_response），2 秒后重试（1/2）…`。

重试期间保留同一玩家、同一提案和同一份上下文，不推进对局；只有获得有效结果才写入发言和私有记忆。全部尝试失败才停止，不生成替代行动。密钥、余额、参数等不可恢复的错误以及模型拒答会直接停止；DeepSeek 的错误含义可参考[官方错误码说明](https://api-docs.deepseek.com/quick_start/error_codes/)。

可在 `.env` 中用 `OPENAI_MAX_RETRIES` 设置额外重试次数（0–5，0 表示不重试），用 `OPENAI_RETRY_DELAY_SECONDS` 设置首次等待秒数（0–30）。后续等待时间翻倍，单次最多 30 秒。等待或请求过程中可按 Ctrl+C 退出。错误会区分 `invalid_response`（格式错误）、`empty_response`（空响应）、`truncated_response`（输出截断）等，便于调整配置。

旧版的 `--mock` 参数已移除。请求按发言顺序串行执行，`AVALON_LLM_CONCURRENCY` 不再使用。输出上限默认 2400 tokens，可通过 `OPENAI_MAX_TOKENS` 调整。

## 按顺序实时发言

每次选队提案按以下顺序推进：

1. 如果队长是 AI，先调用一次 LLM，按其最新排名选择队伍。
2. 公开队伍和发言顺序：从队长开始，按座位顺序绕桌一圈。
3. 轮到某个 AI 时，才把当前队伍、此前发言和它自己的私有记忆发送给 LLM。
4. 显示它的社交牌、自然语言发言和简短判断依据；写入公开事件后，下一位 AI 才开始请求。
5. 收齐所有发言后，按照各自最近的模型策略投票和执行任务。提案被否决后，新队长重新选队，所有人重新发言。

每份模型计划包含身份和行为估计、策略、选队排名、投票阈值、社交行动、秘密任务牌和刺杀排名。投票仍结合最新的本地身份估计；投票、任务执行和刺杀本身不额外调用 LLM。

没有失败时，每个 AI 每次发言调用一次，AI 队长选队另加一次。普通五人局每次提案共 4–5 次请求，六人局 5–6 次；全 AI 演示分别为 6、7 次。重试会增加实际请求数。成功计划仅在同一「任务轮 / 提案 / 阶段」内缓存，避免重复请求，不跨提案复用发言。结束时 `[CALLS]` 列出每位 agent 每个任务轮的实际 HTTP 尝试数，包含失败和重试。

首次调用发送的历史画像为 `beliefs={}`、`profiles={}`，并标记 `no_previous_model`，不发送预设概率、mock 画像或虚构往局记录。模型依据当前角色合法可知的信息建立假设；成功生成计划后，才把实际模型估计与后续公开观察带入下一次调用。失败尝试不会被当作模型历史。

发言字段 `statement` 和理由摘要 `rationale` 各最多 240 字符，`evidence` 可引用最多 3 条可见公开事件编号。判断摘要说明公开依据、当前倾向和不确定性；不会读取或展示服务商返回的内部 `reasoning_content`。

## 私有记忆和公开日志

- 裁判广播公开结构化事件；每个 agent 只看到自己的角色、合法已知座位和最近 **20 条事件**。
- 最多 5 条任务汇总、最多 6 条近期证据，加上各自压缩后的 belief/profile 进入下一次调用上下文；不会重发完整聊天记录。
- 社交牌更新公开信任信号与攻击倾向；被施压后的反击更新 retaliation；投票更新 approval/consensus；任务结果更新身份估计。这些值影响后续选队、投票与 probe 目标。
- 模型输出只接受指定字段、有限数值、有效座位和枚举；仅允许 `statement` 与 `rationale` 作为公开短文本，每项最多 240 字符，拒绝换行和终端控制字符。
- 公开理由可引用最多 3 条实际可见事件编号，终端每条公开事件均带 `[#编号]` 方便核对。重复或过长的有效引用列表会本地去重、取前三条，保留模型决策；不存在的引用仍拒绝。投票规律或任务证据类理由必须引用对应记录。自然语言属于玩家的观点与主张，不是裁判确认的事实。
- 公开文本对明确自报私有身份的常见表达做保护，例如“作为邪恶方”：只替换该文本为卡牌与公开理由概述，保留模型决策，不增加请求。原始响应与 `reasoning_content` 均不打印或保存；这不保证自由发言无法被其他玩家推断身份。
- `[PRIVATE]` 只用于本地人类的角色与秘密输入提示，**不会**进入 JSONL，也不会发送给其他 agent。
- `--log` 保存完整公开事件，包含赛后身份揭晓。`--dossier` 仅在比赛结束后打印有限的画像、策略和公开证据摘要，不包含 chain-of-thought。
- 画像是单局内的游戏状态；MVP 没有数据库、跨局记忆或外部 agent 框架。AI 的自然语言发言属于当前对局，人类输入仍采用卡牌和选项。

## 目录

```text
terminal-avalon/
├── avalon/
│   ├── __main__.py     # python -m avalon
│   ├── engine.py       # 规则、隐藏身份、公开事件、胜负
│   ├── agents.py       # 独立私有记忆、逐次发言计划、行动策略
│   ├── llm.py          # dotenv、一次 HTTP 请求、响应解析
│   └── terminal.py     # 人类输入、公开打印、对局循环
├── tests/              # 标准库 unittest，含本地 HTTP 契约测试
├── examples/           # 历史 API 与离线运行记录（仅作参考）
├── .env.example
├── requirements.txt
├── pyproject.toml
└── README.md
```

也可安装为命令；较旧的 Python 自带 pip 需要先升级，才能识别此项目的 editable 安装配置：

```sh
python -m pip install --upgrade pip
python -m pip install -e .
avalon
```

## 验证

```sh
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
# 以下整局演示需要先配置真实模型
python -m avalon --demo --players 5 --seed 7 --dossier
python -m avalon --demo --players 6 --seed 7
```

自动化测试覆盖规则、随机队长与发言方向、随机序列隔离、秘密信息隔离、非法输入、逐次发言与请求顺序、前序发言进入后续上下文、空历史开场、公开依据校验、失败重试后继续同一发言、重试次数上限、Ctrl+C 中断、本地 HTTP 请求、真人输入路径，以及多个 seed 的整局结束。测试仅在外部模型边界提供受控响应，不需要真实密钥，正式游戏不加载测试数据。旧版 API 与离线运行记录见 [examples/README.md](examples/README.md)，其中调用次数与当前版本不同。逐次调用版本已用 DeepSeek V4 Pro 验证单次真实游戏发言接入；这不等于完整对局的模型质量评测。
