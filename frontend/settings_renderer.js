const { ipcRenderer } = require('electron');

document.addEventListener('DOMContentLoaded', () => {
  // ── Navigation ──────────────────────────────────────
  const navItems = document.querySelectorAll('.nav-item');
  const pages    = document.querySelectorAll('.page');

  navItems.forEach(item => {
    item.addEventListener('click', () => {
      const target = item.dataset.page;

      navItems.forEach(n => n.classList.remove('active'));
      pages.forEach(p => p.classList.remove('active'));

      item.classList.add('active');
      const page = document.getElementById('page-' + target);
      if (page) page.classList.add('active');
    });
  });

  // ── Model selection ─────────────────────────────────
  const savedModel = localStorage.getItem('miku-model-type') || 'cnn';
  const savedRadio = document.querySelector(`input[name="model-select"][value="${savedModel}"]`);
  if (savedRadio) savedRadio.checked = true;

  document.getElementsByName('model-select').forEach(radio => {
    radio.addEventListener('change', (e) => {
      const selectedModel = e.target.value;
      localStorage.setItem('miku-model-type', selectedModel);
      ipcRenderer.send('model-changed', selectedModel);
    });
  });
});
