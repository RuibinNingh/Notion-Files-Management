<template>
  <el-container class="layout">
    <el-aside :width="collapsed ? '64px' : '210px'" class="aside">
      <div class="brand" role="button" tabindex="0" @click="router.push('/')" @keyup.enter="router.push('/')">
        <img src="/logo.png" alt="NFM logo" class="logo" />
        <div v-show="!collapsed" class="brand-text">
          <div>NFM</div>
          <div class="brand-subtitle">Files Console</div>
        </div>
      </div>
      <el-menu
        :default-active="route.path"
        :collapse="collapsed"
        router
        class="nav"
      >
        <el-menu-item index="/">
          <el-icon><HomeFilled /></el-icon><template #title>主页</template>
        </el-menu-item>
        <el-menu-item index="/notice">
          <span class="nav-icon-wrap">
            <el-icon><Bell /></el-icon>
            <span v-if="collapsed && unread" class="nav-icon-dot" aria-hidden="true" />
          </span>
          <template #title>
            <span class="nav-title">
              <span>公告</span>
              <el-badge v-if="unread" :value="unread" class="nav-badge" />
            </span>
          </template>
        </el-menu-item>
        <el-menu-item index="/tasks">
          <el-icon><List /></el-icon><template #title>任务</template>
        </el-menu-item>
        <el-menu-item index="/cache">
          <el-icon><FolderOpened /></el-icon><template #title>云端缓存</template>
        </el-menu-item>
        <el-menu-item index="/upload">
          <el-icon><Upload /></el-icon><template #title>上传</template>
        </el-menu-item>
        <el-menu-item index="/download">
          <el-icon><Download /></el-icon><template #title>下载</template>
        </el-menu-item>
        <el-menu-item index="/tools">
          <el-icon><Tools /></el-icon><template #title>工具箱</template>
        </el-menu-item>
        <el-menu-item index="/settings">
          <el-icon><Setting /></el-icon><template #title>设置</template>
        </el-menu-item>
      </el-menu>
    </el-aside>
    <el-container>
      <el-header class="header">
        <el-button class="icon-btn" text :icon="collapsed ? Expand : Fold" :aria-label="collapsed ? '展开侧栏' : '收起侧栏'" @click="toggleCollapse" />
        <div class="header-title">{{ currentTitle }}</div>
        <div class="header-actions">
          <el-button class="icon-btn" text :icon="theme.mode === 'dark' ? Sunny : Moon" :aria-label="theme.mode === 'dark' ? '切换到浅色' : '切换到深色'" :title="theme.mode === 'dark' ? '切换到浅色' : '切换到深色'" @click="theme.toggle" />
          <el-tag v-if="channel" class="optional" size="small" :type="channel === 'Status' ? 'success' : 'warning'" effect="plain">
            {{ channel === 'Status' ? '正式版' : 'Beta' }}
          </el-tag>
          <el-tag size="small" :type="config.config?.notion_token ? 'success' : 'warning'" effect="plain">
            {{ config.config?.notion_token ? 'Token 已配置' : 'Token 未配置' }}
          </el-tag>
          <el-button text :icon="SwitchButton" @click="onLogout">退出</el-button>
        </div>
      </el-header>
      <el-main id="main-content" class="main" tabindex="-1">
        <keep-alive :include="['Download']">
          <router-view />
        </keep-alive>
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, watch, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { HomeFilled, Bell, Upload, Download, Tools, Setting, Fold, Expand, SwitchButton, Sunny, Moon, List, FolderOpened } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import { useConfigStore } from '@/stores/config'
import { useThemeStore } from '@/stores/theme'
import { api } from '@/api/client'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const config = useConfigStore()
const theme = useThemeStore()
const collapsed = ref(false)
const unread = ref(0)
const channel = ref<string>('Status')

const titleMap: Record<string, string> = {
  '/': '主页',
  '/notice': '公告',
  '/tasks': '任务看板',
  '/cache': '云端缓存',
  '/upload': '文件上传',
  '/download': '文件下载',
  '/tools': '工具箱',
  '/settings': '设置',
}
const currentTitle = computed(() => titleMap[route.path] || 'Notion Files Management')

function syncForViewport() {
  if (window.innerWidth <= 720) collapsed.value = true
}

function toggleCollapse() {
  collapsed.value = !collapsed.value
}

async function refreshUnread() {
  try {
    const r = await api.get('/api/notices')
    unread.value = (r.data.notices || []).filter((n: any) => n.unread).length
  } catch {}
}

function onNoticesUpdated(e: Event) {
  const detail = (e as CustomEvent<{ unread?: number }>).detail
  if (typeof detail?.unread === 'number') {
    unread.value = detail.unread
    return
  }
  refreshUnread()
}

onMounted(async () => {
  syncForViewport()
  window.addEventListener('resize', syncForViewport)
  window.addEventListener('nfm:notices-updated', onNoticesUpdated)
  try {
    const ch = await api.get('/api/version/channel')
    channel.value = ch.data.channel
  } catch {}
  refreshUnread()
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', syncForViewport)
  window.removeEventListener('nfm:notices-updated', onNoticesUpdated)
})
watch(() => route.path, async () => {
  syncForViewport()
  await nextTick()
  document.getElementById('main-content')?.focus({ preventScroll: true })
})

async function onLogout() {
  await auth.logout()
  router.push('/login')
}
</script>
