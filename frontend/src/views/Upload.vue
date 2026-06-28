<template>
  <div class="page page-stack">
    <div class="page-head">
      <div>
        <div class="page-kicker">Upload</div>
        <h1 class="page-title"><el-icon><Upload /></el-icon><span>文件上传</span></h1>
      </div>
    </div>

    <el-card class="panel" shadow="never">
      <div class="panel-head">
        <div>
          <div class="panel-title">上传任务</div>
          <div class="panel-subtitle">目标 Page ID</div>
        </div>
        <span class="status-chip" :class="selectedFiles.length ? 'ok' : 'warn'">{{ selectedFiles.length }} 个文件</span>
      </div>
      <el-form label-width="100px" class="responsive-form">
        <el-form-item label="选择文件">
          <el-upload
            action="#"
            :auto-upload="false"
            :multiple="true"
            :on-change="onFileChange"
            :on-remove="onFileRemove"
            :file-list="fileList"
            :show-file-list="true"
          >
            <div class="action-row">
              <el-button :icon="DocumentAdd">选择文件</el-button>
              <el-button :icon="FolderOpened" @click.stop="pickFolder">选择文件夹</el-button>
            </div>
            <input ref="folderInput" class="hidden-file-input" type="file" webkitdirectory directory multiple @change="onFolderChange" />
            <template #tip><div class="muted">{{ selectedFiles.length ? `${selectedFiles.length} 个文件待上传` : '未选择文件' }}</div></template>
          </el-upload>
        </el-form-item>
        <el-form-item label="Page ID">
          <PageIdInput v-model="pageId" @valid="(v) => (pageIdValid = v)" />
        </el-form-item>
        <el-form-item>
          <div class="action-row">
            <el-button type="primary" :loading="stage === 'cache'" :disabled="!canStart" @click="onStart">开始上传</el-button>
            <span class="status-chip" :class="pageIdValid ? 'ok' : 'warn'">{{ pageIdValid ? 'Page ID 有效' : '等待有效 Page ID' }}</span>
          </div>
          <div class="muted">文件会先上传到服务器缓存区,再由后台分片上传至 Notion 云端。</div>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card v-if="stage !== 'idle'" class="panel upload-progress" shadow="never">
      <div class="panel-head">
        <div>
          <div class="panel-title">上传进度</div>
          <div class="panel-subtitle">{{ phaseLabel }}</div>
        </div>
        <div class="action-row">
          <span class="status-chip" :class="overallChip.cls">{{ overallChip.text }}</span>
          <el-button v-if="canCancel" type="danger" plain size="small" @click="onCancel">取消</el-button>
        </div>
      </div>

      <el-steps class="upload-steps" align-center finish-status="success">
        <el-step title="上传到缓存区" :status="cacheStepStatus" :description="cacheStepDesc" />
        <el-step title="上传到云端 Notion" :status="cloudStepStatus" :description="cloudStepDesc" />
      </el-steps>
      <div class="muted cache-note">文件先暂存到本服务器缓存区,再由后台分片上传至 Notion。</div>

      <!-- 阶段 1:上传到服务器缓存区 -->
      <div v-if="stage === 'cache'" class="task-list">
        <div class="task-row">
          <div class="task-head">
            <span class="t-name">正在上传到服务器缓存区</span>
            <span class="t-status" :class="cacheRowStatus">{{ cacheRowText }}</span>
          </div>
          <el-progress :percentage="cachePct" :status="cacheProgressStatus" :stroke-width="8" />
          <div class="muted">已缓存 {{ fmtSize(cache.loadedMb) }} / {{ fmtSize(cache.totalMb) }} · {{ fmtSize(cache.speedMb) }}/s · 剩余 {{ fmtEta(cache.eta) }}</div>
        </div>
      </div>

      <!-- 阶段 2:上传到 Notion 云端 -->
      <div v-else-if="stage === 'cloud'" class="task-list">
        <div v-if="!(task.state.progress?.items?.length) && task.state.status === 'running'" class="muted">等待云端上传开始…</div>
        <div v-for="it in (task.state.progress.items || [])" :key="it.file_path" class="task-row">
          <div class="task-head">
            <span class="t-name">{{ basename(it.file_path) }}</span>
            <span class="t-status" :class="statusClass(it.status)">{{ statusText(it) }}</span>
          </div>
          <el-progress :percentage="Math.min(100, it.progress||0)" :status="progressStatus(it.status)" :stroke-width="8" />
          <div class="muted">{{ fmtSize(it.uploaded_mb) }} / {{ fmtSize(it.total_mb) }} · {{ fmtSize(it.speed_mb_s) }}/s · 剩余 {{ fmtEta(it.ETA) }}</div>
        </div>
      </div>

      <div v-if="finished" class="reset-row">
        <el-button type="primary" plain :icon="RefreshRight" @click="onReset">再上传一次</el-button>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, watch } from 'vue'
