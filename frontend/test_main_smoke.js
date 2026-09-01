const assert = require('assert');
const crypto = require('crypto');
const { EventEmitter } = require('events');
const fs = require('fs');
const Module = require('module');
const os = require('os');
const path = require('path');
const { launcherHeartbeatSignature } = require('./security');

const windows = [];
const scheduledIntervals = [];
let quitCalls = 0;
let fakeNow = 1_800_000_000_000;
const realDateNow = Date.now;
const realSetInterval = global.setInterval;
const realClearInterval = global.clearInterval;
Date.now = () => fakeNow;
global.setInterval = (callback, delay) => {
  const handle = { callback, delay, active: true };
  scheduledIntervals.push(handle);
  return handle;
};
global.clearInterval = (handle) => {
  if (handle) handle.active = false;
};
const app = new EventEmitter();
app.isPackaged = false;
app.setAppUserModelId = () => {};
app.disableHardwareAcceleration = () => {};
app.getPath = () => __dirname;
app.getVersion = () => '1.2.2';
app.whenReady = () => Promise.resolve();
app.quit = () => { quitCalls += 1; };

class MockWebContents extends EventEmitter {
  constructor() {
    super();
    this.sent = [];
  }
  setWindowOpenHandler(handler) { this.windowOpenHandler = handler; }
  send(...args) { this.sent.push(args); }
  setZoomFactor() {}
  isLoading() { return false; }
}

class MockBrowserWindow extends EventEmitter {
  constructor(options) {
    super();
    this.options = options;
    this.webContents = new MockWebContents();
    this.destroyed = false;
    this.visible = options.show !== false;
    this.minimized = false;
    this.alwaysOnTop = options.alwaysOnTop === true;
    this.alwaysOnTopHistory = [];
    this.bounds = {
      x: options.x || 0,
      y: options.y || 0,
      width: options.width,
      height: options.height,
    };
    windows.push(this);
  }
  loadFile() { return Promise.resolve(); }
  isDestroyed() { return this.destroyed; }
  getBounds() { return { ...this.bounds }; }
  isVisible() { return this.visible; }
  isMinimized() { return this.minimized; }
  isAlwaysOnTop() { return this.alwaysOnTop; }
  setMenu() {}
  setBounds(bounds) { this.bounds = { ...this.bounds, ...bounds }; }
  setPosition(x, y) { this.bounds = { ...this.bounds, x, y }; }
  setAlwaysOnTop(value) {
    this.alwaysOnTop = value;
    this.alwaysOnTopHistory.push(value);
  }
  show() { this.visible = true; this.minimized = false; this.emit('show'); }
  showInactive() { this.visible = true; this.minimized = false; this.emit('show'); }
  hide() { this.visible = false; this.emit('hide'); }
  minimize() { this.minimized = true; this.emit('minimize'); }
  restore() { this.visible = true; this.minimized = false; this.emit('restore'); }
  focus() {}
  moveTop() {}
  close() { this.visible = false; this.destroyed = true; this.emit('closed'); }
}

const ipcMain = new EventEmitter();
ipcMain.handlers = new Map();
ipcMain.handle = (channel, handler) => ipcMain.handlers.set(channel, handler);
const defaultSession = {
  setPermissionCheckHandler(handler) { this.permissionCheckHandler = handler; },
  setPermissionRequestHandler(handler) { this.permissionRequestHandler = handler; },
};
const primaryDisplay = {
  workArea: { x: 0, y: 0, width: 1920, height: 1080 },
};
const leftDisplay = {
  workArea: { x: -1536, y: 222, width: 1536, height: 816 },
};
const electronMock = {
  app,
  BrowserWindow: MockBrowserWindow,
  ipcMain,
  safeStorage: { isEncryptionAvailable: () => false },
  screen: {
    getPrimaryDisplay: () => primaryDisplay,
    getAllDisplays: () => [leftDisplay, primaryDisplay],
    getDisplayNearestPoint: ({ x }) => x < 0 ? leftDisplay : primaryDisplay,
  },
  session: { defaultSession },
  shell: { openExternal: () => Promise.resolve() },
};

const testUserDir = fs.mkdtempSync(path.join(os.tmpdir(), 'miku-heartbeat-test-'));
const launchSession = 'smoke-session';
const wsToken = 'a'.repeat(64);
process.env.MIKU_EXTERNAL_BACKEND = '1';
process.env.MIKU_USER_DIR = testUserDir;
process.env.MIKU_LAUNCH_SESSION = launchSession;
process.env.MIKU_WS_TOKEN = wsToken;
process.env.MIKU_LAUNCH_DISPLAY_X = '-800';
process.env.MIKU_LAUNCH_DISPLAY_Y = '600';

function writeHeartbeat(ts) {
  const heartbeat = {
    action: 'heartbeat',
    launch_session: launchSession,
    ts,
  };
  heartbeat.signature = launcherHeartbeatSignature(wsToken, launchSession, ts);
  fs.writeFileSync(
    path.join(testUserDir, 'launcher_heartbeat.json'),
    JSON.stringify(heartbeat),
    'utf8',
  );
}
writeHeartbeat(fakeNow);

function writePetCommand(action, ts) {
  const command = {
    action,
    launch_session: launchSession,
    ts,
  };
  command.signature = crypto
    .createHmac('sha256', wsToken)
    .update(`${action}:${launchSession}:${ts}`)
    .digest('hex');
  fs.writeFileSync(path.join(testUserDir, 'pet_control.json'), JSON.stringify(command), 'utf8');
}

