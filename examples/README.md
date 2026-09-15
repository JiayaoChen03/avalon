# 实际运行记录

2026-09-15 在 Windows 上通过真实命令行入口运行。两局均使用 deterministic/mock，无远程 LLM 请求。另有本地 HTTP 集成测试验证实际请求与降级。

## 五人局 人类输入路径

```sh
python -m avalon --mock --players 5 --seed 7 --dossier --log examples/mock-human-5.jsonl
```

P1 使用正常 Human 控制器；测试脚本依次输入 `P1 P2`、`BAIT P3`、`n`，之后对所有提示输入回车接受默认值。其他四席使用 agent。此项验证人类交互路径，不代表真人体验评测。

- [完整终端记录](mock-human-5.txt)
- [公开事件 JSONL](mock-human-5.jsonl)
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
- 5 个任务轮，5 次选队、30 次社交行动、30 次公开投票。
- 16 个秘密任务票提交回执，5 次任务结果；三次任务失败，EVIL 获胜。
- 包含全部六席的公开社交牌、投票及其实际发生的其他行动。
- 退出码 0，HTTP 请求数 0。

## 自动核对内容

运行后解析公开日志，逐个提案检查 **所有玩家各有一条社交行动和一条投票**；逐个任务检查队员提交回执齐全；确认结束后才出现 REVEAL，公开日志不含 belief/profile 或个人任务牌。计数保存在 [smoke-summary.json](smoke-summary.json)。终端记录中的 `[PRIVATE]` 仅为 P1 自己合法可见的信息，JSONL 不含这些提示。

## 本地 API 与回归测试

`python -m unittest discover -s tests -v` 共 **28 项测试通过**，其中包含：

- 5/6 人规则、连续五次否决、三次失败、刺杀命中与未命中。
- 40 局不同 seed 的完整 mock 对局，以及重复运行的一致性检查。
- 真实本地 HTTP 服务 + 1 人类输入席位 + 4 agents：三轮任务成功后刺杀，共 12 次请求，每位 agent 每任务轮恰好 1 次。
- 401、429、重定向、连接超时、不完整 HTTP 内容、无效/截断/过深 JSON、极大整数等错误降级。
- 隐藏信息隔离、独立记忆、公开事件驱动的画像变化、非法人类输入和 EOF 退出。

本地 HTTP 测试直连 loopback，使用模拟响应与测试密钥。它验证接入协议和调用预算；实际服务商可用性与真实模型的游戏水平仍需用户配置 API 后体验。
