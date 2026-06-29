const { app, BrowserWindow, screen, ipcMain } = require('electron');
const path = require('path');
const fs = require('fs');
const { spawn, execSync, exec } = require('child_process');

// Set application name for Task Manager and Taskbar
app.name = 'miku cure';
if (process.platform === 'win32') {
  app.setAppUserModelId('miku cure');
}

// RTX 5060 Blackwell GPU is not supported by Electron's GPU process (sm_120).
// Disable hardware acceleration to prevent GPU process crashes.
app.disableHardwareAcceleration();

let mainWindow;
let settingsWindow = null;
let reportWindow = null;
let chatWindow = null;
let backendProcess = null;
let backendPid = null;

// Force-kill the Python backend process tree (Windows-safe)
function killBackend() {
  if (!backendProcess && !backendPid) return;
  const pid = backendPid || (backendProcess && backendProcess.pid);
  if (pid) {
    try {
      // On Windows: kill entire process tree recursively
      if (process.platform === 'win32') {
        execSync(`taskkill /F /T /PID ${pid}`, { stdio: 'ignore' });
      } else {
        process.kill(-pid, 'SIGKILL'); // Unix: kill process group
      }
    } catch (e) {
      // Process may have already exited
    }
  }
  backendProcess = null;
  backendPid = null;
}


