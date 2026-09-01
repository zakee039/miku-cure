const assert = require('assert');
const fs = require('fs');
const Module = require('module');
const path = require('path');
const vm = require('vm');

let exposed;
const calls = [];
const electronMock = {
  contextBridge: {
    exposeInMainWorld(name, value) {
      assert.strictEqual(name, 'miku');
      exposed = value;
    },
  },
  ipcRenderer: {
    send: (...args) => calls.push(['send', ...args]),
    sendSync: (...args) => { calls.push(['sendSync', ...args]); return null; },
    invoke: (...args) => { calls.push(['invoke', ...args]); return Promise.resolve(null); },
    on: (...args) => calls.push(['on', ...args]),
    removeListener: (...args) => calls.push(['removeListener', ...args]),
  },
};
const originalLoad = Module._load;
Module._load = function(request, parent, isMain) {
  if (request === 'electron') return electronMock;
  return originalLoad.call(this, request, parent, isMain);
};
try {
  require('./preload');
} finally {
  Module._load = originalLoad;
}
assert.ok(exposed?.ipc);
assert.ok(exposed?.chat);
assert.strictEqual(exposed.chat.textMax, 4000);
assert.strictEqual(exposed.chat.hiddenContextMax, 8000);
assert.deepStrictEqual(exposed.chat.sanitizeRequest('x'.repeat(4001)), 'x'.repeat(4000));
assert.deepStrictEqual(
  exposed.chat.parseReply({ type: 'chat_reply', success: false, error: 'chat_failed' }),
  { ok: false, requestId: '', error: 'chat_failed', text: '' },
);
assert.throws(() => exposed.ipc.send('not-allowed'));
assert.throws(() => exposed.ipc.invoke('not-allowed'));
assert.throws(() => exposed.ipc.on('not-allowed', () => {}));
assert.doesNotThrow(() => exposed.ipc.send('mouse-tracking-subscription', true));
assert.doesNotThrow(() => exposed.ipc.on('cursor-screen-point', () => {}));

const renderers = ['renderer.js', 'settings_renderer.js', 'chat_renderer.js', 'report_renderer.js'];
const operationPattern = /ipcRenderer\.(sendSync|send|invoke|on)\(\s*['"]([^'"]+)['"]/g;
for (const filename of renderers) {
  const source = fs.readFileSync(path.join(__dirname, filename), 'utf8');
  let match;
  while ((match = operationPattern.exec(source))) {
    const [, operation, channel] = match;
    assert.doesNotThrow(() => {
      if (operation === 'on') exposed.ipc.on(channel, () => {});
      else exposed.ipc[operation](channel);
    }, `${filename}: preload must allow ${operation}(${channel})`);
  }
}
console.log('frontend preload contract tests passed');

const preloadSource = fs.readFileSync(path.join(__dirname, 'preload.js'), 'utf8');
assert.doesNotMatch(
  preloadSource,
  /require\(['"]\.\//,
  'sandboxed preload must not require relative modules',
);
assert.doesNotThrow(
  () => new vm.Script(
    fs.readFileSync(path.join(__dirname, 'i18n.js'), 'utf8')
      + '\n'
      + fs.readFileSync(path.join(__dirname, 'renderer.js'), 'utf8'),
  ),
  'i18n and the main renderer must not redeclare top-level lexical bindings',
);
