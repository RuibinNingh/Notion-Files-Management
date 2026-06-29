<template>
  <div class="page page-stack">
    <div class="page-head">
      <div>
        <div class="page-kicker">API Keys</div>
        <h1 class="page-title"><el-icon><Key /></el-icon><span>API 密钥</span></h1>
        <p class="page-desc">为第三方调用签发密钥。明文只显示一次，丢失需重新生成。长期密钥永远只走 Bearer 头，不放进 URL。</p>
      </div>
      <div class="action-row">
        <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
        <el-button type="primary" :icon="Plus" @click="openCreate">新建密钥</el-button>
      </div>
    </div>

    <el-card class="panel" shadow="never">
      <div class="section-toolbar">
        <div>
          <div class="panel-title">密钥列表</div>
          <div class="panel-subtitle">仅保存哈希；列表只显示前缀、权限、状态与最后使用</div>
        </div>
      </div>

      <el-empty v-if="!loading && !items.length" description="暂无 API 密钥" :image-size="80" />
      <el-table v-else :data="items" row-key="id" size="small">
        <el-table-column label="名称 / 前缀" min-width="220">
          <template #default="{ row }">
            <div class="key-name">
              <div class="key-title">
                <span>{{ row.name }}</span>
                <span class="status-chip" :class="statusClass(row)">{{ statusText(row) }}</span>
              </div>
              <div class="key-prefix">{{ row.prefix }}••••••••</div>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="权限范围" min-width="220">
          <template #default="{ row }">
            <div class="scope-chips">
              <el-tag v-for="s in row.scopes" :key="s" size="small" :type="isHighRisk(s) ? 'danger' : 'info'" effect="plain">
                {{ s }}
              </el-tag>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="限流" width="100">
          <template #default="{ row }">{{ row.rate_limit_rpm ? row.rate_limit_rpm + ' /分' : '不限' }}</template>
        </el-table-column>
        <el-table-column label="过期时间" min-width="160">
          <template #default="{ row }">{{ row.expires_at ? fmtTime(row.expires_at) : '永不过期' }}</template>
        </el-table-column>
        <el-table-column label="最后使用" min-width="170">
          <template #default="{ row }">{{ row.last_used_at ? fmtTime(row.last_used_at) : '从未使用' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <div class="table-actions">
              <el-button link :icon="row.enabled ? Lock : Unlock" @click="toggle(row)">
                {{ row.enabled ? '禁用' : '启用' }}
              </el-button>
              <el-button link :icon="EditPen" @click="openEdit(row)">编辑</el-button>
              <el-button link type="danger" :icon="Delete" @click="remove(row)">删除</el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 跨域允许源 -->
    <el-card class="panel" shadow="never">
      <div class="section-toolbar">
        <div>
          <div class="panel-title">跨域允许源（CORS）</div>
          <div class="panel-subtitle">仅白名单域名可从浏览器跨域调用本服务；默认不开放。禁用 *、null、带路径的 origin。</div>
        </div>
      </div>
      <div class="cors-row">
        <el-input
          v-model="newOrigin"
          placeholder="https://your-app.example.com"
          @keyup.enter="addOrigin"
          style="flex: 1"
        />
        <el-button :icon="Plus" @click="addOrigin">添加</el-button>
        <el-button type="primary" :loading="savingCors" @click="saveCors">保存</el-button>
      </div>
      <div v-if="corsOrigins.length" class="cors-chips">
        <el-tag
          v-for="(o, i) in corsOrigins"
          :key="i"
          closable
          @close="removeOrigin(i)"
        >{{ o }}</el-tag>
      </div>
      <el-empty v-else description="未配置跨域白名单（默认不开放跨域）" :image-size="60" />
    </el-card>

    <!-- 创建 / 编辑 -->
    <el-dialog v-model="dialogVisible" :title="editing ? '编辑密钥' : '新建密钥'" width="560px" @closed="onDialogClosed">
      <el-form label-position="top" class="key-form">
        <el-form-item label="名称">
          <el-input v-model="form.name" placeholder="便于识别的用途，如：自动化脚本" maxlength="120" show-word-limit />
        </el-form-item>
        <el-form-item label="权限范围">
          <div class="scope-groups">
            <div class="scope-group">
              <div class="scope-group-title">业务能力</div>
              <el-checkbox-group v-model="form.scopes">
                <el-checkbox v-for="s in businessScopes" :key="s" :value="s">{{ s }}</el-checkbox>
              </el-checkbox-group>
            </div>
            <div class="scope-group">
              <div class="scope-group-title danger">高危能力（需谨慎）</div>
              <el-checkbox-group v-model="form.scopes">
                <el-checkbox v-for="s in highRiskScopes" :key="s" :value="s">{{ s }}</el-checkbox>
              </el-checkbox-group>
            </div>
          </div>
        </el-form-item>
        <el-form-item label="过期时间（留空=永不过期，按本地时间选择）">
          <el-date-picker
            v-model="form.expires_at"
            type="datetime"
            placeholder="选择过期时间"
            format="YYYY-MM-DD HH:mm"
            :clearable="true"
            style="width: 100%"
          />
          <div class="muted-hint">过期时间会以 UTC 存储并展示为本地时间。</div>
        </el-form-item>
        <el-form-item label="限流（每分钟请求数，0=不限）">
          <el-input-number v-model="form.rate_limit_rpm" :min="0" :max="100000" :step="10" controls-position="right" />
        </el-form-item>
        <el-form-item v-if="!editing" label="创建后立即启用">
          <el-switch v-model="form.enabled" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submit">确定</el-button>
      </template>
    </el-dialog>

    <!-- 一次性明文展示 -->
    <el-dialog v-model="plainVisible" title="密钥已创建" width="560px" :close-on-click-modal="false" @closed="onPlainClosed">
      <el-alert type="warning" :closable="false" show-icon title="明文只显示一次，请立即复制保存，关闭后无法再次查看。" />
      <div class="plaintext-box">
        <code>{{ plaintext }}</code>
        <el-button :icon="CopyDocument" @click="copyPlain">复制</el-button>
      </div>
      <template #footer>
        <el-button type="primary" @click="plainVisible = false">我已保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Key, Refresh, Plus, Delete, EditPen, Lock, Unlock, CopyDocument } from '@element-plus/icons-vue'
