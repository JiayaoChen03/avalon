// 全局配置：设计分辨率 / 分层定义 / 布局规格 / 角色与卡牌表
// 所有调参入口都集中在这里

// 固定设计坐标系
export const DESIGN_W = 1536;
export const DESIGN_H = 1024;
// 环境层绘制时的出血边距，保证视差最大偏移时不会露出黑边
export const BLEED = 160;

// z 间隔 10，方便日后插层；parallax 仅环境层（z<=100）有值
export const LAYERS = [
  { id: 'sky',        z: 30,  parallax: 0    },
  { id: 'cloudsFar',  z: 40 }, // 云不跟随鼠标，仅自然漂移动画（见 placeholders.js clouds）
  { id: 'skyDetail',  z: 45 }, // 天空细节层：天穹裂隙/眼状云纹/触手阴影/王冠圣环（静态）
  { id: 'cloudsMid',  z: 50 },
  { id: 'eye',        z: 60 }, // 邪眼本体锚定（层内自带微视差，见 EldritchEye.js）
  { id: 'tentacles',  z: 70,  parallax: 0.12 },
  { id: 'castle',     z: 80 }, // 城堡固定，不参与视差（含自动漂移）
  { id: 'midground',  z: 90 }, // 城市剪影+石桥固定（建筑带全部不动）
  { id: 'fgEnv',      z: 100 }, // 前景框景（枯树/石拱）固定
  { id: 'tableShadowBack', z: 105 }, // 桌后接地暗晕 + 桌外两侧/下方渐暗基础
  { id: 'characters', z: 120 },
  { id: 'tableSurface',     z: 125 }, // 梯形弧缘台面（遮住角色胸以下）
  { id: 'tableProps',       z: 128 }, // 蜡烛/羊皮纸/高脚杯（台面上）
  { id: 'tableFrontLip',    z: 132 }, // 前缘立面（可见厚度）
  { id: 'tableFrontShadow', z: 136 }, // 前缘下方深暗（卡牌的黑暗前景）
  { id: 'tableSupport',     z: 137 }, // 两侧祭坛石墩（块状两级基座+尖拱神龛，向下渐隐入黑）
  { id: 'tableFrontProps',  z: 139 }, // 桌前小道具（压在人物下缘前）
  { id: 'fgFx',       z: 140 },
  { id: 'labels',     z: 150 },
  { id: 'hud',        z: 160 },
  { id: 'cards',      z: 170 },
  { id: 'drag',       z: 180 },
  { id: 'modal',      z: 190 },
  { id: 'corruption', z: 195 },
];

// 布局规格（px 为设计坐标）。本轮为 blockout 锁定稿：
// 桌子/对话面板/羊皮纸/任务面板外框、中排四人 X、卡行总宽均已锁定
export const LAYOUT = {
  // 桌子（table-only pass 立体化）：中下部弧缘实体桌，不再铺满下半屏
  table: {
    backSideY: 528, backY: 538,       // 后缘弧（端点/中央，中央略沉）
    frontSideY: 606, frontY: 622,     // 前缘顶线弧（中央更近更低）
    lipSideH: 42, lipH: 56,           // 前缘立面厚（厚重祭坛切面：立面是整块石板的砍切面，中央 > 两侧）
    lipOutset: 8,                     // 立面比台面外扩 px
    backInset: 0.075, frontOut: 0.03, // 后缘内收 / 前缘外扩（×W）
  },
  charBaseline: 620,
  plateY: 552,         // 名牌骑在前桌沿上
  // 左上标题系统（整组下移 32px，顶部留白 72px ≥ 30px 安全边距）
  title: { x: 56, y: 72 },
  bannerL: { x: 8, w: 26 },
  // 左下对话面板（外框锁定）
  chat: { x: 0, y: 615, w: 315, h: 385 },
  // 右上任务面板（右缘贴住窄幡条，间距 8px；内部 padding 26px 五区结构）
  mission: { x: 1194, y: 30, w: 300, h: 320, pad: 26 },
  // 最右窄幅邪教横幅
  banner: { x: 1502, w: 26 },
  // 中央动作栈（整组上移：槽 588→521、按钮 658→591、卡组 958→934 底）
  party: { y: 521, slot: 64, gap: 120 },
  confirm: { w: 220, h: 40, y: 591 },
  cards: {
    centerX: 768, spacing: 164, bottomY: 934, // 收窄间距，让放大的卡牌连续遮住桌前支撑
    w: 198, h: 270, // 五张卡统一尺寸：静置时略放大，压住桌沿下方的穿帮
  },
  // 底部 HUD 状态带：rail 占 y≈974-1024（约 50px）
  apLine: { y: 996 },
  // 右下 P1 私密记录（外框锚点）
  note: { x: 1240, y: 650, w: 280, h: 350 },
  // 背景焦点
  eye: { x: 0.60, y: 0.10 },
  castleCenter: 0.55,
  keep: 0.62,
};

