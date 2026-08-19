const { contextBridge, ipcRenderer } = require('electron');

// Sandboxed Electron preload scripts cannot load relative CommonJS modules.
// Keep this small, side-effect-free validation boundary self-contained.
const CHAT_TEXT_MAX = 4000;
const CHAT_HIDDEN_CONTEXT_MAX = 8000;
const CHAT_REPLY_MAX = 50000;

function isPlainObject(value) {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}

function sanitizeChatRequest(value) {
  if (typeof value === 'string') {
    const text = value.slice(0, CHAT_TEXT_MAX);
    return text.trim() ? text : null;
  }
  if (!isPlainObject(value) || typeof value.text !== 'string') return null;
  const text = value.text.slice(0, CHAT_TEXT_MAX);
  if (!text.trim()) return null;
  if (value.hidden_context !== undefined && typeof value.hidden_context !== 'string') return null;
  return {
    text,
    hidden_context: typeof value.hidden_context === 'string'
      ? value.hidden_context.slice(0, CHAT_HIDDEN_CONTEXT_MAX)
      : '',
  };
}

function parseChatReply(value) {
  if (!isPlainObject(value) || value.type !== 'chat_reply') return null;
  const requestId = typeof value.request_id === 'string'
    ? value.request_id.slice(0, 128)
    : '';
  const error = typeof value.error === 'string' ? value.error.slice(0, 100) : '';
  if (value.success === false || error) {
    return { ok: false, requestId, error: error || 'chat_failed', text: '' };
  }
  if (typeof value.text !== 'string') {
    return { ok: false, requestId, error: 'invalid_chat_reply', text: '' };
  }
  return { ok: true, requestId, error: '', text: value.text.slice(0, CHAT_REPLY_MAX) };
}

const SEND_CHANNELS = new Set([
  'action-from-chat', 'action-from-report', 'analyze-report-request',
  'chat-history-from-backend', 'chat-message', 'chat-reply-from-backend',
  'chat-send-failed', 'drag-start', 'hide-pet', 'lang-changed',
  'llm-changed', 'model-changed', 'display-mode-changed', 'character-model-changed', 'open-chat', 'open-report',
  'open-settings', 'request-chat-history', 'resize-window', 'run-train',
  'set-config', 'size-changed', 'start-backend', 'window-drag',
  'renderer-ready',
]);
const INVOKE_CHANNELS = new Set([
  'api-fetch-models', 'apis-load', 'apis-save', 'backend-connection',
  'get-app-version', 'get-models', 'get-selected-llm', 'has-lora',
  'list-media', 'list-character-models',
]);
const RECEIVE_CHANNELS = new Set([
  'action-from-chat', 'action-from-report', 'change-model',
  'chat-history-from-backend', 'chat-reply-from-backend', 'chat-send-failed',
  'force-adjust-size', 'forward-chat-to-backend',
  'forward-history-request-to-backend', 'lang-changed', 'language-changed',
  'llm-changed', 'change-display-mode', 'change-character-model', 'load-report', 'populate-chat-input',
]);

function assertAllowed(set, channel) {
  if (!set.has(channel)) throw new Error(`IPC channel is not allowed: ${channel}`);
}

const ipc = Object.freeze({
  send(channel, ...args) {
    assertAllowed(SEND_CHANNELS, channel);
    ipcRenderer.send(channel, ...args);
  },
  sendSync(channel, ...args) {
    if (channel !== 'get-config') throw new Error(`Synchronous IPC is not allowed: ${channel}`);
    return ipcRenderer.sendSync(channel, ...args);
  },
  invoke(channel, ...args) {
    assertAllowed(INVOKE_CHANNELS, channel);
    return ipcRenderer.invoke(channel, ...args);
  },
  on(channel, callback) {
    assertAllowed(RECEIVE_CHANNELS, channel);
    if (typeof callback !== 'function') throw new TypeError('IPC listener must be a function');
    const wrapped = (_event, ...args) => callback(undefined, ...args);
    ipcRenderer.on(channel, wrapped);
    return () => ipcRenderer.removeListener(channel, wrapped);
  },
});

contextBridge.exposeInMainWorld('miku', Object.freeze({
  ipc,
  chat: Object.freeze({
    textMax: CHAT_TEXT_MAX,
    hiddenContextMax: CHAT_HIDDEN_CONTEXT_MAX,
    sanitizeRequest: sanitizeChatRequest,
    parseReply: parseChatReply,
  }),
  runtime: Object.freeze({
    externalBackend: process.env.MIKU_EXTERNAL_BACKEND === '1',
  }),
}));
