const { app, BrowserWindow, screen, ipcMain } = require('electron');
const path = require('path');
const { spawn } = require('child_process');

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

// 1. IPC listener for custom window dragging
ipcMain.on('window-drag', (event, delta) => {
  if (!mainWindow) return;
  const { dx, dy } = delta;
  const [x, y] = mainWindow.getPosition();
  mainWindow.setPosition(x + dx, y + dy);
});

// 2. IPC listener to open settings window in a separate container
ipcMain.on('open-settings', () => {
  if (settingsWindow) {
    settingsWindow.focus();
    return;
  }

  settingsWindow = new BrowserWindow({
    width: 320,
    height: 240,
    title: "模型选择与设置",
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
