import { Application, Container, Rectangle } from 'pixi.js';
import { DESIGN_W, DESIGN_H, LAYERS, SEATS } from './config.js';
import { buildPlaceholders, GAME } from './placeholders.js';
import { loadEnvironmentSet } from './assets.js';
import { EldritchEye } from './EldritchEye.js';
import { Parallax } from './Parallax.js';
import { Shake } from './Shake.js';
import { ScreenFx } from './ScreenFx.js';
import { GameClient } from './gameClient.js';
import { mountGameControls } from './gameControls.js';
import './gameControls.css';

const SEAT_NAMES = new Map(SEATS.map((seat) => [seat.seatId, seat.name]));
const PUBLIC_CARD_LABELS = { HEDGE: '保留判断', DEFEND: '辩护', ACCUSE: '指控', PRESSURE: '施压', BAIT: '试探' };

function clipIntelText(value, max = 30) {
  const text = String(value || '').replace(/\s+/g, ' ').trim();
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

function intelPlayerLabel(state, playerId) {
  const name = SEAT_NAMES.get(playerId) || (state.players || []).find((player) => player.id === playerId)?.name || playerId;
  return `${playerId} · ${name}`;
}

function buildPrivateIntel(state) {
  const round = Math.max(1, Number(state.mission_round) || 1);
  const entries = [];
  const events = Array.isArray(state.public_events) ? state.public_events : [];
  const dialogue = Array.isArray(state.dialogue) ? state.dialogue : [];
  // The browser surface is always the P1 seat; never let a server-side
  // spectator/AI identifier change whose private notebook is being rendered.
  const owner = 'P1';

  if (state.private?.role) {
    entries.push({ id: 'identity', type: 'confirmed', text: `${intelPlayerLabel(state, owner)} · 当前身份：${state.private.role}`, createdRound: round });
  }

  const mission = [...events].reverse().find((event) => event.kind === 'MISSION');
  if (mission) {
    const team = (mission.team || []).map((playerId) => intelPlayerLabel(state, playerId)).join('、');
    entries.push({
      id: `mission:${mission.seq}`,
      type: 'confirmed',
      text: `第 ${mission.round} 次任务${mission.success ? '成功' : '失败'} · ${team}`,
      createdRound: mission.round || round,
    });
  }

  const teamVote = [...events].reverse().find((event) => event.kind === 'TEAM_VOTE' && event.votes);
  if (teamVote) {
    const observed = Object.entries(teamVote.votes)
      .filter(([playerId]) => playerId !== owner)
      .slice(0, 1);
    observed.forEach(([playerId, approve]) => entries.push({
      id: `vote:${teamVote.seq}:${playerId}`,
      type: 'confirmed',
      text: `${intelPlayerLabel(state, playerId)} ${approve ? '赞成' : '反对'}了上一支队伍`,
      createdRound: teamVote.round || round,
    }));
  }

  [...dialogue].reverse().slice(0, 2).forEach((line) => {
    entries.push({
      id: `dialogue:${line.seq}`,
      type: 'clue',
      text: `${intelPlayerLabel(state, line.actor)}：${clipIntelText(line.statement, 28)}`,
      createdRound: line.round || round,
    });
  });

  if (!dialogue.length) {
    const action = [...events].reverse().find((event) => PUBLIC_CARD_LABELS[event.card]);
    if (action) entries.push({
      id: `action:${action.seq}`,
      type: 'clue',
      text: `${intelPlayerLabel(state, action.actor)} 使用${PUBLIC_CARD_LABELS[action.card]}卡`,
      createdRound: action.round || round,
    });
  }
  return entries;
}

function syncPrivateIntel(state) {
  if (!state || !Array.isArray(state.players) || !state.players.length) return;
  const previous = GAME.privateIntel || {};
  const newSession = state.phase === 'ROLE_REVEAL' && previous.sessionKey !== state.revision;
  const seen = new Set(newSession ? [] : (previous.seenEntryIds || []));
  const entries = buildPrivateIntel(state).map((entry) => {
    const isNew = !seen.has(entry.id);
    seen.add(entry.id);
    return { ...entry, isNew };
  });
  GAME.setPrivateIntel({
    ownerSeatId: 'P1',
    entries,
    manualTrustMarks: newSession ? {} : { ...(previous.manualTrustMarks || {}) },
    seenEntryIds: [...seen],
    sessionKey: newSession ? state.revision : (previous.sessionKey ?? state.revision),
  });
}

// 不用模块顶层 await：顶层 await 会挂起页面 load 事件，
// 且所有资产网络加载必须在 WebGL 初始化之前完成（无头环境下顺序敏感）
async function start() {
  // 1) 先加载环境资产（缺失的自动回退占位块）
  const env = await loadEnvironmentSet();
  console.warn('[main] env', !!env.skyTex, env.cloudFarTexs.length, env.cloudMidTexs.length);

  // 2) 再初始化渲染器
  const app = new Application();
  await app.init({
    resizeTo: window,
    background: 0x080406,
    antialias: true,
    preference: 'webgl',
  });
  document.body.appendChild(app.canvas);
  window.__APP = app; // 诊断钩子（CDP A/B 测试用，验证后删）
  // 舞台保持默认 passive：hitTestRecursive 对 passive 容器不做 containsPoint
  // 测试（_isInteractive false 时 testFn 被跳过），只让自身 eventMode='static' 的
  // 对象（卡牌/角色）成为命中候选——若设 stage='static'，模式沿树继承，场景里
  // 所有全屏 Graphics/Sprite（桌面暗部/聊天面板/corruption 覆盖层等）都会在
  // 逆序遍历中先于角色被命中并返回空数组毒化 pointerdown/up（hover 用宽容变体
  // hitTestMoveRecursive 不受影响——"悬停正常、点击失效"即此症状）

  // 层级关系：stage -> worldRoot（cover 缩放适配）-> cameraRoot（震屏偏移）-> 各层
  const worldRoot = new Container();
  const cameraRoot = new Container();
  worldRoot.addChild(cameraRoot);
  app.stage.addChild(worldRoot);
  cameraRoot.sortableChildren = true;

  function fit() {
    const s = Math.max(window.innerWidth / DESIGN_W, window.innerHeight / DESIGN_H);
    worldRoot.scale.set(s);
    worldRoot.position.set(
      (window.innerWidth - DESIGN_W * s) / 2,
      (window.innerHeight - DESIGN_H * s) / 2,
    );
  }
  fit();
  window.addEventListener('resize', fit);

  const layerMap = new Map();
  for (const def of LAYERS) {
    const c = new Container();
    c.zIndex = def.z;
    c.label = def.id;
    cameraRoot.addChild(c);
    layerMap.set(def.id, c);
  }

  // 3) 建场景（贴图已就绪，纯同步）+ 独立的邪眼组件
  const parallax = new Parallax(layerMap);
  const scene = buildPlaceholders(layerMap, env, parallax);
  const eldritchEye = new EldritchEye(layerMap.get('eye'), {
    eyeTex: env.eyeTex,
    cloudTex: (env.cloudFarTexs || [])[0] || null,
  });
  // 悬停卡牌 → 邪眼突然睁开注视该牌（cards() 经 GAME.cardHover 回调到这里）
  GAME.cardHover = (x, on) => eldritchEye.focusCard(x, on);

  // Browser controls are an input/visual projection only. The Python
  // GameSession remains authoritative for rules, hidden roles, AP, missions,
  // votes, and results. Keep Pixi's event traversal passive so card
  // pointerover/pointerout can drive visual feedback, while hoverOnly guards
  // the old local click/drag handlers from mutating a second game.
  cameraRoot.eventMode = 'passive';
  GAME.hoverOnly = true;
  document.querySelector('#hint')?.remove();
  const browserGame = { party: [] };
  const gameClient = new GameClient();
  gameClient.subscribe(({ state }) => {
    if (!state || !Array.isArray(state.players)) return;
    const human = state.players.find((player) => player.id === state.human_id);
    GAME.ap = human?.resolve ?? GAME.ap;
    GAME.party.length = 0;
    browserGame.party.length = 0;
    if (state.engine_phase === 'team' && Array.isArray(state.proposed_team)) {
      GAME.party.push(...state.proposed_team);
      browserGame.party.push(...state.proposed_team);
    }
    GAME.mission.round = state.mission_round || GAME.mission.round;
    GAME.mission.required = state.team_size || GAME.mission.required;
    syncPrivateIntel(state);
    GAME.notify();
    GAME.notifyParty();
  });
  const browserControls = mountGameControls(gameClient, browserGame);
  // Pixi cards remain a visual input surface, while the server-backed DOM
  // controller builds and submits the legal action payload.
  GAME.actionCard = (name) => browserControls.game.selectActionCard?.(name);
  GAME.cardActionEnabled = (name) => browserControls.game.isActionCardEnabled?.(name) ?? false;
  GAME.notify();
  window.__GAME_CLIENT = gameClient;
  // 调试钩子（CDP 测试用）
  // 调试钩子（CDP 测试用）：绕过输入管线直接驱动队伍状态机
  window.__GAME = GAME;
  window.__EYE_DEBUG = () => ({
    focusOn: eldritchEye.focusOn,
    focusX: eldritchEye.focusX,
    openV: +eldritchEye.openV.toFixed(3),
    iri: { x: +eldritchEye.iri.x.toFixed(1), y: +eldritchEye.iri.y.toFixed(1) },
    pup: { x: +eldritchEye.pup.x.toFixed(1), y: +eldritchEye.pup.y.toFixed(1) },
    glowA: +eldritchEye.glow.alpha.toFixed(3),
    atmoA: +eldritchEye.atmo.alpha.toFixed(3),
  });
  const shake = new Shake(cameraRoot);
  const screenFx = new ScreenFx(app.stage, layerMap.get('corruption'));

  // pointermove 只写目标状态（零分配）；所有缓动统一在 ticker 内计算
  let lastMX = DESIGN_W / 2;
  let lastMY = DESIGN_H / 2;
  window.addEventListener('pointermove', (e) => {
    const nx = (e.clientX / window.innerWidth) * 2 - 1;
    const ny = (e.clientY / window.innerHeight) * 2 - 1;
    parallax.setTarget(nx, ny);
    // 设计坐标系下的鼠标位置与移动速度（供邪眼注视/受惊反馈）
    const mx = (e.clientX / window.innerWidth) * DESIGN_W;
    const my = (e.clientY / window.innerHeight) * DESIGN_H;
    eldritchEye.setTarget(mx, my);
    eldritchEye.notifyVelocity(Math.hypot(mx - lastMX, my - lastMY));
    lastMX = mx;
    lastMY = my;
  });
  window.addEventListener('pointerdown', () => shake.trigger());
  window.addEventListener('keydown', (e) => {
    if (e.key === 's' || e.key === 'S') shake.trigger(22, 0.6);
    else if (e.key === 'k' || e.key === 'K') screenFx.corruptionPulse();
    else if (e.key === 'l' || e.key === 'L') scene.toggleLabels();
    else if (e.key === 'b' || e.key === 'B') eldritchEye.blink(true); // 手动触发眨眼（调试）
  });

  app.ticker.add((ticker) => {
    const t = ticker.lastTime;
    parallax.update(t);
    scene.update(t);
    eldritchEye.update(ticker.deltaMS);
    shake.update();
    screenFx.update();
  });

  // 场景已就绪：再实际渲染 ~45 帧后才放行 /__gate——"ready"必须是"已画出画面"，
  // 否则无头截图在 load 事件瞬间捕获到尚未绘制的黑 canvas（Pixi 首帧在 RAF 里）
  let readyFrames = 0;
  app.ticker.add(() => {
    if (++readyFrames === 45) fetch('/__ready').catch(() => {});
  });

  // 开发期页面内回读通道（.codely-cli/shot-extract.mjs）：
  // 无头合成器黑屏时的截图兜底——extract 在页面内直接渲染到纹理并回读，不依赖合成器。
  // 注意①不可用 import.meta.env.DEV 门控（本机 NODE_ENV=production 使 DEV=false）
  // ②必须显式 frame+resolution：默认按 stage bounds（含出血层，1536×1150）×渲染器
  // resolution 出图，坐标会与设计分辨率错位
  window.__AVALON_SNAP = () => app.renderer.extract.base64({
    target: app.stage,
    frame: new Rectangle(0, 0, DESIGN_W, DESIGN_H),
    clearColor: 0x080406,
    antialias: true,
    format: 'png',
    resolution: 1,
  });
}

start().catch((err) => console.error('[main] fatal', err));
