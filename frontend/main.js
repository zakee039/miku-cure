const { app, BrowserWindow, screen, ipcMain, safeStorage } = require('electron');
const path = require('path');
const fs = require('fs');
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

// Set application name for Task Manager and Taskbar
app.name = 'Miku Cure';
// Note: Electron API is setAppUserModelId (lowercase d), not setAppUserModelID
if (process.platform === 'win32' && typeof app.setAppUserModelId === 'function') {
  app.setAppUserModelId('MikuCure.DesktopPet.1.1.2');
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
app.disableHardwareAcceleration();

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

function petControlPath() {
  return path.join(getUserDir(), 'pet_control.json');
}

function writePetState(extra = {}) {
  try {
    const p = petControlPath();
    fs.mkdirSync(path.dirname(p), { recursive: true });
    const payload = {
      action: petHidden ? 'hide' : 'show',
      state: petHidden ? 'hidden' : 'visible',
      ts: Date.now(),
      launch_session: process.env.MIKU_LAUNCH_SESSION || '',
      ...extra,
    };
    fs.writeFileSync(p, JSON.stringify(payload), 'utf8');
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
    if (!mainWindow.isVisible()) mainWindow.showInactive();
    mainWindow.setAlwaysOnTop(true);
  }
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
      lastMtime = m;
      const cmd = JSON.parse(fs.readFileSync(p, 'utf8') || '{}');
      // Commands already came from this file. Do not write them back or the
      // watcher will create a 400ms show/focus feedback loop.
      if (cmd.action === 'hide') applyPetVisibility(true, false);
      else if (cmd.action === 'show') applyPetVisibility(false, false);
      else if (cmd.action === 'toggle') applyPetVisibility(!petHidden, false);
      else if (cmd.action === 'language' && mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.webContents.send('language-changed', cmd.lang || 'zh');
        if (settingsWindow && !settingsWindow.isDestroyed()) {
          settingsWindow.webContents.send('language-changed', cmd.lang || 'zh');
        }
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
    // Keep nodeIntegration for local file:// UI scripts; secrets live in main via IPC.
    nodeIntegration: true,
    contextIsolation: false,
    sandbox: false,
    webSecurity: true,
    preload: path.join(__dirname, 'preload.js'),
  };
}

function isPortableLayout() {
  try {
    const root = getResourcesRoot();
    return (
      process.env.MIKU_PROJECT_ROOT ||
      process.env.MIKU_EXTERNAL_BACKEND === '1' ||
      fs.existsSync(path.join(root, 'PORTABLE_MANIFEST.json')) ||
      fs.existsSync(path.join(root, 'runtime', 'python', 'python.exe'))
    );
  } catch {
    return false;
  }
}

function encryptSecret(plain) {
  if (!plain) return '';
  if (typeof plain === 'string' && plain.startsWith(ENC_PREFIX)) {
    // Already encrypted — if portable, migrate safeStorage blobs to b64 on next save
    if (isPortableLayout() && !plain.startsWith(ENC_PREFIX + 'b64:')) {
      const dec = decryptSecret(plain);
      if (dec) {
        return ENC_PREFIX + 'b64:' + Buffer.from(dec, 'utf8').toString('base64');
      }
    }
    return plain;
  }
  // Always prefer portable b64 for keys under portable layout / external backend.
  // Dev-only: optional OS safeStorage (machine-bound).
  if (!isPortableLayout()) {
    try {
      if (safeStorage && safeStorage.isEncryptionAvailable()) {
        const buf = safeStorage.encryptString(String(plain));
        return ENC_PREFIX + buf.toString('base64');
      }
    } catch (e) {
      console.error('safeStorage encrypt failed', e);
    }
  }
  return ENC_PREFIX + 'b64:' + Buffer.from(String(plain), 'utf8').toString('base64');
}

function decryptSecret(stored) {
  if (!stored) return '';
  if (typeof stored !== 'string') return '';
  if (!stored.startsWith(ENC_PREFIX)) return stored; // legacy plaintext
  const payload = stored.slice(ENC_PREFIX.length);
  try {
    if (payload.startsWith('b64:')) {
      return Buffer.from(payload.slice(4), 'base64').toString('utf8');
    }
    // Legacy machine-bound safeStorage — try migrate if OS can decrypt
    if (safeStorage && safeStorage.isEncryptionAvailable()) {
      return safeStorage.decryptString(Buffer.from(payload, 'base64'));
    }
    console.warn(
      'Cannot decrypt API key (safeStorage unavailable / portable). Re-save the API key in Settings.'
    );
  } catch (e) {
    console.error('API key decrypt failed — re-save API key in Settings.', e);
  }
  return '';
}

const userDir = getUserDir();
const keysDir = path.join(userDir, 'keys');
const apiJsonPath = path.join(keysDir, 'api.json');

function loadApisRaw() {
  try {
    if (!fs.existsSync(keysDir)) fs.mkdirSync(keysDir, { recursive: true });
    if (fs.existsSync(apiJsonPath)) {
      return JSON.parse(fs.readFileSync(apiJsonPath, 'utf8')) || [];
    }
  } catch (e) {
    console.error('Failed to load api.json', e);
  }
  return [];
}

function saveApisEncrypted(list) {
  try {
    if (!fs.existsSync(keysDir)) fs.mkdirSync(keysDir, { recursive: true });
    const toStore = (list || []).map((api) => ({
      ...api,
      apiKey: encryptSecret(api.apiKey || ''),
    }));
    fs.writeFileSync(apiJsonPath, JSON.stringify(toStore, null, 2), 'utf8');
    return true;
  } catch (e) {
    console.error('Failed to save api.json', e);
    return false;
  }
}

function loadApisDecrypted() {
  const list = loadApisRaw();
  let needsRewrite = false;
  const portable = isPortableLayout();
  const out = list.map((api) => {
    const raw = api.apiKey || '';
    // Plaintext → encrypt
    if (raw && !String(raw).startsWith(ENC_PREFIX)) needsRewrite = true;
    // Portable: rewrite non-b64 (safeStorage) blobs to machine-independent b64
    if (
      portable &&
      raw &&
      String(raw).startsWith(ENC_PREFIX) &&
      !String(raw).startsWith(ENC_PREFIX + 'b64:')
    ) {
      needsRewrite = true;
    }
    return { ...api, apiKey: decryptSecret(raw) };
  });
  // Drop empty keys that failed decrypt (avoid writing blanks over salvageable raw)
  if (needsRewrite && out.length) {
    const anyKey = out.some((a) => a.apiKey);
    if (anyKey) {
      saveApisEncrypted(out);
      console.log('[Main] API keys migrated to portable storage format');
    } else if (portable) {
      console.warn(
        '[Main] Portable mode: API keys could not be decrypted. Open Settings and re-enter API key.'
      );
    }
  }
  return out;
}

// Stop Python backend process tree (Windows-safe).
// When MIKU_EXTERNAL_BACKEND=1 the backend is a *child of the launcher*, not of Electron.
// Electron must NOT taskkill it (and must never spawn PowerShell / net probes — those trip firewalls).
// Launcher watches pet_control.json + Electron exit and stops backend via its own tracked PID.
function killBackend() {
  if (isExternalBackend()) {
    if (backendStopNotified) return;
    backendStopNotified = true;
    console.log('[Main] External backend mode — notify launcher only (no taskkill / no PowerShell)');
    try {
      writePetState({ action: 'pet_closed', state: petHidden ? 'hidden' : 'visible' });
    } catch (_) {
      try {
        const ctrl = path.join(getUserDir(), 'pet_control.json');
        fs.writeFileSync(ctrl, JSON.stringify({ action: 'pet_closed', ts: Date.now() }), 'utf8');
      } catch (__) {}
    }
    backendProcess = null;
    backendPid = null;
    return;
  }
  const pids = new Set();
  if (backendPid) pids.add(Number(backendPid));
  if (backendProcess && backendProcess.pid) pids.add(Number(backendProcess.pid));

  // PID file written by backend/main.py — never scan ports / never PowerShell
  try {
    const pidFile = path.join(getUserDir(), 'backend.pid');
    if (fs.existsSync(pidFile)) {
      const raw = fs.readFileSync(pidFile, 'utf8').trim();
      const n = parseInt(raw, 10);
      if (Number.isFinite(n) && n > 0) pids.add(n);
      try { fs.unlinkSync(pidFile); } catch (_) {}
    }
  } catch (_) {}

  for (const pid of pids) {
    if (!pid) continue;
    try {
      if (process.platform === 'win32') {
        // Known PID only — never Get-NetTCPConnection / netstat via PowerShell
        execSync(`taskkill /F /T /PID ${pid}`, {
          stdio: 'ignore',
          windowsHide: true,
          timeout: 8000,
        });
      } else {
        try { process.kill(pid, 'SIGTERM'); } catch (_) {}
        try { process.kill(pid, 'SIGKILL'); } catch (_) {}
      }
    } catch (_) {
      // already exited
    }
  }

  if (backendProcess) {
    try { backendProcess.kill(); } catch (_) {}
  }
  backendProcess = null;
  backendPid = null;
  console.log('[Main] Backend kill sequence finished.');
}


function createWindow() {
  backendStopNotified = false;
  const primaryWorkArea = screen.getPrimaryDisplay().workArea;

  // Pet main window dimensions: exactly 208x208 (fits 200x200 video + margins & shadows)
  const windowWidth = 208;
  const windowHeight = 208;

  mainWindow = new BrowserWindow({
    width: windowWidth,
    height: windowHeight,
    x: primaryWorkArea.x + primaryWorkArea.width - windowWidth - 20,
    y: primaryWorkArea.y + primaryWorkArea.height - windowHeight - 20,
    type: 'toolbar',
    frame: false,
    transparent: true,
    alwaysOnTop: true,
    resizable: false,
    icon: APP_ICON,
    webPreferences: securePrefs()
  });

  mainWindow.loadFile('index.html');

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
ipcMain.on('drag-start', () => {
  if (mainWindow) {
    dragStartBounds = mainWindow.getBounds();
  }
});

ipcMain.on('window-drag', (event, delta) => {
  if (!mainWindow || !dragStartBounds) return;
  const { dx, dy } = delta;
  mainWindow.setBounds({
    x: dragStartBounds.x + dx,
    y: dragStartBounds.y + dy,
    width: dragStartBounds.width,
    height: dragStartBounds.height
  });
});

ipcMain.on('hide-pet', () => {
  applyPetVisibility(true);
});

function positionAuxiliaryWindow(window) {
  if (!window || window.isDestroyed() || !mainWindow || mainWindow.isDestroyed()) return;

  const petBounds = mainWindow.getBounds();
  const workArea = screen.getDisplayMatching(petBounds).workArea;
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

function showAuxiliaryWindow(window, temporaryTop = false) {
  if (!window || window.isDestroyed()) return;
  if (window.isMinimized()) window.restore();
  positionAuxiliaryWindow(window);
  if (temporaryTop) window.setAlwaysOnTop(true, 'floating');
  window.show();
  window.focus();
  window.moveTop();
  if (temporaryTop) {
    setTimeout(() => {
      if (window && !window.isDestroyed()) window.setAlwaysOnTop(false);
    }, 250);
  }
}

// 2. IPC listener to open settings window in a separate container
ipcMain.on('open-settings', () => {
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

    settingsWindow.setMenu(null);
    settingsWindow.loadFile(path.join(__dirname, 'settings.html')).catch((error) => {
      console.error('[Main] Settings window failed to load:', error);
    });
    settingsWindow.once('ready-to-show', () => {
      showAuxiliaryWindow(settingsWindow);
    });

    settingsWindow.on('closed', () => {
      settingsWindow = null;
    });
  } catch (error) {
    settingsWindow = null;
    console.error('[Main] Settings window failed to create:', error);
  }
});

// 3. Forward model-changed IPC message from settingsWindow to mainWindow
ipcMain.on('model-changed', (event, selectedModel) => {
  if (mainWindow) {
    mainWindow.webContents.send('change-model', selectedModel);
  }
});

// Independent Report Window
ipcMain.on('open-report', (event, data) => {
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
  });
});

