const { ipcRenderer } = require('electron');
const { t, getCurrentLang, applyI18n } = require('./i18n');
const fs = require('fs');
const path = require('path');

// ── LocalStorage key for API list ─────────────────────────────────────────────
const userDir = path.join(__dirname, '..', 'user');
const keysDir = path.join(userDir, 'keys');
const apiJsonPath = path.join(keysDir, 'api.json');

const LS_SEL_API   = 'miku-sel-api';    // selected api id
const LS_SEL_MODEL = 'miku-sel-model';  // selected model string

function loadApis() {
  try {
    if (!fs.existsSync(keysDir)) fs.mkdirSync(keysDir, { recursive: true });
    if (fs.existsSync(apiJsonPath)) {
      return JSON.parse(fs.readFileSync(apiJsonPath, 'utf8')) || [];
    }
  } catch (e) { console.error('Failed to load api.json', e); }
  return [];
}
function saveApis(list) {
  try {
    if (!fs.existsSync(keysDir)) fs.mkdirSync(keysDir, { recursive: true });
    fs.writeFileSync(apiJsonPath, JSON.stringify(list, null, 2), 'utf8');
  } catch (e) { console.error('Failed to save api.json', e); }
}
function uid() {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
}

// ── Broadcast current LLM selection to backend (via main process) ─────────────
function broadcastLlmConfig() {
  const apis  = loadApis();
  const selId = ipcRenderer.sendSync('get-config', LS_SEL_API) || '';
  const model = ipcRenderer.sendSync('get-config', LS_SEL_MODEL) || '';
  const api   = apis.find(a => a.id === selId);
  if (api) {
    ipcRenderer.send('llm-changed', { baseUrl: api.baseUrl, apiKey: api.apiKey, model });
  } else {
    ipcRenderer.send('llm-changed', { baseUrl: '', apiKey: '', model: '' }); // revert to .env
  }
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

  let hasDeepface = false;
  
  async function checkDeepfaceStatus() {
    try {
      hasDeepface = await ipcRenderer.invoke('check-deepface');
      const opt = modelSelect.querySelector('option[value="deepface"]');
      const statusText = document.getElementById('deepface-status-text');
      const dlRow = document.getElementById('deepface-download-row');
      
      if (hasDeepface) {
        if (opt) opt.disabled = false;
        statusText.textContent = t('model.deepface.installed');
        statusText.style.color = '#39c5bb';
        dlRow.style.display = 'none';
      } else {
        if (opt) opt.disabled = true;
        statusText.textContent = t('model.deepface.not_installed');
        statusText.style.color = '#ff5f56';
        dlRow.style.display = 'flex';
        if (modelSelect.value === 'deepface') {
          modelSelect.value = 'mock';
          ipcRenderer.send('set-config', {key: 'miku-model-type', val: 'mock'});
          ipcRenderer.send('model-changed', 'mock');
        }
      }
    } catch (e) {
      console.error(e);
    }
  }

  const btnDownloadDeepface = document.getElementById('btn-download-deepface');
  const deepfaceProgCont = document.getElementById('deepface-progress-container');
  const deepfaceProgBar = document.getElementById('deepface-progress-bar');
  const deepfaceProgText = document.getElementById('deepface-progress-text');
  const deepfaceSpeedText = document.getElementById('deepface-speed-text');

  btnDownloadDeepface.addEventListener('click', () => {
    btnDownloadDeepface.style.display = 'none';
    deepfaceProgCont.style.display = 'flex';
    ipcRenderer.send('download-deepface');
  });

  ipcRenderer.on('deepface-download-status', (event, data) => {
    if (data.type === 'download_progress') {
      deepfaceProgBar.style.width = data.progress + '%';
      deepfaceProgText.textContent = data.progress + '%';
      deepfaceSpeedText.textContent = data.speed || '';
    } else if (data.type === 'download_complete') {
      if (data.success) {
        checkDeepfaceStatus();
      } else {
        alert("Download failed: " + data.error);
        btnDownloadDeepface.style.display = 'block';
        deepfaceProgCont.style.display = 'none';
      }
    }
  });

  // Dynamically load models from backend
  ipcRenderer.invoke('get-models').then((models) => {
    // Custom sort order requested by author
    const customOrder = ['best_rnn_attention.pth', 'best_cnn.pth', 'best_mobilenet_v2.pth'];
    models.sort((a, b) => {
      let idxA = customOrder.indexOf(a);
      let idxB = customOrder.indexOf(b);
      if (idxA === -1) idxA = 999;
      if (idxB === -1) idxB = 999;
      return idxA - idxB;
    });

    modelSelect.innerHTML = ''; // Clear existing hardcoded options

    // Add .pth models first
    models.forEach(modelName => {
      const opt = document.createElement('option');
      opt.value = modelName;
      opt.textContent = modelName;
      modelSelect.appendChild(opt);
    });

    // Add DeepFace
    const dfOpt = document.createElement('option');
    dfOpt.value = 'deepface';
    dfOpt.textContent = 'DeepFace（预训练）';
    dfOpt.setAttribute('data-i18n-option', 'model.deepface.name');
    modelSelect.appendChild(dfOpt);

    // Add Mock
    const mockOpt = document.createElement('option');
    mockOpt.value = 'mock';
    mockOpt.textContent = '亮度模拟器';
    mockOpt.setAttribute('data-i18n-option', 'model.mock.name');
    modelSelect.appendChild(mockOpt);

    applyAllTranslations(); // Re-apply i18n for the new options

  }).catch(err => {
    console.error('Failed to load models:', err);
  }).finally(() => {
    checkDeepfaceStatus().then(() => {
      const savedModel = ipcRenderer.sendSync('get-config', 'miku-model-type');
      if (savedModel && Array.from(modelSelect.options).some(o => o.value === savedModel && !o.disabled)) {
        modelSelect.value = savedModel;
      } else {
        const fallback = modelSelect.querySelector('option[value="deepface"]').disabled ? 'mock' : 'deepface';
        modelSelect.value = fallback;
        ipcRenderer.send('set-config', {key: 'miku-model-type', val: fallback});
      }
    });
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

  // ── Language Select ──────────────────────────────────────────────────────
  const langSelect = document.getElementById('lang-select');
  langSelect.value = getCurrentLang();
  langSelect.addEventListener('change', () => {
    const lang = langSelect.value;
    ipcRenderer.send('set-config', {key: 'miku-language', val: lang});
    applyAllTranslations();
    renderApiList();          // re-render API list with new i18n
    if (ceremonySuccessSection.style.display === 'block') {
      const masterName = ipcRenderer.sendSync('get-config', 'miku-master-name') || '主人';
      ceremonySuccessMsg.textContent = t('ceremony.success_title', { name: masterName });
    }
    ipcRenderer.send('lang-changed', lang);
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
    const apis   = loadApis();
    const selId  = ipcRenderer.sendSync('get-config', LS_SEL_API) || '';
    const selMod = ipcRenderer.sendSync('get-config', LS_SEL_MODEL) || '';

    // Populate API dropdown
    apiActiveSelect.innerHTML = `<option value="">${t('api.none')}</option>`;
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
    const apis = loadApis();
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
    const apis = loadApis();
    apiList.innerHTML = '';
    if (apis.length === 0) {
      const empty = document.createElement('div');
      empty.style.cssText = 'font-size:13px;color:#9ba8b8;padding:6px 0;';
      empty.textContent = t('api.none');
      apiList.appendChild(empty);
      return;
    }
    apis.forEach(api => {
      const item = document.createElement('div');
      item.className = 'api-item';
      item.innerHTML = `
        <span class="api-item-name">${api.name}</span>
        <span class="api-item-url">${api.baseUrl}</span>
        <button class="api-item-btn edit-btn">${t('api.edit')}</button>
        <button class="api-item-btn del del-btn">${t('api.delete')}</button>
      `;
      item.querySelector('.edit-btn').addEventListener('click', () => openForm(api.id));
      item.querySelector('.del-btn').addEventListener('click', () => deleteApi(api.id));
      apiList.appendChild(item);
    });
    renderActiveSelectors();
  }

  // ── Form open / close ────────────────────────────────────────────────────
  function openForm(id = null) {
    editingId = id;
    apiForm.classList.add('open');
    if (id) {
      const api = loadApis().find(a => a.id === id);
      if (api) {
        apiFormName.value   = api.name;
        apiFormUrl.value    = api.baseUrl;
        apiFormKey.value    = api.apiKey;
        apiFormModels.value = api.models.join(', ');
      }
    } else {
      apiFormName.value = apiFormUrl.value = apiFormKey.value = apiFormModels.value = '';
    }
    apiFormModels.disabled = true;
    apiFormModels.style.opacity = '0.6';
    apiFormName.focus();
  }

  async function autoFetchModels() {
    const url = apiFormUrl.value.trim();
    const key = apiFormKey.value.trim();
    if (!url || !key) {
      apiFormModels.disabled = false;
      apiFormModels.style.opacity = '1';
      return;
    }
    apiFormModels.value = t('api.fetching_models') || 'Fetching...';
    try {
      let safeUrl = url.replace(/\/+$/, '');
      let res = await fetch(`${safeUrl}/v1/models`, { headers: { 'Authorization': `Bearer ${key}` } }).catch(() => null);
      if (!res || !res.ok) {
        res = await fetch(`${safeUrl}/models`, { headers: { 'Authorization': `Bearer ${key}` } }).catch(() => null);
      }
      if (res && res.ok) {
        const data = await res.json();
        if (data && data.data && Array.isArray(data.data)) {
          const models = data.data.map(m => m.id);
          apiFormModels.value = models.join(', ');
        } else {
          apiFormModels.value = '';
        }
      } else {
        apiFormModels.value = '';
      }
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
  apiFormSave.addEventListener('click', () => {
    const name   = apiFormName.value.trim();
    const url    = apiFormUrl.value.trim();
    const key    = apiFormKey.value.trim();
    const models = apiFormModels.value.split(',').map(m => m.trim()).filter(Boolean);
    if (!name || !url) return;

    const apis = loadApis();
    if (editingId) {
      const idx = apis.findIndex(a => a.id === editingId);
      if (idx >= 0) apis[idx] = { id: editingId, name, baseUrl: url, apiKey: key, models };
    } else {
      apis.push({ id: uid(), name, baseUrl: url, apiKey: key, models });
    }
    saveApis(apis);
    renderApiList();
    closeForm();
    broadcastLlmConfig();
  });

  function deleteApi(id) {
    let apis = loadApis().filter(a => a.id !== id);
    saveApis(apis);
    if (ipcRenderer.sendSync('get-config', LS_SEL_API) === id) {
      ipcRenderer.send('set-config', {key: LS_SEL_API, val: null});
      ipcRenderer.send('set-config', {key: LS_SEL_MODEL, val: null});
      broadcastLlmConfig();
    }
    renderApiList();
  }

  // ── Initial render ────────────────────────────────────────────────────────
  renderApiList();

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

  async function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

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

    let ws = new WebSocket('ws://127.0.0.1:8765');
    
    // Wait for WS to connect
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error("WebSocket timeout")), 2000);
      ws.onopen = () => {
        clearTimeout(timer);
        resolve();
      };
      ws.onerror = () => {
        clearTimeout(timer);
        reject(new Error("WebSocket error"));
      };
    });

    try {
      ceremonyModalText.textContent = t('ceremony.starting');
      ws.send(JSON.stringify({ type: 'toggle_camera', state: false }));
      await sleep(1500);

      stream = await navigator.mediaDevices.getUserMedia({ video: true });
      ceremonyVideo.srcObject = stream;
      await new Promise(r => ceremonyVideo.onloadedmetadata = r);
      ceremonyVideo.play();

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
      ceremonyVideo.srcObject = null;

      ceremonyModalText.textContent = t('ceremony.training');
      ceremonyModalProgress.style.width = '0%';

      // Send to backend via existing WebSocket
      ws.send(JSON.stringify({
        type: 'start_lora_training',
        master_name: masterName,
        data: capturedData
      }));

      ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        if (data.type === 'training_progress') {
          ceremonyModalProgress.style.width = data.progress + '%';
        } else if (data.type === 'training_complete') {
          if (data.success) {
            ceremonyModal.style.display = 'none';
            ceremonyIdleSection.style.display = 'none';
            ceremonySuccessSection.style.display = 'block';
            ceremonySuccessMsg.textContent = t('ceremony.success_title', { name: masterName });
            ipcRenderer.send('set-config', {key: 'miku-master-name', val: masterName});
            // ceremony done is now file based
          } else {
            alert("认主失败：" + data.error);
            ceremonyModal.style.display = 'none';
          }
          setTimeout(() => ws.close(), 500);
        }
      };

      ws.onerror = (e) => {
        alert("无法连接到后端，认主失败。");
        ceremonyModal.style.display = 'none';
      };

    } catch (e) {
      console.error(e);
      alert("无法访问摄像头，认主失败：" + e.message);
      ceremonyModal.style.display = 'none';
      if (stream) stream.getTracks().forEach(t => t.stop());
      if (ws && ws.readyState === WebSocket.OPEN) {
          setTimeout(() => ws.close(), 500);
      }
    }
  }

  btnStartCeremony.addEventListener('click', startCeremony);
  btnReinitCeremony.addEventListener('click', startCeremony);
  btnDeleteCeremony.addEventListener('click', () => {
    if (confirm(t('ceremony.confirm_delete'))) {
      let ws = new WebSocket('ws://127.0.0.1:8765');
      ws.onopen = () => {
        ws.send(JSON.stringify({ type: 'delete_lora_data' }));
        setTimeout(() => ws.close(), 1000);
      };
      // ceremony done is now file based
      ipcRenderer.send('set-config', {key: 'miku-master-name', val: null});
      ceremonyNameInput.value = '';
      ceremonyIdleSection.style.display = 'flex';
      ceremonySuccessSection.style.display = 'none';
    }
  });

  // Check state on load
  const loraDir = path.join(__dirname, '..', 'user', 'lora');
  if (fs.existsSync(loraDir) && fs.readdirSync(loraDir).some(f => f.endsWith('.safetensors') || f.endsWith('.pth'))) {
    const masterName = ipcRenderer.sendSync('get-config', 'miku-master-name') || '主人';
    ceremonyNameInput.value = masterName;
    ceremonyIdleSection.style.display = 'none';
    ceremonySuccessSection.style.display = 'block';
    ceremonySuccessMsg.textContent = t('ceremony.success_title', { name: masterName });
  }

});
