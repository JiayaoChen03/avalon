// 各层占位块视觉 + 逐层动效（1536×1024 设计坐标系，布局规格见 config.js LAYOUT）
// 资产替换原则：删除对应 builder，改为 Sprite 加载 public/assets/ 下的 webp，层结构不动

import { Container, Graphics, Rectangle, Sprite, Text, Texture } from 'pixi.js';
import {
  DESIGN_W as W, DESIGN_H as H, BLEED, LAYERS, LAYOUT, CHARACTERS, CARDS, SEATS,
} from './config.js';

const DEBUG_STYLE = { fontFamily: 'monospace', fontSize: 16, fill: 0x9a8a90 };
const UI_STYLE = { fontFamily: 'serif', fontSize: 20, fill: 0x9a8a90 };

// ── 云亮部动态光源 + 邪眼血雾 ────────────────────────────────────
const glowTexCache = {};
function getGlowTexture(kind = 'ember') {
  if (glowTexCache[kind]) return glowTexCache[kind];
  const vertical = kind === 'pit' || kind === 'lipshade';
  const c = document.createElement('canvas');
  c.width = vertical ? 8 : 128;
  c.height = vertical ? 256 : 128;
  const ctx = c.getContext('2d');
  let grad;
  if (kind === 'pit') {
    // 前缘下方渐暗：透明起步 → 迅速入黑（卡牌的黑暗前景，无硬边）
    grad = ctx.createLinearGradient(0, 0, 0, c.height);
    grad.addColorStop(0, 'rgba(10,5,7,0)');
    grad.addColorStop(0.35, 'rgba(10,5,7,0.82)');
    grad.addColorStop(1, 'rgba(7,3,5,0.98)');
  } else if (kind === 'lipshade') {
    // 前缘立面体积明暗：顶缘窄遮蔽带（只压最上 ~5px，避让 bevelCatch 受光碎段）
    // → 中段近乎透明（立面石面本身要读出来，暗度只交给 faceMass 大暗块）
    // → 底部沉入近黑（厚板底缘的"接地压深"，比 v7 更深一档）
    grad = ctx.createLinearGradient(0, 0, 0, c.height);
    grad.addColorStop(0, 'rgba(16,10,8,0.46)');
    grad.addColorStop(0.07, 'rgba(0,0,0,0.14)');
    grad.addColorStop(0.32, 'rgba(0,0,0,0.07)');
    grad.addColorStop(0.62, 'rgba(0,0,0,0.34)');
    grad.addColorStop(1, 'rgba(0,0,0,0.8)');
  } else {
    grad = ctx.createRadialGradient(64, 64, 0, 64, 64, 64);
    if (kind === 'ring') {
      // 环形血雾：中心透明（不糊瞳孔），外缘浓、再向外渐隐——柔化邪眼硬切边
      grad.addColorStop(0, 'rgba(150,32,42,0)');
      grad.addColorStop(0.42, 'rgba(150,32,42,0)');
      grad.addColorStop(0.72, 'rgba(140,30,40,0.55)');
      grad.addColorStop(0.92, 'rgba(110,22,30,0.28)');
      grad.addColorStop(1, 'rgba(90,18,24,0)');
    } else if (kind === 'socket') {
      // 眼窝阴影盘：中心近实暗、软边渐隐——盖住生成图烤死的瞳孔与白高光
      grad.addColorStop(0, 'rgba(12,5,7,0.97)');
      grad.addColorStop(0.7, 'rgba(15,6,8,0.9)');
      grad.addColorStop(1, 'rgba(20,8,10,0)');
    } else if (kind === 'mist') {
      // 大范围内燃血雾：中心可见、向外衰减——邪眼"照亮邻云"的主光晕
      grad.addColorStop(0, 'rgba(175,42,50,0.6)');
      grad.addColorStop(0.45, 'rgba(130,26,34,0.3)');
      grad.addColorStop(1, 'rgba(90,16,22,0)');
    } else {
      grad.addColorStop(0, 'rgba(255,196,120,1)');
      grad.addColorStop(0.3, 'rgba(255,150,70,0.55)');
      grad.addColorStop(1, 'rgba(255,120,40,0)');
    }
  }
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, c.width, c.height);
  glowTexCache[kind] = Texture.from(c);
  return glowTexCache[kind];
}

// 每张贴图的亮部质心（对 cloud_*.png 做亮度分析得出）
// fx/fy=贴图内亮部质心，w=光晕直径/贴图宽，a=基准强度
const CLOUD_GLOWS = {
  far: [
    { fx: 0.522, fy: 0.555, w: 0.3, a: 0.5 },
    { fx: 0.6, fy: 0.476, w: 0.28, a: 0.45 },
    { fx: 0.47, fy: 0.557, w: 0.3, a: 0.5 },
  ],
  mid: [
    { fx: 0.458, fy: 0.787, w: 0.34, a: 0.6 },
    { fx: 0.517, fy: 0.533, w: 0.42, a: 0.55 },
  ],
};

function sky(L, tex) {
  if (tex) {
    // 真实贴图：cover 满出血区（W+2*BLEED × H+2*BLEED），居中裁切
    const s = new Sprite(tex);
    const bw = W + BLEED * 2;
    const bh = H + BLEED * 2;
    s.anchor.set(0.5);
    s.scale.set(Math.max(bw / tex.width, bh / tex.height));
    s.position.set(W / 2, H / 2);
    L.addChild(s);
    return;
  }
  // 占位块回退
  const g = new Graphics();
  g.rect(-BLEED, -BLEED, W + BLEED * 2, H + BLEED * 2).fill(0x140709);
  g.rect(-BLEED, 110, W + BLEED * 2, 300).fill({ color: 0x2a0c10, alpha: 0.5 });
  g.rect(-BLEED, 330, W + BLEED * 2, 180).fill({ color: 0x3a0e12, alpha: 0.35 });
  L.addChild(g);
}

// ── 天空细节层（A: 城堡上方恐怖主视觉 + C: 右侧低对比暗层，静态）────
function skyDetails(L) {
  const pulseGlows = [];

  // A1. 天穹裂隙：邪眼周围的发光裂纹（折线 + 底部泛光，缓慢脉动）
  const crackDefs = [
    [[0.58, 0.085], [0.595, 0.13], [0.583, 0.16], [0.602, 0.2], [0.592, 0.245]],
    [[0.625, 0.065], [0.636, 0.115], [0.627, 0.17], [0.643, 0.225]],
    [[0.548, 0.115], [0.561, 0.165], [0.551, 0.215]],
  ];
  crackDefs.forEach((pts, i) => {
    const glow = new Sprite(getGlowTexture('ember'));
    glow.anchor.set(0.5);
    glow.blendMode = 'add';
    glow.alpha = 0.3;
    glow.scale.set((90 + i * 30) / 128);
    glow.position.set(pts[0][0] * W, pts[0][1] * H);
    L.addChild(glow);
    pulseGlows.push({ g: glow, phase: i * 2.6, base: 0.3 });
    const g = new Graphics();
    for (let k = 0; k < pts.length - 1; k++) {
      g.moveTo(pts[k][0] * W, pts[k][1] * H).lineTo(pts[k + 1][0] * W, pts[k + 1][1] * H);
    }
    g.stroke({ width: 1.5 + i * 0.8, color: 0xff7a42, alpha: 0.5 });
    L.addChild(g);
  });

  // A2. 模糊眼状云纹（左上，三层低对比椭圆叠出"雾里睁眼"感）
  const eyeCloud = new Graphics();
  eyeCloud.ellipse(0, 0, 95, 36).fill({ color: 0x2a0d12, alpha: 0.45 });
  eyeCloud.ellipse(4, 2, 58, 22).fill({ color: 0x1c080c, alpha: 0.5 });
  eyeCloud.ellipse(-8, 1, 17, 9).fill({ color: 0x12060a, alpha: 0.6 });
  eyeCloud.position.set(W * 0.3, H * 0.2);
  L.addChild(eyeCloud);

  // A3. 大尺度触手阴影（右上，粗弯钩剪影，极暗）
  const sh = new Graphics();
  sh.poly([
    W * 0.8, -20, W * 0.83, -10, W * 0.8, 60, W * 0.76, 120,
    W * 0.72, 170, W * 0.7, 150, W * 0.72, 90, W * 0.75, 30,
  ]).fill({ color: 0x120608, alpha: 0.5 });
  L.addChild(sh);

  // A4. 天空圣环 + 破碎王冠（环绕/悬在邪眼上方）
  const halo = new Graphics();
  halo.ellipse(0, 0, 195, 132).stroke({ width: 3, color: 0x7a2a24, alpha: 0.3 });
  halo.ellipse(0, 0, 208, 144).stroke({ width: 1.5, color: 0x5a1c18, alpha: 0.22 });
  halo.position.set(W * 0.6, H * 0.135);
  L.addChild(halo);
  const crown = new Graphics();
  for (let k = -2; k <= 2; k++) {
    const bx = k * 15;
    const bh = k % 2 === 0 ? 24 : 32;
    crown.poly([bx - 6, 0, bx, -bh, bx + 6, 0]).fill({ color: 0x0e0507, alpha: 0.9 });
  }
  crown.rect(-32, -4, 64, 8).fill({ color: 0x0e0507, alpha: 0.9 });
  crown.position.set(W * 0.6, H * 0.045);
  L.addChild(crown);

  // C1. 右上低对比眼状裂缝（任务 UI 后方，若隐若现）
  const eyeCrack = new Graphics();
  eyeCrack.ellipse(0, 0, 62, 15).stroke({ width: 2, color: 0x5a1a1e, alpha: 0.28 });
  eyeCrack.ellipse(0, 2, 20, 7).fill({ color: 0x140608, alpha: 0.4 });
  eyeCrack.position.set(W * 0.78, H * 0.16);
  L.addChild(eyeCrack);

  // C2. 右上低对比云纹（UI 后方深度层）
  const wisp = new Graphics();
  wisp.ellipse(0, 0, 115, 32).fill({ color: 0x1c0a10, alpha: 0.35 });
  wisp.ellipse(32, 12, 72, 20).fill({ color: 0x160810, alpha: 0.3 });
  wisp.position.set(W * 0.74, H * 0.1);
  L.addChild(wisp);

  // 天穹裂隙泛光脉动
  return (t) => {
    for (const g of pulseGlows) {
      g.g.alpha = g.base * (0.7 + 0.3 * Math.sin(t * 0.0016 + g.phase));
    }
  };
}

function clouds(L, color, alpha, yBase, count, speed, amp, texs = [], glowCfgs = []) {
  const list = [];
  const glows = [];
  const span = W + BLEED * 2;
  for (let i = 0; i < count; i++) {
    let d;
    if (texs.length) {
      // 真实云精灵：循环复用贴图，翻转/缩放/透明度做差异
      const tex = texs[i % texs.length];
      const s = new Sprite(tex);
      s.anchor.set(0.5);
      // 云贴图不满幅（2560 画布内云占约一半），按整图缩放需放大目标宽度
      s.scale.set((520 + ((i * 97) % 380)) / tex.width);
      if ((i * 53) % 7 > 3) s.scale.x *= -1; // 部分水平翻转
      s.alpha = alpha + ((i * 31) % 20) / 100;
      // 在亮部质心挂动态光晕（加法混合，随云翻转/缩放/漂移/视差一起动）
      const cfg = glowCfgs[i % glowCfgs.length];
      if (cfg) {
        const glow = new Sprite(getGlowTexture());
        glow.anchor.set(0.5);
        glow.blendMode = 'add';
        glow.position.set((cfg.fx - 0.5) * tex.width, (cfg.fy - 0.5) * tex.height);
        glow.scale.set((tex.width * cfg.w) / 128);
        glow.alpha = cfg.a;
        s.addChild(glow);
        glows.push({ g: glow, phase: i * 2.3, base: cfg.a, bs: (tex.width * cfg.w) / 128 });
      }
      d = s;
    } else {
      const g = new Graphics();
      g.ellipse(0, 0, 170 + ((i * 97) % 240), 36 + ((i * 53) % 46)).fill({ color, alpha });
      d = g;
    }
    d.position.set(((i + 0.5) * span) / count - BLEED, yBase + ((i * 71) % 150));
    L.addChild(d);
    list.push({ g: d, x0: d.x, phase: i * 1.7, amp: amp * (0.6 + ((i * 31) % 40) / 100) });
  }
  return (t) => {
    for (const c of list) c.g.x = c.x0 + Math.sin(t * speed + c.phase) * c.amp;
    // 火光闪烁：双频正弦叠加（慢呼吸 + 快抖动），并带轻微尺寸脉动
    for (const gl of glows) {
      gl.g.alpha = gl.base * (0.82 + 0.22 * Math.sin(t * 0.0021 + gl.phase) + 0.1 * Math.sin(t * 0.011 + gl.phase * 1.7));
      gl.g.scale.set(gl.bs * (1 + 0.05 * Math.sin(t * 0.003 + gl.phase * 0.6)));
    }
  };
}

// 每张贴图的非透明内容框（System.Drawing bbox 分析得出，fx/fy=左上角比例，fw/fh=宽高比例）
// 用于把"画布留白"排除在缩放计算外
// 注：邪眼（eldritch_eye/pupil）已独立为 src/EldritchEye.js 组件，其贴图框数据随组件维护
const TEX_BOX = {
  tentacle_far_01: { fy: 0.306, fh: 0.541 },
  tentacle_far_02: { fy: 0, fh: 0.944 },
  tentacle_far_03: { fy: 0, fh: 0.831 },
  castle_far: { fh: 0.939 },
  city_mid: { fh: 0.95 },
  bridge_mid: { fw: 0.981 },
  foreground_left: { fy: 0.297, fh: 0.703 },
  foreground_right: { fy: 0.022, fh: 0.978 },
};

// 触手贴图顺序与 TENTACLE_DEFS 一一对应（tentacle_far_01/02/03）

// 邪眼已独立为 src/EldritchEye.js 组件（分层结构+注视追踪+眨眼），
// 由 main.js 装配；本文件不再构建 eye 层内容

// 触手贴图顺序与 TENTACLE_DEFS 一一对应（tentacle_far_01/02/03）
const TENTACLE_BOXES = [
  TEX_BOX.tentacle_far_01,
  TEX_BOX.tentacle_far_02,
  TEX_BOX.tentacle_far_03,
];

function tentacles(L, texs = []) {
  const defs = [
    { fx: 0.52, len: 340, w: 30 },
    { fx: 0.62, len: 260, w: 24 },
    { fx: 0.72, len: 380, w: 36 },
    { fx: 0.78, len: 300, w: 26 }, // C: 右侧半隐藏触手（部分被任务面板遮住）
  ];
  const list = defs.map((d, i) => {
    let g;
    if (texs.length) {
      // 真贴图：按内容高度缩放，内容顶端对齐 y=40（顶部为摆动枢轴）
      const tex = texs[i % texs.length];
      const box = TENTACLE_BOXES[i % TENTACLE_BOXES.length];
      const s = (d.len / (tex.height * box.fh));
      g = new Sprite(tex);
      g.anchor.set(0.5, 0);
      g.scale.set(s);
      g.position.set(d.fx * W, 40 - box.fy * tex.height * s);
    } else {
      g = new Graphics();
      g.roundRect(-d.w / 2, 0, d.w, d.len, d.w / 2).fill({ color: 0x251029, alpha: 0.92 });
      g.position.set(d.fx * W, 30);
    }
    // 可读性需求：压低横穿邪眼区域（EYE cx=0.6）触手的亮度/对比度，避免抢走邪眼焦点
    const near = Math.max(0, 1 - Math.abs(d.fx - 0.6) / 0.15);
    if (near > 0) {
      g.alpha = 1 - 0.24 * near;
      const mix = (a, b) => Math.round(a + (b - a) * near);
      g.tint = (mix(255, 160) << 16) | (mix(255, 128) << 8) | mix(255, 138);
    }
    L.addChild(g);
    return { g, phase: i * 2.1, base: (i - 1) * 0.09 };
  });
  return (t) => {
    for (const { g, phase, base } of list) g.rotation = base + Math.sin(t * 0.0009 + phase) * 0.05;
  };
}

// 城堡窗灯实测位置（System.Drawing 亮度聚类，fx/fy=贴图内比例）
const CASTLE_WINDOWS = [
  { fx: 0.3, fy: 0.565, a: 0.55 }, { fx: 0.423, fy: 0.541, a: 0.45 },
  { fx: 0.7, fy: 0.714, a: 0.55 }, { fx: 0.384, fy: 0.578, a: 0.4 },
  { fx: 0.447, fy: 0.557, a: 0.5 }, { fx: 0.56, fy: 0.706, a: 0.5 },
  { fx: 0.463, fy: 0.515, a: 0.35 }, { fx: 0.421, fy: 0.669, a: 0.45 },
  { fx: 0.63, fy: 0.597, a: 0.4 }, { fx: 0.707, fy: 0.751, a: 0.45 },
  { fx: 0.715, fy: 0.561, a: 0.4 }, { fx: 0.552, fy: 0.621, a: 0.35 },
  { fx: 0.598, fy: 0.742, a: 0.45 },
];

