const fs = require('fs');
const path = require('path');
const { ipcRenderer } = require('electron');
const { t, applyI18n } = require('./i18n');

// Resolve media roots (dev / portable / electron-builder)
function resolveMediaDirs() {
  const candidates = [
    process.env.MIKU_PROJECT_ROOT ? path.join(process.env.MIKU_PROJECT_ROOT, 'miku') : null,
    process.env.MIKU_RESOURCES ? path.join(process.env.MIKU_RESOURCES, 'miku') : null,
    path.join(__dirname, '..', 'miku'),
    process.resourcesPath ? path.join(process.resourcesPath, 'miku') : null,
  ].filter(Boolean);
  for (const root of candidates) {
    if (fs.existsSync(root)) {
      return {
        projectRoot: path.dirname(root),
        gifDir: path.join(root, 'gif'),
        danceDir: path.join(root, 'dance'),
        singDir: path.join(root, 'sing'),
      };
    }
  }
  const fallback = path.join(__dirname, '..', 'miku');
  return {
    projectRoot: path.join(__dirname, '..'),
    gifDir: path.join(fallback, 'gif'),
    danceDir: path.join(fallback, 'dance'),
    singDir: path.join(fallback, 'sing'),
  };
}
const { projectRoot, gifDir, danceDir, singDir } = resolveMediaDirs();
const assetsDir = path.join(__dirname, 'assets');

// Cache resource file lists
let gifFiles = [];
let danceFiles = [];
let singFiles = [];

// Special state videos for the sing player
const SING_VIDEO  = 'MIKU-SING.mp4';
const PAUSE_VIDEO = 'MIKU-PAUSE.mp4';
const SPECIAL_VIDEOS = new Set([SING_VIDEO, PAUSE_VIDEO]);
const VIDEO_EXTENSIONS = new Set(['.mp4', '.webm', '.mkv', '.mov', '.avi', '.m4v']);
const IMAGE_EXTENSIONS = new Set(['.gif', '.png', '.jpg', '.jpeg', '.webp', '.bmp']);
const AUDIO_EXTENSIONS = new Set(['.ogg', '.mp3', '.wav', '.m4a', '.aac', '.flac']);

function hasExtension(filename, extensions) {
  return extensions.has(path.extname(filename).toLowerCase());
}

try {
  if (fs.existsSync(gifDir)) {
    // Exclude special sing-player videos from daily rotation
    gifFiles = fs.readdirSync(gifDir).filter(f =>
      (hasExtension(f, VIDEO_EXTENSIONS) || hasExtension(f, IMAGE_EXTENSIONS)) && !SPECIAL_VIDEOS.has(f)
    );
  }
  if (fs.existsSync(danceDir)) {
    danceFiles = fs.readdirSync(danceDir).filter(f => hasExtension(f, VIDEO_EXTENSIONS));
  }
  if (fs.existsSync(singDir)) {
    singFiles = fs.readdirSync(singDir).filter(f => hasExtension(f, AUDIO_EXTENSIONS));
  }
} catch (err) {
  console.error("Error reading Miku directories:", err);
}

// Helper: switch Miku video to a specific file in assets dir (looped, muted)
function playSingStateVideo(filename) {
  const p = path.join(assetsDir, filename);
  if (!fs.existsSync(p)) {
    // Fallback to normal daily GIF if special video not found
    playRandomDailyVideo();
    return;
  }
  clearTimeout(rotationTimer);
  mikuImage.style.display = 'none';
  mikuImage.removeAttribute('src');
  mikuVideo.style.display = 'block';
  const targetSrc = 'file:///' + p.replace(/\\/g, '/');
  
  // Prevent restarting the video if it's already playing the target file
  if (mikuVideo.src === targetSrc || decodeURI(mikuVideo.src) === targetSrc) {
    return;
  }
  
  mikuVideo.src = targetSrc;
  mikuVideo.muted = true;
  mikuVideo.loop = true;
  mikuVideo.play().catch(err => console.error('Sing-state video error:', err));
}

// DOM Elements
const mikuVideo = document.getElementById('miku-video');
const mikuImage = document.getElementById('miku-image');
const closeBtn = document.getElementById('close-btn');
const chatBubble = document.getElementById('chat-bubble');
const chatText = document.getElementById('chat-text');

const bubbleDance = document.getElementById('bubble-dance');
const bubbleSing = document.getElementById('bubble-sing');
const bubbleDismiss = document.getElementById('bubble-dismiss');

