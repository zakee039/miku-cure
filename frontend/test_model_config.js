const assert = require('assert');
const fs = require('fs');
const path = require('path');
const { loadModelConfig, sanitizeModelConfig } = require('./model_config');

const modelsRoot = path.join(__dirname, '..', 'miku', 'models');
const cases = [
  { folder: 'miku', homeButton: 'feed', hasWatermark: true },
  { folder: '樱花miku', homeButton: 'blush', hasWatermark: true },
];

for (const testCase of cases) {
  const directory = path.join(modelsRoot, testCase.folder);
  const config = loadModelConfig(directory);
  assert.strictEqual(config.version, 1, `${testCase.folder} must have a versioned config`);
  assert.deepStrictEqual(config.homeButtons.map((button) => button.action), [testCase.homeButton]);
  assert.deepStrictEqual(config.editButtons, []);
  assert.strictEqual(Boolean(config.watermark), testCase.hasWatermark);
  assert.strictEqual(config.tracking.mouse.supported, true);
  assert.strictEqual(config.tracking.face.supported, true);
  assert.strictEqual(config.tracking.face.parameters.headX.id, 'ParamAngleX');
  assert.strictEqual(config.tracking.face.parameters.eyeX.scale, -1);
  if (testCase.folder === 'miku') {
    assert.deepStrictEqual(config.watermark.partIds, ['Part18', 'Part17']);
  }

  const expressionNames = new Set(fs.readdirSync(directory)
    .filter((name) => name.endsWith('.exp3.json'))
    .map((name) => name.replace(/\.exp3\.json$/i, '')));
  for (const [action, definition] of Object.entries(config.actions)) {
    assert.ok(expressionNames.has(definition.expression),
      `${testCase.folder}.${action} references missing expression ${definition.expression}`);
  }
}

const sakura = loadModelConfig(path.join(modelsRoot, '樱花miku'));
assert.strictEqual(sakura.actions.cry.expression, '哭');
assert.strictEqual(sakura.actions.blush.expression, '脸红');
assert.deepStrictEqual(sakura.actions.blush.parameters, { Param130: 1 });
assert.ok(!sakura.actions.feed, 'Sakura Miku must not inherit the normal Miku feed action');
assert.ok(!sakura.actions.size, 'Sakura Miku must not automatically switch into its QQ chibi form');
assert.ok(!sakura.interactions.doubleClick, 'Sakura Miku double-click must not trigger the QQ chibi form');
assert.ok(!sakura.emotions.surprise, 'Surprise detection must not trigger the QQ chibi form');
assert.ok(!sakura.interactions.music, 'Sakura Miku must not inherit an unavailable sing action');
assert.deepStrictEqual(sakura.watermark.parameterIds, []);
assert.deepStrictEqual(sakura.watermark.partIds, ['Part18', 'Part17']);
assert.strictEqual(sakura.watermark.hiddenValue, 0);
assert.strictEqual(sakura.watermark.visibleValue, 1);

const sanitized = sanitizeModelConfig({
  version: 1,
  actions: {
    safe: { expression: '脸红', duration: 1000, parameters: { Param130: 1 } },
    '<script>': { expression: 'bad' },
  },
  homeButtons: [
    { id: 'safe', function: 'action', action: 'safe', icon: '🌸', title: '安全按钮' },
    { id: 'script', function: 'javascript', action: 'safe', icon: 'x', title: '不允许' },
    { id: 'missing', function: 'action', action: 'missing', icon: 'x', title: '不存在' },
  ],
  editButtons: [
    { id: 'edit-safe', function: 'action', action: 'safe', icon: '🌸', title: '编辑动作' },
  ],
  watermark: { partIds: ['Part18', '../bad'], hiddenValue: -5, visibleValue: 8 },
  tracking: {
    mouse: { supported: true, eyeStrength: 0.7, headStrength: 99, bodyStrength: 0.1 },
    face: {
      supported: true,
      parameters: {
        headX: { id: 'ParamAngleX', scale: 30, offset: 0, min: -30, max: 30 },
        script: { id: 'ParamBad', scale: 1, offset: 0, min: -1, max: 1 },
        eyeX: { id: '../bad', scale: 1, offset: 0, min: -1, max: 1 },
      },
    },
  },
});
assert.deepStrictEqual(Object.keys(sanitized.actions), ['safe']);
assert.deepStrictEqual(sanitized.homeButtons.map((button) => button.id), ['safe']);
assert.deepStrictEqual(sanitized.editButtons.map((button) => button.id), ['edit-safe']);
assert.deepStrictEqual(sanitized.watermark.partIds, ['Part18']);
assert.strictEqual(sanitized.watermark.hiddenValue, 0);
assert.strictEqual(sanitized.watermark.visibleValue, 1);
assert.strictEqual(sanitized.tracking.mouse.eyeStrength, 0.7);
assert.strictEqual(sanitized.tracking.mouse.headStrength, 0.45);
assert.deepStrictEqual(Object.keys(sanitized.tracking.face.parameters), ['headX']);
assert.deepStrictEqual(sanitizeModelConfig({ version: 2, actions: {} }), {});

const legacy = sanitizeModelConfig({
  version: 1,
  actions: { safe: { expression: '脸红' } },
  buttons: [{ id: 'safe', function: 'action', action: 'safe', icon: 'x', title: '旧配置' }],
});
assert.deepStrictEqual(legacy.homeButtons.map((button) => button.id), ['safe']);
assert.deepStrictEqual(legacy.editButtons, []);

console.log('frontend model configuration tests passed');
