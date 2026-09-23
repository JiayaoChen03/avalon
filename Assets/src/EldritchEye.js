// 独立封装的古神之眼组件（Eldritch Eye）—— v7: 补全动画应用层 + 可读性增强
// 分层：crackSocketStatic(裂口体,永不动) / scleraStatic(眼球基底,±1px)
//       / socketAmbient×2(上下眼窝暗红环境光,上下两条不连成完整椭圆)
//       / irisContainer[iris+glow+pupil](唯一可动,被 eyeMask 裁切)
//       / topOcclusion×2(静态遮挡,总遮挡约30-40%) / atmosphericOverlay(低频红雾,不跟鼠标)
// 交互：注视鼠标(死区40px+归一方向+椭圆钳制+分层阻尼 0.08/0.12)、
//       随机眨眼(8-20s,10%双眨,纯辉光熄灭式压暗)、高速鼠标→瞳孔收缩400ms、靠近→辉光渐升
// 性能：pointermove 只写目标值；一切缓动/呼吸/眨眼统一在 update(dt) 内计算，零分配
import { Container, Graphics, Sprite, Texture } from 'pixi.js';
import { DESIGN_W as W, DESIGN_H as H } from './config.js';

// —— 模块私有程序纹理 ——
const texCache = {};
function makeRadial(key, stops) {
  if (texCache[key]) return texCache[key];
  const c = document.createElement('canvas');
  c.width = 128;
  c.height = 128;
  const ctx = c.getContext('2d');
  const g = ctx.createRadialGradient(64, 64, 0, 64, 64, 64);
  for (const [p, col] of stops) g.addColorStop(p, col);
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, 128, 128);
  texCache[key] = Texture.from(c);
  return texCache[key];
}
function makeLidTexture() {
  // 眼睑条：外端实心暗部 → 内端柔和渐隐（上下两条镜像使用）
  if (texCache.lid) return texCache.lid;
  const c = document.createElement('canvas');
  c.width = 256;
  c.height = 128;
  const ctx = c.getContext('2d');
  const g = ctx.createLinearGradient(0, 0, 0, 128);
  g.addColorStop(0, 'rgba(8,3,5,0.96)');
  g.addColorStop(0.72, 'rgba(10,4,6,0.9)');
  g.addColorStop(1, 'rgba(12,5,7,0)');
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, 256, 128);
  texCache.lid = Texture.from(c);
  return texCache.lid;
}
const innerGlowTex = () => makeRadial('ee-inner', [
  [0, 'rgba(160,34,40,0.85)'],
  [0.5, 'rgba(120,22,28,0.4)'],
  [1, 'rgba(80,14,18,0)'],
]);
const auraTex = () => makeRadial('ee-aura', [
  [0, 'rgba(150,32,42,0.5)'],
  [0.5, 'rgba(110,22,30,0.22)'],
  [1, 'rgba(80,14,20,0)'],
]);
const scleraTex = () => makeRadial('ee-sclera', [
  [0, 'rgba(58,12,16,0.95)'],
  [0.55, 'rgba(36,8,12,0.7)'],
  [1, 'rgba(18,5,8,0)'],
]);
// 眼窝边缘环境光：暗红、加法混合、极弱——只让轮廓可感知，不形成独立发光体
const socketEdgeTex = () => makeRadial('ee-socketEdge', [
  [0, 'rgba(112,24,30,0.55)'],
  [0.55, 'rgba(82,16,22,0.26)'],
  [1, 'rgba(56,12,16,0)'],
]);

// 运行时羽化：把贴图 alpha 乘以椭圆径向渐变（destination-in），
// 生成图的硬切外缘直接融进透明，跨 Pixi 版本行为完全确定
function featherTexture(tex) {
  const src = tex.source.resource;
  const w = tex.width;
  const h = tex.height;
  const c = document.createElement('canvas');
  c.width = w;
  c.height = h;
  const ctx = c.getContext('2d');
  ctx.drawImage(src, 0, 0, w, h);
  ctx.globalCompositeOperation = 'destination-in';
  ctx.translate(w / 2, h / 2);
  ctx.scale(w / 2, h / 2); // 单位圆 → 覆盖全画布的椭圆
  const g = ctx.createRadialGradient(0, 0, 0, 0, 0, 1);
  g.addColorStop(0, 'rgba(0,0,0,1)');
  g.addColorStop(0.72, 'rgba(0,0,0,1)');
  g.addColorStop(0.92, 'rgba(0,0,0,0.85)');
  g.addColorStop(1, 'rgba(0,0,0,0)');
  ctx.fillStyle = g;
  ctx.fillRect(-1.2, -1.2, 2.4, 2.4);
  return Texture.from(c);
}

