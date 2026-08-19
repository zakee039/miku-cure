const ipcRenderer = window.miku.ipc;
const chatProtocol = window.miku.chat;
const { t, setCurrentLang, applyI18n } = window.MikuI18n;

const chatHistory = document.getElementById('chat-history');
const typingIndicator = document.getElementById('typing-indicator');
const chatInput = document.getElementById('chat-input');
chatInput.maxLength = chatProtocol.textMax;

let historyLoaded = false;
let pendingPopulate = null;
let historyFallbackTimer = null;
const sendBtn = document.getElementById('send-btn');

document.addEventListener('DOMContentLoaded', () => {
  applyI18n();
  // Request history from backend
  ipcRenderer.send('request-chat-history');
  historyFallbackTimer = setTimeout(() => {
    historyLoaded = true;
    if (pendingPopulate) {
      const pending = pendingPopulate;
      pendingPopulate = null;
      handlePopulate(pending.prompt, pending.displayPrompt);
    }
  }, 3000);
});

function scrollToBottom() {
  chatHistory.scrollTop = chatHistory.scrollHeight;
}

function addMessage(text, isUser = false, showImage = false) {
  const msgDiv = document.createElement('div');
  msgDiv.className = `message ${isUser ? 'user' : 'miku'}`;
  const bubble = document.createElement('div');
  bubble.className = 'bubble';
  bubble.textContent = text;
  
  if (showImage && !isUser) {
    ipcRenderer.invoke('list-media', 'daily').then((allFiles) => {
      const files = Array.isArray(allFiles)
        ? allFiles.filter(file => /\.(mp4|webm)$/i.test(file.name || ''))
        : [];
      if (files.length > 0) {
        const randomFile = files[Math.floor(Math.random() * files.length)];
        const video = document.createElement('video');
        video.src = randomFile.url;
        video.autoplay = true;
        video.loop = true;
        video.muted = true;
        video.className = 'chat-bubble-media';
        bubble.appendChild(video);
      }
    }).catch((err) => {
      console.error("Error loading GIF for chat:", err);
    });
  }
  
  msgDiv.appendChild(bubble);
  
  // Insert before typing indicator
  chatHistory.insertBefore(msgDiv, typingIndicator);
  scrollToBottom();
}

function showTyping(show) {
  if (show) {
    typingIndicator.classList.add('active');
  } else {
    typingIndicator.classList.remove('active');
  }
  scrollToBottom();
}

function sendMessage() {
  const text = chatInput.value.trim().slice(0, chatProtocol.textMax);
  if (!text) return;
  
  addMessage(text, true);
  chatInput.value = '';
  sendBtn.disabled = true;
  chatInput.disabled = true;
  showTyping(true);
  
  ipcRenderer.send('chat-message', text);
}

sendBtn.addEventListener('click', sendMessage);
chatInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
});

ipcRenderer.on('chat-reply-from-backend', (event, reply) => {
  if (typeof reply !== 'string') return;
  showTyping(false);
  
  let cleanText = reply;
  let showImage = false;
  
  if (cleanText.includes('[PLAY_MUSIC]')) {
    cleanText = cleanText.replace('[PLAY_MUSIC]', '').trim();
    ipcRenderer.send('action-from-chat', 'play_music');
  }
  
  if (cleanText.includes('[SHOW_IMAGE]')) {
    cleanText = cleanText.replace('[SHOW_IMAGE]', '').trim();
    showImage = true;
  }
  
  addMessage(cleanText, false, showImage);
  sendBtn.disabled = false;
  chatInput.disabled = false;
  chatInput.focus();
});

ipcRenderer.on('chat-send-failed', (event, reason) => {
  if (typeof reason !== 'string') reason = t('emotion.disconnected');
  showTyping(false);
  addMessage(reason || t('emotion.disconnected'), false);
  sendBtn.disabled = false;
  chatInput.disabled = false;
  chatInput.focus();
});

ipcRenderer.on('chat-history-from-backend', (event, history) => {
  if (!Array.isArray(history)) return;
  clearTimeout(historyFallbackTimer);
  historyLoaded = true;
  if (history && history.length > 0) {
    // Clear existing static welcome message
    const msgs = chatHistory.querySelectorAll('.message');
    msgs.forEach(m => m.remove());

    // Populate with history
    history.slice(-500).forEach(msg => {
      if (!msg || typeof msg.content !== 'string') return;
      const isUser = msg.role === 'user';
      addMessage(msg.content, isUser);
    });
  }
  
  if (pendingPopulate) {
    const { prompt, displayPrompt } = pendingPopulate;
    pendingPopulate = null;
    handlePopulate(prompt, displayPrompt);
  }
});

ipcRenderer.on('lang-changed', (event, lang) => {
  setCurrentLang(lang);
  applyI18n();
});

function handlePopulate(prompt, displayPrompt) {
  if (displayPrompt) {
    prompt = prompt.slice(0, chatProtocol.hiddenContextMax);
    displayPrompt = displayPrompt.slice(0, chatProtocol.textMax);
    addMessage(displayPrompt, true);
    chatInput.value = '';
    sendBtn.disabled = true;
    chatInput.disabled = true;
    showTyping(true);
    ipcRenderer.send('chat-message', { text: displayPrompt, hidden_context: prompt });
  } else {
    chatInput.value = prompt;
    sendMessage();
  }
}

ipcRenderer.on('populate-chat-input', (event, prompt, displayPrompt) => {
  if (typeof prompt !== 'string') return;
  prompt = prompt.slice(0, chatProtocol.hiddenContextMax);
  displayPrompt = typeof displayPrompt === 'string'
    ? displayPrompt.slice(0, chatProtocol.textMax)
    : '';
  if (!historyLoaded) {
    pendingPopulate = { prompt, displayPrompt };
  } else {
    handlePopulate(prompt, displayPrompt);
  }
});
