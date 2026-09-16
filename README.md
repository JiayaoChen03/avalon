# Terminal Avalon MVP

一个可以直接在终端玩的 **1 名人类 + 4/5 个 LLM agent** 社交推理游戏。保留 Avalon 基础规则，玩家依次选择沉默或消耗 Resolve 进行公开交流。AI 发言包含自然语言表态、简短判断依据和 social card。善良 AI 维护独立判断与画像；邪恶 AI 共享代码维护的战略状态，并各自生成自然发言。

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

## 腐化城堡场景

启动时默认加载 [腐化城堡 system prompt](prompts/corrupted_castle_system.md)，并显示 `[WORLD] 腐化城堡`。所有角色都以在被腐化的中世纪城堡中活下来为个人动机，围绕外出搜寻物资、名单、信任和风险发言。角色公开对话使用世界内表达，程序字段仍保留原有格式。

提示词在每局开始时读取，后续发言和重试使用同一份内容；修改文件后重启游戏即可生效。缺失、空白或编码无效会在开局前报错。当前接入负责角色动机与对话，选队、投票、任务及胜负仍按下述 Avalon 规则结算；没有凭空新增库存、伤亡或个人生存值。读取和安装方式见 [提示词说明](prompts/README.md)。

## 怎么操作

| 环节 | 输入示例 | 行为 |
| --- | --- | --- |
| 队长选队 | `1 3` 或 `P1,P3` | 选择指定人数，不允许重复座位 |
| 社交出牌 | `ACCUSE P3` | 公开指控 P3 |
| 社交出牌 | `DEFEND P2` | 公开支持 P2，也可以为自己辩护 |
| 社交出牌 | `HEDGE P4` | 保留判断 |
| 社交出牌 | `PRESSURE P2` | 施压并观察目标的反应 |
| 社交出牌 | `BAIT P5` | 诱导并观察目标的反应 |
| 沉默 | `PASS` 或直接回车 | 免费结束自己的正常讨论轮次 |
| 加强承诺 | `COMMIT ACCUSE P3` | 共花 2 Resolve，公开标记为 COMMITTED |
| 质询 / 引证 | `CHALLENGE P3 #17` / `CITE #17` | 花 1 Resolve，引用已有公开事件编号 |
| 等待 / 反应 | `HOLD`，之后 `REACT DEFEND P2` 或 `SKIP` | HOLD 预付 1，REACT 不再收费；SKIP 保留等待 |
| 回应质询 | `RESPOND HEDGE P2` / `DECLINE` | 回应花 1，拒绝免费并公开记录 |
| 队长定稿 | `LOCK` / `REVISE P3 P2` | 免费锁队，或花 1 把 P3 替换为 P2 |
| 全员投票 | `A` / `R`（也支持 `y` / `n`） | 免费赞成 / 反对；收齐后一起公开 |
| 强承诺投票 | `SA` / `SR` | 花 1 强烈赞成 / 反对，仍然只有一票 |
| 邪恶执行任务 | `s` / `f` | 秘密提交成功 / 失败牌 |
| 刺客行动 | `P2` | 三次任务成功后选择 Merlin |

每次提案，从队长开始按座位顺序获得一次正常讨论机会，可以 PASS 或选择付费行动；社交牌可重复使用。AI 会阅读此前的公开发言，再选择是否发言及生成判断摘要。已有社交牌语义保留；花费 Resolve 或加强承诺不会直接增加信任、嫌疑或任务分数。

开局通过 `[DIRECTION]` 公布本局发言方向：`clockwise` 为顺时针（座位号递增），`counterclockwise` 为逆时针（座位号递减）。每次提案均从当前队长开始，终端打印完整 `[SPEAKING ORDER]`，正常讨论、回应和反应结束后，由队长锁队或替换一人，再投票。方向整局固定，队长仍按座位号递增轮换。

每位 agent 的社交回答先显示玩家与卡牌，再将 **表态** 和 **理由摘要** 分别显示在独立行；社交台词和赛后摘要不额外展示依据列表，CITE/CHALLENGE 则显示行动所引用的事件编号。后发言的 agent 能看到先前的真实表态，并在自己的发言中回应。理由摘要是对其他玩家说的公开解释，不展示模型内部完整思维链。没有历史依据时可以自由开场、提出问题或试探，不会因此切换 mock。

## Resolve / Action Points

