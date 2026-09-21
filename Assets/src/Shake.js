// 屏幕震动：trigger 后随机偏移 cameraRoot，gsap 负责衰减

import gsap from 'gsap';

export class Shake {
  constructor(cameraRoot) {
    this.cameraRoot = cameraRoot;
    this.amp = 0;
  }

  trigger(strength = 16, duration = 0.55) {
    this.amp = strength;
    gsap.to(this, { amp: 0, duration, ease: 'power2.out', overwrite: true });
  }

  update() {
    if (this.amp < 0.05) {
      this.cameraRoot.position.set(0, 0);
      return;
    }
    this.cameraRoot.position.set(
      (Math.random() * 2 - 1) * this.amp,
      (Math.random() * 2 - 1) * this.amp,
    );
  }
}
