<template>
  <div class="page page-stack">
    <div class="page-head board-head">
      <div>
        <div class="page-kicker">Tasks</div>
        <h1 class="page-title"><el-icon><List /></el-icon><span>任务看板</span></h1>
      </div>
      <div class="action-row">
        <el-button :icon="Refresh" :loading="tasks.loading" @click="tasks.load">刷新</el-button>
      </div>
    </div>

    <div class="board-stats">
      <div class="stat-pill">
        <span>全部</span>
        <strong>{{ tasks.sorted.length }}</strong>
      </div>
      <div class="stat-pill">
        <span>运行中</span>
        <strong>{{ tasks.running.length }}</strong>
      </div>
      <div class="stat-pill danger">
        <span>失败</span>
        <strong>{{ tasks.failed.length }}</strong>
      </div>
    </div>

    <el-card class="panel" shadow="never">
      <div class="board-toolbar">
        <div>
          <div class="panel-title">任务列表</div>
          <div class="panel-subtitle">{{ filtered.length }} / {{ tasks.sorted.length }} · {{ activeFilterText }}</div>
        </div>
        <el-radio-group v-model="filter" class="filter-group" size="small">
          <el-radio-button value="all">全部</el-radio-button>
          <el-radio-button value="running">运行中</el-radio-button>
          <el-radio-button value="error">失败</el-radio-button>
          <el-radio-button value="done">已完成</el-radio-button>
          <el-radio-button value="cancelled">已取消</el-radio-button>
        </el-radio-group>
      </div>

      <el-empty v-if="!tasks.loading && !filtered.length" description="暂无任务" :image-size="80" />

      <div v-else class="task-queue">
        <div v-for="task in filtered" :key="task.task_id" class="queue-row">
          <div class="queue-main">
            <div class="queue-status">
              <span class="t-status" :class="statusClass(task.status)">{{ statusText(task.status) }}</span>
            </div>

            <div class="queue-title">
              <span class="task-name">{{ task.title || task.kind }}</span>
              <span class="task-meta-line">{{ kindText(task.kind) }} · {{ fmtTime(task.created_at) }}</span>
            </div>

            <div class="queue-progress">
              <div class="queue-progress-head">
                <strong>{{ taskPercent(task) }}%</strong>
                <span>{{ taskMetric(task) }}</span>
              </div>
              <el-progress :percentage="taskPercent(task)" :status="progressStatus(task.status)" :stroke-width="5" :show-text="false" />
            </div>

            <div class="queue-summary">
              <span>{{ taskSummary(task) }}</span>
              <span v-if="task.error" class="task-error">{{ task.error }}</span>
            </div>

            <div class="queue-actions">
              <el-button v-if="task.status === 'running'" link type="danger" @click="onCancel(task)">取消</el-button>
              <el-button v-if="task.retryable && task.terminal" link type="primary" :loading="retrying === task.task_id" @click="onRetry(task)">重试</el-button>
              <el-button v-if="task.kind === 'download' && task.terminal" link :icon="Download" @click="open(`/api/download/${task.task_id}/zip`)">ZIP</el-button>
              <el-button v-if="task.artifact?.cache_id" link @click="router.push('/cache')">缓存</el-button>
            </div>
          </div>

          <el-collapse class="queue-detail" @change="onDetailToggle(task, $event)">
            <el-collapse-item name="detail">
              <template #title>
                <span class="detail-title">详情</span>
                <span v-if="detailCount(task)" class="detail-count">{{ detailCount(task) }}</span>
              </template>

              <div class="detail-shell">
                <div v-if="task.kind === 'download' && task.progress?.perf" class="metric-bar">
                  <div><span>并发</span><strong>{{ task.progress.perf.active_files || 0 }} / {{ task.progress.perf.max_workers || 0 }}</strong></div>
                  <div><span>排队</span><strong>{{ task.progress.perf.waiting_files || 0 }}</strong></div>
                  <div><span>当前</span><strong>{{ fmtSize(task.progress.perf.speed_mb_s || 0) }}/s</strong></div>
                  <div><span>平均</span><strong>{{ fmtSize(task.progress.perf.avg_speed_mb_s || 0) }}/s</strong></div>
                  <div><span>已下载</span><strong>{{ fmtSize(task.progress.perf.downloaded_mb || 0) }} / {{ fmtSize(task.progress.perf.total_mb || 0) }}</strong></div>
                  <div><span>耗时</span><strong>{{ fmtEta(task.progress.perf.elapsed_s || 0) }}</strong></div>
                </div>

                <div v-if="task.kind === 'download' && task.progress?.perf" class="detail-note">{{ perfHint(task) }}</div>

                <div v-if="task.kind === 'scan'" class="scan-detail">
                  <div v-if="scanLoading[task.task_id]" class="detail-note">正在加载扫描结果…</div>
                  <el-empty v-else-if="!scanItems(task).length" description="暂无扫描结果" :image-size="56" />
                  <div v-else class="detail-table scan-table">
                    <div class="detail-table-head">
                      <span>文件</span>
                      <span>大小</span>
                      <span>来源</span>
                    </div>
                    <div v-for="(item, idx) in scanItems(task)" :key="itemKey(item, idx)" class="detail-table-row">
                      <span class="file-name">{{ itemName(item) }}</span>
                      <span>{{ Number(item.size_mb || 0) > 0 ? fmtSize(Number(item.size_mb) || 0) : '-' }}</span>
                      <span class="mono-cell">{{ shortBlock(item.block_id || item.url) }}</span>
                    </div>
                  </div>
                </div>

                <div v-else-if="taskItems(task).length" class="detail-table">
                  <div class="detail-table-head">
                    <span>文件</span>
                    <span>状态</span>
                    <span>进度</span>
                    <span>速度</span>
                    <span>模式</span>
                  </div>
                  <div v-for="(item, idx) in taskItems(task)" :key="itemKey(item, idx)" class="detail-table-row">
                    <span class="file-name">{{ itemName(item) }}</span>
                    <span><span class="t-status" :class="itemStatusClass(item)">{{ itemStatusText(item) }}</span></span>
                    <span>{{ transferredText(task, item) }} · {{ itemPercent(item) }}%</span>
                    <span>{{ fmtSize(Number(item.speed_mb_s) || 0) }}/s</span>
                    <span>{{ task.kind === 'download' ? rangeText(item) : itemTimingText(item) }}</span>
                    <span v-if="item.error" class="row-error">{{ item.error }}</span>
                  </div>
                </div>

                <div v-else class="task-detail-grid">
                  <div v-for="entry in detailEntries(task)" :key="entry.label" class="detail-entry">
                    <span class="detail-label">{{ entry.label }}</span>
                    <span class="detail-value">{{ entry.value }}</span>
                  </div>
                </div>
              </div>
            </el-collapse-item>
          </el-collapse>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Download, List, Refresh } from '@element-plus/icons-vue'