const carePopup = document.getElementById('care-popup');
const careText = document.getElementById('care-text');
const careChatBtn = document.getElementById('care-chat-btn');
const careDismissBtn = document.getElementById('care-dismiss-btn');

const timerPanel = document.getElementById('timer-panel');
const timerToggle = document.getElementById('timer-toggle');
const durationInput = document.getElementById('duration-input');
const startBtn = document.getElementById('start-btn');
const timerSetup = document.getElementById('timer-setup');
const timerActive = document.getElementById('timer-active');
const countdownDisplay = document.getElementById('countdown');
const pauseBtn = document.getElementById('pause-btn');
const stopBtn = document.getElementById('stop-btn');

const settingsToggle = document.getElementById('settings-toggle');
const talentToggle = document.getElementById('talent-toggle');
const talentPanel = document.getElementById('talent-panel');

const actionDance = document.getElementById('action-dance');
const actionSing  = document.getElementById('action-sing');
const actionChat  = document.getElementById('action-chat');

const mediaPlayerPanel = document.getElementById('media-player-panel');
const danceControlsPanel = document.getElementById('dance-controls-panel');
const danceNextBtn     = document.getElementById('dance-next');
const danceCloseBtn    = document.getElementById('dance-close');
const songTitle = document.getElementById('song-title');
const playerPrev = document.getElementById('player-prev');
const playerPlay = document.getElementById('player-play');
const playerNext = document.getElementById('player-next');
const playerClose = document.getElementById('player-close');

// App state
let mikuState = 'daily'; // 'daily', 'dancing', 'singing'
let currentAudio = null;
let rotationTimer = null;
let pomodoroTimer = null;
let focusTimeTotal = 30 * 60; // in seconds
let focusTimeRemaining = 30 * 60;
let isPaused = false;
let ws = null;
let focusStartTimeStr = "";
let currentSingIndex = 0;
let currentDanceIndex = 0;
let isPlayingSing = false;
let currentModelType = ipcRenderer.sendSync('get-config', 'miku-model-type') || 'best_rnn_attention.pth';

function showMediaFile(filePath, { muted = true, loop = true } = {}) {
  const source = 'file:///' + filePath.replace(/\\/g, '/');
  if (hasExtension(filePath, IMAGE_EXTENSIONS)) {
    mikuVideo.pause();
    mikuVideo.style.display = 'none';
    mikuImage.src = source;
    mikuImage.style.display = 'block';
    return Promise.resolve();
  }
  mikuImage.style.display = 'none';
  mikuImage.removeAttribute('src');
  mikuVideo.style.display = 'block';
  mikuVideo.src = source;
  mikuVideo.muted = muted;
  mikuVideo.loop = loop;
  return mikuVideo.play();
}
// Migrate obsolete engines (DeepFace fully removed) → default RNN
{
  const mt = String(currentModelType || '').toLowerCase();
  if (mt === 'deepface' || mt === 'df' || mt.includes('deepface') || mt === 'cnn') {
    currentModelType = 'best_rnn_attention.pth';
    ipcRenderer.send('set-config', { key: 'miku-model-type', val: currentModelType });
  }
}



// The pet close icon always hides the widget; services keep running.
closeBtn.addEventListener('click', () => {
  ipcRenderer.send('hide-pet');
});

// Custom JS-Based Window Dragging (Drift-free)
let isDragging = false;
let mouseStartX, mouseStartY;

document.addEventListener('mousedown', (e) => {
  if (
    e.target.closest('button') || 
    e.target.closest('input') || 
    e.target.closest('.settings-panel') || 
    e.target.closest('.report-card') ||
    e.target.closest('.timer-overlay') ||
    e.target.closest('.talent-overlay') ||
    e.target.closest('.media-player-overlay') ||
    e.target.closest('.emotion-badge')
  ) {
    return;
  }
  isDragging = true;
  mouseStartX = e.screenX;
  mouseStartY = e.screenY;
  ipcRenderer.send('drag-start');
});

document.addEventListener('mousemove', (e) => {
  if (!isDragging) return;
  const dx = e.screenX - mouseStartX;
  const dy = e.screenY - mouseStartY;
  ipcRenderer.send('window-drag', { dx, dy });
});

document.addEventListener('mouseup', () => {
  isDragging = false;
});

// Emotion badge click to toggle camera
let isCameraConnected = false;
let isCameraConnecting = false;
const emotionBadge = document.getElementById('emotion-badge');

