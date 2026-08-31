const { app, BrowserWindow, screen, ipcMain, safeStorage, session, shell } = require('electron');
const path = require('path');
const fs = require('fs');
const crypto = require('crypto');
const { pathToFileURL } = require('url');
const { spawn, execSync, exec } = require('child_process');
const {
  getBackendDir,
  getUserDir,
  getMikuDir,
  resolvePython,
  isPackaged,
  isExternalBackend,
  getResourcesRoot,
} = require('./paths');
const {
  CHAT_HIDDEN_CONTEXT_MAX,
  isPlainObject,
  normalizeApiBaseUrl,
  normalizeExternalUrl,
  sanitizeApiRecord,
  sanitizeChatRequest,
  validateBackendDescriptor,
  validateLauncherHeartbeat,
} = require('./security');
const { loadModelConfig } = require('./model_config');

// A launcher can close its inherited console before Electron finishes loading.
// Treat the resulting broken output pipe as a logging failure, not an app crash.
for (const output of [process.stdout, process.stderr]) {
  output?.on?.('error', (error) => {
    if (error?.code === 'EPIPE') return;
  });
}

// Set application name for Task Manager and Taskbar
app.name = 'Miku Cure';
// Note: Electron API is setAppUserModelId (lowercase d), not setAppUserModelID
if (process.platform === 'win32' && typeof app.setAppUserModelId === 'function') {
  app.setAppUserModelId('MikuCure.DesktopPet.1.2.1');
}

/** Unified app icon: miku face from miku/icon.* */
function resolveAppIcon() {
  const root = getResourcesRoot();
  const candidates = [
    path.join(root, 'miku', 'icon.ico'),
    path.join(root, 'miku', 'icon.png'),
    path.join(__dirname, '..', 'miku', 'icon.ico'),
    path.join(__dirname, '..', 'miku', 'icon.png'),
    path.join(__dirname, 'assets', 'miku.ico'),
  ];
  for (const p of candidates) {
    if (fs.existsSync(p)) return p;
  }
  return path.join(__dirname, 'assets', 'miku.ico');
}
const APP_ICON = resolveAppIcon();


// RTX 5060 Blackwell GPU is not supported by Electron's GPU process (sm_120).
// Disable hardware acceleration to prevent GPU process crashes.
if (process.env.MIKU_DISABLE_GPU === '1') app.disableHardwareAcceleration();

const LAUNCH_SESSION = process.env.MIKU_LAUNCH_SESSION || '';
const WS_TOKEN = process.env.MIKU_WS_TOKEN || crypto.randomBytes(32).toString('hex');

let mainWindow;
let settingsWindow = null;
let reportWindow = null;
let chatWindow = null;
let backendProcess = null;
let backendPid = null;
let petControlTimer = null;
let petHidden = false;
let backendStopNotified = false;
let quitting = false;
let auxiliaryPositionTimer = null;
let launcherHeartbeatTimer = null;
let launcherHeartbeatStartedAt = 0;
let launcherLastHeartbeatTs = 0;
let rendererReady = false;
let petLaunchWorkArea = null;
let petLaunchHorizontalEdge = 'right';

const PET_SCREEN_MARGIN = 20;

function displayForWindowCenter(bounds) {
  return screen.getDisplayNearestPoint({
    x: Math.round(bounds.x + bounds.width / 2),
    y: Math.round(bounds.y + bounds.height / 2),
  });
}

function chooseOuterHorizontalEdge(display) {
  if (!screen.getAllDisplays) return 'right';
  const area = display.workArea;
  const displays = screen.getAllDisplays();
  let hasLeftNeighbor = false;
  let hasRightNeighbor = false;

  for (const candidate of displays) {
    const other = candidate.workArea;
    if (
      other.x === area.x
      && other.y === area.y
      && other.width === area.width
      && other.height === area.height
    ) continue;

    const verticallyOverlaps = Math.min(
      area.y + area.height,
      other.y + other.height,
    ) > Math.max(area.y, other.y);
    if (!verticallyOverlaps) continue;
    if (other.x + other.width <= area.x) hasLeftNeighbor = true;
    if (other.x >= area.x + area.width) hasRightNeighbor = true;
  }

  // Keep the pet away from a seam between side-by-side monitors.
  if (hasRightNeighbor && !hasLeftNeighbor) return 'left';
  if (hasLeftNeighbor && !hasRightNeighbor) return 'right';
  if (!hasLeftNeighbor && !hasRightNeighbor) return 'right';

  const minX = Math.min(...displays.map(({ workArea }) => workArea.x));
  const maxX = Math.max(...displays.map(({ workArea }) => workArea.x + workArea.width));
  const distanceToLeftEdge = area.x - minX;
  const distanceToRightEdge = maxX - (area.x + area.width);
  return distanceToLeftEdge <= distanceToRightEdge ? 'left' : 'right';
}

function petPositionAtScreenEdge(workArea, bounds, horizontalEdge) {
  const minX = workArea.x + PET_SCREEN_MARGIN;
  const maxX = workArea.x + workArea.width - bounds.width - PET_SCREEN_MARGIN;
  return {
    x: horizontalEdge === 'left' ? minX : maxX,
    y: workArea.y + workArea.height - bounds.height - PET_SCREEN_MARGIN,
  };
}

function petControlPath() {
  return path.join(getUserDir(), 'pet_control.json');
}

function petControlSignature(action, launchSession, ts) {
  return crypto
    .createHmac('sha256', WS_TOKEN)
    .update(`${action}:${launchSession}:${ts}`)
    .digest('hex');
}

function isValidPetControl(command) {
  if (!isPlainObject(command)) return false;
  const action = String(command.action || '');
  const launchSession = String(command.launch_session || '');
  const ts = Number(command.ts);
  const signature = String(command.signature || '').toLowerCase();
  if (!['hide', 'show', 'toggle', 'language', 'quit', 'pet_closed', 'renderer_ready', 'starting'].includes(action)) return false;
  if (launchSession !== LAUNCH_SESSION || !Number.isFinite(ts)) return false;
  if (Math.abs(Date.now() - ts) > 10 * 60 * 1000 || !/^[a-f0-9]{64}$/.test(signature)) return false;
  const expected = petControlSignature(action, launchSession, ts);
  return crypto.timingSafeEqual(Buffer.from(signature, 'hex'), Buffer.from(expected, 'hex'));
}

function writePetState(extra = {}) {
  try {
    const p = petControlPath();
    fs.mkdirSync(path.dirname(p), { recursive: true });
    const payload = {
      action: petHidden ? 'hide' : 'show',
      state: petHidden ? 'hidden' : 'visible',
      ...extra,
      ts: Date.now(),
      launch_session: LAUNCH_SESSION,
    };
    payload.signature = petControlSignature(payload.action, payload.launch_session, payload.ts);
    const temporary = p + '.electron.tmp';
    fs.writeFileSync(temporary, JSON.stringify(payload), 'utf8');
    fs.renameSync(temporary, p);
  } catch (e) {
    console.error('writePetState failed', e);
  }
}