// 虹膜程序纹理：暗红圆盘基底 + 52 条放射血丝/焦红笔触（种子随机，形态稳定）
// 可读性规格：暗红亮度 +20%（保持暗红调，只提亮，不做亮色眼球）
function makeIrisTexture() {
  const S = 256;
  const c = document.createElement('canvas');
  c.width = S;
  c.height = S;
  const ctx = c.getContext('2d');
  const base = ctx.createRadialGradient(128, 128, 10, 128, 128, 120);
  base.addColorStop(0, 'rgba(84,17,22,1)');
  base.addColorStop(0.55, 'rgba(55,12,17,1)');
  base.addColorStop(0.94, 'rgba(33,8,12,0.7)');
  base.addColorStop(1, 'rgba(29,7,11,0)');
  ctx.fillStyle = base;
  ctx.beginPath();
  ctx.arc(128, 128, 120, 0, Math.PI * 2);
  ctx.fill();
  let seed = 7;
  const rnd = () => {
    seed = (seed * 16807) % 2147483647;
    return seed / 2147483647;
  };
  for (let i = 0; i < 52; i++) {
    const a = rnd() * Math.PI * 2;
    const len = 55 + rnd() * 48;
    const w = 1.5 + rnd() * 2.5;
    const x0 = 128 + Math.cos(a) * 14;
    const y0 = 128 + Math.sin(a) * 14;
    const x1 = 128 + Math.cos(a + (rnd() - 0.5) * 0.5) * len;
    const y1 = 128 + Math.sin(a + (rnd() - 0.5) * 0.5) * len;
    ctx.strokeStyle = ['rgba(138,30,34,0.8)', 'rgba(101,18,25,0.75)', 'rgba(172,46,39,0.65)', 'rgba(69,12,16,0.85)'][i % 4];
    ctx.lineWidth = w;
    ctx.beginPath();
    ctx.moveTo(x0, y0);
    ctx.lineTo(x1, y1);
    ctx.stroke();
    if (rnd() > 0.6) {
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(x1, y1);
      ctx.lineTo(x1 + Math.cos(a + 0.5) * (8 + rnd() * 12), y1 + Math.sin(a + 0.5) * (8 + rnd() * 12));
      ctx.stroke();
    }
  }
  return Texture.from(c);
}

// 竖缝瞳孔：程序绘制的镜片形（上下尖、中间略宽），近纯黑 + 两侧极弱余烬侧光
// rim light 作为瞳孔子对象：受惊收缩（scaleY 压扁）时侧光同步跟随，天然正确
function makeSlit() {
  const g = new Graphics();
  const pts = [0, -78, 5, -30, 7, 0, 5, 30, 0, 78, -5, 30, -7, 0, -7, -30];
  g.poly(pts).fill(0x050203);
  g.poly(pts).stroke({ width: 1.5, color: 0x7a1a14, alpha: 0.5 });
  const rim = new Graphics();
  const left = [-2.5, -70, -8, -30, -10, 0, -8, 30, -2.5, 70];
  const right = [2.5, -70, 8, -30, 10, 0, 8, 30, 2.5, 70];
  rim.poly(left).stroke({ width: 2.2, color: 0x9a2a20, alpha: 0.3 });
  rim.poly(right).stroke({ width: 2.2, color: 0x9a2a20, alpha: 0.3 });
  rim.blendMode = 'add';
  g.addChild(rim);
  return g;
}

const clamp01 = (v) => (v < 0 ? 0 : v > 1 ? 1 : v);
const easeInOut = (p) => (p < 0.5 ? 2 * p * p : 1 - (-2 * p + 2) ** 2 / 2);

