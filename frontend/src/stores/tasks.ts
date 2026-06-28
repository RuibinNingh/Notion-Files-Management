import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api } from '@/api/client'

export interface TaskSummary {
  task_id: string
  kind: string
  title: string
  source?: string
  status: string
  progress: Record<string, any>
  terminal: boolean
  error?: string | null
  retryable?: boolean
  input?: Record<string, any>
  artifact?: Record<string, any>
  cache_refs?: string[]
  created_at?: number
  updated_at?: number
  finished_at?: number | null
}

export const useTasksStore = defineStore('tasks', () => {
  const tasks = ref<TaskSummary[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)
  const streams = new Map<string, EventSource>()

  const sorted = computed(() => [...tasks.value].sort((a, b) => (b.created_at || 0) - (a.created_at || 0)))
  const running = computed(() => sorted.value.filter(t => !t.terminal && t.status === 'running'))
  const failed = computed(() => sorted.value.filter(t => t.status === 'error'))
  const recent = computed(() => sorted.value.slice(0, 5))

  function upsert(task: TaskSummary) {
    const idx = tasks.value.findIndex(t => t.task_id === task.task_id)
    if (idx >= 0) {
      tasks.value[idx] = { ...tasks.value[idx], ...task }
    } else {
      tasks.value.unshift(task)
    }
  }

  async function load() {
    loading.value = true
    error.value = null
    try {
      const r = await api.get('/api/tasks')
      tasks.value = r.data || []
      tasks.value.forEach(t => {
        if (!t.terminal && t.status === 'running') track(t.task_id)
      })
    } catch (e: any) {
      error.value = e?.message || '任务列表加载失败'
    } finally {
      loading.value = false
    }
  }

  function track(taskId: string) {
    if (!taskId || streams.has(taskId)) return
    const es = new EventSource(`/api/tasks/${taskId}/events`, { withCredentials: true })
    streams.set(taskId, es)

    es.addEventListener('progress', (e: MessageEvent) => {
      try {
        const progress = JSON.parse(e.data)
        const idx = tasks.value.findIndex(t => t.task_id === taskId)
        if (idx >= 0) {
          tasks.value[idx] = {
            ...tasks.value[idx],
            progress,
            status: progress.status || tasks.value[idx].status || 'running',
            terminal: !!progress.done,
            updated_at: Date.now() / 1000,
          }
        }
      } catch {}
    })

    es.addEventListener('done', (e: MessageEvent) => {
      try {
        const d = JSON.parse(e.data)
        const idx = tasks.value.findIndex(t => t.task_id === taskId)
        if (idx >= 0) {
          tasks.value[idx] = {
            ...tasks.value[idx],
            status: d.status || 'done',
            terminal: true,
            error: d.error || null,
            progress: { ...(tasks.value[idx].progress || {}), ...d },
            updated_at: Date.now() / 1000,
            finished_at: Date.now() / 1000,
          }
        }
      } catch {}
      stopTracking(taskId)
      refreshOne(taskId)
    })

    es.onerror = () => {
      const t = tasks.value.find(x => x.task_id === taskId)
      if (t?.terminal) stopTracking(taskId)
    }
  }

  function stopTracking(taskId: string) {
    const es = streams.get(taskId)
    if (es) es.close()
    streams.delete(taskId)
  }

  async function refreshOne(taskId: string) {
    try {
      const r = await api.get(`/api/tasks/${taskId}`)
      upsert(r.data)
      if (!r.data.terminal && r.data.status === 'running') track(taskId)
    } catch {}
  }

  async function cancel(taskId: string) {
    await api.post(`/api/tasks/${taskId}/cancel`)
    await refreshOne(taskId)
  }

  async function retry(taskId: string) {
    const r = await api.post(`/api/tasks/${taskId}/retry`)
    await load()
    track(r.data.task_id)
    return r.data.task_id as string
  }

  return {
    tasks,
    sorted,
    running,
    failed,
    recent,
    loading,
    error,
    load,
    track,
    cancel,
    retry,
    refreshOne,
  }
})
