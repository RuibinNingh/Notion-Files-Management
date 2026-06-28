<template>
  <div class="page page-stack">
    <div class="page-head">
      <div>
        <div class="page-kicker">Tools</div>
        <h1 class="page-title"><el-icon><Tools /></el-icon><span>工具箱</span></h1>
      </div>
    </div>

    <el-card class="panel tools-panel" shadow="never">
      <el-tabs v-model="active" class="tool-tabs">
        <el-tab-pane label="页面大小查询" name="query">
          <div class="inline-form">
            <PageIdInput v-model="q.pageId" class="wide-input" @valid="(v) => (q.valid = v)" />
            <el-button type="primary" :loading="q.scanning" :disabled="!q.valid || q.scanning" @click="q.scan">查询</el-button>
            <el-button v-if="q.scanning" type="danger" plain @click="q.cancel">取消</el-button>
          </div>
          <div v-if="q.scanning" class="status-chip info tool-status">已发现 {{ q.items.length }} · 已探测 {{ q.task.state.progress.files_probed || 0 }}/{{ q.task.state.progress.total_urls || 0 }}</div>
          <el-table v-if="q.items.length" :data="q.items" size="small" max-height="420" class="result-table">
            <el-table-column label="文件名" prop="real_name" min-width="240" show-overflow-tooltip />
            <el-table-column label="类型" prop="block_type" width="100" />
            <el-table-column label="大小" width="110">
              <template #default="{ row }">{{ row.size_mb > 0 ? fmtSize(row.size_mb) : '探测中…' }}</template>
            </el-table-column>
          </el-table>
          <div v-if="q.items.length" class="muted result-summary">总大小：{{ fmtSize(q.items.reduce((s:number,x:any)=>s+(x.size_mb||0),0)) }}</div>
        </el-tab-pane>

      <!-- 页面大小自动更新 -->
      <el-tab-pane label="页面大小自动更新" name="pagesize">
        <el-form label-width="120px" class="responsive-form">
          <el-form-item label="数据源 ID"><PageIdInput v-model="ps.dsId" @valid="(v) => (ps.valid = v)" /></el-form-item>
          <el-form-item label="大小属性">
            <el-select v-model="ps.sizeProp" placeholder="选择 number 属性" class="prop-select">
              <el-option v-for="p in ps.numberProps" :key="p.name" :label="`${p.name} [${p.type}]`" :value="p.name" />
            </el-select>
            <div class="action-row tool-inline-actions">
              <el-button :loading="ps.fetchingProps" :disabled="!ps.valid || ps.fetchingProps" @click="ps.fetchProps">获取属性</el-button>
              <el-button :loading="ps.scanningPages" :disabled="!ps.valid || !ps.sizeProp || ps.scanningPages" @click="ps.scanPages">扫描页面</el-button>
            </div>
          </el-form-item>
          <el-form-item v-if="ps.pages.length">
            <el-button type="primary" :loading="ps.starting" :disabled="!ps.selected.length || ps.starting" @click="ps.start">更新选中 ({{ ps.selected.length }})</el-button>
          </el-form-item>
        </el-form>
        <el-table v-if="ps.pages.length" :data="ps.pages" size="small" max-height="360" @selection-change="ps.onSel">
          <el-table-column type="selection" width="40" />
          <el-table-column label="页面标题" prop="title" min-width="240" show-overflow-tooltip />
          <el-table-column label="当前大小" width="120">
            <template #default="{ row }">{{ row.size_value != null ? fmtSize(row.size_value*1024) : '未设置' }}</template>
          </el-table-column>
        </el-table>
        <div v-if="ps.task.state.progress?.status" class="prog-box">
          <el-progress :percentage="ps.task.state.progress.percent||0" :status="ps.task.state.done ? 'success' : undefined" />
          <div class="muted">总计 {{ ps.task.state.progress.total }} · 链接已查询 {{ ps.task.state.progress.link_queried }} · 已更新 {{ ps.task.state.progress.size_updated }} · 失败 {{ ps.task.state.progress.failed }}</div>
        </div>
      </el-tab-pane>

      <!-- 数据源迁移 -->
      <el-tab-pane label="数据源迁移" name="migrate">
        <el-form label-width="120px" class="responsive-form">
          <el-form-item label="源数据源 ID"><PageIdInput v-model="mg.srcId" @valid="(v) => (mg.src = v)" /></el-form-item>
          <el-form-item label="目标数据源 ID"><PageIdInput v-model="mg.tgtId" @valid="(v) => (mg.tgt = v)" /></el-form-item>
          <el-form-item><el-button type="primary" :loading="mg.fetching" :disabled="!mg.src || !mg.tgt || mg.fetching" @click="mg.fetchProps">获取属性映射</el-button></el-form-item>
        </el-form>
        <el-table v-if="mg.rows.length" :data="mg.rows" size="small" max-height="300" class="mapping-table">
          <el-table-column label="源属性" min-width="180">
            <template #default="{ row }">{{ row.name }} [{{ row.type }}]{{ row.readonly ? ' (只读)' : '' }}</template>
          </el-table-column>
          <el-table-column label="目标属性" min-width="220">
            <template #default="{ row }">
              <el-select v-model="row.target" :disabled="row.readonly" clearable placeholder="(不映射)" class="full-select">
                <el-option v-for="p in mg.tgtProps" :key="p.name" :label="`${p.name} [${p.type}]`" :value="p.name" />
              </el-select>
            </template>
          </el-table-column>
        </el-table>
        <div v-if="mg.rows.length" class="inline-form migrate-actions">
          <span class="muted">并发</span>
          <el-input-number v-model="mg.workers" :min="1" :max="8" />
          <el-button type="primary" :loading="mg.starting" :disabled="mg.starting" @click="mg.start">开始迁移</el-button>
        </div>
        <div v-if="mg.task.state.progress?.status" class="prog-box">
          <el-progress :percentage="mg.task.state.progress.percent||0" :status="mg.task.state.done ? 'success' : undefined" />
          <div class="muted">总计 {{ mg.task.state.progress.total }} · 成功 {{ mg.task.state.progress.done }} · 失败 {{ mg.task.state.progress.failed }}</div>
        </div>
      </el-tab-pane>

      <!-- 批量去后缀 -->
      <el-tab-pane label="批量去除后缀" name="suffix">
        <el-form label-width="120px" class="responsive-form compact-form">
          <el-form-item label="数据源 ID"><PageIdInput v-model="sf.dsId" @valid="(v) => (sf.ds = v)" /></el-form-item>
          <el-form-item label="要去除的后缀"><el-input v-model="sf.suffix" placeholder="例如 (1)" /></el-form-item>
          <el-form-item label="并发"><el-input-number v-model="sf.workers" :min="1" :max="8" /></el-form-item>
          <el-form-item><el-button type="primary" :loading="sf.starting" :disabled="!sf.ds || !sf.suffix || sf.starting" @click="sf.start">开始去除</el-button></el-form-item>
        </el-form>
        <div v-if="sf.task.state.progress?.status" class="prog-box">
          <el-progress :percentage="sf.task.state.progress.percent||0" :status="sf.task.state.done ? 'success' : undefined" />
          <div class="muted">扫描 {{ sf.task.state.progress.scanned }} · 匹配 {{ sf.task.state.progress.total }} · 成功 {{ sf.task.state.progress.done }} · 失败 {{ sf.task.state.progress.failed }} · 跳过 {{ sf.task.state.progress.skipped }}</div>
        </div>
      </el-tab-pane>
      </el-tabs>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Tools } from '@element-plus/icons-vue'
