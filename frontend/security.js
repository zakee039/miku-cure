const crypto = require('crypto');

const MAX_CLOCK_SKEW_MS = 60 * 1000;
const CHAT_TEXT_MAX = 4000;
const CHAT_HIDDEN_CONTEXT_MAX = 8000;
const CHAT_REPLY_MAX = 50000;
const ALLOWED_EXTERNAL_HOSTS = new Set([
  'github.com',
  'www.github.com',
  'piapro.jp',
  'space.bilibili.com',
  'www.bilibili.com',
  'x.com',
  'www.x.com',
]);

function isPlainObject(value) {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}

function isLoopbackHost(host) {
  const normalized = String(host || '').replace(/^\[|\]$/g, '').toLowerCase();
  return normalized === '127.0.0.1' || normalized === 'localhost' || normalized === '::1';
}

function endpointSignature(token, host, port, ts, launchSession) {
  return crypto
    .createHmac('sha256', token)
    .update(`${host}:${port}:${ts}:${launchSession}`)
    .digest('hex');
}

function validateBackendDescriptor(value, options = {}) {
  if (!isPlainObject(value)) throw new Error('Invalid backend descriptor');
  const token = String(options.token || '');
  const expectedSession = String(options.launchSession || '');
  const now = Number(options.now || Date.now());
  const host = String(value.host || '');
  const port = Number(value.port);
  const ts = Number(value.ts);
  const launchSession = String(value.launch_session || '');
  const signature = String(value.signature || '').toLowerCase();

  if (token.length < 16) throw new Error('Backend authentication token is unavailable');
  if (!isLoopbackHost(host)) throw new Error('Backend host must be loopback');
  if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error('Invalid backend port');
  if (!Number.isFinite(ts) || ts <= 0) throw new Error('Invalid backend timestamp');
  if (ts - now > MAX_CLOCK_SKEW_MS) throw new Error('Backend descriptor timestamp is in the future');
  if (expectedSession && launchSession !== expectedSession) {
    throw new Error('Backend launch session mismatch');
  }
  if (!/^[a-f0-9]{64}$/.test(signature)) throw new Error('Invalid backend signature');

  const expected = endpointSignature(token, host, port, ts, launchSession);
  if (!crypto.timingSafeEqual(Buffer.from(signature, 'hex'), Buffer.from(expected, 'hex'))) {
    throw new Error('Backend signature mismatch');
  }
  return {
    url: `ws://127.0.0.1:${port}`,
    token,
    launchSession,
  };
}

function normalizeExternalUrl(raw) {
  try {
    const url = new URL(String(raw || ''));
    if (url.protocol !== 'https:' || !ALLOWED_EXTERNAL_HOSTS.has(url.hostname.toLowerCase())) {
      return null;
    }
    url.username = '';
    url.password = '';
    return url.toString();
  } catch {
    return null;
  }
}

function boundedString(value, maxLength, fallback = '') {
  if (typeof value !== 'string') return fallback;
  return value.slice(0, maxLength);
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

function launcherHeartbeatSignature(token, launchSession, ts) {
  return crypto
    .createHmac('sha256', String(token || ''))
    .update(`heartbeat:${launchSession}:${ts}`)
    .digest('hex');
}

function validateLauncherHeartbeat(value, options = {}) {
  if (!isPlainObject(value) || value.action !== 'heartbeat') return null;
  const token = String(options.token || '');
  const expectedSession = String(options.launchSession || '');
  const now = Number(options.now ?? Date.now());
  const maxAgeMs = Number(options.maxAgeMs ?? 5000);
  const launchSession = String(value.launch_session || '');
  const ts = Number(value.ts);
  const signature = String(value.signature || '').toLowerCase();
  if (token.length < 16 || !expectedSession || launchSession !== expectedSession) return null;
  if (!Number.isSafeInteger(ts) || ts <= 0 || !Number.isFinite(now)) return null;
  if (!Number.isFinite(maxAgeMs) || maxAgeMs <= 0 || ts > now || now - ts > maxAgeMs) return null;
  if (!/^[a-f0-9]{64}$/.test(signature)) return null;
  const expected = launcherHeartbeatSignature(token, launchSession, ts);
  if (!crypto.timingSafeEqual(Buffer.from(signature, 'hex'), Buffer.from(expected, 'hex'))) return null;
  return ts;
}

function normalizeApiBaseUrl(raw) {
  const value = boundedString(raw, 2048).trim().replace(/\/+$/, '');
  let parsed;
  try {
    parsed = new URL(value);
  } catch {
    return null;
  }
  if (parsed.username || parsed.password || parsed.search || parsed.hash) return null;
  if (parsed.protocol !== 'https:' && !(parsed.protocol === 'http:' && isLoopbackHost(parsed.hostname))) {
    return null;
  }
  return value;
}

function sanitizeApiRecord(value) {
  if (!isPlainObject(value)) return null;
  const id = boundedString(value.id, 80).trim();
  const name = boundedString(value.name, 100).trim();
  const baseUrl = normalizeApiBaseUrl(value.baseUrl);
  const apiKey = boundedString(value.apiKey, 4096);
  const models = Array.isArray(value.models)
    ? value.models.map((item) => boundedString(item, 200).trim()).filter(Boolean).slice(0, 200)
    : [];
  if (!id || !name || !baseUrl) return null;
  return { id, name, baseUrl, apiKey, models };
}

module.exports = {
  CHAT_HIDDEN_CONTEXT_MAX,
  CHAT_TEXT_MAX,
  endpointSignature,
  isPlainObject,
  launcherHeartbeatSignature,
  normalizeApiBaseUrl,
  normalizeExternalUrl,
  parseChatReply,
  sanitizeApiRecord,
  sanitizeChatRequest,
  validateBackendDescriptor,
  validateLauncherHeartbeat,
};