export class EldritchEye {
  constructor(layer, { eyeTex, cloudTex = null, cx = 0.6, cy = 0.1, height = 440 }) {
    this.layer = layer;
    this.centerX = cx * W;
    this.centerY = cy * H;
    this.eyeH = height;
    this.eyeW = height * (eyeTex.width / eyeTex.height);

    // —— 状态 ——
    this.time = 0;
    this.targetX = this.centerX;
    this.targetY = this.centerY;
    this.scl = { x: 0, y: 0 };  // sclera 微漂（±1px 级）
    this.iri = { x: 0, y: 0 };  // iris 偏移（lerp 0.08）
    this.pup = { x: 0, y: 0 };  // pupil 偏移（lerp 0.12）
    this.intensity = 0;         // 靠近增强（0..1 平滑）
    this.externalIntensity = 0;
    this.contractStart = -1e9;
    this.contractCooldown = 0;
    this.lidT = 0;              // 闭眼进度 0..1
    this.blinkState = 'idle';   // idle | close | hold | open | gap
    this.blinkT0 = 0;
    this.pendingDouble = false;
    this.nextBlinkAt = 6000 + Math.random() * 8000;
    // 卡牌聚焦（悬停卡 → 突然睁开注视该牌）：openV=睁开因子（开快 0.3/关慢 0.02），
    // focusOn 期间注视目标锁定卡位、前 350ms snap lerp 猛转头、抑制随机眨眼
    this.focusOn = false;
    this.focusX = 0;
    this.focusY = 800;          // 手牌带高度
    this.openV = 0;
    this.focusSnapT = -1e9;

    this.buildSprites(eyeTex, cloudTex);
    this.setupMask();
    layer.addChild(this.holder);
  }

  buildSprites(eyeTex, cloudTex) {
    const holder = new Container();
    holder.position.set(this.centerX, this.centerY);
    this.holder = holder;
    this.base = this.eyeH / eyeTex.height;

    // crackSocketStatic：静态裂缝+天空创口（运行时羽化消硬边）——永不动
    // 生成图偏灰白（"stained glass"被字面理解），tint 压成暗红黑以符合血肉化色调
    this.socket = new Sprite(featherTexture(eyeTex));
    this.socket.anchor.set(0.5);
    this.socket.tint = 0x5a1420;
    this.socket.scale.set(this.base);
    holder.addChild(this.socket);

    // scleraStatic：暗红眼球基底（几乎静止，仅 ±1px 呼吸漂移）
    this.sclera = new Sprite(scleraTex());
    this.sclera.anchor.set(0.5);
    this.sclera.scale.set((this.eyeW * 0.52) / 128, (this.eyeH * 0.44) / 128);
    holder.addChild(this.sclera);

    // socketAmbient：上下眼窝边缘的少量暗红环境光（加法混合）
    // 只做上下两条，左右留空——轮廓可感知但不连成完整规则椭圆
    this.socketAmbient = [];
    [[0, -0.4, 0.34], [0, 0.42, 0.3]].forEach(([ax, ay, a]) => {
      const s = new Sprite(socketEdgeTex());
      s.anchor.set(0.5);
      s.blendMode = 'add';
      s.alpha = a;
      s.baseAlpha = a;
      s.position.set(ax * this.eyeW, ay * this.eyeH);
      s.scale.set((this.eyeW * 1.35) / 128, (this.eyeH * 0.36) / 128);
      this.socketAmbient.push(s);
      holder.addChild(s);
    });

    // irisContainer：唯一可动组（iris + glow + pupil）
    this.irisContainer = new Container();
    this.iris = new Sprite(makeIrisTexture());
    this.iris.anchor.set(0.5);
    this.irisBase = (this.eyeW * 0.5) / 256;
    this.iris.scale.set(this.irisBase);
    this.irisContainer.addChild(this.iris);
    this.glow = new Sprite(innerGlowTex());
    this.glow.anchor.set(0.5);
    this.glow.blendMode = 'add';
    this.glow.alpha = 0.15;
    this.glow.scale.set(150 / 128);
    this.irisContainer.addChild(this.glow);
    this.pupil = makeSlit();
    this.irisContainer.addChild(this.pupil);
    holder.addChild(this.irisContainer);

    // eyeMask 遮罩由 setupMask() 创建并挂载（renderable=false，仅作裁切不作渲染）
    holder.addChild(this.irisContainer);

    // topOcclusion：静态前景暗云（打断完整边界；尺寸/透明度压低使总遮挡约 30-40%）
    this.occlusion = [];
    if (cloudTex) {
      [[-0.34, -0.38, 1], [0.38, 0.44, -1]].forEach(([sx, sy, flip]) => {
        const m = new Sprite(cloudTex);
        m.anchor.set(0.5);
        m.scale.set((this.eyeW * 0.95) / cloudTex.width);
        m.scale.y *= flip;
        m.tint = 0x1c0a10;
        m.alpha = 0.66;
        m.position.set(sx * this.eyeW, sy * this.eyeH);
        this.occlusion.push(m);
        holder.addChild(m);
      });
    }

    // atmosphericOverlay：低频红雾（不跟鼠标，极低频透明度变化）
    this.atmo = new Sprite(auraTex());
    this.atmo.anchor.set(0.5);
    this.atmo.alpha = 0.1;
    this.atmo.scale.set((this.eyeH * 2.2) / 128);
    holder.addChild(this.atmo);

    // 开眼闪光：卡牌聚焦瞬间的 900ms 钟形脉冲（"突然睁开"的可见拍点），
    // 加法混合盖在眼球基底上、前景遮云之下——云让开时正好露出
    this.flash = new Sprite(innerGlowTex());
    this.flash.anchor.set(0.5);
    this.flash.blendMode = 'add';
    this.flash.alpha = 0;
    this.flash.scale.set((this.eyeW * 0.62) / 128, (this.eyeH * 0.5) / 128);
    holder.addChildAt(this.flash, holder.children.indexOf(this.irisContainer));
  }

