const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

class MockClassList {
  constructor() {
    this.values = new Set();
  }

  add(name) { this.values.add(name); }
  remove(name) { this.values.delete(name); }
  toggle(name, force) {
    if (force === undefined) {
      if (this.values.has(name)) this.values.delete(name);
      else this.values.add(name);
      return this.values.has(name);
    }
    if (force) this.values.add(name);
    else this.values.delete(name);
    return force;
  }
}

class MockElement {
  constructor() {
    this.attributes = new Map();
    this.classList = new MockClassList();
    this.listeners = new Map();
    this.textContent = '';
    this.title = '';
    this.children = [];
  }

  addEventListener(type, listener) { this.listeners.set(type, listener); }
  setAttribute(name, value) { this.attributes.set(name, String(value)); }
  appendChild(child) { this.children.push(child); return child; }
  replaceChildren(...children) { this.children = children; }
}

const elementIds = [
  'miku-3d-canvas', 'miku-3d-layer', 'miku-display', 'miku-3d-status',
  'character-home-buttons', 'character-edit-buttons', 'character-edit-feature-buttons', 'character-adjust-toggle', 'character-watermark-toggle',
  'character-adjust-dismiss', 'character-tracking-status',
];
const elements = Object.fromEntries(elementIds.map((id) => [id, new MockElement()]));
const sent = [];
const received = new Map();
const ipc = {
  sendSync(channel, key) {
    assert.strictEqual(channel, 'get-config');
    if (key === 'miku-hide-model-watermark') return false;
    if (key === 'miku-character-view') return {};
    if (key === 'miku-character-tracking') return {};
    assert.fail(`Unexpected config key: ${key}`);
  },
  send(channel, payload) { sent.push([channel, payload]); },
  on(channel, listener) { received.set(channel, listener); },
};
const runtimeSource = fs.readFileSync(path.join(__dirname, '3d_runtime.js'), 'utf8');
const context = {
  console,
  URL,
  performance: { now: () => 0 },
  fetch: async () => ({ ok: false }),
  document: {
    getElementById: (id) => elements[id] || null,
    createElement: () => new MockElement(),
  },
  CustomEvent: class CustomEvent { constructor(type, options) { this.type = type; this.detail = options?.detail; } },
  window: {
    miku: { ipc },
    clearTimeout() {},
    setTimeout() { return 1; },
    setInterval() { return 1; },
    dispatchEvent() {},
    screenX: 0,
    screenY: 0,
  },
};
vm.runInNewContext(runtimeSource, context, { filename: '3d_runtime.js' });

const watermarkButton = elements['character-watermark-toggle'];
assert.strictEqual(watermarkButton.textContent, '🖼️');
assert.strictEqual(watermarkButton.attributes.get('aria-pressed'), 'true');
assert.strictEqual(watermarkButton.classList.values.has('is-off'), false);
watermarkButton.listeners.get('click')({ preventDefault() {}, stopPropagation() {} });
assert.deepStrictEqual(JSON.parse(JSON.stringify(sent)), [
  ['set-config', { key: 'miku-hide-model-watermark', val: true }],
  ['watermark-visibility-changed', true],
]);
assert.strictEqual(watermarkButton.textContent, '🖼️');
assert.strictEqual(watermarkButton.attributes.get('aria-pressed'), 'false');
assert.strictEqual(watermarkButton.classList.values.has('is-off'), true);
received.get('watermark-visibility-changed')({}, false);
assert.strictEqual(watermarkButton.attributes.get('aria-pressed'), 'true');
assert.strictEqual(watermarkButton.classList.values.has('is-off'), false);

