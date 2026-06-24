const fs = require('fs');
const path = require('path');
const { ipcRenderer } = require('electron');

// Get project paths
const projectRoot = path.join(__dirname, '..');
const gifDir = path.join(projectRoot, 'miku', 'gif');
const danceDir = path.join(projectRoot, 'miku', 'dance');
const singDir = path.join(projectRoot, 'miku', 'sing');

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

// Helper: switch Miku video to a specific file in gif dir (looped, muted)
function playSingStateVideo(filename) {
  const p = path.join(gifDir, filename);
  if (!fs.existsSync(p)) {
    // Fallback to normal daily GIF if special video not found
    playRandomDailyVideo();
    return;
  }
  clearTimeout(rotationTimer);
  mikuVideo.src = 'file:///' + p.replace(/\\/g, '/');
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
const danceClosePanel  = document.getElementById('dance-close-panel');
const danceCloseBtn    = document.getElementById('dance-close');
const songTitle = document.getElementById('song-title');
const playerPrev = document.getElementById('player-prev');
const playerPlay = document.getElementById('player-play');
const playerNext = document.getElementById('player-next');
const playerClose = document.getElementById('player-close');

const reportOverlay = document.getElementById('report-overlay');
const reportPeriod = document.getElementById('report-period');
const chartBars = document.getElementById('chart-bars');
const reportCommentText = document.getElementById('report-comment-text');
const reportCloseBtn = document.getElementById('report-close-btn');

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
let isPlayingSing = false;
let currentModelType = localStorage.getItem('miku-model-type') || 'cnn';

// Close Window Action
closeBtn.addEventListener('click', () => {
  window.close();
});

// 1. Custom JS-Based Window Dragging
let isDragging = false;
let startX, startY;

document.addEventListener('mousedown', (e) => {
  if (
    e.target.closest('button') || 
    e.target.closest('input') || 
    e.target.closest('.settings-panel') || 
    e.target.closest('.report-card') ||
    e.target.closest('.timer-overlay') ||
    e.target.closest('.talent-overlay') ||
    e.target.closest('.media-player-overlay')
  ) {
    return;
  }
  isDragging = true;
  startX = e.screenX;
  startY = e.screenY;
});

document.addEventListener('mousemove', (e) => {
  if (!isDragging) return;
  const dx = e.screenX - startX;
  const dy = e.screenY - startY;
  startX = e.screenX;
  startY = e.screenY;
  ipcRenderer.send('window-drag', { dx, dy });
});

document.addEventListener('mouseup', () => {
  isDragging = false;
});

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
function startDance() {
  if (danceFiles.length === 0) {
    showChatBubble("Miku 发现没有放跳舞视频哦（在 miku/dance 目录）", false);
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
  danceClosePanel.classList.remove('hide');  // show red X
  // Fold the header bar up during dance
  document.getElementById('viewport-header').classList.add('header-folded');
  
  const randomFile = danceFiles[Math.floor(Math.random() * danceFiles.length)];
  mikuVideo.src = 'file:///' + path.join(danceDir, randomFile).replace(/\\/g, '/');
  mikuVideo.muted = false;
  mikuVideo.loop = false;
  
  updateStatus("💃 正在为你跳舞中...", "#ff5f56");
  
  mikuVideo.play().catch(err => {
    console.error("Dance video play error:", err);
    stopSingOrDance();
  });
}

// 4. Play Sing mode (Playlist Player)
function startSingPlaylist(index = 0) {
  if (singFiles.length === 0) {
    showChatBubble("Miku 发现没有放歌曲音频哦（在 miku/sing 目录）", false);
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
  updateStatus("🎵 正在为你唱歌中...", "#bf73ff");
  
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
  danceClosePanel.classList.add('hide');  // hide red X
  // Restore header
  document.getElementById('viewport-header').classList.remove('header-folded');
  updateStatus("😐 正在静静陪伴你", "#39c5bb");
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
    updateStatus("⏸️ 音乐已暂停", "#bf73ff");
    // Switch to MIKU-PAUSE looping video
    playSingStateVideo(PAUSE_VIDEO);
  } else {
    currentAudio.play().catch(e => console.error(e));
    isPlayingSing = true;
    playerPlay.textContent = "||";
    updateStatus("🎵 正在为你唱歌中...", "#bf73ff");
    // Switch back to MIKU-SING looping video
    playSingStateVideo(SING_VIDEO);
  }
});

playerClose.addEventListener('click', () => {
  stopSingOrDance();
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
  updateCountdownDisplay();
  
  // Notify Python Backend
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({
      type: 'start_focus',
      duration_minutes: mins
    }));
  }
  
  updateStatus(`🍅 专注中 (${mins}分钟)`, "#39c5bb");

  // Start timer interval
  clearInterval(pomodoroTimer);
  pomodoroTimer = setInterval(tickTimer, 1000);
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
  pauseBtn.textContent = isPaused ? "▶" : "⏸";
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: 'pause_focus', paused: isPaused }));
  }
});

