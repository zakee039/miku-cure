const { app, BrowserWindow, screen, ipcMain } = require('electron');
const path = require('path');
const { spawn } = require('child_process');

// RTX 5060 Blackwell GPU is not supported by Electron's GPU process (sm_120).
// Disable hardware acceleration to prevent GPU process crashes.
app.disableHardwareAcceleration();

let mainWindow;
let settingsWindow = null;
let backendProcess = null;


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
    mainWindow = null;
    if (settingsWindow) {
      settingsWindow.close();
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

// 4. Handle window size change
ipcMain.on('size-changed', (event, size) => {
  if (!mainWindow) return;
  let scale = 1.0;
  if (size === 'small') scale = 0.67;
  else if (size === 'large') scale = 1.5;
  
  const width = Math.round(208 * scale);
  const height = Math.round(208 * scale);
  mainWindow.setSize(width, height);
  mainWindow.webContents.setZoomFactor(scale);
});

app.on('ready', createWindow);

// Kill backend process when Electron fully quits
app.on('will-quit', () => {
  if (backendProcess) {
    try { backendProcess.kill(); } catch (e) {}
    backendProcess = null;
  }
});

// IPC: renderer asks main to launch backend
ipcMain.on('start-backend', (event, pythonExe) => {
  if (backendProcess) return; // already running
  const backendDir = path.join(__dirname, '..', 'backend');
  backendProcess = spawn(pythonExe, ['main.py'], {
    cwd: backendDir,
    stdio: ['ignore', 'pipe', 'pipe']
  });
  backendProcess.stdout.on('data', d => process.stdout.write('[Backend] ' + d));
  backendProcess.stderr.on('data', d => process.stderr.write('[Backend] ' + d));
  backendProcess.on('exit', code => {
    console.log(`[Backend] exited with code ${code}`);
    backendProcess = null;
  });
  console.log('[Main] Backend process started, PID:', backendProcess.pid);
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
