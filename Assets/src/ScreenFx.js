// Screen FX：挂在 stage 根上的滤镜管线（调色 / vignette / 噪点）
// 腐化脉冲为独立的全屏叠层（z195 corruption 层），不占用滤镜
// 注：pixi-filters 6.x 已移除 VignetteFilter，此处手写等价 shader

import gsap from 'gsap';
import { Filter, GlProgram, Graphics, NoiseFilter, UniformGroup, defaultFilterVert } from 'pixi.js';
import { AdjustmentFilter } from 'pixi-filters';
import { DESIGN_W, DESIGN_H, BLEED } from './config.js';

const VIGNETTE_FRAG = `
in vec2 vTextureCoord;
out vec4 finalColor;
uniform sampler2D uTexture;
uniform float uSize;
uniform float uStrength;

void main(void) {
  vec4 color = texture(uTexture, vTextureCoord);
  float d = distance(vTextureCoord, vec2(0.5)) * 2.0;
  float vig = smoothstep(uSize, 1.0, d) * uStrength;
  color.rgb *= 1.0 - vig;
  finalColor = color;
}
`;

export class ScreenFx {
  constructor(stage, corruptionLayer) {
    this.adjust = new AdjustmentFilter({
      saturation: 0.85,
      contrast: 1.07,
      brightness: 0.96,
      gamma: 1.03,
      red: 1.05,
      green: 0.97,
      blue: 1.02,
    });
    this.vignette = new Filter({
      glProgram: GlProgram.from({
        vertex: defaultFilterVert,
        fragment: VIGNETTE_FRAG,
        name: 'vignette-filter',
      }),
      resources: {
        vignetteUniforms: new UniformGroup({
          uSize: { value: 0.55, type: 'f32' },
          uStrength: { value: 0.6, type: 'f32' },
        }),
      },
    });
    this.noise = new NoiseFilter({ noise: 0.05 });
    stage.filters = [this.adjust, this.vignette, this.noise];

    this.overlay = new Graphics();
    this.overlay
      .rect(-BLEED, -BLEED, DESIGN_W + BLEED * 2, DESIGN_H + BLEED * 2)
      .fill(0x8a1016);
    this.overlay.alpha = 0;
    // 全屏覆盖层必须显式排除出命中测试：eventMode 默认 passive 会被
    // hitTestMoveRecursive 的 containsPoint 命中（stage.static 继承模式下
    // 返回空数组毒化 hitTestRecursive——pointerdown/up 永远到不了卡牌/角色）
    this.overlay.eventMode = 'none';
    corruptionLayer.addChild(this.overlay);
  }

  update() {
    // 每帧换 seed 让噪点颗粒动起来
    this.noise.seed = Math.random() * 1000;
  }

  corruptionPulse() {
    gsap.fromTo(
      this.overlay,
      { alpha: 0.42 },
      { alpha: 0, duration: 0.9, ease: 'power2.out', overwrite: true },
    );
  }
}
