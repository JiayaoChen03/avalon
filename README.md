# Terminal Avalon MVP

一个可以直接在终端玩的 **1 名人类 + 4/5 个 LLM agent** 社交推理游戏。保留 Avalon 基础规则，玩家依次选择沉默或消耗 Resolve 进行公开交流。AI 通过短手稿与 social card 留下永久记录，死亡与重生之间保留重要记忆。善良 AI 维护独立判断与画像；邪恶 AI 共享代码维护的战略状态，并各自生成简短手稿。

**Python 3.10+，需要配置真实 LLM 服务。启动时自动读取配置，不使用 mock 或失败回退。**

Agent 使用完整角色配置的概率联合信念，角色边际、队伍风险和条件概率均由代码推导。规则排除不可能的配置，模型只解释结构化语言证据，再从更新后的信念选择行动。证据去重、审计和开发视图见 [Agent cognition](docs/agent-cognition.md)；终端使用 `--debug-cognition` 查看独立私有调试输出。

## Godot 图形界面

现在可以通过图形界面操作整局比赛。用 Godot 4（本机已验证 4.8.dev6）打开
[`frontend-godot/project.godot`](frontend-godot/project.godot)，点击「运行项目」；
macOS 也可双击项目根目录中的 **Play Avalon.app**。
Python 后端会自动启动，沿用现有 `.venv` 和 `.env` 配置，游戏过程中无需终端输入。
界面为中文，支持 5/6 人、身份揭晓、选队、全部 Resolve（决心）操作、密封投票、匿名任务、安全轮、任务后议会与三选一出局投票、刺杀和重新开局。
中央「圆桌手稿」展示已落笔的短句、作者、行动和稳定记录 ID，玩家席位分列两侧。
可按角色或关键词、记录编号筛选；翻看旧记录时，新回答不会拉走阅读位置，点击「回到最新」恢复跟随。
「编年史」保存公开行动。引文、记录编号和回应链接都可打开原始记录，角色座位显示当前世数。
AI 思考期间仍可查阅历史，筛选与页签在刷新后保留，新开一局时清除。
真人也可输入短句并选择引用。所有手稿都可能成为后续证据。
AI 请求失败时会停在当前决策，可在界面点击重试。
安装要求、结构和验证说明见 [Godot UI README](frontend-godot/README.md)。

### PixiJS 网页界面

`Assets/` 是同一套游戏的网页前端。先启动本地浏览器后端（默认离线联调，不调用外部模型），再启动 Vite：

```sh
PYTHONPATH=. .venv/bin/python -m avalon.web_server --mode offline --port 8765
cd Assets && npm run dev
```

打开终端提示的本地地址即可。网页端通过 `/api/session`、`/api/state` 和 `/api/command` 使用现有 `GameSession`；规则、身份、投票、任务结算和公开记录不会在前端重复实现。需要真实模型时，将后端参数改为 `--mode live` 并确保 `.env` 已配置。

本地试用真实 API 与 V5 梅林投票策略时，可以单独构建并启动一个网页后端，保留已有的离线联调会话：

```sh
cd Assets && npm run build && cd ..
PYTHONPATH=. .venv/bin/python -m avalon.web_server --mode live --merlin-policy v5 --port 8766 --assets-dir Assets/dist
```

打开 `http://127.0.0.1:8766`。V5 只作用于 AI 梅林的投票；真人梅林仍由玩家自己投票。未指定 `--merlin-policy v5` 时默认使用原投票策略。网页显示的是本地试用配置，不代表 V5 已通过生产效果门槛；R5 配对全局测试的结论仍为 `FULL_GAME_EFFECT_NOT_ESTABLISHED`。

新启动的 live 网页默认启用“积极发言”：讨论或议会阶段，只要能够合法支付 1 点决心，就要求模型生成简短的公开发言；证据不足时表达保留意见或提出问题。沉默及“沉默却附带草稿”的回复会被拒绝并限次重试，不会被程序改写成发言。决心耗尽时仍可沉默。该行为独立于 V5 投票策略；需要原讨论策略时添加 `--discussion-policy baseline`。正在运行的旧后端需要新进程才能加载修复。

新启动的 live 后端会在终端打印本地 AI 行动诊断文件路径。该文件记录失败尝试的阶段、合法行动、重试次数、固定校验原因和响应 ID；讨论行动成功提交后还记录实际行动种类、事件序号及回复中是否有未使用的发言草稿。文件不记录密钥、提示词、角色或模型回复正文。正在运行的旧进程不会自动加载这一诊断功能。

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