import { useTasksStore, type TaskSummary } from '@/stores/tasks'
import { api, errMsg } from '@/api/client'
import { fmtSize, fmtEta } from '@/utils/format'

const router = useRouter()
const tasks = useTasksStore()
const filter = ref('all')
const retrying = ref('')
const scanLoading = ref<Record<string, boolean>>({})
const scanResults = ref<Record<string, any[]>>({})

const filtered = computed(() => {
  if (filter.value === 'all') return tasks.sorted
  if (filter.value === 'running') return tasks.sorted.filter(t => t.status === 'running' && !t.terminal)
  return tasks.sorted.filter(t => t.status === filter.value)
})
const activeFilterText = computed(() => ({ all: '全部', running: '运行中', error: '失败', done: '已完成', cancelled: '已取消' } as any)[filter.value] || filter.value)

onMounted(() => tasks.load())

async function onCancel(task: TaskSummary) {
  try {
    await ElMessageBox.confirm(`确定取消任务「${task.title || task.task_id}」？`, '取消任务', { type: 'warning' })
    await tasks.cancel(task.task_id)
    ElMessage.success('任务已取消')
  } catch (e: any) {
    if (e !== 'cancel') ElMessage.error(errMsg(e))
  }
}

async function onRetry(task: TaskSummary) {
  retrying.value = task.task_id
  try {
    const next = await tasks.retry(task.task_id)
    ElMessage.success(`已创建重试任务 ${next}`)
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    retrying.value = ''
  }
}

