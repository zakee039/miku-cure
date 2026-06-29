<script setup lang="ts">
import { ref } from 'vue'
import { currentLocale, locales, t } from './i18n'
import TrainingConsole from './components/TrainingConsole.vue'

const currentView = ref<'training'>('training')

// Music Player Logic
const isMusicPlaying = ref(false)
const audioPlayer = ref<HTMLAudioElement | null>(null)

// Dynamically import all .ogg files from src/music/
const musicModules = import.meta.glob('@music/*.ogg', { eager: true })
const musicUrls = Object.values(musicModules).map((mod: any) => mod.default)

const playRandomMusic = async () => {
  if (musicUrls.length === 0) return
  const randomUrl = musicUrls[Math.floor(Math.random() * musicUrls.length)]
  
  try {
    if (!audioPlayer.value) {
      audioPlayer.value = new Audio(randomUrl)
      audioPlayer.value.volume = 0.5
      audioPlayer.value.addEventListener('ended', playRandomMusic)
    } else {
      audioPlayer.value.src = randomUrl
    }
    
    await audioPlayer.value.play()
    isMusicPlaying.value = true
  } catch (err) {
    console.error("Audio play failed:", err)
    isMusicPlaying.value = false
  }
}

const toggleMusic = () => {
  if (isMusicPlaying.value) {
    audioPlayer.value?.pause()
    isMusicPlaying.value = false
  } else {
    playRandomMusic()
  }
}


</script>

<template>
  <div class="app-container">
    <!-- Top Bar -->
    <div class="top-bar">
      <div class="left-controls">
        <!-- Removed inference view toggle -->
        
        <button class="music-btn" :class="{ 'is-playing': isMusicPlaying }" @click="toggleMusic">
          🎵
        </button>
      </div>
      
      <div class="top-bar-title">
        <span class="miku-text">{{ t('title') }}</span>
        <span class="sub-text">{{ t('subtitle') }}</span>
      </div>
      
      <div class="language-selector">
        <select v-model="currentLocale" class="lang-dropdown">
          <option v-for="loc in locales" :key="loc.value" :value="loc.value">
            v {{ loc.label }}
          </option>
        </select>
      </div>
    </div>

    <main class="main-content">
      <div class="view-container">
        
        <!-- Removed inference view -->

        <!-- Training Section -->
        <div v-if="currentView === 'training'" class="fade-in">
          <TrainingConsole />
        </div>
        
      </div>
    </main>
  </div>
</template>

<style scoped>
.app-container {
  max-width: 1200px;
  margin: 0 auto;
  padding: 2rem;
  display: flex;
  flex-direction: column;
  align-items: center;
}

.top-bar {
  width: 100%;
  max-width: 800px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 2rem;
}

.left-controls {
  display: flex;
  gap: 12px;
  align-items: center;
}

.music-btn {
  background: transparent;
  border: 2px solid var(--primary);
  border-radius: 50%;
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  position: relative;
  transition: all 0.2s ease;
  color: var(--primary);
  font-size: 16px;
  overflow: hidden;
}

.music-btn:hover {
  background: rgba(57, 197, 187, 0.1);
  transform: translateY(-2px);
}

.music-btn:not(.is-playing)::after {
  content: '';
  position: absolute;
  top: 50%;
  left: 10%;
  right: 10%;
  height: 2px;
  background-color: var(--accent);
  transform: translateY(-50%) rotate(-45deg);
}

.music-btn.is-playing {
  background: var(--primary);
  color: #fff;
  animation: pulse 2s infinite;
}

.top-bar-title {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 1.25rem;
  font-weight: 800;
  letter-spacing: 1px;
}

.miku-text {
  color: var(--primary);
  text-transform: uppercase;
}

.sub-text {
  color: var(--text-main);
  opacity: 0.8;
}

@keyframes pulse {
  0% { box-shadow: 0 0 0 0 rgba(57, 197, 187, 0.4); }
  70% { box-shadow: 0 0 0 10px rgba(57, 197, 187, 0); }
  100% { box-shadow: 0 0 0 0 rgba(57, 197, 187, 0); }
}

.toggle-view-btn {
  background: transparent;
  color: var(--accent);
  border: 2px solid var(--accent);
  border-radius: var(--radius-sm);
  padding: 6px 16px;
  font-weight: bold;
  cursor: pointer;
  transition: all 0.2s ease;
}

.toggle-view-btn:hover {
  background: var(--accent);
  color: #fff;
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(225, 40, 133, 0.2);
}

.lang-dropdown {
  appearance: none;
  background: transparent;
  border: none;
  color: var(--text-main);
  font-weight: bold;
  font-size: 1rem;
  cursor: pointer;
  padding: 4px 8px;
  outline: none;
  font-family: inherit;
}
.lang-dropdown:hover {
  color: var(--primary);
}

.header {
  text-align: center;
  margin-bottom: 2rem;
}

.title {
  font-size: 3rem;
  letter-spacing: -0.5px;
  color: var(--text-main);
}

.subtitle {
  color: var(--text-muted);
  font-size: 1.1rem;
  margin-top: 0.5rem;
  font-weight: bold;
  letter-spacing: 2px;
  text-transform: uppercase;
}

.main-content {
  width: 100%;
  display: flex;
  justify-content: center;
}

.view-container {
  width: 100%;
  max-width: 800px;
}

.fade-in {
  animation: fadeIn 0.4s ease;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1.5rem;
  padding-bottom: 1rem;
  border-bottom: 2px solid var(--border-light);
}

.panel-header h2 {
  font-size: 1.4rem;
  color: var(--text-main);
  display: flex;
  align-items: center;
  gap: 8px;
}

.status-badge {
  background: var(--base-surface);
  color: var(--text-muted);
  padding: 4px 12px;
  border-radius: var(--radius-sm);
  font-size: 0.8rem;
  font-weight: bold;
  border: 1px solid var(--border-light);
}

.status-badge.active {
  background: #e6f9f8;
  color: var(--primary);
  border-color: var(--primary);
}

.status-badge.done {
  background: #e6ffe6;
  color: #28a745;
  border-color: #28a745;
}

.action-bar {
  margin-top: 2rem;
  display: flex;
  gap: 1rem;
  justify-content: flex-end;
}

.generate-btn {
  min-width: 180px;
}

.download-btn {
  background: var(--base-bg);
  color: var(--primary);
  border: 2px solid var(--primary);
  box-shadow: none;
}
.download-btn:hover {
  background: var(--primary);
  color: #fff;
}
</style>