function renderCameraConnectionState() {
  const emojiEl = document.getElementById('emotion-emoji');
  const labelEl = document.getElementById('emotion-label');
  const confEl = document.getElementById('emotion-conf');
  if (isCameraConnecting) {
    if (labelEl) {
      labelEl.textContent = t('emotion.connecting');
      labelEl.removeAttribute('data-i18n');
    }
    if (confEl) confEl.textContent = '--%';
  } else if (!isCameraConnected) {
    if (emojiEl) emojiEl.textContent = '🔌';
    if (labelEl) {
      labelEl.textContent = t('emotion.disconnected');
      labelEl.removeAttribute('data-i18n');
    }
    if (confEl) confEl.textContent = '--%';
  }
}

if (emotionBadge) {
  renderCameraConnectionState();
  emotionBadge.addEventListener('click', () => {
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      isCameraConnected = false;
      isCameraConnecting = false;
      renderCameraConnectionState();
      return;
    }

    const shouldConnect = !isCameraConnected && !isCameraConnecting;
    isCameraConnecting = shouldConnect;
    if (!shouldConnect) isCameraConnected = false;
    renderCameraConnectionState();
    ws.send(JSON.stringify({ type: 'toggle_camera', state: shouldConnect }));
  });
}

// 2. Miku Animation Player State Machine
function playRandomDailyVideo() {
  if (mikuState !== 'daily') return;
  if (gifFiles.length === 0) {
    console.warn("No supported animation or image files found in miku/gif/");
    return;
  }
  const randomFile = gifFiles[Math.floor(Math.random() * gifFiles.length)];
  showMediaFile(path.join(gifDir, randomFile)).catch(err => console.error("Playback error:", err));

  // Set rotation timer for 30s
  clearTimeout(rotationTimer);
  rotationTimer = setTimeout(playRandomDailyVideo, 30000);
}

// Double click to switch GIF
document.getElementById('miku-display').addEventListener('dblclick', (event) => {
  if (event.target.closest('button, input, .emotion-badge')) return;
  if (mikuState === 'daily') {
    playRandomDailyVideo();
  }
});

// 3. Play Dance mode
function startDance(index = null) {
  if (danceFiles.length === 0) {
    showChatBubble(t('status.no_dance'), false);
    return;
  }
  clearTimeout(rotationTimer);
  if (currentAudio) {
    currentAudio.pause();
    currentAudio = null;
  }
  mikuState = 'dancing';
  hideChatBubble();
  talentPanel.classList.add('hide');
  timerPanel.classList.add('hide');
  mediaPlayerPanel.classList.add('hide');
  danceControlsPanel.classList.remove('hide');  // show controls
  // Fold the header bar up during dance
  document.getElementById('viewport-header').classList.add('header-folded');
  
  if (index === null || typeof index !== 'number') {
    currentDanceIndex = Math.floor(Math.random() * danceFiles.length);
  } else {
    currentDanceIndex = (index + danceFiles.length) % danceFiles.length;
  }
  
  const randomFile = danceFiles[currentDanceIndex];
  mikuImage.style.display = 'none';
  mikuVideo.style.display = 'block';
  mikuVideo.src = 'file:///' + path.join(danceDir, randomFile).replace(/\\/g, '/');
  mikuVideo.muted = false;
  mikuVideo.loop = false;
  
  updateStatus(t('status.dancing'), "#ff5f56");
  
  mikuVideo.play().catch(err => {
    console.error("Dance video play error:", err);
    stopSingOrDance();
  });
}

// 4. Play Sing mode (Playlist Player)
function startSingPlaylist(index = 0) {
  if (singFiles.length === 0) {
    showChatBubble(t('status.no_sing'), false);
    return;
  }
  clearTimeout(rotationTimer);
  mikuState = 'singing';
  isPlayingSing = true;
  hideChatBubble();
  talentPanel.classList.add('hide');
  timerPanel.classList.add('hide');
  mediaPlayerPanel.classList.remove('hide');
  
  currentSingIndex = (index + singFiles.length) % singFiles.length;
  const randomFile = singFiles[currentSingIndex];
  
  if (currentAudio) {
    currentAudio.pause();
  }
  
  currentAudio = new Audio('file:///' + path.join(singDir, randomFile).replace(/\\/g, '/'));
  if (typeof currentVolume !== 'undefined') currentAudio.volume = currentVolume;
  currentAudio.play().catch(err => {
    console.error("Sing audio play error:", err);
    stopSingOrDance();
  });
  
  songTitle.textContent = randomFile;
  playerPlay.textContent = "||";
  updateStatus(t('status.singing'), "#bf73ff");
  
  // Show MIKU-SING looping video while music is playing
  playSingStateVideo(SING_VIDEO);
  
  currentAudio.onended = () => {
    // Auto next song
    startSingPlaylist(currentSingIndex + 1);
  };
}

