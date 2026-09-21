// 视差控制器：鼠标偏移（平滑跟随）+ 场景自动呼吸漂移，按层系数偏移环境层

import { LAYERS } from './config.js';

export class Parallax {
  constructor(layerMap) {
    this.entries = LAYERS
      .filter((d) => d.parallax !== undefined)
      .map((d) => ({ container: layerMap.get(d.id), factor: d.parallax }));
    this.x = 0; // 已平滑的鼠标偏移
    this.y = 0;
    this.tx = 0; // 目标
    this.ty = 0;
  }

  setTarget(nx, ny) {
    this.tx = Math.max(-1, Math.min(1, nx));
    this.ty = Math.max(-1, Math.min(1, ny));
  }

  update(t) {
    this.x += (this.tx - this.x) * 0.04;
    this.y += (this.ty - this.y) * 0.04;
    const driftX = Math.sin(t * 0.00008) * 26; // 缓慢呼吸漂移，周期约 78s
    const driftY = Math.cos(t * 0.00005) * 12;
    const ox = driftX + this.x * 64;
    const oy = driftY + this.y * 36;
    for (const e of this.entries) {
      e.container.position.set(ox * e.factor, oy * e.factor);
    }
  }
}
