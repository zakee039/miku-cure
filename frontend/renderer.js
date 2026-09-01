const ipcRenderer = window.miku.ipc;
const chatProtocol = window.miku.chat;
const { t, applyI18n, getCurrentLang, setCurrentLang } = window.MikuI18n;

// Cache resource file lists
let gifFiles = [];
let danceFiles = [];
let singFiles = [];
let assetFiles = [];

// Special state videos for the sing player
const SING_VIDEO  = 'MIKU-SING.mp4';
const PAUSE_VIDEO = 'MIKU-PAUSE.mp4';
const SPECIAL_VIDEOS = new Set([SING_VIDEO, PAUSE_VIDEO]);
const VIDEO_EXTENSIONS = new Set(['.mp4', '.webm', '.mkv', '.mov', '.avi', '.m4v']);
const IMAGE_EXTENSIONS = new Set(['.gif', '.png', '.jpg', '.jpeg', '.webp', '.bmp']);
const AUDIO_EXTENSIONS = new Set(['.ogg', '.mp3', '.wav', '.m4a', '.aac', '.flac']);

function extensionOf(filename) {
  const match = /\.[^.]+$/.exec(String(filename || ''));
  return match ? match[0].toLowerCase() : '';
}

function hasExtension(filename, extensions) {
  return extensions.has(extensionOf(filename));
}

async function refreshMedia(kind = null) {
  const kinds = kind ? [kind] : ['daily', 'dance', 'sing', 'asset'];
  const values = await Promise.all(kinds.map(async (item) => {
    try {
      const result = await ipcRenderer.invoke('list-media', item);
      return Array.isArray(result) ? result : [];
    } catch {
      return [];
    }
  }));
  kinds.forEach((item, index) => {
    if (item === 'daily') gifFiles = values[index].filter((file) => !SPECIAL_VIDEOS.has(file.name));
    if (item === 'dance') danceFiles = values[index];
    if (item === 'sing') singFiles = values[index];
    if (item === 'asset') assetFiles = values[index];
  });
}

// Helper: switch Miku video to a specific file in assets dir (looped, muted)
function playSingStateVideo(filename) {
  const media = assetFiles.find((file) => file.name === filename);
  if (!media) {
    // Fallback to normal daily GIF if special video not found
    playRandomDailyVideo();
    return;
  }
  clearTimeout(rotationTimer);
  mikuImage.style.display = 'none';
  mikuImage.removeAttribute('src');
  mikuVideo.style.display = 'block';
  const targetSrc = media.url;
  
  // Prevent restarting the video if it's already playing the target file
  if (mikuVideo.src === targetSrc) {
    return;
  }
  
  mikuVideo.src = targetSrc;
  mikuVideo.muted = true;
  mikuVideo.loop = true;
  mikuVideo.play().catch(err => console.error('Sing-state video error:', err));
}

function updateSingVisual(playing) {
  const useLive2DVisual = is3dMode() && window.Miku3D?.hasMusicAction?.() === true;
  if (useLive2DVisual) {
    mikuVideo.pause();
    mikuVideo.style.display = 'none';
    mikuImage.style.display = 'none';
    miku3dLayer?.classList.add('active');
    window.Miku3D?.setMode('3d');
    window.Miku3D?.setMusicPlaying(Boolean(playing));
    return;
  }

  // Models without their own sing expression temporarily use the same
  // looped sing/pause videos as media mode, without changing the saved mode.
  miku3dLayer?.classList.remove('active');
  window.Miku3D?.setMusicPlaying(false);
  playSingStateVideo(playing ? SING_VIDEO : PAUSE_VIDEO);
}

// DOM Elements
const mikuVideo = document.getElementById('miku-video');
const mikuImage = document.getElementById('miku-image');
const miku3dLayer = document.getElementById('miku-3d-layer');
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
let focusDeadlineMs = 0;
let isPaused = false;
let ws = null;
let focusStartTimeStr = "";
let currentSingIndex = 0;
let currentDanceIndex = 0;
let isPlayingSing = false;
let currentModelType = ipcRenderer.sendSync('get-config', 'miku-model-type') || 'best_rnn_attention.pth';
let currentDisplayMode = ipcRenderer.sendSync('get-config', 'miku-display-mode') || 'media';
let currentCharacterModel = ipcRenderer.sendSync('get-config', 'miku-character-model') || '';