// Stop special activities and return to daily animation
function stopSingOrDance() {
  if (currentAudio) {
    currentAudio.pause();
    currentAudio = null;
  }
  mikuState = 'daily';
  isPlayingSing = false;
  mikuVideo.loop = true;
  mikuVideo.muted = true;
  mediaPlayerPanel.classList.add('hide');
  danceControlsPanel.classList.add('hide');  // hide controls
  // Restore header
  document.getElementById('viewport-header').classList.remove('header-folded');
  updateStatus(t('status.idle'), "#39c5bb");
  playRandomDailyVideo();
}

// When video ends (useful for dance mode)
mikuVideo.addEventListener('ended', () => {
  if (mikuState === 'dancing') {
    stopSingOrDance();
  }
});

// UI Event Handlers for overlays
bubbleDance.addEventListener('click', startDance);
bubbleSing.addEventListener('click', () => startSingPlaylist(Math.floor(Math.random() * singFiles.length)));
bubbleDismiss.addEventListener('click', () => {
  hideChatBubble();
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: 'bubble_dismissed' }));
  }
});

// Care Popup Event Handlers
careChatBtn.addEventListener('click', () => {
  hideCarePopup();
  ipcRenderer.send('open-chat');
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: 'care_popup_dismissed' }));
    ws.send(JSON.stringify({ 
      type: 'chat_request', 
      text: t('btn.care_chat'), 
      hidden_context: "[System]: The user just clicked 'Chat' from a proactive care popup because they were feeling negative emotions recently. Please start the conversation by gently asking what's bothering them and offer your comfort."
    }));
  }
});

careDismissBtn.addEventListener('click', () => {
  hideCarePopup();
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: 'care_popup_dismissed' }));
  }
});

actionDance.addEventListener('click', startDance);
actionSing.addEventListener('click', () => startSingPlaylist(Math.floor(Math.random() * singFiles.length)));
actionChat.addEventListener('click', () => {
  ipcRenderer.send('open-chat');
  talentPanel.classList.add('hide');
});

// Media player controls
playerPrev.addEventListener('click', () => {
  startSingPlaylist(currentSingIndex - 1);
});

playerNext.addEventListener('click', () => {
  startSingPlaylist(currentSingIndex + 1);
});

playerPlay.addEventListener('click', () => {
  if (!currentAudio) return;
  if (isPlayingSing) {
    currentAudio.pause();
    isPlayingSing = false;
    playerPlay.textContent = "▶";
    updateStatus(t('status.paused'), "#bf73ff");
    // Switch to MIKU-PAUSE looping video
    playSingStateVideo(PAUSE_VIDEO);
  } else {
    currentAudio.play().catch(e => console.error(e));
    isPlayingSing = true;
    playerPlay.textContent = "||";
    updateStatus(t('status.singing'), "#bf73ff");
    // Switch back to MIKU-SING looping video
    playSingStateVideo(SING_VIDEO);
  }
});

playerClose.addEventListener('click', () => {
  stopSingOrDance();
});

danceNextBtn.addEventListener('click', () => {
  startDance(currentDanceIndex + 1);
});

danceCloseBtn.addEventListener('click', () => {
  stopSingOrDance();
});

// Chat Bubble helpers
function showChatBubble(text, showActions = true) {
  chatText.textContent = text;
  if (showActions) {
    bubbleDance.classList.remove('hide');
    bubbleSing.classList.remove('hide');
  } else {
    bubbleDance.classList.add('hide');
    bubbleSing.classList.add('hide');
  }
  chatBubble.classList.remove('hide');
}

function hideChatBubble() {
  chatBubble.classList.add('hide');
}

// Care Popup helpers
function showCarePopup(text) {
  careText.textContent = text;
  carePopup.classList.remove('hide');
}

function hideCarePopup() {
  carePopup.classList.add('hide');
}

// 5. Settings toggle (opens separate settings window)
settingsToggle.addEventListener('click', () => {
  timerPanel.classList.add('hide');
  talentPanel.classList.add('hide');
  ipcRenderer.send('open-settings');
});