  setupMask() {
    // 固定椭圆遮罩：与裂口中央暗腔对齐，irisContainer 的一切动态被限制在其内
    // renderable=false：只作裁切，绝不作为可见内容渲染
    const mask = new Graphics();
    mask.ellipse(0, 0, this.eyeW * 0.30, this.eyeH * 0.36).fill(0xffffff);
    mask.position.set(0, 0);
    mask.renderable = false;
    this.holder.addChild(mask);
    this.irisContainer.mask = mask;
  }

  // —— 对外接口 ——————————————————————————————
  setTarget(x, y) {
    this.targetX = x;
    this.targetY = y;
  }

  notifyVelocity(speedPx) {
    if (speedPx > 55 && this.time > this.contractCooldown) {
      this.contractStart = this.time;
      this.contractCooldown = this.time + 1200 + Math.random() * 800;
    }
  }

  blink(force = false) {
    if (this.blinkState !== 'idle' && !force) return;
    this.blinkState = 'close';
    this.blinkT0 = this.time;
    if (force) this.pendingDouble = false;
  }

  setIntensity(v) {
    this.externalIntensity = clamp01(v);
  }

  // 卡牌聚焦：悬停卡牌 → 眼突然睁开并注视该牌方向（on=false 缓缓回落）
  focusCard(x, on) {
    if (on) {
      this.focusOn = true;
      this.focusX = x;
      this.focusSnapT = this.time;
      // 受惊式收缩一拍——"突然睁开"的戏剧节拍（直接写 contractStart 绕过冷却）
      this.contractStart = this.time;
    } else {
      this.focusOn = false;
    }
  }

  destroy() {
    this.layer.removeChild(this.holder);
    this.holder.destroy({ children: true });
  }

  // —— 每帧更新 ——————————————————————————————
  update(dt) {
    this.time += dt;
    this.updateBlink();
    this.updateTracking();
    this.updateIdle(dt);
  }

