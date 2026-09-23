import test from 'node:test';
import assert from 'node:assert/strict';
import { advanceLabel, resultPresentation } from '../Assets/src/gameFlow.js';

test('rejected sealed vote identifies next proposal, not a new mission', () => {
  const presentation = resultPresentation({ phase: 'VOTE_RESULT', mission_round: 1,
    result: { approved: false, attempt: 1, votes: { P1: false, P2: true, P3: false, P4: true, P5: false, P6: false } } });
  assert.equal(presentation.summary, '提案被否决：2 票赞成 / 4 票反对');
  assert.equal(presentation.label, '开始第 2 次提案');
  assert.match(presentation.detail, /任务轮次不变/);
});

test('approved vote leads to mission and fifth rejection leads to game result', () => {
  assert.equal(resultPresentation({ phase: 'VOTE_RESULT', result: { approved: true, votes: { P1: true } } }).label, '进入任务');
  assert.equal(resultPresentation({ phase: 'VOTE_RESULT', winner: 'EVIL', result: { approved: false, attempt: 5 } }).label, '查看对局结果');
});

test('collection UI describes sealed voting without exposing choices', () => {
  for (const phase of ['VOTE', 'EXILE_VOTE']) {
    assert.equal(advanceLabel({ phase }), '收齐 AI 选票');
    assert.equal(advanceLabel({ phase }, true), '正在收集 AI 选票…');
    assert.equal(resultPresentation({ phase }), null);
  }
  assert.equal(advanceLabel({ phase: 'DISCUSSION' }), '推进 AI 行动');
});

test('mission and exile results each expose their required continue gate', () => {
  assert.equal(resultPresentation({ phase: 'ROUND_RESULT', result: { round: 1, success: true } }).label, '进入任务后议会');
  assert.equal(resultPresentation({ phase: 'EXILE_RESULT', result: { target: 'P4', exiled: false } }).summary, 'P4 未出局');
});
