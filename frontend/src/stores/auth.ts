import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '../api/client'

export const useAuthStore = defineStore('auth', () => {
  const isLoggedIn = ref(false)
  const checking = ref(false)

  async function check() {
    checking.value = true
    try {
      const r = await api.get('/api/auth/check')
      isLoggedIn.value = r.data.auth === true
    } catch {
      isLoggedIn.value = false
    } finally {
      checking.value = false
    }
  }

  async function login(password: string) {
    await api.post('/api/auth/login', { password })
    isLoggedIn.value = true
  }

  async function logout() {
    try { await api.post('/api/auth/logout') } catch {}
    isLoggedIn.value = false
  }

  return { isLoggedIn, checking, check, login, logout }
})