function open(url: string) {
  window.open(url, '_blank')
}

function onDetailToggle(task: TaskSummary, names: unknown) {
  void onDetailChange(task, names)
}

async function onDetailChange(task: TaskSummary, names: unknown) {
  const open = Array.isArray(names) ? names.includes('detail') : names === 'detail'
  if (open && task.kind === 'scan') await loadScanResults(task)
}

async function loadScanResults(task: TaskSummary) {
  if (!task.task_id || scanLoading.value[task.task_id] || scanResults.value[task.task_id]) return
  scanLoading.value = { ...scanLoading.value, [task.task_id]: true }
  try {
    const r = await api.get(`/api/scan/${task.task_id}/list`)
    scanResults.value = { ...scanResults.value, [task.task_id]: r.data.items || [] }
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    scanLoading.value = { ...scanLoading.value, [task.task_id]: false }
  }
}

function taskPercent(task: TaskSummary) {
  const p = task.progress || {}
  if (typeof p.percent === 'number') return Math.min(100, Math.max(0, Math.round(p.percent)))
  const items = Array.isArray(p.items) ? p.items : []
  if (items.length) {
    const total = items.reduce((sum, it) => sum + (Number(it.progress) || 0), 0)
    return Math.round(total / items.length)
  }
  if (task.terminal) return (task.status === 'error' || task.status === 'cancelled') ? 0 : 100
  return 0
}

function taskSummary(task: TaskSummary) {
  const p = task.progress || {}
  if (task.kind === 'scan') return `已发现 ${p.items_count || p.discovered || 0} · 已探测 ${p.files_probed || 0}/${p.total_urls || 0}`
  if (task.kind === 'download') return itemSummary(p.items, '下载')
  if (task.kind === 'upload') return itemSummary(p.items, '上传')
  if (typeof p.total !== 'undefined') return `总计 ${p.total || 0} · 完成 ${p.done || 0} · 失败 ${p.failed || 0}`
  return task.input?.page_id ? `Page ID ${task.input.page_id}` : task.task_id
}

function taskMetric(task: TaskSummary) {
  const p = task.progress || {}
  if (task.kind === 'download' && p.perf) return `${fmtSize(Number(p.perf.speed_mb_s) || 0)}/s · ${fmtSize(Number(p.perf.downloaded_mb) || 0)}`
  if (task.kind === 'scan') return `${p.files_probed || 0}/${p.total_urls || 0} 探测`
  if (task.kind === 'upload') return itemSummary(p.items, '上传')
  if (typeof p.done !== 'undefined' || typeof p.total !== 'undefined') return `${p.done || 0}/${p.total || 0}`
  return statusText(task.status)
}

function taskItems(task: TaskSummary): any[] {
  const items = task.progress?.items
  return Array.isArray(items) ? items : []
}

function scanItems(task: TaskSummary): any[] {
  return scanResults.value[task.task_id] || []
}

function detailCount(task: TaskSummary) {
  if (task.kind === 'scan') {
    const loaded = scanResults.value[task.task_id]?.length
    const count = loaded || task.progress?.items_count || task.progress?.discovered || 0
    return count ? `${count} 项` : ''
  }
  const count = taskItems(task).length
  return count ? `${count} 项` : ''
}

