const ipcRenderer = window.miku.ipc;
const { t, getCurrentLang, setCurrentLang, applyI18n } = window.MikuI18n;

const LS_SEL_API   = 'miku-sel-api';    // selected api id
const LS_SEL_MODEL = 'miku-sel-model';  // selected model string

// In-memory cache of decrypted APIs (keys never written from renderer disk APIs)
let _apisCache = null;

async function loadApis() {
  try {
    _apisCache = await ipcRenderer.invoke('apis-load') || [];
    return _apisCache;
  } catch (e) {
    console.error('Failed to load apis via IPC', e);
    return _apisCache || [];
  }
}

function loadApisSync() {
  // Prefer cache; if empty, block via sendSync is not available for invoke.
  // Callers that need sync should use cached data after first async load.
  return _apisCache || [];
}

async function saveApis(list) {
  try {
    const result = await ipcRenderer.invoke('apis-save', list || []);
    if (!result?.ok) throw new Error(result?.error || 'Save failed');
    _apisCache = await ipcRenderer.invoke('apis-load') || [];
    return true;
  } catch (e) {
    console.error('Failed to save apis via IPC', e);
    alert(e.message);
    return false;
  }
}

function uid() {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
}

function escapeHtml(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

// ── Broadcast current LLM selection to backend (via main process) ─────────────
async function broadcastLlmConfig() {
  ipcRenderer.send('llm-changed');
}

document.addEventListener('DOMContentLoaded', () => {

  // ── Tab Navigation ───────────────────────────────────────────────────────
  const tabs  = document.querySelectorAll('.tab');
  const pages = document.querySelectorAll('.page');

  tabs.forEach(tab => {
    tab.addEventListener('click', () => {
      const target = tab.dataset.page;
      tabs.forEach(t  => t.classList.remove('active'));
      pages.forEach(p => p.classList.remove('active'));
      tab.classList.add('active');
      const page = document.getElementById('page-' + target);
      if (page) page.classList.add('active');
    });
  });

  // ── Apply i18n ───────────────────────────────────────────────────────────
  function applyAllTranslations() {
    applyI18n();
    document.querySelectorAll('[data-i18n-option]').forEach(el => {
      el.textContent = t(el.getAttribute('data-i18n-option'));
    });
  }
  applyAllTranslations();

  // ── Inject Version ────────────────────────────────────────────────────────
  ipcRenderer.invoke('get-app-version').then(version => {
    const el = document.getElementById('about-ver');
    if (el) el.textContent = 'v' + version;
  });

  // ── Model Select ─────────────────────────────────────────────────────────
  const modelSelect = document.getElementById('model-select');
  const btnTrain = document.getElementById('btn-train');
  
  btnTrain.addEventListener('click', () => {
    ipcRenderer.send('run-train');
  });

  // Dynamically load models from backend (.pth only; DeepFace permanently removed)
  const DEFAULT_MODEL = 'best_rnn_attention.pth';
  ipcRenderer.invoke('get-models').then((models) => {
    const customOrder = ['best_rnn_attention.pth', 'best_cnn.pth', 'best_mobilenet_v2.pth'];
    models = (models || []).filter((m) => {
      const s = String(m).toLowerCase();
      return s.endsWith('.pth') && !s.includes('deepface');
    });
    models.sort((a, b) => {
      let idxA = customOrder.indexOf(a);
      let idxB = customOrder.indexOf(b);
      if (idxA === -1) idxA = 999;
      if (idxB === -1) idxB = 999;
      return idxA - idxB;
    });

    modelSelect.innerHTML = '';

    models.forEach(modelName => {
      const opt = document.createElement('option');
      opt.value = modelName;
      opt.textContent = modelName;
      modelSelect.appendChild(opt);
    });

    const mockOpt = document.createElement('option');
    mockOpt.value = 'mock';
    mockOpt.textContent = '亮度模拟器';
    mockOpt.setAttribute('data-i18n-option', 'model.mock.name');
    modelSelect.appendChild(mockOpt);

    applyAllTranslations();

    let savedModel = ipcRenderer.sendSync('get-config', 'miku-model-type');
    const sm = String(savedModel || '').toLowerCase();
    if (sm === 'deepface' || sm === 'df' || sm.includes('deepface') || sm === 'cnn') {
      savedModel = DEFAULT_MODEL;
      ipcRenderer.send('set-config', {key: 'miku-model-type', val: DEFAULT_MODEL});
    }
    if (savedModel && Array.from(modelSelect.options).some(o => o.value === savedModel)) {
      modelSelect.value = savedModel;
    } else {
      modelSelect.value = Array.from(modelSelect.options).some(o => o.value === DEFAULT_MODEL)
        ? DEFAULT_MODEL
        : (modelSelect.options[0] ? modelSelect.options[0].value : 'mock');
      ipcRenderer.send('set-config', {key: 'miku-model-type', val: modelSelect.value});
    }
    ipcRenderer.send('model-changed', modelSelect.value);
  }).catch(err => {
    console.error('Failed to load models:', err);
  });

  modelSelect.addEventListener('change', () => {
    ipcRenderer.send('set-config', {key: 'miku-model-type', val: modelSelect.value});
    ipcRenderer.send('model-changed', modelSelect.value);
  });

  // ── Size Select ──────────────────────────────────────────────────────────
  const sizeSelect = document.getElementById('size-select');
  sizeSelect.value = ipcRenderer.sendSync('get-config', 'miku-window-size') || 'medium';
  sizeSelect.addEventListener('change', () => {
    ipcRenderer.send('set-config', {key: 'miku-window-size', val: sizeSelect.value});
    ipcRenderer.send('size-changed', sizeSelect.value);
  });

  // ── Character display mode ──────────────────────────────────────────────
  const displayModeSelect = document.getElementById('display-mode-select');
  displayModeSelect.value = ipcRenderer.sendSync('get-config', 'miku-display-mode') || 'media';
  displayModeSelect.addEventListener('change', () => {
    const mode = displayModeSelect.value === '3d' ? '3d' : 'media';
    ipcRenderer.send('set-config', {key: 'miku-display-mode', val: mode});
    ipcRenderer.send('display-mode-changed', mode);
  });

  // ── Character model selection ───────────────────────────────────────────
  const characterModelSelect = document.getElementById('character-model-select');
  const characterModelTip = document.getElementById('character-model-tip');
  const savedCharacterModel = ipcRenderer.sendSync('get-config', 'miku-character-model') || '';
  ipcRenderer.invoke('list-character-models').then((models) => {
    const list = Array.isArray(models) ? models : [];
    characterModelSelect.replaceChildren();
    if (!list.length) {
      const option = new Option('未找到模型', '');
      characterModelSelect.add(option);
      characterModelSelect.disabled = true;
      characterModelTip.textContent = '将 .pmx/.pmd 或 .model3.json 连同资源放入 miku/models/<模型名>/。';
      return;
    }
    for (const model of list) {
      const typeLabel = model.type === 'live2d' ? 'Live2D' : 'MMD';
      characterModelSelect.add(new Option(`${model.name} (${typeLabel})`, model.id));
    }
    const selected = list.some((model) => model.id === savedCharacterModel)
      ? savedCharacterModel
      : (list.find((model) => model.type === 'live2d') || list[0]).id;
    characterModelSelect.value = selected;
    if (selected !== savedCharacterModel) {
      ipcRenderer.send('set-config', { key: 'miku-character-model', val: selected });
    }
    const selectedModel = list.find((model) => model.id === selected);
    characterModelTip.textContent = selectedModel?.type === 'live2d'
      ? `已识别 ${selectedModel.motions?.length || 0} 个动作和 ${selectedModel.expressions?.length || 0} 个表情。`
      : 'MMD 模型会保留原始纹理目录。';
  }).catch((error) => {
    console.error('Failed to scan character models:', error);
    characterModelSelect.disabled = true;
    characterModelTip.textContent = '模型扫描失败，请查看启动器日志。';
  });

  characterModelSelect.addEventListener('change', () => {
    const modelId = characterModelSelect.value;
    if (!modelId) return;
    ipcRenderer.send('set-config', { key: 'miku-character-model', val: modelId });
    ipcRenderer.send('character-model-changed', modelId);
  });

  // ── Language Select ──────────────────────────────────────────────────────
  const langSelect = document.getElementById('lang-select');
  langSelect.value = getCurrentLang();
  langSelect.addEventListener('change', () => {
    const lang = langSelect.value;
    setCurrentLang(lang);
    ipcRenderer.send('set-config', {key: 'miku-language', val: lang});
    applyAllTranslations();
    renderApiList();          // re-render API list with new i18n
    if (ceremonySuccessSection.style.display === 'block') {
      const masterName = ipcRenderer.sendSync('get-config', 'miku-master-name') || '主人';
      ceremonySuccessMsg.textContent = t('ceremony.success_title', { name: masterName });
    }
    ipcRenderer.send('lang-changed', lang);
  });

  ipcRenderer.on('language-changed', (event, lang) => {
    setCurrentLang(lang);
    langSelect.value = getCurrentLang();
    applyAllTranslations();
    renderApiList();
  });

  // ══════════════════════════════════════════════════════════════════════════
  //  API Management
  // ══════════════════════════════════════════════════════════════════════════

  const apiActiveSelect  = document.getElementById('api-active-select');
  const modelActiveSelect= document.getElementById('model-active-select');
  const apiList          = document.getElementById('api-list');
  const apiAddBtn        = document.getElementById('api-add-btn');
  const apiForm          = document.getElementById('api-form');
  const apiFormName      = document.getElementById('api-form-name');
  const apiFormUrl       = document.getElementById('api-form-url');
  const apiFormKey       = document.getElementById('api-form-key');
  const apiFormModels    = document.getElementById('api-form-models');
  const apiFormSave      = document.getElementById('api-form-save');
  const apiFormCancel    = document.getElementById('api-form-cancel');

  let editingId = null; // null = adding new, string = editing existing id

  // ── Render API active selector ────────────────────────────────────────────
  function renderActiveSelectors() {
    const apis   = loadApisSync();
    const selId  = ipcRenderer.sendSync('get-config', LS_SEL_API) || '';
    const selMod = ipcRenderer.sendSync('get-config', LS_SEL_MODEL) || '';

    // Populate API dropdown
    apiActiveSelect.innerHTML = '';
    const noneOpt = document.createElement('option');
    noneOpt.value = '';
    noneOpt.textContent = t('api.none');
    apiActiveSelect.appendChild(noneOpt);
    apis.forEach(api => {
      const opt = document.createElement('option');
      opt.value = api.id;
      opt.textContent = api.name;
      if (api.id === selId) opt.selected = true;
      apiActiveSelect.appendChild(opt);
    });

    // Populate Model dropdown based on selected API
    updateModelDropdown(apis.find(a => a.id === selId), selMod);
  }

  function updateModelDropdown(api, selectedModel) {
    modelActiveSelect.innerHTML = '';
    if (!api || !api.models || api.models.length === 0) {
      const opt = document.createElement('option');
      opt.value = '';
      opt.textContent = t('api.no_model');
      modelActiveSelect.appendChild(opt);
      return;
    }
    api.models.forEach(m => {
      const opt = document.createElement('option');
      opt.value = m;
      opt.textContent = m;
      if (m === selectedModel) opt.selected = true;
      modelActiveSelect.appendChild(opt);
    });
  }

  apiActiveSelect.addEventListener('change', () => {
    const apis = loadApisSync();
    const selId = apiActiveSelect.value;
    ipcRenderer.send('set-config', {key: LS_SEL_API, val: selId});
    const api = apis.find(a => a.id === selId);
    const firstModel = api && api.models[0] ? api.models[0] : '';
    ipcRenderer.send('set-config', {key: LS_SEL_MODEL, val: firstModel});
    updateModelDropdown(api, firstModel);
    broadcastLlmConfig();
  });

  modelActiveSelect.addEventListener('change', () => {
    ipcRenderer.send('set-config', {key: LS_SEL_MODEL, val: modelActiveSelect.value});
    broadcastLlmConfig();
  });

  // ── Render API list ───────────────────────────────────────────────────────
  function renderApiList() {
    const apis = loadApisSync();
    apiList.innerHTML = '';
    if (apis.length === 0) {
      const empty = document.createElement('div');
      empty.style.cssText = 'font-size:13px;color:#9ba8b8;padding:6px 0;';
      empty.textContent = t('api.none');
      apiList.appendChild(empty);
      renderActiveSelectors();
      return;
    }
    apis.forEach(api => {
      const item = document.createElement('div');
      item.className = 'api-item';
      const nameSpan = document.createElement('span');
      nameSpan.className = 'api-item-name';
      nameSpan.textContent = api.name;
      const urlSpan = document.createElement('span');
      urlSpan.className = 'api-item-url';
      urlSpan.textContent = api.baseUrl;
      const editBtn = document.createElement('button');
      editBtn.className = 'api-item-btn edit-btn';
      editBtn.textContent = t('api.edit');
      editBtn.addEventListener('click', () => openForm(api.id));
      const delBtn = document.createElement('button');
      delBtn.className = 'api-item-btn del del-btn';
      delBtn.textContent = t('api.delete');
      delBtn.addEventListener('click', () => deleteApi(api.id));
      item.appendChild(nameSpan);
      item.appendChild(urlSpan);
      item.appendChild(editBtn);
      item.appendChild(delBtn);
      apiList.appendChild(item);
    });
    renderActiveSelectors();
  }

  // ── Form open / close ────────────────────────────────────────────────────
  function openForm(id = null) {
    editingId = id;
    apiForm.classList.add('open');
    if (id) {
      const api = loadApisSync().find(a => a.id === id);
      if (api) {
        apiFormName.value   = api.name;
        apiFormUrl.value    = api.baseUrl;
        apiFormKey.value    = '';
        apiFormKey.placeholder = api.hasApiKey ? '•••••••• (leave blank to keep)' : t('api.form.key');
        apiFormModels.value = api.models.join(', ');
      }
    } else {
      apiFormName.value = apiFormUrl.value = apiFormKey.value = apiFormModels.value = '';
      apiFormKey.placeholder = t('api.form.key');
    }
    apiFormModels.disabled = true;
    apiFormModels.style.opacity = '0.6';
    apiFormName.focus();
  }

  async function autoFetchModels() {
    const url = apiFormUrl.value.trim();
    const key = apiFormKey.value.trim();
    if (!url || (!key && !editingId)) {
      apiFormModels.disabled = false;
      apiFormModels.style.opacity = '1';
      return;
    }
    apiFormModels.value = t('api.fetching_models') || 'Fetching...';
    try {
      const models = await ipcRenderer.invoke('api-fetch-models', {
        baseUrl: url,
        apiKey: key,
        apiId: editingId || '',
      });
      apiFormModels.value = Array.isArray(models) ? models.join(', ') : '';
    } catch (e) {
      console.error('Auto fetch models failed', e);
      apiFormModels.value = '';
    } finally {
      apiFormModels.disabled = false;
      apiFormModels.style.opacity = '1';
    }
  }

  apiFormUrl.addEventListener('blur', () => {
    if (!apiFormName.value.trim() && apiFormUrl.value.trim()) {
      try {
        let urlStr = apiFormUrl.value.trim();
        if (!urlStr.startsWith('http')) urlStr = 'https://' + urlStr;
        const urlObj = new URL(urlStr);
        const parts = urlObj.hostname.split('.');
        let name = parts[0];
        if (parts.length >= 2) {
          name = parts[parts.length - 2];
        }
        if (name) {
          // e.g., deepseek -> Deepseek
          apiFormName.value = name.charAt(0).toUpperCase() + name.slice(1);
        }
      } catch (e) {}
    }
    autoFetchModels();
  });
  apiFormKey.addEventListener('blur', autoFetchModels);

  function closeForm() {
    apiForm.classList.remove('open');
    editingId = null;
  }

  apiAddBtn.addEventListener('click', () => openForm(null));
  apiFormCancel.addEventListener('click', closeForm);

  // ── Save / Delete ─────────────────────────────────────────────────────────
  apiFormSave.addEventListener('click', async () => {
    const name   = apiFormName.value.trim();
    const url    = apiFormUrl.value.trim();
    const key    = apiFormKey.value.trim();
    const models = apiFormModels.value.split(',').map(m => m.trim()).filter(Boolean);
    if (!name || !url) return;

    const apis = [...loadApisSync()];
    if (editingId) {
      const idx = apis.findIndex(a => a.id === editingId);
      if (idx >= 0) apis[idx] = { id: editingId, name, baseUrl: url, apiKey: key, models };
    } else {
      apis.push({ id: uid(), name, baseUrl: url, apiKey: key, models });
    }
    if (!await saveApis(apis)) return;
    renderApiList();
    closeForm();
    broadcastLlmConfig();
  });

  async function deleteApi(id) {
    let apis = loadApisSync().filter(a => a.id !== id);
    if (!await saveApis(apis)) return;
    if (ipcRenderer.sendSync('get-config', LS_SEL_API) === id) {
      ipcRenderer.send('set-config', {key: LS_SEL_API, val: null});
      ipcRenderer.send('set-config', {key: LS_SEL_MODEL, val: null});
      broadcastLlmConfig();
    }
    renderApiList();
  }

  // ── Initial render (load encrypted APIs via main process first) ───────────
  loadApis().then(() => {
    renderApiList();
    broadcastLlmConfig();
  });

  // ══════════════════════════════════════════════════════════════════════════
  //  Ceremony (LoRA Initialization)
  // ══════════════════════════════════════════════════════════════════════════

  const btnStartCeremony = document.getElementById('btn-start-ceremony');
  const btnReinitCeremony = document.getElementById('btn-reinit-ceremony');
  const btnDeleteCeremony = document.getElementById('btn-delete-ceremony');
  const ceremonyModal = document.getElementById('ceremony-modal');
  const ceremonyModalText = document.getElementById('ceremony-modal-text');
  const ceremonyModalProgress = document.getElementById('ceremony-modal-progress');
  const ceremonyVideo = document.getElementById('ceremony-video');
  const ceremonyCanvas = document.getElementById('ceremony-canvas');
  const ceremonyNameInput = document.getElementById('ceremony-name-input');
  const ceremonyModalContinue = document.getElementById('ceremony-modal-continue');

  const ceremonyIdleSection = document.getElementById('ceremony-idle-section');
  const ceremonySuccessSection = document.getElementById('ceremony-success-section');
  const ceremonySuccessMsg = document.getElementById('ceremony-success-msg');

  let stream = null;
  let capturedData = [];
  let activeCeremonySocket = null;
  let priorCameraConnected = null;

  async function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

  function parseBackendMessage(event) {
    if (typeof event.data !== 'string' || event.data.length > 20_000_000) return null;
    try {
      const value = JSON.parse(event.data);
      return value && typeof value === 'object' && !Array.isArray(value) ? value : null;
    } catch {
      return null;
    }
  }

  function waitForBackendMessage(ws, predicate, timeoutMs = 5000, onMessage = null) {
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        cleanup();
        reject(new Error('Backend response timeout'));
      }, timeoutMs);
      const onClose = () => {
        cleanup();
        reject(new Error('Backend connection closed'));
      };
      const onData = (event) => {
        const data = parseBackendMessage(event);
        if (!data) return;
        if (onMessage) onMessage(data);
        if (!predicate(data)) return;
        cleanup();
        resolve(data);
      };
      function cleanup() {
        clearTimeout(timer);
        ws.removeEventListener('message', onData);
        ws.removeEventListener('close', onClose);
      }
      ws.addEventListener('message', onData);
      ws.addEventListener('close', onClose);
    });
  }

  async function connectAuthenticatedBackend() {
    const connection = await ipcRenderer.invoke('backend-connection');
    if (!connection || typeof connection.url !== 'string' || typeof connection.token !== 'string') {
      throw new Error('Backend endpoint is unavailable');
    }
    const ws = new WebSocket(connection.url);
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('WebSocket timeout')), 5000);
      ws.addEventListener('open', () => { clearTimeout(timer); resolve(); }, { once: true });
      ws.addEventListener('error', () => { clearTimeout(timer); reject(new Error('WebSocket error')); }, { once: true });
    });
    ws.send(JSON.stringify({
      type: 'authenticate',
      token: connection.token,
      launch_session: connection.launchSession || '',
    }));
    const authenticated = await waitForBackendMessage(ws, (data) => data.type === 'authenticated');
    if (authenticated.ok !== true) {
      ws.close();
      throw new Error('Backend authentication failed');
    }
    return ws;
  }

  async function queryCameraState(ws) {
    ws.send(JSON.stringify({ type: 'get_camera_status' }));
    const status = await waitForBackendMessage(
      ws,
      (data) => data.type === 'camera_status' && typeof data.connected === 'boolean',
    );
    return status.connected;
  }

  function stopCeremonyMedia() {
    if (stream) {
      stream.getTracks().forEach(track => track.stop());
      stream = null;
      ceremonyVideo.srcObject = null;
    }
  }

  function cleanupCeremony() {
    stopCeremonyMedia();
    if (activeCeremonySocket?.readyState === WebSocket.OPEN && priorCameraConnected !== null) {
      activeCeremonySocket.send(JSON.stringify({ type: 'toggle_camera', state: priorCameraConnected }));
    }
  }

  async function restoreCeremonyCamera() {
    stopCeremonyMedia();
    if (activeCeremonySocket?.readyState !== WebSocket.OPEN || priorCameraConnected === null) return;
    activeCeremonySocket.send(JSON.stringify({ type: 'toggle_camera', state: priorCameraConnected }));
    try {
      await waitForBackendMessage(
        activeCeremonySocket,
        (data) => data.type === 'camera_status' && data.connected === priorCameraConnected,
      );
    } catch (error) {
      console.warn('Could not confirm camera restoration:', error.message);
    }
  }

  window.addEventListener('beforeunload', cleanupCeremony);

  async function waitForContinue(btnText = "继续") {
    return new Promise(resolve => {
      ceremonyModalContinue.textContent = btnText;
      ceremonyModalContinue.style.display = 'block';
      const onClick = () => {
        ceremonyModalContinue.style.display = 'none';
        ceremonyModalContinue.removeEventListener('click', onClick);
        resolve();
      };
      ceremonyModalContinue.addEventListener('click', onClick);
    });
  }

  async function captureStage(label, promptTextKey, numImages = 25, delayMs = 200) {
    ceremonyModalText.textContent = t(promptTextKey);
    for (let i = 0; i < numImages; i++) {
      await sleep(delayMs);
      ceremonyCanvas.width = ceremonyVideo.videoWidth;
      ceremonyCanvas.height = ceremonyVideo.videoHeight;
      const ctx = ceremonyCanvas.getContext('2d');
      ctx.drawImage(ceremonyVideo, 0, 0, ceremonyCanvas.width, ceremonyCanvas.height);
      const dataUrl = ceremonyCanvas.toDataURL('image/jpeg', 0.8);
      capturedData.push({ label, image: dataUrl });
      
      const progress = (capturedData.length / 75) * 100;
      ceremonyModalProgress.style.width = progress + '%';
    }
  }

  async function startCeremony() {
    const masterName = ceremonyNameInput.value.trim();
    if (!masterName) {
      alert(t('ceremony.error.no_name'));
      return;
    }
    ceremonyModal.style.display = 'flex';
    ceremonyModalProgress.style.width = '0%';
    capturedData = [];

    try {
      activeCeremonySocket = await connectAuthenticatedBackend();
      priorCameraConnected = await queryCameraState(activeCeremonySocket);
      ceremonyModalText.textContent = t('ceremony.starting');
      activeCeremonySocket.send(JSON.stringify({ type: 'toggle_camera', state: false }));
      await waitForBackendMessage(
        activeCeremonySocket,
        (data) => data.type === 'camera_status' && data.connected === false,
      );

      stream = await navigator.mediaDevices.getUserMedia({ video: true });
      ceremonyVideo.srcObject = stream;
      await new Promise(r => ceremonyVideo.onloadedmetadata = r);
      await ceremonyVideo.play();

      await sleep(1000);

      // Stage 1: Neutral
      ceremonyModalText.textContent = t('ceremony.stage1.prep');
      await waitForContinue(t('ceremony.btn.ready'));
      await captureStage('neutral', 'ceremony.stage1.cap', 25, 200);
      
      // Stage 2: Happy
      ceremonyModalText.textContent = t('ceremony.stage2.prep');
      await waitForContinue(t('ceremony.btn.continue'));
      await captureStage('happy', 'ceremony.stage2.cap', 25, 200);
      
      // Stage 3: Sadness
      ceremonyModalText.textContent = t('ceremony.stage3.prep');
      await waitForContinue(t('ceremony.btn.continue'));
      await captureStage('sadness', 'ceremony.stage3.cap', 25, 200);

      // Stop camera
      stream.getTracks().forEach(t => t.stop());
      stream = null;
      ceremonyVideo.srcObject = null;

      ceremonyModalText.textContent = t('ceremony.training');
      ceremonyModalProgress.style.width = '0%';

      // Send to backend via existing WebSocket
      activeCeremonySocket.send(JSON.stringify({
        type: 'start_lora_training',
        master_name: masterName,
        data: capturedData
      }));
      const result = await waitForBackendMessage(
        activeCeremonySocket,
        (data) => data.type === 'training_complete',
        30 * 60 * 1000,
        (data) => {
          if (data.type === 'training_progress' && Number.isFinite(data.progress)) {
            ceremonyModalProgress.style.width = Math.max(0, Math.min(100, data.progress)) + '%';
          }
        },
      );
      if (result.success !== true) throw new Error(String(result.error || 'Training failed'));
      ceremonyModal.style.display = 'none';
      ceremonyIdleSection.style.display = 'none';
      ceremonySuccessSection.style.display = 'block';
      ceremonySuccessMsg.textContent = t('ceremony.success_title', { name: masterName });
      ipcRenderer.send('set-config', {key: 'miku-master-name', val: masterName});
    } catch (e) {
      console.error(e);
      alert("认主失败：" + e.message);
      ceremonyModal.style.display = 'none';
    } finally {
      await restoreCeremonyCamera();
      if (activeCeremonySocket) activeCeremonySocket.close();
      activeCeremonySocket = null;
      priorCameraConnected = null;
    }
  }

  btnStartCeremony.addEventListener('click', startCeremony);
  btnReinitCeremony.addEventListener('click', startCeremony);
  btnDeleteCeremony.addEventListener('click', async () => {
    if (confirm(t('ceremony.confirm_delete'))) {
      let ws = null;
      try {
        ws = await connectAuthenticatedBackend();
        ws.send(JSON.stringify({ type: 'delete_lora_data' }));
        await sleep(250);
        ipcRenderer.send('set-config', {key: 'miku-master-name', val: null});
        ceremonyNameInput.value = '';
        ceremonyIdleSection.style.display = 'flex';
        ceremonySuccessSection.style.display = 'none';
      } catch (error) {
        alert("删除失败：" + error.message);
      } finally {
        if (ws) ws.close();
      }
    }
  });

  // Check LoRA state on load (via main process — no direct fs for secrets dirs)
  ipcRenderer.invoke('has-lora').then((hasLora) => {
    if (hasLora) {
      const masterName = ipcRenderer.sendSync('get-config', 'miku-master-name') || '主人';
      ceremonyNameInput.value = masterName;
      ceremonyIdleSection.style.display = 'none';
      ceremonySuccessSection.style.display = 'block';
      ceremonySuccessMsg.textContent = t('ceremony.success_title', { name: masterName });
    }
  });

});
