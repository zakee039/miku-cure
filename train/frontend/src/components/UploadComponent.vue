<script setup lang="ts">
import { ref } from 'vue'
import { t } from '../i18n'

const emit = defineEmits(['file-selected'])
const isDragging = ref(false)
const selectedFileName = ref('')

const onFileDrop = (e: DragEvent) => {
  isDragging.value = false
  const file = e.dataTransfer?.files[0]
  if (file && (file.type.includes('audio') || file.name.endsWith('.ogg') || file.name.endsWith('.mp3') || file.name.endsWith('.wav'))) {
    selectedFileName.value = file.name
    emit('file-selected', file)
  } else {
    alert('Please upload an audio file (.ogg, .mp3, .wav)')
  }
}

const onFileSelect = (e: Event) => {
  const target = e.target as HTMLInputElement
  const file = target.files?.[0]
  if (file) {
    selectedFileName.value = file.name
    emit('file-selected', file)
  }
}
</script>

<template>
  <div class="upload-container">
    <label class="input-label">{{ t('uploadAudioSource') }}</label>
    <div 
      class="upload-dropzone"
      :class="{ 'is-dragging': isDragging }"
      @dragover.prevent="isDragging = true"
      @dragleave.prevent="isDragging = false"
      @drop.prevent="onFileDrop"
    >
      <input 
        type="file" 
        id="audio-upload" 
        class="file-input" 
        accept="audio/*,.ogg,.mp3,.wav"
        @change="onFileSelect"
      >
      <label for="audio-upload" class="upload-label">
        <div class="upload-icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
            <polyline points="17 8 12 3 7 8" />
            <line x1="12" y1="3" x2="12" y2="15" />
          </svg>
        </div>
        <div class="upload-text">
          <span v-if="!selectedFileName" class="primary-text">{{ t('uploadDrop') }}</span>
          <span v-else class="success-text">{{ selectedFileName }}</span>
        </div>
        <div class="upload-subtext">{{ t('uploadSupport') }}</div>
      </label>
    </div>
  </div>
</template>

<style scoped>
.upload-container {
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

.upload-dropzone {
  border: 2px dashed var(--border-light);
  border-radius: var(--radius-md);
  background: var(--base-surface);
  transition: all 0.3s ease;
  position: relative;
}

.upload-dropzone.is-dragging {
  border-color: var(--primary);
  background: rgba(57, 197, 187, 0.05);
  box-shadow: 0 0 15px rgba(57, 197, 187, 0.2);
}

.upload-dropzone:hover {
  border-color: var(--primary);
}

.file-input {
  position: absolute;
  width: 0;
  height: 0;
  opacity: 0;
}

.upload-label {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 3rem 2rem;
  cursor: pointer;
  height: 100%;
}

.upload-icon {
  width: 48px;
  height: 48px;
  color: var(--primary);
  margin-bottom: 1rem;
  transition: transform 0.3s ease;
}

.upload-dropzone:hover .upload-icon {
  transform: translateY(-5px);
}

.upload-text {
  font-size: 1.1rem;
  font-weight: 600;
  margin-bottom: 0.5rem;
}

.primary-text {
  color: var(--text-main);
}

.success-text {
  color: var(--primary);
  word-break: break-all;
  text-align: center;
}

.upload-subtext {
  font-size: 0.85rem;
  color: var(--text-muted);
}
</style>