function applyPetVisibility(hide, publishState = true) {
  petHidden = !!hide;
  if (!mainWindow || mainWindow.isDestroyed()) return;
  if (petHidden) {
    mainWindow.hide();
  } else {
    if (rendererReady && !mainWindow.isVisible()) mainWindow.showInactive();
  }
  syncMainWindowAlwaysOnTop();
  if (publishState) writePetState();
}

function startPetControlWatcher() {
  if (petControlTimer) return;
  const p = petControlPath();
  let lastMtime = 0;
  petControlTimer = setInterval(() => {
    try {
      if (!fs.existsSync(p)) return;
      const st = fs.statSync(p);
      const m = st.mtimeMs || st.mtime.getTime();
      if (m <= lastMtime) return;
      const cmd = JSON.parse(fs.readFileSync(p, 'utf8') || '{}');
      if (!isValidPetControl(cmd)) return;
      lastMtime = m;
      // Commands already came from this file. Do not write them back or the
      // watcher will create a 400ms show/focus feedback loop.
      if (cmd.action === 'hide') applyPetVisibility(true, false);
      else if (cmd.action === 'show') applyPetVisibility(false, false);
      else if (cmd.action === 'toggle') applyPetVisibility(!petHidden, false);
      else if (cmd.action === 'language' && mainWindow && !mainWindow.isDestroyed()) {
        if (!['zh', 'ja', 'en'].includes(cmd.lang)) return;
        mainWindow.webContents.send('language-changed', cmd.lang || 'zh');
        if (settingsWindow && !settingsWindow.isDestroyed()) {
          settingsWindow.webContents.send('language-changed', cmd.lang || 'zh');
        }
        sendTo(reportWindow, 'lang-changed', cmd.lang);
        sendTo(chatWindow, 'lang-changed', cmd.lang);
      }
      else if (cmd.action === 'quit') {
        // Launcher is exiting everything — quit Electron; backend stopped by launcher PID tree
        if (petControlTimer) {
          clearInterval(petControlTimer);
          petControlTimer = null;
        }
        app.quit();
      }
    } catch (_) {}
  }, 400);
}

const ENC_PREFIX = 'enc:v1:';

function securePrefs() {
  return {
    nodeIntegration: false,
    contextIsolation: true,
    sandbox: true,
    webSecurity: true,
    preload: path.join(__dirname, 'preload.js'),
  };
}

function hardenWindow(window) {
  window.webContents.setWindowOpenHandler(({ url }) => {
    const external = normalizeExternalUrl(url);
    if (external) shell.openExternal(external).catch(() => {});
    return { action: 'deny' };
  });
  window.webContents.on('will-navigate', (event, url) => {
    if (url !== window.webContents.getURL()) event.preventDefault();
  });
  window.webContents.on('will-attach-webview', (event) => event.preventDefault());
}

function isWindowSender(event, window) {
  return !!window && !window.isDestroyed() && event.sender === window.webContents;
}

function isAnyAppSender(event) {
  return [mainWindow, settingsWindow, reportWindow, chatWindow]
    .some((window) => isWindowSender(event, window));
}

function sendTo(window, channel, ...args) {
  if (window && !window.isDestroyed()) window.webContents.send(channel, ...args);
}

const SAFE_PREFIX = 'enc:v2:safe:';

function encryptionAvailable() {
  try {
    if (!safeStorage || !safeStorage.isEncryptionAvailable()) return false;
    if (
      process.platform === 'linux'
      && typeof safeStorage.getSelectedStorageBackend === 'function'
      && safeStorage.getSelectedStorageBackend() === 'basic_text'
    ) return false;
    return true;
  } catch {
    return false;
  }
}

function encryptSecret(plain) {
  if (!plain) return '';
  if (!encryptionAvailable()) {
    throw new Error('Operating-system credential encryption is unavailable');
  }
  return SAFE_PREFIX + safeStorage.encryptString(String(plain)).toString('base64');
}

function decryptSecret(stored) {
  if (!stored || typeof stored !== 'string') return { plain: '', legacy: false };
  try {
    if (stored.startsWith(SAFE_PREFIX)) {
      if (!encryptionAvailable()) return { plain: '', legacy: false };
      return {
        plain: safeStorage.decryptString(Buffer.from(stored.slice(SAFE_PREFIX.length), 'base64')),
        legacy: false,
      };
    }
    if (stored.startsWith(ENC_PREFIX + 'b64:')) {
      return {
        plain: Buffer.from(stored.slice((ENC_PREFIX + 'b64:').length), 'base64').toString('utf8'),
        legacy: true,
      };
    }
    if (stored.startsWith(ENC_PREFIX)) {
      if (!encryptionAvailable()) return { plain: '', legacy: false };
      return {
        plain: safeStorage.decryptString(Buffer.from(stored.slice(ENC_PREFIX.length), 'base64')),
        legacy: true,
      };
    }
    return { plain: stored, legacy: true };
  } catch (error) {
    console.error('[Main] API key could not be decrypted; re-enter it in Settings.', error.message);
    return { plain: '', legacy: false };
  }
}

const userDir = getUserDir();
const keysDir = path.join(userDir, 'keys');
const apiJsonPath = path.join(keysDir, 'api.json');

function loadApisRaw() {
  try {
    if (!fs.existsSync(keysDir)) fs.mkdirSync(keysDir, { recursive: true });
    if (fs.existsSync(apiJsonPath)) {
      const parsed = JSON.parse(fs.readFileSync(apiJsonPath, 'utf8'));
      return Array.isArray(parsed) ? parsed : [];
    }
  } catch (e) {
    console.error('Failed to load api.json', e);
  }
  return [];
}

function writeApisRaw(list) {
  try {
    if (!fs.existsSync(keysDir)) fs.mkdirSync(keysDir, { recursive: true });
    const temporary = apiJsonPath + '.tmp';
    fs.writeFileSync(temporary, JSON.stringify(list, null, 2), 'utf8');
    fs.renameSync(temporary, apiJsonPath);
    return true;
  } catch (e) {
    console.error('Failed to save api.json', e);
    return false;
  }
}

function loadApisDecrypted() {
  const list = loadApisRaw();
  if (!Array.isArray(list)) return [];
  let changed = false;
  const out = list.map((api) => {
    const raw = api.apiKey || '';
    const decrypted = decryptSecret(raw);
    if (decrypted.legacy) {
      changed = true;
      api.apiKey = decrypted.plain && encryptionAvailable()
        ? encryptSecret(decrypted.plain)
        : '';
    }
    return { ...api, apiKey: decrypted.plain };
  });
  if (changed) {
    writeApisRaw(list);
    console.log('[Main] Legacy API key storage migrated to OS safeStorage');
  }
  return out;
}