const indexHtml = fs.readFileSync(path.join(__dirname, 'index.html'), 'utf8');
assert.match(indexHtml, /id="character-adjust-toggle"[\s\S]*?title="编辑模式"/);
assert.match(indexHtml, /id="character-watermark-toggle"/);
assert.match(indexHtml, /id="character-home-buttons"/);
assert.match(indexHtml, /id="character-edit-buttons"/);
assert.match(indexHtml, /id="character-edit-feature-buttons"/);
assert.match(indexHtml, /id="character-tracking-status"/);
assert.match(runtimeSource, /miku-face-tracking-toggle/);
assert.match(runtimeSource, /mouse-tracking-subscription/);
assert.match(runtimeSource, /bodyEnabled/);
assert.match(runtimeSource, /typeof value\.faceEnabled === 'boolean'[\s\S]*?bodyEnabled = value\.faceEnabled/, 'v1.2.2 faceEnabled preferences must migrate to bodyEnabled');
const mainSource = fs.readFileSync(path.join(__dirname, 'main.js'), 'utf8');
assert.match(mainSource, /typeof state\.bodyEnabled === 'boolean'[\s\S]*?typeof state\.faceEnabled === 'boolean'[\s\S]*?bodyEnabled,/, 'main-process config sanitizer must normalize legacy faceEnabled to bodyEnabled');
assert.match(runtimeSource, /editFeatureButtons\.appendChild\(watermarkToggle\)[\s\S]*?createFeatureButton\('🖱'[\s\S]*?createFeatureButton\('🫣'/, 'feature button order must be watermark, mouse, body');
assert.match(runtimeSource, /faceFeatureEnabled/);
assert.doesNotMatch(runtimeSource, /preference\.faceEnabled/);
assert.match(runtimeSource, /createFeatureButton\('🖱', '鼠标追踪'/);
assert.match(runtimeSource, /createFeatureButton\('🫣', '肢体追踪'/);
assert.match(runtimeSource, /trackingStatus\.textContent = preference\.bodyEnabled[\s\S]*?当前追踪：肢体追踪/);
assert.match(runtimeSource, /modelDragActive = true;[\s\S]*?syncMouseTrackingSubscription\(\)/);
assert.match(runtimeSource, /modelDragActive = false;[\s\S]*?syncMouseTrackingSubscription\(\)/);
assert.doesNotMatch(runtimeSource, /resolveTrackingSource\(now\)[\s\S]{0,250}if \(!adjustmentEnabled\)/, 'edit mode must not disable the tracking arbiter');
assert.match(runtimeSource, /const FACE_LOSS_FALLBACK_MS = 3000/);
assert.match(runtimeSource, /now - faceLastValidAt < FACE_LOSS_FALLBACK_MS/);
assert.match(runtimeSource, /const FACE_RECOVERY_STABLE_MS = 400/);
assert.match(runtimeSource, /now - faceValidSince >= FACE_RECOVERY_STABLE_MS/);
assert.match(runtimeSource, /function mirroredFaceSemanticTarget\(payload\)/);
assert.match(runtimeSource, /headX: -payload\.head\?\.x/);
assert.match(runtimeSource, /headY: -payload\.head\?\.y/);
assert.match(runtimeSource, /headZ: -payload\.head\?\.z/);
assert.match(runtimeSource, /eyeX: -payload\.eyes\?\.x/);
assert.match(runtimeSource, /eyeY: payload\.eyes\?\.y/);
assert.match(runtimeSource, /eyeLOpen: payload\.eyes\?\.rightOpen/);
assert.match(runtimeSource, /eyeROpen: payload\.eyes\?\.leftOpen/);
assert.match(runtimeSource, /mouthX: payload\.mouth\?\.x/);
assert.match(runtimeSource, /modelReady: Boolean\(live2dModel && activeModelConfig\?\.version === 1\)/);
assert.match(runtimeSource, /暂未检测到人脸，3 秒后回退鼠标/);
assert.match(
  runtimeSource,
  /resetParameters[\s\S]*?applyTrackingOverrides\(coreModel\)[\s\S]*?activeActionParameters/,
  'tracking must be written after resets and before explicit action overrides',
);
assert.match(
  runtimeSource,
  /const width = Math\.max\(layer\?\.clientWidth \|\| canvas\.clientWidth, 1\)/,
  'Live2D resize must use the viewport instead of Pixi\'s stale inline canvas width',
);
assert.match(
  runtimeSource,
  /canvas\.style\.width = '100%'/,
  'Live2D canvas must remain responsive after Pixi renderer resize',
);
const styleSource = fs.readFileSync(path.join(__dirname, 'style.css'), 'utf8');
assert.match(
  styleSource,
  /\.miku-3d-layer canvas[\s\S]*?width: 100% !important;[\s\S]*?height: 100% !important;/,
  'CSS must prevent Pixi inline dimensions from exposing the old canvas boundary',
);
assert.match(
  styleSource,
  /\.has-live2d:not\(\.is-adjusting\) \.character-home-buttons:not\(:empty\)/,
  'home buttons must only be visible outside edit mode',
);
assert.match(
  styleSource,
  /\.has-live2d\.is-adjusting \.character-edit-buttons:not\(:empty\),[\s\S]*?\.character-edit-feature-buttons:not\(:empty\)/,
  'edit buttons and model features must only be visible inside edit mode',
);
assert.match(styleSource, /\.character-edit-feature-buttons[\s\S]*?flex-direction: column/);
assert.match(styleSource, /\.character-model-button\.is-off::after[\s\S]*?background: #e53935[\s\S]*?rotate\(-45deg\)/);
assert.match(styleSource, /\.character-tracking-status[\s\S]*?right: 8px;[\s\S]*?bottom: 8px;/);
assert.match(
  runtimeSource,
  /activeModelConfig\.actions\?\.\[action\]/,
  'actions must come from the selected model configuration',
);
assert.match(
  runtimeSource,
  /renderConfiguredButtons\(homeButtons, activeModelConfig\.homeButtons\)/,
  'home buttons must render on their own surface',
);
assert.match(
  runtimeSource,
  /renderConfiguredButtons\(editButtons, activeModelConfig\.editButtons\)/,
  'edit buttons must render on their own surface',
);
assert.match(
  runtimeSource,
  /definition\.function === 'action' && performAction\(definition\.action\)/,
  'configured buttons must call the loaded model action directly',
);
assert.match(
  runtimeSource,
  /coreModel\.update = \(\.\.\.args\) => \{\s*applyLive2DOverrides\(\);\s*return updateCoreModel/,
  'watermark and action parameters must be applied before Cubism updates drawables',
);
assert.match(
  runtimeSource,
  /Live2DModel\.from\(manifest, \{\s*autoInteract: false,/,
  'Live2D pointer focus must stay disabled unless a model explicitly opts in',
);
assert.doesNotMatch(
  runtimeSource,
  /focusController\.(?:x|y)\s*=/,
  'the app must not silently convert pointer movement into model tracking',
);
assert.doesNotMatch(runtimeSource, /XUANBAO|LIVE2D_ACTIONS|character-feed-toggle/);

const rendererSource = fs.readFileSync(path.join(__dirname, 'renderer.js'), 'utf8');
assert.match(rendererSource, /message\.type === 'set_face_tracking'[\s\S]*?staleIndex = pendingBackendMessages\.findIndex[\s\S]*?configSynced/, 'face tracking startup state must be coalesced until config sync');
assert.match(rendererSource, /if \(trackingState\?\.modelReady\)[\s\S]*?set_face_tracking/, 'backend-ready handshake must wait for Live2D model capability');
assert.match(
  rendererSource,
  /is3dMode\(\) && window\.Miku3D\?\.hasMusicAction\?\.\(\) === true/,
  '3D sing visuals must depend on the selected model music capability',
);
assert.match(
  rendererSource,
  /miku3dLayer\?\.classList\.remove\('active'\);[\s\S]*?playSingStateVideo\(playing \? SING_VIDEO : PAUSE_VIDEO\)/,
  'models without a sing action must fall back to media-mode videos',
);
console.log('frontend 3D edit controls tests passed');