每名玩家每个 **Mission Round 有 3 Resolve**，余额公开，由 `Game` 管理。只有任务结算后进入下一任务轮才恢复到 3；**提案被否决不会恢复**，未使用的点数不累积。终端显示如 `[P1] RESOLVE ●●○ (2/3)`。

| 行动 | Resolve 成本 |
| --- | --- |
| PASS、普通投票、正常选队、任务 SUCCESS/FAIL、刺杀、LOCK | 0 |
| SOCIAL、CHALLENGE、RESPOND、CITE、HOLD、REVISE、STRONG VOTE | 1 |
| COMMITTED SOCIAL | 2（含普通社交牌的 1） |
| DECLINE、SKIP、已预付的 REACT | 0 |

有余额也可以选择 PASS，为后续提案、更有价值的证据、回应或投票保留机会。0 Resolve 仍能完成所有 Avalon 基本环节。回车只执行免费动作：讨论 PASS、质询 DECLINE、反应 SKIP、定稿 LOCK、投票普通 APPROVE。

CHALLENGE 必须引用涉及目标的已有公开行动；目标立即获得一次 RESPOND/DECLINE 机会，之后照常保留自己的正常轮次。CITE 只突出旧证据，原事件保持不变；当前提案引用的原事件会进入 agent 的 `focused_events`，即使已离开最近 20 条事件窗口。

HOLD 在其他玩家后续的正常公开行动（包括 PASS/HOLD）后开放反应机会；多名等待者按原发言顺序处理。SKIP 只跳过当前机会，仍可等下一次。质询先收回应，再处理这次正常行动带来的 HOLD 窗口。REACT 最多一次，不额外收费；RESPOND/REACT 不再触发新窗口，也不能叠加 COMMIT。讨论关闭时，未用 HOLD 作废且不退款，包括最后发言者的 HOLD。

队长只可在讨论关闭后付费替换一名队员，不重新讨论。强投票仅加强公开承诺，**始终是一票**；所有票及其 Resolve 扣款收齐后一同公开，收票期间不会泄露余额变化。所有付费行动带 `resolve_cost` / `resolve_after`，新任务轮有 `RESOLVE_REFRESH`，可从公开 JSONL 重建余额。花费、沉默和承诺是行为证据，不购买隐藏信息，也没有自动数值加成。

引擎调用兼容性：正常社交仍可调用 `Game.social(..., committed=True/False)`，其他讨论/回应/定稿行动通过 `Game.act(actor, action)`；讨论后必须显式 LOCK 或 REVISE 才能调用 `Game.vote(..., strong=...)`。新增 `challenge`、`reaction`、`revision`、`vote` 阶段；`Game.view()` 提供 `next_actor`、`legal_actions`、公开余额与待反应状态。公开事件编号因新事件插入而变化，应使用实际 `seq`。

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

配置读取规则：

- 默认仅加载本项目根目录 `.env`，不会向上搜索其他项目。
- 项目 `.env`（或 `--env-file` 指定文件）中的同名配置优先；`override=True`，避免终端中的其他 API 密钥覆盖本项目配置。文件未定义的变量仍可由进程环境提供。
- 支持 Windows UTF-8 BOM；`encoding="utf-8-sig"`。
- 不展开 `${...}`；`interpolate=False`。
- 若要完全使用进程环境变量，启动前设置 `PYTHON_DOTENV_DISABLED=1`，禁止加载配置文件。导入模块不会读取密钥或调用网络。

兼容别名按优先级读取：

| 项目 | 优先级 |
| --- | --- |
| key | `OPENAI_API_KEY` → `LLM_API_KEY` → `DEEPSEEK_API_KEY` |
| base URL | `OPENAI_BASE_URL` → `LLM_BASE_URL` → `LLM_API_URL` |
| model | `OPENAI_MODEL` → `LLM_MODEL` → `DEEPSEEK_MODEL` |

只有 DeepSeek key 时，默认 base URL 为 `https://api.deepseek.com`，仍需配置模型。其他情况默认 OpenAI base URL。混用不同前缀时，以表中的优先级为准。

请求使用 OpenAI-compatible Chat Completions。`OPENAI_TOKEN_LIMIT_FIELD` 可设置 `max_completion_tokens`，以适配要求该字段的模型；默认 `max_tokens` 便于兼容其他服务。可用 `OPENAI_JSON_MODE=true` 开启 JSON object 模式。参数依据：[OpenAI API 官方文档](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)。