function castle(L, tex) {
  if (tex) {
    // 真贴图：按内容高度缩放的中央厚重城堡体块，内容底边（=画布底）对齐地平线
    const s = 430 / (tex.height * TEX_BOX.castle_far.fh);
    const sp = new Sprite(tex);
    sp.anchor.set(0.5, 1);
    sp.scale.set(s);
    sp.position.set(LAYOUT.castleCenter * W, 562);
    L.addChild(sp);

    // 窗灯动态光源：在实测窗位叠 add 混合的暖橙光晕，
    // 每扇窗独立相位双频闪烁（1.9s 呼吸 + 0.5s 火光抖动），忽明忽暗
    const box = TEX_BOX.castle_far;
    const spW = tex.width * s;                    // 贴图显示宽
    const spH = tex.height * s;                   // 贴图显示高
    const left = LAYOUT.castleCenter * W - spW / 2;   // 显示左缘
    const top = 562 - spH;                        // 显示上缘（anchor 底部对齐 562）
    const winLights = [];
    CASTLE_WINDOWS.forEach((win, i) => {
      const glow = new Sprite(getGlowTexture());
      glow.anchor.set(0.5);
      glow.blendMode = 'add';
      glow.alpha = win.a;
      glow.scale.set(26 / 128);                   // 光晕直径 26px（贴着窗户）
      glow.position.set(left + win.fx * spW, top + win.fy * spH);
      L.addChild(glow);
      winLights.push({ g: glow, base: win.a, phase: i * 1.83, fast: 0.5 + (i % 5) * 0.13 });
    });
    return (t) => {
      for (const w of winLights) {
        // 呼吸基线 + 快抖动，偶尔接近熄灭（忽明忽暗）
        w.g.alpha = w.base * (0.35 + 0.45 * Math.sin(t * 0.0033 + w.phase)
          + 0.28 * Math.sin(t * (0.011 + w.fast * 0.004) + w.phase * 2.7));
      }
    };
  }
  // 占位块回退
  const g = new Graphics();
  g.rect(-BLEED, 330, W + BLEED * 2, 230).fill(0x251116);
  g.rect(W * 0.49, 350, W * 0.3, 210).fill(0x150a0e);
  g.rect(W * 0.585, 330, 58, 230).fill(0x1a0b10);
  g.rect(W * 0.655, 344, 46, 216).fill(0x1a0b10);
  const spires = [
    [0.52, 185, 58], [0.56, 118, 42], [0.60, 205, 50], [0.63, 175, 62],
    [0.66, 150, 46], [0.70, 178, 52], [0.44, 105, 40], [0.47, 88, 34],
    [0.75, 128, 42], [0.79, 92, 36],
  ];
  for (const [fx, h, w] of spires) {
    const x = fx * W;
    g.poly([x - w / 2, 332, x, 332 - h, x + w / 2, 332]).fill(0x1d0d13);
  }
  L.addChild(g);
}

function midground(L, cityTex, bridgeTex) {
  if (cityTex) {
    // 真贴图：城市剪影簇，按内容高度缩放、底部对齐
    const s = 260 / (cityTex.height * TEX_BOX.city_mid.fh);
    const sp = new Sprite(cityTex);
    sp.anchor.set(0.5, 1);
    sp.scale.set(s);
    sp.position.set(W / 2, 585);
    L.addChild(sp);
  } else {
    const g = new Graphics();
    g.rect(-BLEED, 450, W + BLEED * 2, 130).fill(0x2b161c);
    const blocks = [
      [0.05, 50], [0.15, 78], [0.27, 42], [0.41, 90], [0.55, 58],
      [0.68, 80], [0.81, 48], [0.93, 86],
    ];
    for (const [fx, h] of blocks) g.rect(fx * W - 38, 450 - h, 76, h).fill(0x241219);
    L.addChild(g);
  }
  if (bridgeTex) {
    // 真贴图：石桥，按内容宽缩放
    const s = 690 / (bridgeTex.width * TEX_BOX.bridge_mid.fw);
    const sp = new Sprite(bridgeTex);
    sp.anchor.set(0.5, 0.5);
    sp.scale.set(s);
    sp.position.set(W * 0.39, 533);
    L.addChild(sp);
  } else {
    const g = new Graphics();
    g.rect(W * 0.18, 468, W * 0.42, 14).fill(0x1f0e13);
    g.rect(W * 0.24, 482, 26, 100).fill(0x1c0d11);
    g.rect(W * 0.52, 482, 26, 100).fill(0x1c0d11);
    L.addChild(g);
  }

  // —— B: 左中补充（静态：断塔/扭曲枝干/异形肢体/低雾）——
  const md = new Graphics();
  // 远处小型断塔（尖顶已断）
  md.rect(W * 0.115, 470, 24, 118).fill({ color: 0x100608, alpha: 0.9 });
  md.poly([W * 0.108, 470, W * 0.127, 448, W * 0.146, 470]).fill({ color: 0x0e0608, alpha: 0.9 });
  // 巨大异形肢体轮廓（从左缘黑暗中伸入）
  md.poly([
    -BLEED, 300, W * 0.06, 320, W * 0.1, 360, W * 0.075, 400,
    W * 0.11, 430, W * 0.05, 440, -BLEED, 430,
  ]).fill({ color: 0x0c0507, alpha: 0.85 });
  // 扭曲枝干（几段折线枝）
  md.moveTo(W * 0.16, 470).lineTo(W * 0.175, 430).lineTo(W * 0.168, 396)
    .lineTo(W * 0.185, 368).moveTo(W * 0.175, 430).lineTo(W * 0.196, 418)
    .stroke({ width: 3, color: 0x0c0508, alpha: 0.9 });
  // 低雾横带
  md.rect(-BLEED, 508, W * 0.34, 74).fill({ color: 0x1a0a10, alpha: 0.45 });
  L.addChild(md);

  // —— C: 右侧红雾深度层（任务面板后方若隐若现）——
  const veil = new Graphics();
  veil.rect(W * 0.62, 300, W * 0.33, 220).fill({ color: 0x2a0d14, alpha: 0.3 });
  L.addChild(veil);

  // —— D: 地平线与底部（低强度：石碑/尖桩/废墟/黑雾/火点）——
  // 可见带只有 y 450-520（tableShadowBack 自 470 渐暗、台面自 ~528 接管），克制分布在左右两角避开城市簇
  const dg = new Graphics();
  for (let k = 0; k < 5; k++) {
    const x = W * 0.045 + k * 26 + (k % 2) * 9;
    dg.rect(x, 470 + (k % 2) * 12, 6, 46 + (k % 3) * 12).fill({ color: 0x0b0408, alpha: 0.9 });
  }
  for (let k = 0; k < 4; k++) {
    const x = W * 0.86 + k * 30 + (k % 2) * 8;
    dg.rect(x, 466 + (k % 2) * 10, 6, 52 + (k % 3) * 10).fill({ color: 0x0b0408, alpha: 0.9 });
  }
  dg.poly([W * 0.03, 518, W * 0.05, 486, W * 0.075, 502, W * 0.1, 478, W * 0.125, 518])
    .fill({ color: 0x0b0408, alpha: 0.85 });
  dg.poly([W * 0.87, 518, W * 0.895, 490, W * 0.92, 505, W * 0.945, 482, W * 0.97, 518])
    .fill({ color: 0x0b0408, alpha: 0.85 });
  dg.rect(-BLEED, 492, W + BLEED * 2, 46).fill({ color: 0x0a0407, alpha: 0.5 });
  L.addChild(dg);

  // 低强度火点（地平线两角，加法光点闪烁）
  const fires = [];
  [[W * 0.055, 512], [W * 0.315, 516], [W * 0.83, 514], [W * 0.935, 510]].forEach(([fx, fy], i) => {
    const f = new Sprite(getGlowTexture());
    f.anchor.set(0.5);
    f.blendMode = 'add';
    f.alpha = 0.3;
    f.scale.set(34 / 128);
    f.position.set(fx, fy);
    L.addChild(f);
    fires.push({ g: f, phase: i * 2.1 });
  });
  return (t) => {
    for (const f of fires) {
      f.g.alpha = 0.22 + 0.16 * Math.sin(t * 0.006 + f.phase)
        + 0.08 * Math.sin(t * 0.017 + f.phase * 2.2);
    }
  };
}

function fgEnv(L, leftTex, rightTex) {
  if (leftTex) {
    // 真贴图：左边缘框景，按内容高度缩放（内容底边=画布底）
    const box = TEX_BOX.foreground_left;
    const s = 900 / (leftTex.height * box.fh);
    const sp = new Sprite(leftTex);
    sp.anchor.set(0, 1);
    sp.scale.set(s);
    sp.position.set(-BLEED + 8, H + BLEED - 4);
    L.addChild(sp);
  } else {
    const left = new Graphics()
      .poly([-BLEED, H + BLEED, -BLEED, 210, 120, 390, 30, 590, 175, 830, 45, H + BLEED])
      .fill(0x0a0508);
    L.addChild(left);
  }
  if (rightTex) {
    const box = TEX_BOX.foreground_right;
    const s = 900 / (rightTex.height * box.fh);
    const sp = new Sprite(rightTex);
    sp.anchor.set(1, 1);
    sp.scale.set(s);
    sp.position.set(W + BLEED - 8, H + BLEED - 4);
    L.addChild(sp);
  } else {
    const right = new Graphics()
      .poly([W + BLEED, H + BLEED, W + BLEED, 260, W - 140, 440, W - 42, 640, W - 165, 860, W - 28, H + BLEED])
      .fill(0x0a0508);
    L.addChild(right);
  }
}

// 石板贴图（bbox 实测 table_altar，独板巨石无砖缝）：
// 顶面 = 源 x2-97% / y3-79%。注：贴图自带的"前立面带"（y79-93%）实测近全黑
// （生成模型把过梁阴影画死了，无法作立面用）——立面改为折缝包裹裁切（见 getSlabCrops）
const TABLE_STONE = {
  top: { fx0: 0.02, fx1: 0.97, fy0: 0.03, fy1: 0.79 },
  front: { fx0: 0.02, fx1: 0.98, fy0: 0.79, fy1: 0.93 },
};

// 裁"贴折缝"的连续条带：台面取顶面下段；
// 立面（折缝包裹）取【顶面窗口的底部条带、底边对齐折缝行】——
// 同一层石纹跨折缝向下延续过桌棱，是"整块厚板折下来"的最强读法；
// 折缝交界由 crease/seam 暗缝 + lipshade 体积光承担
const slabCache = new Map();
function getSlabCrops(tex, T) {
  if (slabCache.has(tex)) return slabCache.get(tex);
  const bw = (1 + T.frontOut * 2) * W;
  const bh = T.frontY - (T.backSideY - 8);
  // 顶面：贴折缝的下段横带
  const topW = (TABLE_STONE.top.fx1 - TABLE_STONE.top.fx0) * tex.width;
  const topH = (TABLE_STONE.top.fy1 - TABLE_STONE.top.fy0) * tex.height;
  const surfCh = Math.min(topH, topW / (bw / bh));
  const surf = new Texture({
    source: tex.source,
    frame: new Rectangle(
      Math.round(TABLE_STONE.top.fx0 * tex.width),
      Math.round(TABLE_STONE.top.fy1 * tex.height - surfCh),
      Math.round(topW),
      Math.round(surfCh),
    ),
  });
  // 立面（折缝包裹）：底边对齐折缝行，向下取顶面窗口底部条带
  const wrapW = (TABLE_STONE.top.fx1 - TABLE_STONE.top.fx0) * tex.width;
  const faceH = T.frontY + T.lipH - T.frontSideY;
  const lipAspect = (W * (1 + T.frontOut * 2) + T.lipOutset * 2) / faceH;
  const lipCh = Math.min(
    (TABLE_STONE.top.fy1 - TABLE_STONE.top.fy0) * tex.height,
    wrapW / lipAspect,
  );
  const lip = new Texture({
    source: tex.source,
    frame: new Rectangle(
      Math.round(TABLE_STONE.top.fx0 * tex.width),
      Math.round(TABLE_STONE.top.fy1 * tex.height - lipCh),
      Math.round(wrapW),
      Math.round(lipCh),
    ),
  });
  const crops = { surf, lip };
  slabCache.set(tex, crops);
  return crops;
}

// ── 桌子（table-only pass）：立体议事桌，桌子只占中下部弧缘带 ──────────
// 层序：tableShadowBack(105) → characters(120) → tableSurface(125) → tableProps(128)
//       → tableFrontLip(132) → tableFrontShadow(136) → tableFrontProps(139)
// 台面遮住角色胸以下（后缘在人物前方），前缘立面有厚度，下方迅速入黑承接卡牌

function tableShadowBack(L) {
  const T = LAYOUT.table;
  // 桌后接地暗晕：后缘线处最暗，把桌带从城堡/城市底边压进阴影
  const g = new Sprite(getGlowTexture('socket'));
  g.anchor.set(0.5);
  g.scale.set((W * 1.5) / 128, 240 / 128);
  g.position.set(W / 2, T.backY - 10);
  g.alpha = 0.6;
  L.addChild(g);
  // 全宽渐暗基础：桌外两侧 + 前缘下方先沉底，真实台面/暗部层再在其上收束
  const pit = new Sprite(getGlowTexture('pit'));
  pit.position.set(-BLEED, 470);
  pit.scale.set((W + BLEED * 2) / 8, (H + BLEED * 2 - 470) / 256);
  L.addChild(pit);
}

// 台面轮廓路径（梯形 + 浅弧缘：后缘中央略沉，前缘中央更近更低）
function tablePath(g, T) {
  g.moveTo(T.backInset * W, T.backSideY);
  g.quadraticCurveTo(W / 2, 2 * T.backY - T.backSideY, (1 - T.backInset) * W, T.backSideY);
  g.lineTo((1 + T.frontOut) * W, T.frontSideY);
  g.quadraticCurveTo(W / 2, 2 * T.frontY - T.frontSideY, -T.frontOut * W, T.frontSideY);
  g.closePath();
}

