# 历史运行记录

> 以下内容记录 2026-09-15 的旧版行为，仅作历史参考。当前版本已移除 `--mock` 和错误回退，默认接入真实 LLM 并逐人实时发言；含 `--mock` 的历史命令已不可用，旧版每任务轮一次请求的计数也不适用于当前版本。当前操作说明与验证方法见 [项目 README](../README.md)。这些文件不会被正式游戏加载。

2026-09-15 在 Windows 上通过真实命令行入口运行：一局使用真实 DeepSeek V4 Pro，另两局使用 deterministic/mock。本地 HTTP 集成测试单独验证请求协议与错误降级。

## 五人局 真实 DeepSeek V4 Pro

在本地 `.env` 配置 `OPENAI_MODEL=deepseek-v4-pro`、DeepSeek endpoint、JSON object 输出和 `DEEPSEEK_THINKING=disabled` 后运行：

```sh
python -m avalon --players 5 --seed 12 --direction counterclockwise --log examples/deepseek-live-5.jsonl
```

P1 使用正常 Human 控制器，测试脚本对提示输入回车接受默认值；P2–P5 均使用真实远程模型。这验证人类输入路径与完整 API 对局，不代表真人体验评测。

- [完整终端记录](deepseek-live-5.txt)、[公开事件 JSONL](deepseek-live-5.jsonl)、[核对结果](deepseek-live-summary.json)。
- 第一轮前抽中 P3 为首任队长，此局后两轮依次由 P4、P5 担任队长。
- 开局确定逆时针发言；第一轮顺序为 P3 → P2 → P1 → P5 → P4。模型轮到自己时才请求，按顺序看到前面的公开表态。
- 首位 agent 从空的历史 belief/profile 开始，自由给出开场立场；每个 agent 的表态附公开理由摘要与可核对的事件编号。
- 3 个任务轮，3 次选队、15 次社交行动、15 次公开投票，7 个秘密任务票提交回执和 3 次任务结果。
- 共 **12 次真实 API 请求**，每位 agent 每轮恰好一次；12 个计划全部通过校验，**0 次 fallback**。刺杀没有增加调用。
- 善良三次任务成功，刺客选择 P3，Merlin 存活，最终 GOOD 获胜；退出码 0。
- 本局实际出现 BAIT、HEDGE、PRESSURE；五种牌均由下方 mock 对局和回归测试覆盖。

固定 seed 复现角色与首任队长；真实模型的后续行动不保证复现。记录仅包含终端可见内容与公开事件，未保存服务商原始响应、密钥或 chain-of-thought。

## 五人局 人类输入路径

```sh
python -m avalon --mock --players 5 --seed 7 --dossier --log examples/mock-human-5.jsonl
```

P1 使用正常 Human 控制器；测试脚本依次输入 `P1 P2`、`BAIT P3`、`n`，之后对所有提示输入回车接受默认值。其他四席使用 agent。此项验证人类交互路径，不代表真人体验评测。

- [完整终端记录](mock-human-5.txt)
- [公开事件 JSONL](mock-human-5.jsonl)
- 首任队长抽中 P1，开局确定逆时针；队长和方向均在第一轮前打印。
- 5 个任务轮，6 次选队提案（包含一次否决）。
- 30 次公开社交行动、30 次公开投票，五种社交牌均出现。
- 13 个秘密任务票提交回执，5 次任务结果；无个人秘密任务票泄露。
- 善良完成三次任务后进入刺杀，Merlin 被刺中，最终 EVIL 获胜。
- 退出码 0，所有 agent HTTP 请求数均为 0。

## 六人自动演示

```sh
python -m avalon --demo --mock --players 6 --seed 0 --log examples/mock-demo-6.jsonl
```

- [完整终端记录](mock-demo-6.txt)
- [公开事件 JSONL](mock-demo-6.jsonl)
- 首任队长抽中 P1，开局确定顺时针；队长和方向均在第一轮前打印。
- 5 个任务轮，5 次选队、30 次社交行动、30 次公开投票。
- 16 个秘密任务票提交回执，5 次任务结果；三次任务失败，EVIL 获胜。
- 包含全部六席的公开社交牌、投票及其实际发生的其他行动。
- 退出码 0，HTTP 请求数 0。

## 自动核对内容

运行后解析公开日志，检查首任队长与方向先于第一轮公布；逐个提案检查 **所有玩家按顺序各有一条社交行动，并各有一条投票**；逐个任务检查队员提交回执齐全；确认结束后才出现 REVEAL，公开日志不含 belief/profile 或个人任务牌。mock 计数保存在 [smoke-summary.json](smoke-summary.json)，真实 API 计数保存在 [deepseek-live-summary.json](deepseek-live-summary.json)。终端记录中的 `[PRIVATE]` 仅为 P1 自己合法可见的信息，JSONL 不含这些提示。

## 本地 API 与回归测试

`python -m unittest discover -s tests -v` 共 **44 项测试通过**，其中包含：

- 5/6 人规则、连续五次否决、三次失败、刺杀命中与未命中。
- 首任队长可抽中任意座位，先公布再开始第一轮，后续按座位轮换；发牌与队长使用独立随机序列，避免从公开抽签推断最后座位身份。
- 顺/逆时针开局固定、每次提案从队长起依序发言、越序拒绝、后发者看到实际前序发言；方向也使用独立随机序列。
- 首轮模型上下文没有预填画像、真实响应不先生成 mock 计划、fallback 估计不冒充模型历史。
- 公开短文本拒绝控制字符、保护常见的直接身份泄漏表达、核对引用存在且与理由类型匹配；有效引用过长或重复时本地整理，不追加调用。
- 40 局不同 seed 的完整 mock 对局，以及重复运行的一致性检查。
- 真实本地 HTTP 服务 + 1 人类输入席位 + 4 agents：三轮任务成功后刺杀，共 12 次请求，每位 agent 每任务轮恰好 1 次。
- DeepSeek V4 Pro 的模型名称、可选 `thinking` 参数与 JSON object 请求；其他服务默认不发送 DeepSeek 专有参数。
- 401、429、重定向、连接超时、不完整 HTTP 内容、无效/截断/过深 JSON、极大整数等错误降级。
- 隐藏信息隔离、独立记忆、公开事件驱动的画像变化、非法人类输入和 EOF 退出。

本地 HTTP 测试直连 loopback，使用模拟响应与测试密钥，验证接入协议和调用预算。上方真实 API 对局验证了当次服务可用性，不用于衡量模型游戏水平。