const originalLoad = Module._load;
Module._load = function(request, parent, isMain) {
  if (request === 'electron') return electronMock;
  return originalLoad.call(this, request, parent, isMain);
};
require('./main');
Module._load = originalLoad;

setImmediate(() => {
  assert.strictEqual(windows.length, 1);
  const petWindow = windows[0];
  assert.strictEqual(
    petWindow.options.x,
    -1516,
    'pet on the left monitor should start at its outer edge, away from the screen seam',
  );
  assert.strictEqual(petWindow.options.y, 810, 'pet should use launcher-display work area');
  assert.deepStrictEqual(
    {
      nodeIntegration: windows[0].options.webPreferences.nodeIntegration,
      contextIsolation: windows[0].options.webPreferences.contextIsolation,
      sandbox: windows[0].options.webPreferences.sandbox,
      webSecurity: windows[0].options.webPreferences.webSecurity,
    },
    { nodeIntegration: false, contextIsolation: true, sandbox: true, webSecurity: true },
  );
  assert.strictEqual(typeof windows[0].webContents.windowOpenHandler, 'function');
  assert.strictEqual(windows[0].listenerCount('resize'), 1);
  assert.strictEqual(typeof defaultSession.permissionRequestHandler, 'function');
  assert.ok(ipcMain.handlers.has('backend-connection'));
  assert.strictEqual(petWindow.isAlwaysOnTop(), true);

  const mainSender = { sender: petWindow.webContents };
  ipcMain.emit('open-settings', mainSender);
  const settingsWindow = windows[1];
  settingsWindow.emit('ready-to-show');
  assert.strictEqual(petWindow.isAlwaysOnTop(), false, 'settings must stay above the pet');
  ipcMain.emit('watermark-visibility-changed', mainSender, true);
  assert.ok(
    settingsWindow.webContents.sent.some(([channel, hidden]) => (
      channel === 'watermark-visibility-changed' && hidden === true
    )),
    'the edit-mode watermark button must update an open settings window',
  );
  ipcMain.emit(
    'watermark-visibility-changed',
    { sender: settingsWindow.webContents },
    false,
  );
  assert.ok(
    petWindow.webContents.sent.some(([channel, hidden]) => (
      channel === 'watermark-visibility-changed' && hidden === false
    )),
    'the settings watermark checkbox must update the pet window',
  );
  settingsWindow.hide();
  assert.strictEqual(petWindow.isAlwaysOnTop(), true);

  ipcMain.emit('open-report', mainSender, { duration: 1 });
  const reportWindow = windows[2];
  reportWindow.emit('ready-to-show');
  assert.strictEqual(petWindow.isAlwaysOnTop(), false, 'report must stay above the pet');
  reportWindow.hide();
  assert.strictEqual(petWindow.isAlwaysOnTop(), true);

  ipcMain.emit('open-chat', mainSender);
  const chatWindow = windows[3];
  chatWindow.emit('ready-to-show');
  assert.strictEqual(petWindow.isAlwaysOnTop(), false, 'chat must stay above the pet');
  assert.ok(
    [settingsWindow, reportWindow, chatWindow].every((window) => !window.alwaysOnTopHistory.includes(true)),
    'auxiliary windows must not remain globally always-on-top',
  );

  ipcMain.emit('hide-pet', mainSender);
  assert.strictEqual(petWindow.isVisible(), false);
  writePetCommand('show', fakeNow);
  const petControlInterval = scheduledIntervals.find((item) => item.delay === 400);
  assert.ok(petControlInterval?.active);
  petControlInterval.callback();
  assert.strictEqual(
    petWindow.isVisible(),
    false,
    'a show command must not expose a transparent window before renderer readiness',
  );
  ipcMain.emit('renderer-ready', mainSender, { dailyMediaCount: 3 });
  assert.strictEqual(petWindow.isVisible(), true);
  assert.strictEqual(
    petWindow.isAlwaysOnTop(),
    false,
    'showing the pet must not cover an open auxiliary window',
  );
  assert.strictEqual(petWindow.getBounds().x, -1516, 'renderer readiness must keep the outer edge');
  ipcMain.emit('resize-window', mainSender, { contentWidth: 300, contentHeight: 300, scale: 1 });
  assert.strictEqual(petWindow.getBounds().x, -1516, 'media resize must remain wholly on the left display');
  assert.strictEqual(petWindow.getBounds().width, 308);
  chatWindow.hide();
  assert.strictEqual(petWindow.isAlwaysOnTop(), true, 'pet topmost state returns after all auxiliaries hide');

  const heartbeatInterval = scheduledIntervals.find((item) => item.delay === 500);
  assert.ok(heartbeatInterval?.active, 'signed launcher heartbeat monitor must be active');
  assert.strictEqual(quitCalls, 0);

  fakeNow += 4000;
  writeHeartbeat(fakeNow);
  heartbeatInterval.callback();
  assert.strictEqual(quitCalls, 0, 'a fresh signed heartbeat must extend launcher lifetime');

  fakeNow += 5001;
  heartbeatInterval.callback();
  assert.strictEqual(heartbeatInterval.active, false);
  assert.strictEqual(quitCalls, 1, 'a static expired heartbeat must not keep Electron alive');
  assert.strictEqual(quitCalls, 1);
  console.log('frontend main-process no-GUI smoke passed');
  Date.now = realDateNow;
  global.setInterval = realSetInterval;
  global.clearInterval = realClearInterval;
  fs.rmSync(testUserDir, { recursive: true, force: true });
  process.exit(0);
});
