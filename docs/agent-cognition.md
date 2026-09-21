# Agent cognition · 概率联合角色信念

认知沿用 `Game.view()`、Chronicle、AgentState、Resolve、记忆和行动校验。规则决定可能的角色配置，代码根据证据计算后验；模型解释语言并从更新后的信念选择行动。当前游戏仍为 5／6 人、GOOD／MERLIN／ASSASSIN／EVIL，没有新增角色规则。

## 模块边界

| 模块 | 职责 |
| --- | --- |
| `avalon/engine.py` | 合法视图、公开角色数量与阵营映射、任务结算及共享机械约束 `mission_result_constraints`。 |
| `avalon/joint_beliefs.py` | 完整角色配置的精确枚举、对数归一化、边际／联合／条件查询、更新审计结构。 |
| `avalon/evidence.py` | 合法 Observation、HARD／BEHAVIORAL／LANGUAGE Evidence、规范化信号来源、可配置似然模型。 |
| `avalon/cognition.py` | 每个 Agent 独立的 PrivateBeliefs、证据批次、去重、简洁摘要、解释与公开立场。 |
| `avalon/agents.py`、`avalon/llm.py` | 解释阶段 → 更新后验 → 行动阶段 → 校验；兼容旧行动协议。 |
| `avalon/evil_strategy.py`、`avalon/evil_state.py` | Merlin 试探和刺杀使用行动者自己的联合信念；公开声誉仍只用于策略。 |
| `avalon/theory_of_mind.py` | 单目标、显式触发的二阶建模接口；目前没有估算实现或自动调用。 |

`AgentState` 继续分为 `objective_state`、`private_knowledge`、`private_beliefs`、`public_stances`、`observations`、`belief_history`。`PrivateBeliefs` 继承 `JointBeliefState`，底层只有完整角色配置。`worlds`／`possible_worlds` 和 `Agent.memory['beliefs']` 是兼容投影，不是另一套可独立修改的概率。

## 完整角色配置

每个 `JointHypothesis` 含 `roles: {player: role}` 和对外的 `probability`，内部保存 `log_probability`。枚举读取公开配置的多重集合，相同 GOOD 角色不产生重复排列；随后通过私有知识 Observation 排除与自身份、角色可见阵营或明确可见特殊角色冲突的配置。

| 观察者 | 5 人配置数 | 6 人配置数 |
| --- | ---: | ---: |
| 应用私有知识前 | 60 | 120 |
| 普通 GOOD | 24 | 60 |
| MERLIN，已知两个坏人 | 2 | 2 |
| ASSASSIN，已知同伴 | 3 | 4 |
| 普通 EVIL，已知同伴 | 3 | 4 |

Merlin 仍不确定两名坏人的具体角色；Assassin 对 Merlin 的不确定性存在于同一个联合分布内。不同 Agent 的假设、排除记录和后验互不共享。交换观察者无权区分的真实角色，不会改变其上下文或初始信念。

## 更新与数值约束

更新遵循 `P(H | E) ∝ P(E | H) P(H)`。硬证据的似然为 0 或 1，软证据必须有限且大于 0。每批证据在副本中完成校验、更新及归一化，成功后才提交。

归一化使用 log-sum-exp。仅为防止浮点下溢，把相对对数质量下限设为 -690；没有旧版的 [-4, 4] 怀疑度上限。显式零概率与硬证据排除的配置永久退出支持集，后续软证据不能恢复。空支持、全零、NaN、正无穷和非法配置报错，不会悄悄重置先验。

后验的和为 1，但行为／语言似然尚未经过实测校准，不应理解为经过校准的身份识别准确率。

### 硬证据

合法知识、公开刺杀者角色及任务结果均先转为 Observation，再提取硬证据。`MISSION_SUBMIT` 和赛后 `REVEAL` 不进入 Agent 观察流；不知道谁提交了哪张任务牌。

任务约束直接复用规则：好人不能 FAIL 时，f 张 FAIL 意味着至少 f 名坏人；坏人允许 SUCCESS 时，成功不能清白整队。两人队两张 FAIL 才证明两人都是坏人。失败阈值决定任务成败，安全轮只改变死亡。测试也覆盖允许好人 FAIL、禁止坏人 SUCCESS 的独立规则参数。

### 行为与语言

行为模型确定性地处理组队、选票、维护和反对。默认似然温和：组队 1.04，坏人投票 1.03，Merlin 避开含坏人的队伍 1.06，维护 1.05，跨阵营反对 1.03。它们只改变相对权重，不能证明身份。PASS、HOLD、CITE、花费多少决心和强承诺不额外加权。

**自己的行为是策略输出，不作为证据反向强化自己的角色判断。** 自己公开 DEFEND 一个怀疑对象只改变公开立场。任务结果即使来自自己的队伍，仍是新的机械证据。

语言解释只接受另一名玩家实际 `public_writing`／`statement` 的来源。模型提供有限枚举，不允许概率或数值乘数：

```json
{
  "language_evidence": [{
    "origin_event_id": "R1-012",
    "target": "P4",
    "signal": "increase_suspicion",
    "strength": "medium",
    "reason_type": "contradiction",
    "confidence": "medium"
  }]
}
```

- `signal`：`increase_suspicion`／`decrease_suspicion`／`neutral`。
- `strength`：`weak`／`medium`／`strong`，代码默认 1.10／1.30／1.60。
- `confidence`：`low`／`medium`／`high`，作为强度的指数，默认 0.5／0.75／1.0。
- `reason_type`：`contradiction`、`defense`、`accusation`、`vote_inconsistency`、`team_inconsistency`、`privileged_information_signal`、`coordination_signal`、`deception_signal`、`unsupported_certainty`。

