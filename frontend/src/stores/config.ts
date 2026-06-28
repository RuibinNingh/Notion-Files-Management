import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '../api/client'

export interface AppConfig {
  notion_token?: string
  notion_base_url?: string
  max_download_workers?: number
  max_upload_workers?: number
  enable_range_download?: boolean
  range_download_min_mb?: number
  range_download_chunks?: number
  cache_auto_cleanup_enabled?: boolean
  cache_ttl_seconds?: number
  cache_cleanup_interval_seconds?: number
  theme_accent_color?: string
  background?: string
}

export const useConfigStore = defineStore('config', () => {
  const config = ref<AppConfig | null>(null)

  async function load() {
    try {
      const r = await api.get('/api/settings')
      config.value = r.data
    } catch {
      config.value = null
    }
  }

  async function save(patch: Partial<AppConfig> & { password?: string }) {
    await api.put('/api/settings', patch)
    await load()
  }

  return { config, load, save }
})