**没有 key/model 或配置无效时，程序会说明缺失项并退出，不会开始模拟对局。** 超时、连接失败、限流、常见服务端错误、空响应、格式错误、截断输出或非法计划会自动重试。默认最多重试 2 次，加上首次调用共 3 次；重试前分别等待 2 秒、4 秒。终端会显示当前玩家、错误代码和重试进度，例如 `[RETRY] [SAGE/P5] 调用失败（invalid_response），2 秒后重试（1/2）…`。

重试期间保留同一玩家、同一提案及相同的对局、记忆和战术上下文，不推进对局。行动校验失败时，下一次请求会附带宿主生成的 `validation_feedback`，说明需要修正的结构或规则；不回传失败原文，也不将反馈写入公开事件或私有记忆。只有获得有效结果才写入发言和私有记忆。全部尝试失败才停止，不生成替代行动。密钥、余额、参数等不可恢复的错误以及模型拒答会直接停止；DeepSeek 的错误含义可参考[官方错误码说明](https://api-docs.deepseek.com/quick_start/error_codes/)。

`invalid_plan` 表示模型返回的 JSON 已解析，但行动结构、字段或规则校验未通过。开发排查时，`--debug-strategy` 会在私有调试通道显示具体校验原因；普通游戏界面保持统一错误码，避免透露角色或战术信息。

可在 `.env` 中用 `OPENAI_MAX_RETRIES` 设置额外重试次数（0–5，0 表示不重试），用 `OPENAI_RETRY_DELAY_SECONDS` 设置首次等待秒数（0–30）。后续等待时间翻倍，单次最多 30 秒。等待或请求过程中可按 Ctrl+C 退出。错误会区分 `invalid_response`（格式错误）、`empty_response`（空响应）、`truncated_response`（输出截断）等，便于调整配置。

旧版的 `--mock` 参数已移除。请求按发言顺序串行执行，`AVALON_LLM_CONCURRENCY` 不再使用。输出上限默认 2400 tokens，可通过 `OPENAI_MAX_TOKENS` 调整。

## 按顺序实时发言

每次选队提案按以下顺序推进：

1. 如果队长是 AI，先准备选队。善良 AI 使用模型排名；邪恶 AI 由策略代码直接确定队伍，在后续发言时由 LLM 解释选择。
2. 公开队伍和发言顺序：从队长开始，按座位顺序绕桌一圈。
3. 轮到某个 AI 时，才把当前队伍、此前发言和其合法私有信息发送给 LLM；邪恶 AI 额外收到当次精简战术上下文。
4. 发布选择的讨论行动；社交牌分行显示表态和理由摘要。处理这次行动的质询回应与 HOLD 反应窗口，再轮到下一位正常发言者。
5. 讨论关闭，队长 LOCK 或 REVISE；善良 AI 按最近模型策略投票，邪恶 AI 按代码策略投票和协调任务牌。强投票沿用该票的赞成/反对方向。提案被否决后，新队长重新选队，所有人重新获得讨论机会，Resolve 余额保持不变。

善良 AI 的模型计划包含身份和行为估计、策略、选队排名、投票阈值和社交行动。两阵营的模型都选择 Resolve 讨论行动、后续修订策略及强投票意愿。邪恶 AI 不能覆盖共享战略、概率、初始队伍、普通投票方向、任务牌或刺杀目标。投票、任务执行和刺杀本身不额外调用 LLM。

对于只返回社交行动的协议，如果服务把六个社交字段直接放在顶层，程序会补回 `social` 外层包装，再执行相同的字段、目标、卡牌、依据和隐私校验；不会补造缺失的决策，也不会忽略额外字段。

没有失败或额外回应窗口时，每个 AI 的正常讨论调用一次，善良 AI 队长选队另加一次；邪恶队长选队不额外调用模型。普通五人局每次提案共 4–5 次请求，六人局 5–6 次；全 AI 演示分别为 5–6、6–7 次。Resolve 选择加入这次计划的 `discussion`、`revision`、`strong_vote` 字段，不单独调用资源管理模型；队长修订与强投票按该计划的后续策略执行，若期间余额不足则采用免费 LOCK / 普通票。

真实 CHALLENGE/HOLD 窗口用一次短请求，根据最新公开事实选择结构化回应或跳过；0 Resolve 的被质询者直接免费 DECLINE。窗口按「任务轮 / 提案 / 阶段 / 触发事件」缓存，单个窗口不会重复请求，也不会递归生成新窗口。正常计划仍按「任务轮 / 提案 / 阶段」缓存。重试会增加实际请求数，结束时 `[CALLS]` 包含失败和重试。旧版仅有 `social` 的计划仍兼容：按普通社交成本扣费，余额为 0 时 PASS，不使用修订或强投票；新版提示词要求显式选择资源策略。

善良 AI 首次调用发送的历史画像为 `beliefs={}`、`profiles={}`，并标记 `no_previous_model`，不发送 mock 画像或虚构往局记录。成功生成计划后，才把实际模型估计与后续公开观察带入下一次调用。邪恶 AI 使用代码维护的当前战术，不接收另一名 AI 的私有模型输出。失败尝试不会被当作模型历史。

发言字段 `statement` 和理由摘要 `rationale` 各最多 240 字符，社交牌的 `evidence` 可引用最多 3 条可见公开事件编号，仅保留在结构化事件和 agent 上下文中。CITE/CHALLENGE 的单个事件引用会在终端显示。理由摘要说明当前判断、倾向和不确定性；不会读取或展示服务商返回的内部 `reasoning_content`。

## 双邪恶混合策略 v2

每局自动创建一个 `EvilStrategyManager`，由两个邪恶 AI 共享。它只接收玩家 ID、已知邪恶成员和真实公开事件，**不读取真正的 Merlin 身份**。善良 AI（包括 Merlin）不能绑定这个共享状态。Avalon 规则、任务和投票结果仍由 `Game` 独立校验。

```text
Game 公开事件 → EvilSharedState → 策略评分和合法行动
                                      ↓
                              小型 TacticalContext
                                      ↓
                         LLM Resolve 选择与自然发言
                                      ↓
                              校验 → Game 公开事件
```

代码维护嫌疑、信任、关联度、行为标签、Merlin 概率、Aggressor/Sleeper 分工、战术目标、牺牲对象、失败票负责人和有公开依据的叙事。状态跨任务轮保存，在新对局重新创建。模式采用局势评分加小幅随机变化；`--seed` 同时控制独立的策略随机序列，模型原文仍不保证重复。

| 模式 | 代码控制的行为 |
| --- | --- |
| `NORMAL_DECEPTION` | 一方主动试探，另一方低调建立信任 |
| `FAKE_CONFLICT` | 关联嫌疑、持续同票或过度保护提高切割倾向；强度随局势变化 |
| `CONSENSUS_SEEDING` | 以真实表态播种观点，有其他玩家介入后才由队友逐步呼应 |
| `AGENDA_CAPTURE` | 围绕真实公开记录改变当前讨论重点 |
| `MERLIN_HUNT` | 累计准确判断和投票信号，试探可疑对象；一次行为不会锁定 Merlin |
| `SACRIFICE` | 高嫌疑成员牺牲自身信用，保护安全队友并制造误导关联 |
| `CRISIS_RECOVERY` | 两人都暴露时降低风险并提供竞争性解释 |

每次只分配一个主目标和最多一个次目标。社交牌范围与目标由代码分配，LLM 决定是否花费 Resolve、使用什么讨论机会，以及具体攻击、辩护、施压和解释。指定战术不强制付费；邪恶 AI 也可以有余额却选择 PASS。两名邪恶 AI 不共享完整计划或内部推理。公开文字泄露明显身份、战术字段或目标名称时，会重新请求；耗尽重试即停止，不生成固定替代台词。公开错误统一显示 `invalid_plan`，内部原因 `private_disclosure` 仅出现在开发者调试通道，避免由错误类型暴露阵营。

两名邪恶 AI 同队执行任务时，由 `mission_fail_owner` 协调至多一张 FAIL；负责人会结合暴露程度、历史和随机变化选择。5/6 人局仍严格遵守一张 FAIL 即任务失败。人类玩家的操作始终保留：先收取人类秘密任务牌，若人类邪恶成员已经出 FAIL，AI 不再追加；善良玩家仍只能出 SUCCESS。

开发者可以单独查看战略更新及结构化决策轨迹：

```sh
python -m avalon --demo --seed 7 --debug-strategy --strategy-log private-strategy.jsonl --log public-game.jsonl
```

`--debug-strategy` 将内部状态写入 **stderr**；请求前显示 `EVIL TACTICAL PLAN`，实际发言被游戏接受后才写入对应的战略记录。`--strategy-log` 保存独立私有 JSONL，包含阶段、玩家、模式、目标、置信度及实际结构化行动，不含完整推理或原始模型响应。失败或取消的发言不会生成已执行的社交记录。这些内容不会进入公开事件、公开日志或善良玩家的模型上下文。正常游玩省略这两个开发者选项；在同一终端打开调试时会看到隐藏战略。公开和私有日志必须用不同路径，不能覆盖环境配置。

目前已实现 P0，以及七种模式所需的公开评分、保护限制、叙事、行为标签和 Merlin 估计基础。评分是可复现的启发式假设，不代表身份事实或已验证的胜率提升。人格权重层、让 LLM 提议战略再由代码批准的扩展尚未启用。显式泄漏检查可阻止字段照抄和常见自报身份表达，不能证明任意自然语言隐喻都没有信息泄漏。

## 私有记忆和公开日志

- 裁判广播公开结构化事件；每个 agent 看到自己的角色、合法已知座位、所有公开 Resolve 余额和最近 **20 条事件**，另有当前 CITE / 回应窗口涉及的少量原始公开证据。
- 最多 5 条任务汇总、最多 6 条近期证据，加上各自压缩后的 belief/profile 进入下一次调用上下文；不会重发完整聊天记录。
- 社交牌更新公开信任信号与攻击倾向；被施压后的反击更新 retaliation；投票更新 approval/consensus；任务结果更新身份估计。这些值影响后续选队、投票与 probe 目标。
- 模型输出只接受指定字段、有限数值、有效座位和枚举；仅允许 `statement` 与 `rationale` 作为公开短文本，每项最多 240 字符，拒绝换行和终端控制字符。
- 公开理由可引用最多 3 条实际可见事件编号，终端每条公开事件均带 `[#编号]` 方便核对。重复或过长的有效引用列表会本地去重、取前三条，保留模型决策；不存在的引用仍拒绝。投票规律或任务证据类理由必须引用对应记录。自然语言属于玩家的观点与主张，不是裁判确认的事实。
- 所有 AI 的公开文本都要通过显式身份泄露检查，邪恶 AI 额外检查私有战术信息。失败时重新请求模型，耗尽重试即停止，不生成固定替代台词。原始响应与 `reasoning_content` 均不打印或保存；这不保证自由发言无法被其他玩家推断身份。
- `[PRIVATE]` 只用于本地人类的角色与秘密输入提示，**不会**进入 JSONL，也不会发送给其他 agent。
- `--log` 保存完整公开事件，包含赛后身份揭晓。`--dossier` 仅在比赛结束后打印有限的画像、策略和社交行动摘要，不显示公开依据，不包含 chain-of-thought。
- 画像是单局内的游戏状态；MVP 没有数据库、跨局记忆或外部 agent 框架。AI 的自然语言发言属于当前对局，人类输入仍采用卡牌和选项。

## 目录

```text
terminal-avalon/
├── avalon/
│   ├── __main__.py     # python -m avalon
│   ├── engine.py       # 规则、隐藏身份、公开事件、胜负
│   ├── agents.py       # 独立私有记忆、逐次发言计划、行动策略
│   ├── evil_strategy.py # 私有共享战略、战术目标和行动协调
│   ├── evil_state.py    # 公开事件驱动的邪恶阵营估计与有限叙事
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

自动化测试覆盖基础规则、随机队长与发言方向、顺序请求、失败重试、真人输入和多个 seed 的完整对局。v2 另外覆盖七种策略、动态分工、假冲突与牺牲、单人破坏任务、人类任务票、公开事件驱动的关联判断与 Merlin 估计、固定 seed 复现、上下文隔离、拒绝模型覆盖战略，以及公开错误和私有调试分流。

Resolve 测试覆盖初始化、付费与非法动作原子性、拒绝后保留、任务轮刷新、质询与拒绝、HOLD 的顺序和到期、单人修订、强投票计票及收票保密、0 点继续游戏、Human/AI 相同校验、主动保留点数，以及完整 5/6 人局的公开余额重建。模型边界使用受控响应；这些测试验证规则与接口，不代表真实模型的节省资源频率或对局质量评测。

测试仅在外部模型边界提供受控响应，不需要真实密钥，正式游戏不加载测试数据。旧版 API 与离线运行记录见 [examples/README.md](examples/README.md)，其中调用次数与当前版本不同。本次 v2 使用现有本地配置的 DeepSeek V4 Flash 完成两名邪恶 AI 的连续真实发言，两次均在首次请求通过校验并进入公开事件；没有修改本地模型配置。这是接入验证，不是整局模型质量或胜率评测。