function loadApisForSettings() {
  return loadApisDecrypted().map((api) => ({
    id: String(api.id || ''),
    name: String(api.name || ''),
    baseUrl: String(api.baseUrl || ''),
    models: Array.isArray(api.models) ? api.models : [],
    apiKey: '',
    hasApiKey: !!api.apiKey,
  }));
}

function saveApisFromSettings(input) {
  if (!Array.isArray(input) || input.length > 50) return { ok: false, error: 'Invalid API list' };
  const existing = new Map(loadApisRaw().map((api) => [String(api.id || ''), api]));
  const next = [];
  try {
    for (const candidate of input) {
      const clean = sanitizeApiRecord(candidate);
      if (!clean) return { ok: false, error: 'Invalid API configuration' };
      const old = existing.get(clean.id);
      const apiKey = clean.apiKey
        ? encryptSecret(clean.apiKey)
        : (old && typeof old.apiKey === 'string' ? old.apiKey : '');
      next.push({
        id: clean.id,
        name: clean.name,
        baseUrl: clean.baseUrl,
        models: clean.models,
        apiKey,
      });
    }
  } catch (error) {
    return { ok: false, error: error.message };
  }
  return writeApisRaw(next)
    ? { ok: true }
    : { ok: false, error: 'Could not save API settings' };
}

// Stop Python backend process tree (Windows-safe).
// When MIKU_EXTERNAL_BACKEND=1 the backend is a *child of the launcher*, not of Electron.
// Electron must not taskkill it or probe the network. The signed heartbeat
// below verifies that the launcher for this session is still alive.
// Launcher watches pet_control.json + Electron exit and stops backend via its own tracked PID.
function removeBackendPidFileIfTracked(trackedPid) {
  if (!Number.isInteger(trackedPid) || trackedPid <= 0) return;
  try {
    const pidFile = path.join(getUserDir(), 'backend.pid');
    if (!fs.existsSync(pidFile)) return;
    const filePid = Number.parseInt(fs.readFileSync(pidFile, 'utf8').trim(), 10);
    if (filePid === trackedPid) fs.unlinkSync(pidFile);
  } catch (_) {}
}

function killBackend() {
  if (isExternalBackend()) {
    if (backendStopNotified) return;
    backendStopNotified = true;
    console.log('[Main] External backend mode - notify launcher only (no backend taskkill or network probe)');
    try {
      writePetState({ action: 'pet_closed', state: petHidden ? 'hidden' : 'visible' });
    } catch (_) {}
    backendProcess = null;
    backendPid = null;
    return;
  }
  const trackedProcess = backendProcess;
  const trackedPid = Number(trackedProcess?.pid);
  if (Number.isInteger(trackedPid) && trackedPid > 0) {
    try {
      if (process.platform === 'win32') {
        execSync(`taskkill /F /T /PID ${trackedPid}`, {
          stdio: 'ignore',
          windowsHide: true,
          timeout: 8000,
        });
      } else {
        try { trackedProcess.kill('SIGTERM'); } catch (_) {}
        try { trackedProcess.kill('SIGKILL'); } catch (_) {}
      }
    } catch (_) {
      // already exited
    }
    removeBackendPidFileIfTracked(trackedPid);
  }

  if (trackedProcess) {
    try { trackedProcess.kill(); } catch (_) {}
  }
  backendProcess = null;
  backendPid = null;
  console.log('[Main] Backend kill sequence finished.');
}

const LAUNCHER_HEARTBEAT_TIMEOUT_MS = 5000;
const LAUNCHER_HEARTBEAT_POLL_MS = 500;

function launcherHeartbeatPath() {
  return path.join(getUserDir(), 'launcher_heartbeat.json');
}

function stopLauncherHeartbeatMonitor() {
  if (launcherHeartbeatTimer) {
    clearInterval(launcherHeartbeatTimer);
    launcherHeartbeatTimer = null;
  }
}

function checkLauncherHeartbeat() {
  if (!isExternalBackend() || quitting) return;
  const now = Date.now();
  try {
    const heartbeatPath = launcherHeartbeatPath();
    const stat = fs.statSync(heartbeatPath);
    if (stat.isFile() && stat.size > 0 && stat.size <= 16 * 1024) {
      const heartbeat = JSON.parse(fs.readFileSync(heartbeatPath, 'utf8'));
      const validTs = validateLauncherHeartbeat(heartbeat, {
        token: WS_TOKEN,
        launchSession: LAUNCH_SESSION,
        now,
        maxAgeMs: LAUNCHER_HEARTBEAT_TIMEOUT_MS,
      });
      if (validTs !== null && validTs > launcherLastHeartbeatTs) {
        launcherLastHeartbeatTs = validTs;
      }
    }
  } catch (_) {
    // The launcher writes atomically; missing or transiently unreadable files
    // are tolerated until the last valid heartbeat reaches the deadline.
  }

  const latestProof = Math.max(launcherHeartbeatStartedAt, launcherLastHeartbeatTs);
  if (now - latestProof > LAUNCHER_HEARTBEAT_TIMEOUT_MS) {
    stopLauncherHeartbeatMonitor();
    console.warn('[Main] Signed launcher heartbeat expired; closing Electron.');
    app.quit();
  }
}

function startLauncherHeartbeatMonitor() {
  if (!isExternalBackend() || launcherHeartbeatTimer) return;
  launcherHeartbeatStartedAt = Date.now();
  launcherLastHeartbeatTs = 0;
  checkLauncherHeartbeat();
  if (!quitting) {
    launcherHeartbeatTimer = setInterval(checkLauncherHeartbeat, LAUNCHER_HEARTBEAT_POLL_MS);
  }
}


