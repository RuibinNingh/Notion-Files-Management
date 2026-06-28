<template>
  <el-dialog
    :model-value="modelValue"
    @update:model-value="emit('update:modelValue', $event)"
    title="日志查看"
    width="88%"
    top="5vh"
    class="logs-dialog"
  >
    <div class="logs-body">
      <!-- 左:文件列表(多选) -->
      <div class="logs-left">
        <div class="logs-toolbar">
          <span class="muted">{{ logs.length }} 个文件 · 已选 {{ selected.length }}</span>
          <el-button size="small" :icon="Refresh" :loading="loadingList" @click="loadLogs">刷新</el-button>
        </div>
        <el-table
          :data="logs"
          height="58vh"
          size="small"
          highlight-current-row
          @selection-change="onSelectionChange"
          @row-click="onRowClick"
        >
          <el-table-column type="selection" width="40" />
          <el-table-column prop="name" label="文件名" min-width="200" show-overflow-tooltip />
          <el-table-column label="大小" width="84" align="right">
            <template #default="{ row }">{{ fmtSize((row.size || 0) / 1048576) }}</template>
          </el-table-column>
        </el-table>
        <div class="logs-actions">
          <el-button
            size="small"
            type="primary"
            plain
            :disabled="!selected.length"
            :loading="downloading"
            @click="onDownloadSelected"
          >
            下载选中<span v-if="selected.length > 1">(打包 zip)</span>
          </el-button>
        </div>
      </div>

      <!-- 右:选中文件内容 -->
      <div class="logs-right">
        <div v-if="!current" class="logs-empty muted">点击左侧文件查看内容</div>
        <template v-else>
          <div class="logs-content-head">
            <span class="logs-name" :title="current.name">{{ current.name }}</span>
            <el-button size="small" :icon="Download" :loading="downloading" @click="downloadOne(current.name)">下载</el-button>
          </div>
          <div v-if="contentLoading" class="muted logs-loading">加载中…</div>
          <div v-else class="logs-content">
            <div v-if="truncated" class="logs-trunc muted">⚠ 文件较大,仅显示尾部 {{ maxLines }} 行,完整内容请下载</div>
            <pre>{{ content || '(空)' }}</pre>
          </div>
        </template>
      </div>
    </div>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh, Download } from '@element-plus/icons-vue'
import { api, errMsg } from '@/api/client'
import { fmtSize } from '@/utils/format'

const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [boolean] }>()

const logs = ref<any[]>([])
const selected = ref<any[]>([])
const current = ref<any>(null)
const content = ref('')
const truncated = ref(false)
const loadingList = ref(false)
const contentLoading = ref(false)
const downloading = ref(false)
const maxLines = 2000

// 打开弹窗时拉列表
watch(() => props.modelValue, (v) => {
  if (v) loadLogs()
})

async function loadLogs() {
  loadingList.value = true
  try {
    const r = await api.get('/api/logs')
    logs.value = r.data.logs || []
    // list_logs 是 sorted 升序,最后一个是最新;默认展示它
    if (logs.value.length) {
      const latest = logs.value[logs.value.length - 1]
      if (!current.value || !logs.value.find(l => l.name === current.value.name)) {
        onRowClick(latest)
      }
    } else {
      current.value = null
      content.value = ''
    }
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    loadingList.value = false
  }
}

function onSelectionChange(rows: any[]) {
  selected.value = rows
}

async function onRowClick(row: any) {
  current.value = row
  contentLoading.value = true
  try {
    const r = await api.get(`/api/logs/${encodeURIComponent(row.name)}`, { params: { max_lines: maxLines } })
    content.value = r.data.content || ''
    truncated.value = !!r.data.truncated
  } catch (e) {
    ElMessage.error(errMsg(e))
    content.value = ''
  } finally {
    contentLoading.value = false
  }
}

async function downloadOne(name: string) {
  downloading.value = true
  try {
    const r = await api.get(`/api/logs/${encodeURIComponent(name)}/download`, { responseType: 'blob' })
    saveBlob(r, name)
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    downloading.value = false
  }
}

async function onDownloadSelected() {
  if (!selected.value.length) return
  downloading.value = true
  try {
    if (selected.value.length === 1) {
      const name = selected.value[0].name
      const r = await api.get(`/api/logs/${encodeURIComponent(name)}/download`, { responseType: 'blob' })
      saveBlob(r, name)
    } else {
      const r = await api.post(
        '/api/logs/download',
        { names: selected.value.map(s => s.name) },
        { responseType: 'blob' },
      )
      saveBlob(r, 'nfm-logs.zip')
    }
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    downloading.value = false
  }
}

/** blob 下载:错误响应(404/401 等)也是 blob,需解析后提示 */
function saveBlob(r: any, filename: string) {
  const data = r.data
  if (data instanceof Blob && data.type && data.type.includes('json')) {
    data.text().then((t: string) => {
      try { ElMessage.error(JSON.parse(t).detail || '下载失败') }
      catch { ElMessage.error('下载失败') }
    })
    return
  }
  const url = URL.createObjectURL(data)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}
</script>

<style scoped>
.logs-body {
  display: flex;
  gap: var(--space-3);
  min-height: 60vh;
}
.logs-left {
  width: 320px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.logs-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.logs-actions {
  display: flex;
  justify-content: flex-end;
}
.logs-right {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.logs-empty,
.logs-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  flex: 1;
}
.logs-content-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
}
.logs-name {
  font-weight: 650;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.logs-content {
  flex: 1;
  overflow: auto;
  background: var(--app-surface-2);
  border: 1px solid var(--app-border-soft);
  border-radius: var(--radius-md);
  padding: var(--space-2);
}
.logs-content pre {
  margin: 0;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: var(--font-size-xs);
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-all;
}
.logs-trunc {
  margin-bottom: var(--space-2);
}
</style>
