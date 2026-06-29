<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { t } from '../i18n'

const loadState = (key: string, defaultVal: any) => {
  const val = localStorage.getItem(`miku_cure_${key}`)
  return val ? JSON.parse(val) : defaultVal
}

const isTraining = ref(false)
const isPaused = ref(false)
const showAbortModal = ref(false)
const epoch = ref(0)
const totalEpochs = ref(3) // 默认为3（快速测试的配置）
const loss = ref(0.0)
const lr = ref('1e-4')
const logs = ref<string[]>([])

const datasets = ref<string[]>([])
const configDataset = ref('')

type ModelConfig = { lr: number, dynamicLr: boolean, epochs: number, batchSize: number }
const defaultConfigs: Record<string, ModelConfig> = {
  cnn: { lr: 0.0001, dynamicLr: false, epochs: 30, batchSize: 64 },
  rnn: { lr: 0.0001, dynamicLr: false, epochs: 30, batchSize: 64 },
  mobilenet: { lr: 0.0001, dynamicLr: false, epochs: 30, batchSize: 64 }
}

// 确保读取出的配置有全部字段
const loadedConfigs = loadState('modelConfigs', defaultConfigs)
const mergedConfigs = { ...defaultConfigs, ...loadedConfigs }
const modelConfigs = ref<Record<string, ModelConfig>>(mergedConfigs)

const selectedModels = ref<string[]>(loadState('selectedModels', ['cnn']))
const editingModel = ref<string>('cnn')
const trainingQueue = ref<string[]>(loadState('trainingQueue', []))
const currentTrainingModel = ref<string>(loadState('currentTrainingModel', ''))

watch(selectedModels, (val) => localStorage.setItem('miku_cure_selectedModels', JSON.stringify(val)), { deep: true })
watch(trainingQueue, (val) => localStorage.setItem('miku_cure_trainingQueue', JSON.stringify(val)), { deep: true })
watch(currentTrainingModel, (val) => localStorage.setItem('miku_cure_currentTrainingModel', JSON.stringify(val)))
watch(modelConfigs, (val) => localStorage.setItem('miku_cure_modelConfigs', JSON.stringify(val)), { deep: true })

const modelNameMap: Record<string, string> = {
  cnn: 'EmotionCNN',
  rnn: 'RNN+Attention',
  mobilenet: 'MobileNetV2'
}

const toggleModel = (model: string) => {
  editingModel.value = model
  const idx = selectedModels.value.indexOf(model)
  if (idx > -1) {
    selectedModels.value.splice(idx, 1)
  } else {
    selectedModels.value.push(model)
  }
}

const displayTotalEpochs = computed(() => {
  if (isTraining.value) return totalEpochs.value
  return modelConfigs.value[editingModel.value]?.epochs || 30
})

const displayLr = computed(() => {
  if (isTraining.value) return lr.value
  const conf = modelConfigs.value[editingModel.value]
  if (!conf) return '1e-4'
  return conf.dynamicLr ? t('auto') : conf.lr
})

let ws: WebSocket | null = null