import { api, errMsg } from '@/api/client'

interface ApiKey {
  id: string
  name: string
  prefix: string
  scopes: string[]
  enabled: boolean
  expires_at: string | null
  rate_limit_rpm: number
  created_at: string
  last_used_at: string | null
  last_used_ip: string
}

const items = ref<ApiKey[]>([])
const loading = ref(false)
const businessScopes = ref<string[]>(['scan', 'download', 'upload', 'tools', 'tasks'])
const highRiskScopes = ref<string[]>(['settings', 'system', 'logs', 'cache', 'apikeys'])

const dialogVisible = ref(false)
const editing = ref<ApiKey | null>(null)
const saving = ref(false)
// 过期时间用 Date 对象绑定（el-date-picker 显示本地时间），提交时转 UTC ISO
const form = reactive({
  name: '',
  scopes: [] as string[],
  expires_at: null as Date | null,
  rate_limit_rpm: 0,
  enabled: true,
})

const plainVisible = ref(false)
const plaintext = ref('')

// 跨域白名单
const corsOrigins = ref<string[]>([])
const newOrigin = ref('')
const savingCors = ref(false)

onMounted(load)

async function load() {
  loading.value = true
  try {
    const [keysR, cfgR] = await Promise.all([
      api.get('/api/apikeys'),
      api.get('/api/settings'),
    ])
    items.value = keysR.data.items || []
    if (keysR.data.scopes) {
      businessScopes.value = keysR.data.scopes.business || businessScopes.value
      highRiskScopes.value = keysR.data.scopes.high_risk || highRiskScopes.value
    }
    corsOrigins.value = cfgR.data.api_cors_allowed_origins || []
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    loading.value = false
  }
}

function isHighRisk(s: string) {
  return highRiskScopes.value.includes(s)
}

function statusText(row: ApiKey) {
  if (!row.enabled) return '已禁用'
  if (row.expires_at && new Date(row.expires_at).getTime() <= Date.now()) return '已过期'
  return '启用中'
}
function statusClass(row: ApiKey) {
  if (!row.enabled) return 'warn'
  if (row.expires_at && new Date(row.expires_at).getTime() <= Date.now()) return 'err'
  return 'ok'
}

function openCreate() {
  editing.value = null
  form.name = ''
  form.scopes = ['scan', 'download', 'upload', 'tools', 'tasks']
  form.expires_at = null
  form.rate_limit_rpm = 0
  form.enabled = true
  dialogVisible.value = true
}