function createWindow() {
  backendStopNotified = false;
  rendererReady = false;
  const launchX = Number(process.env.MIKU_LAUNCH_DISPLAY_X);
  const launchY = Number(process.env.MIKU_LAUNCH_DISPLAY_Y);
  const launchDisplay = Number.isFinite(launchX) && Number.isFinite(launchY)
    ? screen.getDisplayNearestPoint({ x: launchX, y: launchY })
    : screen.getPrimaryDisplay();
  const launchWorkArea = launchDisplay.workArea;
  petLaunchWorkArea = { ...launchWorkArea };
  petLaunchHorizontalEdge = chooseOuterHorizontalEdge(launchDisplay);

  // Pet main window dimensions: exactly 208x208 (fits 200x200 video + margins & shadows)
  const windowWidth = 208;
  const windowHeight = 208;

  mainWindow = new BrowserWindow({
    width: windowWidth,
    height: windowHeight,
    x: petPositionAtScreenEdge(
      launchWorkArea,
      { width: windowWidth, height: windowHeight },
      petLaunchHorizontalEdge,
    ).x,
    y: petPositionAtScreenEdge(
      launchWorkArea,
      { width: windowWidth, height: windowHeight },
      petLaunchHorizontalEdge,
    ).y,
    type: 'toolbar',
    frame: false,
    transparent: true,
    alwaysOnTop: true,
    resizable: false,
    show: false,
    icon: APP_ICON,
    webPreferences: securePrefs()
  });

  hardenWindow(mainWindow);
  mainWindow.webContents.on('console-message', (details) => {
    const level = details && details.level !== undefined ? details.level : 'log';
    const message = details && details.message !== undefined ? details.message : '';
    const line = details && details.lineNumber !== undefined ? details.lineNumber : 0;
    const source = path.basename(String(details && details.sourceId || 'renderer'));
    if (process.stdout?.destroyed || process.stdout?.writable === false) return;
    console.log('[Renderer:' + level + '] ' + message + ' (' + source + ':' + line + ')');
  });
  mainWindow.webContents.on('did-fail-load', (_event, code, description) => {
    console.error('[Main] Pet page failed to load (' + code + '): ' + description);
  });
  mainWindow.webContents.on('render-process-gone', (_event, details) => {
    console.error('[Main] Pet renderer exited: ' + details.reason + ' (' + details.exitCode + ')');
  });
  mainWindow.loadFile('index.html').catch((error) => {
    console.error('[Main] Pet page load failed:', error);
  });
  mainWindow.on('move', scheduleAuxiliaryWindowPositions);
  mainWindow.on('resize', scheduleAuxiliaryWindowPositions);

  // Launcher can request hide/show via user/pet_control.json
  startPetControlWatcher();

  mainWindow.on('close', (event) => {
    if (!quitting) {
      event.preventDefault();
      app.quit();
    }
  });

  mainWindow.on('closed', function () {
    mainWindow = null;
    rendererReady = false;
    petLaunchWorkArea = null;
    petLaunchHorizontalEdge = 'right';
    if (settingsWindow) {
      settingsWindow.close();
      settingsWindow = null;
    }
    if (reportWindow) {
      reportWindow.close();
      reportWindow = null;
    }
    if (chatWindow) {
      chatWindow.close();
      chatWindow = null;
    }
  });
}

// 1. IPC listener for custom window dragging (Drift-free absolute positioning)
let dragStartBounds;
ipcMain.on('drag-start', (event) => {
  if (!isWindowSender(event, mainWindow)) return;
  if (mainWindow) {
    dragStartBounds = mainWindow.getBounds();
  }
});

ipcMain.on('window-drag', (event, delta) => {
  if (!isWindowSender(event, mainWindow) || !mainWindow || !dragStartBounds || !isPlainObject(delta)) return;
  const { dx, dy } = delta;
  if (!Number.isFinite(dx) || !Number.isFinite(dy) || Math.abs(dx) > 10000 || Math.abs(dy) > 10000) return;
  mainWindow.setBounds({
    x: dragStartBounds.x + dx,
    y: dragStartBounds.y + dy,
    width: dragStartBounds.width,
    height: dragStartBounds.height
  });
});

ipcMain.on('hide-pet', (event) => {
  if (!isWindowSender(event, mainWindow)) return;
  applyPetVisibility(true);
});

function positionAuxiliaryWindow(window) {
  if (!window || window.isDestroyed() || !mainWindow || mainWindow.isDestroyed()) return;

  const petBounds = mainWindow.getBounds();
  const workArea = displayForWindowCenter(petBounds).workArea;
  const windowBounds = window.getBounds();
  const gap = 12;
  const rightX = petBounds.x + petBounds.width + gap;
  const leftX = petBounds.x - windowBounds.width - gap;
  const fitsRight = rightX + windowBounds.width <= workArea.x + workArea.width;
  const fitsLeft = leftX >= workArea.x;

  let x;
  if (fitsRight) {
    x = rightX;
  } else if (fitsLeft) {
    x = leftX;
  } else {
    const rightSpace = workArea.x + workArea.width - (petBounds.x + petBounds.width);
    const leftSpace = petBounds.x - workArea.x;
    x = rightSpace >= leftSpace
      ? workArea.x + workArea.width - windowBounds.width
      : workArea.x;
  }

  let y = Math.round(
    petBounds.y + petBounds.height / 2 - windowBounds.height / 2,
  );
  x = Math.max(
    workArea.x,
    Math.min(x, workArea.x + workArea.width - windowBounds.width),
  );
  y = Math.max(
    workArea.y,
    Math.min(y, workArea.y + workArea.height - windowBounds.height),
  );
  window.setPosition(Math.round(x), Math.round(y), false);
}

function scheduleAuxiliaryWindowPositions() {
  if (auxiliaryPositionTimer) return;
  auxiliaryPositionTimer = setTimeout(() => {
    auxiliaryPositionTimer = null;
    [settingsWindow, reportWindow, chatWindow].forEach((window) => {
      if (window && !window.isDestroyed() && window.isVisible()) positionAuxiliaryWindow(window);
    });
  }, 16);
}

function hasVisibleAuxiliaryWindow() {
  return [settingsWindow, reportWindow, chatWindow].some((window) => (
    window
    && !window.isDestroyed()
    && window.isVisible()
    && !window.isMinimized()
  ));
}

function syncMainWindowAlwaysOnTop() {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  const shouldStayOnTop = !petHidden && !hasVisibleAuxiliaryWindow();
  if (
    typeof mainWindow.isAlwaysOnTop === 'function'
    && mainWindow.isAlwaysOnTop() === shouldStayOnTop
  ) return;
  mainWindow.setAlwaysOnTop(shouldStayOnTop);
}

function trackAuxiliaryWindow(window) {
  ['show', 'hide', 'minimize', 'restore'].forEach((eventName) => {
    window.on(eventName, syncMainWindowAlwaysOnTop);
  });
}

ipcMain.on('renderer-ready', (event, payload) => {
  if (!isWindowSender(event, mainWindow) || !isPlainObject(payload)) return;
  const mediaCount = Number(payload.dailyMediaCount);
  const displayMode = loadConfig()['miku-display-mode'] || 'media';
  if (!Number.isInteger(mediaCount) || mediaCount < 0) return;
  if (mediaCount < 1 && displayMode !== '3d') return;
  rendererReady = true;
  if (mainWindow && !mainWindow.isDestroyed() && !petHidden) {
    const bounds = mainWindow.getBounds();
    const workArea = petLaunchWorkArea || screen.getPrimaryDisplay().workArea;
    const position = petPositionAtScreenEdge(workArea, bounds, petLaunchHorizontalEdge);
    mainWindow.setPosition(Math.round(position.x), Math.round(position.y), false);
    mainWindow.showInactive();
  }
  writePetState({
    action: 'renderer_ready',
    state: 'visible',
    media_count: mediaCount,
  });
});

function showAuxiliaryWindow(window) {
  if (!window || window.isDestroyed()) return;
  if (window.isMinimized()) window.restore();
  positionAuxiliaryWindow(window);
  if (mainWindow && !mainWindow.isDestroyed()) mainWindow.setAlwaysOnTop(false);
  window.show();
  syncMainWindowAlwaysOnTop();
  window.focus();
  window.moveTop();
}

