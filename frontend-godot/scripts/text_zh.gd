extends RefCounted
## Display labels only. Commands keep the engine's original IDs and enums.

const LABELS = {
	"START": "开始游戏", "ROLE_REVEAL": "查看身份", "TEAM_DRAFT": "队长选队",
	"DISCUSSION": "圆桌讨论", "CHALLENGE_RESPONSE": "回应质询", "REACTION": "反应机会",
	"TEAM_CONFIRM": "队伍定稿", "VOTE": "队伍投票", "VOTE_RESULT": "投票结果",
	"MISSION": "执行任务", "ROUND_RESULT": "任务结果", "ASSASSINATION": "刺杀梅林",
	"COUNCIL_DISCUSSION": "任务后议会", "EXILE_NOMINATION": "出局提名",
	"EXILE_VOTE": "出局投票", "EXILE_RESULT": "出局结果",
	"APPROVE": "赞成", "REJECT": "反对", "ABSTAIN": "弃票",
	"GAME_OVER": "游戏结束", "GOOD": "善良阵营", "EVIL": "邪恶阵营",
	"MERLIN": "梅林 · 善良阵营", "ASSASSIN": "刺客 · 邪恶阵营",
	"ACCUSE": "指控", "DEFEND": "辩护", "HEDGE": "保留判断", "PRESSURE": "施压", "BAIT": "试探",
	"SOCIAL": "落笔", "REACT": "反应", "SUCCESS": "成功", "FAIL": "失败",
	"waiting": "等待落笔", "completed": "已完成落笔",
}

static func label(value: String) -> String:
	return LABELS.get(value, value)
