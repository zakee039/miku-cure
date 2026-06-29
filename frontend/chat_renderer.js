const { ipcRenderer } = require('electron');
const fs = require('fs');
const path = require('path');
const { t, applyI18n } = require('./i18n');

const projectRoot = path.join(__dirname, '..');
const gifDir = path.join(projectRoot, 'miku', 'gif');

const chatHistory = document.getElementById('chat-history');
const typingIndicator = document.getElementById('typing-indicator');
const chatInput = document.getElementById('chat-input');

let historyLoaded = false;
let pendingPopulate = null;
const sendBtn = document.getElementById('send-btn');

document.addEventListener('DOMContentLoaded', () => {
  applyI18n();
  // Request history from backend
  ipcRenderer.send('request-chat-history');
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
    try {
      const files = fs.readdirSync(gifDir).filter(f => f.endsWith('.mp4') && f !== 'MIKU-SING.mp4' && f !== 'MIKU-PAUSE.mp4');
      if (files.length > 0) {
        const randomFile = files[Math.floor(Math.random() * files.length)];
        const video = document.createElement('video');
        video.src = 'file:///' + path.join(gifDir, randomFile).replace(/\\/g, '/');
        video.autoplay = true;
        video.loop = true;
        video.muted = true;
        video.className = 'chat-bubble-media';
        bubble.appendChild(video);
      }
    } catch (err) {
      console.error("Error loading GIF for chat:", err);
    }
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
  const text = chatInput.value.trim();
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

ipcRenderer.on('chat-history-from-backend', (event, history) => {
  historyLoaded = true;
  if (history && history.length > 0) {
    // Clear existing static welcome message
    const msgs = chatHistory.querySelectorAll('.message');
    msgs.forEach(m => m.remove());

    // Populate with history
    history.forEach(msg => {
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

ipcRenderer.on('lang-changed', () => {
  applyI18n();
});

function handlePopulate(prompt, displayPrompt) {
  if (displayPrompt) {
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
  if (!historyLoaded) {
    pendingPopulate = { prompt, displayPrompt };
  } else {
    handlePopulate(prompt, displayPrompt);
  }
});