import { api, errMsg } from '@/api/client'
import { useTask } from '@/composables/useTask'
import PageIdInput from '@/components/PageIdInput.vue'
import { fmtSize } from '@/utils/format'

const active = ref('query')
const READONLY = new Set(['rollup','created_by','created_time','last_edited_by','last_edited_time','formula','unique_id','button'])

// ---- 页面大小查询 ----
const q = reactive((() => {
  const pageId = ref(''), valid = ref(false), scanning = ref(false), items = ref<any[]>([])
  const task = useTask()
  let tid: string | null = null, timer: any = null
  async function scan() {
    if (scanning.value) return
    stop()
    items.value = []; scanning.value = true
    try {
      const r = await api.post('/api/scan', { page_id: pageId.value, probe_workers: 8 })
      tid = r.data.task_id as string
      task.start(tid, (p) => { if (p.done) { scanning.value = false; stop(); refresh() } })
      timer = setInterval(refresh, 800)
    } catch (e) { scanning.value = false; ElMessage.error(errMsg(e)) }
  }
  async function refresh() { if (!tid) return; try { const r = await api.get(`/api/scan/${tid}/list`); items.value = r.data.items || [] } catch {} }
  function stop() { if (timer) { clearInterval(timer); timer = null } }
  async function cancel() { if (tid) await task.cancel(tid); stop(); scanning.value = false }
  onUnmounted(stop)
  return { pageId, valid, scanning, items, task, scan, cancel }
})())

