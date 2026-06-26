<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { t } from '../i18n'

const isTraining = ref(false)
const epoch = ref(0)
const totalEpochs = ref(3) // 默认为3（快速测试的配置）
const loss = ref(0.0)
const lr = ref('1e-4')
const logs = ref<string[]>([])

const datasets = ref<string[]>([])
const configDataset = ref('')
const configModel = ref('cnn')
const configTrainAll = ref(false)
const configLr = ref(0.0001)
const configDynamicLr = ref(false)
const configEpochs = ref(30)
const configBatchSize = ref(64)

const displayTotalEpochs = computed(() => isTraining.value ? totalEpochs.value : configEpochs.value)
const displayLr = computed(() => {
  if (isTraining.value) return lr.value
  return configDynamicLr.value ? t('auto') : configLr.value
})

let ws: WebSocket | null = null

const connectWS = () => {
  ws = new WebSocket(`ws://${window.location.host}/ws/train`)
  ws.onopen = () => {
    ws?.send(JSON.stringify({ action: 'get_datasets' }))
  }
  ws.onmessage = (event) => {
    const data = JSON.parse(event.data)
    if (data.type === 'datasets') {
      datasets.value = data.datasets
      if (datasets.value.length > 0 && !configDataset.value) {
        configDataset.value = datasets.value[0]
      }
    } else if (data.type === 'status') {
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
  lr.value = configLr.value.toExponential(0)
  totalEpochs.value = configEpochs.value
  
  const payload = {
    action: 'start',
    dataset: configDataset.value,
    model: configTrainAll.value ? 'ALL' : configModel.value,
    lr: configLr.value,
    dynamicLr: configDynamicLr.value,
    epochs: configEpochs.value,
    batchSize: configBatchSize.value
  }

  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(payload))
  } else {
    connectWS()
    setTimeout(() => {
      ws?.send(JSON.stringify(payload))
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

    <div class="config-panel" v-if="!isTraining && epoch === 0">
      <div class="config-group">
        <label>{{ t('dataset') }}</label>
        <select v-model="configDataset" class="miku-input">
          <option v-for="ds in datasets" :key="ds" :value="ds">{{ ds }}</option>
        </select>
      </div>
      
      <div class="config-group">
        <div class="config-header">
          <label>{{ t('modelArchitecture') }}</label>
          <label class="dynamic-lr-label">
            <input type="checkbox" v-model="configTrainAll" class="miku-checkbox" />
            {{ t('trainAll') }}
          </label>
        </div>
        <div class="model-tabs" :class="{ disabled: configTrainAll }">
          <button 
            class="tab-btn" 
            :class="{ active: configModel === 'cnn' && !configTrainAll }" 
            :disabled="configTrainAll"
            @click="configModel = 'cnn'">EmotionCNN</button>
          <button 
            class="tab-btn" 
            :class="{ active: configModel === 'rnn' && !configTrainAll }" 
            :disabled="configTrainAll"
            @click="configModel = 'rnn'">RNN+Attention</button>
          <button 
            class="tab-btn" 
            :class="{ active: configModel === 'mobilenet' && !configTrainAll }" 
            :disabled="configTrainAll"
            @click="configModel = 'mobilenet'">MobileNetV2</button>
        </div>
      </div>

        <div class="hyperparams-grid">
          <div class="config-group">
            <div class="config-header">
              <label>{{ t('learningRate') }}</label>
              <label class="dynamic-lr-label">
                <input type="checkbox" v-model="configDynamicLr" class="miku-checkbox" />
                {{ t('dynamicLr') }}
              </label>
            </div>
            <input type="number" v-model="configLr" step="0.0001" class="miku-input" :disabled="configDynamicLr" :class="{ disabled: configDynamicLr }" />
          </div>
          <div class="config-group">
            <div class="config-header">
              <label>{{ t('totalEpochs') }}</label>
            </div>
            <input type="number" v-model="configEpochs" class="miku-input" />
          </div>
          <div class="config-group">
            <div class="config-header">
              <label>{{ t('batchSize') }}</label>
            </div>
            <input type="number" v-model="configBatchSize" class="miku-input" />
          </div>
      </div>
    </div>

      <div class="metrics-grid">
        <div class="metric-box">
          <span class="label">{{ t('epoch') }}</span>
          <span class="value">{{ epoch }} / {{ displayTotalEpochs }}</span>
        </div>
        <div class="metric-box">
          <span class="label">{{ t('loss') }}</span>
          <span class="value highlight">{{ loss.toFixed(4) }}</span>
        </div>
        <div class="metric-box">
          <span class="label">{{ t('lr') }}</span>
          <span class="value">{{ displayLr }}</span>
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

  .config-panel {
    display: flex;
    flex-direction: column;
    gap: 16px;
    margin-bottom: 10px;
  }
  
  .config-group {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  
  .config-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    height: 18px;
  }

  .dynamic-lr-label {
    display: flex;
    align-items: center;
    gap: 4px;
    cursor: pointer;
  }

  .config-group label {
    font-size: 12px;
    color: rgba(255, 255, 255, 0.9);
    font-weight: bold;
    letter-spacing: 1px;
    margin: 0;
  }

.miku-input {
  background: var(--base-surface);
  border: 1px solid var(--border-light);
  color: var(--text-main);
  padding: 8px 12px;
  border-radius: var(--radius-sm);
  font-family: inherit;
  font-size: 14px;
  transition: all 0.2s ease;
}

  .miku-input:focus:not(:disabled) {
    outline: none;
    border-color: var(--primary);
    box-shadow: 0 0 0 2px rgba(57, 197, 187, 0.2);
  }
  
  .miku-input:disabled {
    background: rgba(0, 0, 0, 0.05);
    color: var(--text-muted);
    cursor: not-allowed;
  }
  
  .miku-checkbox {
    appearance: none;
    -webkit-appearance: none;
    background: rgba(255, 255, 255, 0.2);
    border: 1px solid rgba(255, 255, 255, 0.5);
    border-radius: 3px;
    width: 14px;
    height: 14px;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    box-shadow: none;
    outline: none;
    transition: all 0.2s ease;
  }

  .miku-checkbox:checked {
    background: var(--primary);
    border-color: #fff;
  }

  .miku-checkbox:checked::before {
    content: "✓";
    color: #fff;
    font-size: 10px;
    font-weight: bold;
  }

.model-tabs {
  display: flex;
  background: var(--base-surface);
  border-radius: var(--radius-sm);
  padding: 4px;
  gap: 4px;
}

.tab-btn {
  flex: 1;
  background: transparent;
  border: none;
  color: var(--text-muted);
  padding: 8px;
  font-size: 13px;
  font-weight: bold;
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: all 0.2s ease;
}

.tab-btn.active {
  background: var(--primary);
  color: #fff;
  box-shadow: 0 2px 8px rgba(57, 197, 187, 0.3);
}

  .tab-btn:hover:not(.active) {
    background: rgba(0, 0, 0, 0.05);
  }

.hyperparams-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
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
  font-family: 'Courier New', Courier, monospace, 'PingFang SC', 'Microsoft YaHei', sans-serif;
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
