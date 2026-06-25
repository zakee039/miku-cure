const { app, BrowserWindow, screen, ipcMain } = require('electron');
const path = require('path');
const { spawn, execSync } = require('child_process');

// RTX 5060 Blackwell GPU is not supported by Electron's GPU process (sm_120).
// Disable hardware acceleration to prevent GPU process crashes.
app.disableHardwareAcceleration();

let mainWindow;
let settingsWindow = null;
let reportWindow = null;
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
    webPreferences: {
      nodeIntegration: true,
      contextIsolation: false
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

ipcMain.on('lang-changed', (event, lang) => {
  if (mainWindow)   mainWindow.webContents.send('lang-changed', lang);
  if (reportWindow) reportWindow.webContents.send('lang-changed', lang);
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
    stdio: ['ignore', 'pipe', 'pipe']
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