function tableSurface(L, tex) {
  const T = LAYOUT.table;
  const holder = new Container();
  L.addChild(holder);

  if (tex) {
    // 真贴图：石板顶面贴折缝的下段横带（折角光影由贴图自带）
    const bw = (1 + T.frontOut * 2) * W;
    const bh = T.frontY - (T.backSideY - 8);
    const s = new Sprite(getSlabCrops(tex, T).surf);
    s.scale.set(bw / s.texture.width, bh / s.texture.height);
    s.position.set(-T.frontOut * W, T.backSideY - 8);
    s.tint = 0x7a746c; // 哥特暗石基底：中暗暖灰（主体保持中暗值），亮部只留给烛池与受光棱
    holder.addChild(s);
    // 罩染平涂层：在贴图细噪上压一层冷炭薄纱，把"照片式均匀细噪"收进大色面——
    // 手绘大值块语言的底座；暗值块/冷蓝面/烛池再在其上重建明暗结构
    const veil = new Graphics();
    veil.rect(-T.frontOut * W - 16, T.backSideY - 8, bw + 32, T.frontY - T.backSideY + 18)
      .fill({ color: 0x26262e, alpha: 0.34 });
    holder.addChild(veil);
  } else {
    const base = new Graphics();
    tablePath(base, T);
    base.fill(0x23262c);
    holder.addChild(base);
  }

  // 四周收暗（环形暗晕：中心透明 → 桌缘浓，压住左右两端）
  const vig = new Sprite(getGlowTexture('ring'));
  vig.anchor.set(0.5);
  vig.scale.set((W * 0.5) / 46, 48 / 46);
  vig.position.set(W / 2, (T.backY + T.frontY) / 2);
  vig.alpha = 0.55;
  holder.addChild(vig);
  // 大笔触暗值块（手绘值块语言）：非对称暗部三块——远离烛位的石面沉进暗部，
  // 亮部只留在烛池周围，打破"整幅等亮的台面"（=地面/ledge 的读法根）；
  // 无中央均匀光池：烛光只属于各烛自己的局部池（见 tableProps 双区光池）
  const topMass = new Graphics();
  topMass.poly([
    W * 0.045, 543, W * 0.16, 537, W * 0.27, 549, W * 0.25, 585,
    W * 0.145, 604, W * 0.07, 600, W * 0.038, 572,
  ]).fill({ color: 0x111014, alpha: 0.34 });
  topMass.poly([
    W * 0.315, 542, W * 0.40, 546, W * 0.41, 583, W * 0.36, 606, W * 0.31, 588,
  ]).fill({ color: 0x111014, alpha: 0.22 });
  topMass.poly([
    W * 0.60, 538, W * 0.73, 534, W * 0.85, 541, W * 0.915, 556,
    W * 0.885, 598, W * 0.74, 610, W * 0.635, 604, W * 0.605, 568,
  ]).fill({ color: 0x111014, alpha: 0.35 });
  topMass.poly([
    W * 0.45, 552, W * 0.53, 548, W * 0.545, 585, W * 0.475, 600, W * 0.44, 572,
  ]).fill({ color: 0x111014, alpha: 0.2 });
  holder.addChild(topMass);
  // 冷灰蓝大色面（值块语言的"受天光面"）：左右可见带各一大笔触，与暗值块交替——
  // 石面明暗由几块大面构成而非均匀纹理，与城堡同一位"画家"的大面笔法
  const slatePlanes = new Graphics();
  slatePlanes.poly([
    W * 0.05, 545, W * 0.145, 538, W * 0.225, 547, W * 0.245, 575,
    W * 0.185, 604, W * 0.09, 602, W * 0.033, 570,
  ]).fill({ color: 0x3a4150, alpha: 0.19 });
  slatePlanes.poly([
    W * 0.655, 540, W * 0.75, 536, W * 0.86, 545, W * 0.885, 570,
    W * 0.80, 602, W * 0.70, 606, W * 0.655, 575,
  ]).fill({ color: 0x3a4150, alpha: 0.18 });
  // 中央开放带（槽位下方到前缘）一块冷面：补上"槽下阴影带"的大面语言
  slatePlanes.poly([
    W * 0.38, 578, W * 0.52, 574, W * 0.545, 600, W * 0.40, 606,
  ]).fill({ color: 0x3a4150, alpha: 0.13 });
  holder.addChild(slatePlanes);
  // 选择性亮面：烛位近旁被照亮的一小片石面（大片干净面上克制的一笔亮色）
  const litPlanes = new Graphics();
  litPlanes.poly([
    W * 0.315, 590, W * 0.36, 588, W * 0.372, 602, W * 0.33, 606,
  ]).fill({ color: 0x8a8578, alpha: 0.19 });
  litPlanes.poly([
    W * 0.70, 592, W * 0.745, 590, W * 0.757, 604, W * 0.715, 609,
  ]).fill({ color: 0x8a8578, alpha: 0.19 });
  litPlanes.poly([
    W * 0.148, 602, W * 0.19, 600, W * 0.198, 612, W * 0.155, 615,
  ]).fill({ color: 0x8a8578, alpha: 0.16 });
  litPlanes.poly([
    W * 0.878, 606, W * 0.915, 604, W * 0.92, 616, W * 0.885, 618,
  ]).fill({ color: 0x8a8578, alpha: 0.15 });
  holder.addChild(litPlanes);

  // 后缘：不做受光棱线（亮棱=地面/平台的背光读法）——人物立在桌后，
  // 桌沿在他们身前沉入阴影，只用暗接触带交代"桌沿在身前"的转折
  const rim = new Graphics();
  rim.moveTo(T.backInset * W, T.backSideY);
  rim.quadraticCurveTo(W / 2, 2 * T.backY - T.backSideY, (1 - T.backInset) * W, T.backSideY);
  rim.stroke({ width: 2.5, color: 0x0a090c, alpha: 0.55 });
  holder.addChild(rim);
  const contact = new Sprite(getGlowTexture('socket'));
  contact.anchor.set(0.5);
  contact.scale.set((W * 0.92) / 128, 34 / 128);
  contact.position.set(W / 2, T.backY + 8);
  contact.alpha = 0.62;
  holder.addChild(contact);
  // 两端沉暗：台面尽头没入黑暗——"黑暗房间里被烛光照亮的实体桌"，
  // 打破"满幅等亮=地面"的读法（地板才会均匀亮到画布边缘）
  for (const fx of [0.035, 0.965]) {
    const side = new Sprite(getGlowTexture('socket'));
    side.anchor.set(0.5);
    side.scale.set((W * 0.31) / 128, 138 / 128);
    side.position.set(fx * W, (T.backY + T.frontY) / 2 + 6);
    side.alpha = 0.72;
    holder.addChild(side);
  }
  // 前缘折线暗缝：台面与立面交界的转折读点（上下两半由 surface/lip 各出一半，合成完整暗缝）
  const crease = new Graphics();
  crease.moveTo(-T.frontOut * W, T.frontSideY);
  crease.quadraticCurveTo(W / 2, 2 * T.frontY - T.frontSideY, (1 + T.frontOut) * W, T.frontSideY);
  crease.stroke({ width: 3, color: 0x0e0a0c, alpha: 0.92 });
  holder.addChild(crease);
  // 石面划痕：几道细浅痕（年代感，避开桌心 UI 区）
  const scratch = new Graphics();
  for (const [sx, sy, len, ang] of [[0.22, 566, 70, 0.06], [0.44, 580, 90, -0.05], [0.585, 572, 60, 0.04], [0.815, 578, 80, -0.07], [0.68, 596, 55, 0.03]]) {
    scratch.moveTo(sx * W, sy);
    scratch.lineTo(sx * W + Math.cos(ang) * len, sy + Math.sin(ang) * len);
  }
  // 浅刻仪式刻痕：一处小三角刻符（克制的叙事暗示）
  const sgx = W * 0.605;
  scratch.moveTo(sgx, 592);
  scratch.lineTo(sgx + 11, 610);
  scratch.lineTo(sgx - 7, 608);
  scratch.closePath();
  scratch.stroke({ width: 1.5, color: 0x0e0e12, alpha: 0.14 });
  scratch.stroke({ width: 1, color: 0xb0b6bc, alpha: 0.18 });
  holder.addChild(scratch);
  // 浅刻仪式刻带：沿前缘内侧 ~22px 的刻槽环（似祭坛刻带），磨损处断开；
  // 刻槽读法 = 暗刻线 + 下缘浅受光 catch（纯刻痕，不发光）
  const foldX0 = (1 + T.frontOut) * W, foldX1 = -T.frontOut * W;
  const foldY0 = T.frontSideY, foldC = 2 * T.frontY - T.frontSideY;
  const grooveSegs = [[0.03, 0.30], [0.335, 0.62], [0.655, 0.97]];
  const grooveDark = new Graphics();
  const grooveCatch = new Graphics();
  for (const [g, dy] of [[grooveDark, -22], [grooveCatch, -19.5]]) {
    for (const [a, b] of grooveSegs) {
      for (let k = 0; k <= 12; k++) {
        const t = a + (b - a) * (k / 12);
        const mt = 1 - t;
        const x = mt * mt * foldX0 + 2 * mt * t * (W / 2) + t * t * foldX1;
        const y = mt * mt * foldY0 + 2 * mt * t * foldC + t * t * foldY0 + dy;
        if (k === 0) g.moveTo(x, y); else g.lineTo(x, y);
      }
    }
  }
  grooveDark.stroke({ width: 2, color: 0x151119, alpha: 0.62 });
  grooveCatch.stroke({ width: 1, color: 0xcac2b4, alpha: 0.14 });
  holder.addChild(grooveDark, grooveCatch);
  // 磨损封印刻环（右侧台面，若隐若现的双弧残环；两弧各用独立 Graphics 防路径串线）
  const sealA = new Graphics();
  sealA.arc(W * 0.828, 556, 24, Math.PI * 0.25, Math.PI * 1.55);
  sealA.stroke({ width: 2, color: 0x151119, alpha: 0.55 });
  const sealB = new Graphics();
  sealB.arc(W * 0.828, 556, 15, Math.PI * 1.7, Math.PI * 0.6);
  sealB.stroke({ width: 1.6, color: 0x151119, alpha: 0.45 });
  holder.addChild(sealA, sealB);
  // 陈年烟熏渍（两处极淡暗斑）
  const grime = new Graphics();
  grime.ellipse(W * 0.205, 552, 26, 10).fill({ color: 0x0b0a0e, alpha: 0.16 });
  grime.ellipse(W * 0.83, 560, 30, 11).fill({ color: 0x0b0a0e, alpha: 0.13 });
  holder.addChild(grime);
  // 发丝裂纹（克制，勿裂纹糊脸）：一条主裂自台面深处裂到前棱折线、
  // 与立面 0.685 裂纹首尾相接——"整块厚板从头裂到底"的独石读法；
  // 次裂仅一条短痕；大块干净面留给值块语言
  const crack = new Graphics();
  crack.moveTo(W * 0.17, 552);
  crack.lineTo(W * 0.175, 566);
  crack.lineTo(W * 0.168, 580);
  crack.lineTo(W * 0.172, 598);
  crack.moveTo(W * 0.685, 548);
  crack.lineTo(W * 0.679, 566);
  crack.lineTo(W * 0.688, 584);
  crack.lineTo(W * 0.682, 600);
  crack.lineTo(W * 0.687, 612);
  crack.lineTo(W * 0.683, 619);
  crack.stroke({ width: 1.7, color: 0x0c0c10, alpha: 0.68 });
  holder.addChild(crack);
  // 裂纹积尘：裂缝里积灰接光的碎屑亮痕（暗缝旁 1px 灰尘 catch，克制撒点）
  const dust = new Graphics();
  for (const [dx, dy, l] of [
    [0.171, 560, 5], [0.172, 576, 6], [0.169, 592, 4],
    [0.683, 556, 5], [0.681, 576, 6], [0.686, 596, 4], [0.684, 610, 5],
  ]) {
    dust.moveTo(dx * W + 1.5, dy);
    dust.lineTo(dx * W + 1.5 + l, dy + 1);
  }
  dust.stroke({ width: 1, color: 0x9aa0a8, alpha: 0.13 });
  holder.addChild(dust);
  // 两端磨圆的老角：后棱角被摸圆的岁月痕迹（暗豁口 + 内侧浅受光弧）
  const wornDark = new Graphics();
  const wornCatch = new Graphics();
  for (const [wx, dir] of [[T.backInset * W + 2, 1], [(1 - T.backInset) * W - 2, -1]]) {
    wornDark.moveTo(wx, T.backSideY - 1);
    wornDark.quadraticCurveTo(wx + dir * 26, T.backSideY + 3, wx + dir * 30, T.backSideY + 26);
    wornCatch.moveTo(wx + dir * 8, T.backSideY + 5);
    wornCatch.quadraticCurveTo(wx + dir * 20, T.backSideY + 8, wx + dir * 23, T.backSideY + 22);
  }
  wornDark.stroke({ width: 2.5, color: 0x0b0a0d, alpha: 0.5 });
  wornCatch.stroke({ width: 1, color: 0xa8a49a, alpha: 0.14 });
  holder.addChild(wornDark, wornCatch);

  // 台面轮廓遮罩（实测 v8.21：mask 本体不会作为内容渲染；
  // 误设 renderable=false 反而使遮罩取空、被遮罩层整体不渲染）
  const mask = new Graphics();
  tablePath(mask, T);
  mask.fill(0xffffff);
  L.addChild(mask);
  holder.mask = mask;
}

// 角色专属剪影（blockout 锁定稿）
function drawRoleBody(body, c) {
  const w = c.shW;
  // 躯干：先知为收腰长袍，其余为通用圆角袍
  if (c.id === 'prophet') {
    body.poly([-30, -214, 30, -214, 18, 0, -18, 0]).fill(c.color);
  } else {
    body.roundRect(-w * 0.42, -214, w * 0.84, 214, 26).fill(c.color);
  }
  switch (c.id) {
    case 'prophet': // 窄肩 + 高尖兜帽
      body.roundRect(-w / 2, -248, w, 56, 20).fill(c.color);
      body.circle(0, -276, c.headR).fill(c.color);
      body.circle(0, -268, c.headR * 0.6).fill(0x0d070a);
      body.poly([-18, -296, 0, -352, 18, -296]).fill(c.color);
      break;
    case 'knight': // 宽甲 + 双肩甲球 + 小盔头
      body.roundRect(-w / 2, -248, w, 56, 22).fill(c.color);
      body.circle(0, -278, c.headR).fill(c.color);
      body.circle(0, -274, c.headR * 0.55).fill(0x0d070a);
      body.circle(-w / 2 + 8, -240, 17).fill(c.color);
      body.circle(w / 2 - 8, -240, 17).fill(c.color);
      break;
    case 'nun': // 纤细竖长 + 垂坠头巾
      body.roundRect(-w / 2, -248, w, 56, 20).fill(c.color);
      body.circle(0, -278, c.headR).fill(c.color);
      body.circle(0, -272, c.headR * 0.55).fill(0x0d070a);
      body.roundRect(-c.headR * 0.7, -252, c.headR * 1.4, 44, 14).fill(c.color);
      break;
    case 'king': // 最大最宽 + 王冠尖顶（锁定不变）
      body.roundRect(-w / 2, -248, w, 56, 22).fill(c.color);
      body.circle(0, -278, c.headR).fill(c.color);
      body.circle(0, -272, c.headR * 0.55).fill(0x0d070a);
      body.rect(-26, -312, 52, 10).fill(c.color);
      body.poly([-24, -306, -16, -332, -8, -306]).fill(c.color);
      body.poly([-8, -306, 0, -340, 8, -306]).fill(c.color);
      body.poly([8, -306, 16, -332, 24, -306]).fill(c.color);
      break;
    case 'wanderer': // 佝偻：高低肩 + 头前移 12px + 大背包 + 前倾 tilt 0.075
      body.roundRect(-w / 2, -264, w * 0.56, 50, 20).fill(c.color);
      body.roundRect(-w * 0.06, -248, w * 0.56, 50, 20).fill(c.color);
      body.circle(12, -266, c.headR).fill(c.color);
      body.circle(12, -260, c.headR * 0.55).fill(0x0d070a);
      body.circle(-20, -232, 30).fill(c.color);
      break;
    case 'doctor': // 鸟喙朝画面中心（左）前伸 ~40px + 头部前倾 + 宽檐帽
      body.roundRect(-w / 2, -248, w, 56, 22).fill(c.color);
      body.circle(-6, -276, c.headR).fill(c.color);
      body.circle(-6, -272, c.headR * 0.5).fill(0x0d070a);
      body.poly([-10, -284, -46, -260, -8, -250]).fill(c.color);
      body.ellipse(-6, -300, 46, 9).fill(c.color);
      body.roundRect(-20, -316, 28, 20, 6).fill(c.color);
      break;
  }
}

// ── 局面状态（AP 单例：hud 的 AP 轨与卡牌可用性联动；cardHover 钩子由 main.js
//    桥接到 EldritchEye——悬停卡牌时邪眼突然睁开注视该牌）─────────────────
export const GAME = {
  ap: 3, max: 3, _cb: [], cardHover: null, actionCard: null, cardActionEnabled: null,
  privateIntel: { ownerSeatId: 'P1', entries: [], manualTrustMarks: {}, seenEntryIds: [], sessionKey: null },
  // Browser mode keeps Pixi hover feedback but lets the DOM/GameSession own clicks.
  hoverOnly: false,
  onApi(fn) { this._cb.push(fn); },
  notify() { this._cb.forEach((f) => f()); },
  _intelCb: [],
  onIntel(fn) { this._intelCb.push(fn); },
  notifyIntel() { this._intelCb.forEach((f) => f(this.privateIntel)); },
  setPrivateIntel(value) {
    this.privateIntel = value || { ownerSeatId: 'P1', entries: [], manualTrustMarks: {}, seenEntryIds: [], sessionKey: null };
    this.notifyIntel();
  },
  cycleTrustMark(seatId) {
    const marks = { ...(this.privateIntel?.manualTrustMarks || {}) };
    const order = [null, 'trusted', 'watch', 'suspicious'];
    const current = marks[seatId] || null;
    const next = order[(order.indexOf(current) + 1) % order.length];
    if (next) marks[seatId] = next;
    else delete marks[seatId];
    this.privateIntel = { ...this.privateIntel, manualTrustMarks: marks };
    this.notifyIntel();
  },
  spend(n) { this.ap = Math.max(0, this.ap - n); this.notify(); },
  // —— 任务与队伍（Gameplay UI Restructure）——
  mission: { round: 1, total: 5, required: 2, failVotes: 1, results: [null, null, null, null, null] },
  party: [],            // 已选座位 seatId 列表（顺序=选择顺序）
  _partyCb: [],
  onParty(fn) { this._partyCb.push(fn); },
  notifyParty() { this._partyCb.forEach((f) => f()); },
  // 点选/取消角色（角色本体是主要交互）：再点已选=取消；满员时不可加选；
  // 结算动画期间锁定（新回合未开启前不接受选人）
  toggleSeat(seatId) {
    if (this.resolving) return;
    const i = this.party.indexOf(seatId);
    if (i >= 0) this.party.splice(i, 1);
    else if (this.party.length < this.mission.required) this.party.push(seatId);
    this.notifyParty();
  },
  partyFull() { return this.party.length >= this.mission.required; },
  // —— 回合闭环：确认派遣 → 结算动画（hud updater 播放）→ nextRound ——
  resolving: false, resolveStart: 0, resolveOutcome: null, _roundCb: [],
  onRound(fn) { this._roundCb.push(fn); },
  confirmReady() { return this.partyFull() && !this.resolving; },
  beginResolve(outcome) {
    if (!this.confirmReady()) return false;
    this.resolving = true;
    this.resolveOutcome = outcome;
    this.resolveStart = performance.now();
    return true;
  },
  // 结算落账：结果写入进度条 → 轮次推进 → AP 回满 → 清空队伍 → 全量通知
  finishResolve() {
    const m = this.mission;
    m.results[m.round - 1] = this.resolveOutcome;
    if (m.round < m.total) m.round++;
    this.ap = this.max;
    this.party = [];
    this.resolving = false;
    this.notify();        // AP 轨重绘 + 各卡 playOK 重估
    this.notifyParty();   // token 行按新 required 重建（空队伍）
    this._roundCb.forEach((f) => f()); // 已出卡复活回手牌等
  },
};

// ── 围坐议会布板（2026-09-21 最终融入 pass）──────────────────────────────
// 左簇(先知/骑士/修女)+右簇(国王/流浪者/医者)；中央 修女右缘(580)→王左缘(866) ≈286px
// 城堡视窗。体量层级：王(胸线宽 188-194+冠)>骑士(肩甲 197=左墙)>流浪者(背包 179)>
// 医者(108)>修女(96)≈先知(97 但极窄长)。尺寸刻意不归一（王仅 +4%；骑士成墙允许
// 盔顶略高于冠——王仍以宽度+王冠保持第一体量）。
// 议会弧走脚位相对关系：骑士/王最深(最近 797/788)，外侧先知/医者最浅(最远 772/767)——
// 放大后脚位统一加深保住 44-47% 坐姿裁切（若按字面"外侧上提"裁切破读成站像）。
// 脚沉在台面后缘弧(y528-538)之后由桌体自然遮挡；烛光受光+接触暗部见 CANDLE_ACCENTS。
const COUNCIL = {
  prophet:  { x: 152,  h: 448, feet: 762, top: 331 },  // +18%；兜帽尖 331（全席最高，外侧露最多躯干）
  knight:   { x: 314,  h: 470, feet: 812, top: 338 },  // +13%；盔顶 338；肩甲 202 宽=左侧之墙(主强化)
  nun:      { x: 532,  h: 419, feet: 773, top: 347 },  // +8%；兜帽顶 354 附近；高窄
  king:     { x: 960,  h: 447, feet: 793, top: 341 },  // +4%；冠顶 348 附近；第一体量
  wanderer: { x: 1168, h: 420, feet: 773, top: 347 },  // +7%；背包顶 353；异形不对称
  doctor:   { x: 1352, h: 432, feet: 760, top: 335 },  // +13%；帽顶 328 附近；宽檐+喙朝左
};
// 议会弧=碗状裁切：中排(骑士/修女/王/流浪者)裁得更高沉进桌后(裁 0.416-0.44)，
// 外侧(先知/医者)露更多躯干(0.485-0.50)且头更高——桌面切线是平的，弧由躯干露出量表达。
// 烛光融入层（渲染序=暗盘→反弹→缘口）：只推色相不推明度——全部挂 0xd98a3a 暖橙
// tint（加法后在暗值上呈深橙可感知，而非被吞成灰白）；bounce=低位反弹(中心 y512),
// acc=特征缘口受光 [x,y,w,h,alpha]（acc2=可选第二缘口），bias=向最近烛源偏置,
// ao=切线接触暗部
const CANDLE_ACCENTS = {
  prophet:  { acc: [172, 412, 88, 26, 0.22], acc2: [152, 352, 46, 18, 0.10], bw: 121, bias: 14 }, // 兜帽右缘+帽尖(烛1最近)
  knight:   { acc: [314, 442, 205, 32, 0.26], bw: 226, bias: -12 }, // 肩甲顶缘(烛1在左)
  nun:      { acc: [532, 472, 84, 26, 0.18], bw: 120, bias: -12 },  // 兜帽缘(烛2在左)
  king:     { acc: [960, 386, 62, 22, 0.19], bw: 226, bias: -10 }, // 冠缘(烛3在左)
  wanderer: { acc: [1140, 416, 130, 28, 0.16], bw: 215, bias: -16 }, // 背包缘(烛3在左)
  doctor:   { acc: [1298, 421, 70, 24, 0.22], bw: 135, bias: 8 },   // 鸟喙面具缘(烛4在右)
};

