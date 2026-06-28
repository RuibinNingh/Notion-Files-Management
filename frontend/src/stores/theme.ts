import { defineStore } from 'pinia'
import { ref } from 'vue'

export type ThemeMode = 'dark' | 'light'

const STORAGE_KEY = 'nfm-theme'

function resolveInitial(): ThemeMode {
  const saved = localStorage.getItem(STORAGE_KEY)
  if (saved === 'dark' || saved === 'light') return saved
  // 首次访问跟随系统偏好，默认深色
  return window.matchMedia?.('(prefers-color-scheme: light)').matches ? 'light' : 'dark'
}

function apply(mode: ThemeMode) {
  const html = document.documentElement
  if (mode === 'dark') html.classList.add('dark')
  else html.classList.remove('dark')
  html.style.colorScheme = mode
}

export const useThemeStore = defineStore('theme', () => {
  const mode = ref<ThemeMode>(resolveInitial())
  apply(mode.value)

  function setMode(next: ThemeMode) {
    mode.value = next
    localStorage.setItem(STORAGE_KEY, next)
    apply(next)
  }

  function toggle() {
    setMode(mode.value === 'dark' ? 'light' : 'dark')
  }

  return { mode, setMode, toggle }
})