// ---- 页面大小自动更新 ----
const ps = reactive((() => {
  const dsId = ref(''), valid = ref(false)
  const sizeProp = ref(''), numberProps = ref<any[]>([])
  const pages = ref<any[]>([]), selected = ref<any[]>([])
  const fetchingProps = ref(false), scanningPages = ref(false), starting = ref(false)
  const task = useTask()
  async function fetchProps() {
    if (!valid.value || fetchingProps.value) return
    fetchingProps.value = true
    try {
      const r = await api.post('/api/tools/properties', { data_source_id: dsId.value })
      const props = r.data.properties || {}
      numberProps.value = Object.entries(props).map(([name, v]: any) => ({ name, type: v.type })).filter((p: any) => p.type === 'number')
    } catch (e) { ElMessage.error(errMsg(e)) } finally { fetchingProps.value = false }
  }
  async function scanPages() {
    if (!valid.value || !sizeProp.value || scanningPages.value) return
    scanningPages.value = true
    try {
      const r = await api.post('/api/tools/page-size/scan', { data_source_id: dsId.value, size_property_name: sizeProp.value })
      pages.value = [...(r.data.pages_without_size||[]), ...(r.data.pages_with_size||[])]
    } catch (e) { ElMessage.error(errMsg(e)) } finally { scanningPages.value = false }
  }
  function onSel(rows: any[]) { selected.value = rows }
  async function start() {
    if (starting.value) return
    starting.value = true
    try {
      if (!pages.value.length) await scanPages()
      const ids = selected.value.map((p: any) => p.id)
      const r = await api.post('/api/tools/page-size/start', { data_source_id: dsId.value, size_property_name: sizeProp.value, page_ids: ids, link_workers: 3, size_workers: 5 })
      task.start(r.data.task_id)
    } catch (e) { ElMessage.error(errMsg(e)) } finally { starting.value = false }
  }
  return { dsId, valid, sizeProp, numberProps, pages, selected, fetchingProps, scanningPages, starting, task, fetchProps, scanPages, onSel, start }
})())

// ---- 数据源迁移 ----
const mg = reactive((() => {
  const srcId = ref(''), tgtId = ref(''), src = ref(false), tgt = ref(false)
  const tgtProps = ref<any[]>([])
  const rows = ref<any[]>([])
  const fetching = ref(false), starting = ref(false), workers = ref(3)
  const task = useTask()
  async function fetchProps() {
    if (fetching.value) return
    fetching.value = true
    try {
      const r = await api.post('/api/tools/migrate/props', { source_id: srcId.value, target_id: tgtId.value })
      const srcProps = Object.entries(r.data.source.properties||{}).map(([name,v]:any)=>({name,type:v.type,readonly:READONLY.has(v.type)}))
      tgtProps.value = Object.entries(r.data.target.properties||{}).map(([name,v]:any)=>({name,type:v.type}))
      rows.value = srcProps.map((p:any) => ({...p, target: tgtProps.value.find((t:any)=>t.name===p.name)?.name || ''}))
    } catch (e) { ElMessage.error(errMsg(e)) } finally { fetching.value = false }
  }
  async function start() {
    if (starting.value) return
    starting.value = true
    try {
      const mapping: Record<string,string> = {}
      rows.value.forEach((r:any) => { if (r.target && !r.readonly) mapping[r.name] = r.target })
      if (!Object.keys(mapping).length) { ElMessage.warning('请至少选择一个属性映射'); starting.value=false; return }
      const r = await api.post('/api/tools/migrate/start', { source_id: srcId.value, target_id: tgtId.value, mapping, max_workers: workers.value })
      task.start(r.data.task_id)
    } catch (e) { ElMessage.error(errMsg(e)) } finally { starting.value = false }
  }
  return { srcId, tgtId, src, tgt, tgtProps, rows, fetching, starting, workers, task, fetchProps, start }
})())

// ---- 批量去后缀 ----
const sf = reactive((() => {
  const dsId = ref(''), suffix = ref(''), workers = ref(3)
  const ds = ref(false), starting = ref(false)
  const task = useTask()
  async function start() {
    if (starting.value) return
    starting.value = true
    try {
      const r = await api.post('/api/tools/suffix/start', { data_source_id: dsId.value, suffix: suffix.value, max_workers: workers.value })
      task.start(r.data.task_id)
    } catch (e) { ElMessage.error(errMsg(e)) } finally { starting.value = false }
  }
  return { dsId, suffix, workers, ds, starting, task, start }
})())
</script>

<style scoped>
.tools-panel :deep(.el-card__body) {
  padding-top: 10px;
}
.tool-tabs :deep(.el-tabs__nav-wrap::after) {
  background: var(--app-border-soft);
}
.wide-input {
  width: min(420px, 100%);
}
.result-table {
  margin-top: var(--space-3);
}
.result-summary {
  margin-top: var(--space-2);
}
.prop-select {
  width: 240px;
}
.mapping-table {
  margin-bottom: 12px;
}
.full-select {
  width: 100%;
}
.tool-inline-actions {
  display: inline-flex;
  margin-left: var(--space-2);
  vertical-align: middle;
}
.prog-box {
  margin-top: var(--space-4);
  padding: var(--space-3);
  background: var(--app-surface-2);
  border: 1px solid var(--app-border-soft);
  border-radius: var(--radius-md);
}
.compact-form {
  max-width: 620px;
}
.tool-status {
  margin-top: var(--space-3);
}
@media (max-width: 720px) {
  .tool-inline-actions {
    display: flex;
    margin: var(--space-3) 0 0;
  }
}
</style>
