<template>
  <div class="page page-stack">
    <div class="page-head">
      <div>
        <div class="page-kicker">Workspace</div>
        <h1 class="page-title">
          <el-icon><HomeFilled /></el-icon>
          <span>Notion Files Management</span>
        </h1>
        <p class="page-desc">v{{ localVersion }}</p>
      </div>
      <div class="action-row">
        <el-button :icon="Link" @click="open('https://nfm.ruibin-ningh.top')">官网</el-button>
        <el-button :icon="Link" @click="open('https://github.com/RuibinNingh/Notion-Files-Management')">GitHub</el-button>
        <el-button type="warning" plain :icon="Star" @click="open('https://nfm.ruibin-ningh.top/sponsor')">赞助</el-button>
      </div>
    </div>

    <el-alert
      v-if="versionInfo && hasUpdate"
      :title="`发现新版本 ${versionInfo.version}`"
      type="warning"
      show-icon
      :closable="false"
    />

    <div class="quick-grid">
      <el-card
        v-for="item in quickActions"
        :key="item.path"
        class="panel quick-card"
        shadow="never"
        role="button"
        tabindex="0"
        @click="router.push(item.path)"
        @keyup.enter="router.push(item.path)"
      >
        <div class="quick-icon">
          <el-icon><component :is="item.icon" /></el-icon>
        </div>
        <div class="quick-body">
          <div class="panel-title">{{ item.title }}</div>
          <div class="panel-subtitle">{{ item.desc }}</div>
        </div>
      </el-card>
    </div>

    <el-card class="panel" shadow="never">
      <div class="panel-head">
        <div>
          <div class="panel-title">最近任务</div>
          <div class="panel-subtitle">运行中 {{ tasks.running.length }} · 失败 {{ tasks.failed.length }}</div>
        </div>
        <el-button size="small" :icon="List" @click="router.push('/tasks')">任务看板</el-button>
      </div>
      <el-empty v-if="!tasks.recent.length" description="暂无任务" :image-size="72" />
      <div v-else class="task-list dashboard-task-list">
        <div v-for="task in tasks.recent" :key="task.task_id" class="task-row dashboard-task-row">
          <div class="task-head">
            <span class="task-name">{{ task.title || task.kind }}</span>
            <span class="t-status" :class="statusClass(task.status)">{{ statusText(task.status) }}</span>
          </div>
          <div class="muted">{{ task.kind }} · {{ fmtTime(task.created_at) }}</div>
        </div>
      </div>
    </el-card>

    <el-card class="panel" shadow="never">
      <div class="panel-head">
        <div>
          <div class="panel-title">运行状态</div>
          <div class="panel-subtitle">这些状态来自本地服务配置。</div>
        </div>
      </div>
      <div class="status-grid">
        <div class="metric">
          <div class="metric-label">Notion Token</div>
          <div class="metric-value">{{ tokenReady ? '已配置' : '未配置' }}</div>
        </div>
        <div class="metric">
          <div class="metric-label">下载并发</div>
          <div class="metric-value">{{ config.config?.max_download_workers || 3 }}</div>
        </div>
        <div class="metric">
          <div class="metric-label">上传并发</div>
          <div class="metric-value">{{ config.config?.max_upload_workers || 3 }}</div>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { Link, Star, HomeFilled, Upload, Download, Tools, Setting, List, FolderOpened } from '@element-plus/icons-vue'
import { api } from '@/api/client'
import { useConfigStore } from '@/stores/config'
import { useTasksStore } from '@/stores/tasks'

const versionInfo = ref<any>(null)
const localVersion = computed(() => versionInfo.value?.local || '2.0.0-Beta')
const router = useRouter()
const config = useConfigStore()
const tasks = useTasksStore()
const tokenReady = computed(() => !!config.config?.notion_token)
const quickActions = [
  { path: '/download', title: '下载文件', desc: '扫描 · 选择 · 打包', icon: Download },
  { path: '/upload', title: '上传文件', desc: '文件 · 文件夹 · 进度', icon: Upload },
  { path: '/tasks', title: '任务看板', desc: '全局 · 重试 · 取消', icon: List },
  { path: '/cache', title: '云端缓存', desc: '上传 · 下载 · 清理', icon: FolderOpened },
  { path: '/tools', title: '工具箱', desc: '大小 · 迁移 · 后缀', icon: Tools },
  { path: '/settings', title: '设置', desc: 'Token · 并发 · 密码', icon: Setting },
]

const hasUpdate = computed(() => {
  if (!versionInfo.value?.version) return false
  return String(versionInfo.value.version) !== localVersion.value
})

function open(url: string) {
  window.open(url, '_blank')
}

onMounted(async () => {
  tasks.load()
  try {
    const r = await api.get('/api/version')
    versionInfo.value = r.data
  } catch {}
})

function statusText(s: string) {
  return ({ running: '运行中', done: '已完成', error: '失败', cancelled: '已取消' } as any)[s] || s
}

function statusClass(s: string) {
  return ({ done: 'ok', error: 'err', cancelled: 'wait', running: 'wait' } as any)[s] || 'wait'
}

function fmtTime(ts?: number) {
  if (!ts) return '-'
  return new Date(ts * 1000).toLocaleString()
}
</script>

<style scoped>
.quick-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
  gap: 14px;
}
.quick-card {
  cursor: pointer;
  transition: border-color var(--duration-fast) ease-in-out, transform var(--duration-normal) var(--ease-standard);
}
.quick-card:hover {
  border-color: color-mix(in srgb, var(--app-primary) 55%, var(--app-border-soft));
  transform: translateY(-1px);
}
.quick-card :deep(.el-card__body) {
  display: flex;
  gap: 12px;
  align-items: flex-start;
}
.quick-icon {
  display: grid;
  place-items: center;
  width: 38px;
  height: 38px;
  color: var(--app-primary);
  background: color-mix(in srgb, var(--app-primary) 12%, transparent);
  border: 1px solid color-mix(in srgb, var(--app-primary) 22%, transparent);
  border-radius: 8px;
}
.quick-body {
  min-width: 0;
}
.dashboard-task-list {
  gap: 8px;
}
.dashboard-task-row {
  padding: 10px 12px;
}
</style>