// 2. IPC listener to open settings window in a separate container
ipcMain.on('open-settings', (event) => {
  if (!isWindowSender(event, mainWindow)) return;
  if (settingsWindow) {
    showAuxiliaryWindow(settingsWindow);
    return;
  }

  try {
    settingsWindow = new BrowserWindow({
      width: 720,
      height: 480,
      title: "Miku Cure 设置",
      show: false,
      resizable: false,
      minimizable: true,
      maximizable: false,
      icon: APP_ICON,
      webPreferences: securePrefs()
    });

    hardenWindow(settingsWindow);
    trackAuxiliaryWindow(settingsWindow);
    settingsWindow.setMenu(null);
    settingsWindow.loadFile(path.join(__dirname, 'settings.html')).catch((error) => {
      console.error('[Main] Settings window failed to load:', error);
    });
    settingsWindow.once('ready-to-show', () => {
      showAuxiliaryWindow(settingsWindow);
    });

    settingsWindow.on('closed', () => {
      settingsWindow = null;
      syncMainWindowAlwaysOnTop();
    });
  } catch (error) {
    settingsWindow = null;
    console.error('[Main] Settings window failed to create:', error);
  }
});

// 3. Forward model-changed IPC message from settingsWindow to mainWindow
ipcMain.on('model-changed', (event, selectedModel) => {
  if (!isWindowSender(event, settingsWindow) || typeof selectedModel !== 'string') return;
  const safeModel = path.basename(selectedModel).slice(0, 200);
  if (safeModel !== 'mock' && !safeModel.endsWith('.pth')) return;
  if (mainWindow) {
    mainWindow.webContents.send('change-model', safeModel);
  }
});

// Forward the character display mode from settings to the main pet window.
ipcMain.on('display-mode-changed', (event, mode) => {
  if (!isWindowSender(event, settingsWindow) || !['media', '3d'].includes(mode)) return;
  if (mainWindow) mainWindow.webContents.send('change-display-mode', mode);
});

ipcMain.on('character-model-changed', (event, modelId) => {
  if (!isWindowSender(event, settingsWindow) || typeof modelId !== 'string') return;
  if (!listCharacterModels().some((model) => model.id === modelId)) return;
  if (mainWindow) mainWindow.webContents.send('change-character-model', modelId);
});

ipcMain.on('watermark-visibility-changed', (event, hidden) => {
  if (typeof hidden !== 'boolean') return;
  if (isWindowSender(event, settingsWindow)) {
    if (mainWindow) mainWindow.webContents.send('watermark-visibility-changed', hidden);
  } else if (isWindowSender(event, mainWindow)) {
    if (settingsWindow) settingsWindow.webContents.send('watermark-visibility-changed', hidden);
  }
});

// Independent Report Window
ipcMain.on('open-report', (event, data) => {
  if (!isWindowSender(event, mainWindow) || !isPlainObject(data)) return;
  try {
    if (Buffer.byteLength(JSON.stringify(data), 'utf8') > 100000) return;
  } catch {
    return;
  }
  if (reportWindow) {
    showAuxiliaryWindow(reportWindow);
    reportWindow.webContents.send('load-report', data);
    return;
  }

  reportWindow = new BrowserWindow({
    width: 400,
    height: 520,
    title: "专注周期总结报告",
    show: false,
    resizable: false,
    minimizable: false,
    maximizable: false,
    icon: APP_ICON,
    webPreferences: securePrefs()
  });

  hardenWindow(reportWindow);
  trackAuxiliaryWindow(reportWindow);
  reportWindow.setMenu(null);
  reportWindow.loadFile(path.join(__dirname, 'report.html'));
  reportWindow.once('ready-to-show', () => {
    showAuxiliaryWindow(reportWindow);
  });
  
  reportWindow.webContents.on('did-finish-load', () => {
    reportWindow.webContents.send('load-report', data);
  });

  reportWindow.on('closed', () => {
    reportWindow = null;
    syncMainWindowAlwaysOnTop();
  });
});

ipcMain.on('action-from-report', (event, action) => {
  if (!isWindowSender(event, reportWindow) || !['sing', 'dance'].includes(action)) return;
  if (mainWindow) {
    mainWindow.webContents.send('action-from-report', action);
  }
});

function showChatWindow() {
  showAuxiliaryWindow(chatWindow);
}

function openChatWindow(onLoaded = null) {
  if (chatWindow && !chatWindow.isDestroyed()) {
    showChatWindow();
    if (onLoaded) {
      if (chatWindow.webContents.isLoading()) {
        chatWindow.webContents.once('did-finish-load', onLoaded);
      } else {
        onLoaded();
      }
    }
    return;
  }

  chatWindow = new BrowserWindow({
    width: 400,
    height: 520,
    title: "Miku Chat",
    show: false,
    resizable: false,
    minimizable: true,
    maximizable: false,
    icon: APP_ICON,
    webPreferences: securePrefs()
  });
  hardenWindow(chatWindow);
  trackAuxiliaryWindow(chatWindow);
  chatWindow.setMenu(null);
  chatWindow.once('ready-to-show', showChatWindow);
  chatWindow.webContents.once('did-finish-load', () => {
    showChatWindow();
    if (onLoaded) onLoaded();
  });
  chatWindow.webContents.on('did-fail-load', (event, code, description) => {
    console.error(`[Main] Chat window failed to load (${code}): ${description}`);
  });
  chatWindow.loadFile(path.join(__dirname, 'chat.html')).catch((error) => {
    console.error('[Main] Chat window failed to open:', error);
  });
  chatWindow.on('closed', () => {
    chatWindow = null;
    syncMainWindowAlwaysOnTop();
  });
}

ipcMain.on('analyze-report-request', (event, prompt, displayPrompt) => {
  if (!isWindowSender(event, reportWindow) || typeof prompt !== 'string' || typeof displayPrompt !== 'string') return;
  prompt = prompt.slice(0, CHAT_HIDDEN_CONTEXT_MAX);
  displayPrompt = displayPrompt.slice(0, 1000);
  openChatWindow(() => {
    if (chatWindow && !chatWindow.isDestroyed()) {
      chatWindow.webContents.send('populate-chat-input', prompt, displayPrompt);
    }
  });
});

// ── Chat Window IPC ──
ipcMain.on('open-chat', (event) => {
  if (!isWindowSender(event, mainWindow)) return;
  openChatWindow();
});

ipcMain.on('chat-message', (event, text) => {
  if (!isWindowSender(event, chatWindow)) return;
  text = sanitizeChatRequest(text);
  if (text === null) return;
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send('forward-chat-to-backend', text);
  } else if (chatWindow && !chatWindow.isDestroyed()) {
    chatWindow.webContents.send('chat-send-failed', '桌宠主窗口未就绪');
  }
});

ipcMain.on('action-from-chat', (event, action) => {
  if (!isWindowSender(event, chatWindow) || action !== 'play_music') return;
  if (mainWindow) mainWindow.webContents.send('action-from-chat', action);
});