// Talent toggle star button click
talentToggle.addEventListener('click', () => {
  const isHidden = talentPanel.classList.contains('hide');
  timerPanel.classList.add('hide');
  
  if (isHidden) {
    talentPanel.classList.remove('hide');
  } else {
    talentPanel.classList.add('hide');
  }
});

// 6. Pomodoro Focus Timer Logic
timerToggle.addEventListener('click', () => {
  const isHidden = timerPanel.classList.contains('hide');
  talentPanel.classList.add('hide');
  
  if (isHidden) {
    timerPanel.classList.remove('hide');
  } else {
    timerPanel.classList.add('hide');
  }
});

// IPC Listener for dynamic model changes from Settings Window
ipcRenderer.on('change-model', (event, selectedModel) => {
  currentModelType = selectedModel;
  console.log("Renderer: Received model change command from IPC:", selectedModel);
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({
      type: 'change_model',
      model_type: selectedModel
    }));
  }
});

// When user changes LLM in settings, force re-sync is not needed — llm-changed IPC already forwards.

startBtn.addEventListener('click', () => {
  const mins = parseInt(durationInput.value) || 30;
  focusTimeTotal = mins * 60;
  focusTimeRemaining = focusTimeTotal;
  isPaused = false;
  
  const now = new Date();
  focusStartTimeStr = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

  // Update layout UI
  timerSetup.classList.add('hide');
  timerActive.classList.remove('hide');
  timerPanel.classList.add('is-active');
  updateCountdownDisplay();
  
  // Notify Python Backend
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({
      type: 'start_focus',
      duration_minutes: mins
    }));
  }
  
  updateStatus(t('status.focus', { min: mins }), "#39c5bb");

  // Start timer interval
  clearInterval(pomodoroTimer);
  pomodoroTimer = setInterval(tickTimer, 1000);
});

// Add wheel support for duration input
durationInput.addEventListener('wheel', (e) => {
  e.preventDefault();
  let val = parseInt(durationInput.value) || 30;
  if (e.deltaY < 0) {
    val += 1;
  } else {
    val -= 1;
  }
  if (val < 1) val = 1;
  if (val > 180) val = 180;
  durationInput.value = val;
});

function updateCountdownDisplay() {
  const m = Math.floor(focusTimeRemaining / 60).toString().padStart(2, '0');
  const s = (focusTimeRemaining % 60).toString().padStart(2, '0');
  countdownDisplay.textContent = `${m}:${s}`;
}

function tickTimer() {
  if (isPaused) return;
  
  if (focusTimeRemaining > 0) {
    focusTimeRemaining--;
    updateCountdownDisplay();
  } else {
    // Timer reached 0!
    clearInterval(pomodoroTimer);
    timerActive.classList.add('hide');
    timerSetup.classList.remove('hide');
    timerPanel.classList.add('hide');
    timerPanel.classList.remove('is-active');
    
    // Notify Backend & requesting end-of-period report
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({
        type: 'end_focus',
        completed: true
      }));
    }
  }
}

pauseBtn.addEventListener('click', () => {
  isPaused = !isPaused;
  pauseBtn.textContent = isPaused ? "►" : "||";
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: 'pause_focus', paused: isPaused }));
  }
});

stopBtn.addEventListener('click', () => {
  clearInterval(pomodoroTimer);
  timerActive.classList.add('hide');
  timerSetup.classList.remove('hide');
  timerPanel.classList.add('hide');
  timerPanel.classList.remove('is-active');
  updateStatus(t('status.interrupted'), "#ff5f56");
  
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({
      type: 'end_focus',
      completed: false
    }));
  }
});

// Dummy updateStatus for compatibility
function updateStatus(text, color) {
  console.log("Status changed:", text);
}

// 7. WebSocket connection to Python Backend (ready handshake + exponential backoff)
let wsRetryDelay = 1000;
const WS_RETRY_MAX = 15000;
let backendReady = false;

/** Resolve backend WS URL. Prefer 13939; runtime port written to user/ws_port.json. */
function getBackendWsUrl() {
  try {
    const portFile = path.join(projectRoot, 'user', 'ws_port.json');
    // Packaged: user dir may live under userData — also try sibling of backend
    const candidates = [
      portFile,
      path.join(__dirname, '..', 'user', 'ws_port.json'),
      process.env.MIKU_USER_DIR ? path.join(process.env.MIKU_USER_DIR, 'ws_port.json') : null,
    ].filter(Boolean);
    for (const p of candidates) {
      if (fs.existsSync(p)) {
        const cfg = JSON.parse(fs.readFileSync(p, 'utf8'));
        const host = cfg.host || '127.0.0.1';
        const port = cfg.port || 13939;
        return `ws://${host}:${port}`;
      }
    }
  } catch (e) {
    console.warn('Failed to read ws_port.json', e);
  }
  return 'ws://127.0.0.1:13939';
}

