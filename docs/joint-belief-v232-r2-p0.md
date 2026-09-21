# Joint Belief v2.3.2-r2 P0：响应留存与来源验证

本轮只修复评估链路。生产 belief、证据、任务似然、菜单合同、刺客 native argmax、世界提示词和行动策略不变。`avalon.llm.ChatClient` 新增默认关闭的 `response_sink`；启用时，动作正文 JSON 解析前必须先完成安全证据持久化。供应商独立推理字段不进入 sink。

入口复用 `python -m avalon.eval.v2.v232_runner --mode p0-*`。旧模式保留，旧 pilot 的结果仍是历史结果；本轮交付不自动重启它。

```sh
cd /Users/jiayaochen/Desktop/avalon
python -m avalon.eval.v2.v232_runner --mode p0-tests --run-dir results/joint_belief_v2_3_2/20260919-v232-r2-p0
python -m avalon.eval.v2.v232_runner --mode p0-report-only --run-dir results/joint_belief_v2_3_2/20260919-v232-r2-p0
```

`p0-tests` 先运行 `tests/eval/test_v232_r2.py`，再运行完整 `tests`；保存实际命令、进程退出码、代码哈希、XML 和日志。针对性测试包含在完整回归中，不能把两次执行数当成独立覆盖数。测试只用合成 fixture、本地 HTTP 和实际生产 Game；不加载真实凭据或调用付费服务。

`p0-report-only` 在现有 `offline_guard` 内运行，禁止网络连接、凭据加载及 `ChatClient.complete`。费用从逐请求/响应记录重算，摘要保留原运行的累计请求数，这不是报告重算时新增的请求数。无效 B 输出的效应是 null/UNAVAILABLE。

如需在独立新目录重做只读来源验证，可使用 `p0-prepare`、`p0-verify`；准备默认关闭 live。当前运行已写入 `paid_halt.json`，对它执行 `p0-smoke` 会在读取凭据前拒绝派发，不能删除标记来补满成功数。

## 组件与记录映射

- `v232_persistence.RecordedAttempt`：复用 `DurableBudget`，原子预留后写 reserved/sent/received/validated 状态。一次调用只含一个 transport attempt，没有内层重试。A1/A2 使用不同 logical ID，因此发出独立请求；恢复同一个 ID 只复用本地已保存结果。
- `ResponseJournal`：restricted diagnostic 文件保存安全正文及其 hash；正文权限 0600、运行与正文目录 0700。保留无效 JSON、额外字段及非法枚举；安全脱敏必须标记，脱敏文本不得执行。
- `responses/<attempt>.receipt.json`：修复版在动作 JSON 解析前的完整安全 receipt。r0 实际 smoke 没有该修复版 receipt，只有保留下来的原始 response/journal，不能冒充 r1 运行。
- `requests/*.request.json`：logical/attempt 绑定、配置与 payload hash、合法请求上下文、预留。
- `requests/*.response.json`：结算及校验结果。未知 usage 保留预留，不写零；未知在途请求不自动重发。已确认 reserved 且未写 sent 标记的记录才可显式释放。
- `response_journal.jsonl`：事件序列；一个 attempt 可以有 received/validated 两行，不能当成两个模型响应。`api_attempts.jsonl` 是每 attempt 一行的可重算投影。
- `Session`：继续独占生产动作提交；恢复 accepted/executed 决策不重新调用模型、不重复提交或扣资源。固定快照 smoke 本身不提交游戏动作。
- `v232_replay_verification`：从原始角色配置建立 referee Game，只给各观察者合法视图与公共事件；按历史实际席位版本重放生产事务，逐步校验事件、视图、边际和可用完整 posterior hash。
- `replay_verification.csv` 每行一个来源档案，聚合其全部席位；具体 observer、decision index 与 cutoff 在 `replay_cutoffs.jsonl`。后者包含完整 posterior 是否有历史存档可核验，不能把仅有边际的生成语料称为历史完整 joint 复现。
- `eligible_snapshot_manifest.json` 单独绑定原始请求、来源 cutoff、菜单、posterior、公共前缀和 decoder。精确并列/公开文字是事前适用性条件，不按刺杀成败筛选。

## 本轮真实观察的边界

`20260919-v232-r2-p0` 的初版 smoke 实际发出 3 次请求，均拒绝，正文与 usage 均保存。请求端遗漏现有 `configure_transport`，令旧 full-plan 系统协议与 menu 合同冲突；新保存的三份响应都有冲突字段。旧 r1 丢失的 30 份正文不能恢复，不能据此逐条归因为同一个字段错误。

初版首次失败后仍继续后两次，违反立即停止要求；价格也在请求后才重新核验。这两项偏差保留在报告，不以最终本地测试通过抹除。修复后加入持久化 halt，本轮没有再发付费请求。修正适配器的真实 smoke 为 NOT_RUN，真实语言实验门槛没有通过。

历史 r0 的 HTTP status 未留存，不能回填 200；新 hook 会记录该字段。实际 dispatch 时的完整 r0 源码未另存独立快照，只有当时哈希、逐请求数据及之后的 r0 副本；最终 `delivery_source_snapshot/` 是修正版，不冒充 dispatch 源码。

P1 离线开发可以使用已验证的 cutoff，且必须遵守各行的完整 posterior 存档限制。真实语言实验、候选或完整对局没有在此任务中恢复或启动。