启动时默认加载 [腐化城堡 system prompt](prompts/corrupted_castle_system.md)，并显示 `[WORLD] 腐化城堡`。所有角色都以在被腐化的中世纪城堡中活下来为个人动机，围绕外出搜寻物资、名单、信任和风险发言。旧神监听言语，因此所有公开交流都是手写。文字通常为 1–3 个短句；沉默也是合法选择。

角色使用自然、日常的现代中文，像平时玩桌游时一样直接讨论队伍、投票和任务。直接称呼 P2、P3，不再使用「阁下、旧卷、守誓」等中世纪措辞，也不照搬历史记录里的古风句式。不同角色仍可表达不同性格，但不强制同一套口头禅、不编造剧情。质询回应、补记和任务后议会采用相同的日常表达。

提示词在每局开始时读取，后续发言和重试使用同一份内容；修改提示词文件后重新开局生效，修改 Python 协议文本还需重启后端。缺失、空白或编码无效会在开局前报错。选队、投票、任务及胜负仍按下述规则结算。危险轮的失败远征导致全体队员死亡，安全轮失败则只计分、不致死；议会出局也会死亡，在下一任务轮以原身份重生。重生延续关系判断、承诺、前世摘要和重要记忆，不重发完整历史。终局没有下一轮时保留待重生状态；重新开局是独立对局。读取和安装方式见 [提示词说明](prompts/README.md)。

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
| 议会提名 | `P2` | 本次任务队长提名一名仍存活的角色 |
| 出局投票 | `A` / `R` / `B` | 赞成 / 反对 / 弃票；回车为弃票，均免费 |
| 刺客行动 | `P2` | 三次任务成功后选择 Merlin |

每次提案，从队长开始按座位顺序获得一次正常讨论机会，可以 PASS 或选择付费行动；社交牌可重复使用。AI 会阅读此前的公开发言，再选择是否落笔。已有社交牌语义保留；花费 Resolve 或加强承诺不会直接增加信任、嫌疑或任务分数。

开局通过 `[DIRECTION]` 公布本局发言方向：`clockwise` 为顺时针（座位号递增），`counterclockwise` 为逆时针（座位号递减）。每次提案均从当前队长开始，终端打印完整 `[SPEAKING ORDER]`，正常讨论、回应和反应结束后，由队长锁队或替换一人，再投票。方向整局固定，队长仍按座位号递增轮换。

每位 agent 的公开行动只展示简短 **手写文字** 和有效引文。内部判断不显示给玩家。ACCUSE 支持引用旧世记录；不存在的引用会触发内部纠正，不能凭空补造。没有足够证据时可以保留判断、检索旧记录或 PASS；沉默无需生成文字。

## Chronicle 与跨世记忆

**编年史记住一切，角色记住重要的事。** 原有事件日志就是 Chronicle，记录 ID 采用 `R{轮次}-{全局 seq}`，例如 `R2-043`，一局内稳定且唯一。图形界面和终端正常运行会自动追加保存到 `~/.avalon/chronicles/<对局 ID>.jsonl`，`--log` 仍可另存公开日志。角色无权修改记录；完整档案不会放进模型上下文。

| 记忆层 | 固定上限 | 作用 |
| --- | --- | --- |
| Working Memory | 8 条事件 | 近期重要观察 |
| Belief State | 按当前 5/6 个角色维护 | 既有身份概率、行为画像、信任与最近 3 条判断依据 |
| Life Memory | 最近 3 世，每份至多 850 字符 | 死亡时提取重要关系、承诺和未解决指控；更早生命压缩成计数及 5 个历史锚点 |
| Memory Scars | 最强 5 条 | 历史偏向可衰减，新证据可以改变判断 |
| Chronicle retrieval | 每次最多 5 条 | 找回精确手稿、指控、辩护、死亡与远征记录 |

死亡反思由确定性代码提取，不额外请求模型。记忆和原身份在下一轮延续；失败票的作者始终保密。提名或先前指控可以成为怀疑线索，不能被当成杀人事实。档案可从磁盘重新读取；当前未实现退出后恢复整局私有状态，也不把终局揭晓的身份带入新对局。

实现与复现方法见 [记忆架构说明](docs/agent-memory.md)。