// Hoisted — avoid reallocating map on every 1Hz emotion_update
const EMOTION_UI_MAP = {
  happy:    { emoji: '😊', key: 'emotion.happy' },
  neutral:  { emoji: '😐', key: 'emotion.neutral' },
  sadness:  { emoji: '😔', key: 'emotion.sadness' },
  anger:    { emoji: '😠', key: 'emotion.anger' },
  fear:     { emoji: '😨', key: 'emotion.fear' },
  disgust:  { emoji: '🤢', key: 'emotion.disgust' },
  surprise: { emoji: '😲', key: 'emotion.surprise' },
  contempt: { emoji: '😒', key: 'emotion.contempt' },
  no_face:  { emoji: '👽', key: 'emotion.no_face' },
};

let configSynced = false;
const pendingBackendMessages = [];
let pendingChatTimeout = null;

function sendOrQueueBackendMessage(message) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(message));
    return;
  }
  pendingBackendMessages.push(message);
}

function flushPendingBackendMessages() {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  while (pendingBackendMessages.length) {
    ws.send(JSON.stringify(pendingBackendMessages.shift()));
  }
}

function armChatTimeout() {
  clearTimeout(pendingChatTimeout);
  pendingChatTimeout = setTimeout(() => {
    ipcRenderer.send('chat-send-failed', '聊天服务暂时没有响应，请稍后重试。');
  }, 20000);
}

async function syncConfigToBackend(force = false) {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  if (configSynced && !force) return;
  configSynced = true;
  ws.send(JSON.stringify({ type: 'change_model', model_type: currentModelType }));
  ws.send(JSON.stringify({ type: 'set_lang', lang: require('./i18n').getCurrentLang() }));
  try {
    const cfg = await ipcRenderer.invoke('get-selected-llm');
    if (cfg && (cfg.apiKey || cfg.baseUrl)) {
      ws.send(JSON.stringify({
        type: 'change_llm',
        base_url: cfg.baseUrl || '',
        api_key: cfg.apiKey || '',
        model: cfg.model || '',
      }));
    }
  } catch (e) {
    console.error('Failed to sync LLM config', e);
  }
}

function connectBackend() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
    return;
  }
  try {
    const url = getBackendWsUrl();
    console.log('Connecting backend WS:', url);
    ws = new WebSocket(url);
  } catch (e) {
    console.warn('WebSocket construct failed', e);
    scheduleReconnect();
    return;
  }

  ws.onopen = () => {
    console.log('Connected to Python emotion backend (awaiting ready).');
    updateStatus(t('status.idle'), "#39c5bb");
    wsRetryDelay = 1000;
    configSynced = false;
    ws.send(JSON.stringify({ type: 'ping' }));
    flushPendingBackendMessages();
  };

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);

      // Handshake once per connection — avoid thrashing change_model/change_llm
      if (data.type === 'backend_ready' || data.type === 'pong') {
        if (!backendReady) {
          backendReady = true;
          console.log('Backend ready handshake OK.');
        }
        syncConfigToBackend(false);
        if (data.type === 'backend_ready' && typeof data.camera_enabled === 'boolean') {
          isCameraConnected = data.camera_enabled;
          isCameraConnecting = false;
          renderCameraConnectionState();
        }
      }

      if (data.type === 'camera_status' && typeof data.connected === 'boolean') {
        isCameraConnected = data.connected;
        isCameraConnecting = false;
        renderCameraConnectionState();
      }

      // Real-time emotion update
      if (data.type === 'emotion_update') {
        const info = EMOTION_UI_MAP[data.emotion] || EMOTION_UI_MAP.neutral;

        const percent = Math.round(data.confidence * 100);
        const emojiEl = document.getElementById('emotion-emoji');
        const labelEl = document.getElementById('emotion-label');
        const confEl  = document.getElementById('emotion-conf');
        if (!isCameraConnected) return; // Do not update UI if disconnected manually
        if (emojiEl) emojiEl.textContent = info.emoji;
        if (labelEl) {
          labelEl.textContent = t(info.key);
          labelEl.setAttribute('data-i18n', info.key);
        }
        if (confEl) {
          confEl.textContent = data.emotion === 'no_face' ? '--%' : percent + '%';
        }
      }
      
      // LLM bubble trigger
      if (data.type === 'trigger_bubble') {
        showChatBubble(data.text, data.show_actions !== false);
      }
      
      // Proactive care trigger
      if (data.type === 'trigger_care_popup') {
        showCarePopup(data.text);
      }
      
      // Period Report display
      if (data.type === 'focus_report') {
        showReportCard(data);
      }
      
      // Chat reply
      if (data.type === 'chat_reply') {
        clearTimeout(pendingChatTimeout);
        pendingChatTimeout = null;
        ipcRenderer.send('chat-reply-from-backend', data.text);
      }
      
      // Chat history
      if (data.type === 'chat_history_response') {
        ipcRenderer.send('chat-history-from-backend', data.history);
      }
    } catch (e) {
      console.error("Error processing websocket message:", e);
    }
  };
  
  ws.onerror = () => {
    // onclose will fire; avoid double schedule
  };

  ws.onclose = () => {
    backendReady = false;
    configSynced = false;
    isCameraConnected = false;
    isCameraConnecting = false;
    console.warn(`Backend connection lost. Retrying in ${wsRetryDelay}ms...`);
    const emojiEl = document.getElementById('emotion-emoji');
    const confEl = document.getElementById('emotion-conf');
    const labelEl = document.getElementById('emotion-label');
    if (emojiEl) emojiEl.textContent = "🔌";
    if (confEl) confEl.textContent = "--%";
    if (labelEl) labelEl.textContent = t('emotion.disconnected');
    scheduleReconnect();
  };
}

