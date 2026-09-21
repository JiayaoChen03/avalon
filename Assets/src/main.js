import { Application, Container, Rectangle } from 'pixi.js';
import { DESIGN_W, DESIGN_H, LAYERS } from './config.js';
import { buildPlaceholders } from './placeholders.js';
import { loadEnvironmentSet } from './assets.js';
import { EldritchEye } from './EldritchEye.js';
import { Parallax } from './Parallax.js';
import { Shake } from './Shake.js';
import { ScreenFx } from './ScreenFx.js';

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