function openEdit(row: ApiKey) {
  editing.value = row
  form.name = row.name
  form.scopes = [...row.scopes]
  form.expires_at = row.expires_at ? new Date(row.expires_at) : null
  form.rate_limit_rpm = row.rate_limit_rpm
  form.enabled = row.enabled
  dialogVisible.value = true
}

function onDialogClosed() {
  editing.value = null
}

function onPlainClosed() {
  // 弹窗关闭后立即清空明文，减少明文留在前端内存的时间
  plaintext.value = ''
}

// 本地时间 Date → UTC ISO 字符串（或 null）
function expiresPayload(): string | null {
  return form.expires_at ? new Date(form.expires_at).toISOString() : null
}

async function submit() {
  if (!form.scopes.length) {
    ElMessage.warning('至少选择一个权限范围')
    return
  }
  saving.value = true
  try {
    if (editing.value) {
      await api.patch(`/api/apikeys/${editing.value.id}`, {
        name: form.name,
        scopes: form.scopes,
        expires_at: expiresPayload(),
        rate_limit_rpm: form.rate_limit_rpm,
      })
      ElMessage.success('密钥已更新')
      dialogVisible.value = false
    } else {
      const r = await api.post('/api/apikeys', {
        name: form.name,
        scopes: form.scopes,
        expires_at: expiresPayload(),
        rate_limit_rpm: form.rate_limit_rpm,
        enabled: form.enabled,
      })
      plaintext.value = r.data.plaintext
      dialogVisible.value = false
      plainVisible.value = true
      ElMessage.success('密钥已创建')
    }
    await load()
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    saving.value = false
  }
}

async function toggle(row: ApiKey) {
  try {
    await api.patch(`/api/apikeys/${row.id}`, { enabled: !row.enabled })
    ElMessage.success(row.enabled ? '已禁用' : '已启用')
    await load()
  } catch (e) {
    ElMessage.error(errMsg(e))
  }
}

async function remove(row: ApiKey) {
  try {
    await ElMessageBox.confirm(`确定删除密钥「${row.name}」？删除后该密钥立即失效。`, '删除密钥', { type: 'warning' })
    await api.delete(`/api/apikeys/${row.id}`)
    ElMessage.success('密钥已删除')
    await load()
  } catch (e: any) {
    if (e !== 'cancel') ElMessage.error(errMsg(e))
  }
}

async function copyPlain() {
  try {
    await navigator.clipboard.writeText(plaintext.value)
    ElMessage.success('已复制到剪贴板')
  } catch {
    ElMessage.warning('复制失败，请手动选中复制')
  }
}

// ---- 跨域白名单 ----
function addOrigin() {
  const o = newOrigin.value.trim()
  if (!o) return
  if (!/^https?:\/\/[^/]+$/i.test(o)) {
    ElMessage.warning('请输入合法的 http(s) origin，如 https://your-app.example.com')
    return
  }
  if (corsOrigins.value.includes(o)) {
    ElMessage.warning('该 origin 已存在')
    return
  }
  corsOrigins.value.push(o)
  newOrigin.value = ''
}

function removeOrigin(i: number) {
  corsOrigins.value.splice(i, 1)
}

async function saveCors() {
  savingCors.value = true
  try {
    await api.put('/api/settings', { api_cors_allowed_origins: corsOrigins.value })
    ElMessage.success('跨域白名单已保存')
    await load()
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    savingCors.value = false
  }
}

function fmtTime(s: string | null) {
  if (!s) return '-'
  return new Date(s).toLocaleString()
}
</script>

<style scoped>
.key-name {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.key-title {
  display: flex;
  align-items: center;
  gap: 8px;
}
.key-prefix {
  color: var(--app-muted);
  font-size: 12px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}
.scope-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.table-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}
.key-form :deep(.el-checkbox) {
  margin-right: 12px;
}
.scope-groups {
  display: flex;
  flex-direction: column;
  gap: 12px;
  width: 100%;
}
.scope-group-title {
  font-size: 13px;
  color: var(--app-muted);
  margin-bottom: 4px;
}
.scope-group-title.danger {
  color: var(--app-danger);
}
.muted-hint {
  margin-top: 4px;
  font-size: 12px;
  color: var(--app-muted);
}
.plaintext-box {
  margin-top: 12px;
  display: flex;
  gap: 8px;
  align-items: center;
}
.plaintext-box code {
  flex: 1;
  padding: 8px 10px;
  background: var(--el-fill-color-light);
  border-radius: var(--radius-md);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  word-break: break-all;
}
.cors-row {
  display: flex;
  gap: 8px;
  align-items: center;
}
.cors-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}
</style>
