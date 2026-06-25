const fs = require('fs');
const path = require('path');
const { ipcRenderer } = require('electron');
const { t, applyI18n } = require('./i18n');

// Get project paths
const projectRoot = path.join(__dirname, '..');
const gifDir = path.join(projectRoot, 'miku', 'gif');
const danceDir = path.join(projectRoot, 'miku', 'dance');
const singDir = path.join(projectRoot, 'miku', 'sing');
const assetsDir = path.join(projectRoot, 'frontend', 'assets');

// Cache resource file lists
let gifFiles = [];
let danceFiles = [];
let singFiles = [];

// Special state videos for the sing player
const SING_VIDEO  = 'MIKU-SING.mp4';
const PAUSE_VIDEO = 'MIKU-PAUSE.mp4';
const SPECIAL_VIDEOS = new Set([SING_VIDEO, PAUSE_VIDEO]);

try {
  if (fs.existsSync(gifDir)) {
    // Exclude special sing-player videos from daily rotation
    gifFiles = fs.readdirSync(gifDir).filter(f => f.endsWith('.mp4') && !SPECIAL_VIDEOS.has(f));
  }
  if (fs.existsSync(danceDir)) {
    danceFiles = fs.readdirSync(danceDir).filter(f => f.endsWith('.mp4'));
  }
  if (fs.existsSync(singDir)) {
    singFiles = fs.readdirSync(singDir).filter(f => f.endsWith('.ogg') || f.endsWith('.mp3'));
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
const closeBtn = document.getElementById('close-btn');
const chatBubble = document.getElementById('chat-bubble');
const chatText = document.getElementById('chat-text');

const bubbleDance = document.getElementById('bubble-dance');
const bubbleSing = document.getElementById('bubble-sing');
const bubbleDismiss = document.getElementById('bubble-dismiss');

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
let currentModelType = localStorage.getItem('miku-model-type') || 'cnn';



// Close Window Action
closeBtn.addEventListener('click', () => {
  window.close();
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
let isCameraConnected = true;
const emotionBadge = document.getElementById('emotion-badge');
if (emotionBadge) {
  emotionBadge.addEventListener('click', () => {
    isCameraConnected = !isCameraConnected;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'toggle_camera', state: isCameraConnected }));
    }
    if (!isCameraConnected) {
      const emojiEl = document.getElementById('emotion-emoji');
      const labelEl = document.getElementById('emotion-label');
      const confEl  = document.getElementById('emotion-conf');
      if (emojiEl) emojiEl.textContent = '🔌';
      if (labelEl) labelEl.textContent = t('emotion.disconnected');
      if (confEl)  confEl.textContent  = '--%';
    } else {
      const labelEl = document.getElementById('emotion-label');
      if (labelEl) labelEl.textContent = t('emotion.connecting');
    }
  });
}

// 2. Miku Animation Player State Machine
function playRandomDailyVideo() {
  if (mikuState !== 'daily') return;
  if (gifFiles.length === 0) {
    console.warn("No daily MP4 animation files found in miku/gif/");
    return;
  }
  const randomFile = gifFiles[Math.floor(Math.random() * gifFiles.length)];
  mikuVideo.src = 'file:///' + path.join(gifDir, randomFile).replace(/\\/g, '/');
  mikuVideo.muted = true;
  mikuVideo.play().catch(err => console.error("Playback error:", err));

  // Set rotation timer for 30s
  clearTimeout(rotationTimer);
  rotationTimer = setTimeout(playRandomDailyVideo, 30000);
}

