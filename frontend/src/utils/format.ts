export const fmtPct = (v: number | undefined, decimals = 1) =>
  v == null ? '—' : `${(v * 100).toFixed(decimals)}%`

export const fmtNum = (v: number | undefined, decimals = 2) =>
  v == null ? '—' : v.toFixed(decimals)

export const fmtVnd = (v: number | undefined) => {
  if (v == null) return '—'
  if (Math.abs(v) >= 1e9) return `${(v / 1e9).toFixed(1)}B`
  if (Math.abs(v) >= 1e6) return `${(v / 1e6).toFixed(1)}M`
  return v.toLocaleString()
}
