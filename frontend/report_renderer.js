const { ipcRenderer } = require('electron');

const reportPeriod = document.getElementById('report-period');
const chartBars = document.getElementById('chart-bars');
const reportCommentText = document.getElementById('report-comment-text');

const btnSing = document.getElementById('btn-sing');
const btnDance = document.getElementById('btn-dance');
const btnClose = document.getElementById('btn-close');


// Load data when sent from main process
ipcRenderer.on('load-report', (event, data) => {
  reportPeriod.textContent = `${data.startTime} ~ ${data.endTime} (专注 ${data.duration_minutes} 分钟)`;
  
  chartBars.innerHTML = '';
  
  const emotionLabels = {
    'happy': '😊 开?,
    'neutral': '😐 中?,
    'sadness': '😔 悲伤',
    'anger': '😠 愤?,
    'fear': '😨 焦虑',
    'disgust': '🤢 厌恶',
    'surprise': '😲 惊讶'
  };

  const stats = data.stats || {};
  
  for (const [emotion, percent] of Object.entries(stats)) {
    const row = document.createElement('div');
    row.className = 'chart-bar-row';
    
    const label = document.createElement('span');
    label.className = 'chart-bar-label';
    const emotionLabelKey = `emotion-${emotion}`;
    let transLabel = emotionLabels[emotion] || emotion;
    if (window.i18n && window.i18n.translations[currentLang] && window.i18n.translations[currentLang][emotionLabelKey]) {
      // Extract the emoji from the emotionLabels, append translated string
      const emoji = emotionLabels[emotion] ? emotionLabels[emotion].split(' ')[0] : '';
      transLabel = `${emoji} ${window.i18n.translations[currentLang][emotionLabelKey]}`;
    }
    
    label.textContent = transLabel;
    
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
    
    setTimeout(() => {
      inner.style.width = `${percent}%`;
    }, 100);
  }
  
  reportCommentText.textContent = data.comment || "Miku 今天陪着你，感觉很安心！";
});

btnSing.addEventListener('click', () => {
  ipcRenderer.send('action-from-report', 'sing');
  window.close();
});

btnDance.addEventListener('click', () => {
  ipcRenderer.send('action-from-report', 'dance');
  window.close();
});

btnClose.addEventListener('click', () => {
  window.close();
});