`target` 可替换为 1–2 人的 `targets`，两人表示“双方都是坏人”；`privileged_information_signal` 只接受一名 Merlin 候选。目标必须涉及该事件或出现在文本中。匹配目标假设时，增加怀疑乘有效强度，其余配置乘倒数；降低怀疑反转乘数；neutral 为 1。`LikelihoodConfig` 可由代码配置，并校验数值与强度单调性。

## 去重与审计

Evidence 同时保存 `origin_event_id` 和代码生成的 `signal_id`：

| 来源 | 规范化信号 |
| --- | --- |
| 任务现场事件／视图任务回顾 | `mission:round:proposal` |
| 逐人 VOTE／STRONG_VOTE／TEAM_VOTE 中同一票 | `vote:round:proposal:actor` |
| 公开卡牌／挑战／组队 | `action:event_id` |
| 同一段语言的不同目标、强度或重新分类 | `language:event_id` |

DEFEND 的“维护／配合”转述、ACCUSE 的指控转述、组队和选票的直接转述，复用原行为信号。真正不同的语义特征（例如发言自相矛盾）可独立更新一次。同一个机械任务结果不允许作为语言来源；旧版 `belief_updates` 中对机械事件的再引用只能回放原始代码证据，不能叠加模型乘数。语言阶段的提示同样禁止把任务事实转述当成新的语义证据。

去重集合不受近期窗口裁剪，旧记录不会在重试、再次检索或换一种表示后重新加权。`BeliefUpdateRecord` 保存来源、类型、前后 top 配置、精确边际差值、排除数量和最大变化。最近 32 条数值审计、40 条兼容更新、12 条观察及 32 条定性变化留在 Agent；完整公开历史仍在 Chronicle。摘要只保留少量真正收紧支持集的硬约束引用，不随无信息的重复任务结果增长。

## 查询与模型输入

```python
beliefs.P_role("P2", "MERLIN")
beliefs.P_alignment("P3", "EVIL")
beliefs.P_joint({"P3": "EVIL", "P4": "EVIL"})
beliefs.P_conditional({"P4": "EVIL"}, {"P3": "GOOD"})
```

查询中的 `GOOD`／`EVIL` 字符串表示阵营。查询具体普通角色可使用 `{"P3": {"role": "GOOD"}}`，或直接调用 `P_role`。不可能的条件返回 `None`，不伪造概率；无效玩家或角色报错。

Prompt 区分 FACTS、BELIEFS、INFERENCES、STRATEGIC OBJECTIVE；沿用城堡求生、承诺与当前指定战术等既有目标，不从信念变化发明新的目标。并提供每人的角色／阵营边际、top 3 完整配置、top 5 坏人组合及条件关系。展示的 top 配置保持原始概率，不重新归一化；`shown_evil_team_mass` 明示已展示的质量。不会把全部角色配置或完整审计记录送给模型。

有新的待解释发言时，第一次响应只返回 `language_evidence`，每次最多解释 4 条。代码应用有效证据、刷新后验与兼容边际，再调用模型选择行动。允许在解释前做一次有界 `memory_query`。一次成功决策最多经过检索、解释、行动三个调用，错误重试仍受原来的重试次数限制。解释批次的提交独立于行动：后续非法行动不会撤销已接受证据，也不会发布立场。

最终响应沿用认知信封：

```json
{
  "belief_updates": [],
  "interpretation": [],
  "public_stance_change": null,
  "recommended_action": {"action": {"kind": "SKIP"}},
  "short_rationale": "保留回应机会。"
}
```

上例为反应窗口；普通计划、邪恶表演、议会各用既有 `recommended_action` 结构。行动响应不能夹带尚未处理的新概率证据。旧行动客户端可直接返回计划，其数字身份判断不写入信念；旧引用更新仅在原代码信号已经处理时允许随行动兼容回读。模型不会获得修改事实、角色配置或概率表的接口。

## 策略、二阶接口与调试

普通投票使用“队伍至少含一个坏人”的联合概率。刺杀和 Merlin 试探接收当前 Agent 自己的联合信念。共享邪恶策略对象不会保存 Agent 的私有后验；旧 `state.merlin_probabilities` 属性成为只读的、由联合角色先验推导的独立调用兼容值，不再根据事件维护第二套评分。它不是实战 Agent 的后验。公开怀疑度／信任度指标保留为**声誉启发式**，不作为身份概率或他人真实信念。

`ModeledBelief`、`ToMRequest`、`ToMTrigger` 和 `BoundedTheoryOfMind` 只定义将来的接口。每次针对一个其他 Agent，深度最多一层，触发场景包括信息泄露、寻找 Merlin、角色歧义、检验欺骗和高影响指控。目前无估算器、自动触发、全员持续建模或递归推演，估计不能反向覆写一阶分布。

终端 `--debug-cognition` 使用独立 stderr；GUI 开发模式的 `/debug/cognition` 沿用原认证，普通 `/state` 不暴露认知。开发快照含剩余配置数、top 配置、角色边际、最新审计、最大变化和排除原因；不进入玩家事件或模型上下文。

验证：`.venv/bin/python -m unittest discover -s tests -v`。`tests/test_joint_beliefs.py` 验证枚举、规则、数值、边际／条件查询、证据类型、重复信号、私有知识隔离、两阶段决策与二阶接口；原有认知、记忆、策略、GUI、终端、资源和完整对局测试继续覆盖兼容性。测试替代外部模型，不请求付费服务。