function characters(L, charTexs) {
  const seatStates = []; // 角色交互态（hover/选中环）——Gameplay UI Restructure
  const figures = CHARACTERS.map((c, i) => {
    const seat = COUNCIL[c.id];
    const holder = new Container();
    const shadow = new Graphics().ellipse(0, 0, 72, 18).fill({ color: 0x000000, alpha: 0.45 });
    let body;
    const tex = charTexs && charTexs[c.id];
    if (tex) {
      body = new Sprite(tex);
      body.anchor.set(0.5, 1);
      body.scale.set(seat.h / tex.height);
      body.y = 2; // 脚尖略沉进接地阴影（下沉走 holder.position，见下）
    } else {
      body = new Graphics();
      drawRoleBody(body, c);
      body.scale.set(seat.h / 352); // 剪影体系按 352 基高等比放大
    }
    holder.addChild(shadow, body);
    // 脚位并入 holder.position（呼吸 updater 每帧覆写 body.y，sink 若放 body.y 会被
    // 完全冲掉——v3-v5 医者帽一直顶在面板后就是这个 bug，A/B 差分帧相同暴露的）。
    // 医者帽顶 364 仍留任务面板(y30-350)下缘 14px 净空
    holder.position.set(seat.x, seat.feet);
    // 流浪者的佝偻已画进立绘本身，holder 倾斜减半避免过度前倾
    if (c.tilt) body.rotation = tex ? c.tilt * 0.5 : c.tilt;
    // 末端二人补一层暖光纱（加法极淡）：画面两端本就最暗，立绘又是深值——
    // 不补这层时读成纯黑剪影"贴"在黑边上，与中央四人接烛光的体积感脱节
    if (tex && (c.id === 'prophet' || c.id === 'doctor')) {
      const warm = new Sprite(getGlowTexture('ember'));
      warm.anchor.set(0.5);
      warm.blendMode = 'add';
      warm.tint = 0xd98a3a;
      warm.alpha = c.id === 'prophet' ? 0.11 : 0.07;
      warm.scale.set(190 / 128, 420 / 128);
      // 暖纱中心跟可见躯干走（0.75≈头肩胸中带）：下沉后光晕若停在躯干
      // 原中心会整段沉进桌沿以下，躯干只剩淡边——"黑剪影贴黑边"读法回归
      warm.position.set(0, -tex.height * body.scale.x * 0.75);
      holder.addChild(warm);
    }
    L.addChild(holder);
    // —— 角色本体=队伍选择交互（Gameplay UI Restructure）——
    // hover=轻微提亮（暖 tint 不做 glow）；点击=选入/取消（GAME.toggleSeat）；
    // 选中=脚下细 selection ring（桌游 token 感）。P1 与 AI 座位同一逻辑，不锁定。
    const seatData = SEATS.find((s) => s.characterId === c.id);
    if (seatData) {
      const st2 = { hov: 0 };
      holder.eventMode = 'static';
      holder.cursor = 'pointer';
      holder.on('pointerover', () => { st2.hov = 1; });
      holder.on('pointerout', () => { st2.hov = 0; });
      holder.on('pointertap', () => {
        if (GAME.hoverOnly) return;
        GAME.toggleSeat(seatData.seatId);
        window.__TAPLOG.push(seatData.seatId);
      });
      // 选中细环：脚下扁椭圆描边（座位 accent，细 1.5px，无 glow）
      const ring = new Graphics();
      ring.ellipse(0, -4, seat.h * 0.16, 10).stroke({ width: 1.5, color: seatData.accent, alpha: 0.85 });
      ring.position.set(0, -seat.h * 0.02);
      ring.visible = false;
      holder.addChildAt(ring, 0);
      seatStates.push({ holder, body, st2, ring, seatId: seatData.seatId });
    }
    return { body, phase: i * 1.3 };
  });
  // 选中环与提亮的统一刷新（GAME.party 驱动）
  GAME.onParty(() => {
    for (const s of seatStates) s.ring.visible = GAME.party.includes(s.seatId);
  });
  // 调试钩子（CDP 测试用）：角色交互态 + 队伍 + tap 日志
  window.__TAPLOG = [];
  window.__SEATS_DEBUG = () => ({
    ap: GAME.ap, party: [...GAME.party], taps: [...window.__TAPLOG],
    seats: seatStates.map((s) => ({
      seatId: s.seatId, sel: GAME.party.includes(s.seatId),
      hov: s.st2.hov, hovV: +(s.st2.hovV ?? 0).toFixed(2), ring: s.ring.visible,
    })),
  });
  // ── 烛光融入层（加于各 holder 之后=渲染于人物之上，台面 z125 之下）──
  // 不整体提亮：只给①低位胸面烛光反弹 ②兜帽/肩甲/冠/鸟喙等缘口受光
  // ③切线接触暗部。背侧与外侧保持暗——受光一律朝最近烛源偏置，从桌面方向来。
  const candle = [];
  CHARACTERS.forEach((c, i) => {
    const seat = COUNCIL[c.id];
    const spec = CANDLE_ACCENTS[c.id];
    // 低位反弹：宽扁加法暖光——中心 y512 落进可见带下段，烛光贴桌沿处最亮。
    // tint 只推色相：加法在暗值上呈深橙可感知，纯提亮会被暗调吞成灰白
    const bounce = new Sprite(getGlowTexture('ember'));
    bounce.anchor.set(0.5);
    bounce.blendMode = 'add';
    bounce.tint = 0xd98a3a;
    bounce.position.set(seat.x + spec.bias, 512);
    bounce.scale.set(spec.bw / 128, 96 / 128);
    bounce.alpha = 0.16;
    // 缘口受光：小面积加法亮斑，落点=该剪影特征的实际行高（肩甲顶/冠/喙）；
    // acc2=可选第二缘口（先知帽尖：把视线引上尖顶，强化可读性而非放大尺寸）
    const edges = [spec.acc, spec.acc2].filter(Boolean).map(([ax, ay, aw, ah, aa]) => {
      const e = new Sprite(getGlowTexture('ember'));
      e.anchor.set(0.5);
      e.blendMode = 'add';
      e.tint = 0xd98a3a;
      e.position.set(ax, ay);
      e.scale.set(aw / 128, ah / 128);
      e.alpha = aa;
      L.addChild(e);
      return { s: e, a0: aa };
    });
    // 接触暗部：y546 压暗盘——下半被台面(z125)盖住，只留躯干下缘 496-538 的
    // 渐隐暗带，身体"沉进"桌面后缘的环境光遮蔽（贴桌读法的关键）
    const ao = new Sprite(getGlowTexture('socket'));
    ao.anchor.set(0.5);
    ao.position.set(seat.x, 546);
    ao.scale.set(spec.bw / 128, 100 / 128);
    ao.alpha = 0.36;
    // 渲染序：暗盘在最底，反弹/缘口叠其上——烛光在接触线附近穿透 AO
    L.addChild(ao, bounce);
    candle.push({ bounce, edges, phase: i * 1.7 });
  });
  return (t) => {
    for (const f of figures) f.body.y = Math.sin(t * 0.0011 + f.phase) * 3;
    // 角色交互反馈：hover 轻微提亮（向暖白 tint 插值，无 glow 的克制读法）
    for (const s of seatStates) {
      s.st2.hovV = (s.st2.hovV ?? 0) + (s.st2.hov - (s.st2.hovV ?? 0)) * 0.1;
      const k = s.st2.hovV;
      // 0xffffff → 0xfff2e0：R 恒 255，G/B 微降 31——"提亮"而非"染色"
      s.body.tint = (0xff << 16) | (Math.round(0xff - 0x0d * k) << 8) | Math.round(0xff - 0x1f * k);
    }
    // 受光随烛焰呼吸（低频小幅）：静光在满屏闪烁的烛池旁会读成"死灯"
    for (const k of candle) {
      const fl = 1 + Math.sin(t * 0.0007 + k.phase) * 0.12;
      k.bounce.alpha = 0.16 * fl;
      for (const e of k.edges) e.s.alpha = e.a0 * fl;
    }
  };
}

function tableProps(L) {
  const flames = [];
  // 蜡烛 ×4：沿后缘分布，桌心留空给队伍选择/确认按钮
  for (const [fx, baseY] of [[0.135, 592], [0.30, 578], [0.70, 580], [0.93, 596]]) {
    const x = fx * W;
    // 暖光"揭示"纱（普通混合）：先让烛下石面本身被照暖一点——
    // 光池才读成"照亮了石头"，而非浮在石面上的橙色加色
    const reveal = new Graphics();
    reveal.ellipse(0, 7, 62, 19).fill({ color: 0x6e5a44, alpha: 0.22 });
    reveal.position.set(x, baseY);
    L.addChild(reveal);
    // 烛下光池（双区制）：贴座小亮核 + 短轴中亮椭圆、向外快速衰减——
    // 亮部只属于烛池，四周石面回落中暗（局部光，非整幅洗光）
    const pool = new Sprite(getGlowTexture('ember'));
    pool.anchor.set(0.5);
    pool.blendMode = 'add';
    pool.scale.set(138 / 128, 40 / 128);
    pool.position.set(x, baseY + 8);
    pool.alpha = 0.42;
    const core = new Sprite(getGlowTexture('ember'));
    core.anchor.set(0.5);
    core.blendMode = 'add';
    core.scale.set(58 / 128, 20 / 128);
    core.position.set(x, baseY + 4);
    core.alpha = 0.68;
    L.addChild(pool, core);
    // 烛座：接触阴影、铜色托盘和一圈磨损高光，让蜡烛真正压在石桌上
    const saucer = new Graphics();
    saucer.ellipse(0, 7, 24, 7).fill({ color: 0x000000, alpha: 0.42 });
    saucer.ellipse(0, 4, 19, 5.5).fill({ color: 0x28161b, alpha: 0.96 });
    saucer.ellipse(0, 2, 16, 4.5).fill({ color: 0x6a4130, alpha: 0.8 });
    saucer.ellipse(0, 0.5, 13, 3.1).stroke({ width: 1.2, color: 0xc18a4b, alpha: 0.5 });
    saucer.ellipse(0, -1, 9, 2.2).fill({ color: 0x171014, alpha: 0.9 });
    saucer.position.set(x, baseY);
    L.addChild(saucer);

    // 烛身：暖白中央受光、暗红侧面、顶部蜡唇和不规则流痕
    const cs = new Graphics();
    cs.roundRect(-6, -26, 12, 27, 3).fill({ color: 0x88705c, alpha: 0.98 });
    cs.roundRect(-4.5, -26, 8, 25, 2.2).fill({ color: 0xd4c2a2, alpha: 0.98 });
    cs.rect(-3.2, -24, 2.2, 22).fill({ color: 0xf0ddb0, alpha: 0.62 });
    cs.ellipse(0, -26, 6, 2.5).fill({ color: 0x9b8168, alpha: 0.98 });
    cs.ellipse(0, -27, 3.9, 1.55).fill({ color: 0xe6d2ab, alpha: 0.9 });
    cs.moveTo(-4.8, -21).lineTo(-5.8, -14).lineTo(-5.1, -8);
    cs.moveTo(4.4, -18).lineTo(5.4, -12).lineTo(4.8, -6);
    cs.stroke({ width: 1.5, color: 0x937457, alpha: 0.72 });
    cs.ellipse(-5.2, -7, 1.4, 3.2).fill({ color: 0xc1a37b, alpha: 0.64 });
    // 烟熏与旧蜡渍只留在烛座附近，避免桌面出现新的块状占位感
    cs.ellipse(-13, 4, 7, 2.5).fill({ color: 0x9a8a6c, alpha: 0.28 });
    cs.ellipse(12, 5, 5, 2).fill({ color: 0x8a7a5e, alpha: 0.25 });
    cs.ellipse(-11, -6, 8, 4).fill({ color: 0x0a0a0c, alpha: 0.2 });
    cs.position.set(x, baseY);
    L.addChild(cs);

    // 灯芯和分层火焰：外焰橙红、内焰金黄、焰心淡色
    const flame = new Graphics();
    flame.moveTo(0, -47).lineTo(-5.6, -39).lineTo(-4.1, -32.2).lineTo(0, -28.2);
    flame.lineTo(4.2, -33.4).lineTo(5.2, -40.2).closePath();
    flame.fill({ color: 0xc94e2d, alpha: 0.95 });
    flame.poly([0, -44, -3.2, -38, -2.5, -33, 0, -29.6, 2.6, -34.6, 2.8, -39.6])
      .fill({ color: 0xffa53e, alpha: 0.98 });
    flame.ellipse(0, -35.2, 1.8, 4.3).fill({ color: 0xffe4a3, alpha: 0.98 });
    flame.moveTo(0, -27).lineTo(0, -31).stroke({ width: 1.3, color: 0x24151a, alpha: 0.9 });
    flame.position.set(x, baseY);
    L.addChild(flame);
    const glow = new Sprite(getGlowTexture('ember'));
    glow.anchor.set(0.5);
    glow.blendMode = 'add';
    glow.scale.set(42 / 128);
    glow.position.set(x, baseY - 34);
    glow.alpha = 0.48;
    L.addChild(glow);
    flames.push({ flame, glow, pool, core, phase: flames.length * 2.1, baseX: x, baseY });
  }
  // 高脚杯剪影（右内侧，暗色金属，克制）
  const gob = new Graphics();
  gob.ellipse(0, 1, 12, 4).fill({ color: 0x000000, alpha: 0.4 });
  gob.ellipse(0, -20, 11, 9).fill(0x171012);
  gob.ellipse(0, -20, 11, 9).stroke({ width: 1.5, color: 0x5a4438, alpha: 0.6 });
  gob.rect(-2, -13, 4, 11).fill(0x171012);
  gob.ellipse(0, -1, 8, 2.5).fill(0x171012);
  gob.position.set(W * 0.645, 604);
  L.addChild(gob);
  return (t) => {
    for (const f of flames) {
      const k = 0.76 + Math.sin(t * 0.012 + f.phase) * 0.16;
      const sway = Math.sin(t * 0.014 + f.phase) * 0.9;
      const lift = Math.sin(t * 0.017 + f.phase * 1.2) * 0.55;
      f.flame.alpha = k;
      f.flame.x = f.baseX + sway;
      f.flame.y = f.baseY + lift;
      f.flame.scale.set(
        0.92 + Math.sin(t * 0.02 + f.phase * 1.4) * 0.1,
        0.96 + Math.sin(t * 0.018 + f.phase) * 0.12,
      );
      f.glow.x = f.baseX + sway * 0.35;
      f.glow.y = f.baseY - 34 + lift * 0.35;
      f.glow.alpha = 0.34 + 0.22 * k;
      f.pool.alpha = 0.3 + 0.26 * k;
      f.core.alpha = 0.54 + 0.24 * k;
    }
  };
}

