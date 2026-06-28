/** 格式化 MB 为自适应单位 */
export function fmtSize(mb: number): string {
  if (!mb || mb <= 0) return '-'
  if (mb < 1 / 1024) return (mb * 1024 * 1024).toFixed(0) + ' B'
  if (mb < 1) return (mb * 1024).toFixed(1) + ' KB'
  if (mb < 1024) return mb.toFixed(1) + ' MB'
  return (mb / 1024).toFixed(3) + ' GB'
}

export function fmtPct(p: number): string {
  return (p || 0).toFixed(0) + '%'
}

export function fmtEta(s: number): string {
  if (!s || s <= 0) return '-'
  if (s < 60) return s + 's'
  return Math.floor(s / 60) + 'm' + (s % 60) + 's'
}
