<template>
  <div class="page page-narrow page-stack">
    <div class="page-head">
      <div>
        <div class="page-kicker">Configuration</div>
        <h1 class="page-title"><el-icon><Setting /></el-icon><span>设置</span></h1>
      </div>
    </div>

    <el-card class="panel" shadow="never">
      <div class="panel-head">
        <div>
          <div class="panel-title">应用配置</div>
          <div class="panel-subtitle">config.json</div>
        </div>
        <span class="status-chip" :class="form.notion_token ? 'ok' : 'warn'">{{ form.notion_token ? 'Token 已填写' : 'Token 未填写' }}</span>
      </div>
      <el-form :model="form" label-width="140px" class="responsive-form">
        <div class="form-section">Notion 服务配置</div>
        <el-form-item label="Integration Token">
          <el-input v-model="form.notion_token" type="password" show-password placeholder="ntn_xxxxxxxx..." />
        </el-form-item>
        <el-form-item label="Notion 地址">
          <el-input v-model="form.notion_base_url" placeholder="https://api.notion.com/v1" />
        </el-form-item>

        <div class="form-section">任务并发</div>
        <el-form-item label="下载并发数">
          <el-select v-model="form.max_download_workers" class="workers-select">
            <el-option v-for="n in [1,2,3,5,8]" :key="n" :label="String(n)" :value="n" />
          </el-select>
        </el-form-item>
        <el-form-item label="上传并发数">
          <el-select v-model="form.max_upload_workers" class="workers-select">
            <el-option v-for="n in [1,2,3,5,8]" :key="n" :label="String(n)" :value="n" />
          </el-select>
        </el-form-item>

        <div class="form-section">实验性下载加速</div>
        <el-form-item label="分片下载">
          <el-switch v-model="form.enable_range_download" />
          <span class="muted inline-note">仅大文件且 URL 支持 Range 时启用</span>
        </el-form-item>
        <el-form-item label="分片阈值">
          <el-input-number v-model="form.range_download_min_mb" :min="16" :max="8192" />
          <span class="muted inline-note">MB</span>
        </el-form-item>
        <el-form-item label="分片数">
          <el-select v-model="form.range_download_chunks" class="workers-select">
            <el-option v-for="n in [2,3,4,6,8,12,16]" :key="n" :label="String(n)" :value="n" />
          </el-select>
          <span class="muted inline-note">建议先用 4</span>
        </el-form-item>

        <div class="form-section">缓存策略</div>
        <el-form-item label="自动清理">
          <el-switch v-model="form.cache_auto_cleanup_enabled" />
          <span class="muted inline-note">跳过运行中的任务缓存</span>
        </el-form-item>
        <el-form-item label="缓存保留">
          <el-input-number v-model="form.cache_ttl_hours" :min="1" :max="168" />
          <span class="muted inline-note">小时</span>
        </el-form-item>
        <el-form-item label="清理间隔">
          <el-input-number v-model="form.cache_cleanup_interval_minutes" :min="1" :max="1440" />
          <span class="muted inline-note">分钟</span>
        </el-form-item>

        <div class="form-section">外观</div>
        <el-form-item label="主题模式">
          <el-radio-group :model-value="theme.mode" @update:model-value="(v: any) => theme.setMode(v)">
            <el-radio-button value="light">浅色</el-radio-button>
            <el-radio-button value="dark">深色</el-radio-button>
          </el-radio-group>
          <span class="muted inline-note">本机浏览器</span>
        </el-form-item>
        <el-form-item label="主题色">
          <el-color-picker v-model="form.theme_accent_color" />
          <span class="muted inline-note">{{ form.theme_accent_color }}</span>
        </el-form-item>

        <div class="form-section">访问密码</div>
        <el-form-item label="新密码">
          <el-input v-model="form.password" type="password" show-password placeholder="留空则不修改" />
        </el-form-item>

        <el-form-item>
          <div class="action-row">
            <el-button type="primary" :loading="saving" @click="onSave">保存配置</el-button>
            <span class="muted">部分设置需重启应用才能完全生效</span>
          </div>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card class="panel" shadow="never">
      <div class="panel-head">
        <div>
          <div class="panel-title">系统工具</div>
          <div class="panel-subtitle">本地维护</div>
        </div>
      </div>
      <div class="action-row">
        <el-button :icon="Refresh" :loading="checking" @click="onCheckVersion">检查版本更新</el-button>
        <el-button :icon="Delete" @click="onClearCache">清除缓存</el-button>
        <el-button :icon="Document" @click="onViewLogs">查看日志</el-button>
        <el-button type="warning" plain :icon="RefreshRight" @click="onRestart">重启服务</el-button>
      </div>
      <div v-if="versionInfo" class="version-box">
        <el-descriptions :column="1" border>
          <el-descriptions-item label="当前版本">
            <span>v{{ localVersion }}</span>
            <el-tag v-if="channel" class="channel-tag" size="small" :type="channel === 'Status' ? 'success' : 'warning'">
              {{ channel === 'Status' ? '正式版' : '预发布 Beta' }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="最新版本">{{ versionInfo.version || '-' }}</el-descriptions-item>
          <el-descriptions-item label="构建日期">{{ versionInfo.build_date || '-' }}</el-descriptions-item>
          <el-descriptions-item label="更新内容">
            <ul class="changelog"><li v-for="(c,i) in (versionInfo.changelog||[])" :key="i">{{ c }}</li></ul>
          </el-descriptions-item>
        </el-descriptions>
      </div>
    </el-card>

    <LogsDialog v-model="logsVisible" />
  </div>
</template>

<script setup lang="ts">
import { computed, ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Setting, Refresh, Delete, Document, RefreshRight } from '@element-plus/icons-vue'
import { useConfigStore } from '@/stores/config'
import { useThemeStore } from '@/stores/theme'
import { api, errMsg } from '@/api/client'
import LogsDialog from '@/components/LogsDialog.vue'

const config = useConfigStore()
const theme = useThemeStore()
const saving = ref(false)
const checking = ref(false)
const versionInfo = ref<any>(null)
const channel = ref<string>('Status')
const logsVisible = ref(false)
const localVersion = computed(() => versionInfo.value?.local || `2.0.0-${channel.value || 'Status'}`)

const form = reactive({
  notion_token: '',
  notion_base_url: 'https://api.notion.com/v1',
  max_download_workers: 3,
  max_upload_workers: 3,
  enable_range_download: false,
  range_download_min_mb: 128,
  range_download_chunks: 4,
  cache_auto_cleanup_enabled: true,
  cache_ttl_hours: 1,
  cache_cleanup_interval_minutes: 15,
  theme_accent_color: '#1E90FF',
  password: '',
})

onMounted(() => {
  const c = config.config
  if (c) {
    form.notion_token = c.notion_token || ''
    form.notion_base_url = c.notion_base_url || 'https://api.notion.com/v1'
    form.max_download_workers = c.max_download_workers || 3
    form.max_upload_workers = c.max_upload_workers || 3
    form.enable_range_download = !!c.enable_range_download
    form.range_download_min_mb = c.range_download_min_mb || 128
    form.range_download_chunks = c.range_download_chunks || 4
    form.cache_auto_cleanup_enabled = c.cache_auto_cleanup_enabled !== false
    form.cache_ttl_hours = Math.max(1, Math.round((c.cache_ttl_seconds || 3600) / 3600))
    form.cache_cleanup_interval_minutes = Math.max(1, Math.round((c.cache_cleanup_interval_seconds || 900) / 60))
    form.theme_accent_color = c.theme_accent_color || '#1E90FF'
  }
})

// 拉取当前渠道（启动时通过 NFM_CHANNEL 环境变量写入后端 config.json）
onMounted(async () => {
  try {
    const r = await api.get('/api/version/channel')
    channel.value = r.data.channel
  } catch {}
})

async function onSave() {
  saving.value = true
  try {
    const patch: any = {
      ...form,
      cache_ttl_seconds: Math.max(1, form.cache_ttl_hours) * 3600,
      cache_cleanup_interval_seconds: Math.max(1, form.cache_cleanup_interval_minutes) * 60,
    }
    delete patch.cache_ttl_hours
    delete patch.cache_cleanup_interval_minutes
    if (!patch.password) delete patch.password
    await config.save(patch)
    ElMessage.success('配置已保存')
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    saving.value = false
  }
}

async function onCheckVersion() {
  checking.value = true
  try {
    const r = await api.get('/api/version')
    versionInfo.value = r.data
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    checking.value = false
  }
}

async function onClearCache() {
  try {
    await ElMessageBox.confirm('将清除所有缓存（staging/公告缓存），确定继续？', '危险操作', { type: 'warning' })
    const r = await api.post('/api/cache/clear')
    ElMessage.success(`已清除 ${r.data.deleted} 项缓存`)
  } catch (e: any) {
    if (e !== 'cancel') ElMessage.error(errMsg(e))
  }
}

function onViewLogs() {
  logsVisible.value = true
}

async function onRestart() {
  try {
    await ElMessageBox.confirm('确定重启服务？运行中的任务可能丢失。', '确认重启', { type: 'warning' })
    await api.post('/api/system/restart')
    ElMessage.success('重启指令已发送，请稍后刷新页面')
  } catch (e: any) {
    if (e !== 'cancel') ElMessage.error(errMsg(e))
  }
}
</script>

<style scoped>
.version-box { margin-top: 16px; }
.changelog { margin: 0; padding-left: 18px; }
.workers-select {
  width: 120px;
}
.inline-note,
.channel-tag {
  margin-left: 12px;
}
.form-section {
  margin: 18px 0 12px;
  color: var(--app-text);
  font-weight: 700;
}
.form-section:first-child {
  margin-top: 0;
}
</style>