function itemKey(item: any, idx: number) {
  return item.url || item.file_path || item.save_name || item.real_name || `${idx}`
}

function itemName(item: any) {
  const p = item.file_path || item.real_name || item.save_name || item.name || item.url || '文件'
  return String(p).split(/[\\/]/).pop()
}

function itemPercent(item: any) {
  return Math.min(100, Math.max(0, Math.round(Number(item.progress) || 0)))
}

function transferredText(task: TaskSummary, item: any) {
  const done = task.kind === 'upload' ? item.uploaded_mb : item.downloaded_mb
  const total = item.total_mb
  return `${fmtSize(Number(done) || 0)} / ${fmtSize(Number(total) || 0)}`
}

function rangeText(item: any) {
  if (item.mode === 'range') return `分片 ${item.range_chunks || 0}`
  if (item.range_reason && item.range_reason !== 'disabled') return `单连接 · ${item.range_reason}`
  return '单连接'
}

function itemTimingText(item: any) {
  if (item.ETA) return `剩余 ${fmtEta(Number(item.ETA) || 0)}`
  if (item.usedTime) return `耗时 ${fmtEta(Number(item.usedTime) || 0)}`
  return '-'
}

function itemStatusText(item: any) {
  if (item.error) return '错误'
  return ({
    waiting: '等待中',
    uploading: '上传中',
    downloading: '下载中',
    refreshing: '刷新链接',
    completed: '已完成',
    error: '错误',
  } as any)[item.status] || item.status || '等待中'
}

function itemStatusClass(item: any) {
  if (item.error) return 'err'
  return ({ completed: 'ok', error: 'err', waiting: 'wait' } as any)[item.status] || 'wait'
}

function detailEntries(task: TaskSummary) {
  const p = task.progress || {}
  const entries: Array<{ label: string; value: string }> = []
  if (task.task_id) entries.push({ label: '任务 ID', value: task.task_id })
  if (task.kind) entries.push({ label: '类型', value: task.kind })
  if (task.input?.page_id) entries.push({ label: 'Page ID', value: String(task.input.page_id) })
  if (typeof p.percent !== 'undefined') entries.push({ label: '进度', value: `${Math.round(Number(p.percent) || 0)}%` })
  if (typeof p.total !== 'undefined') entries.push({ label: '总计', value: String(p.total || 0) })
  if (typeof p.done !== 'undefined') entries.push({ label: '完成', value: String(p.done || 0) })
  if (typeof p.failed !== 'undefined') entries.push({ label: '失败', value: String(p.failed || 0) })
  if (typeof p.items_count !== 'undefined') entries.push({ label: '已发现', value: String(p.items_count || 0) })
  if (typeof p.files_probed !== 'undefined') entries.push({ label: '已探测', value: `${p.files_probed || 0}/${p.total_urls || 0}` })
  return entries.length ? entries : [{ label: '状态', value: task.status }]
}

function perfHint(task: TaskSummary) {
  const perf = task.progress?.perf || {}
  if (perf.queue_pressure) return `当前达到下载并发上限 ${perf.max_workers}，仍有 ${perf.waiting_files} 个文件排队；可以在设置页临时提高下载并发观察是否改善。`
  if ((perf.active_files || 0) > 0 && (perf.speed_mb_s || 0) <= 0.05) return '已有文件在下载但速率很低，优先检查 Notion 链接响应、服务器出口带宽或目标磁盘写入。'
  if ((perf.total_files || 0) > 0 && (perf.active_files || 0) === 0 && (perf.waiting_files || 0) > 0) return '任务仍在等待线程调度，可能是下载线程池被其它文件占满。'
  if ((perf.failed_files || 0) > 0) return '存在失败文件，展开文件列表查看具体错误；链接过期会触发刷新链接流程。'
  return '当前未发现明显排队瓶颈；如果体感仍慢，重点看单文件速率和等待时间。'
}