## Resolve / Action Points

每名玩家每个 **Mission Round 有 3 Resolve**，余额公开，由 `Game` 管理。任务后的议会讨论共用本轮剩余点数；出局投票结束、进入下一任务轮才恢复到 3；**提案被否决不会恢复**，未使用的点数不累积。终端显示如 `[P1] RESOLVE ●●○ (2/3)`。

| 行动 | Resolve 成本 |
| --- | --- |
| PASS、普通投票、出局提名与投票、正常选队、任务 SUCCESS/FAIL、刺杀、LOCK | 0 |
| SOCIAL、CHALLENGE、RESPOND、CITE、HOLD、REVISE、STRONG VOTE | 1 |
| COMMITTED SOCIAL | 2（含普通社交牌的 1） |
| DECLINE、SKIP、已预付的 REACT | 0 |

有余额也可以选择 PASS，为后续提案、更有价值的证据、回应或投票保留机会。0 Resolve 仍能完成所有 Avalon 基本环节。回车只执行免费动作：讨论 PASS、质询 DECLINE、反应 SKIP、定稿 LOCK、投票普通 APPROVE。

CHALLENGE 必须引用涉及目标的已有公开行动；目标立即获得一次 RESPOND/DECLINE 机会，之后照常保留自己的正常轮次。CITE 只突出旧证据，原事件保持不变；当前提案引用的原事件会进入 agent 的 `focused_events`，即使已离开最近 20 条事件窗口。

HOLD 在其他玩家后续的正常公开行动（包括 PASS/HOLD）后开放反应机会；多名等待者按原发言顺序处理。SKIP 只跳过当前机会，仍可等下一次。质询先收回应，再处理这次正常行动带来的 HOLD 窗口。REACT 最多一次，不额外收费；RESPOND/REACT 不再触发新窗口，也不能叠加 COMMIT。讨论关闭时，未用 HOLD 作废且不退款，包括最后发言者的 HOLD。

队长只可在讨论关闭后付费替换一名队员，不重新讨论。强投票仅加强公开承诺，**始终是一票**；所有票及其 Resolve 扣款收齐后一同公开，收票期间不会泄露余额变化。所有付费行动带 `resolve_cost` / `resolve_after`，新任务轮有 `RESOLVE_REFRESH`，可从公开 JSONL 重建余额。花费、沉默和承诺是行为证据，不购买隐藏信息，也没有自动数值加成。

引擎调用兼容性：正常社交仍可调用 `Game.social(..., committed=True/False)`，其他讨论/回应/定稿行动通过 `Game.act(actor, action)`；讨论后必须显式 LOCK 或 REVISE 才能调用 `Game.vote(..., strong=...)`。新增 `challenge`、`reaction`、`revision`、`vote` 阶段；`Game.view()` 提供 `next_actor`、`legal_actions`、公开余额与待反应状态。公开事件编号因新事件插入而变化，应使用实际 `seq`。

## 安全轮与任务后议会

首轮为危险任务轮。每次完成出局投票后，**下一任务轮为安全轮**，无论是否有人出局。每次任务都接议会，因此正常对局从第二任务轮起均为安全轮；提案被否决不消耗或改变本轮安全状态。安全轮仍正常选队、秘密出任务牌和计分，一张 FAIL 仍使任务失败，但不会杀死队员。安全保护不阻止议会出局。

每次任务结束，先展示任务结果，再依次进行：

1. 全员按本次任务队长起始的原定方向讨论一次，可以保持沉默，也可使用原有质询、引证和反应行动。
2. 本次任务队长提名一名仍存活的角色，可以提名自己；此时不能再改任务队伍。
3. 全员对这名候选人投 **赞成 / 反对 / 弃票**。收齐前保密，每人一票，无强票、无决心花费。
4. 赞成严格超过全员半数才出局：5 人需 3 票，6 人需 4 票；平票不通过，弃票计入全员人数。界面显示逐人选票及三种票数。
5. 出局角色死亡；点击继续后，在下一任务轮重生，保留身份和记忆。队长轮换、全员决心恢复，并开始安全轮。

议会按固定席位举行，等待重生的角色也保留讨论、提名和投票权，但不能被再次提名。出局提名、选票与结果进入编年史，角色可以记住谁支持或反对自己出局，并引用原始记录。