  updateTracking() {
    // 死区 40px → 归一方向 → 分层椭圆半径 → 分层阻尼。
    // 卡牌聚焦期间目标锁定为该牌位置（无视鼠标），开场 350ms 用 snap 阻尼猛转
    const tx = this.focusOn ? this.focusX : this.targetX;
    const ty = this.focusOn ? this.focusY : this.targetY;
    const dx = tx - this.centerX;
    const dy = ty - this.centerY;
    const dist = Math.hypot(dx, dy);
    let nx = 0;
    let ny = 0;
    if (dist > 40) {
      nx = dx / dist;
      ny = dy / dist;
    }
    // 目标（椭圆钳制：归一方向 × 半径，天然满足 (x/maxX)²+(y/maxY)² = 1）
    const irisMaxX = this.eyeW * 0.055;
    const irisMaxY = this.eyeH * 0.055;
    const pupilMaxX = this.eyeW * 0.075;
    const pupilMaxY = this.eyeH * 0.095;
    const tiX = nx * irisMaxX;
    const tiY = ny * irisMaxY;
    const tpX = nx * pupilMaxX;
    const tpY = ny * pupilMaxY;
    // 分层阻尼：pupil 略快于 iris（虹膜拖在瞳孔后面，制造深度）
    const snap = this.focusOn && (this.time - this.focusSnapT) < 350;
    const kI = snap ? 0.35 : 0.08;
    const kP = snap ? 0.45 : 0.12;
    this.iri.x += (tiX - this.iri.x) * kI;
    this.iri.y += (tiY - this.iri.y) * kI;
    this.pup.x += (tpX - this.pup.x) * kP;
    this.pup.y += (tpY - this.pup.y) * kP;
    // sclera：±1px 级呼吸漂移（几乎不动）
    const driftX = Math.sin(this.time * 0.00037 + 1.3) * 1;
    const driftY = Math.sin(this.time * 0.00023 + 4.1) * 1;
    this.scl.x += (driftX - this.scl.x) * 0.04;
    this.scl.y += (driftY - this.scl.y) * 0.04;
  }

  applyClamp() {
    // 椭圆钳制兜底（目标本身已在椭圆上，lerp 后仍在凸椭圆内——此处仅防御）
    const ex = this.eyeW * 0.075;
    const ey = this.eyeH * 0.095;
    const d = (this.pup.x / ex) ** 2 + (this.pup.y / ey) ** 2;
    if (d > 1) {
      this.pup.x *= 1 / Math.sqrt(d);
      this.pup.y *= 1 / Math.sqrt(d);
    }
    const d2 = (this.iri.x / (ex * 0.55)) ** 2 + (this.iri.y / (ey * 0.55)) ** 2;
    if (d2 > 1) {
      this.iri.x *= 1 / Math.sqrt(d2);
      this.iri.y *= 1 / Math.sqrt(d2);
    }
  }