function itemSummary(items: any[] | undefined, label: string) {
  const list = Array.isArray(items) ? items : []
  const done = list.filter(it => it.status === 'completed').length
  const failed = list.filter(it => it.status === 'error' || it.error).length
  return `${label} ${done}/${list.length} · 失败 ${failed}`
}

function kindText(kind: string) {
  return ({ scan: '扫描', download: '下载', upload: '上传', migrate: '迁移', suffix: '后缀', 'page-size': '页面大小' } as any)[kind] || kind
}

function shortBlock(v?: string) {
  const s = String(v || '')
  if (!s) return '-'
  return s.length > 18 ? `${s.slice(0, 8)}…${s.slice(-6)}` : s
}

function statusText(s: string) {
  return ({ running: '运行中', done: '已完成', error: '失败', cancelled: '已取消' } as any)[s] || s
}

function statusClass(s: string) {
  return ({ done: 'ok', error: 'err', cancelled: 'wait', running: 'wait' } as any)[s] || 'wait'
}

function progressStatus(s: string) {
  if (s === 'done') return 'success'
  if (s === 'error' || s === 'cancelled') return 'exception'
  return undefined
}

function fmtTime(ts?: number) {
  if (!ts) return '-'
  return new Date(ts * 1000).toLocaleString()
}
</script>

