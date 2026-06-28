import { reactive, onUnmounted } from 'vue'
import { api } from '@/api/client'

/** SSE 任务进度订阅 composable。
 * 后端终端事件统一为 `done`（data.status 区分 done/error/cancelled）。
 * 使用 reactive state 以便在模板中可深层访问（嵌套 ref 不会自动解包）。 */
export function useTask() {
  const state = reactive({
    progress: {} as Record<string, any>,
    status: 'idle' as string, // idle | running | done | error | cancelled
    error: null as string | null,
    done: false,
  })
  let es: EventSource | null = null

  function close() {
    if (es) { es.close(); es = null }
  }

  function _attachListeners(es: EventSource, onProgress?: (p: any) => void) {
    es.addEventListener('progress', (e: MessageEvent) => {
      try {
        state.progress = JSON.parse(e.data)
        onProgress?.(state.progress)
      } catch {}
    })

    es.addEventListener('done', (e: MessageEvent) => {
      try {
        const d = JSON.parse(e.data)
        state.progress = { ...state.progress, ...d }
        state.status = d.status || 'done'
        if (d.status === 'error') state.error = d.error || '任务出错'
        state.done = true
      } catch {}
      close()
    })

    es.onerror = () => {
      // EventSource 会自动重连；若已结束则关闭
      if (state.done) close()
    }
  }

  function start(taskId: string, onProgress?: (p: any) => void) {
    close()
    state.status = 'running'
    state.done = false
    state.error = null
    state.progress = {}

    es = new EventSource(`/api/tasks/${taskId}/events`, { withCredentials: true })
    _attachListeners(es, onProgress)
  }

  /** 重新订阅同一任务的 SSE，不重置 state（用于 keep-alive 切回页面时）。 */
  function reconnect(taskId: string, onProgress?: (p: any) => void) {
    close()
    if (state.done) return

    es = new EventSource(`/api/tasks/${taskId}/events`, { withCredentials: true })
    _attachListeners(es, onProgress)
  }

  async function cancel(taskId: string) {
    try { await api.post(`/api/tasks/${taskId}/cancel`) } catch {}
  }

  onUnmounted(close)

  return { state, start, stop: close, cancel, reconnect }
}