// 前缘立面：厚重切面（烛光体积受光 + 浅裂纹 + 棱缘崩缺 + 底部沉入阴影）
function tableFrontLip(L, tex) {
  const T = LAYOUT.table;
  const holder = new Container();
  L.addChild(holder);
  const yBotSide = T.frontSideY + T.lipSideH;
  const yBot = T.frontY + T.lipH;
  // 立面比台面左右各外扩 lipOutset（修复：此前误写成 ±outX 居中短带）
  const lipL = -(T.frontOut * W + T.lipOutset);
  const lipR = (1 + T.frontOut) * W + T.lipOutset;
  const faceH = yBot - T.frontSideY;

  if (tex) {
    // 石材连续裁切：立面取贴图自带前立面的上段（贴折缝，承接顶面投下的过梁阴影）
    const slab = new Sprite(getSlabCrops(tex, T).lip);
    // 纵向翻转：条带底行（=折缝行）显示到立面上缘——石纹跨折缝真正连续"包"过桌棱
    slab.scale.set((lipR - lipL) / slab.width, -faceH / slab.height);
    slab.position.set(lipL, T.frontSideY + faceH);
    slab.tint = 0x6e675f; // 立面暗于台面但必须读得出石面（v7 的 0x59554e×暗条带=近黑，厚板读不出来）
    holder.addChild(slab);
    // 立面罩染：更冷的薄纱把贴图细噪收进大面（立面是"折下来的同一块石头"，
    // 罩色比台面淡——明暗转折主要由 lipshade/faceMass 承担）
    const faceVeil = new Graphics();
    faceVeil.rect(lipL, T.frontSideY, lipR - lipL, faceH + 2).fill({ color: 0x23222a, alpha: 0.13 });
    holder.addChild(faceVeil);
    // 立面明暗：顶棱微受光 → 底部沉入阴影（贴图自带折角光影，只补冷暖）
    const shade = new Sprite(getGlowTexture('lipshade'));
    shade.position.set(lipL, T.frontSideY);
    shade.scale.set((lipR - lipL) / 8, faceH / 256);
    holder.addChild(shade);
    // 立面大色面（手绘值块语言）：lip 裁切条带在源贴图里左/右两端是画家画的暗值
    // （乘 tint 后≈黑，石面读不出）——用两块中值灰蓝大笔触把可见窗的石面"托"出来，
    // faceMass 暗块再压回其上，明暗由大面构成（与台面/城堡同一套笔法）；
    // 每块两层洋葱皮（外大淡/内小浓）=笔触边缘的软过渡，避免硬边"贴片"读法
    const facePlanes = new Graphics();
    facePlanes.poly([
      W * 0.198, 646, W * 0.24, 630, W * 0.30, 626, W * 0.372, 629, W * 0.408, 638,
      W * 0.402, 660, W * 0.33, 670, W * 0.252, 670, W * 0.212, 660,
    ]).fill({ color: 0x4a505c, alpha: 0.24 });
    facePlanes.poly([
      W * 0.225, 640, W * 0.262, 630, W * 0.315, 628, W * 0.365, 632, W * 0.392, 640,
      W * 0.386, 654, W * 0.33, 663, W * 0.268, 664, W * 0.238, 654,
    ]).fill({ color: 0x4a505c, alpha: 0.26 });
    facePlanes.poly([
      W * 0.772, 632, W * 0.83, 622, W * 0.876, 628, W * 0.872, 650, W * 0.796, 656,
    ]).fill({ color: 0x4a505c, alpha: 0.15 });
    facePlanes.poly([
      W * 0.792, 630, W * 0.832, 624, W * 0.86, 629, W * 0.856, 644, W * 0.806, 649,
    ]).fill({ color: 0x4a505c, alpha: 0.16 });
    holder.addChild(facePlanes);
    // 立面烛光反弹（加法暖光）：只贴在卡扇/面板夹出的两个可见立面窗口
    // （左窗 x315-658 / 右窗 x1048-1536 上半）——中央段被中央卡整个吞掉，光给那里是浪费
    for (const [bfx, bw] of [[0.317, 0.24], [0.815, 0.26]]) {
      const bounce = new Sprite(getGlowTexture('ember'));
      bounce.anchor.set(0.5);
      bounce.blendMode = 'add';
      bounce.scale.set((W * bw) / 128, 34 / 128);
      bounce.position.set(W * bfx, T.frontSideY + faceH * 0.52);
      bounce.alpha = 0.15;
      holder.addChild(bounce);
    }
  } else {
    const flat = new Graphics();
    flat.rect(lipL, T.frontSideY, lipR - lipL, faceH).fill(0x2e2e33);
    holder.addChild(flat);
  }
  // ── 立面手绘值块结构（大暗形 + 棱下遮蔽 + 烛位受光碎段 + 竖切槽）──
  // 沿折线/底弧取 y（x→贝塞尔采样；线性近似在中央段偏差 ~8px 不可用）
  const foldC = 2 * T.frontY - T.frontSideY;
  const foldY = (x) => {
    const t = (x - lipL) / (lipR - lipL);
    const mt = 1 - t;
    return mt * mt * T.frontSideY + 2 * mt * t * foldC + t * t * T.frontSideY;
  };
  const botY = (x) => {
    const t = (x - lipL) / (lipR - lipL);
    const mt = 1 - t;
    return mt * mt * yBotSide + 2 * mt * t * (2 * yBot - yBotSide) + t * t * yBotSide;
  };
  // 大笔触暗部体块 ×3（非对称、避开烛位）：立面不再均匀等亮，
  // 中央与两端亮度有别——与城堡剪影的"大暗形"语言一致。
  // 块顶边一律压到折线 +8px 以下：不遮 bevelCatch 受光碎段与棱下遮蔽带
  const faceMass = new Graphics();
  faceMass.poly([
    lipL, T.frontSideY + 18, W * 0.17, T.frontSideY + 16, W * 0.26, T.frontSideY + 22,
    W * 0.245, botY(W * 0.245) - 4, W * 0.10, botY(W * 0.10) - 2, lipL, yBotSide,
  ]).fill({ color: 0x0c0b0e, alpha: 0.33 });
  faceMass.poly([
    W * 0.40, T.frontSideY + 16, W * 0.50, T.frontSideY + 14, W * 0.515, T.frontSideY + 34,
    W * 0.465, botY(W * 0.465) - 6, W * 0.405, botY(W * 0.405) - 9,
  ]).fill({ color: 0x0c0b0e, alpha: 0.29 });
  faceMass.poly([
    W * 0.775, T.frontSideY + 16, W * 0.87, T.frontSideY + 20, W * 0.895, T.frontSideY + 30,
    W * 0.855, botY(W * 0.855) - 5, W * 0.795, botY(W * 0.795) - 2,
  ]).fill({ color: 0x0c0b0e, alpha: 0.31 });
  holder.addChild(faceMass);
  // 棱下遮蔽暗带（全宽）：顶面出檐在立面顶缘压出的本影，位于受光碎段之下——
  // 厚板"上檐探出、立面内收"的体积读法（暗缝而非连续亮线）
  const occl = new Graphics();
  for (let k = 0; k <= 20; k++) {
    const x = lipL + ((lipR - lipL) * k) / 20;
    const y = foldY(x) + 8.5;
    if (k === 0) occl.moveTo(x, y); else occl.lineTo(x, y);
  }
  occl.stroke({ width: 10, color: 0x0a080b, alpha: 0.66 });
  holder.addChild(occl);
  // 竖向哥特切槽 ×3：立面浅刻竖切（古老仪式语言的克制残留，非通栏装饰）
  const vcuts = new Graphics();
  for (const [vfx, hFrac] of [[0.215, 0.5], [0.475, 0.38], [0.845, 0.55]]) {
    const y0 = foldY(vfx * W) + 9;
    vcuts.moveTo(vfx * W, y0);
    vcuts.lineTo(vfx * W + 1.5, y0 + faceH * hFrac);
  }
  vcuts.stroke({ width: 2.2, color: 0x0e0c11, alpha: 0.45 });
  holder.addChild(vcuts);
  // 烛光外溢：台面烛火越过桌棱，在立面顶端落下暖光斑——顶棱受光来自
  // 体积光（贴折缝明暗 + 光斑），不再用整圈描边线（那是"图形化发光边"）
  for (const fx of [0.135, 0.30, 0.70, 0.93]) {
    const x = fx * W;
    // 按真折线（贝塞尔）取 y——线性近似在中央段比真实折线高 ~8px
    const t = ((1 + T.frontOut) * W - x) / (W * (1 + T.frontOut * 2));
    const mt = 1 - t;
    const fy = mt * mt * T.frontSideY + 2 * mt * t * (2 * T.frontY - T.frontSideY) + t * t * T.frontSideY;
    const spill = new Sprite(getGlowTexture('ember'));
    spill.anchor.set(0.5);
    spill.blendMode = 'add';
    spill.scale.set(84 / 128, 32 / 128);
    spill.position.set(x, fy + 10);
    spill.alpha = 0.46;
    holder.addChild(spill);
  }
  // 折缝下侧暗缝（上侧由 tableSurface 的 crease 负责，合成完整转折暗线）
  const seam = new Graphics();
  seam.moveTo(lipL, T.frontSideY);
  seam.quadraticCurveTo(W / 2, 2 * T.frontY - T.frontSideY, lipR, T.frontSideY);
  seam.stroke({ width: 3, color: 0x0e0a0c, alpha: 0.88 });
  holder.addChild(seam);
  // 棱缘受光碎段 + 棱下受光面：只出现在烛火真能照到的棱段（四烛位），宽度不一、微起伏；
  // catch=短斜切面接烛光，下方再压一条更宽更淡的受光面（bevelPlane）——
  // "棱是有厚度的斜切面被照亮"而非一条描边线/发光边
  const bevelCatch = new Graphics();
  const bevelPlane = new Graphics();
  const catchSegs = [[0.135, 64], [0.30, 84], [0.70, 76], [0.93, 96]];
  for (const [cfx, segW] of catchSegs) {
    for (let k = 0; k <= 10; k++) {
      const x = cfx * W + (k / 10 - 0.5) * segW;
      const y = foldY(x) + 3 + Math.sin(k * 2.1) * 0.7;
      if (k === 0) bevelCatch.moveTo(x, y); else bevelCatch.lineTo(x, y);
    }
    for (let k = 0; k <= 10; k++) {
      const x = cfx * W + (k / 10 - 0.5) * (segW * 0.92);
      const y = foldY(x) + 6.5 + Math.sin(k * 1.7 + 1) * 0.9;
      if (k === 0) bevelPlane.moveTo(x, y); else bevelPlane.lineTo(x, y);
    }
  }
  bevelCatch.stroke({ width: 5.2, color: 0xcdbfa0, alpha: 0.55 });
  bevelPlane.stroke({ width: 5, color: 0xb3a284, alpha: 0.16 });
  holder.addChild(bevelCatch, bevelPlane);
  // 棱缘崩缺：沿弧线的不规则豁口（岁月磨损，打破笔直棱线）——
  // 崩口暗缺 + 断裂面下唇一点烛光 catch（受光体积，非描边）
  // 沿真折线（贝塞尔）取 y：线性近似在中央段比真实折线高出 ~8px，
  // 会把崩缺/裂纹画进台面区而被遮罩裁掉——必须与遮罩用同一条二次曲线求值
  const edgeY = (fx) => {
    const t = ((1 + T.frontOut) * W - fx * W) / (W * (1 + T.frontOut * 2));
    const mt = 1 - t;
    return mt * mt * T.frontSideY + 2 * mt * t * (2 * T.frontY - T.frontSideY) + t * t * T.frontSideY;
  };
  const chipDefs = [[0.135, 23, 9], [0.315, 15, 6], [0.475, 12, 5], [0.62, 19, 8], [0.795, 13, 5], [0.90, 20, 8]];
  const chips = new Graphics();
  for (const [fx, cw, ch] of chipDefs) {
    const x = fx * W;
    const ey = edgeY(fx) - 1;
    chips.moveTo(x, ey);
    chips.lineTo(x + cw, ey);
    chips.lineTo(x + cw * 0.45, ey + ch);
    chips.closePath();
  }
  chips.fill(0x050407);
  const chipCatch = new Graphics();
  for (const [fx, cw, ch] of chipDefs) {
    const x = fx * W;
    const ey = edgeY(fx) - 1;
    chipCatch.moveTo(x + cw * 0.45, ey + ch - 0.5);
    chipCatch.lineTo(x + cw - 1, ey + 1.5);
  }
  chipCatch.stroke({ width: 1.5, color: 0xbfae92, alpha: 0.36 });
  holder.addChild(chips, chipCatch);
  // 立面浅裂纹（克制）：0.685 主裂与台面主裂首尾相接（贯穿独石读法），
  // 其余两条短浅裂；不再密铺——裂纹糊脸=纹理化，违反值块语言
  const seams = new Graphics();
  const seamDefs = [[0.30, 5, 26], [0.685, 3, 46, true], [0.79, 5, 28]];
  for (const [fx, h0, h1, fork] of seamDefs) {
    const sx = fx * W;
    const y0 = edgeY(fx) + h0;
    seams.moveTo(sx, y0);
    seams.lineTo(sx + 2.5, y0 + (h1 - h0) * 0.42);
    seams.lineTo(sx - 1.5, y0 + (h1 - h0) * 0.75);
    seams.lineTo(sx + 0.5, y0 + (h1 - h0));
    if (fork) {
      seams.moveTo(sx + 2.5, y0 + (h1 - h0) * 0.42);
      seams.lineTo(sx + 8, y0 + (h1 - h0) * 0.6);
    }
  }
  seams.stroke({ width: 1.8, color: 0x0d0d10, alpha: 0.68 });
  holder.addChild(seams);
  // 底部分界：暖回光只在烛位近旁留碎段（远离烛光的底缘沉进黑暗）
  // + 近黑底缘——立面与桌底黑暗的分界
  const edgeWarm = new Graphics();
  for (const cfx of [0.135, 0.30, 0.70, 0.93]) {
    for (let k = 0; k <= 10; k++) {
      const x = cfx * W + (k / 10 - 0.5) * 64;
      const y = botY(x) - 3;
      if (k === 0) edgeWarm.moveTo(x, y); else edgeWarm.lineTo(x, y);
    }
  }
  edgeWarm.stroke({ width: 1.5, color: 0x6a5644, alpha: 0.35 });
  const edgeDark = new Graphics();
  edgeDark.moveTo(lipL, yBotSide + 0.5);
  edgeDark.quadraticCurveTo(W / 2, 2 * yBot - yBotSide + 0.5, lipR, yBotSide + 0.5);
  edgeDark.stroke({ width: 6.5, color: 0x060305, alpha: 1 });
  holder.addChild(edgeWarm, edgeDark);
  // 底缘侵蚀豁口：立面底边的不规则啃缺，填色与桌下黑暗同源——
  // 底部轮廓从"笔直长线"变参差断口，桌不再读成规整墙沿/台座
  const erosion = new Graphics();
  // 豁口只落在"大暗块之外"的可见窗口（0.265-0.34 / 0.70-0.775W），
  // 暗块内的豁口会黑上加黑、毫无对比
  const erosionDefs = [[0.265, 12, 5], [0.335, 18, 9], [0.70, 18, 8], [0.755, 12, 5], [0.77, 24, 12]];
  for (const [fx, w, ch] of erosionDefs) {
    const x = fx * W;
    const yb = botY(x);
    erosion.moveTo(x - 2, yb + 3);
    erosion.lineTo(x + w, yb + 3);
    erosion.lineTo(x + w * 0.42, yb - ch);
    erosion.lineTo(x + w * 0.12, yb - ch * 0.35);
    erosion.closePath();
  }
  erosion.fill(0x060305);
  // 侵蚀豁口的受光断口边：下半立面已沉入暗部，豁口本体与黑底无对比——
  // 断口上缘一点暖 catch 才能在近黑里读出"这里缺了一块"的参差轮廓
  const erosionCatch = new Graphics();
  for (const [fx, w, ch] of erosionDefs) {
    const x = fx * W;
    const yb = botY(x);
    erosionCatch.moveTo(x + w * 0.42, yb - ch + 0.5);
    erosionCatch.lineTo(x + w * 0.12, yb - ch * 0.35 + 0.5);
  }
  erosionCatch.stroke({ width: 1.5, color: 0x8a7a62, alpha: 0.35 });
  holder.addChild(erosion, erosionCatch);

  // 立面轮廓遮罩（同台面：不可设 renderable=false）
  const mask = new Graphics();
  mask.moveTo(lipL, T.frontSideY);
  mask.quadraticCurveTo(W / 2, 2 * T.frontY - T.frontSideY, lipR, T.frontSideY);
  mask.lineTo(lipR, yBotSide);
  mask.quadraticCurveTo(W / 2, 2 * yBot - yBotSide, lipL, yBotSide);
  mask.closePath();
  mask.fill(0xffffff);
  L.addChild(mask);
  holder.mask = mask;
}

// 两侧祭坛石墩（宽重化+暖炭灰色阶）：两级基座帽头贴着立面底缘，墩身浅刻神龛、
// 大部没入黑暗（可见 ~30%）——"有巨大结构撑住整块石板"而非"看得清桌腿"
function tableSupport(L) {
  const T = LAYOUT.table;
  const lipL = -(T.frontOut * W + T.lipOutset);
  const lipR = (1 + T.frontOut) * W + T.lipOutset;
  const yBotSide = T.frontSideY + T.lipSideH;
  const cpY = 2 * (T.frontY + T.lipH) - yBotSide;
  // 墩位实测（对话面板/羊皮纸/卡扇三者夹出的唯一可见带）：
  // 0.27W 帽头躲开对话面板右缘315px 与卡扇左角；0.73W 躲开羊皮纸左缘1240px
  for (const cx of [W * 0.27, W * 0.73]) {
    // 墩顶下移 5px：唇底近黑描边与帽头亮线之间留出 ~2px 纯黑缝 + 黑描边本身——
    // "厚板悬在黑暗里的支座上"的读法全靠这条阴影缝，帽头亮线贴缝才读得出"从黑里顶出来"
    const t = (cx - lipL) / (lipR - lipL);
    const topY = yBotSide + 2 * t * (1 - t) * (cpY - yBotSide) + 5;
    const g = new Graphics();
    // 石墩帽头（宽重楔形帽板 + 双级踏步）：可见窄缝里"巨物顶出来"的读法
    // 全靠帽头亮棱与块面——上亮线/中块面/下暗register/踏步catch 的阶梯轮廓，非家具腿
    g.poly([cx - 74, topY, cx + 74, topY, cx + 58, topY + 28, cx - 58, topY + 28]).fill(0x4a443e);
    g.rect(cx - 74, topY, 148, 4.5).fill({ color: 0x9a8766, alpha: 0.95 });
    g.rect(cx - 58, topY + 18, 116, 9).fill({ color: 0x241f1c, alpha: 0.75 });
    g.rect(cx - 82, topY + 28, 164, 18).fill(0x35312c);
    g.rect(cx - 82, topY + 28, 164, 3).fill({ color: 0x6b6353, alpha: 0.9 });
    // 墩身（更宽的块状体量，浅刻神龛暗龛 + 横向凿刻带——祭坛语言，克制装饰）
    g.rect(cx - 52, topY + 40, 104, 74).fill(0x423c36);
    g.rect(cx - 46, topY + 66, 92, 2).fill({ color: 0x0e0c10, alpha: 0.55 });
    g.rect(cx - 46, topY + 68.5, 92, 1).fill({ color: 0x6a6252, alpha: 0.32 });
    g.roundRect(cx - 13, topY + 52, 26, 30, 5).fill({ color: 0x0b090d, alpha: 0.85 });
    g.poly([cx - 13, topY + 57, cx, topY + 46, cx + 13, topY + 57]).fill({ color: 0x0b090d, alpha: 0.85 });
    // 神龛拱缘受光（刻入暗龛的折面接一点烛光——龛"洞"而非色块）
    const rim = new Graphics();
    rim.roundRect(cx - 13, topY + 52, 26, 30, 5).stroke({ width: 1.5, color: 0x5e5748, alpha: 0.6 });
    L.addChild(rim);
    // 内侧受光棱（烛光暖灰，压在暗石上）
    const ex = cx < W / 2 ? cx + 42 : cx - 46;
    g.rect(ex, topY + 41, 4, 44).fill({ color: 0x6a5c46, alpha: 0.7 });
    // 铁箍（古老加固件，位于神龛下方）
    g.rect(cx - 34, topY + 86, 68, 6).fill(0x0d0a0c);
    g.rect(cx - 34, topY + 86, 68, 1.5).fill({ color: 0x3a3a42, alpha: 0.5 });
    // 底部没入黑暗（渐隐四段：可见带 ~1/3——帽头+墩肩必须"从黑暗里
    // 顶出来"承担承重读法，其余沉入桌底近黑，不露任何"地板"）
    g.rect(cx - 52, topY + 54, 104, 16).fill({ color: 0x050308, alpha: 0.42 });
    g.rect(cx - 52, topY + 70, 104, 16).fill({ color: 0x050308, alpha: 0.68 });
    g.rect(cx - 52, topY + 86, 104, 16).fill({ color: 0x040207, alpha: 0.92 });
    g.rect(cx - 52, topY + 100, 104, 34).fill({ color: 0x030106, alpha: 0.99 });
    L.addChild(g);
  }
}

