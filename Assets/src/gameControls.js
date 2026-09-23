/** DOM control surface for the authoritative Avalon browser session. */
const ACTION_CARD_DEFS = Object.freeze({
  '侦察': { card: 'HEDGE', reason: 'observe', description: '留下保留判断的公开手稿，观察目标的后续行动。' },
  '劝说': { card: 'DEFEND', reason: 'support', description: '公开支持目标，形成一条可追溯的站队记录。' },
  '质疑': { challenge: true, description: '引用一条与目标有关的公开记录，发起质询。' },
  '挑拨': { card: 'BAIT', reason: 'test_reaction', description: '公开诱导目标回应，观察其反应。' },
  '沉默': { silence: true, description: '结束本次发言机会，不消耗决心。' },
});
const MISSION_RULES = Object.freeze([
  { round: 1, required: 2, failVotes: 1 },
  { round: 2, required: 3, failVotes: 1 },
  { round: 3, required: 3, failVotes: 1 },
  { round: 4, required: 4, failVotes: 2 },
  { round: 5, required: 4, failVotes: 2 },
]);

// These anchors mirror the Pixi hand in config.js. The inline drawer sits just
// above the card and stays in the same design-coordinate system as #game-ui.
const CARD_ACTION_ANCHORS = Object.freeze({
  '侦察': { x: 440, top: 646 },
  '劝说': { x: 604, top: 641 },
  '质疑': { x: 768, top: 630 },
  '挑拨': { x: 932, top: 641 },
  '沉默': { x: 1096, top: 646 },
});

