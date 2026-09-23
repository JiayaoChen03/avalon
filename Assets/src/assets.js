// 真实资产加载器：按清单直接 Assets.load（不逐扩展名探测）
// 探测"缺失文件"会触发 vite SPA 回退（200 text/html），
// 在无头等受限环境还会拖死网络空闲判定——清单驱动最稳
// 注意：所有网络加载必须发生在 WebGL 初始化之前
import { Assets } from 'pixi.js';

// public/ 目录映射为站点根路径
const ENV_DIR = '/assets/environment';
const CHAR_DIR = '/assets/characters';

// 环境层资产清单：name -> 实际扩展名（生成后维护此表）
const ENV_MANIFEST = {
  sky_base: 'jpeg',
  cloud_far_01: 'png',
  cloud_far_02: 'png',
  cloud_far_03: 'png',
  cloud_mid_01: 'png',
  cloud_mid_02: 'png',
  eldritch_eye: 'png',
  eldritch_pupil: 'png',
  tentacle_far_01: 'png',
  tentacle_far_02: 'png',
  tentacle_far_03: 'png',
  castle_far: 'png',
  city_mid: 'png',
  bridge_mid: 'png',
  foreground_left: 'png',
  foreground_right: 'png',
  table_altar: 'jpeg',
};

async function loadOne(name, ext, dir = ENV_DIR) {
  const url = `${dir}/${name}.${ext}`;
  try {
    const t = await Assets.load(url);
    console.warn('[assets] ok', name);
    return t;
  } catch (err) {
    console.warn('[assets] fail', name, String(err));
    return null; // 单个资产失败不阻塞场景，回退占位块
  }
}

export async function loadEnvironmentSet() {
  const names = Object.keys(ENV_MANIFEST);
  const texs = await Promise.all(names.map((n) => loadOne(n, ENV_MANIFEST[n])));
  const by = {};
  names.forEach((n, i) => {
    by[n] = texs[i];
  });
  return {
    skyTex: by.sky_base,
    cloudFarTexs: [by.cloud_far_01, by.cloud_far_02, by.cloud_far_03].filter(Boolean),
    cloudMidTexs: [by.cloud_mid_01, by.cloud_mid_02].filter(Boolean),
    eyeTex: by.eldritch_eye,
    pupilTex: by.eldritch_pupil,
    tentacleTexs: [by.tentacle_far_01, by.tentacle_far_02, by.tentacle_far_03].filter(Boolean),
    castleTex: by.castle_far,
    cityTex: by.city_mid,
    bridgeTex: by.bridge_mid,
    fgLeftTex: by.foreground_left,
    fgRightTex: by.foreground_right,
    tableFrontTex: by.table_altar,
    charTexs: await loadCharacterSet(),
    cardTexs: await loadCardsSet(),
  };
}

// 角色立绘清单（抠图+裁剪已完成的透明 PNG，见 .codely-cli/char-key.mjs）
const CHAR_MANIFEST = {
  prophet: 'png',
  knight: 'png',
  nun: 'png',
  king: 'png',
  wanderer: 'png',
  doctor: 'png',
};

async function loadCharacterSet() {
  const names = Object.keys(CHAR_MANIFEST);
  const texs = await Promise.all(names.map((n) => loadOne(n, CHAR_MANIFEST[n], CHAR_DIR)));
  const by = {};
  names.forEach((n, i) => {
    by[n] = texs[i];
  });
  return by;
}

// 卡面插画清单（DD 手绘风，内框比例 164:232 ≈ 480:680 生成）
const CARD_DIR = '/assets/cards';
const CARDS_MANIFEST = {
  scout: 'jpeg',     // 侦察
  persuade: 'jpeg',  // 劝说
  question: 'jpeg',  // 质疑
  provoke: 'jpeg',   // 挑拨
  silence: 'jpeg',   // 沉默
};

export async function loadCardsSet() {
  const names = Object.keys(CARDS_MANIFEST);
  const texs = await Promise.all(names.map((n) => loadOne(n, CARDS_MANIFEST[n], CARD_DIR)));
  const by = {};
  names.forEach((n, i) => {
    by[n] = texs[i];
  });
  return by;
}
