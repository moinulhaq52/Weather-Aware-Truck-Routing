// Presentation helpers. All times arrive as UTC epoch seconds and are shown in the viewer's
// local time zone (or an explicit one, for tests).

export function formatDuration(seconds: number): string {
  const totalMin = Math.round(seconds / 60)
  const h = Math.floor(totalMin / 60)
  const m = totalMin % 60
  if (h === 0) return `${m} min`
  return `${h} h ${String(m).padStart(2, '0')} min`
}

export function formatMiles(mi: number): string {
  if (mi >= 100) return `${Math.round(mi).toLocaleString('en-US')} mi`
  if (mi >= 10) return `${mi.toFixed(0)} mi`
  return `${mi.toFixed(1)} mi`
}

// Intl.DateTimeFormat construction is expensive (it showed up in slider profiles), so formatters
// are cached per (kind, time zone).
const formatters = new Map<string, Intl.DateTimeFormat>()
function formatter(kind: 'time' | 'datetime', timeZone?: string): Intl.DateTimeFormat {
  const key = `${kind}|${timeZone ?? ''}`
  let f = formatters.get(key)
  if (!f) {
    f = new Intl.DateTimeFormat(
      'en-US',
      kind === 'time'
        ? { weekday: 'short', hour: 'numeric', minute: '2-digit', timeZone }
        : {
            weekday: 'short',
            month: 'short',
            day: 'numeric',
            hour: 'numeric',
            minute: '2-digit',
            timeZone,
            timeZoneName: 'short',
          },
    )
    formatters.set(key, f)
  }
  return f
}

export function formatTime(epoch: number, timeZone?: string): string {
  return formatter('time', timeZone).format(new Date(epoch * 1000))
}

export function formatDateTime(epoch: number, timeZone?: string): string {
  return formatter('datetime', timeZone).format(new Date(epoch * 1000))
}

/** `<input type="datetime-local">` value for a Date, in local time. */
export function toDatetimeLocal(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/** ISO-8601 with the local UTC offset, e.g. 2026-11-04T08:00:00-06:00 (what the API requires). */
export function toIsoWithOffset(d: Date): string {
  const pad = (n: number) => String(Math.floor(Math.abs(n))).padStart(2, '0')
  const off = -d.getTimezoneOffset()
  const sign = off >= 0 ? '+' : '-'
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
    `T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}` +
    `${sign}${pad(off / 60)}:${pad(off % 60)}`
  )
}

/** The next whole hour from `now` (default departure suggestion). */
export function nextHour(now = new Date()): Date {
  const d = new Date(now)
  d.setMinutes(0, 0, 0)
  d.setHours(d.getHours() + 1)
  return d
}