决定三胜或三败的最后一次任务也先完成议会，再结算原有胜负。出局不改变角色与阵营，也不取消刺客的最终行动或被刺杀资格；已出局的角色不会重复记录死亡。终局无下一任务轮时，不立即重生。

引擎阶段依次为 `council_discussion` → `exile_nomination` → `exile_vote` → `council_result`。分别通过原有 `act()`、`nominate_exile()`、`vote_exile()`、`finish_council()` 推进。`Game.view()` 包含本轮安全状态、候选人、可提名对象与所需赞成票数。

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
4. 发布选择的讨论行动；社交牌显示短手稿及引文。处理这次行动的质询回应与 HOLD 反应窗口，再轮到下一位正常发言者。
5. 讨论关闭，队长 LOCK 或 REVISE；善良 AI 按最近模型策略投票，邪恶 AI 按代码策略投票和协调任务牌。强投票沿用该票的赞成/反对方向。提案被否决后，新队长重新选队，所有人重新获得讨论机会，Resolve 余额保持不变。

善良 AI 的模型计划包含带引用的软证据解释、策略、选队排名、投票阈值和社交行动；身份联合假设、权重与行为画像由代码维护。两阵营的模型都选择 Resolve 讨论行动、后续修订策略及强投票意愿。邪恶 AI 不能覆盖共享战略、概率、初始队伍、普通队伍投票方向、任务牌或刺杀目标。队伍投票、任务执行和刺杀本身不额外调用 LLM。任务后议会讨论使用一次新计划，议会提名和每张出局票分别选择一个简短决策；邪恶 AI 同时收到当前战术提示。有待解释发言时，先执行一次有界语言解释，由代码更新概率，再选择行动。所有最终响应使用认知信封，实际行动位于 `recommended_action`。

对于只返回社交行动的协议，如果服务把完整社交字段直接放在顶层，程序会补回 `social` 外层包装，再执行相同的字段、目标、卡牌、依据和隐私校验；不会补造缺失的决策，也不会忽略额外字段。

没有失败、主动检索或额外回应窗口时，每个 AI 的正常讨论调用一次，善良 AI 队长选队另加一次；邪恶队长选队不额外调用模型。普通五人局每次提案共 4–5 次请求，六人局 5–6 次；全 AI 演示分别为 5–6、6–7 次。Resolve 选择加入这次计划的 `discussion`、`revision`、`strong_vote` 字段，不单独调用资源管理模型；队长修订与强投票按该计划的后续策略执行，若期间余额不足则采用免费 LOCK / 普通票。

真实 CHALLENGE/HOLD 窗口用一次短请求，根据最新公开事实选择结构化回应或跳过；0 Resolve 的被质询者直接免费 DECLINE。窗口按「任务轮 / 提案 / 阶段 / 触发事件」缓存，单个窗口不会重复请求，也不会递归生成新窗口。正常计划仍按「任务轮 / 提案 / 阶段」缓存。重试会增加实际请求数，结束时 `[CALLS]` 包含失败和重试。旧版仅有 `social` 的计划仍兼容：按普通社交成本扣费，余额为 0 时 PASS，不使用修订或强投票；新版提示词要求显式选择资源策略。

善良 AI 没有先前模型计划或前世记录时，兼容的 `memory` 字段为空并标记 `no_previous_model`；准确的初始知识与代码推导假设始终位于独立认知字段。后续模型只解释有限新证据，代码更新假设并保留证据来源。邪恶 AI 使用代码维护的当前战术，不接收另一名 AI 的私有模型输出。失败尝试不会被当作模型历史。

模型使用 `social.public_writing`（单行、最多 240 字符）与 `social.citations`（最多 3 个真实 Chronicle ID）。旧的 `statement/rationale/evidence` 输入继续兼容，但不再展示额外理由摘要。模型可先返回一次 `memory_query`，宿主检索最多 5 条历史记录后再请求最终行动；这会增加一次模型请求。不会读取、展示或归档服务商的内部 `reasoning_content`。

## 双邪恶混合策略 v2

每局自动创建一个 `EvilStrategyManager`，由两个邪恶 AI 共享。它只接收玩家 ID、已知邪恶成员和真实公开事件，**不读取真正的 Merlin 身份**。善良 AI（包括 Merlin）不能绑定这个共享状态。Avalon 规则、任务和投票结果仍由 `Game` 独立校验。

```text
Game 公开事件 → EvilSharedState → 策略评分和合法行动
                                      ↓
                              小型 TacticalContext
                                      ↓
                         LLM Resolve 选择与简短手稿
                                      ↓
                              校验 → Game 公开事件
```

