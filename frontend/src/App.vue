<template>
  <el-config-provider :locale="locale">
    <router-view />
  </el-config-provider>
</template>

<script setup lang="ts">
import { onMounted, watch } from 'vue'
import { ElConfigProvider } from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import { useAuthStore } from './stores/auth'
import { useConfigStore } from './stores/config'
import { useThemeStore } from './stores/theme'

const locale = zhCn
const auth = useAuthStore()
const config = useConfigStore()
// 初始化主题 store：实例化时根据本地存储应用深/浅色，避免登录页等无 MainLayout 的场景失同步
useThemeStore()

onMounted(async () => {
  await auth.check()
})

// 已登录后才拉取配置（未登录时 /api/settings 会 401）
watch(() => auth.isLoggedIn, (v) => { if (v) config.load() }, { immediate: true })

watch(
  () => config.config?.theme_accent_color,
  (v) => {
    if (v) document.documentElement.style.setProperty('--app-primary', v)
  },
  { immediate: true },
)
</script>