import { useRouter } from 'vue-router'
import axios from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Upload, DocumentAdd, FolderOpened, RefreshRight } from '@element-plus/icons-vue'
import type { UploadFile } from 'element-plus'
import { api, errMsg } from '@/api/client'
import { useTask } from '@/composables/useTask'
import { useTasksStore } from '@/stores/tasks'
import PageIdInput from '@/components/PageIdInput.vue'
import { fmtSize, fmtEta } from '@/utils/format'

type StepStatus = 'wait' | 'process' | 'finish' | 'success' | 'error'

const pageId = ref('')
const router = useRouter()
const tasks = useTasksStore()
const pageIdValid = ref(false)
const selectedFiles = ref<File[]>([])
const fileList = ref<UploadFile[]>([])
const folderInput = ref<HTMLInputElement | null>(null)
const currentTaskId = ref<string | null>(null)
const task = useTask()

// 上传阶段: idle(未开始) → cache(阶段1:浏览器→服务器缓存区) → cloud(阶段2:服务器→Notion 云端)
const stage = ref<'idle' | 'cache' | 'cloud'>('idle')
const finished = ref(false)              // 已到达终态(完成/出错/取消)
const cancelled = ref(false)             // 被取消
const runError = ref<string | null>(null) // 非取消错误(缓存/ /start /云端统一)
const cache = reactive({ loadedMb: 0, totalMb: 0, percent: 0, speedMb: 0, eta: 0 })
let abortCtrl: AbortController | null = null
// 手动 EMA 速度(模块私有,非响应式)
let lastTick = 0, lastLoaded = 0, emaRate = 0

const precomputedTotalBytes = computed(() => selectedFiles.value.reduce((s, f) => s + (f.size || 0), 0))

const canStart = computed(() => pageIdValid.value && selectedFiles.value.length > 0 && (stage.value === 'idle' || finished.value))
const canCancel = computed(() => stage.value === 'cache' || (stage.value === 'cloud' && task.state.status === 'running'))

// el-steps 每步状态
const cacheStepStatus = computed<StepStatus>(() => {
  if (stage.value === 'idle') return 'wait'
  if (stage.value === 'cache') return finished.value ? (cancelled.value || !!runError.value ? 'error' : 'success') : 'process'
  return 'finish' // stage === 'cloud':缓存阶段已成功
})
const cloudStepStatus = computed<StepStatus>(() => {
  if (stage.value !== 'cloud') return 'wait'
  if (!finished.value) return 'process'
  return task.state.status === 'done' ? 'success' : 'error'
})
const cacheStepDesc = computed(() => {
  if (stage.value === 'idle') return '等待中'
  if (stage.value === 'cache') {
    if (finished.value) return cancelled.value ? '已取消' : (runError.value ? '出错' : '已完成')
    return cache.percent >= 100 ? '服务器处理中…' : '上传中'
  }
  return '已完成'
})
const cloudStepDesc = computed(() => {
  if (stage.value !== 'cloud') return '等待中'
  if (!finished.value) return '进行中'
  if (cancelled.value) return '已取消'
  if (task.state.status === 'done') return '已完成'
  return '出错'
})

// 缓存阶段进度行
const cacheRowStatus = computed(() => finished.value ? (cancelled.value || runError.value ? 'err' : 'ok') : 'wait')
const cacheRowText = computed(() => finished.value ? (cancelled.value ? '已取消' : runError.value ? '出错' : '已完成') : '上传中')
const cachePct = computed(() => Math.min(100, Math.max(0, Math.round(cache.percent))))
const cacheProgressStatus = computed<'success' | 'exception' | undefined>(() =>
  finished.value ? (cancelled.value || !!runError.value ? 'exception' : 'success') : undefined)

const overallChip = computed(() => {
  if (cancelled.value) return { text: '已取消', cls: 'warn' }
  if (runError.value || task.state.status === 'error') return { text: '出错', cls: 'err' }
  if (stage.value === 'cache' && !finished.value) return { text: '上传缓存区中', cls: 'info' }
  if (stage.value === 'cloud' && !finished.value) return { text: '上传云端中', cls: 'info' }
  if (finished.value) return { text: '已完成', cls: 'ok' }
  return { text: '准备中', cls: 'warn' }
})
const phaseLabel = computed(() => {
  if (stage.value === 'cache') return '阶段 1 / 2 · 上传到服务器缓存区'
  if (stage.value === 'cloud') return '阶段 2 / 2 · 上传到 Notion 云端'
  return ''
})

// 云端阶段终态:监听 SSE 任务状态
watch(() => task.state.status, (s) => {
  if (stage.value === 'cloud' && (s === 'done' || s === 'error' || s === 'cancelled')) {
    finished.value = true
    cancelled.value = s === 'cancelled'
    if (s === 'error') runError.value = task.state.error || '任务出错'
  }
})

function onFileChange(_file: UploadFile, files: UploadFile[]) {
  fileList.value = files
  selectedFiles.value = files.map(f => f.raw as File)
}
function onFileRemove(_file: UploadFile, files: UploadFile[]) {
  fileList.value = files
  selectedFiles.value = files.map(f => f.raw as File)
}