<style scoped>
.board-head {
  margin-bottom: 2px;
}
.board-stats {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.stat-pill {
  display: inline-flex;
  align-items: baseline;
  gap: 8px;
  min-height: 34px;
  padding: 6px 10px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--radius-sm);
  background: var(--app-surface-2);
}
.stat-pill span {
  color: var(--app-muted);
  font-size: 12px;
}
.stat-pill strong {
  color: var(--app-text);
  font-size: 17px;
  line-height: 1;
}
.stat-pill.danger strong {
  color: var(--app-danger);
}
.board-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}
.task-queue {
  display: grid;
  gap: 8px;
}
.queue-row {
  min-width: 0;
  padding: 9px 12px 0;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--app-surface-2) 72%, transparent);
}
.queue-main {
  display: grid;
  grid-template-columns: 74px minmax(150px, 1.4fr) minmax(180px, 1fr) minmax(160px, 1.1fr) auto;
  align-items: center;
  gap: 12px;
  min-width: 0;
}
.queue-status {
  min-width: 0;
}
.queue-title {
  display: grid;
  gap: 3px;
  min-width: 0;
}
.task-meta-line {
  color: var(--app-muted);
  font-size: 11px;
}
.queue-progress {
  display: grid;
  gap: 5px;
  min-width: 0;
}
.queue-progress-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  color: var(--app-muted);
  font-size: 12px;
}
.queue-progress-head strong {
  color: var(--app-text);
  font-size: 13px;
}
.queue-summary {
  display: grid;
  gap: 2px;
  min-width: 0;
  color: var(--app-muted);
  font-size: 12px;
}
.queue-summary > span:first-child {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.queue-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 4px;
  min-width: 120px;
  white-space: nowrap;
}
.task-error {
  color: var(--app-danger);
  font-size: 12px;
}
.queue-detail {
  margin-top: 4px;
  border-top: 1px solid var(--app-border-soft);
  border-bottom: 0;
}
.queue-detail :deep(.el-collapse-item__header) {
  height: 26px;
  background: transparent;
  color: var(--app-muted);
  border-bottom: 0;
  font-size: 12px;
}
.queue-detail :deep(.el-collapse-item__wrap) {
  background: transparent;
  border-bottom: 0;
}
.queue-detail :deep(.el-collapse-item__content) {
  padding: 0 0 10px;
}
.detail-title {
  font-weight: 650;
}
.detail-count {
  margin-left: 8px;
  color: var(--app-muted);
  font-size: 11px;
}
.detail-shell {
  display: grid;
  gap: 8px;
}
.metric-bar {
  display: grid;
  grid-template-columns: repeat(6, minmax(88px, 1fr));
  gap: 1px;
  overflow: hidden;
  border: 1px solid color-mix(in srgb, var(--app-primary) 24%, var(--app-border-soft));
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--app-primary) 5%, transparent);
}
.metric-bar > div {
  display: grid;
  gap: 2px;
  min-width: 0;
  padding: 7px 9px;
  border-right: 1px solid var(--app-border-soft);
}
.metric-bar > div:last-child {
  border-right: 0;
}
.metric-bar span,
.detail-note {
  color: var(--app-muted);
  font-size: 12px;
}
.metric-bar strong {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--app-text);
  font-size: 13px;
}
.detail-note {
  line-height: 1.5;
}
.detail-table {
  display: grid;
  overflow: hidden;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--radius-sm);
}
.detail-table-head,
.detail-table-row {
  display: grid;
  grid-template-columns: minmax(180px, 1.8fr) minmax(78px, 0.7fr) minmax(120px, 1fr) minmax(88px, 0.7fr) minmax(96px, 0.8fr);
  align-items: center;
  gap: 10px;
  min-width: 0;
  padding: 7px 9px;
}
.scan-table .detail-table-head,
.scan-table .detail-table-row {
  grid-template-columns: minmax(180px, 2fr) minmax(78px, 0.7fr) minmax(120px, 1fr);
}
.detail-table-head {
  color: var(--app-muted);
  font-size: 11px;
  font-weight: 700;
  background: color-mix(in srgb, var(--app-surface) 70%, transparent);
}
.detail-table-row {
  border-top: 1px solid var(--app-border-soft);
  color: var(--app-muted);
  font-size: 12px;
}
.detail-table-row > span {
  min-width: 0;
}
.file-name {
  color: var(--app-text);
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.mono-cell {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
}
.task-detail-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 6px;
}
.detail-entry {
  display: grid;
  gap: 2px;
  padding: 7px 9px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--app-surface-2) 72%, transparent);
}
.detail-label {
  color: var(--app-muted);
  font-size: 12px;
}
.detail-value {
  min-width: 0;
  overflow-wrap: anywhere;
  color: var(--app-text);
  font-size: 13px;
  font-weight: 600;
}
.row-error {
  grid-column: 1 / -1;
  color: var(--app-danger);
  overflow-wrap: anywhere;
}
@media (max-width: 1100px) {
  .queue-main {
    grid-template-columns: 70px minmax(160px, 1.2fr) minmax(180px, 1fr);
  }
  .queue-summary {
    grid-column: 2 / 4;
  }
  .queue-actions {
    grid-column: 1 / 4;
    justify-content: flex-start;
    min-width: 0;
    padding-top: 2px;
  }
  .metric-bar {
    grid-template-columns: repeat(3, minmax(100px, 1fr));
  }
}
@media (max-width: 760px) {
  .board-toolbar {
    align-items: stretch;
    flex-direction: column;
  }
  .queue-main {
    grid-template-columns: 1fr;
    gap: 7px;
  }
  .filter-group {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    width: 100%;
  }
  .filter-group :deep(.el-radio-button__inner) {
    width: 100%;
    padding-inline: 8px;
  }
  .queue-status,
  .queue-title,
  .queue-progress,
  .queue-summary,
  .queue-actions {
    grid-column: auto;
  }
  .queue-actions {
    flex-wrap: wrap;
  }
  .queue-summary > span:first-child,
  .file-name {
    white-space: normal;
    overflow-wrap: anywhere;
  }
  .metric-bar {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .detail-table {
    overflow-x: hidden;
  }
  .detail-table-head {
    display: none;
  }
  .detail-table-row,
  .scan-table .detail-table-row {
    grid-template-columns: 1fr;
    gap: 4px;
    min-width: 0;
  }
}
</style>
