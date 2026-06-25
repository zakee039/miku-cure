const { ipcRenderer } = require('electron');
const { t, applyI18n } = require('./i18n');

const reportPeriod      = document.getElementById('report-period');
const chartBars         = document.getElementById('chart-bars');
const reportCommentText = document.getElementById('report-comment-text');

const btnSing  = document.getElementById('btn-sing');
const btnDance = document.getElementById('btn-dance');
const btnClose = document.getElementById('btn-close');
const btnCloseIcon = document.getElementById('btn-close-icon');

// Emotion key → emoji (language-neutral)
const emotionEmoji = {
  'happy':   '😊',
  'neutral': '😐',
  'sadness': '😔',
  'anger':   '😠',
  'fear':    '😨',
  'disgust': '🤢',
  'surprise':'😲'
};

// Apply translations on load
applyI18n();

// Load report data sent from main process
ipcRenderer.on('load-report', (event, data) => {
  const dur = data.duration_minutes;
  reportPeriod.textContent = `${data.startTime || '--:--'} ~ ${data.endTime || '--:--'}  (${dur} min)`;

  chartBars.innerHTML = '';

  const stats = data.stats || {};
  for (const [emotion, percent] of Object.entries(stats)) {
    if (percent < 0.5) continue; // skip near-zero entries

    const row = document.createElement('div');
    row.className = 'chart-bar-row';

    const label = document.createElement('span');
    label.className = 'chart-bar-label';
    const emoji = emotionEmoji[emotion] || '';
    label.textContent = `${emoji} ${t('emotion.' + emotion) || emotion}`;

    const outer = document.createElement('div');
    outer.className = 'chart-bar-outer';

    const inner = document.createElement('div');
    inner.className = `chart-bar-inner bar-${emotion}`;
    inner.style.width = '0%';

    const val = document.createElement('span');
    val.className = 'chart-bar-val';
    val.textContent = `${Math.round(percent)}%`;

    outer.appendChild(inner);
    row.appendChild(label);
    row.appendChild(outer);
    row.appendChild(val);
    chartBars.appendChild(row);

    setTimeout(() => { inner.style.width = `${percent}%`; }, 100);
  }

  // Update Miku comment (override the loading placeholder)
  reportCommentText.textContent = data.comment || t('report.loading');
});

// Re-apply translations when language changes
ipcRenderer.on('lang-changed', () => {
  applyI18n();
});

btnSing.addEventListener('click', () => {
  ipcRenderer.send('action-from-report', 'sing');
  window.close();
});

btnDance.addEventListener('click', () => {
  ipcRenderer.send('action-from-report', 'dance');
  window.close();
});

btnClose.addEventListener('click', () => window.close());
if (btnCloseIcon) btnCloseIcon.addEventListener('click', () => window.close());