function pickFolder() { folderInput.value?.click() }
function onFolderChange(e: Event) {
  const input = e.target as HTMLInputElement
  const files = Array.from(input.files || [])
  selectedFiles.value = files
  fileList.value = files.map(f => ({ name: (f as any).webkitRelativePath || f.name, raw: f } as UploadFile))
}

async function onStart() {
  if (!canStart.value) return
  // 重置状态
  finished.value = false
  cancelled.value = false
  runError.value = null
  cache.loadedMb = 0
  cache.totalMb = precomputedTotalBytes.value / 1048576
  cache.percent = 0
  cache.speedMb = 0
  cache.eta = 0
  lastTick = 0
  lastLoaded = 0
  emaRate = 0
  abortCtrl = new AbortController()
  stage.value = 'cache'

  try {
    const fd = new FormData()
    const rels: string[] = []
    selectedFiles.value.forEach(f => {
      const rel = (f as any).webkitRelativePath || f.name
      rels.push(rel)
      fd.append('files', f, f.name)
    })
    rels.forEach(r => fd.append('rels', r))

    // 阶段 1:上传到服务器缓存区(用 axios onUploadProgress 追踪进度)
    const up = await api.post('/api/upload/files', fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
      signal: abortCtrl.signal,
      onUploadProgress: (e) => {
        const loaded = e.loaded || 0
        // e.total 含 multipart 开销,与 loaded 配对使用;缺失时才用预计算兜底
        const total = (e.lengthComputable && e.total && e.total > 0) ? e.total : precomputedTotalBytes.value
        cache.loadedMb = loaded / 1048576
        cache.totalMb = total / 1048576
        cache.percent = total > 0 ? Math.min(100, (loaded / total) * 100) : 0
        // EMA 速度,≥250ms 采样一次
        const now = Date.now()
        if (!lastTick) {
          lastTick = now
          lastLoaded = loaded
        } else if (now - lastTick >= 250 && loaded > lastLoaded) {
          const dt = (now - lastTick) / 1000
          const inst = (loaded - lastLoaded) / dt // bytes/s
          emaRate = emaRate > 0 ? emaRate * 0.5 + inst * 0.5 : inst
          lastTick = now
          lastLoaded = loaded
        }
        cache.speedMb = emaRate / 1048576
        cache.eta = emaRate > 0 && total > loaded ? (total - loaded) / emaRate : 0
      },
    })

    // 阶段 2:启动云端上传(先切 stage 再 task.start,保证 watcher 看到 cloud)
    stage.value = 'cloud'
    const sessionId = up.data.session_id
    const folderMode = selectedFiles.value.some(f => !!(f as any).webkitRelativePath)
    const r = await api.post('/api/upload/start', { page_id: pageId.value, session_id: sessionId, folder_mode: folderMode })
    currentTaskId.value = r.data.task_id
    task.start(r.data.task_id)
    await tasks.load()
    tasks.track(r.data.task_id)
    await promptOpenTaskBoard()
  } catch (e) {
    if (axios.isCancel(e)) {
      cancelled.value = true
      ElMessage.info('已取消上传')
    } else {
      runError.value = errMsg(e)
      ElMessage.error(errMsg(e))
    }
    finished.value = true
    // stage 保持原值(cache 或 cloud),在步骤条上显示错误/取消态
  } finally {
    abortCtrl = null
  }
}

async function onCancel() {
  if (stage.value === 'cache' && abortCtrl) {
    abortCtrl.abort() // → 走 onStart 的 isCancel 分支
  } else if (stage.value === 'cloud' && currentTaskId.value) {
    await task.cancel(currentTaskId.value) // → 靠 SSE done + watcher 翻终态
  }
}

function onReset() {
  // 重置为干净的初始状态:关闭 SSE、清空文件选择与进度,回到"选择文件"
  task.stop()
  currentTaskId.value = null
  stage.value = 'idle'
  finished.value = false
  cancelled.value = false
  runError.value = null
  cache.loadedMb = 0
  cache.totalMb = 0
  cache.percent = 0
  cache.speedMb = 0
  cache.eta = 0
  selectedFiles.value = []
  fileList.value = []
  lastTick = 0
  lastLoaded = 0
  emaRate = 0
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

function basename(p: string) { return (p || '').split(/[\\/]/).pop() }
function statusText(it: any) {
  if (it.error) return '错误'
  return ({ waiting: '等待中', uploading: '上传中', completed: '已完成', error: '错误' } as any)[it.status] || it.status
}
function statusClass(s: string) {
  return ({ completed: 'ok', error: 'err', waiting: 'wait' } as any)[s] || ''
}
function progressStatus(s: string) {
  if (s === 'completed') return 'success'
  if (s === 'error') return 'exception'
  return undefined
}
</script>

<style scoped>
.hidden-file-input {
  display: none;
}
.upload-progress {
  --el-color-success: var(--app-success);
  --el-color-error: var(--app-danger);
}
.upload-steps {
  margin: var(--space-3) 0 var(--space-2);
}
.cache-note {
  margin: var(--space-2) 0 var(--space-3);
}
.reset-row {
  margin-top: var(--space-3);
  display: flex;
  justify-content: center;
}
</style>
