/**
 * Resolve project resource roots for:
 *  - Dev:          frontend/ next to backend/, miku/, user/
 *  - Portable zip: same layout + runtime/python
 *  - electron-builder: extraResources under process.resourcesPath
 */
const path = require('path');
const fs = require('fs');
const { app } = require('electron');

function isPackaged() {
  try {
    return !!(app && app.isPackaged);
  } catch {
    return false;
  }
}

function isExternalBackend() {
  return process.env.MIKU_EXTERNAL_BACKEND === '1';
}

/** Project root (dev / portable) or resources root (electron-builder). */
function getResourcesRoot() {
  if (process.env.MIKU_PROJECT_ROOT) {
    return path.resolve(process.env.MIKU_PROJECT_ROOT);
  }
  if (process.env.MIKU_RESOURCES) {
    return path.resolve(process.env.MIKU_RESOURCES);
  }
  if (isPackaged()) {
    return process.resourcesPath;
  }
  // frontend/ is one level under project root
  return path.join(__dirname, '..');
}

function getBackendDir() {
  return path.join(getResourcesRoot(), 'backend');
}

function getMikuDir() {
  return path.join(getResourcesRoot(), 'miku');
}

function getUserDir() {
  if (process.env.MIKU_USER_DIR) {
    const ud = path.resolve(process.env.MIKU_USER_DIR);
    try {
      fs.mkdirSync(path.join(ud, 'keys'), { recursive: true });
      fs.mkdirSync(path.join(ud, 'lora'), { recursive: true });
      fs.mkdirSync(path.join(ud, 'memorize'), { recursive: true });
    } catch (_) {}
    return ud;
  }
  // Prefer writable userData only for classic electron-builder installs
  if (isPackaged() && app && !process.env.MIKU_PROJECT_ROOT) {
    const ud = path.join(app.getPath('userData'), 'user');
    if (!fs.existsSync(ud)) {
      try {
        fs.mkdirSync(ud, { recursive: true });
        fs.mkdirSync(path.join(ud, 'keys'), { recursive: true });
        fs.mkdirSync(path.join(ud, 'lora'), { recursive: true });
        fs.mkdirSync(path.join(ud, 'memorize'), { recursive: true });
      } catch (e) {
        console.error('Failed to create userData user dir', e);
      }
    }
    return ud;
  }
  return path.join(getResourcesRoot(), 'user');
}

function getPythonCandidates() {
  const root = getResourcesRoot();
  const backend = getBackendDir();
  const list = [];
  if (process.platform === 'win32') {
    // Portable embeddable runtime first
    list.push(path.join(root, 'runtime', 'python', 'python.exe'));
    list.push(path.join(backend, '.venv', 'Scripts', 'python.exe'));
    list.push(path.join(backend, 'python', 'python.exe'));
  } else {
    list.push(path.join(root, 'runtime', 'python', 'bin', 'python'));
    list.push(path.join(backend, '.venv', 'bin', 'python'));
  }
  list.push('python');
  return list;
}

function resolvePython() {
  for (const p of getPythonCandidates()) {
    if (p === 'python' || fs.existsSync(p)) return p;
  }
  return 'python';
}

module.exports = {
  isPackaged,
  isExternalBackend,
  getResourcesRoot,
  getBackendDir,
  getMikuDir,
  getUserDir,
  resolvePython,
  getPythonCandidates,
};
