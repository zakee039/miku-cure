const assert = require('assert');
const fs = require('fs');
const path = require('path');
const {
  CHAT_HIDDEN_CONTEXT_MAX,
  CHAT_TEXT_MAX,
  endpointSignature,
  launcherHeartbeatSignature,
  normalizeApiBaseUrl,
  normalizeExternalUrl,
  parseChatReply,
  sanitizeApiRecord,
  sanitizeChatRequest,
  validateBackendDescriptor,
  validateLauncherHeartbeat,
} = require('./security');

const token = 'a'.repeat(64);
const now = 1_800_000_000_000;
const descriptor = {
  host: '127.0.0.1',
  port: 13939,
  ts: now,
  launch_session: 'session-1',
};
descriptor.signature = endpointSignature(
  token,
  descriptor.host,
  descriptor.port,
  descriptor.ts,
  descriptor.launch_session,
);
assert.deepStrictEqual(
  validateBackendDescriptor(descriptor, { token, launchSession: 'session-1', now }),
  { url: 'ws://127.0.0.1:13939', token, launchSession: 'session-1' },
);
assert.throws(() => validateBackendDescriptor({ ...descriptor, host: '192.168.1.2' }, { token, now }));
assert.throws(() => validateBackendDescriptor({ ...descriptor, signature: '0'.repeat(64) }, { token, now }));
assert.throws(() => validateBackendDescriptor(descriptor, { token, launchSession: 'other', now }));
assert.doesNotThrow(() => validateBackendDescriptor(descriptor, {
  token,
  launchSession: 'session-1',
  now: now + 30 * 24 * 60 * 60 * 1000,
}));
assert.strictEqual(normalizeExternalUrl('https://github.com/zakee039/miku-cure'), 'https://github.com/zakee039/miku-cure');
assert.strictEqual(normalizeExternalUrl('https://piapro.jp/t/KPU3'), 'https://piapro.jp/t/KPU3');
assert.strictEqual(normalizeExternalUrl('https://space.bilibili.com/131661224'), 'https://space.bilibili.com/131661224');
assert.strictEqual(normalizeExternalUrl('https://www.bilibili.com/video/BV1B1Mo67E3g'), 'https://www.bilibili.com/video/BV1B1Mo67E3g');
assert.strictEqual(normalizeExternalUrl('https://example.com/'), null);
assert.strictEqual(normalizeExternalUrl('javascript:alert(1)'), null);
assert.deepStrictEqual(
  sanitizeApiRecord({ id: '1', name: 'DeepSeek', baseUrl: 'https://api.deepseek.com/', apiKey: 'secret', models: ['m'] }),
  { id: '1', name: 'DeepSeek', baseUrl: 'https://api.deepseek.com', apiKey: 'secret', models: ['m'] },
);
assert.strictEqual(sanitizeApiRecord({ id: '1', name: 'bad', baseUrl: 'file:///tmp/x' }), null);
assert.strictEqual(normalizeApiBaseUrl('http://api.deepseek.com'), null);
assert.strictEqual(normalizeApiBaseUrl('http://127.0.0.1:11434/v1'), 'http://127.0.0.1:11434/v1');
assert.strictEqual(normalizeApiBaseUrl('http://[::1]:11434/v1'), 'http://[::1]:11434/v1');
assert.strictEqual(normalizeApiBaseUrl('https://user:pass@example.com'), null);
assert.strictEqual(normalizeApiBaseUrl('https://example.com/v1?token=x'), null);
assert.strictEqual(normalizeApiBaseUrl('https://example.com/v1#fragment'), null);

assert.strictEqual(CHAT_TEXT_MAX, 4000);
assert.strictEqual(CHAT_HIDDEN_CONTEXT_MAX, 8000);
assert.strictEqual(sanitizeChatRequest('x'.repeat(4001)).length, 4000);
assert.deepStrictEqual(
  sanitizeChatRequest({ text: 'hello', hidden_context: 'x'.repeat(8001) }),
  { text: 'hello', hidden_context: 'x'.repeat(8000) },
);
assert.strictEqual(sanitizeChatRequest('   '), null);
assert.strictEqual(sanitizeChatRequest({ text: 'hello', hidden_context: 123 }), null);
assert.deepStrictEqual(
  parseChatReply({ type: 'chat_reply', text: 'ok', request_id: 'request-1' }),
  { ok: true, requestId: 'request-1', error: '', text: 'ok' },
);
assert.deepStrictEqual(
  parseChatReply({ type: 'chat_reply', success: false, error: 'chat_failed', request_id: 'request-2' }),
  { ok: false, requestId: 'request-2', error: 'chat_failed', text: '' },
);
assert.deepStrictEqual(
  parseChatReply({ type: 'chat_reply', success: false, request_id: 'request-3' }),
  { ok: false, requestId: 'request-3', error: 'chat_failed', text: '' },
);
const heartbeat = {
  action: 'heartbeat',
  launch_session: 'session-1',
  ts: now,
};
heartbeat.signature = launcherHeartbeatSignature(token, heartbeat.launch_session, heartbeat.ts);
assert.strictEqual(
  validateLauncherHeartbeat(heartbeat, { token, launchSession: 'session-1', now, maxAgeMs: 5000 }),
  now,
);
const wrongSessionHeartbeat = { ...heartbeat, launch_session: 'other' };
wrongSessionHeartbeat.signature = launcherHeartbeatSignature(
  token,
  wrongSessionHeartbeat.launch_session,
  wrongSessionHeartbeat.ts,
);
assert.strictEqual(validateLauncherHeartbeat(
  wrongSessionHeartbeat,
  { token, launchSession: 'session-1', now, maxAgeMs: 5000 },
), null);
assert.strictEqual(validateLauncherHeartbeat(
  { ...heartbeat, signature: '0'.repeat(64) },
  { token, launchSession: 'session-1', now, maxAgeMs: 5000 },
), null);
const staleHeartbeat = { ...heartbeat, ts: now - 5001 };
staleHeartbeat.signature = launcherHeartbeatSignature(token, staleHeartbeat.launch_session, staleHeartbeat.ts);
assert.strictEqual(validateLauncherHeartbeat(
  staleHeartbeat,
  { token, launchSession: 'session-1', now, maxAgeMs: 5000 },
), null);
const futureHeartbeat = { ...heartbeat, ts: now + 1 };
futureHeartbeat.signature = launcherHeartbeatSignature(token, futureHeartbeat.launch_session, futureHeartbeat.ts);
assert.strictEqual(validateLauncherHeartbeat(
  futureHeartbeat,
  { token, launchSession: 'session-1', now, maxAgeMs: 5000 },
), null);