代码维护公开声誉、信任、关联度、行为标签、Aggressor/Sleeper 分工、战术目标、牺牲对象、失败票负责人和有公开依据的叙事。身份与 Merlin 概率由每名 Agent 自己的联合角色分布推导，策略管理器不再维护独立的身份评分。状态跨任务轮保存，在新对局重新创建。模式采用局势评分加小幅随机变化；`--seed` 同时控制独立的策略随机序列，模型原文仍不保证重复。

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

- 裁判广播公开结构化事件；每个 agent 看到自己的角色、合法已知座位、所有公开 Resolve 余额和最近 **8 条重要事件**（引擎的兼容视图仍最多 20 条），另有当前 CITE / 回应窗口涉及的少量原始公开证据。
- 最多 5 条任务汇总、8 条 Working Memory、5 条检索结果，加上各自的 belief/profile、关系和固定大小的前世记忆进入下一次调用；不会重发完整历史。
- 社交牌更新公开信任信号与攻击倾向；被施压后的反击更新 retaliation；投票更新 approval/consensus；任务结果更新身份估计。这些值影响后续选队、投票与 probe 目标。
- 模型输出只接受指定字段、有限数值、有效座位和枚举；新协议仅允许 `public_writing` 作为公开短文本，最多 240 字符，拒绝换行和终端控制字符。
- 公开理由可引用最多 3 条实际可见事件编号，终端每条公开事件均带 `[#编号]` 方便核对。新协议要求至多 3 个不重复的 Chronicle ID；旧整数引用列表仍可本地去重、取前三条，不存在的引用始终拒绝。投票规律或任务证据类理由必须引用对应记录。自然语言属于玩家的观点与主张，不是裁判确认的事实。
- 所有 AI 的公开文本都要通过显式身份泄露检查，邪恶 AI 额外检查私有战术信息。失败时重新请求模型，耗尽重试即停止，不生成固定替代台词。原始响应与 `reasoning_content` 均不打印或保存；这不保证自由发言无法被其他玩家推断身份。
- `[PRIVATE]` 只用于本地人类的角色与秘密输入提示，**不会**进入 JSONL，也不会发送给其他 agent。
- `--log` 保存完整公开事件，包含赛后身份揭晓。`--dossier` 仅在比赛结束后打印有限的画像、策略和社交行动摘要，不显示公开依据，不包含 chain-of-thought。
- 画像是单局内的游戏状态；MVP 没有数据库、跨局记忆或外部 agent 框架。记忆可跨当前局的多次生命延续；图形界面中的真人也可输入手稿与引文。

## 目录

```text
terminal-avalon/
├── avalon/
│   ├── __main__.py     # python -m avalon
│   ├── engine.py       # 规则、隐藏身份、公开事件、胜负
│   ├── agents.py       # 独立判断、有限上下文、行动策略
│   ├── memory.py       # 前世摘要、记忆伤痕、关系与承诺
│   ├── chronicle.py    # 不可改写的公开历史、稳定 ID、检索
│   ├── joint_beliefs.py # 完整角色配置、归一化与概率查询
│   ├── evidence.py      # 合法观察、证据类型、去重与似然
│   ├── cognition.py     # 每席认知、更新审计与公开立场
│   ├── theory_of_mind.py # 有界二阶接口（尚未启用估算）
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

联合信念的离线效果评测见 [本地评测说明](docs/joint-belief-evaluation.md)。安装 `python -m pip install -e '.[eval]'` 后，一条命令依次运行 pytest 正确性测试、固定记录回放、20 组配对冒烟测试和 500 组配对比赛，并导出置信区间、CSV、图表和报告；不调用外部模型：

```sh
python -m avalon.eval.joint_belief --games 500 --variants baseline,joint_belief --seed 1000 --output-dir results/joint_belief
```

测试仅在外部模型边界提供受控响应，不需要真实密钥，正式游戏不加载测试数据。旧版 API 与离线运行记录见 [examples/README.md](examples/README.md)，其中调用次数与当前版本不同。本次 v2 使用现有本地配置的 DeepSeek V4 Flash 完成两名邪恶 AI 的连续真实发言，两次均在首次请求通过校验并进入公开事件；没有修改本地模型配置。这是接入验证，不是整局模型质量或胜率评测。