// 角色中心 X（fraction）。边缘二人按锁定稿平移：先知 +36px→9.34%，医者 -40px→87.92%
// 中排四人（骑士/修女/国王/流浪者）位置锁定
export const CHAR_XS = [0.0934, 0.21, 0.38, 0.62, 0.76, 0.8792];

// headR=剪影头半径, shW=肩宽, tilt=身体微倾；scale/dx/dy/rot 为整体缩放与名牌偏移
export const CHARACTERS = [
  { id: 'prophet',  name: '先知',   color: 0x4a3550, headR: 44, shW: 68,  scale: 1.00, tilt: 0,     dx: -8,  dy: -6,  rot: -0.012 },
  { id: 'knight',   name: '骑士',   color: 0x3f4436, headR: 30, shW: 136, scale: 0.96, tilt: 0,     dx: 12,  dy: 8,   rot: 0.018 },
  { id: 'nun',      name: '修女',   color: 0x52322e, headR: 34, shW: 80,  scale: 1.02, tilt: 0,     dx: -6,  dy: -10, rot: 0.008 },
  { id: 'king',     name: '国王',   color: 0x504a2a, headR: 40, shW: 146, scale: 1.12, tilt: 0,     dx: 44, dy: 4,   rot: -0.02 },
  { id: 'wanderer', name: '流浪者', color: 0x32414d, headR: 32, shW: 92,  scale: 0.92, tilt: 0.075, dx: -12, dy: -8,  rot: 0.022 },
  { id: 'doctor',   name: '医者',   color: 0x45303c, headR: 32, shW: 86,  scale: 0.98, tilt: 0,     dx: 7,   dy: 10,  rot: -0.006 },
];

// 玩家座位模型：P1=人类玩家，P2-P6=AI（对应六立绘；P7 为扩展席位预留——当前画面
// 无第 7 立绘，仅出现在任务表与进度条语境）。accent=固定低饱和识别色（辅助，
// 编号才是主识别）；角色名仍走 parchment 色系，只有 P# 与小 marker 用 accent。
export const SEATS = [
  { seatId: 'P1', characterId: 'prophet',  name: '先知',   isHuman: true,  accent: 0x9a7a3a }, // muted warm gold
  { seatId: 'P2', characterId: 'knight',   name: '骑士',   isHuman: false, accent: 0x5a6a52 }, // desat iron green
  { seatId: 'P3', characterId: 'nun',       name: '修女',   isHuman: false, accent: 0x7a3a34 }, // oxblood
  { seatId: 'P4', characterId: 'king',     name: '国王',   isHuman: false, accent: 0x8a6a3a }, // dirty amber
  { seatId: 'P5', characterId: 'wanderer', name: '流浪者', isHuman: false, accent: 0x5a6672 }, // cold blue-gray
  { seatId: 'P6', characterId: 'doctor',   name: '医者',   isHuman: false, accent: 0x6a4a5a }, // muted plum
  { seatId: 'P7', characterId: null,       name: '侍从',   isHuman: false, accent: 0x4a6a6a }, // desat teal（预留）
];

// 7 人局五轮任务表（进度条展示用）：每轮所需人数 / 失败票数
export const MISSIONS = [
  { round: 1, required: 2, failVotes: 1 },
  { round: 2, required: 3, failVotes: 1 },
  { round: 3, required: 3, failVotes: 1 },
  { round: 4, required: 4, failVotes: 2 },
  { round: 5, required: 4, failVotes: 2 },
];

// 卡牌：底部中心枢轴旋转；rot=度数，scale/raise/z 逐卡控制（中央卡最高 z）
export const CARDS = [
  { name: '侦察', cost: 1, rot: -8, scale: 0.97,  raise: 0,  z: 3 },
  { name: '劝说', cost: 1, rot: -4, scale: 1.0,   raise: 5,  z: 4 },
  { name: '质疑', cost: 2, rot: 0,  scale: 1.0,   raise: 16, z: 5 },
  { name: '挑拨', cost: 1, rot: 4,  scale: 1.0,   raise: 5,  z: 4 },
  { name: '沉默', cost: 0, rot: 8,  scale: 0.97,  raise: 0,  z: 3 },
];