const connectWS = () => {
  ws = new WebSocket(`ws://${window.location.host}/ws/train`)
  ws.onopen = () => {
    ws?.send(JSON.stringify({ action: 'get_datasets' }))
    ws?.send(JSON.stringify({ action: 'get_status' }))
  }
  ws.onmessage = (event) => {
    const data = JSON.parse(event.data)
    if (data.type === 'datasets') {
      datasets.value = data.datasets
      if (datasets.value.length > 0 && !configDataset.value) {
        configDataset.value = datasets.value[0]
      }
    } else if (data.type === 'status') {
      if (data.status === 'running') {
        isTraining.value = true
        isPaused.value = false
        if (data.model) currentTrainingModel.value = data.model
      } else if (data.status === 'paused') {
        isTraining.value = true
        isPaused.value = true
        if (data.model) currentTrainingModel.value = data.model
      } else if (data.status === 'stopped') {
        const wasTraining = isTraining.value
        isTraining.value = false
        isPaused.value = false
        if (wasTraining && trainingQueue.value.length > 0) {
          setTimeout(() => {
            processNextInQueue()
          }, 1000)
        } else if (!wasTraining) {
            // it was just a status sync on connect, do nothing
        } else {
            currentTrainingModel.value = ''
        }
      }
    } else if (data.type === 'recent_logs') {
      logs.value = data.logs
      // Extract latest epoch/loss to restore UI state
      data.logs.forEach((line: string) => {
        const epochMatch = line.match(/Epoch (\d+)\/(\d+)/)
        if (epochMatch) {
          epoch.value = parseInt(epochMatch[1])
          totalEpochs.value = parseInt(epochMatch[2])
        }
        const lossMatch = line.match(/Loss: ([\d.]+)/)
        if (lossMatch) {
          loss.value = parseFloat(lossMatch[1])
        }
      })
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
  if (selectedModels.value.length === 0) return
  trainingQueue.value = [...selectedModels.value]
  processNextInQueue()
}

const processNextInQueue = () => {
  if (trainingQueue.value.length === 0) {
    isTraining.value = false
    currentTrainingModel.value = ''
    return
  }
  const currentModel = trainingQueue.value.shift()
  if (!currentModel) return
  
  currentTrainingModel.value = currentModel

  const conf = modelConfigs.value[currentModel]
  
  logs.value = []
  lr.value = conf.lr.toExponential(0)
  totalEpochs.value = conf.epochs
  
  const payload = {
    action: 'start',
    dataset: configDataset.value,
    model: currentModel,
    lr: conf.lr,
    dynamicLr: conf.dynamicLr,
    epochs: conf.epochs,
    batchSize: conf.batchSize
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
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ action: isPaused.value ? 'resume' : 'pause' }))
  }
}

const stopTraining = () => {
  showAbortModal.value = true
}

const returnToHome = () => {
  trainingQueue.value = []
  currentTrainingModel.value = ''
  epoch.value = 0
  loss.value = 0.0
  isTraining.value = false
  isPaused.value = false
  logs.value = []
}

const confirmAbort = () => {
  showAbortModal.value = false
  trainingQueue.value = []
  currentTrainingModel.value = ''
  epoch.value = 0
  loss.value = 0.0
  isTraining.value = false
  isPaused.value = false
  logs.value = []
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ action: 'stop' }))
  }
}
</script>

<template>
  <div class="miku-card-mecha training-console">
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
        </div>
        <div class="model-tabs">
          <button 
            class="tab-btn" 
            :class="{ active: selectedModels.includes('cnn') }" 
            @click="toggleModel('cnn')">EmotionCNN</button>
          <button 
            class="tab-btn" 
            :class="{ active: selectedModels.includes('rnn') }" 
            @click="toggleModel('rnn')">RNN+Attention</button>
          <button 
            class="tab-btn" 
            :class="{ active: selectedModels.includes('mobilenet') }" 
            @click="toggleModel('mobilenet')">MobileNetV2</button>
        </div>
      </div>

      <div class="config-group" style="margin-top: 8px;">
        <div class="config-header">
          <label>{{ modelNameMap[editingModel] }} {{ t('paramAdjust') }}</label>
        </div>
        <div class="hyperparams-grid">
          <div class="config-group">
            <div class="config-header">
              <label>{{ t('initialLr') }}</label>
              <label class="dynamic-lr-label">
                <input type="checkbox" v-model="modelConfigs[editingModel].dynamicLr" class="miku-checkbox" />
                {{ t('dynamicLr') }}
              </label>
            </div>
            <input type="number" v-model="modelConfigs[editingModel].lr" step="0.0001" class="miku-input" />
          </div>
          <div class="config-group">
            <div class="config-header">
              <label>{{ t('totalEpochs') }}</label>
            </div>
            <input type="number" v-model="modelConfigs[editingModel].epochs" class="miku-input" />
          </div>
          <div class="config-group">
            <div class="config-header">
              <label>{{ t('batchSize') }}</label>
            </div>
            <input type="number" v-model="modelConfigs[editingModel].batchSize" class="miku-input" />
          </div>
        </div>
      </div>
    </div>

    <!-- 仅在训练或有训练数据时显示的训练看板 -->
    <div class="training-status-panel" v-if="isTraining || epoch > 0">
      <h2 class="training-title">{{ isTraining ? t('trainingInProgress') : t('trainingCompleteTitle') }}</h2>
      <div class="task-info">
        <span class="label">{{ t('currentTask') }}: {{ currentTrainingModel ? modelNameMap[currentTrainingModel] : 'N/A' }}</span>
        <span class="label">{{ t('remainingTasks') }}: {{ trainingQueue.length }}</span>
      </div>
      <div class="dashed-divider"></div>
      <template v-if="!isTraining && epoch > 0">
        <div class="completion-text">{{ t('trainingCompleteDesc') }}</div>
        <div class="dashed-divider"></div>
      </template>
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
      <template v-if="!isTraining && epoch === 0">
        <button class="btn-primary start-btn" :disabled="selectedModels.length === 0" @click="startTraining">
          {{ t('startTraining') }}
        </button>
      </template>
      <template v-else-if="isTraining">
        <button class="btn-accent pause-btn" @click="pauseTraining">
          {{ isPaused ? t('resumeTraining') : t('pause') }}
        </button>
        <button class="btn-primary stop-btn" @click="stopTraining">
          {{ t('abort') }}
        </button>
      </template>
      <template v-else-if="!isTraining && epoch > 0">
        <button class="btn-primary return-btn" @click="returnToHome">
          {{ t('returnHome') }}
        </button>
      </template>
    </div>

    <div class="miku-modal-overlay" v-if="showAbortModal">
      <div class="miku-modal">
        <div class="modal-body">{{ t('reallyAbort') }}</div>
        <div class="modal-actions">
          <button class="modal-btn abort-btn-red" @click="confirmAbort">{{ t('confirmAbort') }}</button>
          <button class="modal-btn resume-btn-white" @click="showAbortModal = false">{{ t('modalResume') }}</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.training-console {
  display: flex;
  flex-direction: column;
  gap: 20px;
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
  background: rgba(0, 0, 0, 0.15);
  border-radius: 6px;
  overflow: hidden;
  box-shadow: inset 0 1px 3px rgba(0, 0, 0, 0.1);
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, rgba(255,255,255,0.7) 0%, #ffffff 100%);
  box-shadow: 0 0 8px rgba(255, 255, 255, 0.5);
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
  background: white;
  color: var(--primary);
  font-weight: bold;
}
.start-btn:hover:not(:disabled) {
  background: #f0f0f0;
}
.pause-btn {
  flex: 2;
}
.stop-btn {
  flex: 1;
  background: var(--accent);
  color: white;
  border: none;
  box-shadow: 0 4px 12px rgba(233, 30, 99, 0.3);
}
.stop-btn:hover:not(:disabled) {
  background: #d81b60;
  color: white;
}