ipcMain.on('chat-reply-from-backend', (event, reply) => {
  if (!isWindowSender(event, mainWindow) || typeof reply !== 'string') return;
  reply = reply.slice(0, 50000);
  if (chatWindow) chatWindow.webContents.send('chat-reply-from-backend', reply);
});

ipcMain.on('chat-send-failed', (event, reason) => {
  if (!isWindowSender(event, mainWindow) || typeof reason !== 'string') return;
  reason = reason.slice(0, 1000);
  if (chatWindow && !chatWindow.isDestroyed()) {
    chatWindow.webContents.send('chat-send-failed', reason);
  }
});

ipcMain.on('request-chat-history', (event) => {
  if (!isWindowSender(event, chatWindow)) return;
  if (mainWindow) mainWindow.webContents.send('forward-history-request-to-backend');
});

ipcMain.on('chat-history-from-backend', (event, history) => {
  if (!isWindowSender(event, mainWindow) || !Array.isArray(history)) return;
  history = history.slice(-500).filter((entry) => (
    isPlainObject(entry)
    && ['user', 'assistant', 'system'].includes(entry.role)
    && typeof entry.content === 'string'
  )).map((entry) => ({ role: entry.role, content: entry.content.slice(0, 50000) }));
  if (chatWindow) chatWindow.webContents.send('chat-history-from-backend', history);
});

ipcMain.on('lang-changed', (event, lang) => {
  if (!isWindowSender(event, settingsWindow) || !['zh', 'ja', 'en'].includes(lang)) return;
  if (mainWindow)   mainWindow.webContents.send('lang-changed', lang);
  if (reportWindow) reportWindow.webContents.send('lang-changed', lang);
  if (chatWindow)   chatWindow.webContents.send('lang-changed', lang);
});

// Forward LLM API config change from settings window to main renderer
ipcMain.on('llm-changed', (event) => {
  if (!isWindowSender(event, settingsWindow)) return;
  const config = selectedLlmConfig();
  if (mainWindow) mainWindow.webContents.send('llm-changed', config);
});

// 4. Handle window size change
ipcMain.on('size-changed', (event, size) => {
  if (!isWindowSender(event, settingsWindow) && !isWindowSender(event, mainWindow)) return;
  if (!['small', 'medium', 'large'].includes(size)) return;
  if (!mainWindow) return;
  // Forward to renderer to recalculate with video aspect ratio
  mainWindow.webContents.send('force-adjust-size', size);
});

// 5. Dynamic window resize based on video content
ipcMain.on('resize-window', (event, payload) => {
  if (!isWindowSender(event, mainWindow) || !isPlainObject(payload)) return;
  let { contentWidth, contentHeight, scale } = payload;
  if (!mainWindow || mainWindow.isDestroyed()) return;
  if (![contentWidth, contentHeight, scale].every(Number.isFinite)) return;
  contentWidth = Math.max(1, Math.min(contentWidth, 2000));
  contentHeight = Math.max(1, Math.min(contentHeight, 2000));
  scale = Math.max(0.5, Math.min(scale, 2));
  const bounds = mainWindow.getBounds();
  const display = displayForWindowCenter(bounds);
  const workArea = display.workArea;
  const usableWidth = Math.max(1, workArea.width - PET_SCREEN_MARGIN * 2);
  const usableHeight = Math.max(1, workArea.height - PET_SCREEN_MARGIN * 2);
  const width = Math.min(
    Math.round((contentWidth + 8) * scale),
    usableWidth,
  );
  const height = Math.min(
    Math.round((contentHeight + 8) * scale),
    usableHeight,
  );

  const cx = bounds.x + bounds.width / 2;
  const cy = bounds.y + bounds.height / 2;

  let x = Math.round(cx - width / 2);
  let y = Math.round(cy - height / 2);

  const minX = workArea.x + PET_SCREEN_MARGIN;
  const maxX = workArea.x + workArea.width - width - PET_SCREEN_MARGIN;
  const minY = workArea.y + PET_SCREEN_MARGIN;
  const maxY = workArea.y + workArea.height - height - PET_SCREEN_MARGIN;
  x = Math.max(minX, Math.min(x, maxX));
  y = Math.max(minY, Math.min(y, maxY));
  
  mainWindow.setBounds({ width, height, x, y });
  mainWindow.webContents.setZoomFactor(scale);
  scheduleAuxiliaryWindowPositions();
});

// Handle request to list available model files
ipcMain.handle('get-models', async (event) => {
  if (!isWindowSender(event, settingsWindow)) return [];
  const modelsDir = path.join(getBackendDir(), 'models');
  try {
    if (!fs.existsSync(modelsDir)) return [];
    const files = fs.readdirSync(modelsDir);
    return files.filter(f => f.endsWith('.pth'));
  } catch (err) {
    console.error('Error reading models directory:', err);
    return [];
  }
});

// Handle request to start the training process independently
ipcMain.on('run-train', (event) => {
  if (!isWindowSender(event, settingsWindow)) return;
  const trainBat = isPackaged()
    ? path.join(getBackendDir(), '..', 'train.bat')
    : path.join(__dirname, '..', 'train.bat');
  if (!fs.existsSync(trainBat)) {
    console.error('train.bat not found:', trainBat);
    return;
  }
  exec(`start "Miku Training" "${trainBat}"`);
});

app.whenReady().then(() => {
  session.defaultSession.setPermissionCheckHandler((webContents, permission) => (
    permission === 'media' && isWindowSender({ sender: webContents }, settingsWindow)
  ));
  session.defaultSession.setPermissionRequestHandler((webContents, permission, callback, details) => {
    const mediaTypes = Array.isArray(details?.mediaTypes) ? details.mediaTypes : [];
    const allowed = permission === 'media'
      && isWindowSender({ sender: webContents }, settingsWindow)
      && !mediaTypes.includes('audio');
    callback(allowed);
  });
  createWindow();
  startLauncherHeartbeatMonitor();
});

// Kill backend on every quit path (safety net)
app.on('before-quit', () => {
  quitting = true;
  stopLauncherHeartbeatMonitor();
  killBackend();
});
app.on('will-quit', () => {
  killBackend();
});
app.on('quit', () => {
  killBackend();
});