  updateIdle() {
    const t = this.time;

    // —— 追踪应用：整组虹膜 + 瞳孔附加偏移（瞳孔先动、虹膜拖后 → 深度感）——
    this.applyClamp();
    this.irisContainer.position.set(this.iri.x, this.iri.y);
    this.pupil.position.set(this.pup.x - this.iri.x, this.pup.y - this.iri.y);
    this.sclera.position.set(this.scl.x, this.scl.y);

    // —— 靠近增强：eyeH*1.3 范围内辉光渐升（无 UI 暗示，缓慢趋近）——
    const gx = this.focusOn ? this.focusX : this.targetX;
    const gy = this.focusOn ? this.focusY : this.targetY;
    const nearK = clamp01(1 - Math.hypot(gx - this.centerX, gy - this.centerY) / (this.eyeH * 1.3));
    const wantI = Math.max(nearK, this.externalIntensity);
    this.intensity += (wantI - this.intensity) * 0.03;

    // —— 卡牌聚焦：睁开因子（开快 0.3 = "突然"，关慢 0.02 = 余威缓缓回落）——
    this.openV += ((this.focusOn ? 1 : 0) - this.openV) * (this.focusOn ? 0.3 : 0.02);
    const op = this.openV;

    // 开眼闪光：聚焦起点后 900ms 钟形脉冲（可读的"啪一下"拍点）
    const ob = this.focusOn ? Math.sin(Math.PI * clamp01((t - this.focusSnapT) / 900)) : 0;
    this.flash.alpha = 0.42 * ob;

    // 前景遮云让开：睁开时云层退散 75%——"云开眼现"是"睁开"的最强读法
    for (let i = 0; i < this.occlusion.length; i++) {
      this.occlusion[i].alpha = 0.66 * (1 - 0.75 * op);
    }

    // —— 受惊收缩：高速鼠标后 400ms 瞳孔纵向压扁 + 内辉脉动 ——
    let contractPulse = 0;
    const ck = (t - this.contractStart) / 400;
    if (ck >= 0 && ck < 1) {
      const bell = Math.sin(Math.PI * ck);
      this.pupil.scale.set(1, 1 - 0.15 * bell);
      contractPulse = 0.09 * bell;
    } else {
      this.pupil.scale.set(1, 1);
    }

    // —— 眨眼压暗：v5 认可的"纯辉光熄灭"——辉光强压、裂口中压、环境光轻压 ——
    const dim = 1 - 0.82 * this.lidT;

    // iris：5.5s ±2% 尺寸呼吸；聚焦时放大 6%（"睁大"）
    this.iris.scale.set(this.irisBase * (1 + Math.sin(t * 0.001143) * 0.02) * (1 + 0.06 * op));
    this.iris.alpha = 1 - 0.5 * this.lidT;

    // glow：4.5s+1.7s 双频呼吸 + ±1.5px 双频漂移 + 靠近/受惊增强（空闲 0.15-0.27，靠近至 ~0.32）
    // 聚焦睁开：+0.38 猛增——"突然睁开"的主要亮度信号（随瞳位置移动=方向可读）
    this.glow.alpha = clamp01(0.21 + 0.06 * Math.sin(t * 0.001396) + 0.02 * Math.sin(t * 0.00371 + 1.7) + 0.11 * this.intensity + contractPulse + 0.38 * op) * dim;
    this.glow.position.set(Math.sin(t * 0.0011) * 1.5, Math.sin(t * 0.0016 + 2.1) * 1.5);

    // socket：眨眼时轻压（结构永不动，仅短暂压暗）
    this.socket.alpha = 1 - 0.45 * this.lidT;

    // socketAmbient：缓慢明暗 + 眨眼轻压 + 聚焦增强（眼窝轮廓点燃）
    for (let i = 0; i < this.socketAmbient.length; i++) {
      const s = this.socketAmbient[i];
      s.alpha = s.baseAlpha * (1 + 0.15 * Math.sin(t * 0.001 + i * 2.4)) * (1 + 1.2 * op) * (1 - 0.35 * this.lidT);
    }

    // atmo：6s+1.7s 低频呼吸；聚焦时周围血雾 ×(1+3op)——整片天区"醒过来"
    this.atmo.alpha = (0.1 + 0.03 * Math.sin(t * 0.001047) + 0.015 * Math.sin(t * 0.003696 + 3)) * (1 + 3 * op) * (1 - 0.35 * this.lidT);
  }

  updateBlink() {
    // 眨眼状态机（close 130ms / hold 55ms / open 240ms，8-20s 随机，10% 双眨）
    // 聚焦注视期间抑制新眨眼（正在"盯着牌"时闭眼会破坏读法），进行中的眨眼照常收尾
    if (this.focusOn && this.blinkState === 'idle') {
      this.nextBlinkAt = this.time + 5000;
      this.lidT += (0 - this.lidT) * 0.1;
      return;
    }
    if (this.blinkState === 'idle' && this.time > this.nextBlinkAt) {
      this.blinkState = 'close';
      this.blinkT0 = this.time;
      this.pendingDouble = Math.random() < 0.1;
    }
    let lidTarget = 0;
    if (this.blinkState === 'close') {
      const p = (this.time - this.blinkT0) / 130;
      lidTarget = easeInOut(clamp01(p));
      if (p >= 1) { this.blinkState = 'hold'; this.blinkT0 = this.time; }
    } else if (this.blinkState === 'hold') {
      lidTarget = 1;
      if (this.time - this.blinkT0 > 55) { this.blinkState = 'open'; this.blinkT0 = this.time; }
    } else if (this.blinkState === 'open') {
      const p = (this.time - this.blinkT0) / 240;
      lidTarget = 1 - easeInOut(clamp01(p));
      if (p >= 1) {
        if (this.pendingDouble) {
          this.pendingDouble = false;
          this.blinkState = 'close';
          this.blinkT0 = this.time + 150;
        } else {
          this.blinkState = 'idle';
          this.nextBlinkAt = this.time + 8000 + Math.random() * 12000;
        }
      }
    }
    this.lidT += (lidTarget - this.lidT) * (this.blinkState === 'idle' ? 0.1 : 0.35);
  }
}