ipcMain.on('action-from-report', (event, action) => {
  if (mainWindow) {
    mainWindow.webContents.send('action-from-report', action);
  }
});

function showChatWindow() {
  showAuxiliaryWindow(chatWindow, true);
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
  });
}

ipcMain.on('analyze-report-request', (event, prompt, displayPrompt) => {
  openChatWindow(() => {
    if (chatWindow && !chatWindow.isDestroyed()) {
      chatWindow.webContents.send('populate-chat-input', prompt, displayPrompt);
    }
  });
});

// ── Chat Window IPC ──
ipcMain.on('open-chat', () => {
  openChatWindow();
});

ipcMain.on('chat-message', (event, text) => {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send('forward-chat-to-backend', text);
  } else if (chatWindow && !chatWindow.isDestroyed()) {
    chatWindow.webContents.send('chat-send-failed', '桌宠主窗口未就绪');
  }
});

ipcMain.on('action-from-chat', (event, action) => {
  if (mainWindow) mainWindow.webContents.send('action-from-chat', action);
});

ipcMain.on('chat-reply-from-backend', (event, reply) => {
  if (chatWindow) chatWindow.webContents.send('chat-reply-from-backend', reply);
});

ipcMain.on('chat-send-failed', (event, reason) => {
  if (chatWindow && !chatWindow.isDestroyed()) {
    chatWindow.webContents.send('chat-send-failed', reason);
  }
});

