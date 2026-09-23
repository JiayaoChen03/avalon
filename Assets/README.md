# Avalon — Beneath the Hollow Crown

DD（Darkest Dungeon）风格围桌卡牌游戏的 PixiJS 场景骨架。固定 **1536×1024** 设计坐标系。当前为**占位块阶段**：全部 18 层、视差、动效、屏幕滤镜已跑通，之后逐批用 `public/assets/` 的真实 webp 替换占位块即可。布局规格（桌子/对话面板/手牌/派遣区/背景焦点坐标）集中在 `src/config.js` 的 `LAYOUT`。

## 运行

```bash
npm install
npm run dev      # http://localhost:5173
npm run build    # 产物 dist/
```

## 前后端联调

Pixi 场景现在通过同一套 Python `GameSession` 接入后端。后端默认使用**离线联调模型**，不会调用外部 API；规则、身份、投票、任务结果和公开记录仍由 Python 引擎决定。

先在仓库根目录启动后端：

```bash
PYTHONPATH=. .venv/bin/python -m avalon.web_server --mode offline --port 8765
```

再在 `Assets/` 启动前端：

```bash
npm run dev
```

打开 `http://localhost:5173/`，右上角显示「离线联调」即已连接。需要使用真实模型时，确认 `.env` 已配置后，将后端启动参数改为 `--mode live`；前端协议不变。浏览器每个操作都携带 revision 和 request ID，断线重试不会重复推进对局。

## 分层（cameraRoot 按 zIndex 排序）

| z | 层 | 视差 | 对应资产 |
|---|---|---|---|
| 30 | sky | 0 | environment/sky_base |
| 40 | cloudsFar | 0.04 | environment/clouds_far |
| 50 | cloudsMid | 0.07 | environment/clouds_mid |
| 60 | eye | 0.10 | environment/eldritch_eye |
| 70 | tentacles | 0.12 | environment/tentacle_far_01~03 |
| 80 | castle | 0.18 | environment/castle_far |
| 90 | midground | 0.28 | environment/city_mid + bridge_mid |
| 100 | fgEnv | 0.45 | environment/foreground_left/right |
| 110 | tableBack | — | table/table_base + table_shadow |
| 120 | characters | — | characters/*/body |
| 130 | tableFront | — | table/parchment + props + candles |
| 140 | fgFx | — | fx/smoke、fx/flame、fx/ash |
| 150 | labels | — | ui/nameplate |
| 160 | hud | — | ui/panel_dialogue、panel_mission、ap_orb |
| 170 | cards | — | cards/frame_* + illustrations/ |
| 180 | drag | — | 拖拽中的卡（运行时） |
| 190 | modal | — | 弹窗/浮层 |
| 195 | corruption | — | 全屏腐化脉冲（运行时） |

桌子遮挡是**三明治**：tableBack(110) → characters(120) → tableFront(130)，角色下半身被桌沿遮住。

## 调试操作

- 鼠标移动 —— 视差（叠加自动呼吸漂移）
- 点击 / `S` —— 屏幕震动
- `K` —— 腐化红光脉冲
- `L` —— 显隐各层标签（标签会随视差移动，可直观感受层间相对运动）

## 目录

```
public/assets/   真实资产的家（已按层建好目录）
src/config.js    1536×1024 设计坐标 / LAYOUT 布局规格 / 层定义 / 角色配置 —— 全部调参入口
src/main.js      装配入口（资产预加载 → WebGL 初始化 → 建场景）
src/assets.js    资产加载器：按 ENV_MANIFEST 清单加载，缺失自动回退占位块
src/placeholders.js  各层占位视觉 + 逐层动效
src/Parallax.js  视差控制器
src/Shake.js     屏幕震动
src/ScreenFx.js  暗角/噪点/调色滤镜 + 腐化脉冲
```

## 资产替换流程

1. 生成/放入资产到 `public/assets/environment/`（当前已接入：sky_base.jpeg + cloud_far_01~03.png + cloud_mid_01~02.png）
2. 在 `src/assets.js` 的 `ENV_MANIFEST` 登记文件名与扩展名
3. `placeholders.js` 对应 builder 自动改用真贴图（缺失层继续用占位块）

注意：所有资产网络加载必须发生在 WebGL 初始化之前（main.js 的 start() 顺序），不要挪到场景构建之后。
