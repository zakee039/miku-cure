const { ipcRenderer } = require('electron');

document.addEventListener('DOMContentLoaded', () => {
  // Retrieve the model type saved in localStorage (defaulting to 'cnn')
  const savedModel = localStorage.getItem('miku-model-type') || 'cnn';
  const radio = document.querySelector(`input[name="model-select"][value="${savedModel}"]`);
  if (radio) {
    radio.checked = true;
  }

  // Listen for user changes on radio select
  const modelRadios = document.getElementsByName('model-select');
  modelRadios.forEach(radio => {
    radio.addEventListener('change', (e) => {
      const selectedModel = e.target.value;
      console.log("Settings: Changed model to", selectedModel);
      localStorage.setItem('miku-model-type', selectedModel);
      
      // Notify main process to broadcast the change
      ipcRenderer.send('model-changed', selectedModel);
    });
  });
});