ipcMain.on('request-chat-history', () => {
  if (mainWindow) mainWindow.webContents.send('forward-history-request-to-backend');
});

ipcMain.on('chat-history-from-backend', (event, history) => {
  if (chatWindow) chatWindow.webContents.send('chat-history-from-backend', history);
});

ipcMain.on('lang-changed', (event, lang) => {
  if (mainWindow)   mainWindow.webContents.send('lang-changed', lang);
  if (reportWindow) reportWindow.webContents.send('lang-changed', lang);
  if (chatWindow)   chatWindow.webContents.send('lang-changed', lang);
});

// Forward LLM API config change from settings window to main renderer
ipcMain.on('llm-changed', (event, config) => {
  if (mainWindow) mainWindow.webContents.send('llm-changed', config);
});

// 4. Handle window size change
ipcMain.on('size-changed', (event, size) => {
  if (!mainWindow) return;
  // Forward to renderer to recalculate with video aspect ratio
  mainWindow.webContents.send('force-adjust-size', size);
});

// 5. Dynamic window resize based on video content
ipcMain.on('resize-window', (event, { contentWidth, contentHeight, scale }) => {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  const bounds = mainWindow.getBounds();
  const display = screen.getDisplayMatching(bounds);
  const workArea = display.workArea;
  const width = Math.min(
    Math.round((contentWidth + 8) * scale),
    workArea.width,
  );
  const height = Math.min(
    Math.round((contentHeight + 8) * scale),
    workArea.height,
  );

  const cx = bounds.x + bounds.width / 2;
  const cy = bounds.y + bounds.height / 2;

  let x = Math.round(cx - width / 2);
  let y = Math.round(cy - height / 2);

  if (x + width > workArea.x + workArea.width) x = workArea.x + workArea.width - width;
  if (y + height > workArea.y + workArea.height) y = workArea.y + workArea.height - height;
  if (x < workArea.x) x = workArea.x;
  if (y < workArea.y) y = workArea.y;
  
  mainWindow.setBounds({ width, height, x, y });
  mainWindow.webContents.setZoomFactor(scale);
});