export function mountGameControls(client, game = {}) {
  const root = document.createElement('div');
  root.id = 'game-ui';
  root.innerHTML = [
    '<section class="game-status" aria-live="polite"><span class="game-title">AVALON · 围桌手稿</span><span class="game-connection"></span><span class="game-phase"></span><span class="game-prompt"></span></section>',
    '<section class="game-panel" aria-label="任务与行动会话"><div class="panel-heading"><span>任务 · 行动</span><button class="panel-private" type="button">身份</button></div><div class="mission-summary" aria-live="polite" hidden><div class="mission-line"><strong class="mission-round"></strong><span class="mission-stage"></span></div><div class="mission-detail"></div><div class="mission-progress" aria-label="任务轮次进度"></div></div><div class="panel-section-label">当前行动</div><div class="game-action"></div><div class="game-ai"></div><div class="game-error" role="alert"></div></section>',
    '<section class="game-log" aria-label="公开记录"><button class="log-card" type="button" aria-haspopup="dialog" aria-controls="public-records-dialog" aria-expanded="false"><img class="log-card-art" src="/assets/cards/question.jpeg" alt="" draggable="false"><span class="log-card-copy"><span class="log-card-title">公开记录</span><span class="log-card-subtitle">PUBLIC RECORD</span><span class="log-card-preview">暂无公开内容</span><span class="log-card-hint">点击展开</span><span class="log-card-count">暂无记录</span></span></button></section>',
    '<dialog id="public-records-dialog" class="log-dialog" aria-label="公开记录详情"><form method="dialog"><button class="log-dialog-close" value="close" aria-label="关闭公开记录">×</button><h2>公开记录</h2><div class="log-dialog-list"></div></form></dialog>',
    '<section class="card-action-inline" aria-label="卡牌行动选项" hidden><div class="card-action-inline-head"><h2 class="card-action-title">行动卡</h2><button class="card-action-close" type="button" aria-label="收起行动卡">×</button></div><p class="card-action-description"></p><div class="card-action-body"></div><div class="card-action-error" role="alert"></div></section>',
    '<dialog class="game-private"><form method="dialog"><button class="dialog-close" value="close" aria-label="关闭">×</button><h2>你的身份</h2><div class="private-body"></div></form></dialog>',
  ].join('');
  document.body.appendChild(root);
  const connection = root.querySelector('.game-connection');
  const phase = root.querySelector('.game-phase');
  const prompt = root.querySelector('.game-prompt');
  const missionSummary = root.querySelector('.mission-summary');
  const missionRound = root.querySelector('.mission-round');
  const missionStage = root.querySelector('.mission-stage');
  const missionDetail = root.querySelector('.mission-detail');
  const missionProgress = root.querySelector('.mission-progress');
  const panel = root.querySelector('.game-action');
  const ai = root.querySelector('.game-ai');
  const error = root.querySelector('.game-error');
  const logCard = root.querySelector('.log-card');
  const logCardCount = root.querySelector('.log-card-count');
  const logCardLatest = root.querySelector('.log-card-preview');
  const logDialog = root.querySelector('.log-dialog');
  const log = root.querySelector('.log-dialog-list');
  const cardActionInline = root.querySelector('.card-action-inline');
  const cardActionTitle = root.querySelector('.card-action-title');
  const cardActionDescription = root.querySelector('.card-action-description');
  const cardActionBody = root.querySelector('.card-action-body');
  const cardActionError = root.querySelector('.card-action-error');
  const privateDialog = root.querySelector('.game-private');
  const privateBody = root.querySelector('.private-body');
  root.querySelector('.panel-private').addEventListener('click', () => privateDialog.showModal());
  logCard.addEventListener('click', () => {
    if (!logDialog.open) logDialog.showModal();
    logCard.setAttribute('aria-expanded', 'true');
  });
  root.querySelector('.log-dialog-close').addEventListener('click', (e) => {
    e.preventDefault();
    e.stopPropagation();
    logDialog.close();
  });
  logDialog.addEventListener('close', () => logCard.setAttribute('aria-expanded', 'false'));
  logDialog.addEventListener('click', (e) => {
    if (e.target === logDialog) logDialog.close();
  });
  let activeCardName = null;
  const closeCardAction = () => {
    activeCardName = null;
    cardActionInline.hidden = true;
    cardActionBody.replaceChildren();
    cardActionError.textContent = '';
  };
  root.querySelector('.card-action-close').addEventListener('click', closeCardAction);
  // X 关闭按钮：显式绑定 close()（<form method=dialog> 原生关闭在 Pixi canvas 覆盖下偶发失效）
  root.querySelector('.dialog-close').addEventListener('click', (e) => {
    e.preventDefault();
    e.stopPropagation();
    privateDialog.close();
  });
  // 点击 backdrop 区域也能关闭
  privateDialog.addEventListener('click', (e) => {
    if (e.target === privateDialog) privateDialog.close();
  });

  const team = Array.isArray(game.party) ? game.party : [];
  game.party = team;
  game.toggleSeat = (seatId) => {
    const state = client.state;
    if (!state || !state.human_turn || state.engine_phase !== 'team') return;
    const index = team.indexOf(seatId);
    if (index >= 0) team.splice(index, 1);
    else if (team.length < Number(state.team_size || 0)) team.push(seatId);
    render(client.snapshot());
  };
  game.confirmReady = () => Boolean(client.state && client.state.human_turn &&
    client.state.engine_phase === 'team' && team.length === Number(client.state.team_size || 0));
  game.confirmTeam = () => client.command('team', { team: team.slice() });
  game.selectAction = (value) => client.command('action', { action: value });
  game.isActionCardEnabled = (name) => {
    const state = client.state;
    const def = ACTION_CARD_DEFS[name];
    if (!state || !def || !state.human_turn) return false;
    const legal = new Set(state.legal_actions || []);
    const canCite = legal.has('CITE') && citationRecords(state).length > 0;
    if (def.silence) return Boolean(actionKindForCard(state, def)) || canCite;
    if (def.challenge) return (legal.has('CHALLENGE') && Object.keys(state.challenge_evidence || {}).length > 0) || canCite;
    return Boolean(actionKindForCard(state, def)) || canCite;
  };
  game.selectActionCard = (name) => {
    const state = client.state;
    const def = ACTION_CARD_DEFS[name];
    if (!def || !game.isActionCardEnabled(name)) return false;
    if (activeCardName === name && !cardActionInline.hidden) {
      closeCardAction();
      return true;
    }
    activeCardName = name;
    const primaryKind = actionKindForCard(state, def);
    cardActionTitle.textContent = name + ' · 行动卡';
    cardActionDescription.textContent = def.description;
    cardActionBody.replaceChildren();
    cardActionError.textContent = '';
    if (def.silence && primaryKind) {
      const submit = button('沉默', () => submitCardAction({ kind: primaryKind }, submit), { className: 'primary' });
      cardActionBody.appendChild(submit);
    } else if (def.challenge && primaryKind === 'CHALLENGE') {
      const challengeTargets = Object.keys(state.challenge_evidence || {});
      const person = select('质询对象', challengeTargets, challengeTargets[0]);
      const refs = select('公开记录', evidenceOptions(state, state.challenge_evidence[challengeTargets[0]] || []), String((state.challenge_evidence[challengeTargets[0]] || [])[0] || ''));
      person.input.addEventListener('change', () => {
        setSelectOptions(refs.input, evidenceOptions(state, state.challenge_evidence?.[person.input.value] || []));
      });
      const submit = button('发起质疑', () => submitCardAction({ kind: 'CHALLENGE', target: person.input.value, evidence: Number(refs.input.value) }, submit), { className: 'primary' });
      cardActionBody.append(person.wrap, refs.wrap, submit);
    } else if (primaryKind && !def.silence && !def.challenge) {
      const targetIds = targets(state);
      if (!targetIds.length) return false;
      const person = select('对象', targetIds, targetIds[0]);
      const writing = document.createElement('input');
      writing.type = 'text';
      writing.maxLength = 240;
      writing.placeholder = '写一句公开手稿（必填）';
      writing.className = 'writing-input';
      const submitLabel = name === '侦察' ? '提交侦察' : name === '劝说' ? '提交劝说' : name === '挑拨' ? '提交挑拨' : '提交行动';
      const social = () => ({ card: def.card, target: person.input.value, reason: def.reason,
        statement: writing.value.trim(), rationale: '人类玩家通过行动卡选择', evidence: [] });
      const submit = button(submitLabel, () => {
        if (writing.value.trim()) submitCardAction({ kind: primaryKind, social: social() }, submit);
      }, { className: 'primary', disabled: true });
      writing.addEventListener('input', () => { submit.disabled = !writing.value.trim(); });
      cardActionBody.append(person.wrap, writing, submit);
    }
    const cite = citationControls(state);
    if (cite) cardActionBody.appendChild(cite);
    positionCardAction(name);
    cardActionInline.hidden = false;
    return true;
  };

  function actionKindForCard(state, def) {
    const legal = new Set(state?.legal_actions || []);
    if (def.silence) {
      if (state.engine_phase === 'reaction' && legal.has('SKIP')) return 'SKIP';
      if (state.engine_phase === 'challenge' && legal.has('DECLINE')) return 'DECLINE';
      return legal.has('PASS') ? 'PASS' : null;
    }
    if (def.challenge) return legal.has('CHALLENGE') ? 'CHALLENGE' : null;
    if (state.engine_phase === 'reaction') return legal.has('REACT') ? 'REACT' : null;
    if (state.engine_phase === 'challenge') return legal.has('RESPOND') ? 'RESPOND' : null;
    if (legal.has('SOCIAL')) return 'SOCIAL';
    return legal.has('COMMITTED_SOCIAL') ? 'COMMITTED_SOCIAL' : null;
  }

  async function submitCardAction(action, trigger) {
    if (!action || trigger?.disabled) return false;
    if (trigger) trigger.disabled = true;
    cardActionError.textContent = '';
    const ok = await client.command('action', { action: action });
    if (ok) closeCardAction();
    else {
      cardActionError.textContent = client.error || '当前无法执行此行动，请检查阶段和决心余额。';
      if (trigger) trigger.disabled = false;
    }
    return ok;
  }

  function actorLabel(state, actor) {
    const player = (state?.players || []).find((entry) => entry.id === actor);
    return player ? (player.is_human ? '你' : player.name) + `（${actor}）` : actor || '';
  }

  function citationRecords(state) {
    const dialogue = new Map((state?.dialogue || []).map((entry) => [Number(entry.seq), entry]));
    return (state?.evidence || []).map((event) => {
      const speech = dialogue.get(Number(event.seq));
      const content = speech?.statement?.trim() || event.public_writing?.trim() || event.text || '公开记录';
      const actor = actorLabel(state, speech?.actor || event.actor);
      const label = speech?.statement?.trim() || event.public_writing?.trim()
        ? `#${event.seq} · ${actor}${content ? `：${content}` : ''}`
        : `#${event.seq} · ${content}`;
      return { value: String(event.seq), label: label, seq: event.seq };
    });
  }

  function evidenceOptions(state, seqs) {
    const allowed = new Set((seqs || []).map(Number));
    return citationRecords(state).filter((record) => allowed.has(Number(record.value)));
  }

  function setSelectOptions(input, values) {
    input.replaceChildren(...(values || []).map((value) => {
      const option = document.createElement('option');
      option.value = typeof value === 'object' ? value.value : String(value);
      option.textContent = typeof value === 'object' ? value.label : String(value);
      return option;
    }));
    if (input.options.length) input.value = input.options[0].value;
  }

  function citationControls(state) {
    const legal = new Set(state?.legal_actions || []);
    const records = citationRecords(state);
    if (!legal.has('CITE') || !records.length) return null;
    const wrap = document.createElement('div');
    wrap.className = 'card-cite-block';
    const refs = select('引用对话', records, records[0].value);
    const cite = button('引用', () => submitCardAction({ kind: 'CITE', evidence: Number(refs.input.value) }, cite), { className: 'card-cite-submit' });
    wrap.append(refs.wrap, cite);
    return wrap;
  }

  function positionCardAction(name) {
    const anchor = CARD_ACTION_ANCHORS[name] || CARD_ACTION_ANCHORS['质疑'];
    cardActionInline.style.left = `${anchor.x}px`;
    cardActionInline.style.top = `${anchor.top}px`;
    cardActionInline.dataset.card = name;
  }

  function button(label, onClick, options = {}) {
    const b = document.createElement('button');
    b.type = 'button'; b.textContent = label;
    if (options.className) b.className = options.className;
    if (options.disabled) b.disabled = true;
    b.addEventListener('click', onClick);
    return b;
  }
  function select(label, values, selected) {
    const wrap = document.createElement('label'); wrap.className = 'field';
    const caption = document.createElement('span'); caption.textContent = label;
    const input = document.createElement('select');
    (values || []).forEach((value) => {
      const option = document.createElement('option');
      option.value = typeof value === 'object' ? value.value : value;
      option.textContent = typeof value === 'object' ? value.label : value;
      input.appendChild(option);
    });
    if (selected !== undefined) input.value = selected;
    wrap.append(caption, input); return { wrap, input };
  }
  function actionRequest(kind, fields) { return client.command('action', { action: Object.assign({ kind: kind }, fields || {}) }); }
  function targets(state) { return (state.players || []).map((p) => p.id).filter((id) => id !== state.human_id); }
  function socialEditor(state, kind, label) {
    const wrap = document.createElement('div'); wrap.className = 'editor';
    const cards = select('手稿', state.social_cards || [], (state.social_cards || [])[0]);
    const people = select('对象', targets(state), targets(state)[0]);
    const writing = document.createElement('input'); writing.type = 'text'; writing.maxLength = 240;
    writing.placeholder = '写一句公开手稿（必填）'; writing.className = 'writing-input';
    const submit = button(label || '落笔', () => actionRequest(kind, {
      social: { card: cards.input.value, target: people.input.value, reason: 'human_choice', statement: writing.value.trim(), rationale: '人类玩家选择', evidence: [] },
    }), { disabled: true });
    writing.addEventListener('input', () => { submit.disabled = !writing.value.trim(); });
    wrap.append(cards.wrap, people.wrap, writing, submit);
    return wrap;
  }
  function renderStart(snapshot) {
    const wrap = document.createElement('div'); wrap.className = 'start-card';
    const live = snapshot.mode === 'live';
    const v5 = live && snapshot.merlinVotePolicy === 'v5';
    const copy = document.createElement('p');
    copy.textContent = v5 ? '已选择真实 API 与 V5 梅林投票实验策略；开始游戏时读取当前模型配置。'
      : live ? '已选择真实 API；开始游戏时读取当前模型配置。'
        : '后端规则已接通。当前为离线联调，不调用外部模型。';
    const count = select('人数', ['5', '6'], '6');
    const seed = document.createElement('input'); seed.type = 'number'; seed.value = '20260922'; seed.className = 'seed-input'; seed.setAttribute('aria-label', '随机种子');
    wrap.append(copy, count.wrap, seed, button(live ? '开始游戏' : '开始离线联调', () => client.command('start', { players: Number(count.input.value), seed: Number(seed.value) }), { className: 'primary' }));
    panel.appendChild(wrap);
  }
  function renderTeam(state) {
    const wrap = document.createElement('div'); wrap.className = 'team-card';
    const title = document.createElement('p'); title.textContent = '选择队伍：' + team.length + ' / ' + state.team_size;
    const seats = document.createElement('div'); seats.className = 'seat-grid';
    (state.players || []).forEach((player) => {
      const chosen = team.includes(player.id);
      const b = button(player.id + ' · ' + player.name, () => game.toggleSeat(player.id), { className: chosen ? 'selected' : '' });
      b.disabled = !chosen && team.length >= state.team_size;
      seats.appendChild(b);
    });
    wrap.append(title, seats, button('确认队伍', () => game.confirmTeam(), { className: 'primary', disabled: !game.confirmReady() }));
    panel.appendChild(wrap);
  }
  function renderCardActionHint(state) {
    const hint = document.createElement('p');
    hint.className = 'card-action-hint';
    hint.textContent = state.human_turn ? '点击底部行动卡展开选项' : '等待当前行动完成后，点击底部行动卡';
    panel.appendChild(hint);
  }
  function renderRevision(state) {
    const opts = new Set(state.legal_actions || []);
    if (opts.has('LOCK')) panel.appendChild(button('锁定队伍', () => actionRequest('LOCK'), { className: 'primary' }));
    if (opts.has('REVISE')) {
      const current = state.proposed_team || [];
      const removed = select('替换', current, current[0]);
      const available = (state.players || []).map((p) => p.id).filter((id) => !current.includes(id));
      const added = select('换入', available, available[0]);
      panel.appendChild(Object.assign(document.createElement('div'), { className: 'editor' }));
      const wrapper = panel.lastChild; wrapper.append(removed.wrap, added.wrap, button('替换并锁定', () => actionRequest('REVISE', { removed: removed.input.value, added: added.input.value })));
    }
  }
  function renderVote(state) {
    const submit = (approve, strong) => client.command('vote', { approve: approve, strong: Boolean(strong) });
    if ((state.legal_actions || []).includes('VOTE')) {
      panel.append(button('赞成', () => submit(true), { className: 'primary' }), button('反对', () => submit(false)));
    }
    if ((state.legal_actions || []).includes('STRONG_VOTE')) panel.append(
      button('强烈赞成', () => submit(true, true), { className: 'strong' }),
      button('强烈反对', () => submit(false, true), { className: 'strong' }),
    );
  }
  function renderMission(state) {
    (state.legal_actions || []).forEach((card) => panel.appendChild(button(card === 'SUCCESS' ? '成功牌' : '失败牌',
      () => client.command('mission', { card: card }), { className: card === 'SUCCESS' ? 'primary' : 'danger' })));
  }
  function renderSelection(state) {
    const people = select('目标', state.selection_targets || [], (state.selection_targets || [])[0]);
    panel.append(people.wrap, button(state.engine_phase === 'assassination' ? '确认刺杀' : '提名出局', () => client.command(
      state.engine_phase === 'assassination' ? 'assassinate' : 'nominate_exile', { target: people.input.value },
    ), { className: 'danger' }));
  }
  function renderExileVote(state) {
    const labels = { APPROVE: '赞成出局', REJECT: '反对出局', ABSTAIN: '弃票' };
    (state.legal_actions || []).forEach((choice) => panel.appendChild(button(labels[choice] || choice, () => client.command('exile_vote', { choice: choice }), { className: choice === 'APPROVE' ? 'danger' : '' })));
  }
  function renderMissionSummary(state) {
    const roundValue = Number(state?.mission_round);
    if (!Number.isFinite(roundValue) || roundValue < 1) {
      missionSummary.hidden = true;
      return;
    }
    const round = Math.min(MISSION_RULES.length, Math.max(1, Math.floor(roundValue)));
    const rule = MISSION_RULES[round - 1];
    const teamSize = Number(state.team_size) || rule.required;
    missionSummary.hidden = false;
    missionRound.textContent = `任务 ${round} / ${MISSION_RULES.length}`;
    missionStage.textContent = state.phase === 'GAME_OVER' ? '本局结束' : `第 ${round} 轮`;
    missionDetail.textContent = `需要成员：${teamSize} 人 · 失败条件：${rule.failVotes} 张失败票`;
    missionProgress.replaceChildren(...MISSION_RULES.map((item, index) => {
      const step = document.createElement('span');
      step.className = 'mission-step' + (item.round === round ? ' current' : item.round < round ? ' done' : '');
      step.setAttribute('aria-label', `第 ${item.round} 轮，需要 ${item.required} 人`);
      const label = document.createElement('span');
      label.className = 'mission-step-label';
      label.textContent = ['I', 'II', 'III', 'IV', 'V'][index];
      const dot = document.createElement('span');
      dot.className = 'mission-step-dot';
      step.append(label, dot);
      return step;
    }));
  }
  function freshSeed() {
    return Math.floor(Date.now() % 2147483647);
  }
  function resetGame(state) {
    return client.command('reset_game', {
      players: (state?.players || []).length || 5,
      seed: freshSeed(),
    });
  }
  function renderGate(state) {
    if (state.phase === 'ROLE_REVEAL') panel.appendChild(button('查看公开桌面', () => client.command('continue'), { className: 'primary' }));
    else if (['VOTE_RESULT', 'ROUND_RESULT', 'EXILE_RESULT'].includes(state.phase)) panel.appendChild(button('继续', () => client.command('continue'), { className: 'primary' }));
    else if (state.phase === 'GAME_OVER') panel.appendChild(button('重新开始', () => resetGame(state), { className: 'primary' }));
  }
  function render(snapshot) {
    const state = snapshot.state;
    if (activeCardName && (!state || !game.isActionCardEnabled(activeCardName))) closeCardAction();
    root.classList.toggle('offline', snapshot.mode === 'offline');
    connection.textContent = !snapshot.connected ? '后端未连接'
      : snapshot.mode === 'offline' ? '离线联调'
        : snapshot.merlinVotePolicy === 'v5' ? '真实 API · V5（实验）' : '真实 API · 基线';
    connection.className = 'game-connection ' + (snapshot.connected ? 'ok' : 'bad');
    phase.textContent = state ? state.phase + (state.mission_round ? ' · 第 ' + state.mission_round + ' 轮' : '') : '';
    prompt.textContent = state?.prompt || '';
    renderMissionSummary(state);
    panel.replaceChildren(); ai.replaceChildren();
    if (!state || state.phase === 'START') renderStart(snapshot);
    else if (state.phase === 'TEAM_DRAFT' && state.human_turn) renderTeam(state);
    else if (['DISCUSSION', 'COUNCIL_DISCUSSION'].includes(state.phase)) renderCardActionHint(state);
    else if (['CHALLENGE_RESPONSE', 'REACTION'].includes(state.phase)) renderCardActionHint(state);
    else if (state.phase === 'TEAM_CONFIRM' && state.human_turn) renderRevision(state);
    else if (state.phase === 'VOTE' && state.human_turn) renderVote(state);
    else if (state.phase === 'MISSION' && state.human_turn) renderMission(state);
    else if (['ASSASSINATION', 'EXILE_NOMINATION'].includes(state.phase) && state.human_turn) renderSelection(state);
    else if (state.phase === 'EXILE_VOTE' && state.human_turn) renderExileVote(state);
    else renderGate(state);
    if (state?.can_advance) ai.appendChild(button('推进 AI 行动', () => client.command('advance'), { className: 'ai-button' }));
    if (state?.retry_ai) {
      const recovery = document.createElement('div');
      recovery.className = 'ai-recovery';
      recovery.append(
        button('重新开始回合', () => client.command('restart_round'), { className: 'primary', disabled: snapshot.busy }),
        button('重置游戏', () => resetGame(state), { className: 'danger', disabled: snapshot.busy }),
      );
      ai.appendChild(recovery);
    }
    if (snapshot.busy) ai.appendChild(document.createTextNode('后端正在处理…'));
    if (snapshot.pending && (snapshot.uncertain || snapshot.error)) ai.appendChild(button('重试刚才的操作', () => client.retryPending(), { className: 'retry' }));
    error.textContent = snapshot.error || state?.error || state?.notice || '';
    error.classList.toggle('visible', Boolean(error.textContent));
    renderLog(state);
    privateBody.textContent = state?.private ? '角色：' + (state.private.role || '未知') + '\n已知邪恶座位：' + ((state.private.known_evil || []).join('、') || '无') : '尚未开始游戏。';
    layout();
  }
  function renderLog(state) {
    log.replaceChildren();
    const dialogue = new Map((state?.dialogue || []).map((entry) => [entry.seq, entry]));
    const events = (state?.public_events || []).map((entry) => {
      const spoken = dialogue.get(entry.seq);
      return spoken ? { seq: entry.seq, text: spoken.actor + '：' + spoken.statement } : entry;
    });
    const rows = events.map((entry) => entry.text || ('#' + (entry.seq || '')));
    rows.forEach((text) => { const row = document.createElement('div'); row.className = 'log-row'; row.textContent = text; log.appendChild(row); });
    logCardCount.textContent = events.length ? `${events.length} 条记录` : '暂无记录';
    logCardLatest.textContent = rows.at(-1) || '暂无公开内容';
    log.scrollTop = log.scrollHeight;
  }
  function layout() {
    // The Pixi world uses a cover fit while this DOM layer uses a contain fit.
    // Place the record card in the same six-card fan as the Pixi hand. The
    // DOM layer uses contain while Pixi uses cover, so convert the hand card's
    // world-space center and size into this layer's design coordinates.
    const designW = 1536;
    const designH = 1024;
    const uiScale = Math.min(window.innerWidth / designW, window.innerHeight / designH);
    const uiLeft = (window.innerWidth - designW * uiScale) / 2;
    const uiTop = (window.innerHeight - designH * uiScale) / 2;
    const worldScale = Math.max(window.innerWidth / designW, window.innerHeight / designH);
    const worldLeft = (window.innerWidth - designW * worldScale) / 2;
    const worldTop = (window.innerHeight - designH * worldScale) / 2;
    const handScale = worldScale / uiScale;
    const recordScale = 0.97;
    const logWidth = 198 * recordScale * handScale;
    const logHeight = 270 * recordScale * handScale;
    const recordCenterX = 768 - 3 * 164;
    const recordCenterY = 934 - (270 * recordScale) / 2;
    const leftDesign = (worldLeft + recordCenterX * worldScale - uiLeft) / uiScale - logWidth / 2;
    const topDesign = (worldTop + recordCenterY * worldScale - uiTop) / uiScale - logHeight / 2;
    root.style.setProperty('--ui-scale', String(uiScale));
    root.style.setProperty('--ui-left', String(uiLeft) + 'px');
    root.style.setProperty('--ui-top', String(uiTop) + 'px');
    root.style.setProperty('--log-left', String(leftDesign) + 'px');
    root.style.setProperty('--log-top', String(topDesign) + 'px');
    root.style.setProperty('--log-width', String(logWidth) + 'px');
    root.style.setProperty('--log-height', String(logHeight) + 'px');
    root.style.setProperty('--log-rotation', '-12deg');
    root.classList.remove('log-above-cards');
    if (activeCardName && !cardActionInline.hidden) positionCardAction(activeCardName);
  }
  const unsubscribe = client.subscribe(render);
  window.addEventListener('resize', layout);
  client.connect().catch(() => {});
  return { root: root, game: game, destroy: () => { unsubscribe(); root.remove(); } };
}
