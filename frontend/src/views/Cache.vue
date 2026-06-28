<template>
  <div class="page page-stack">
    <div class="page-head">
      <div>
        <div class="page-kicker">Cache</div>
        <h1 class="page-title"><el-icon><FolderOpened /></el-icon><span>云端缓存</span></h1>
        <p class="page-desc">管理上传缓存、下载产物和临时打包文件。</p>
      </div>
      <div class="action-row">
        <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
        <el-button :icon="Timer" @click="cleanup">按策略清理</el-button>
      </div>
    </div>

    <div class="status-grid">
      <div class="metric">
        <div class="metric-label">缓存项</div>
        <div class="metric-value">{{ items.length }}</div>
      </div>
      <div class="metric">
        <div class="metric-label">总大小</div>
        <div class="metric-value">{{ fmtSize(totalSize / 1048576) }}</div>
      </div>
      <div class="metric">
        <div class="metric-label">自动清理</div>
        <div class="metric-value">{{ policy.auto_cleanup_enabled ? '开启' : '关闭' }}</div>
      </div>
    </div>

    <el-card class="panel" shadow="never">
      <div class="section-toolbar">
        <div>
          <div class="panel-title">缓存列表</div>
          <div class="panel-subtitle">TTL {{ fmtDuration(policy.ttl_seconds) }} · 间隔 {{ fmtDuration(policy.cleanup_interval_seconds) }}</div>
        </div>
        <el-radio-group v-model="filter" size="small">
          <el-radio-button value="all">全部</el-radio-button>
          <el-radio-button value="upload">上传</el-radio-button>
          <el-radio-button value="download">下载</el-radio-button>
          <el-radio-button value="generated">生成</el-radio-button>
          <el-radio-button value="unknown">其它</el-radio-button>
        </el-radio-group>
      </div>

      <el-empty v-if="!loading && !filtered.length" description="暂无缓存" :image-size="80" />
      <el-table v-else :data="filtered" row-key="id" size="small">
        <el-table-column label="名称" min-width="240">
          <template #default="{ row }">
            <div class="cache-name">
              <div class="cache-title">
                <span>{{ row.name }}</span>
                <span v-if="row.busy" class="status-chip info">使用中</span>
              </div>
              <div v-if="row.storage_name && row.storage_name !== row.name" class="cache-id">{{ row.storage_name }}</div>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="类型" width="100">
          <template #default="{ row }">{{ kindText(row.kind) }}</template>
        </el-table-column>
        <el-table-column label="文件" width="90" prop="files" />
        <el-table-column label="大小" width="120">
          <template #default="{ row }">{{ fmtSize(row.size / 1048576) }}</template>
        </el-table-column>
        <el-table-column label="更新时间" min-width="170">
          <template #default="{ row }">{{ fmtTime(row.updated_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="170" fixed="right">
          <template #default="{ row }">
            <div class="table-actions">
              <el-button link :icon="Download" @click="download(row)">下载</el-button>
              <el-button link type="danger" :icon="Delete" :disabled="row.busy" @click="remove(row)">删除</el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, Download, FolderOpened, Refresh, Timer } from '@element-plus/icons-vue'
import { api, errMsg } from '@/api/client'
import { fmtSize, fmtEta } from '@/utils/format'

interface CacheItem {
  id: string
  name: string
  storage_name?: string
  kind: string
  is_dir: boolean
  size: number
  files: number
  updated_at: number
  busy: boolean
}

const items = ref<CacheItem[]>([])
const loading = ref(false)
const filter = ref('all')
const policy = reactive({
  ttl_seconds: 3600,
  auto_cleanup_enabled: true,
  cleanup_interval_seconds: 900,
})

const totalSize = computed(() => items.value.reduce((sum, it) => sum + (Number(it.size) || 0), 0))
const filtered = computed(() => filter.value === 'all' ? items.value : items.value.filter(it => it.kind === filter.value))

onMounted(load)

async function load() {
  loading.value = true
  try {
    const r = await api.get('/api/cache/items')
    items.value = r.data.items || []
    policy.ttl_seconds = r.data.ttl_seconds || 3600
    policy.auto_cleanup_enabled = !!r.data.auto_cleanup_enabled
    policy.cleanup_interval_seconds = r.data.cleanup_interval_seconds || 900
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    loading.value = false
  }
}

function download(row: CacheItem) {
  window.open(`/api/cache/items/${encodeURIComponent(row.id)}/download`, '_blank')
}

async function remove(row: CacheItem) {
  try {
    await ElMessageBox.confirm(`确定删除缓存「${row.name}」？`, '删除缓存', { type: 'warning' })
    await api.delete(`/api/cache/items/${encodeURIComponent(row.id)}`)
    ElMessage.success('缓存已删除')
    await load()
  } catch (e: any) {
    if (e !== 'cancel') ElMessage.error(errMsg(e))
  }
}

async function cleanup() {
  try {
    const r = await api.post('/api/cache/cleanup')
    ElMessage.success(`已清理 ${r.data.deleted} 项缓存`)
    await load()
  } catch (e) {
    ElMessage.error(errMsg(e))
  }
}

function kindText(kind: string) {
  return ({ upload: '上传', download: '下载', generated: '生成', unknown: '其它' } as any)[kind] || kind
}

function fmtTime(ts?: number) {
  if (!ts) return '-'
  return new Date(ts * 1000).toLocaleString()
}

function fmtDuration(s?: number) {
  return fmtEta(s || 0)
}
</script>

<style scoped>
.cache-name {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  min-width: 0;
}
.cache-title {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  min-width: 0;
}
.cache-title > span:first-child {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.cache-id {
  max-width: 100%;
  overflow: hidden;
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.2;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.table-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}
</style>
