<template>
  <div class="page page-stack">
    <div class="page-head">
      <div>
        <div class="page-kicker">Download</div>
        <h1 class="page-title"><el-icon><Download /></el-icon><span>文件下载</span></h1>
      </div>
    </div>

    <el-card class="panel" shadow="never">
      <div class="panel-head">
        <div>
          <div class="panel-title">扫描页面</div>
          <div class="panel-subtitle">Page ID</div>
        </div>
      </div>
      <el-form label-width="100px" class="responsive-form" @submit.prevent>
        <el-form-item label="Page ID">
          <PageIdInput v-model="pageId" @valid="(v) => (pageIdValid = v)" />
        </el-form-item>
        <el-form-item>
          <div class="action-row">
            <el-button type="primary" :loading="scanning" :disabled="!pageIdValid || scanning" @click="onScan">扫描页面文件</el-button>
            <el-button v-if="scanning" type="danger" plain @click="onCancelScan">取消扫描</el-button>
            <span class="status-chip" :class="pageIdValid ? 'ok' : 'warn'">{{ pageIdValid ? 'Page ID 有效' : '等待有效 Page ID' }}</span>
          </div>
        </el-form-item>
      </el-form>

      <div v-if="scanning || scanDone" class="status-grid">
        <div class="metric">
          <div class="metric-label">已发现</div>
          <div class="metric-value">{{ scanItems.length }}</div>
        </div>
        <div class="metric">
          <div class="metric-label">已探测</div>
          <div class="metric-value">{{ scanTask.state.progress.files_probed || 0 }} / {{ scanTask.state.progress.total_urls || 0 }}</div>
        </div>
        <div class="metric">
          <div class="metric-label">状态</div>
          <div class="metric-value">{{ scanning ? '扫描中' : '扫描完成' }}</div>
        </div>
      </div>
    </el-card>

    <el-card v-if="scanItems.length" class="panel" shadow="never">
      <div class="section-toolbar">
        <div>
          <div class="panel-title">文件列表</div>
          <div class="panel-subtitle">{{ scanItems.length }} 个文件 · 已选择 {{ selected.length }}</div>
        </div>
        <div class="action-row">
          <el-button size="small" @click="toggleAll">{{ allSelected ? '取消全选' : '全选' }}</el-button>
          <el-button type="primary" size="small" :disabled="!selected.length || downloading" :loading="startingDl" @click="onDownload">下载选中 ({{ selected.length }})</el-button>
        </div>
      </div>
      <el-table ref="tableRef" :data="scanItems" row-key="url" @selection-change="onSelection" max-height="420" size="small">
        <el-table-column type="selection" width="40" reserve-selection />
        <el-table-column label="文件名" prop="real_name" min-width="240" show-overflow-tooltip />
        <el-table-column label="类型" prop="block_type" width="100" />
        <el-table-column label="大小" width="110">
          <template #default="{ row }">{{ row.size_mb > 0 ? fmtSize(row.size_mb) : '探测中…' }}</template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card v-else-if="scanDone" class="panel" shadow="never">
      <el-empty description="未发现可下载文件" :image-size="80" />
    </el-card>

    <el-card v-if="dlTask.state.progress?.items?.length || dlTask.state.status === 'running'" class="panel" shadow="never">
      <div class="section-toolbar">
        <div>
          <div class="panel-title">下载进度</div>
          <div class="panel-subtitle">{{ dlTask.state.status }}</div>
        </div>
        <div class="action-row">
          <el-button v-if="dlTask.state.status === 'running'" type="danger" plain size="small" @click="onCancelDl">取消</el-button>
          <el-button v-if="dlTask.state.done" type="primary" size="small" :icon="Download" @click="dlZip">打包下载 ZIP</el-button>
          <el-button v-if="dlTask.state.done && dlTask.state.progress?.items?.length" type="primary" plain size="small" :icon="Refresh" @click="onRedownload">重新下载</el-button>
        </div>
      </div>
      <div class="task-list">
        <div v-for="(it, idx) in (dlTask.state.progress.items || [])" :key="it.url" class="task-row">
          <div class="task-head">
            <span class="t-name">{{ it.real_name }}</span>
            <div class="task-meta">
              <span class="t-status" :class="statusClass(it.status)">{{ statusText(it) }}</span>
              <el-button v-if="dlTask.state.done && it.status === 'completed'" link size="small" @click="dlFile(idx)">下载</el-button>
            </div>
          </div>
          <el-progress :percentage="Math.min(100, it.progress||0)" :status="progressStatus(it.status)" :stroke-width="8" />
          <div class="muted">{{ fmtSize(it.downloaded_mb) }} / {{ fmtSize(it.total_mb) }} · {{ fmtSize(it.speed_mb_s) }}/s · 剩余 {{ fmtEta(it.ETA) }}</div>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