const rendererFiles = ['renderer.js', '3d_runtime.js', 'settings_renderer.js', 'chat_renderer.js', 'report_renderer.js'];
for (const filename of rendererFiles) {
  const source = fs.readFileSync(path.join(__dirname, filename), 'utf8');
  assert.ok(!/\brequire\s*\(/.test(source), `${filename} must not use require()`);
  assert.ok(!/\bprocess\s*\.|\b__dirname\b/.test(source), `${filename} must not access Node globals`);
}
const mainSource = fs.readFileSync(path.join(__dirname, 'main.js'), 'utf8');
const rendererSource = fs.readFileSync(path.join(__dirname, 'renderer.js'), 'utf8');
assert.match(mainSource, /nodeIntegration:\s*false/);
assert.match(mainSource, /contextIsolation:\s*true/);
assert.match(mainSource, /sandbox:\s*true/);
assert.match(mainSource, /mainWindow\.on\('resize',\s*scheduleAuxiliaryWindowPositions\)/);
assert.match(
  mainSource,
  /\[settingsWindow, reportWindow, chatWindow\]\.forEach\(\(window\) =>/,
);
assert.match(mainSource, /launcher_heartbeat\.json/);
assert.ok(!/powershell|\bwmic(?:\.exe)?\b/i.test(mainSource), 'launcher heartbeat monitor must not spawn shell helpers');
assert.ok(!/MIKU_LAUNCHER_(?:PID|STARTED_AT)/.test(mainSource));
assert.match(
  rendererSource,
  /if \(data\.type === 'chat_reply'\)[\s\S]*?chatProtocol\.parseReply\(data\)[\s\S]*?if \(!reply\.ok\)[\s\S]*?chat-send-failed/,
);
assert.match(mainSource, /text = sanitizeChatRequest\(text\)/);
const killBackendSource = mainSource.slice(
  mainSource.indexOf('function killBackend()'),
  mainSource.indexOf('const LAUNCHER_HEARTBEAT_TIMEOUT_MS'),
);
assert.ok(!killBackendSource.includes('backend.pid'), 'killBackend must not trust backend.pid');
assert.ok(!killBackendSource.includes('readFileSync'), 'killBackend must only use the tracked child process');
for (const filename of ['index.html', 'settings.html', 'chat.html', 'report.html']) {
  const html = fs.readFileSync(path.join(__dirname, filename), 'utf8');
  assert.match(html, /Content-Security-Policy/);
  assert.ok(!html.includes('fonts.googleapis.com'));
}
const i18nSource = fs.readFileSync(path.join(__dirname, 'i18n.js'), 'utf8');
const settingsHtml = fs.readFileSync(path.join(__dirname, 'settings.html'), 'utf8');
assert.ok(!i18nSource.includes('DeepSeek AI'));
assert.ok(!settingsHtml.includes('DeepSeek AI'));
assert.ok(!settingsHtml.includes('本系统没有服务器，不会上传任何数据'));
assert.match(settingsHtml, /OpenAI 兼容在线 LLM/);
const packageJson = require('./package.json');
const packageLock = require('./package-lock.json');
assert.deepStrictEqual(packageLock.packages[''].devDependencies, packageJson.devDependencies);
assert.strictEqual(packageJson.scripts.pack, undefined);
assert.strictEqual(packageJson.scripts.dist, undefined);
assert.match(packageJson.scripts['package:portable'], /\.\.\/package_portable\.ps1/);
assert.strictEqual(packageJson.devDependencies['electron-builder'], undefined);
assert.strictEqual(packageJson.build, undefined);
assert.ok(Array.isArray(packageJson.files) && packageJson.files.length > 0);
assert.ok(packageJson.files.includes('model_config.js'));
assert.ok(!packageJson.files.some((entry) => entry.includes('*') || entry.includes('.env') || entry.includes('.electron-cache')));
assert.match(
  fs.readFileSync(path.join(__dirname, '..', 'package_portable.ps1'), 'utf8'),
  /"main\.js", "model_config\.js", "preload\.js"/,
  'the portable package must include the model configuration reader',
);
assert.ok(!fs.existsSync(path.join(__dirname, '.env')));
assert.ok(!fs.existsSync(path.join(__dirname, '.electron-cache')));
console.log('frontend security tests passed');
