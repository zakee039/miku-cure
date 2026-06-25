const { ipcRenderer } = require('electron');
const { t, getCurrentLang, applyI18n } = require('./i18n');

// ── LocalStorage key for API list ─────────────────────────────────────────────
const LS_APIS = 'miku-apis';         // [{id,name,baseUrl,apiKey,models:[]}]
const LS_SEL_API   = 'miku-sel-api';    // selected api id
const LS_SEL_MODEL = 'miku-sel-model';  // selected model string

function loadApis() {
  try { return JSON.parse(localStorage.getItem(LS_APIS)) || []; } catch { return []; }
}
function saveApis(list) {
  localStorage.setItem(LS_APIS, JSON.stringify(list));
}
function uid() {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
}

// ── Broadcast current LLM selection to backend (via main process) ─────────────
function broadcastLlmConfig() {
  const apis  = loadApis();
  const selId = localStorage.getItem(LS_SEL_API) || '';
  const model = localStorage.getItem(LS_SEL_MODEL) || '';
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

  // ── Model Select ─────────────────────────────────────────────────────────
  const modelSelect = document.getElementById('model-select');
  modelSelect.value = localStorage.getItem('miku-model-type') || 'cnn';
  modelSelect.addEventListener('change', () => {
    localStorage.setItem('miku-model-type', modelSelect.value);
    ipcRenderer.send('model-changed', modelSelect.value);
  });

  // ── Size Select ──────────────────────────────────────────────────────────
  const sizeSelect = document.getElementById('size-select');
  sizeSelect.value = localStorage.getItem('miku-window-size') || 'medium';
  sizeSelect.addEventListener('change', () => {
    localStorage.setItem('miku-window-size', sizeSelect.value);
    ipcRenderer.send('size-changed', sizeSelect.value);
  });

  // ── Language Select ──────────────────────────────────────────────────────
  const langSelect = document.getElementById('lang-select');
  langSelect.value = getCurrentLang();
  langSelect.addEventListener('change', () => {
    const lang = langSelect.value;
    localStorage.setItem('miku-language', lang);
    applyAllTranslations();
    renderApiList();          // re-render API list with new i18n
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
    const selId  = localStorage.getItem(LS_SEL_API) || '';
    const selMod = localStorage.getItem(LS_SEL_MODEL) || '';

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
    localStorage.setItem(LS_SEL_API, selId);
    const api = apis.find(a => a.id === selId);
    const firstModel = api && api.models[0] ? api.models[0] : '';
    localStorage.setItem(LS_SEL_MODEL, firstModel);
    updateModelDropdown(api, firstModel);
    broadcastLlmConfig();
  });

  modelActiveSelect.addEventListener('change', () => {
    localStorage.setItem(LS_SEL_MODEL, modelActiveSelect.value);
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
    apiFormName.focus();
  }

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
    if (localStorage.getItem(LS_SEL_API) === id) {
      localStorage.removeItem(LS_SEL_API);
      localStorage.removeItem(LS_SEL_MODEL);
      broadcastLlmConfig();
    }
    renderApiList();
  }

  // ── Initial render ────────────────────────────────────────────────────────
  renderApiList();
});