// IPC: renderer asks main to launch backend
ipcMain.on('start-backend', (event) => {
  if (!isWindowSender(event, mainWindow)) return;
  if (isExternalBackend()) {
    console.log('[Main] External backend mode — Electron will not spawn Python');
    return;
  }
  // Ensure any previous orphan is gone before spawn
  if (backendProcess && backendProcess.exitCode === null) {
    console.log('[Main] Backend already running, PID:', backendPid);
    return;
  }
  killBackend();

  const backendDir = getBackendDir();
  const config = loadConfig();
  const monitorOnStart = config['camera-monitor-on-start']
    ?? config['launcher-auto-monitor']
    ?? true;
  const py = resolvePython();
  const mainPy = path.join(backendDir, 'main.py');
  if (!fs.existsSync(mainPy)) {
    console.error('[Main] backend/main.py not found at', mainPy);
    return;
  }
  const launchedProcess = spawn(py, ['main.py'], {
    cwd: backendDir,
    detached: false,          // keep bound to Electron
    stdio: ['ignore', 'pipe', 'pipe'],
    windowsHide: true,
    env: {
      ...process.env,
      PYTHONUNBUFFERED: '1',
      MIKU_USER_DIR: getUserDir(),
      MIKU_RESOURCES: path.dirname(backendDir),
      MIKU_CAMERA_MONITOR_ON_START: monitorOnStart ? '1' : '0',
      MIKU_WS_TOKEN: WS_TOKEN,
      MIKU_LAUNCH_SESSION: LAUNCH_SESSION,
      MIKU_EXPECT_LAUNCHER_HEARTBEAT: '0',
    }
  });
  backendProcess = launchedProcess;
  backendPid = launchedProcess.pid;
  launchedProcess.stdout.on('data', d => process.stdout.write('[Backend] ' + d));
  launchedProcess.stderr.on('data', d => process.stderr.write('[Backend] ' + d));
  launchedProcess.on('exit', code => {
    console.log(`[Backend] exited with code ${code}`);
    removeBackendPidFileIfTracked(launchedProcess.pid);
    if (backendProcess === launchedProcess) {
      backendProcess = null;
      backendPid = null;
    }
  });
  console.log('[Main] Backend process started, PID:', backendPid, 'py:', py, 'cwd:', backendDir);
});