.miku-modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  width: 100vw;
  height: 100vh;
  background: rgba(0, 0, 0, 0.4);
  display: flex;
  justify-content: center;
  align-items: center;
  z-index: 1000;
  animation: fadeIn 0.2s ease;
}

.miku-modal {
  background: var(--base-surface, #ffffff);
  color: var(--text-main, #333);
  padding: 30px;
  border-radius: 8px;
  box-shadow: 0 4px 20px rgba(0,0,0,0.3);
  display: flex;
  flex-direction: column;
  gap: 24px;
  text-align: center;
  min-width: 320px;
}

.modal-body {
  font-size: 18px;
  font-weight: bold;
}

.modal-actions {
  display: flex;
  justify-content: center;
  gap: 16px;
}

.modal-btn {
  flex: 1;
  padding: 12px 0;
  border-radius: 4px;
  font-weight: bold;
  font-size: 15px;
  cursor: pointer;
  border: none;
  transition: all 0.2s ease;
}

.abort-btn-red {
  background: var(--accent);
  color: white;
}
.abort-btn-red:hover {
  background: #d81b60;
}

.resume-btn-white {
  background: white;
  color: var(--primary);
  border: 1px solid var(--border-light, #ccc);
}
.resume-btn-white:hover {
  background: #f0f0f0;
}

.training-status-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-bottom: 16px;
  animation: fadeIn 0.3s ease;
}

.training-title {
  text-align: center;
  color: var(--accent);
  font-size: 20px;
  letter-spacing: 2px;
  margin: 0;
}

.task-info {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0 4px;
}

.task-info .label {
  color: rgba(255, 255, 255, 0.9);
}

.dashed-divider {
  width: 100%;
  border-bottom: 1px dashed var(--border-light);
  margin-top: 4px;
}

.completion-text {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.9);
  font-weight: bold;
  letter-spacing: 1px;
  text-align: center;
  padding: 4px 0;
}

.return-btn {
  flex: 1;
  background: white;
  color: var(--primary);
  font-weight: bold;
}
.return-btn:hover {
  background: #f0f0f0;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(-5px); }
  to { opacity: 1; transform: translateY(0); }
}
</style>