stopBtn.addEventListener('click', () => {
  clearInterval(pomodoroTimer);
  timerActive.classList.add('hide');
  timerSetup.classList.remove('hide');
  timerPanel.classList.add('hide');
  updateStatus("😐 专注被中断啦", "#ff5f56");
  
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
    updateStatus("😐 正在静静陪伴你", "#39c5bb");
    // Send initial model selection state to backend
    if (ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({
        type: 'change_model',
        model_type: currentModelType
      }));
    }
  };
  
  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      
      // Real-time emotion update
      if (data.type === 'emotion_update') {
        const emotionMap = {
          'happy':   { emoji: '😊', label: '开心' },
          'neutral': { emoji: '😐', label: '中性' },
          'sadness': { emoji: '😔', label: '悲伤' },
          'anger':   { emoji: '😠', label: '憤怒' },
          'fear':    { emoji: '😨', label: '恐惧' },
          'disgust': { emoji: '🤢', label: '厌恶' },
          'surprise':{ emoji: '😲', label: '惊讶' }
        };
        const info    = emotionMap[data.emotion] || { emoji: '😐', label: '中性' };
        const percent = Math.round(data.confidence * 100);
        const labelEl = document.getElementById('emotion-label');
        const confEl  = document.getElementById('emotion-conf');
        if (labelEl) labelEl.textContent = info.emoji + ' ' + info.label;
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

// 8. Period Emotion Report display
function showReportCard(data) {
  const endTime = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  reportPeriod.textContent = `${focusStartTimeStr} ~ ${endTime} (专注 ${data.duration_minutes} 分钟)`;
  
  // Clear previous chart
  chartBars.innerHTML = '';
  
  const emotionLabels = {
    'happy': '😊 开心',
    'neutral': '😐 中性',
    'sadness': '😔 悲伤',
    'anger': '😠 愤怒',
    'fear': '😨 焦虑',
    'disgust': '🤢 厌恶',
    'surprise': '😲 惊讶'
  };

  // Build chart bars
  const stats = data.stats || {};
  
  for (const [emotion, percent] of Object.entries(stats)) {
    const row = document.createElement('div');
    row.className = 'chart-bar-row';
    
    const label = document.createElement('span');
    label.className = 'chart-bar-label';
    label.textContent = emotionLabels[emotion] || emotion;
    
    const outer = document.createElement('div');
    outer.className = 'chart-bar-outer';
    
    const inner = document.createElement('div');
    inner.className = `chart-bar-inner bar-${emotion}`;
    inner.style.width = '0%'; // Start at 0 for load animation
    
    const val = document.createElement('span');
    val.className = 'chart-bar-val';
    val.textContent = `${Math.round(percent)}%`;
    
    outer.appendChild(inner);
    row.appendChild(label);
    row.appendChild(outer);
    row.appendChild(val);
    
    chartBars.appendChild(row);
    
    // Animate bar width loading
    setTimeout(() => {
      inner.style.width = `${percent}%`;
    }, 100);
  }
  
  reportCommentText.textContent = data.comment || "Miku 今天陪着你，感觉很安心！";
  reportOverlay.classList.remove('hide');
}

reportCloseBtn.addEventListener('click', () => {
  reportOverlay.classList.add('hide');
  stopSingOrDance();
});

// App Initialization
mikuState = 'daily';
playRandomDailyVideo();

// Launch backend as child process bound to this Electron window
// Detect python executable (prefer .venv)
const venvPython = path.join(projectRoot, 'backend', '.venv', 'Scripts', 'python.exe');
const pythonExe = fs.existsSync(venvPython) ? venvPython : 'python';
ipcRenderer.send('start-backend', pythonExe);

// Connect WebSocket after a short delay to let backend start
setTimeout(connectBackend, 2000);