function createWindow() {
  const { width: screenWidth, height: screenHeight } = screen.getPrimaryDisplay().workAreaSize;

  // Pet main window dimensions: exactly 208x208 (fits 200x200 video + margins & shadows)
  const windowWidth = 208;
  const windowHeight = 208;

  mainWindow = new BrowserWindow({
    width: windowWidth,
    height: windowHeight,
    x: screenWidth - windowWidth - 20, // Position at bottom right
    y: screenHeight - windowHeight - 20,
    type: 'toolbar',
    frame: false,
    transparent: true,
    alwaysOnTop: true,
    resizable: false,
    icon: path.join(__dirname, 'assets', 'miku.ico'),
    webPreferences: {
      nodeIntegration: true,
      contextIsolation: false,
      preload: path.join(__dirname, 'preload.js')
    }
  });

  mainWindow.loadFile('index.html');

  mainWindow.on('closed', function () {
    // Kill backend immediately when the main window is closed
    killBackend();
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

// 2. IPC listener to open settings window in a separate container
ipcMain.on('open-settings', () => {
  if (settingsWindow) {
    settingsWindow.focus();
    return;
  }

  settingsWindow = new BrowserWindow({
    width: 720,
    height: 480,
    title: "Miku Settings",
    resizable: false,
    minimizable: false,
    maximizable: false,
    icon: path.join(__dirname, 'assets', 'miku.ico'),
    webPreferences: {
      nodeIntegration: true,
      contextIsolation: false,
      webSecurity: false
    }
  });

  settingsWindow.setMenu(null);
  settingsWindow.loadFile('settings.html');

  settingsWindow.on('closed', () => {
    settingsWindow = null;
  });
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
    reportWindow.focus();
    reportWindow.webContents.send('load-report', data);
    return;
  }

  reportWindow = new BrowserWindow({
    width: 400,
    height: 520,
    title: "专注周期总结报告",
    resizable: false,
    minimizable: false,
    maximizable: false,
    icon: path.join(__dirname, 'assets', 'miku.ico'),
    webPreferences: {
      nodeIntegration: true,
      contextIsolation: false
    }
  });

  reportWindow.setMenu(null);
  reportWindow.loadFile('report.html');
  
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

ipcMain.on('analyze-report-request', (event, prompt, displayPrompt) => {
  if (!chatWindow) {
    chatWindow = new BrowserWindow({
      width: 400,
      height: 520,
      title: "Miku Chat",
      resizable: false,
      minimizable: false,
      maximizable: false,
      icon: path.join(__dirname, 'assets', 'miku.ico'),
      webPreferences: {
        nodeIntegration: true,
        contextIsolation: false
      }
    });
    chatWindow.setMenu(null);
    chatWindow.loadFile('chat.html');
    chatWindow.on('closed', () => {
      chatWindow = null;
    });
    
    chatWindow.webContents.on('did-finish-load', () => {
      chatWindow.webContents.send('populate-chat-input', prompt, displayPrompt);
    });
  } else {
    chatWindow.focus();
    chatWindow.webContents.send('populate-chat-input', prompt, displayPrompt);
  }
});

// ── Chat Window IPC ──
ipcMain.on('open-chat', () => {
  if (chatWindow) {
    chatWindow.focus();
    return;
  }
  chatWindow = new BrowserWindow({
    width: 400,
    height: 520,
    title: "Miku Chat",
    resizable: false,
    minimizable: false,
    maximizable: false,
    icon: path.join(__dirname, 'assets', 'miku.ico'),
    webPreferences: {
      nodeIntegration: true,
      contextIsolation: false
    }
  });
  chatWindow.setMenu(null);
  chatWindow.loadFile('chat.html');
  chatWindow.on('closed', () => {
    chatWindow = null;
  });
});

ipcMain.on('chat-message', (event, text) => {
  if (mainWindow) mainWindow.webContents.send('forward-chat-to-backend', text);
});

ipcMain.on('action-from-chat', (event, action) => {
  if (mainWindow) mainWindow.webContents.send('action-from-chat', action);
});

ipcMain.on('chat-reply-from-backend', (event, reply) => {
  if (chatWindow) chatWindow.webContents.send('chat-reply-from-backend', reply);
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
  if (!mainWindow) return;
  const width = Math.round((contentWidth + 8) * scale);
  const height = Math.round((contentHeight + 8) * scale);
  
  const bounds = mainWindow.getBounds();
  const cx = bounds.x + bounds.width / 2;
  const cy = bounds.y + bounds.height / 2;
  
  let x = Math.round(cx - width / 2);
  let y = Math.round(cy - height / 2);
  
  const workArea = screen.getPrimaryDisplay().workArea;
  if (x + width > workArea.x + workArea.width) x = workArea.x + workArea.width - width;
  if (y + height > workArea.y + workArea.height) y = workArea.y + workArea.height - height;
  if (x < workArea.x) x = workArea.x;
  if (y < workArea.y) y = workArea.y;
  
  mainWindow.setBounds({ width, height, x, y });
  mainWindow.webContents.setZoomFactor(scale);
});

// ── DeepFace Download IPC ──
ipcMain.handle('check-deepface', () => {
  const os = require('os');
  const targetPath = path.join(os.homedir(), '.deepface', 'weights', 'facial_expression_model_weights.h5');
  return fs.existsSync(targetPath);
});

ipcMain.on('download-deepface', () => {
  if (mainWindow) {
    mainWindow.webContents.send('forward-download-deepface-to-backend');
  }
});

ipcMain.on('deepface-download-status', (event, data) => {
  if (settingsWindow) {
    settingsWindow.webContents.send('deepface-download-status', data);
  }
});

// Handle request to list available model files
ipcMain.handle('get-models', async () => {
  const modelsDir = path.join(__dirname, '..', 'backend', 'models');
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
  const trainBat = path.join(__dirname, '..', 'train.bat');
  // Use start command to open a new terminal window completely independent of this process
  exec(`start "Miku Training" "${trainBat}"`);
});

app.on('ready', createWindow);

// Kill backend process when Electron fully quits (safety net)
app.on('will-quit', () => {
  killBackend();
});

// IPC: renderer asks main to launch backend
ipcMain.on('start-backend', (event, pythonExe) => {
  if (backendProcess) return; // already running
  const backendDir = path.join(__dirname, '..', 'backend');
  backendProcess = spawn(pythonExe, ['main.py'], {
    cwd: backendDir,
    detached: false,          // keep bound to Electron
    stdio: ['ignore', 'pipe', 'pipe'],
    env: { ...process.env, PYTHONUNBUFFERED: '1' }
  });
  backendPid = backendProcess.pid;
  backendProcess.stdout.on('data', d => process.stdout.write('[Backend] ' + d));
  backendProcess.stderr.on('data', d => process.stderr.write('[Backend] ' + d));
  backendProcess.on('exit', code => {
    console.log(`[Backend] exited with code ${code}`);
    backendProcess = null;
    backendPid = null;
  });
  console.log('[Main] Backend process started, PID:', backendPid);
});

app.on('window-all-closed', function () {
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
const userDir = path.join(__dirname, '..', 'user');
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
