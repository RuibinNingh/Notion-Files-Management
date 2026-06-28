<template>
  <div class="login-wrap">
    <el-card class="login-card panel" shadow="never">
      <div class="login-brand">
        <img src="/logo.png" alt="NFM logo" class="logo" />
        <div>
          <h2>Notion Files Management</h2>
          <p class="muted">请输入访问密码</p>
        </div>
      </div>
      <el-form @submit.prevent="onLogin">
        <el-form-item>
          <el-input
            v-model="password"
            type="password"
            placeholder="访问密码"
            show-password
            size="large"
          />
        </el-form-item>
        <el-button type="primary" size="large" native-type="submit" :loading="loading" class="login-submit">
          登录
        </el-button>
      </el-form>
      <div class="login-foot muted">本地服务使用共享访问密码保护。</div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import { errMsg } from '@/api/client'

const password = ref('')
const loading = ref(false)
const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

async function onLogin() {
  if (loading.value) return
  if (!password.value) return
  loading.value = true
  try {
    await auth.login(password.value)
    const redirect = (route.query.redirect as string) || '/'
    await router.push(redirect)
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-submit {
  width: 100%;
}
.login-foot {
  margin-top: 14px;
  text-align: center;
}
</style>