app.on('window-all-closed', function () {
  killBackend();
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.on('activate', function () {
  if (mainWindow === null) {
    createWindow();
  }
});

// ── Configuration & Version IPC ─────────────────────────────────────────────
const configJsonPath = path.join(userDir, 'config.json');

function loadConfig() {
  try {
    if (!fs.existsSync(userDir)) fs.mkdirSync(userDir, { recursive: true });
    if (fs.existsSync(configJsonPath)) {
      return JSON.parse(fs.readFileSync(configJsonPath, 'utf8')) || {};
    }
  } catch (e) {
    console.error('Failed to load config.json', e);
  }
  return {};
}

function saveConfig(config) {
  try {
    if (!fs.existsSync(userDir)) fs.mkdirSync(userDir, { recursive: true });
    const temporary = configJsonPath + '.tmp';
    fs.writeFileSync(temporary, JSON.stringify(config, null, 2), 'utf8');
    fs.renameSync(temporary, configJsonPath);
  } catch (e) {
    console.error('Failed to save config.json', e);
  }
}

const CONFIG_KEYS = new Set([
  'miku-language', 'miku-master-name', 'miku-model-type', 'miku-sel-api',
  'miku-sel-model', 'miku-volume', 'miku-window-size', 'miku-display-mode',
  'miku-character-model', 'miku-character-view', 'miku-hide-model-watermark',
]);

function sanitizeConfigValue(key, value) {
  if (!CONFIG_KEYS.has(key)) return undefined;
  if (key === 'miku-language') return ['zh', 'ja', 'en'].includes(value) ? value : undefined;
  if (key === 'miku-window-size') return ['small', 'medium', 'large'].includes(value) ? value : undefined;
  if (key === 'miku-display-mode') return ['media', '3d'].includes(value) ? value : undefined;
  if (key === 'miku-hide-model-watermark') return typeof value === 'boolean' ? value : undefined;
  if (key === 'miku-character-model') {
    return typeof value === 'string' && listCharacterModels().some((model) => model.id === value)
      ? value
      : undefined;
  }
  if (key === 'miku-character-view') {
    if (!isPlainObject(value)) return undefined;
    const knownModels = new Set(listCharacterModels().map((model) => model.id));
    const entries = Object.entries(value);
    if (entries.length > 50) return undefined;
    const safeViews = {};
    for (const [modelId, view] of entries) {
      if (!knownModels.has(modelId) || !isPlainObject(view)) return undefined;
      const { x, y, scale } = view;
      if (!Number.isFinite(x) || !Number.isFinite(y) || !Number.isFinite(scale)
        || x < -1 || x > 1 || y < -1 || y > 1 || scale < 0.5 || scale > 3) {
        return undefined;
      }
      safeViews[modelId] = { x, y, scale };
    }
    return safeViews;
  }
  if (key === 'miku-volume') {
    return Number.isFinite(value) && value >= 0 && value <= 1 ? value : undefined;
  }
  if (typeof value !== 'string') return undefined;
  const max = key === 'miku-master-name' ? 100 : 200;
  const text = value.slice(0, max);
  if (key === 'miku-model-type') {
    const model = path.basename(text);
    return model === 'mock' || model.endsWith('.pth') ? model : undefined;
  }
  return text;
}

function selectedLlmConfig() {
  const config = loadConfig();
  const selId = config['miku-sel-api'] || '';
  const model = config['miku-sel-model'] || '';
  const api = loadApisDecrypted().find((item) => item.id === selId);
  if (!api) return { baseUrl: '', apiKey: '', model: '' };
  return { baseUrl: api.baseUrl || '', apiKey: api.apiKey || '', model };
}

ipcMain.handle('get-app-version', (event) => {
  if (!isAnyAppSender(event)) return '';
  return app.getVersion();
});

ipcMain.on('get-config', (event, key) => {
  if (!isAnyAppSender(event) || !CONFIG_KEYS.has(key)) {
    event.returnValue = null;
    return;
  }
  const config = loadConfig();
  event.returnValue = config[key] !== undefined ? config[key] : null;
});

ipcMain.on('set-config', (event, data) => {
  if ((!isWindowSender(event, mainWindow) && !isWindowSender(event, settingsWindow)) || !isPlainObject(data)) return;
  const { key, val } = data;
  if (!CONFIG_KEYS.has(key)) return;
  const config = loadConfig();
  if (val === null || val === undefined) {
    delete config[key];
  } else {
    const safeValue = sanitizeConfigValue(key, val);
    if (safeValue === undefined) return;
    config[key] = safeValue;
  }
  saveConfig(config);
});

// ── Encrypted API key storage (main-process only) ───────────────────────────
ipcMain.handle('apis-load', (event) => {
  if (!isWindowSender(event, settingsWindow)) return [];
  return loadApisForSettings();
});

ipcMain.handle('apis-save', (event, list) => {
  if (!isWindowSender(event, settingsWindow)) return { ok: false, error: 'Not allowed' };
  return saveApisFromSettings(list);
});

/** Return currently selected LLM config with decrypted key (for backend sync). */
ipcMain.handle('get-selected-llm', (event) => {
  if (!isWindowSender(event, mainWindow)) return { baseUrl: '', apiKey: '', model: '' };
  return selectedLlmConfig();
});

ipcMain.handle('has-lora', (event) => {
  if (!isWindowSender(event, settingsWindow)) return false;
  const loraDir = path.join(getUserDir(), 'lora');
  try {
    if (!fs.existsSync(loraDir)) return false;
    return fs.readdirSync(loraDir).some((f) => f.endsWith('.safetensors') || f.endsWith('.pth'));
  } catch {
    return false;
  }
});

ipcMain.handle('backend-connection', (event) => {
  if (!isWindowSender(event, mainWindow) && !isWindowSender(event, settingsWindow)) return null;
  try {
    const descriptorPath = path.join(getUserDir(), 'ws_port.json');
    const stat = fs.statSync(descriptorPath);
    if (!stat.isFile() || stat.size > 8192) return null;
    const descriptor = JSON.parse(fs.readFileSync(descriptorPath, 'utf8'));
    return validateBackendDescriptor(descriptor, {
      token: WS_TOKEN,
      launchSession: LAUNCH_SESSION,
    });
  } catch (error) {
    console.warn('[Main] Backend descriptor rejected:', error.message);
    return null;
  }
});

const MEDIA_EXTENSIONS = Object.freeze({
  daily: new Set(['.gif', '.png', '.jpg', '.jpeg', '.webp', '.bmp', '.mp4', '.webm', '.mkv', '.mov', '.avi', '.m4v']),
  dance: new Set(['.mp4', '.webm', '.mkv', '.mov', '.avi', '.m4v']),
  sing: new Set(['.ogg', '.mp3', '.wav', '.m4a', '.aac', '.flac']),
  asset: new Set(['.mp4', '.webm']),
});

function isPathWithin(root, candidate) {
  const relative = path.relative(root, candidate);
  return relative === '' || (!relative.startsWith('..' + path.sep) && relative !== '..' && !path.isAbsolute(relative));
}

function findFilesRecursively(root, extensions) {
  const files = [];
  const walk = (directory) => {
    let entries;
    try {
      entries = fs.readdirSync(directory, { withFileTypes: true });
    } catch {
      return;
    }
    for (const entry of entries) {
      const absolute = path.join(directory, entry.name);
      if (entry.isDirectory()) {
        walk(absolute);
      } else if (entry.isFile() && [...extensions].some((extension) => entry.name.toLowerCase().endsWith(extension))) {
        files.push(absolute);
      }
    }
  };
  walk(root);
  return files;
}

function relativeModelPath(root, file) {
  return path.relative(root, file).split(path.sep).join('/');
}

function listCharacterModels() {
  const directory = path.join(getMikuDir(), 'models');
  let root;
  try {
    root = fs.realpathSync(directory);
  } catch {
    return [];
  }

  const modelFiles = findFilesRecursively(root, new Set(['.pmx', '.pmd', '.model3.json']))
    .filter((file) => isPathWithin(root, file));
  const byFolder = new Map();

  for (const file of modelFiles) {
    const relative = relativeModelPath(root, file);
    const folder = relative.split('/')[0] || path.basename(path.dirname(file));
    const type = file.toLowerCase().endsWith('.model3.json') ? 'live2d' : 'mmd';
    const current = byFolder.get(folder);
    // Prefer Live2D manifests, then the normal PMX over its optional BDEF variant.
    const score = type === 'live2d' ? 3 : /_BDEF\.(pmx|pmd)$/i.test(file) ? 1 : 2;
    if (!current || score > current.score) byFolder.set(folder, { file, relative, type, score, folder });
  }

  return [...byFolder.values()]
    .map((entry) => {
      const modelDirectory = path.dirname(entry.file);
      const relatedFiles = entry.type === 'live2d'
        ? findFilesRecursively(modelDirectory, new Set(['.motion3.json', '.exp3.json']))
          .filter((file) => isPathWithin(root, file))
          .map((file) => ({
            name: path.basename(file),
            url: pathToFileURL(file).href,
          }))
        : [];
      return {
        id: entry.relative,
        name: entry.folder,
        type: entry.type,
        url: pathToFileURL(entry.file).href,
        config: loadModelConfig(modelDirectory),
        motions: relatedFiles.filter((file) => /\.motion3\.json$/i.test(file.name)),
        expressions: relatedFiles.filter((file) => /\.exp3\.json$/i.test(file.name)),
      };
    })
    .sort((a, b) => a.name.localeCompare(b.name, 'zh-Hans-CN'));
}

function listMedia(kind) {
  const extensions = MEDIA_EXTENSIONS[kind];
  if (!extensions) return [];
  const directory = kind === 'asset'
    ? path.join(__dirname, 'assets')
    : path.join(getMikuDir(), kind === 'daily' ? 'gif' : kind);
  try {
    const resolvedRoot = fs.realpathSync(directory);
    return fs.readdirSync(resolvedRoot, { withFileTypes: true })
      .filter((entry) => entry.isFile() && extensions.has(path.extname(entry.name).toLowerCase()))
      .map((entry) => {
        const absolute = path.resolve(resolvedRoot, entry.name);
        if (path.dirname(absolute) !== resolvedRoot) return null;
        return { name: entry.name, url: pathToFileURL(absolute).href };
      })
      .filter(Boolean);
  } catch {
    return [];
  }
}

ipcMain.handle('list-media', (event, kind) => {
  if (!isWindowSender(event, mainWindow) && !isWindowSender(event, chatWindow)) return [];
  if (!Object.prototype.hasOwnProperty.call(MEDIA_EXTENSIONS, kind)) return [];
  return listMedia(kind);
});

ipcMain.handle('list-character-models', (event) => {
  if (!isWindowSender(event, mainWindow) && !isWindowSender(event, settingsWindow)) return [];
  return listCharacterModels();
});

ipcMain.handle('api-fetch-models', async (event, payload) => {
  if (!isWindowSender(event, settingsWindow) || !isPlainObject(payload)) return [];
  const baseUrl = normalizeApiBaseUrl(payload.baseUrl);
  let apiKey = typeof payload.apiKey === 'string' ? payload.apiKey.slice(0, 4096) : '';
  if (!apiKey && typeof payload.apiId === 'string') {
    apiKey = loadApisDecrypted().find((item) => item.id === payload.apiId)?.apiKey || '';
  }
  if (!baseUrl || !apiKey) return [];
  try {
    const parsed = new URL(baseUrl);
    const candidates = [`${baseUrl}/models`];
    if (!/\/v1$/i.test(parsed.pathname.replace(/\/+$/, ''))) candidates.unshift(`${baseUrl}/v1/models`);
    for (const url of candidates) {
      const response = await fetch(url, {
        headers: { Authorization: `Bearer ${apiKey}` },
        signal: AbortSignal.timeout(10000),
      }).catch(() => null);
      if (!response?.ok) continue;
      const data = await response.json().catch(() => null);
      if (!Array.isArray(data?.data)) continue;
      return data.data
        .map((item) => typeof item?.id === 'string' ? item.id.slice(0, 200) : '')
        .filter(Boolean)
        .slice(0, 200);
    }
  } catch (error) {
    console.warn('[Main] Model discovery failed:', error.message);
  }
  return [];
});