// 前缘下方：桌底接触暗晕 + 迅速入黑（卡牌站在黑暗前景上，立面底缘分界清晰）
function tableFrontShadow(L) {
  const T = LAYOUT.table;
  const lipL = -(T.frontOut * W + T.lipOutset);
  const lipR = (1 + T.frontOut) * W + T.lipOutset;
  const yBotSide = T.frontSideY + T.lipSideH;
  const yBot = T.frontY + T.lipH;
  // 贴底弧黑压带：立面底缘以下"立刻沉黑"——顶面→立面→深黑→支座 转折的第三段。
  // 沿底缘贝塞尔取点向下延 22px 成带（含两端），侧端下方不再漏出背景
  const cpy = 2 * yBot - yBotSide;
  const band = new Graphics();
  for (let k = 0; k <= 24; k++) {
    const t = k / 24, mt = 1 - t;
    const x = lipL + (lipR - lipL) * t;
    const y = mt * mt * yBotSide + 2 * mt * t * cpy + t * t * yBotSide;
    if (k === 0) band.moveTo(x, y - 2); else band.lineTo(x, y - 2);
  }
  for (let k = 24; k >= 0; k--) {
    const t = k / 24, mt = 1 - t;
    const x = lipL + (lipR - lipL) * t;
    const y = mt * mt * yBotSide + 2 * mt * t * cpy + t * t * yBotSide;
    band.lineTo(x, y + 26);
  }
  band.closePath();
  band.fill({ color: 0x040206, alpha: 0.8 });
  L.addChild(band);
  // 两侧桌底暗窝：侧缘下方的宽扁暗盘——桌"两端也踩在黑暗里"，
  // 与中央暗晕一起把整条桌底线沉进近黑（支座在其后仍从黑里顶出）
  for (const fx of [0.085, 0.915]) {
    const side = new Sprite(getGlowTexture('socket'));
    side.anchor.set(0.5);
    side.scale.set(300 / 128, 130 / 128);
    side.position.set(fx * W, yBotSide + 36);
    side.alpha = 0.86;
    L.addChild(side);
  }
  const under = new Sprite(getGlowTexture('socket'));
  under.anchor.set(0.5);
  // 暗晕核心压在支座下方（帽头从黑暗里顶出来，核心不糊墩肩）
  under.scale.set((W * 0.8) / 128, 116 / 128);
  under.position.set(W / 2, yBot + 44);
  under.alpha = 0.9;
  L.addChild(under);
  const pit = new Sprite(getGlowTexture('pit'));
  const pitTop = yBot - 16;
  pit.position.set(-BLEED, pitTop);
  pit.scale.set((W + BLEED * 2) / 8, (H + BLEED * 2 - pitTop) / 256);
  L.addChild(pit);
}

// 桌前小道具：压在人物下缘前的桌沿上，极克制
// （左前矮烛台已删：烛座藏在对话面板后、火苗却浮在面板上方，读成"无源火苗"）
function tableFrontProps(L) {
  const T = LAYOUT.table;
  // 右前：倾倒在桌沿的高脚杯剪影
  const gob = new Graphics();
  gob.ellipse(0, -20, 11, 9).fill(0x120c0e);
  gob.rect(-2, -13, 4, 11).fill(0x120c0e);
  gob.ellipse(0, 0, 9, 3).fill(0x120c0e);
  gob.position.set(W * 0.925, T.frontSideY + 22);
  gob.rotation = 1.25;
  L.addChild(gob);
  return () => {};
}

function fgFx(L) {
  const puffs = [];
  const embers = [];
  for (let i = 0; i < 7; i++) {
    const p = new Graphics().circle(0, 0, 60 + (i * 37) % 80).fill({ color: 0x181016, alpha: 0.3 });
    p.position.set(((i * 211) % (W + BLEED * 2)) - BLEED, 800 + (i * 53) % 120);
    L.addChild(p);
    puffs.push({ g: p, speed: 0.12 + (i % 3) * 0.05, y0: p.y });
  }
  for (let i = 0; i < 9; i++) {
    const e = new Graphics().circle(0, 0, 2.5).fill({ color: 0xff7733, alpha: 0.85 });
    e.position.set(((i * 173) % (W + BLEED * 2)) - BLEED, 860 + (i * 41) % 100);
    L.addChild(e);
    embers.push({ g: e, speed: 0.5 + (i % 4) * 0.12, phase: i });
  }
  return (t) => {
    for (const p of puffs) {
      p.g.y -= p.speed;
      if (p.g.y < 300) p.g.y = p.y0;
    }
    for (const e of embers) {
      e.g.y -= e.speed;
      e.g.x += Math.sin(t * 0.002 + e.phase) * 0.4;
      if (e.g.y < 280) e.g.y = 980;
    }
  };
}

// 角色小标签（替代桌沿大名牌）：每个角色头部附近的小型 "P# · 名字" 标签，
// labels 层（z150 UI Layer）——跟随 COUNCIL 座位但不烘焙进立绘。
// P1=人类玩家：编号亮一档 + 左侧小菱形 marker + 金色细 underline + 迷你"你"副字。
// 每个座位的 P# 与名字都落在对应 accent 色的暗色铭牌上，保证从复杂背景中读出身份。
function characterLabels(L) {
  const labelList = [];
  SEATS.forEach((s) => {
    const seat = COUNCIL[s.characterId];
    if (!seat) return; // P7 无立绘不显示
    const g = new Container();
    g.position.set(seat.x, seat.top - 26); // 头顶上方（top=COUNCIL 注释的各角色顶点 y）
    // 底影 + 本体两行文字：P# · 名字（accent 上色 P#，名字 parchment）
    const numStyle = { fontFamily: 'serif', fontSize: 13, fill: s.isHuman ? 0xd8b46a : s.accent, letterSpacing: 1 };
    const nameStyle = { fontFamily: 'serif', fontSize: 13, fill: 0xc8b8a8 };
    const num = new Text({ text: s.seatId, style: numStyle });
    const dot = new Text({ text: ' · ', style: nameStyle });
    const nm = new Text({ text: s.name, style: nameStyle });
    // P1 玩家身份副字："你"（极小 secondary indicator，不做主角光环）
    let you = null;
    if (s.isHuman) {
      you = new Text({ text: '你', style: { fontFamily: 'serif', fontSize: 10, fill: 0x9a8a6a } });
    }
    const totalW = num.width + dot.width + nm.width + (you ? you.width + 8 : 0);
    g.eventMode = 'static';
    g.cursor = 'pointer';
    g.hitArea = new Rectangle(-totalW / 2 - 14, -9, totalW + 28, 30);
    g.on('pointertap', () => GAME.cycleTrustMark?.(s.seatId));
    let x = -totalW / 2;
    num.position.set(x, 0); x += num.width;
    dot.position.set(x, 0); x += dot.width;
    nm.position.set(x, 0); x += nm.width;
    if (you) { you.position.set(x + 6, 3); }
    // 选中 ✓（GAME.party 驱动重绘）
    const check = new Text({ text: '✓', style: { fontFamily: 'serif', fontSize: 13, fill: s.accent } });
    check.visible = false;
    check.position.set(totalW / 2 + 3, 0);
    // 角色标签打底：暗底压住背景纹理，侧边色条和细描边沿用座位 accent 区分角色。
    const bgX = -totalW / 2 - 9;
    const bgW = totalW + 18;
    const labelBg = new Graphics();
    labelBg.roundRect(bgX, -6, bgW, 25, 5).fill({ color: 0x0e080d, alpha: 0.88 });
    labelBg.roundRect(bgX, -6, bgW, 25, 5).stroke({ width: 1.1, color: s.accent, alpha: 0.72 });
    labelBg.roundRect(bgX, -6, 4, 25, 2).fill({ color: s.accent, alpha: 0.82 });
    g.addChild(labelBg);
    // P1 菱形 marker + 金色 underline（非 glow 的身份识别）
    if (s.isHuman) {
      const mk = new Graphics();
      mk.poly([-totalW / 2 - 12, 7, -totalW / 2 - 7, 2, -totalW / 2 - 2, 7, -totalW / 2 - 7, 12])
        .fill(0xd8b46a);
      g.addChild(mk);
      const ul = new Graphics();
      ul.rect(-num.width / 2 - 1, 15, num.width + 2, 1.2).fill({ color: 0x9a7a3a, alpha: 0.9 });
      ul.position.set(-(totalW / 2) + num.width / 2, 0);
      g.addChild(ul);
    }
    g.addChild(num, dot, nm, check);
    if (you) g.addChild(you);
    L.addChild(g);
    labelList.push({ g, check, seatId: s.seatId });
  });
  GAME.onParty(() => {
    for (const l of labelList) l.check.visible = GAME.party.includes(l.seatId);
  });
}