defineOptions({ name: 'Download' })

import { ref, computed, onUnmounted, onActivated, onDeactivated } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Download, Refresh } from '@element-plus/icons-vue'
import { api, errMsg } from '@/api/client'
import { useTask } from '@/composables/useTask'
import { useTasksStore } from '@/stores/tasks'
import { fmtSize, fmtEta } from '@/utils/format'
import PageIdInput from '@/components/PageIdInput.vue'
import type { ElTable } from 'element-plus'

const pageId = ref('')
const router = useRouter()
const tasks = useTasksStore()
const pageIdValid = ref(false)
const scanning = ref(false)
const scanDone = ref(false)
const scanItems = ref<any[]>([])
const selected = ref<any[]>([])
const scanTaskId = ref<string | null>(null)
const scanTask = useTask()
let listTimer: any = null

const startingDl = ref(false)
const downloading = ref(false)
const dlTaskId = ref<string | null>(null)
const dlTask = useTask()
const tableRef = ref<any>()

const allSelected = computed(() => scanItems.value.length > 0 && selected.value.length === scanItems.value.length)

async function onScan() {
  if (scanning.value) return
  scanItems.value = []
  selected.value = []
  scanDone.value = false
  scanning.value = true
  try {
    const r = await api.post('/api/scan', { page_id: pageId.value, probe_workers: 8 })
    scanTaskId.value = r.data.task_id
    tasks.track(r.data.task_id)
    scanTask.start(r.data.task_id, (p) => {
      if (p.done) { scanning.value = false; scanDone.value = true; stopListPoll(); refreshList() }
    })
    startListPoll()
  } catch (e) {
    scanning.value = false
    ElMessage.error(errMsg(e))
  }
}

function startListPoll() {
  stopListPoll()
  listTimer = setInterval(refreshList, 800)
}
function stopListPoll() { if (listTimer) { clearInterval(listTimer); listTimer = null } }
onUnmounted(stopListPoll)

onDeactivated(() => {
  // 切走时关 SSE + 列表轮询，避免后台空跑
  scanTask.stop()
  dlTask.stop()
  stopListPoll()
})

onActivated(() => {
  // 切回来时，如果任务还在跑，重新订阅 SSE + 恢复列表轮询
  // reconnect 不重置 state，所以已有进度不会闪
  if (scanTaskId.value && !scanTask.state.done) {
    scanTask.reconnect(scanTaskId.value, (p) => {
      if (p.done) { scanning.value = false; scanDone.value = true; stopListPoll(); refreshList() }
    })
    startListPoll()
  }
  if (dlTaskId.value && !dlTask.state.done) {
    dlTask.reconnect(dlTaskId.value, onDlProgress)
  }
})

async function refreshList() {
  if (!scanTaskId.value) return
  try {
    const r = await api.get(`/api/scan/${scanTaskId.value}/list`)
    scanItems.value = r.data.items || []
  } catch {}
}

async function onCancelScan() {
  if (scanTaskId.value) await scanTask.cancel(scanTaskId.value)
  stopListPoll()
  scanning.value = false
}

function onSelection(rows: any[]) { selected.value = rows }
function toggleAll() { tableRef.value?.toggleAllSelection() }