function is3dMode() {
  return currentDisplayMode === '3d';
}

function applyDisplayMode(mode) {
  currentDisplayMode = mode === '3d' ? '3d' : 'media';
  if (is3dMode()) {
    clearTimeout(rotationTimer);
    mikuVideo.pause();
    mikuVideo.style.display = 'none';
    mikuImage.style.display = 'none';
    miku3dLayer?.classList.add('active');
    window.Miku3D?.setModel(currentCharacterModel);
    window.Miku3D?.setMode('3d');
  } else {
    miku3dLayer?.classList.remove('active');
    window.Miku3D?.setMode('media');
    playRandomDailyVideo();
  }
}

function showMediaFile(media, { muted = true, loop = true } = {}) {
  if (!media || typeof media.url !== 'string') return Promise.reject(new Error('Invalid media'));
  const source = media.url;
  if (hasExtension(media.name, IMAGE_EXTENSIONS)) {
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

// Emotion badge controls emotion recognition; camera lifetime is shared with face tracking.
let isCameraConnected = false;
let isCameraConnecting = false;
let emotionRecognitionEnabled = ipcRenderer.sendSync('get-config', 'miku-emotion-recognition-enabled') !== false;
const emotionBadge = document.getElementById('emotion-badge');

function renderCameraConnectionState() {
  const emojiEl = document.getElementById('emotion-emoji');
  const labelEl = document.getElementById('emotion-label');
  const confEl = document.getElementById('emotion-conf');
  if (!emotionRecognitionEnabled) {
    if (emojiEl) emojiEl.textContent = '🔌';
    if (labelEl) {
      labelEl.textContent = t('emotion.recognition_off');
      labelEl.removeAttribute('data-i18n');
    }
    if (confEl) confEl.textContent = '--%';
  } else if (isCameraConnecting) {
    if (labelEl) {
      labelEl.textContent = t('emotion.connecting');
      labelEl.removeAttribute('data-i18n');
    }
    if (confEl) confEl.textContent = '--%';
  } else if (!isCameraConnected) {
    if (emojiEl) emojiEl.textContent = '⚠';
    if (labelEl) {
      labelEl.textContent = t('emotion.camera_unavailable');
      labelEl.removeAttribute('data-i18n');
    }
    if (confEl) confEl.textContent = '--%';
  }
}

if (emotionBadge) {
  renderCameraConnectionState();
  emotionBadge.addEventListener('click', () => {
    if (!ws || ws.readyState !== WebSocket.OPEN || !backendAuthenticated) {
      isCameraConnected = false;
      isCameraConnecting = false;
      renderCameraConnectionState();
      return;
    }

    emotionRecognitionEnabled = !emotionRecognitionEnabled;
    isCameraConnecting = emotionRecognitionEnabled && !isCameraConnected;
    ipcRenderer.send('set-config', {
      key: 'miku-emotion-recognition-enabled',
      val: emotionRecognitionEnabled,
    });
    renderCameraConnectionState();
    sendOrQueueBackendMessage({
      type: 'set_emotion_recognition',
      enabled: emotionRecognitionEnabled,
    });
  });
}

window.addEventListener('miku-face-tracking-toggle', (event) => {
  const detail = event.detail;
  if (!detail || typeof detail.enabled !== 'boolean') return;
  sendOrQueueBackendMessage({
    type: 'set_face_tracking',
    enabled: detail.enabled,
    generation: Number.isInteger(detail.generation) ? detail.generation : 0,
  });
});

// 2. Miku Animation Player State Machine
async function playRandomDailyVideo() {
  if (is3dMode()) return;
  if (mikuState !== 'daily') return;
  await refreshMedia('daily');
  if (mikuState !== 'daily') return;
  if (gifFiles.length === 0) {
    console.warn("No supported animation or image files found in miku/gif/");
    return;
  }
  const randomFile = gifFiles[Math.floor(Math.random() * gifFiles.length)];
  await showMediaFile(randomFile);

  // Set rotation timer for 30s
  clearTimeout(rotationTimer);
  rotationTimer = setTimeout(playRandomDailyVideo, 30000);
}

// Double click to switch GIF
document.getElementById('miku-display').addEventListener('dblclick', (event) => {
  if (event.target.closest('button, input, .emotion-badge')) return;
  if (!is3dMode() && mikuState === 'daily') {
    playRandomDailyVideo();
  }
});

// 3. Play Dance mode
async function startDance(index = null) {
  await refreshMedia('dance');
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
  window.Miku3D?.setMusicPlaying(false);
  miku3dLayer?.classList.remove('active');
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
  mikuVideo.src = randomFile.url;
  mikuVideo.muted = false;
  mikuVideo.loop = false;
  
  updateStatus(t('status.dancing'), "#ff5f56");
  
  mikuVideo.play().catch(err => {
    console.error("Dance video play error:", err);
    stopSingOrDance();
  });
}

// 4. Play Sing mode (Playlist Player)
async function startSingPlaylist(index = 0) {
  await refreshMedia('sing');
  if (singFiles.length === 0) {
    showChatBubble(t('status.no_sing'), false);
    return;
  }
  clearTimeout(rotationTimer);
  mikuState = 'singing';
  if (!is3dMode()) miku3dLayer?.classList.remove('active');
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
  
  currentAudio = new Audio(randomFile.url);
  if (typeof currentVolume !== 'undefined') currentAudio.volume = currentVolume;
  currentAudio.play().catch(err => {
    console.error("Sing audio play error:", err);
    stopSingOrDance();
  });
  
  songTitle.textContent = randomFile.name;
  playerPlay.textContent = "||";
  updateStatus(t('status.singing'), "#bf73ff");
  
  updateSingVisual(true);
  
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
  window.Miku3D?.setMusicPlaying(false);
  mikuVideo.loop = true;
  mikuVideo.muted = true;
  mediaPlayerPanel.classList.add('hide');
  danceControlsPanel.classList.add('hide');  // hide controls
  // Restore header
  document.getElementById('viewport-header').classList.remove('header-folded');
  updateStatus(t('status.idle'), "#39c5bb");
  if (is3dMode()) {
    mikuVideo.pause();
    mikuVideo.style.display = 'none';
    mikuImage.style.display = 'none';
    miku3dLayer?.classList.add('active');
    window.Miku3D?.setMode('3d');
  } else {
    playRandomDailyVideo();
  }
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
  sendOrQueueBackendMessage({ type: 'bubble_dismissed' });
});

// Care Popup Event Handlers
careChatBtn.addEventListener('click', () => {
  hideCarePopup();
  ipcRenderer.send('open-chat');
  sendOrQueueBackendMessage({ type: 'care_popup_dismissed' });
  sendOrQueueBackendMessage({
    type: 'chat_request',
    text: t('btn.care_chat'),
    hidden_context: "[System]: The user just clicked 'Chat' from a proactive care popup because they were feeling negative emotions recently. Please start the conversation by gently asking what's bothering them and offer your comfort.",
  });
});

careDismissBtn.addEventListener('click', () => {
  hideCarePopup();
  sendOrQueueBackendMessage({ type: 'care_popup_dismissed' });
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
    updateSingVisual(false);
  } else {
    currentAudio.play().catch(e => console.error(e));
    isPlayingSing = true;
    playerPlay.textContent = "||";
    updateStatus(t('status.singing'), "#bf73ff");
    updateSingVisual(true);
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
  window.Miku3D?.reactToNegativeReport();
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
  if (typeof selectedModel !== 'string') return;
  currentModelType = selectedModel;
  console.log("Renderer: Received model change command from IPC:", selectedModel);
  sendOrQueueBackendMessage({ type: 'change_model', model_type: selectedModel });
});

ipcRenderer.on('change-display-mode', (event, mode) => {
  applyDisplayMode(mode);
});

ipcRenderer.on('change-character-model', (event, modelId) => {
  if (typeof modelId !== 'string') return;
  currentCharacterModel = modelId;
  if (is3dMode()) window.Miku3D?.setModel(modelId);
});

// When user changes LLM in settings, force re-sync is not needed — llm-changed IPC already forwards.

startBtn.addEventListener('click', () => {
  const mins = parseInt(durationInput.value) || 30;
  focusTimeTotal = mins * 60;
  focusTimeRemaining = focusTimeTotal;
  focusDeadlineMs = Date.now() + focusTimeTotal * 1000;
  isPaused = false;
  
  const now = new Date();
  focusStartTimeStr = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

  // Update layout UI
  timerSetup.classList.add('hide');
  timerActive.classList.remove('hide');
  timerPanel.classList.add('is-active');
  updateCountdownDisplay();
  
  // Notify Python Backend
  sendOrQueueBackendMessage({ type: 'start_focus', duration_minutes: mins });
  
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
  focusTimeRemaining = Math.max(0, Math.ceil((focusDeadlineMs - Date.now()) / 1000));
  if (focusTimeRemaining > 0) {
    updateCountdownDisplay();
  } else {
    // Timer reached 0!
    clearInterval(pomodoroTimer);
    timerActive.classList.add('hide');
    timerSetup.classList.remove('hide');
    timerPanel.classList.add('hide');
    timerPanel.classList.remove('is-active');
    
    // Notify Backend & requesting end-of-period report
    sendOrQueueBackendMessage({ type: 'end_focus', completed: true });
  }
}

pauseBtn.addEventListener('click', () => {
  if (!isPaused) {
    focusTimeRemaining = Math.max(0, Math.ceil((focusDeadlineMs - Date.now()) / 1000));
  } else {
    focusDeadlineMs = Date.now() + focusTimeRemaining * 1000;
  }
  isPaused = !isPaused;
  pauseBtn.textContent = isPaused ? "►" : "||";
  sendOrQueueBackendMessage({ type: 'pause_focus', paused: isPaused });
});

stopBtn.addEventListener('click', () => {
  clearInterval(pomodoroTimer);
  timerActive.classList.add('hide');
  timerSetup.classList.remove('hide');
  timerPanel.classList.add('hide');
  timerPanel.classList.remove('is-active');
  updateStatus(t('status.interrupted'), "#ff5f56");
  
  sendOrQueueBackendMessage({ type: 'end_focus', completed: false });
});

// Dummy updateStatus for compatibility
function updateStatus(text, color) {
  console.log("Status changed:", text);
}

// 7. WebSocket connection to Python Backend (ready handshake + exponential backoff)
let wsRetryDelay = 1000;
const WS_RETRY_MAX = 15000;
let backendReady = false;
let backendAuthenticated = false;
let reconnectTimer = null;
let authenticationTimer = null;

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
const pendingChatTimeouts = new Map();

function isObject(value) {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}

function sendOrQueueBackendMessage(message) {
  if (!isObject(message) || typeof message.type !== 'string') return;
  if (ws && ws.readyState === WebSocket.OPEN && backendAuthenticated) {
    ws.send(JSON.stringify(message));
    return;
  }
  if (pendingBackendMessages.length >= 100) {
    const dropped = pendingBackendMessages.shift();
    if (dropped?.request_id && settleChatRequest(dropped.request_id)) {
      ipcRenderer.send('chat-send-failed', t('chat.error.queue_full'));
    }
  }
  pendingBackendMessages.push(message);
}

function flushPendingBackendMessages() {
  if (!ws || ws.readyState !== WebSocket.OPEN || !backendAuthenticated || !configSynced) return;
  while (pendingBackendMessages.length) {
    ws.send(JSON.stringify(pendingBackendMessages.shift()));
  }
}

function armChatTimeout(requestId) {
  const timer = setTimeout(() => {
    pendingChatTimeouts.delete(requestId);
    const queuedIndex = pendingBackendMessages.findIndex((message) => message.request_id === requestId);
    if (queuedIndex >= 0) pendingBackendMessages.splice(queuedIndex, 1);
    ipcRenderer.send('chat-send-failed', t('chat.error.timeout'));
  }, 20000);
  pendingChatTimeouts.set(requestId, timer);
}

function settleChatRequest(requestId) {
  if (requestId && !pendingChatTimeouts.has(requestId)) return false;
  const id = requestId || pendingChatTimeouts.keys().next().value;
  if (!id) return false;
  clearTimeout(pendingChatTimeouts.get(id));
  pendingChatTimeouts.delete(id);
  return true;
}

function chatErrorMessage(error) {
  const keyByCode = {
    invalid_chat_text: 'chat.error.invalid_text',
    invalid_hidden_context: 'chat.error.invalid_context',
    chat_failed: 'chat.error.failed',
    invalid_chat_reply: 'chat.error.failed',
  };
  return t(keyByCode[error] || 'chat.error.failed');
}

async function syncConfigToBackend(force = false) {
  if (!ws || ws.readyState !== WebSocket.OPEN || !backendAuthenticated) return;
  if (configSynced && !force) return;
  ws.send(JSON.stringify({ type: 'change_model', model_type: currentModelType }));
  ws.send(JSON.stringify({ type: 'set_lang', lang: getCurrentLang() }));
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
  configSynced = true;
  flushPendingBackendMessages();
}

async function connectBackend() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
    return;
  }
  let connection;
  try {
    connection = await ipcRenderer.invoke('backend-connection');
    if (!connection || typeof connection.url !== 'string' || typeof connection.token !== 'string') {
      scheduleReconnect();
      return;
    }
    console.log('Connecting authenticated backend WS:', connection.url);
    ws = new WebSocket(connection.url);
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
    backendAuthenticated = false;
    ws.send(JSON.stringify({
      type: 'authenticate',
      token: connection.token,
      launch_session: connection.launchSession || '',
    }));
    clearTimeout(authenticationTimer);
    authenticationTimer = setTimeout(() => {
      if (!backendAuthenticated && ws) ws.close(4001, 'Authentication timeout');
    }, 5000);
  };

  ws.onmessage = (event) => {
    try {
      if (typeof event.data !== 'string' || event.data.length > 2_000_000) return;
      const data = JSON.parse(event.data);
      if (!isObject(data) || typeof data.type !== 'string') return;

      if (data.type === 'authenticated') {
        if (data.ok !== true) {
          ws.close(4003, 'Authentication rejected');
          return;
        }
        clearTimeout(authenticationTimer);
        backendAuthenticated = true;
        ws.send(JSON.stringify({ type: 'ping' }));
        syncConfigToBackend(false);
        return;
      }
      if (!backendAuthenticated) return;

      // Handshake once per connection — avoid thrashing change_model/change_llm
      if (data.type === 'backend_ready' || data.type === 'pong') {
        if (!backendReady) {
          backendReady = true;
          console.log('Backend ready handshake OK.');
          sendOrQueueBackendMessage({
            type: 'set_emotion_recognition',
            enabled: emotionRecognitionEnabled,
          });
          const trackingState = window.Miku3D?.getTrackingState?.();
          if (trackingState) {
            sendOrQueueBackendMessage({
              type: 'set_face_tracking',
              enabled: trackingState.faceEnabled,
              generation: trackingState.generation,
            });
          }
        }
        syncConfigToBackend(false);
        if (data.type === 'backend_ready' && typeof data.camera_enabled === 'boolean') {
          isCameraConnected = data.camera_enabled;
          if (typeof data.emotion_recognition_enabled === 'boolean') {
            emotionRecognitionEnabled = data.emotion_recognition_enabled;
          }
          isCameraConnecting = false;
          renderCameraConnectionState();
        }
      }

      if (data.type === 'camera_status' && typeof data.connected === 'boolean') {
        isCameraConnected = data.connected;
        if (typeof data.emotionEnabled === 'boolean') emotionRecognitionEnabled = data.emotionEnabled;
        isCameraConnecting = false;
        renderCameraConnectionState();
      }

      if (data.type === 'emotion_recognition_status' && typeof data.enabled === 'boolean') {
        emotionRecognitionEnabled = data.enabled;
        isCameraConnecting = false;
        renderCameraConnectionState();
      }

      if (data.type === 'face_tracking') {
        window.Miku3D?.setFaceTrackingData?.(data);
      }

      if (data.type === 'tracking_status') {
        window.Miku3D?.setFaceTrackingStatus?.(data);
      }

      // Real-time emotion update
      if (data.type === 'emotion_update') {
        if (typeof data.emotion !== 'string' || !Number.isFinite(data.confidence)) return;
        const info = EMOTION_UI_MAP[data.emotion] || EMOTION_UI_MAP.neutral;

        const percent = Math.round(Math.max(0, Math.min(1, data.confidence)) * 100);
        const emojiEl = document.getElementById('emotion-emoji');
        const labelEl = document.getElementById('emotion-label');
        const confEl  = document.getElementById('emotion-conf');
        if (!emotionRecognitionEnabled) return;
        if (emojiEl) emojiEl.textContent = info.emoji;
        if (labelEl) {
          labelEl.textContent = t(info.key);
          labelEl.setAttribute('data-i18n', info.key);
        }
        if (confEl) {
          confEl.textContent = data.emotion === 'no_face' ? '--%' : percent + '%';
        }
        window.Miku3D?.setEmotion(data.emotion);
      }
      
      // LLM bubble trigger
      if (data.type === 'trigger_bubble' && typeof data.text === 'string') {
        showChatBubble(data.text, data.show_actions !== false);
      }
      
      // Proactive care trigger
      if (data.type === 'trigger_care_popup' && typeof data.text === 'string') {
        showCarePopup(data.text);
      }
      
      // Period Report display
      if (data.type === 'focus_report' && isObject(data)) {
        showReportCard(data);
      }
      
      // Chat reply, including backend validation and provider failures.
      if (data.type === 'chat_reply') {
        const reply = chatProtocol.parseReply(data);
        if (!reply) return;
        const accepted = settleChatRequest(reply.requestId);
        if (reply.requestId && !accepted) return;
        if (!reply.ok) {
          ipcRenderer.send('chat-send-failed', chatErrorMessage(reply.error));
          return;
        }
        ipcRenderer.send('chat-reply-from-backend', reply.text);
      }
      
      // Chat history
      if (data.type === 'chat_history_response' && Array.isArray(data.history)) {
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
    backendAuthenticated = false;
    configSynced = false;
    clearTimeout(authenticationTimer);
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
  if (reconnectTimer) return;
  const delay = wsRetryDelay;
  wsRetryDelay = Math.min(WS_RETRY_MAX, Math.floor(wsRetryDelay * 1.6));
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    connectBackend();
  }, delay);
}

// 8. Period Emotion Report display (Now opens in separate window)
function showReportCard(data) {
  const stats = data?.stats;
  if (stats && typeof stats === 'object') {
    const negative = ['sadness', 'anger', 'fear', 'disgust'].reduce((total, key) => (
      total + (Number(stats[key]) || 0)
    ), 0);
    const positive = (Number(stats.happy) || 0) + (Number(stats.neutral) || 0);
    if (negative > positive) window.Miku3D?.reactToNegativeReport();
  }
  data.startTime = focusStartTimeStr;
  data.endTime = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  ipcRenderer.send('open-report', data);
}

// Forward chat message from chat window to backend
ipcRenderer.on('forward-chat-to-backend', (event, payload) => {
  const request = chatProtocol.sanitizeRequest(payload);
  if (request === null) {
    ipcRenderer.send('chat-send-failed', t('chat.error.invalid_text'));
    return;
  }
  const requestId = window.crypto.randomUUID();
  armChatTimeout(requestId);
  if (typeof request === 'string') {
    sendOrQueueBackendMessage({ type: 'chat_request', text: request, request_id: requestId });
  } else {
    sendOrQueueBackendMessage({
      type: 'chat_request',
      text: request.text,
      hidden_context: request.hidden_context,
      request_id: requestId,
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
refreshMedia().then(async () => {
  if (gifFiles.length === 0 && !is3dMode()) {
    throw new Error('No supported animation or image files found in miku/gif/');
  }
  applyDisplayMode(currentDisplayMode);
  ipcRenderer.send('renderer-ready', {
    dailyMediaCount: gifFiles.length,
    width: window.innerWidth,
    height: window.innerHeight,
  });
}).catch((error) => {
  console.error('Renderer initialization failed:', error);
});

ipcRenderer.on('language-changed', (event, lang) => {
  setCurrentLang(lang);
  applyI18n();
  sendOrQueueBackendMessage({ type: 'set_lang', lang });
});

// Apply i18n on startup
applyI18n();

// Re-apply i18n + notify backend when language changes
ipcRenderer.on('lang-changed', (event, lang) => {
  setCurrentLang(lang);
  applyI18n();
  sendOrQueueBackendMessage({ type: 'set_lang', lang });
});

// Forward LLM config change to backend
ipcRenderer.on('llm-changed', (event, config) => {
  if (!isObject(config)) return;
  sendOrQueueBackendMessage({
    type: 'change_llm',
    base_url: typeof config.baseUrl === 'string' ? config.baseUrl : '',
    api_key: typeof config.apiKey === 'string' ? config.apiKey : '',
    model: typeof config.model === 'string' ? config.model : '',
  });
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
const externalBackend = window.miku.runtime.externalBackend;
if (!externalBackend) {
  ipcRenderer.send('start-backend');
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
