<script setup lang="ts">
import { ref, watch } from 'vue'
import { t } from '../i18n'

const emit = defineEmits(['update:config'])

const energyGate = ref(0.5)

watch(energyGate, (newVal) => {
  emit('update:config', { energyGate: newVal })
})
</script>

<template>
  <div class="config-container">
    <label class="input-label">{{ t('configParams') }}</label>
    <div class="config-box">
      <div class="config-item">
        <div class="config-header">
          <span class="config-title">{{ t('configEnergyTitle') }}</span>
          <span class="config-value">{{ energyGate.toFixed(2) }}</span>
        </div>
        <p class="config-desc">{{ t('configEnergyDesc') }}</p>
        
        <div class="slider-wrapper">
          <input 
            type="range" 
            v-model.number="energyGate" 
            min="0" 
            max="1" 
            step="0.05" 
            class="miku-slider"
          >
          <div class="slider-marks">
            <span>0.0</span>
            <span>0.5</span>
            <span>1.0</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.config-container {
  margin-bottom: 2rem;
}

.input-label {
  display: block;
  font-size: 0.9rem;
  color: var(--text-muted);
  margin-bottom: 0.5rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 1px;
}

.config-box {
  background: var(--base-surface);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-md);
  padding: 1.5rem;
}

.config-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.5rem;
}

.config-title {
  font-weight: 600;
  color: var(--text-main);
}

.config-value {
  color: var(--primary);
  font-family: monospace;
  font-weight: bold;
  font-size: 1.1rem;
}

.config-desc {
  font-size: 0.85rem;
  color: var(--text-muted);
  margin-top: 0;
  margin-bottom: 1.5rem;
}

.slider-wrapper {
  padding: 0 5px;
}

.miku-slider {
  -webkit-appearance: none;
  width: 100%;
  height: 6px;
  background: var(--border-light);
  border-radius: 3px;
  outline: none;
  margin-bottom: 8px;
}

.miku-slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: var(--primary);
  cursor: pointer;
  box-shadow: 0 2px 6px rgba(57, 197, 187, 0.4);
  transition: transform 0.1s;
}

.miku-slider::-webkit-slider-thumb:hover {
  transform: scale(1.2);
}

.miku-slider::-moz-range-thumb {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: var(--primary);
  cursor: pointer;
  border: none;
  box-shadow: 0 2px 6px rgba(57, 197, 187, 0.4);
}

.slider-marks {
  display: flex;
  justify-content: space-between;
  font-size: 0.75rem;
  color: var(--text-muted);
}
</style>
