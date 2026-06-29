<script setup lang="ts">
defineProps<{
  status: 'idle' | 'uploading' | 'processing' | 'done' | 'error',
  progress: number,
  message: string
}>()
</script>

<template>
  <div class="progress-container" v-if="status !== 'idle'">
    <div class="status-header">
      <span class="status-message">{{ message }}</span>
      <span class="status-percentage" v-if="status !== 'done' && status !== 'error'">
        {{ progress }}%
      </span>
    </div>
    
    <div class="progress-track" :class="{ 'error': status === 'error' }">
      <div 
        class="progress-fill" 
        :class="{ 'done': status === 'done' }"
        :style="{ width: `${progress}%` }"
      >
        <div class="equalizer-pattern" v-if="status !== 'done' && status !== 'error'"></div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.progress-container {
  margin-top: 2rem;
  background: var(--base-surface);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-md);
  padding: 1.5rem;
  animation: fadeIn 0.3s ease;
}

.status-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1rem;
}

.status-message {
  font-weight: 600;
  color: var(--text-main);
}

.status-percentage {
  color: var(--primary);
  font-family: monospace;
  font-weight: bold;
}

.progress-track {
  height: 16px;
  background: var(--border-light);
  border-radius: 8px;
  overflow: hidden;
  position: relative;
}

.progress-fill {
  height: 100%;
  background: var(--primary);
  transition: width 0.3s ease;
  position: relative;
  overflow: hidden;
}

.progress-fill.done {
  background: #28a745;
}

.progress-track.error .progress-fill {
  background: var(--accent);
}

.equalizer-pattern {
  position: absolute;
  top: 0;
  left: 0;
  bottom: 0;
  width: 200%;
  background-image: linear-gradient(
    45deg,
    rgba(255, 255, 255, 0.2) 25%,
    transparent 25%,
    transparent 50%,
    rgba(255, 255, 255, 0.2) 50%,
    rgba(255, 255, 255, 0.2) 75%,
    transparent 75%,
    transparent
  );
  background-size: 32px 32px;
  animation: moveStripes 1s linear infinite;
}

@keyframes moveStripes {
  0% { transform: translateX(0); }
  100% { transform: translateX(-32px); }
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
}
</style>
