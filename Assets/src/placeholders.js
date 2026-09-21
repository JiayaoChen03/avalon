// 各层占位块视觉 + 逐层动效（1536×1024 设计坐标系，布局规格见 config.js LAYOUT）
// 资产替换原则：删除对应 builder，改为 Sprite 加载 public/assets/ 下的 webp，层结构不动

import { Container, Graphics, Rectangle, Sprite, Text, Texture } from 'pixi.js';
import {
  DESIGN_W as W, DESIGN_H as H, BLEED, LAYERS, LAYOUT, CHAR_XS, CHARACTERS, CARDS,
} from './config.js';

const DEBUG_STYLE = { fontFamily: 'monospace', fontSize: 16, fill: 0x9a8a90 };
const UI_STYLE = { fontFamily: 'serif', fontSize: 20, fill: 0x9a8a90 };
const PLATE_STYLE = { fontFamily: 'serif', fontSize: 21, fill: 0xd8c8b8 };

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

function characters(L, charTexs) {
  // 立绘布板：基高 370×c.scale（352 加大一档：剪影→真立绘后同尺寸读着"离桌远"，
  // 放大后人物贴着桌沿 looming，"刚站在桌后"的读法）；底中对齐 FOOT_Y。
  // 站位上提 20px（脚 y600）：脚在桌后不可见区，纯粹换取头顶空间——
  // 左侧头顶须避开标题组(y≤190)、医者帽须落进任务面板下方
  // 宽度预算 = 与最近邻座的实际净空（布板不越邻）；国王不吃宽预算（高度优先）
  // 注意 holder 还会乘 c.scale（剪影体系的缩放容器）——body 预除回去，防双重缩放
  const BASE_H = 370;
  const FOOT_Y = LAYOUT.charBaseline - 20;
  const WIDTH_BUDGET = [160, 190, 180, 999, 175, 160];
  // 医者立绘下沉：任务面板(y30-350)盖住他天然较高的帽顶——下沉后帽+喙
  // 全部落进面板下缘以下的可见带（脚沉到桌后不可见区，读作站得更靠后）
  const Y_SINK = [0, 0, 0, 0, 0, 141];
  const figures = CHARACTERS.map((c, i) => {
    const holder = new Container();
    const shadow = new Graphics().ellipse(0, 0, 72, 18).fill({ color: 0x000000, alpha: 0.45 });
    let body;
    const tex = charTexs && charTexs[c.id];
    if (tex) {
      body = new Sprite(tex);
      body.anchor.set(0.5, 1);
      // 国王不吃宽预算：370×1.12=414 净高优先（宽 ~292 与流浪者仍有净空）
      const sNet = Math.min(BASE_H * c.scale / tex.height, WIDTH_BUDGET[i] / tex.width);
      body.scale.set(sNet / c.scale);
      body.y = 2; // 脚尖略沉进接地阴影（避让下沉走 holder.y，见下）
    } else {
      body = new Graphics();
      drawRoleBody(body, c);
    }
    holder.addChild(shadow, body);
    holder.position.set(CHAR_XS[i] * W, FOOT_Y);
    holder.scale.set(c.scale);
    // 下沉量并入 holder.y（呼吸 updater 每帧覆写 body.y，sink 若放 body.y 会被
    // 完全冲掉——v3-v5 医者帽一直顶在面板后就是这个 bug，A/B 差分帧相同暴露的）
    if (Y_SINK[i]) holder.y += Y_SINK[i];
    // 流浪者的佝偻已画进立绘本身，holder 倾斜减半避免过度前倾
    if (c.tilt) body.rotation = tex ? c.tilt * 0.5 : c.tilt;
    // 末端二人补一层暖光纱（加法极淡）：画面两端本就最暗，立绘又是深值——
    // 不补这层时读成纯黑剪影"贴"在黑边上，与中央四人接烛光的体积感脱节
    if (tex && (c.id === 'prophet' || c.id === 'doctor')) {
      const warm = new Sprite(getGlowTexture('ember'));
      warm.anchor.set(0.5);
      warm.blendMode = 'add';
      warm.alpha = c.id === 'prophet' ? 0.09 : 0.07;
      warm.scale.set(190 / 128, 420 / 128);
      warm.position.set(0, -tex.height * body.scale.x * 0.4);
      holder.addChild(warm);
    }
    L.addChild(holder);
    return { body, phase: i * 1.3 };
  });
  return (t) => {
    for (const f of figures) f.body.y = Math.sin(t * 0.0011 + f.phase) * 3;
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
    // 蜡油渍（烛座的年代痕迹）
    const wax = new Graphics();
    wax.ellipse(-14, 4, 7, 2.5).fill({ color: 0x9a8a6c, alpha: 0.35 });
    wax.ellipse(12, 5, 5, 2).fill({ color: 0x8a7a5e, alpha: 0.3 });
    // 烟熏暗渍（烛火经年熏出的黑斑）
    wax.ellipse(-16, -8, 9, 5).fill({ color: 0x0a0a0c, alpha: 0.28 });
    // 更宽的极淡烟熏晕（经年烟气扩散的大圈，几乎不可见只添陈旧感）
    wax.ellipse(-4, -11, 17, 6).fill({ color: 0x0a0a0c, alpha: 0.14 });
    // 干蜡流痕：自烛座向桌沿的旧蜡滴（年代使用痕迹，走向桌外缘）
    wax.moveTo(-9, 2).lineTo(-11.5, 14);
    wax.moveTo(7, 3).lineTo(9, 12).lineTo(8, 21);
    wax.stroke({ width: 1.5, color: 0x8a7452, alpha: 0.38 });
    wax.position.set(x, baseY);
    L.addChild(wax);
    // 接触阴影 + 烛身 + 烛泪盘
    const cs = new Graphics();
    cs.ellipse(0, 3, 19, 6).fill({ color: 0x000000, alpha: 0.32 });
    cs.ellipse(0, 2.5, 14, 4.5).fill({ color: 0x000000, alpha: 0.58 });
    cs.rect(-5, -24, 10, 26).fill(0xcfc2a4);
    cs.rect(-5, -24, 3, 26).fill({ color: 0x8a7a64, alpha: 0.7 });
    cs.ellipse(0, -25, 5, 2.5).fill(0xbca88a);
    cs.position.set(x, baseY);
    L.addChild(cs);
    const flame = new Graphics().circle(0, 0, 7).fill(0xffa542);
    flame.position.set(x, baseY - 31);
    L.addChild(flame);
    const glow = new Sprite(getGlowTexture('ember'));
    glow.anchor.set(0.5);
    glow.blendMode = 'add';
    glow.scale.set(34 / 128);
    glow.position.set(x, baseY - 34);
    glow.alpha = 0.55;
    L.addChild(glow);
    flames.push({ flame, glow, pool, core, phase: flames.length * 2.1 });
  }
  // 羊皮纸角 ×2：接触投影垫出"坐在桌上"的接地感；右块内移避让右下日志面板
  const p = new Graphics();
  p.roundRect(W * 0.26 + 4, 566, 150, 48, 6).fill({ color: 0x000000, alpha: 0.35 });
  p.roundRect(W * 0.575 + 4, 570, 140, 44, 6).fill({ color: 0x000000, alpha: 0.35 });
  p.roundRect(W * 0.26, 560, 150, 48, 6).fill({ color: 0x6e5e42, alpha: 0.9 });
  p.roundRect(W * 0.575, 564, 140, 44, 6).fill({ color: 0x6e5e42, alpha: 0.78 });
  L.addChild(p);
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
      const k = 0.65 + Math.sin(t * 0.012 + f.phase) * 0.3;
      f.flame.alpha = k;
      f.flame.scale.set(0.85 + Math.sin(t * 0.02 + f.phase * 1.4) * 0.18);
      f.glow.alpha = 0.4 + 0.25 * k;
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

function nameplates(L) {
  CHARACTERS.forEach((c, i) => {
    const name = new Text({ text: c.name, style: PLATE_STYLE });
    const pw = name.width + 26 + ((i * 17) % 22);
    const plate = new Graphics();
    plate.roundRect(-pw / 2, 0, pw, 40, 6).fill({ color: 0x23141a, alpha: 0.95 });
    plate.roundRect(-pw / 2, 0, pw, 40, 6).stroke({ width: 2, color: 0x6a3a2e });
    plate.position.set(CHAR_XS[i] * W + c.dx, LAYOUT.plateY + c.dy);
    plate.rotation = c.rot;
    name.position.set(-name.width / 2, 7);
    plate.addChild(name);
    L.addChild(plate);
  });
}

function hud(L) {
  // ── 左上标题系统（整组下移 32px，层级 AVALON > 副标题 > 中文标语）──
  const bl = LAYOUT.bannerL;
  const blc = bl.x + bl.w / 2;
  const bannerLeft = new Graphics();
  bannerLeft.rect(bl.x, 24, bl.w, 576).fill({ color: 0x4a1016, alpha: 0.92 });
  bannerLeft.circle(blc, 110, 9).fill(0x8a2028);
  bannerLeft.poly([blc - 8, 290, blc, 278, blc + 8, 290, blc, 302]).fill(0x8a2028);
  bannerLeft.circle(blc, 480, 5).fill(0x6a1820);
  L.addChild(bannerLeft);

  const tx = LAYOUT.title.x;
  const ty = LAYOUT.title.y;
  const tTitle = new Text({
    text: 'AVALON',
    style: { fontFamily: 'serif', fontSize: 44, fill: 0xd8c8b8, letterSpacing: 6 },
  });
  tTitle.position.set(tx, ty);
  L.addChild(tTitle);
  const rule = new Graphics().rect(tx, ty + 58, 210, 2).fill(0x6a3a2e);
  L.addChild(rule);
  const tSub = new Text({
    text: '空冠之下 · Beneath the Hollow Crown',
    style: { fontFamily: 'serif', fontSize: 18, fill: 0x9a8a90 },
  });
  tSub.position.set(tx, ty + 70);
  L.addChild(tSub);
  const tSlogan = new Text({
    text: '当信仰腐烂，谁仍能看见人性？',
    style: { fontFamily: 'serif', fontSize: 15, fill: 0x7a5a62 },
  });
  tSlogan.position.set(tx, ty + 98);
  L.addChild(tSlogan);

  // ── 左下对话面板（次要，外框锁定）──
  const chat = LAYOUT.chat;
  const dialogue = new Graphics();
  dialogue.roundRect(0, 0, chat.w, chat.h, 10).fill({ color: 0x1c0f14, alpha: 0.85 });
  dialogue.roundRect(0, 0, chat.w, chat.h, 10).stroke({ width: 1.5, color: 0x3a2a22 });
  dialogue.position.set(chat.x, chat.y);
  L.addChild(dialogue);
  const tabOn = new Graphics();
  tabOn.roundRect(12, 623, 56, 24, 6).fill(0x351f26);
  tabOn.roundRect(12, 623, 56, 24, 6).stroke({ width: 1.5, color: 0x6a3a2e });
  L.addChild(tabOn);
  const tabOff = new Graphics();
  tabOff.roundRect(76, 623, 56, 24, 6).stroke({ width: 1.5, color: 0x2a1a20 });
  L.addChild(tabOff);
  [
    { text: '记录', x: 12, fill: 0xc8b8a8 },
    { text: '发言', x: 76, fill: 0x5a4a52 },
  ].forEach((tb) => {
    const t = new Text({ text: tb.text, style: { fontFamily: 'serif', fontSize: 14, fill: tb.fill } });
    t.position.set(tb.x + 28 - t.width / 2, 629);
    L.addChild(t);
  });
  const logStyle = { fontFamily: 'serif', fontSize: 13, fill: 0x7a6a70 };
  const log1 = new Text({ text: '先知：真相从不沉默。', style: logStyle });
  log1.position.set(22, 668);
  const log2 = new Text({ text: '医者：我们都已腐烂。', style: logStyle });
  log2.position.set(22, 690);
  L.addChild(log1, log2);
  const inputBox = new Graphics();
  inputBox.roundRect(10, 958, 295, 34, 6).fill(0x140a0e);
  inputBox.roundRect(10, 958, 295, 34, 6).stroke({ width: 1.5, color: 0x2a1a20 });
  L.addChild(inputBox);
  const inputHint = new Text({ text: '输入消息…', style: { fontFamily: 'serif', fontSize: 13, fill: 0x5a4a50 } });
  inputHint.position.set(22, 968);
  L.addChild(inputHint);

  // ── 右上任务面板（外框锁定，26px 内边距五区结构）──
  const mission = LAYOUT.mission;
  const p = mission.pad;
  const missionG = new Graphics();
  missionG.roundRect(0, 0, mission.w, mission.h, 10).fill({ color: 0x1c0f14, alpha: 0.94 });
  missionG.roundRect(0, 0, mission.w, mission.h, 10).stroke({ width: 2, color: 0x55392c });
  missionG.position.set(mission.x, mission.y);
  L.addChild(missionG);
  const mText = new Text({ text: '任务 · 第 2 次远征', style: UI_STYLE });
  mText.position.set(mission.x + p, mission.y + 26);
  L.addChild(mText);
  const dots = new Graphics();
  for (let i = 0; i < 6; i++) {
    dots.circle(mission.x + p + 4 + i * 24, mission.y + 72, 5).fill(i < 2 ? 0xb0543a : 0x3a2a26);
  }
  L.addChild(dots);
  const reqText = new Text({
    text: '派遣 3 名成员 · 成功需要 2 票',
    style: { fontFamily: 'serif', fontSize: 15, fill: 0x7a6a70 },
  });
  reqText.position.set(mission.x + p, mission.y + 92);
  L.addChild(reqText);
  const preview = new Graphics();
  preview.roundRect(mission.x + p, mission.y + 118, mission.w - p * 2, 92, 6).fill(0x0d0709);
  preview.roundRect(mission.x + p, mission.y + 118, mission.w - p * 2, 92, 6).stroke({ width: 1.5, color: 0x3a2a26 });
  L.addChild(preview);
  const previewText = new Text({
    text: '远征预览',
    style: { fontFamily: 'serif', fontSize: 13, fill: 0x5a4a55 },
  });
  previewText.position.set(mission.x + p + 12, mission.y + 156);
  L.addChild(previewText);
  const quoteBar = new Graphics().rect(mission.x + p, mission.y + 226, 3, 48).fill(0x6a3a2e);
  L.addChild(quoteBar);
  const quote = new Text({
    text: '「王冠之下，无人生还。」',
    style: { fontFamily: 'serif', fontSize: 15, fill: 0x8a7a70 },
  });
  quote.position.set(mission.x + p + 14, mission.y + 234);
  L.addChild(quote);

  // ── 中央动作栈：派遣条（2 已选 + 1 空位）──
  const party = LAYOUT.party;
  const filled = [CHARACTERS[2], CHARACTERS[4], null];
  filled.forEach((s, i) => {
    const sx = W / 2 + (i - 1) * party.gap - party.slot / 2;
    // 石面接触投影：令牌坐进石面的接地暗晕（短、近锐远柔——只给世界实体，非 UI 投影）
    const ct = new Graphics();
    ct.roundRect(3, 5, party.slot, party.slot * 0.4, 12).fill({ color: 0x000000, alpha: 0.38 });
    ct.position.set(sx, party.y + party.slot - 10);
    L.addChild(ct);
    const g = new Graphics();
    g.roundRect(0, 0, party.slot, party.slot, 10)
      .fill(s ? { color: s.color, alpha: 0.9 } : 0x140a0e);
    g.roundRect(0, 0, party.slot, party.slot, 10)
      .stroke({ width: 2, color: s ? 0x6a3a2e : 0x2c1c22 });
    g.position.set(sx, party.y);
    L.addChild(g);
    if (!s) {
      const label = new Text({ text: '+', style: { fontFamily: 'serif', fontSize: 30, fill: 0x6a5a60 } });
      label.position.set(sx + party.slot / 2 - label.width / 2, party.y + 14);
      L.addChild(label);
    }
  });

  // ── 确认派遣按钮 ──
  const cf = LAYOUT.confirm;
  const btn = new Graphics();
  btn.roundRect(0, 0, cf.w, cf.h, 8).fill(0x6e1a1e);
  btn.roundRect(0, 0, cf.w, cf.h, 8).stroke({ width: 2, color: 0x8a3026 });
  btn.position.set(W / 2 - cf.w / 2, cf.y);
  L.addChild(btn);
  const btnText = new Text({ text: '确认派遣', style: { fontFamily: 'serif', fontSize: 22, fill: 0xe8d0c0 } });
  btnText.position.set(W / 2 - btnText.width / 2, cf.y + 8);
  L.addChild(btnText);

  // ── 底部状态 rail：○ ○ ○ ○  行动点 1/3（居中，占底部 ~50px 带宽）──
  const ay = LAYOUT.apLine.y;
  const rail = new Graphics();
  for (let i = 0; i < 4; i++) {
    // 暗点用可读闷色（0x3a2a26 会在木色桌面上隐形）
    rail.circle(660 + i * 24, ay, 5).fill(i === 0 ? 0xb0543a : 0x6a4a46);
  }
  L.addChild(rail);
  const apText = new Text({ text: '行动点 1/3', style: { ...UI_STYLE, fill: 0xc8b8a8 } });
  apText.position.set(770, ay - apText.height / 2);
  L.addChild(apText);

  // ── 右下羊皮纸情报面板：多层纸张错位叠放（外框锁定）──
  const note = LAYOUT.note;
  const noteC = new Container();
  const sheet2 = new Graphics();
  sheet2.roundRect(18, 12, note.w - 12, note.h - 4, 6).fill({ color: 0x5c4a34, alpha: 0.85 });
  sheet2.roundRect(18, 12, note.w - 12, note.h - 4, 6).stroke({ width: 2, color: 0x241812 });
  const sheet3 = new Graphics();
  sheet3.roundRect(-14, -8, 90, 70, 4).fill({ color: 0x7a6845, alpha: 0.9 });
  const sheet1 = new Graphics();
  sheet1.roundRect(0, 0, note.w, note.h, 6).fill({ color: 0x6e5a3f, alpha: 0.95 });
  sheet1.roundRect(0, 0, note.w, note.h, 6).stroke({ width: 2, color: 0x2e2118 });
  noteC.addChild(sheet2, sheet3, sheet1);
  const crown = new Graphics();
  const cxn = note.w / 2;
  crown.circle(cxn, 56, 5).fill(0x7c2a20);
  crown.poly([cxn - 18, 70, cxn - 12, 52, cxn - 6, 70]).fill(0x7c2a20);
  crown.poly([cxn - 4, 70, cxn + 2, 48, cxn + 8, 70]).fill(0x7c2a20);
  crown.poly([cxn + 6, 70, cxn + 12, 52, cxn + 18, 70]).fill(0x7c2a20);
  noteC.addChild(crown);
  const noteStyle = { fontFamily: 'serif', fontSize: 22, fill: 0x241a10 };
  const n1 = new Text({ text: '真相尚未到来，', style: noteStyle });
  const n2 = new Text({ text: '但它正在靠近。', style: noteStyle });
  n1.position.set(note.w / 2 - n1.width / 2, 110);
  n2.position.set(note.w / 2 - n2.width / 2, 146);
  noteC.addChild(n1, n2);
  noteC.position.set(note.x, note.y);
  noteC.rotation = 0.015;
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
}

// 卡牌：底部中心枢轴扇形，rot/scale/raise/z 逐卡来自 config
function cards(L) {
  const list = [];
  const cl = LAYOUT.cards;
  const mid = (CARDS.length - 1) / 2;
  L.sortableChildren = true;
  CARDS.forEach((c, i) => {
    const isCenter = i === mid;
    const cw = isCenter ? cl.centerW : cl.w;
    const chh = isCenter ? cl.centerH : cl.h;
    const cx = cl.centerX + (i - mid) * cl.spacing;
    const by = cl.bottomY - c.raise; // 卡底枢轴；raise 为整体抬高量
    const card = new Container();
    const frame = new Graphics();
    // 以底部中心为局部原点（旋转/缩放枢轴）
    frame.roundRect(-cw / 2, -chh, cw, chh, 14).fill(0x241014);
    frame.roundRect(-cw / 2, -chh, cw, chh, 14).stroke({ width: 2, color: 0x6a3a2e });
    frame.roundRect(-cw / 2 + 12, -chh + 12, cw - 24, chh - 24, 10).fill(0x0d0709);
    frame.circle(-cw / 2 + 22, -chh + 22, 14).fill(0x7c2a20);
    card.addChild(frame);
    const name = new Text({ text: c.name, style: { fontFamily: 'serif', fontSize: 22, fill: 0xd8c8b8 } });
    name.position.set(-name.width / 2, -46);
    const cost = new Text({ text: String(c.cost), style: { fontFamily: 'serif', fontSize: 17, fill: 0xe8d8c8 } });
    cost.position.set(-cw / 2 + 22 - cost.width / 2, -chh + 22 - cost.height / 2);
    card.addChild(name, cost);
    card.position.set(cx, by);
    card.scale.set(c.scale);
    card.rotation = (c.rot * Math.PI) / 180;
    card.zIndex = c.z; // 中央卡最高层级
    L.addChild(card);
    list.push({ card, baseY: by, phase: i * 0.9 });
  });
  return (t) => {
    for (const { card, baseY, phase } of list) card.y = baseY + Math.sin(t * 0.0013 + phase) * 3;
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
  nameplates(layerMap.get('labels'));
  hud(layerMap.get('hud'));
  updaters.push(cards(layerMap.get('cards')));

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
