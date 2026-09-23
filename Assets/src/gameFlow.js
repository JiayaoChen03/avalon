/** Presentation derived only from the authoritative public session snapshot. */
export function advanceLabel(state, busy = false) {
  if (['VOTE', 'EXILE_VOTE'].includes(state?.phase)) return busy ? '正在收集 AI 选票…' : '收齐 AI 选票';
  return busy ? 'AI 正在行动…' : '推进 AI 行动';
}

export function resultPresentation(state) {
  const result = state?.result || {};
  if (state?.phase === 'VOTE_RESULT') {
    const votes = Object.values(result.votes || {});
    const approved = votes.filter((vote) => vote === true).length;
    const summary = `提案${result.approved ? '通过' : '被否决'}：${approved} 票赞成 / ${votes.length - approved} 票反对`;
    if (state.winner) return { summary, detail: '本局已结束。', label: '查看对局结果' };
    if (result.approved) return { summary, detail: '队伍已通过，下一步进入任务。', label: '进入任务' };
    const nextAttempt = Number(result.attempt || state.proposal_attempt || 1) + 1;
    return { summary, detail: '任务轮次不变，换下一位队长重新组队。', label: `开始第 ${nextAttempt} 次提案` };
  }
  if (state?.phase === 'ROUND_RESULT') {
    return { summary: `第 ${result.round || state.mission_round} 次任务${result.success ? '成功' : '失败'}`,
      detail: '任务已结算，继续进行任务后议会。', label: '进入任务后议会' };
  }
  if (state?.phase === 'EXILE_RESULT') {
    return { summary: `${result.target || ''} ${result.exiled ? '出局' : '未出局'}`,
      detail: '议会已结束，继续后由规则判定下一阶段。', label: '结束议会并继续' };
  }
  return null;
}