function hud(L, charTexs = null, dragLayer = null) {
  // ── 左上标题系统（整组下移 32px，层级 AVALON > 副标题 > 中文标语）──
  const bl = LAYOUT.bannerL;
  const blc = bl.x + bl.w / 2;
  const bannerLeft = new Graphics();
  bannerLeft.rect(bl.x, 24, bl.w, 576).fill({ color: 0x4a1016, alpha: 0.92 });
  bannerLeft.circle(blc, 110, 9).fill(0x8a2028);
  bannerLeft.poly([blc - 8, 290, blc, 278, blc + 8, 290, blc, 302]).fill(0x8a2028);
  bannerLeft.circle(blc, 480, 5).fill(0x6a1820);
  L.addChild(bannerLeft);
  // 标题组文字（AVALON/分隔线/副标题/标语）已按用户要求移除；竖幅条带装饰保留

  // 右上任务面板已按用户要求整体移除（标题/进度点/派遣说明/远征预览/引用一并删除）

  const partyGlow = []; // 已选 token 的烛光受光纱（hud updater 脉动）
  // ── 中央 Party Selection（动态人数驱动，Gameplay UI Restructure）──
  // 槽数 = GAME.mission.required（不硬编码）；只显示已选座位的小 token + 剩余空位凿刻。
  // token = P# 主识别（accent 色）+ 极小头像。整组比旧 5 槽矮 ~40%，让石桌重新可见。
  const HEAD_WIN = {
    prophet: [116, 25], knight: [187, 25], nun: [126, 25], king: [374, 25],
    wanderer: [95, 45], doctor: [90, 25],
  };
  const TOK = 46;              // token 边长（规格 56-68 的紧凑端）
  const TGAP = 64;             // token 间距
  const PY = 494;              // token 行顶（上移至悬停放大卡顶 585 之上：按钮底 582 留 3px 净空）
  let partyUI = null;
  let countText = null;
  const buildParty = () => {
    if (partyUI) L.removeChild(partyUI);
    if (countText) L.removeChild(countText);
    partyUI = new Container();
    const req = GAME.mission.required;
    countText = new Text({ text: `队伍 ${GAME.party.length} / ${req}`, style: { fontFamily: 'serif', fontSize: 15, fill: 0xc8b8a8, letterSpacing: 2 } });
    countText.position.set(W / 2 - countText.width / 2, PY - 26);
    L.addChild(countText);
    for (let k = 0; k < req; k++) {
      const cx = W / 2 + (k - (req - 1) / 2) * TGAP;
      const seatId = GAME.party[k] ?? null;
      const seat = seatId ? SEATS.find((s) => s.seatId === seatId) : null;
      const g = new Graphics();
      g.roundRect(0, 0, TOK, TOK, 7).fill(seat ? 0x241b21 : 0x1a1318);
      g.roundRect(0, 0, TOK, TOK, 7).stroke({ width: 1.5, color: seat ? seat.accent : 0x3a2c34, alpha: 0.95 });
      g.roundRect(2, 2, TOK - 4, 2, 1).fill({ color: seat ? 0x8a6a4a : 0x4a3a34, alpha: 0.6 });
      g.position.set(cx - TOK / 2, PY);
      partyUI.addChild(g);
      if (seat) {
        const tex = charTexs && charTexs[seat.characterId];
        if (tex) {
          const [wx, wy] = HEAD_WIN[seat.characterId] ?? [tex.width / 2 - 120, 25];
          const head = new Sprite(new Texture({ source: tex.source, frame: new Rectangle(wx, wy, 240, 240) }));
          head.anchor.set(0.5);
          head.scale.set(24 / 240);
          head.position.set(TOK / 2 - 8, 18);
          g.addChild(head);
        }
        const pid = new Text({ text: seat.seatId, style: { fontFamily: 'serif', fontSize: 12, fill: seat.isHuman ? 0xd8b46a : seat.accent } });
        pid.position.set(TOK / 2 + 6 - pid.width / 2, 8);
        g.addChild(pid);
        const nm = new Text({ text: seat.name, style: { fontFamily: 'serif', fontSize: 9, fill: 0x9a8a7a } });
        nm.position.set(TOK / 2 + 6 - nm.width / 2, 24);
        g.addChild(nm);
      } else {
        const dy0 = PY + 12;
        const mark = new Graphics();
        mark.poly([cx + 2, dy0 + 5, cx + 7, dy0 + 10, cx + 2, dy0 + 15, cx - 3, dy0 + 10])
          .fill({ color: 0x020103, alpha: 0.85 });
        mark.poly([cx, dy0 + 3, cx + 5, dy0 + 9, cx, dy0 + 15, cx - 5, dy0 + 9]).fill(0x2c2028);
        mark.moveTo(cx - 5, dy0 + 9).lineTo(cx, dy0 + 3).lineTo(cx + 5, dy0 + 9)
          .stroke({ width: 1.2, color: 0x5a4638, alpha: 0.7 });
        partyUI.addChild(mark);
      }
    }
    L.addChild(partyUI);
  };
  buildParty();
  GAME.onParty(buildParty);

  // ── 确认派遣：窄哥特按钮，三态（disabled/enabled+hover/pressed），结算期锁定 ──
  const cf = { w: 168, h: 32, y: PY + TOK + 10 };
  const bx0 = W / 2 - cf.w / 2;
  const by0 = cf.y;
  const btnBox = new Container(); // 位移（按下下沉 2px）与绘制分离
  btnBox.position.set(bx0, by0);
  btnBox.eventMode = 'static';
  const btn = new Graphics();
  btnBox.addChild(btn);
  // hover 亮边：金描边，alpha 由 updater 缓动（仅激活态显示）
  const edge = new Graphics();
  edge.roundRect(1, 1, cf.w - 2, cf.h - 2, 6).stroke({ width: 1.5, color: 0xd8b46a, alpha: 0.9 });
  edge.alpha = 0;
  btnBox.addChild(edge);
  const btnText = new Text({ text: '确认派遣', style: { fontFamily: 'serif', fontSize: 15, fill: 0xc8a888, letterSpacing: 5 } });
  const btnShadow = new Text({ text: '确认派遣', style: { fontFamily: 'serif', fontSize: 15, fill: 0x050304, letterSpacing: 5 } });
  // 錾刻铭文双居中（按钮内水平/垂直居中，底影右下偏移 1.5px）
  btnShadow.position.set(cf.w / 2 - btnShadow.width / 2 + 1.5, (cf.h - btnShadow.height) / 2 + 1.5);
  btnText.position.set(cf.w / 2 - btnText.width / 2, (cf.h - btnText.height) / 2);
  btnBox.addChild(btnShadow, btnText);
  // 按钮挂 drag 层（z180 > 卡牌 z170）：悬停抬起的中央卡命中区盖住按钮区，
  // 按钮 passive 时 hitTest 会穿透到身后的卡导致 tap 误触选中——static+置顶根治
  (dragLayer ?? L).addChild(btnBox);
  const drawBtn = (ok) => {
    btn.clear();
    btn.roundRect(0, 0, cf.w, cf.h, 6).fill(ok ? 0x2a1a1e : 0x191217);
    btn.roundRect(0, 0, cf.w, cf.h, 6).stroke({ width: 1.5, color: ok ? 0x8a4a3a : 0x2c2228 });
    btn.roundRect(2, 2, cf.w - 4, 2, 1).fill({ color: ok ? 0xa87848 : 0x3a3038, alpha: 0.7 });
    btn.roundRect(4, 5, cf.w - 8, cf.h - 10, 3).stroke({ width: 1, color: ok ? 0x6a3a2e : 0x241a20, alpha: 0.8 });
    btnText.style.fill = ok ? 0xd8b090 : 0x5a4a4a;
    btnText.alpha = ok ? 1 : 0.7;
    btnShadow.alpha = ok ? 0.9 : 0.55;
  };
  let lastOk = null;
  const refreshBtn = () => {
    const ok = GAME.confirmReady();
    if (ok === lastOk) return;
    lastOk = ok;
    drawBtn(ok);
    btnBox.cursor = ok ? 'pointer' : 'default';
  };
  refreshBtn();
  GAME.onParty(refreshBtn);
  const bSt = { hov: 0, hovV: 0, press: 0, pressV: 0 };
  btnBox.on('pointerover', () => { bSt.hov = 1; });
  btnBox.on('pointerout', () => { bSt.hov = 0; });
  btnBox.on('pointerdown', () => { if (!GAME.hoverOnly && GAME.confirmReady()) bSt.press = 1; });
  const releasePress = () => { if (!GAME.hoverOnly) bSt.press = 0; };
  btnBox.on('pointerup', releasePress);
  btnBox.on('pointerupoutside', releasePress);
  // 确认派遣：满员且未在结算 → 进入结算动画（占位：50/50 成功/失败）
  btnBox.on('pointertap', () => {
    if (GAME.hoverOnly) return;
    if (GAME.confirmReady()) GAME.beginResolve(Math.random() < 0.5 ? 'success' : 'fail');
  });

  // ── 结算反馈层：token 行闪光 + 结果大字（resolve 期间由 updater 驱动）──
  const resolveFlash = new Graphics();
  resolveFlash.roundRect(W / 2 - 178, PY - 6, 356, TOK + 12, 8);
  resolveFlash.visible = false;
  L.addChild(resolveFlash);
  const resolveText = new Text({ text: '', style: { fontFamily: 'serif', fontSize: 24, fill: 0xd8c8b8, letterSpacing: 6 } });
  resolveText.visible = false;
  L.addChild(resolveText);

  // ── 底部状态 rail：AP 轨与卡牌可用性联动（GAME 单例：出牌扣减即时重绘）──
  const ay = LAYOUT.apLine.y;
  const AP_X = 660;
  const AP_STEP = 24;
  const AP_COLOR_ON = 0xffb85c;
  const AP_COLOR_OFF = 0x604249;
  let rail = null;
  let apText = null;
  let apTextShadow = null;
  const apLights = [];
  const drawAp = () => {
    if (rail) L.removeChild(rail);
    if (apTextShadow) L.removeChild(apTextShadow);
    if (apText) L.removeChild(apText);
    rail = new Container();
    rail.sortableChildren = true;
    apLights.length = 0;
    for (let i = 0; i < GAME.max; i++) {
      const active = i < GAME.ap;
      const x = AP_X + i * AP_STEP;
      // 每个 AP 都是一盏小烛灯：柔光层 + 金色环 + 明亮灯芯，随后由 hud updater 呼吸。
      const glow = new Sprite(getGlowTexture('ember'));
      glow.anchor.set(0.5);
      glow.position.set(x, ay);
      glow.tint = active ? 0xffb65a : 0x4a3034;
      glow.blendMode = 'add';
      glow.alpha = active ? 0.32 : 0.02;
      glow.scale.set((active ? 28 : 18) / 128);
      glow.zIndex = 0;
      const ring = new Graphics();
      ring.circle(x, ay, 8.5).stroke({ width: 1.4, color: active ? 0xf0b45b : AP_COLOR_OFF, alpha: active ? 0.85 : 0.35 });
      ring.zIndex = 1;
      const core = new Graphics();
      core.circle(x, ay, 5.2).fill(active ? AP_COLOR_ON : AP_COLOR_OFF);
      core.zIndex = 2;
      rail.addChild(glow, ring, core);
      apLights.push({ active, glow, ring, core, phase: i * 0.92 });
    }
    L.addChild(rail);
    const apLabel = `行动点 ${GAME.ap}/${GAME.max}`;
    apTextShadow = new Text({ text: apLabel, style: { ...UI_STYLE, fill: 0x160a0c, letterSpacing: 1 } });
    apText = new Text({ text: apLabel, style: { ...UI_STYLE, fill: 0xf0d7a2, letterSpacing: 1 } });
    apTextShadow.position.set(769, ay - apTextShadow.height / 2 + 2);
    apText.position.set(767, ay - apText.height / 2);
    L.addChild(apTextShadow, apText);
  };
  drawAp();
  GAME.onApi(drawAp);

  // ── 右下 P1 私密记录：只读公开状态 + P1 自己的身份，手动标记只存前端 ──
  const note = LAYOUT.note;
  const intelBaseW = note.w;
  let intelW = intelBaseW;
  let intelCompact = false;
  const intelCollapsedH = 78;
  const intelExpandedH = 310;
  const noteC = new Container();
  const cardRight = LAYOUT.cards.centerX
    + ((CARDS.length - 1) / 2) * LAYOUT.cards.spacing
    + LAYOUT.cards.w / 2
    + 12;
  const updateIntelViewport = () => {
    // The world uses a cover fit, so a short/narrow viewport crops the design
    // edges. Keep this lower-right panel inside the visible edge and leave a
    // small gap after the card fan instead of allowing the parchment to be
    // clipped or to cover a card.
    const viewportW = window.innerWidth || W;
    const viewportH = window.innerHeight || H;
    const worldScale = Math.max(viewportW / W, viewportH / H);
    const worldLeft = (viewportW - W * worldScale) / 2;
    const visibleRight = (viewportW - worldLeft) / worldScale - 10;
    const minX = cardRight + 8;
    const available = visibleRight - minX;
    intelCompact = available < intelBaseW;
    intelW = intelCompact ? Math.min(intelBaseW, Math.max(120, available)) : intelBaseW;
    noteC.position.set(intelCompact ? Math.max(minX, visibleRight - intelW) : note.x, note.y);
    noteC.rotation = intelCompact ? 0 : 0.015;
  };
  updateIntelViewport();
  let intelBody = null;
  let intelExpanded = false;
  let intelPulseRows = [];
  const intelToggle = new Graphics();
  intelToggle.eventMode = 'static';
  intelToggle.cursor = 'pointer';
  intelToggle.on('pointertap', () => {
    intelExpanded = !intelExpanded;
    renderIntelPanel();
  });
  const markNames = { trusted: '可信', watch: '观察', suspicious: '可疑' };
  const markColors = { trusted: 0x9da98c, watch: 0xb29a6a, suspicious: 0xa0645c };
  const intelGroups = [
    { type: 'confirmed', title: '已确认', color: 0xc6ae82, empty: '暂无已确认记录' },
    { type: 'clue', title: '线索', color: 0x9aa8b4, empty: '暂无新线索' },
    { type: 'suspicion', title: '怀疑', color: 0xa0645c, empty: '暂无手动怀疑标记' },
  ];
  const seatLabel = (seatId) => {
    const seat = SEATS.find((entry) => entry.seatId === seatId);
    return `${seatId} · ${seat?.name || seatId}`;
  };
  const renderIntelPanel = () => {
    if (intelBody) {
      noteC.removeChild(intelBody);
      intelBody.destroy({ children: true });
    }
    intelPulseRows = [];
    const info = GAME.privateIntel || {};
    const entries = Array.isArray(info.entries) ? info.entries : [];
    const marks = info.manualTrustMarks || {};
    const panelH = intelExpanded ? intelExpandedH : intelCollapsedH;
    intelBody = new Container();

    const shadow = new Graphics();
    shadow.roundRect(10, 11, intelW - 2, panelH - 3, 8).fill({ color: 0x050305, alpha: 0.58 });
    const paper = new Graphics();
    paper.roundRect(0, 0, intelW, panelH, 8).fill({ color: 0x24151b, alpha: 0.97 });
    paper.roundRect(0, 0, intelW, panelH, 8).stroke({ width: 1.5, color: 0x6c493d, alpha: 0.9 });
    paper.roundRect(7, 7, intelW - 14, panelH - 14, 5).stroke({ width: 1, color: 0x3d292a, alpha: 0.8 });
    intelBody.addChild(shadow, paper);

    const title = new Text({ text: `${info.ownerSeatId || 'P1'} · 私密记录`, style: { fontFamily: 'serif', fontSize: intelCompact ? 15 : 18, fill: 0xd8b46a, letterSpacing: intelCompact ? 0.5 : 1 } });
    title.position.set(16, 12);
    const subtitle = new Text({ text: '仅你可见', style: { fontFamily: 'serif', fontSize: intelCompact ? 9 : 10, fill: 0x9f8e88, letterSpacing: intelCompact ? 0.5 : 1 } });
    subtitle.position.set(17, 35);
    const arrow = new Text({ text: intelExpanded ? '⌃' : '⌄', style: { fontFamily: 'serif', fontSize: intelCompact ? 16 : 18, fill: 0xc49a62 } });
    arrow.position.set(intelW - (intelCompact ? 24 : 31), 15);
    const newCount = entries.filter((entry) => entry.isNew).length;
    const collapsedCount = newCount
      ? (intelCompact ? `● ${newCount}` : `● ${newCount} 条新线索`)
      : (intelCompact ? `${entries.length} 条` : `${entries.length} 条记录`);
    const count = new Text({ text: collapsedCount, style: { fontFamily: 'serif', fontSize: intelCompact ? 9 : 11, fill: newCount ? 0xc49a62 : 0x938486 } });
    count.position.set(intelW - count.width - (intelCompact ? 25 : 34), 38);
    intelBody.addChild(title, subtitle, arrow, count);

    const rule = new Graphics();
    rule.moveTo(16, 53).lineTo(intelW - 16, 53).stroke({ width: 1, color: 0x5c3d38, alpha: 0.75 });
    intelBody.addChild(rule);

    if (intelExpanded) {
      let y = 63;
      for (const group of intelGroups) {
        const heading = new Text({ text: group.title, style: { fontFamily: 'serif', fontSize: intelCompact ? 11 : 12, fill: group.color, letterSpacing: intelCompact ? 1 : 2 } });
        heading.position.set(16, y);
        intelBody.addChild(heading);
        y += 18;
        let rows = entries.filter((entry) => entry.type === group.type).slice(0, 2);
        if (group.type === 'suspicion') {
          const manualRows = Object.entries(marks).filter(([, mark]) => markNames[mark]).map(([seatId, mark]) => ({
            id: `mark:${seatId}`,
            text: `${seatLabel(seatId)} · ${markNames[mark]}`,
            mark,
            type: 'suspicion',
          }));
          rows = manualRows.slice(0, 2);
        }
        if (!rows.length) rows = [{ id: `empty:${group.type}`, text: group.empty, empty: true, type: group.type }];
        for (const entry of rows) {
          const textColor = entry.empty ? 0x786b70 : entry.mark ? markColors[entry.mark] : group.color;
          const row = new Text({
            text: `• ${entry.text}`,
            style: { fontFamily: 'serif', fontSize: intelCompact ? 9.5 : 11, fill: textColor, wordWrap: true, wordWrapWidth: intelW - (intelCompact ? 30 : 38), breakWords: true, lineHeight: intelCompact ? 13 : 15 },
          });
          const rowH = Math.max(21, row.height + 5);
          if (entry.isNew) {
            const highlight = new Graphics();
            highlight.roundRect(11, y - 2, intelW - 22, rowH, 4).fill({ color: group.type === 'confirmed' ? 0x7d6843 : group.type === 'clue' ? 0x4c6574 : 0x713b38, alpha: 0.16 });
            intelBody.addChild(highlight);
            intelPulseRows.push({ highlight, until: performance.now() + 420 });
          }
          row.position.set(18, y);
          intelBody.addChild(row);
          y += rowH + 2;
        }
        y += 6;
      }
    }
    noteC.addChild(intelBody, intelToggle);
    intelToggle.hitArea = new Rectangle(0, 0, intelW, 58);
  };
  GAME.onIntel(renderIntelPanel);
  renderIntelPanel();
  window.addEventListener('resize', () => {
    const previousW = intelW;
    const previousCompact = intelCompact;
    updateIntelViewport();
    if (previousW !== intelW || previousCompact !== intelCompact) renderIntelPanel();
  });
  L.addChild(noteC);

  // ── 最右窄幅邪教横幅 ──
  const banner = LAYOUT.banner;
  const bx = banner.x + banner.w / 2;
  const bannerG = new Graphics();
  bannerG.rect(banner.x, 24, banner.w, 876).fill({ color: 0x4a1016, alpha: 0.92 });
  bannerG.circle(bx, 110, 9).fill(0x8a2028);
  bannerG.poly([bx - 8, 290, bx, 278, bx + 8, 290, bx, 302]).fill(0x8a2028);
  bannerG.poly([bx - 8, 510, bx, 498, bx + 8, 510, bx, 522]).fill(0x6a1820);
  bannerG.circle(bx, 700, 5).fill(0x6a1820);
  L.addChild(bannerG);

  // 派遣 token/按钮的烛光受光低频脉动（buildParty 每次重建会把纱推入 partyGlow）+
  // 确认按钮三态缓动 + 结算反馈动画（resolve 期间闪光与结果大字，结束落账进新回合）
  return (t) => {
    // AP 灯带持续呼吸，出牌扣点后 drawAp 会重建 active 状态。
    for (const light of apLights) {
      const wave = 0.5 + 0.5 * Math.sin(t * 0.0032 + light.phase);
      if (light.active) {
        light.glow.alpha = 0.24 + 0.20 * wave;
        light.glow.scale.set((25 + 8 * wave) / 128);
        light.ring.alpha = 0.68 + 0.25 * wave;
        light.core.alpha = 0.88 + 0.12 * wave;
      } else {
        light.glow.alpha = 0.015;
        light.ring.alpha = 0.26;
        light.core.alpha = 0.5;
      }
    }
    if (apText) apText.alpha = 0.94 + 0.06 * (0.5 + 0.5 * Math.sin(t * 0.0024));
    const intelNow = performance.now();
    for (const pulse of intelPulseRows) {
      const remaining = pulse.until - intelNow;
      pulse.highlight.alpha = remaining > 0 ? 0.16 * Math.min(1, remaining / 420) : 0;
    }
    for (const p of partyGlow) p.s.alpha = 0.10 + 0.05 * (1 + Math.sin(t * 0.0021 + p.phase));
    // 按钮三态缓动：hover 亮边 alpha / 按下下沉 2px
    bSt.hovV += (bSt.hov - bSt.hovV) * 0.2;
    bSt.pressV += (bSt.press - bSt.pressV) * 0.4;
    btnBox.y = by0 + bSt.pressV * 2;
    edge.alpha = (GAME.confirmReady() ? 0.85 : 0) * Math.max(bSt.hovV, bSt.pressV) * (1 - bSt.pressV);
    // 结算反馈：token 行闪光 + 结果大字（成功蓝灰 / 失败血红），900ms 后落账进新回合
    if (GAME.resolving) {
      const k = Math.min(1, (t - GAME.resolveStart) / 900);
      const ok = GAME.resolveOutcome === 'success';
      resolveFlash.visible = true;
      resolveFlash.tint = ok ? 0x9ab0c0 : 0xc04840;
      resolveFlash.alpha = 0.30 * Math.sin(Math.PI * k);
      resolveText.visible = true;
      resolveText.text = ok ? '任务成功' : '任务失败';
      resolveText.style.fill = ok ? 0x9ab0c0 : 0xc04840;
      resolveText.alpha = 0.55 + 0.45 * Math.sin(Math.PI * k);
      resolveText.position.set(W / 2 - resolveText.width / 2, PY - 10);
      if (k >= 1) GAME.finishResolve();
    } else if (resolveText.visible) {
      resolveFlash.visible = false;
      resolveText.visible = false;
    }
  };
}