function scheduleReconnect() {
  const delay = wsRetryDelay;
  wsRetryDelay = Math.min(WS_RETRY_MAX, Math.floor(wsRetryDelay * 1.6));
  setTimeout(connectBackend, delay);
}

// 8. Period Emotion Report display (Now opens in separate window)
function showReportCard(data) {
  data.startTime = focusStartTimeStr;
  data.endTime = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  ipcRenderer.send('open-report', data);
}

// Forward chat message from chat window to backend
ipcRenderer.on('forward-chat-to-backend', (event, payload) => {
  armChatTimeout();
  if (typeof payload === 'string') {
    sendOrQueueBackendMessage({ type: 'chat_request', text: payload });
  } else {
    sendOrQueueBackendMessage({
      type: 'chat_request',
      text: payload.text,
      hidden_context: payload.hidden_context,
    });
  }
});

ipcRenderer.on('forward-history-request-to-backend', () => {
  sendOrQueueBackendMessage({ type: 'get_chat_history' });
});


// Handle actions triggered from the report window
ipcRenderer.on('action-from-report', (event, action) => {
  if (action === 'dance') {
    startDance();
  } else if (action === 'sing') {
    startSingPlaylist(Math.floor(Math.random() * singFiles.length));
  }
});

// Handle actions triggered from the chat window
ipcRenderer.on('action-from-chat', (event, action) => {
  if (action === 'play_music') {
    startSingPlaylist(Math.floor(Math.random() * singFiles.length));
  }
});

// App Initialization
mikuState = 'daily';
playRandomDailyVideo();

ipcRenderer.on('language-changed', (event, lang) => {
  applyI18n();
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: 'set_lang', lang }));
  }
});

// Apply i18n on startup
applyI18n();

// Re-apply i18n + notify backend when language changes
ipcRenderer.on('lang-changed', (event, lang) => {
  applyI18n();
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: 'set_lang', lang }));
  }
});

// Forward LLM config change to backend
ipcRenderer.on('llm-changed', (event, config) => {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({
      type: 'change_llm',
      base_url: config.baseUrl,
      api_key:  config.apiKey,
      model:    config.model
    }));
  }
});

// Dynamic Window Size Setup
ipcRenderer.on('force-adjust-size', (event, sizeStr) => {
  if (sizeStr) ipcRenderer.send('set-config', { key: 'miku-window-size', val: sizeStr });
  adjustWindowSize();
});