async function onDownload() {
  if (startingDl.value || downloading.value) return
  startingDl.value = true
  downloading.value = true
  try {
    const items = selected.value.map(it => ({
      url: it.url, real_name: it.real_name, name: it.name,
      size_mb: it.size_mb, block_id: it.block_id,
    }))
    const r = await api.post('/api/download/start', { items })
    dlTaskId.value = r.data.task_id
    dlTask.start(r.data.task_id, onDlProgress)
    await tasks.load()
    tasks.track(r.data.task_id)
    await promptOpenTaskBoard()
  } catch (e) {
    ElMessage.error(errMsg(e))
    downloading.value = false
  } finally {
    startingDl.value = false
  }
}

function onDlProgress(p: any) {
  if (!p.done) return
  downloading.value = false
  if (allCompleted(dlTask.state.progress?.items)) {
    promptRedownload()
  }
}

async function promptRedownload() {
  try {
    await ElMessageBox.confirm(
      '全部文件已下载完成。是否再下载一次（将清空当前表单）？',
      '下载成功',
      { type: 'success', confirmButtonText: '再下载一次', cancelButtonText: '留在此页' }
    )
    clearForm()
  } catch (e: any) {
    if (e !== 'cancel') ElMessage.error(errMsg(e))
  }
}

function allCompleted(items?: any[]): boolean {
  if (!items || !items.length) return false
  return items.every(it => it.status === 'completed' && !it.error)
}

function clearForm() {
  dlTask.stop()
  scanTask.stop()
  stopListPoll()
  pageId.value = ''
  pageIdValid.value = false
  scanItems.value = []
  selected.value = []
  scanning.value = false
  scanDone.value = false
  scanTaskId.value = null
  downloading.value = false
  startingDl.value = false
  dlTaskId.value = null
  tableRef.value?.clearSelection()
}

async function onRedownload() {
  if (downloading.value) return
  const items = (dlTask.state.progress?.items || []).map((it: any) => ({
    url: it.url,
    real_name: it.real_name,
    name: it.name,
    size_mb: it.total_mb,
    block_id: it.block_id,
  }))
  if (!items.length) return
  startingDl.value = true
  downloading.value = true
  try {
    const r = await api.post('/api/download/start', { items })
    dlTaskId.value = r.data.task_id
    dlTask.start(r.data.task_id, onDlProgress)
    await tasks.load()
    tasks.track(r.data.task_id)
    await promptOpenTaskBoard()
  } catch (e) {
    ElMessage.error(errMsg(e))
    downloading.value = false
  } finally {
    startingDl.value = false
  }
}

async function onCancelDl() {
  if (dlTaskId.value) await dlTask.cancel(dlTaskId.value)
  downloading.value = false
}

function dlFile(idx: number) {
  if (dlTaskId.value) window.open(`/api/download/${dlTaskId.value}/file/${idx}`, '_blank')
}
function dlZip() {
  if (dlTaskId.value) window.open(`/api/download/${dlTaskId.value}/zip`, '_blank')
}

async function promptOpenTaskBoard() {
  try {
    await ElMessageBox.confirm(
      '已创建任务，是否前往任务看板查看？',
      '任务已创建',
      { type: 'success', confirmButtonText: '前往任务看板', cancelButtonText: '留在当前页' },
    )
    router.push('/tasks')
  } catch (e: any) {
    if (e !== 'cancel') ElMessage.error(errMsg(e))
  }
}

function statusText(it: any) {
  if (it.error) return '错误'
  return ({ waiting: '等待中', downloading: '下载中', refreshing: '刷新链接', completed: '已完成', error: '错误' } as any)[it.status] || it.status
}
function statusClass(s: string) { return ({ completed: 'ok', error: 'err', waiting: 'wait' } as any)[s] || '' }
function progressStatus(s: string) {
  if (s === 'completed') return 'success'
  if (s === 'error') return 'exception'
  return undefined
}
</script>