// 卡牌：底部中心枢轴扇形，rot/scale/raise/z 逐卡来自 config。
// 交互全家桶：悬停(1) + 点选金边/徽记(2) + 拖拽跟手(3) + 拖放出牌飞向动作栈(3)
// + 不可用态压暗(4)——事件只写目标态，全部缓动在 updater 内 lerp（项目惯例）
function cards(L, dragLayer, cardTexs) {
  const list = [];
  const cl = LAYOUT.cards;
  const mid = (CARDS.length - 1) / 2;
  const STACK = { x: W / 2, y: LAYOUT.party.y + 32 }; // 出牌目的地：动作栈中心
  L.sortableChildren = true;
  const ART_KEY = { 侦察: 'scout', 劝说: 'persuade', 质疑: 'question', 挑拨: 'provoke', 沉默: 'silence' };
  CARDS.forEach((c, i) => {
    const cw = cl.w;   // 五卡统一尺寸（放大/选中只由动效表达）
    const chh = cl.h;
    const cx = cl.centerX + (i - mid) * cl.spacing;
    const by = cl.bottomY - c.raise; // 卡底枢轴；raise 为整体抬高量
    const card = new Container();
    const frame = new Graphics();
    // 以底部中心为局部原点（旋转/缩放枢轴）
    frame.roundRect(-cw / 2, -chh, cw, chh, 14).fill(0x241014);
    frame.roundRect(-cw / 2, -chh, cw, chh, 14).stroke({ width: 2, color: 0x6a3a2e });
    frame.roundRect(-cw / 2 + 12, -chh + 12, cw - 24, chh - 24, 10).fill(0x0d0709);
    // 成本红点 placeholder：内框顶部中央、插画上沿之上的空带（"卡图上方"）
    frame.circle(0, -chh + 32, 15).fill(0x7c2a20);
    card.addChild(frame);
    // 卡面真美术：内框区域整贴 DD 手绘插画（cover 裁切），中心=内框中心(0,-chh/2+12)，
    // 并用内框圆角矩形作 mask——直角插画不溢出圆角、不压外框。
    // v8.21 mask 注意：不可设 renderable=false（会取空失败），保持默认即可正确裁切
    const artTex = cardTexs && cardTexs[ART_KEY[c.name]];
    let art = null;
    if (artTex) {
      art = new Sprite(artTex);
      art.anchor.set(0.5, 0.5);
      const iw = cw - 24;
      const ih = chh - 24;
      art.scale.set(Math.max(iw / artTex.width, ih / artTex.height)); // cover
      art.position.set(0, -chh / 2 + 12);
      const clip = new Graphics();
      clip.roundRect(-cw / 2 + 12, -chh + 12, cw - 24, chh - 24, 10).fill(0xffffff);
      card.addChild(art, clip);
      art.mask = clip;
    }
    // —— 卡面"生命感"三层动效（全程序化，无额外素材）——
    // ①暖辉呼吸：加法暖光斑在插画中带缓慢呼吸（烛光余温的"活物感"）
    // ②插画微缩放：Ken Burns 式 ±0.6% 极缓呼吸（让静态画面"活着"）
    // ③暗角雾漂：一层低透明暗雾在卡面内缓慢横移（增加深度，被 mask 裁在内框内）
    const haloBase = 1 + 0.02 * (i % 3); // 每卡微差呼吸幅度防机械同步
    const artScale0 = artTex ? Math.max((cw - 24) / artTex.width, (chh - 24) / artTex.height) : 1;
    // 暖辉呼吸层：椭圆暖光斑（中心偏卡面中带，避开顶部角标与底部文字带）
    const artGlow = new Sprite(getGlowTexture('ember'));
    artGlow.anchor.set(0.5);
    artGlow.blendMode = 'add';
    artGlow.tint = 0xd98a3a;
    artGlow.alpha = 0.06;
    artGlow.scale.set((cw * 0.72) / 128, (chh * 0.42) / 128);
    artGlow.position.set(0, -chh * 0.38);
    artGlow.zIndex = 0;
    card.addChild(artGlow);
    const name = new Text({ text: c.name, style: { fontFamily: 'serif', fontSize: 22, fill: 0xd8c8b8 } });
    name.position.set(-name.width / 2, -46);
    // 成本角标：骑跨卡顶边缘（半悬卡外）——不遮挡插画，卡牌游戏经典布局。
    // 金环暗底 + 米白数字，与选中金边同语义
    const costBadge = new Container();
    const badgeBg = new Graphics();
    badgeBg.circle(0, 0, 13).fill(0x1c1116);
    badgeBg.circle(0, 0, 13).stroke({ width: 2, color: 0xb08a3a, alpha: 0.95 });
    badgeBg.circle(-1, -1, 8.5).fill({ color: 0x3a2a26, alpha: 0.7 });
    costBadge.addChild(badgeBg);
    const cost = new Text({ text: String(c.cost), style: { fontFamily: 'serif', fontSize: 17, fill: 0xe8d8c8 } });
    cost.position.set(-cost.width / 2, -cost.height / 2);
    costBadge.addChild(cost);
    costBadge.position.set(0, -chh + 32);
    card.addChild(name, costBadge);
    // 选中金边（同路径描边常驻，alpha 控制）：金=确认语义，与暗红框区分
    const gold = new Graphics();
    gold.roundRect(-cw / 2, -chh, cw, chh, 14).stroke({ width: 3, color: 0xb08a3a });
    gold.alpha = 0;
    gold.zIndex = 2;
    card.addChild(gold);
    // 卡背徽记（圆环+竖眼+三尖冠）：选中后浮现，updater 慢速脉动
    const sigil = new Container();
    const ring = new Graphics();
    ring.circle(0, 0, 26).stroke({ width: 2.5, color: 0xb08a3a, alpha: 0.95 });
    ring.ellipse(0, 0, 7, 15).stroke({ width: 2, color: 0xb08a3a, alpha: 0.9 });
    ring.poly([-16, -8, -10, -26, -4, -9]).fill(0xb08a3a);
    ring.poly([-1, -10, 5, -28, 10, -9]).fill(0xb08a3a);
    ring.poly([8, -8, 16, -24, 18, -5]).fill(0xb08a3a);
    sigil.addChild(ring);
    sigil.position.set(0, -chh / 2);
    sigil.alpha = 0;
    sigil.zIndex = 1;
    card.addChild(sigil);
    // 不可用态暗遮罩：整卡压暗（含金边/徽记），并吃掉指针事件
    const dim = new Graphics();
    dim.rect(-cw / 2 - 2, -chh - 2, cw + 4, chh + 4).fill({ color: 0x060309, alpha: 0.62 });
    dim.alpha = 0;
    dim.zIndex = 3;
    dim.eventMode = 'static';
    card.addChild(dim);
    // 悬停红光圈（用户定稿：紧贴卡牌长方形边缘）——沿卡牌自身轮廓的霓虹发光：
    // 核心亮线紧贴边框 + 宽柔光层向外小半径羽化（霓虹管+外发光），加法混合。
    // 外围悬浮椭圆环两轮目验均被否——发光必须包住卡牌边缘本身
    const haloRing = new Graphics();
    haloRing.roundRect(-cw / 2, -chh, cw, chh, 14)
      .stroke({ width: 12, color: 0xd9453a, alpha: 0.32 }); // 外发光羽化层
    haloRing.roundRect(-cw / 2, -chh, cw, chh, 14)
      .stroke({ width: 3, color: 0xff6a55, alpha: 0.95 });  // 核心亮线
    haloRing.blendMode = 'add';
    haloRing.alpha = 0;
    haloRing.zIndex = 1;
    const haloGlow = new Sprite(getGlowTexture('ember'));
    haloGlow.anchor.set(0.5);
    haloGlow.blendMode = 'add';
    haloGlow.tint = 0xd9453a;
    haloGlow.position.set(0, -chh / 2);
    haloGlow.alpha = 0;
    haloGlow.zIndex = -2;
    card.addChild(haloRing, haloGlow);
    card.position.set(cx, by);
    card.scale.set(c.scale);
    card.rotation = (c.rot * Math.PI) / 180;
    card.zIndex = c.z; // 中央卡最高层级
    // 状态机：hover 悬停 / sel 点选 / drag 拖拽 / fly 出牌飞行 / dead 已出牌 / playOK 可用性
    // playOK 初始 null：强制首刷必写 eventMode/cursor（初始化为 true 会跳过设置，
    // 卡永远不进交互模式——CDP 状态机读数全程静止暴露过的坑）
    const st = { hover: 0, v: 0, sel: false, selV: 0, drag: null, fly: null, return: false, dead: false, playOK: null, dimV: 0 };
    const usable = () => c.cost <= GAME.ap;
    const refresh = () => {
      const browserAllowed = !GAME.hoverOnly || GAME.cardActionEnabled?.(c.name) !== false;
      const ok = (GAME.hoverOnly ? browserAllowed : usable()) && !st.fly;
      if (ok !== st.playOK) {
        st.playOK = ok;
        card.cursor = ok ? 'pointer' : 'default';
        card.eventMode = ok ? 'static' : 'none';
      }
    };
    GAME.onApi(refresh);
    refresh();
    card.on('pointerover', () => { st.hover = 1; card.zIndex = 10; GAME.cardHover?.(cx, true); });
    card.on('pointerout', () => { st.hover = 0; card.zIndex = st.sel ? 10 : c.z; GAME.cardHover?.(cx, false); });
    card.on('pointertap', () => {
      if (GAME.hoverOnly && st.playOK) GAME.actionCard?.(c.name);
    });
    card.on('pointerdown', (e) => {
      if (GAME.hoverOnly || !st.playOK) return;
      st.drag = { sx: e.global.x, sy: e.global.y, moved: false, vx: 0, lx: e.global.x, ly: e.global.y };
    });
    card.on('globalpointermove', (e) => {
      if (!st.drag) return;
      if (!st.drag.moved && Math.hypot(e.global.x - st.drag.sx, e.global.y - st.drag.sy) > 8) {
        st.drag.moved = true;
        // 拖起 reparent 到 drag 层：先取原全局坐标 → addChild 换父 → 用 toLocal 落位
        // （e.global/getGlobalPosition 是舞台坐标，视口非 1:1 时必须 toLocal）
        const gp = card.getGlobalPosition();
        L.removeChild(card);
        dragLayer.addChild(card);
        const p = dragLayer.toLocal(gp);
        card.position.set(p.x, p.y);
        st.sel = false; // 拖拽优先于选中态
        card.zIndex = 10;
      }
      if (st.drag.moved) {
        st.drag.vx = e.global.x - st.drag.lx;
        st.drag.lx = e.global.x;
        st.drag.ly = e.global.y;
        const loc = dragLayer.toLocal(e.global);
        card.x = loc.x;
        card.y = loc.y - chh / 2; // 抓卡身中点
      }
    });
    const release = (e) => {
      if (GAME.hoverOnly) {
        st.drag = null;
        return;
      }
      if (!st.drag) return;
      const wasDrag = st.drag.moved;
      const px = e ? e.global.x : st.drag.lx;
      const py = e ? e.global.y : st.drag.ly;
      st.drag = null;
      if (wasDrag) {
        // 出牌：拖到桌面高度（y<640）且付得起 → 贝塞尔飞向动作栈；否则归位
        if (py < 640 && usable()) {
          st.fly = { t: 0, x0: card.x, y0: card.y, cx: card.x + (Math.random() - 0.5) * 260, cy: 380, dir: Math.sign(STACK.x - card.x) || 1 };
        } else {
          st.return = true;
        }
      } else {
        // tap：点选/取消（金边+徽记+微抬+慢漂）
        st.sel = !st.sel;
        card.zIndex = st.sel ? 10 : c.z;
      }
    };
    card.on('pointerup', release);
    card.on('pointerupoutside', release);
    // window 级 pointerup 兜底：Pixi 的 pointerup 冒泡在无头输入管线偶发不达
    window.addEventListener('pointerup', (ev) => {
      release({ global: { x: ev.clientX, y: ev.clientY } });
    }, { capture: true });
    L.addChild(card);
    list.push({
      card, gold, sigil, dim, haloRing, haloGlow, artGlow, art, artScale0, c, cw, chh,
      baseX: cx, baseY: by, baseScale: c.scale, baseZ: c.z, refresh,
      rotRad: (c.rot * Math.PI) / 180, phase: i * 0.9, st,
    });
  });
  // 回合重置（GAME.finishResolve → onRound）：已出牌复活回手牌、全部状态复位。
  // 中途飞行的卡直接中止飞行（其 AP 消耗由回合结算吞并，不重复扣）
  GAME.onRound(() => {
    for (const en of list) {
      const s = en.st;
      if (s.drag) { s.drag = null; L.addChild(en.card); } // 拖拽中从 drag 层归队
      s.dead = false; s.fly = null; s.return = false; s.sel = false;
      s.hover = 0; s.v = 0; s.selV = 0; s.dimV = 0; s.playOK = null;
      en.card.visible = true; en.card.alpha = 1;
      en.card.position.set(en.baseX, en.baseY);
      en.card.scale.set(en.baseScale); en.card.rotation = en.rotRad;
      en.card.zIndex = en.baseZ;
      en.refresh();
    }
  });
  // 鼠标离开窗口时兜底复位（pointerout 偶发不触发时防"卡死在选中态"）；
  // 拖拽中途离窗 → 取消拖拽并触发弹簧归位（updater 的 return 分支负责 reparent）
  document.addEventListener('pointerleave', () => {
    for (const e of list) {
      e.st.hover = 0;
      if (e.st.drag) { e.st.drag = null; e.st.return = true; }
      e.card.zIndex = e.st.sel ? 10 : e.baseZ;
    }
  });
  // 调试钩子（CDP 测试用）：每卡状态机真值 + AP
  window.__CARDS_DEBUG = () => ({
    ap: GAME.ap,
    cards: list.map((e) => ({
      name: e.c.name, sel: e.st.sel, hover: e.st.hover, playOK: e.st.playOK,
      pressed: !!e.st.drag, drag: !!(e.st.drag && e.st.drag.moved),
      fly: !!e.st.fly, dead: e.st.dead, return: e.st.return,
      dimV: +e.st.dimV.toFixed(2), selV: +e.st.selV.toFixed(2),
      x: Math.round(e.card.x), y: Math.round(e.card.y),
    })),
  });
  return (t) => {
    for (const e of list) {
      const { card, baseX, baseY, baseScale, rotRad, phase, st, cw, chh, gold, sigil, dim, haloRing, haloGlow, artGlow, art, artScale0, c } = e;
      if (st.dead) continue; // 已出牌：彻底退场，不再被手牌弹簧拉回
      // 出牌飞行：二次贝塞尔（起点→抬升控制点→动作栈中心），到达即扣 AP 并隐藏
      if (st.fly) {
        st.fly.t += 0.022;
        const k = st.fly.t;
        if (k >= 1) {
          GAME.spend(c.cost);
          card.visible = false;
          st.fly = null;
          st.dead = true;
          continue;
        }
        const u = 1 - k;
        card.x = u * u * st.fly.x0 + 2 * u * k * st.fly.cx + k * k * STACK.x;
        card.y = u * u * st.fly.y0 + 2 * u * k * st.fly.cy + k * k * STACK.y;
        card.rotation = rotRad + st.fly.dir * k * 1.1;
        card.scale.set(baseScale * (1 - 0.45 * k));
        card.alpha = 1 - 0.55 * k * k;
        gold.alpha = 0; sigil.alpha = 0; haloRing.alpha = 0; haloGlow.alpha = 0;
        continue;
      }
      // 拖拽中：跟手已由事件直写坐标；此处只补速度倾角 + 轻微放大
      if (st.drag && st.drag.moved) {
        const tilt = Math.max(-0.22, Math.min(0.22, st.drag.vx * 0.012));
        card.rotation += (tilt - card.rotation) * 0.25;
        card.scale.set(baseScale * 1.08);
        gold.alpha = 0; sigil.alpha = 0; haloRing.alpha = 0; haloGlow.alpha = 0;
        continue;
      }
      // 拖放取消 → 弹簧归位：先 reparent 回卡牌层再回弹（toLocal 同理）
      if (st.return) {
        st.return = false;
        const p = L.toLocal(card.getGlobalPosition());
        dragLayer.removeChild(card);
        L.addChild(card);
        card.position.set(p.x, p.y);
        card.alpha = 1;
      }
      // 悬停/选中缓动
      st.v += (st.hover - st.v) * 0.2;
      st.selV += ((st.sel ? 1 : 0) - st.selV) * 0.16;
      const h = st.v;
      const s = st.selV;
      // 悬停=拿起（抬 46+放大 12%+角回正 60%）；选中=待命（微抬 14+角回正 30%+
      // 2.2s 慢漂浮）——两种状态可叠；空闲漂浮随悬停淡出
      const idle = Math.sin(t * 0.0013 + phase) * 3 * (1 - h);
      const selFloat = Math.sin(t * 0.0028 + phase) * 4 * s * (1 - h);
      card.x += (baseX - card.x) * 0.3;
      card.y = baseY - 46 * h - 14 * s + idle + selFloat;
      card.scale.set(baseScale * (1 + 0.12 * h + 0.03 * s));
      card.rotation += (rotRad * (1 - 0.6 * h - 0.3 * s) - card.rotation) * 0.3;
      // 金边：选中全亮，悬停给 35% 预示可点；徽记：选中浮现 + 慢脉动
      gold.alpha = Math.min(1, s + 0.35 * h * (1 - s));
      sigil.alpha = s * (0.75 + 0.25 * Math.sin(t * 0.0022 + phase));
      // 悬停红光圈：环线亮度呼吸（0.28~0.98）+ 双轴反相摆动 ±3%（"动态"来源），
      // 背晕反相呼吸垫底——光圈只在 hover 淡入，选中/拖拽/出牌时熄灭。
      // 环线本身已画在卡缘外 80px，scale 只做摆动（基準 1）
      const hp = 0.63 + 0.35 * Math.sin(t * 0.0045 + phase);
      haloRing.alpha = h * hp;
      haloRing.scale.set(
        1 + 0.03 * Math.sin(t * 0.0045 + phase),
        1 + 0.03 * Math.sin(t * 0.0045 + phase + Math.PI / 2),
      );
      haloGlow.alpha = h * (0.11 + 0.06 * Math.sin(t * 0.0045 + phase + 1.5));
      haloGlow.scale.set((cw / 2 + 55) / 64, (chh / 2 + 55) / 64);
      // 不可用压暗（cost>AP）：目标 0/1 缓动，同时清悬停/选中
      const dimT = st.playOK ? 0 : 1;
      st.dimV += (dimT - st.dimV) * 0.12;
      dim.alpha = st.dimV;
      if (!st.playOK) { st.hover = 0; st.sel = false; }
      // —— 卡面"生命感"：插画 Ken Burns 微缩放 + 暖辉呼吸（让静态画面"活着"）——
      const br = 1 + 0.006 * Math.sin(t * 0.0009 + phase);
      art.scale.set(artScale0 * br);
      artGlow.alpha = 0.05 + 0.035 * (1 + Math.sin(t * 0.0018 + phase * 1.3));
    }
  };
}

export function buildPlaceholders(layerMap, env = {}, parallax = null) {
  const updaters = [];
  const debugTexts = [];

  sky(layerMap.get('sky'), env.skyTex);
  updaters.push(skyDetails(layerMap.get('skyDetail')));
  updaters.push(clouds(layerMap.get('cloudsFar'), 0x3a1218, 0.5, 35, 5, 0.00008, 90, env.cloudFarTexs || [], CLOUD_GLOWS.far));
  updaters.push(clouds(layerMap.get('cloudsMid'), 0x48161c, 0.45, 120, 4, 0.00012, 130, env.cloudMidTexs || [], CLOUD_GLOWS.mid));
  // eye 层由 main.js 的 EldritchEye 组件构建（见 src/EldritchEye.js）
  updaters.push(tentacles(layerMap.get('tentacles'), env.tentacleTexs || []));
  castle(layerMap.get('castle'), env.castleTex);
  updaters.push(midground(layerMap.get('midground'), env.cityTex, env.bridgeTex));
  fgEnv(layerMap.get('fgEnv'), env.fgLeftTex, env.fgRightTex);
  tableShadowBack(layerMap.get('tableShadowBack'));
  updaters.push(characters(layerMap.get('characters'), env.charTexs));
  tableSurface(layerMap.get('tableSurface'), env.tableFrontTex);
  updaters.push(tableProps(layerMap.get('tableProps')));
  tableFrontLip(layerMap.get('tableFrontLip'), env.tableFrontTex);
  tableFrontShadow(layerMap.get('tableFrontShadow'));
  tableSupport(layerMap.get('tableSupport'));
  updaters.push(tableFrontProps(layerMap.get('tableFrontProps')));
  updaters.push(fgFx(layerMap.get('fgFx')));
  characterLabels(layerMap.get('labels'));
  updaters.push(hud(layerMap.get('hud'), env.charTexs || null, layerMap.get('drag')));
  updaters.push(cards(layerMap.get('cards'), layerMap.get('drag'), env.cardTexs));

  // 每层一个调试标签，默认隐藏（按 L 唤出）
  LAYERS.forEach((d, i) => {
    const t = new Text({ text: `${d.id} · z${d.z}`, style: DEBUG_STYLE });
    t.position.set(48, 210 + i * 20);
    t.visible = false;
    layerMap.get(d.id).addChild(t);
    debugTexts.push(t);
  });

  return {
    update(t) {
      for (const u of updaters) u(t);
    },
    toggleLabels() {
      const v = !debugTexts[0].visible;
      for (const t of debugTexts) t.visible = v;
    },
  };
}