function adjustWindowSize() {
  // Update layout constraints
  const size = ipcRenderer.sendSync('get-config', 'miku-window-size') || 'medium';
  let scale = 1.0;
  if (size === 'small') scale = 0.67;
  if (size === 'large') scale = 1.5;
  
  const baseSize = 200;
  let targetWidth = baseSize;
  let targetHeight = baseSize;
  
  // Only apply dynamic elastic resizing when dancing
  if (mikuState === 'dancing') {
    const videoWidth = mikuVideo.videoWidth;
    const videoHeight = mikuVideo.videoHeight;
    
    if (videoWidth && videoHeight) {
      const ratio = videoWidth / videoHeight;
      if (ratio > 1) {
        targetWidth = Math.round(baseSize * ratio);
      } else if (ratio < 1) {
        targetHeight = Math.round(baseSize / ratio);
      }
      
      const MAX_DIMENSION = 600;
      if (targetWidth > MAX_DIMENSION) {
        targetWidth = MAX_DIMENSION;
        targetHeight = Math.round(MAX_DIMENSION / ratio);
      }
      if (targetHeight > MAX_DIMENSION) {
        targetHeight = MAX_DIMENSION;
        targetWidth = Math.round(MAX_DIMENSION * ratio);
      }
    }
  }
  
  ipcRenderer.send('resize-window', { contentWidth: targetWidth, contentHeight: targetHeight, scale });
}

mikuVideo.addEventListener('loadedmetadata', adjustWindowSize);

// Trigger initial setup using saved size
const currentWindowSize = ipcRenderer.sendSync('get-config', 'miku-window-size') || 'medium';
ipcRenderer.send('size-changed', currentWindowSize);

// Launch backend unless launcher already hosts it (MIKU_EXTERNAL_BACKEND=1)
const externalBackend = process.env.MIKU_EXTERNAL_BACKEND === '1';
if (!externalBackend) {
  const runtimePy = path.join(projectRoot, 'runtime', 'python', 'python.exe');
  const venvPython = path.join(projectRoot, 'backend', '.venv', 'Scripts', 'python.exe');
  const pythonExe = fs.existsSync(runtimePy)
    ? runtimePy
    : (fs.existsSync(venvPython) ? venvPython : 'python');
  ipcRenderer.send('start-backend', pythonExe);
} else {
  console.log('External backend mode: skip spawn, only connect WS');
}

// Start WS with short delay; exponential backoff handles slow backend boots
setTimeout(connectBackend, externalBackend ? 400 : 800);

// ==========================================
// Volume Control (Global Scroll OSD)
// ==========================================
let currentVolume = ipcRenderer.sendSync('get-config', 'miku-volume');
if (currentVolume === undefined || currentVolume === null) currentVolume = 0.5;

if (typeof currentAudio !== 'undefined' && currentAudio) currentAudio.volume = currentVolume;
mikuVideo.volume = currentVolume;

const volumeOsd = document.getElementById('volume-osd');
const volumeIcon = document.getElementById('volume-icon');
const volumeText = document.getElementById('volume-text');
let volumeOsdTimeout = null;

window.addEventListener('wheel', (e) => {
  // Only trigger if music or dance is active
  const isMusicActive = !document.getElementById('media-player-panel').classList.contains('hide');
  const isDanceActive = !document.getElementById('dance-controls-panel').classList.contains('hide');
  
  if (!isMusicActive && !isDanceActive) return;

  // Adjust volume by 5% per scroll tick
  let step = 0.05;
  if (e.deltaY < 0) {
    currentVolume = Math.min(1.0, currentVolume + step);
  } else {
    currentVolume = Math.max(0.0, currentVolume - step);
  }

  // Apply to media elements
  if (typeof currentAudio !== 'undefined' && currentAudio) {
    currentAudio.volume = currentVolume;
  }
  mikuVideo.volume = currentVolume;
  
  // Save configuration
  ipcRenderer.send('set-config', {key: 'miku-volume', val: currentVolume});

  // Update OSD UI
  let percent = Math.round(currentVolume * 100);
  volumeText.textContent = percent + '%';
  
  if (currentVolume === 0) {
    volumeIcon.textContent = '🔇';
  } else if (currentVolume < 0.4) {
    volumeIcon.textContent = '🔈';
  } else if (currentVolume < 0.8) {
    volumeIcon.textContent = '🔉';
  } else {
    volumeIcon.textContent = '🔊';
  }

  // Show OSD
  volumeOsd.classList.remove('hide');

  // Fade out after 1.5 seconds of inactivity
  if (volumeOsdTimeout) clearTimeout(volumeOsdTimeout);
  volumeOsdTimeout = setTimeout(() => {
    volumeOsd.classList.add('hide');
  }, 1500);
});
