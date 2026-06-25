<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { t } from '../i18n'

const isTraining = ref(false)
const epoch = ref(0)
const totalEpochs = ref(3) // 默认为3（快速测试的配置）
const loss = ref(0.0)
const lr = ref('1e-4')
const logs = ref<string[]>([])

let ws: WebSocket | null = null

const connectWS = () => {
  ws = new WebSocket(`ws://${window.location.host}/ws/train`)
  ws.onmessage = (event) => {
    const data = JSON.parse(event.data)
    if (data.type === 'status') {
      isTraining.value = data.status === 'running'
    } else if (data.type === 'log') {
      logs.value.push(data.line)
      if (logs.value.length > 15) logs.value.shift()
      
      const epochMatch = data.line.match(/Epoch (\d+)\/(\d+)/)
      if (epochMatch) {
        epoch.value = parseInt(epochMatch[1])
        totalEpochs.value = parseInt(epochMatch[2])
      }
      
      const lossMatch = data.line.match(/Loss: ([\d.]+)/)
      if (lossMatch) {
        loss.value = parseFloat(lossMatch[1])
      }
    }
  }
}

onMounted(() => {
  connectWS()
})

onUnmounted(() => {
  if (ws) ws.close()
})

const startTraining = () => {
  logs.value = []
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ action: 'start' }))
  } else {
    connectWS()
    setTimeout(() => {
      ws?.send(JSON.stringify({ action: 'start' }))
    }, 500)
  }
}

const pauseTraining = () => {
  // Not supported by simple subprocess
}

const stopTraining = () => {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ action: 'stop' }))
  }
}
</script>

<template>
  <div class="miku-card-mecha training-console">
    <div class="console-header">
      <h3>{{ t('trainingStation') }}</h3>
      <div class="status-indicator" :class="{ active: isTraining }">
        <span class="dot"></span>
        {{ isTraining ? t('trainRunning') : t('systemIdle') }}
      </div>
    </div>

    <div class="metrics-grid">
      <div class="metric-box">
        <span class="label">{{ t('epoch') }}</span>
        <span class="value">{{ epoch }} / {{ totalEpochs }}</span>
      </div>
      <div class="metric-box">
        <span class="label">{{ t('loss') }}</span>
        <span class="value highlight">{{ loss.toFixed(4) }}</span>
      </div>
      <div class="metric-box">
        <span class="label">{{ t('lr') }}</span>
        <span class="value">{{ lr }}</span>
      </div>
    </div>

    <div class="progress-bar-container">
      <div class="progress-fill" :style="{ width: `${totalEpochs > 0 ? (epoch / totalEpochs) * 100 : 0}%` }"></div>
    </div>
    
    <div class="terminal-logs">
      <div v-for="(line, idx) in logs" :key="idx" class="log-line">{{ line }}</div>
    </div>

    <div class="controls">
      <button v-if="!isTraining" class="btn-primary start-btn" @click="startTraining">
        {{ epoch > 0 ? t('resume') : t('startTraining') }}
      </button>
      <button v-else class="btn-accent pause-btn" @click="pauseTraining">
        {{ t('pause') }}
      </button>
      <button class="btn-primary stop-btn" :disabled="epoch === 0 && !isTraining" @click="stopTraining">
        {{ t('abort') }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.training-console {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.console-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 2px dashed var(--border-light);
  padding-bottom: 12px;
}

.console-header h3 {
  color: var(--primary);
  letter-spacing: 1px;
}

.status-indicator {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  font-weight: bold;
  color: var(--text-muted);
}

.status-indicator.active {
  color: var(--primary);
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--text-muted);
}

.active .dot {
  background: var(--primary);
  box-shadow: 0 0 8px var(--primary);
  animation: blink 1s infinite;
}

@keyframes blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

.metrics-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}

.metric-box {
  background: var(--base-surface);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-sm);
  padding: 16px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
}

.label {
  font-size: 11px;
  color: var(--text-muted);
  font-weight: bold;
  letter-spacing: 1px;
}

.value {
  font-size: 24px;
  font-weight: bold;
  color: var(--text-main);
  font-family: 'Courier New', Courier, monospace;
}

.highlight {
  color: var(--accent);
}

.progress-bar-container {
  height: 12px;
  background: var(--border-light);
  border-radius: 6px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: var(--primary);
  transition: width 0.3s ease;
}

.terminal-logs {
  background: #1e1e1e;
  color: #a9b7c6;
  font-family: 'Courier New', Courier, monospace;
  font-size: 11px;
  padding: 10px;
  border-radius: var(--radius-sm);
  height: 120px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
}

.log-line {
  white-space: pre-wrap;
  margin-bottom: 2px;
}

.controls {
  display: flex;
  gap: 12px;
  margin-top: 10px;
}

.start-btn {
  flex: 2;
}
.pause-btn {
  flex: 2;
}
.stop-btn {
  flex: 1;
  background: var(--base-surface);
  color: var(--text-main);
  border: 1px solid var(--border-light);
  box-shadow: none;
}
.stop-btn:hover:not(:disabled) {
  background: #ffeaef;
  color: var(--accent);
  border-color: var(--accent);
}
</style>