// Handle request to list available model files
ipcMain.handle('get-models', async () => {
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
ipcMain.on('run-train', () => {
  const trainBat = isPackaged()
    ? path.join(getBackendDir(), '..', 'train.bat')
    : path.join(__dirname, '..', 'train.bat');
  if (!fs.existsSync(trainBat)) {
    console.error('train.bat not found:', trainBat);
    return;
  }
  exec(`start "Miku Training" "${trainBat}"`);
});

app.on('ready', createWindow);

// Kill backend on every quit path (safety net)
app.on('before-quit', () => {
  quitting = true;
  killBackend();
});
app.on('will-quit', () => {
  killBackend();
});
app.on('quit', () => {
  killBackend();
});

// IPC: renderer asks main to launch backend
ipcMain.on('start-backend', (event, pythonExe) => {
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
  const py = pythonExe || resolvePython();
  const mainPy = path.join(backendDir, 'main.py');
  if (!fs.existsSync(mainPy)) {
    console.error('[Main] backend/main.py not found at', mainPy);
    return;
  }
  backendProcess = spawn(py, ['main.py'], {
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
    }
  });
  backendPid = backendProcess.pid;
  backendProcess.stdout.on('data', d => process.stdout.write('[Backend] ' + d));
  backendProcess.stderr.on('data', d => process.stderr.write('[Backend] ' + d));
  backendProcess.on('exit', code => {
    console.log(`[Backend] exited with code ${code}`);
    backendProcess = null;
    backendPid = null;
    try {
      const pidFile = path.join(getUserDir(), 'backend.pid');
      if (fs.existsSync(pidFile)) fs.unlinkSync(pidFile);
    } catch (_) {}
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
    fs.writeFileSync(configJsonPath, JSON.stringify(config, null, 2), 'utf8');
  } catch (e) {
    console.error('Failed to save config.json', e);
  }
}

ipcMain.handle('get-app-version', () => {
  return app.getVersion();
});

ipcMain.on('get-config', (event, key) => {
  const config = loadConfig();
  event.returnValue = config[key] !== undefined ? config[key] : null;
});

ipcMain.on('set-config', (event, data) => {
  const { key, val } = data;
  const config = loadConfig();
  if (val === null || val === undefined) {
    delete config[key];
  } else {
    config[key] = val;
  }
  saveConfig(config);
});

// ── Encrypted API key storage (main-process only) ───────────────────────────
ipcMain.handle('apis-load', () => {
  return loadApisDecrypted();
});

ipcMain.handle('apis-save', (event, list) => {
  return saveApisEncrypted(list || []);
});

/** Return currently selected LLM config with decrypted key (for backend sync). */
ipcMain.handle('get-selected-llm', () => {
  const config = loadConfig();
  const selId = config['miku-sel-api'] || '';
  const model = config['miku-sel-model'] || '';
  const apis = loadApisDecrypted();
  const api = apis.find((a) => a.id === selId);
  if (!api) return { baseUrl: '', apiKey: '', model: '' };
  return { baseUrl: api.baseUrl || '', apiKey: api.apiKey || '', model };
});

ipcMain.handle('has-lora', () => {
  const loraDir = path.join(getUserDir(), 'lora');
  try {
    if (!fs.existsSync(loraDir)) return false;
    return fs.readdirSync(loraDir).some((f) => f.endsWith('.safetensors') || f.endsWith('.pth'));
  } catch {
    return false;
  }
});

/** Media / project path helpers for renderer (packaged-safe). */
ipcMain.handle('get-paths', () => {
  return {
    resources: path.dirname(getBackendDir()),
    backend: getBackendDir(),
    miku: getMikuDir(),
    user: getUserDir(),
    packaged: isPackaged(),
    python: resolvePython(),
  };
});
