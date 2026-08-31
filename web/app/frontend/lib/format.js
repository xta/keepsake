// Presentation helpers. Deliberately forgiving: every field these touch is
// optional in SPEC.md, so each one has to render something sane for null.

export function bytes(n) {
  if (n == null) return null
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let value = Number(n)
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit++
  }
  return `${value < 10 && unit > 0 ? value.toFixed(1) : Math.round(value)} ${units[unit]}`
}

export function duration(seconds) {
  if (seconds == null) return null
  const total = Math.round(Number(seconds))
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  const pad = (n) => String(n).padStart(2, '0')
  return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`
}

// SPEC allows `recorded_at` to be a plain date OR a full RFC 3339 timestamp,
// and that difference is real information -- "that day" versus "that moment".
// So a date-only value is never dressed up with a time it does not have.
export function recordedAt(value) {
  if (!value) return null
  const dateOnly = /^\d{4}-\d{2}-\d{2}$/.test(value)
  const date = new Date(dateOnly ? `${value}T12:00:00Z` : value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleDateString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric',
    timeZone: dateOnly ? 'UTC' : undefined,
  })
}

export function timeAgo(iso) {
  if (!iso) return null
  const then = new Date(iso)
  if (Number.isNaN(then.getTime())) return null
  const seconds = Math.round((Date.now() - then.getTime()) / 1000)
  const steps = [
    [60, 'second'], [60, 'minute'], [24, 'hour'], [7, 'day'], [4.35, 'week'], [12, 'month'],
  ]
  let value = seconds
  let unit = 'second'
  for (const [size, name] of steps) {
    if (Math.abs(value) < size) { unit = name; break }
    value = Math.round(value / size)
    unit = name
  }
  if (unit === 'second' && Math.abs(value) < 45) return 'just now'
  const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' })
  return rtf.format(-value, unit)
}