// Double click to switch GIF
mikuVideo.addEventListener('dblclick', () => {
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

actionDance.addEventListener('click', startDance);
actionSing.addEventListener('click', () => startSingPlaylist(Math.floor(Math.random() * singFiles.length)));

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

// 7. WebSocket connection to Python Backend
function connectBackend() {
  ws = new WebSocket('ws://localhost:8765');
  
  ws.onopen = () => {
    console.log('Connected to Python emotion backend.');
    updateStatus(t('status.idle'), "#39c5bb");
    // Send initial model selection state to backend
    if (ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'change_model', model_type: currentModelType }));
      // Sync current language to backend
      ws.send(JSON.stringify({ type: 'set_lang', lang: require('./i18n').getCurrentLang() }));
      // Sync current LLM config to backend
      const selApiId = localStorage.getItem('miku-sel-api') || '';
      const selModel = localStorage.getItem('miku-sel-model') || '';
      try {
        const apis = JSON.parse(localStorage.getItem('miku-apis') || '[]');
        const api  = apis.find(a => a.id === selApiId);
        if (api) {
          ws.send(JSON.stringify({ type: 'change_llm', base_url: api.baseUrl, api_key: api.apiKey, model: selModel }));
        }
      } catch (e) {}
    }
  };
  
  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      
      // Real-time emotion update
      if (data.type === 'emotion_update') {
        const emotionMap = {
          'happy':   { emoji: '😊', key: 'emotion.happy' },
          'neutral': { emoji: '😐', key: 'emotion.neutral' },
          'sadness': { emoji: '😔', key: 'emotion.sadness' },
          'anger':   { emoji: '😠', key: 'emotion.anger' },
          'fear':    { emoji: '😨', key: 'emotion.fear' },
          'disgust': { emoji: '🤢', key: 'emotion.disgust' },
          'surprise':{ emoji: '😲', key: 'emotion.surprise' }
        };
        const info    = emotionMap[data.emotion] || { emoji: '😐', key: 'emotion.neutral' };

        const percent = Math.round(data.confidence * 100);
        const emojiEl = document.getElementById('emotion-emoji');
        const labelEl = document.getElementById('emotion-label');
        const confEl  = document.getElementById('emotion-conf');
        if (!isCameraConnected) return; // Do not update UI if disconnected manually
        if (emojiEl) emojiEl.textContent = info.emoji;
        if (labelEl) labelEl.textContent = t(info.key);
        if (confEl)  confEl.textContent  = percent + '%';
      }
      
      // LLM bubble trigger
      if (data.type === 'trigger_bubble') {
        showChatBubble(data.text, data.show_actions !== false);
      }
      
      // Period Report display
      if (data.type === 'focus_report') {
        showReportCard(data);
      }
    } catch (e) {
      console.error("Error processing websocket message:", e);
    }
  };
  
  ws.onclose = () => {
    console.warn('Backend connection lost. Retrying in 3 seconds...');
    document.getElementById('emotion-badge').textContent = "🔌 --%";
    setTimeout(connectBackend, 3000);
  };
}

// 8. Period Emotion Report display (Now opens in separate window)
function showReportCard(data) {
  data.startTime = focusStartTimeStr;
  data.endTime = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  ipcRenderer.send('open-report', data);
}

// Handle actions triggered from the report window
ipcRenderer.on('action-from-report', (event, action) => {
  if (action === 'dance') {
    startDance();
  } else if (action === 'sing') {
    startSingPlaylist(Math.floor(Math.random() * singFiles.length));
  }
});

// App Initialization
mikuState = 'daily';
playRandomDailyVideo();

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
  if (sizeStr) localStorage.setItem('miku-window-size', sizeStr);
  adjustWindowSize();
});

function adjustWindowSize() {
  const size = localStorage.getItem('miku-window-size') || 'medium';
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
const currentWindowSize = localStorage.getItem('miku-window-size') || 'medium';
ipcRenderer.send('size-changed', currentWindowSize);

// Launch backend as child process bound to this Electron window
// Detect python executable (prefer .venv)
const venvPython = path.join(projectRoot, 'backend', '.venv', 'Scripts', 'python.exe');
const pythonExe = fs.existsSync(venvPython) ? venvPython : 'python';
ipcRenderer.send('start-backend', pythonExe);

// Connect WebSocket after a short delay to let backend start
setTimeout(connectBackend, 2000);
