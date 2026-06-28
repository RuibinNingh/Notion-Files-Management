import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const routes = [
  { path: '/login', name: 'login', component: () => import('@/views/Login.vue'), meta: { public: true } },
  {
    path: '/',
    component: () => import('@/layouts/MainLayout.vue'),
    children: [
      { path: '', name: 'dashboard', component: () => import('@/views/Dashboard.vue') },
      { path: 'notice', name: 'notice', component: () => import('@/views/Notice.vue') },
      { path: 'tasks', name: 'tasks', component: () => import('@/views/Tasks.vue') },
      { path: 'cache', name: 'cache', component: () => import('@/views/Cache.vue') },
      { path: 'upload', name: 'upload', component: () => import('@/views/Upload.vue') },
      { path: 'download', name: 'download', component: () => import('@/views/Download.vue') },
      { path: 'tools', name: 'tools', component: () => import('@/views/Tools.vue') },
      { path: 'settings', name: 'settings', component: () => import('@/views/Settings.vue') },
    ],
  },
]

const router = createRouter({ history: createWebHistory(), routes })

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (to.meta.public) return true
  if (!auth.isLoggedIn) await auth.check()
  if (!auth.isLoggedIn) return { name: 'login', query: { redirect: to.fullPath } }
  return true
})

export default router
