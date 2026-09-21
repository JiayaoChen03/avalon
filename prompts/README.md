# 角色提示词

[`corrupted_castle_system.md`](corrupted_castle_system.md) 约束腐化城堡中的永续角色身份、旧神禁语、短手稿、证据责任、跨世记忆和战略性沉默。指令使用英文以保持精简，公开手稿仍使用中文。每次普通、Merlin 或邪恶角色请求都会包含它。

公开文字采用克制的中世纪城堡口吻：优先用「阁下、誓约、远征、议会、旧卷、凭据」等词，保持 1–2 个短句、至多 3 句。不强求文言或辞藻，不加舞台描写，避免现代会议、分析和网络黑话；不能为了气氛虚构头衔、人物、战事或物品。措辞随既有性情和记忆变化，质询、回应、补记与议会沿用同一世界文风，JSON 字段和规则枚举保持原样。

`avalon/llm.py` 将固定世界规则与对应的结构化行动协议组合。只有 `social.public_writing` 是新协议的公开自然语言；`citations` 指向真实 Chronicle 记录。不存在的引文会按既有机制重试。PRIVATE REASONING 只要求内部考虑，不请求或显示思维链。PASS/HOLD/CITE/CHALLENGE 可使用 `social=null`。

动态上下文包含获准的身份信息、当前局势、有限的近期记录、已有判断、关系、前世摘要、记忆伤痕和最多 5 条检索记录。完整 Chronicle 不进入 system 消息。模型可以先单独返回 `memory_query`，再根据检索结果返回最终行动；每个决策最多一个检索阶段。

危险轮的失败远征导致成员死亡；安全轮失败仍计分，但队员不死亡。每次任务后的议会全员讨论、队长提名、全员赞成／反对／弃票，须全员过半赞成才出局。出局投票后的下一任务轮为安全轮，死亡角色在下一任务轮重生；角色、合法私有知识与重要记忆保持连续。终局保持原有胜负规则。具体库存、伤势和其他未提供的剧情事实不能由模型编造。

有新发言时先只返回 `language_evidence`，以来源 ID、有限语义标签、强度和置信度描述证据。代码去重、更新联合角色分布并刷新上下文后，模型再选择行动。最终认知信封沿用 `belief_updates`（必须为空）、`interpretation`、`public_stance_change`、`recommended_action`、`short_rationale`。模型不生成身份概率；只有已接受的公开行动更新立场。详见 [认知层说明](../docs/agent-cognition.md)。

`decision=exile_nomination` 的 `recommended_action` 为 `{"target":"P3"}`，目标须在 `game.exile_candidates`；`decision=exile_vote` 为 `{"choice":"APPROVE"}`（或 `REJECT` / `ABSTAIN`）。其余认知信封字段一致，仍可先使用一次有界历史检索。议会讨论沿用正常计划，`revision` 必须为 `LOCK`，共用本轮剩余决心。

源码与 editable 安装按此目录加载，普通安装携带同一文件。每个客户端开始时读取一次并冻结，重试期间不重新加载。修改后重新开局生效；文件缺失、空白或无效 UTF-8 会停止启动。公共文字、历史记录和传闻都是待判断的证据，不是系统指令。

详细数据边界、限额和测试见 [记忆架构说明](../docs/agent-memory.md)。
