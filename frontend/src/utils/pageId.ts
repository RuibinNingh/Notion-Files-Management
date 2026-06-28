/** 移植自 C# Utils/NotionPageId.cs：规范化 Notion Page/DataSource ID。
 * 接受 32 位 hex / 带连字符 UUID / 完整 URL，规范化为 8-4-4-4-12 格式。 */
const RE = /([0-9a-f]{32}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/i

export interface NormalizeResult { ok: boolean; value: string; error: string }

export function normalizePageId(input?: string): NormalizeResult {
  const raw = (input || '').replace(/\s/g, '')
  if (!raw) return { ok: false, value: '', error: '请输入目标页面 ID。' }
  const m = RE.exec(raw)
  const candidate = m ? m[1] : raw
  const compact = candidate.replace(/-/g, '')
  if (compact.length !== 32) {
    return { ok: false, value: '', error: 'Page ID 格式不正确：应为 32 位十六进制（可带连字符）。' }
  }
  if (!/^[0-9a-f]{32}$/i.test(compact)) {
    return { ok: false, value: '', error: 'Page ID 格式不正确：只能包含 0-9 / a-f。' }
  }
  const lower = compact.toLowerCase()
  const value = `${lower.slice(0,8)}-${lower.slice(8,12)}-${lower.slice(12,16)}-${lower.slice(16,20)}-${lower.slice(20)}`
  return { ok: true, value, error: '' }
}
