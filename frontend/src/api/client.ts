import axios from 'axios'

export const api = axios.create({
  baseURL: '',
  withCredentials: true,
  timeout: 0,
})

// 错误提示统一由调用方（页面 catch）负责，避免拦截器和页面同时弹错。
// 拦截器仅处理 401 跳登录。
api.interceptors.response.use(
  (res) => res,
  (err) => {
    const status = err?.response?.status
    if (status === 401) {
      if (!location.pathname.startsWith('/login')) {
        location.href = '/login?redirect=' + encodeURIComponent(location.pathname + location.hash)
      }
    }
    return Promise.reject(err)
  },
)

/** 解析错误信息为字符串 */
export function errMsg(e: any): string {
  const d = e?.response?.data?.detail
  if (typeof d === 'string') return d
  if (d) return JSON.stringify(d)
  return e?.message || '未知错误'
}
