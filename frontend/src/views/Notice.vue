<template>
  <div class="page page-stack">
    <div class="page-head">
      <div>
        <div class="page-kicker">Notices</div>
        <h1 class="page-title"><el-icon><Bell /></el-icon><span>公告</span></h1>
      </div>
      <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
    </div>

    <el-card v-if="!loading && !notices.length" class="panel" shadow="never">
      <el-empty description="暂无公告" />
    </el-card>

    <el-card v-for="n in notices" :key="n.id" class="panel notice-card" shadow="never">
      <div class="notice-head">
        <div class="notice-title">
          <el-tag v-if="n.pinned" size="small" type="danger" effect="dark">置顶</el-tag>
          <span class="t">{{ n.title }}</span>
          <el-tag v-for="tag in (n.tags||[])" :key="tag" size="small" effect="plain">{{ tag }}</el-tag>
        </div>
        <div class="notice-meta">
          <span v-if="n.unread" class="unread-dot" aria-label="未读" />
          <span class="muted">{{ n.date }}</span>
        </div>
      </div>
      <el-divider />
      <div v-if="loadingId === n.id" class="center"><el-icon class="is-loading"><Loading /></el-icon></div>
      <div v-else-if="contents[n.id]" class="markdown-body" v-html="contents[n.id]"></div>
      <el-button v-else text size="small" @click="loadContent(n.id)">查看正文</el-button>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { Bell, Refresh, Loading } from '@element-plus/icons-vue'
import MarkdownIt from 'markdown-it'
import { api, errMsg } from '@/api/client'
import { ElMessage } from 'element-plus'

const md = new MarkdownIt({ html: false, linkify: true, breaks: true })
// 链接新标签打开
const defaultLink = md.renderer.rules.link_open || ((tokens, idx, opts, _env, self) => self.renderToken(tokens, idx, opts))
md.renderer.rules.link_open = (tokens, idx, opts, env, self) => {
  const aIndex = tokens[idx].attrIndex('target')
  if (aIndex < 0) tokens[idx].attrPush(['target', '_blank'])
  else tokens[idx].attrs![aIndex][1] = '_blank'
  tokens[idx].attrSet('rel', 'noopener')
  return defaultLink(tokens, idx, opts, env, self)
}

const loading = ref(false)
const loadingId = ref<string | null>(null)
const notices = ref<any[]>([])
const contents = ref<Record<string, string>>({})

function emitUnreadCount() {
  const count = notices.value.filter((n: any) => n.unread).length
  window.dispatchEvent(new CustomEvent('nfm:notices-updated', { detail: { unread: count } }))
}

async function load() {
  loading.value = true
  try {
    const r = await api.get('/api/notices')
    notices.value = r.data.notices || []
    emitUnreadCount()
    // 自动展开第一条（置顶优先）
    if (notices.value.length && !contents.value[notices.value[0].id]) {
      loadContent(notices.value[0].id)
    }
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    loading.value = false
  }
}

async function loadContent(id: string) {
  loadingId.value = id
  try {
    const r = await api.get(`/api/notices/${id}`)
    contents.value[id] = md.render(r.data.content || '')
    const notice = notices.value.find((n: any) => n.id === id)
    if (notice?.unread) {
      notice.unread = false
      emitUnreadCount()
    }
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    loadingId.value = null
  }
}

onMounted(load)
</script>

<style scoped>
.notice-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }
.notice-title { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.notice-title .t { font-weight: 600; font-size: 15px; }
.notice-meta { display: inline-flex; align-items: center; gap: 8px; min-height: 20px; }
.unread-dot {
  width: 8px;
  height: 8px;
  flex: 0 0 auto;
  border-radius: 999px;
  background: var(--app-danger);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--app-danger) 16%, transparent);
}
.markdown-body { line-height: 1.7; }
.markdown-body :deep(h1),.markdown-body :deep(h2),.markdown-body :deep(h3) { margin: 12px 0 6px; }
.markdown-body :deep(p) { margin: 6px 0; }
.markdown-body :deep(code) { background: var(--app-code-bg); padding: 2px 6px; border-radius: 4px; }
.markdown-body :deep(pre) { background: var(--app-pre-bg); padding: 10px; border-radius: 8px; overflow:auto; }
.markdown-body :deep(a) { color: var(--el-color-primary); }
@media (max-width: 640px) {
  .notice-head {
    flex-direction: column;
  }
}
</style>
