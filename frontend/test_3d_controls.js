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
  'character-home-buttons', 'character-edit-buttons', 'character-adjust-toggle', 'character-watermark-toggle',
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
assert.strictEqual(watermarkButton.textContent, '去除水印');
assert.strictEqual(watermarkButton.attributes.get('aria-pressed'), 'false');
watermarkButton.listeners.get('click')({ preventDefault() {}, stopPropagation() {} });
assert.deepStrictEqual(JSON.parse(JSON.stringify(sent)), [
  ['set-config', { key: 'miku-hide-model-watermark', val: true }],
  ['watermark-visibility-changed', true],
]);
assert.strictEqual(watermarkButton.textContent, '恢复水印');
assert.strictEqual(watermarkButton.attributes.get('aria-pressed'), 'true');

received.get('watermark-visibility-changed')({}, false);
assert.strictEqual(watermarkButton.textContent, '去除水印');
assert.strictEqual(watermarkButton.attributes.get('aria-pressed'), 'false');

const indexHtml = fs.readFileSync(path.join(__dirname, 'index.html'), 'utf8');
assert.match(indexHtml, /id="character-adjust-toggle"[\s\S]*?title="编辑模式"/);
assert.match(indexHtml, /id="character-watermark-toggle"/);
assert.match(indexHtml, /id="character-home-buttons"/);
assert.match(indexHtml, /id="character-edit-buttons"/);
assert.match(indexHtml, /id="character-tracking-status"/);
assert.match(runtimeSource, /miku-face-tracking-toggle/);
assert.match(runtimeSource, /mouse-tracking-subscription/);
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
  /\.has-live2d\.is-adjusting \.character-edit-buttons:not\(:empty\)/,
  'edit buttons must only be visible inside edit mode',
);
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
