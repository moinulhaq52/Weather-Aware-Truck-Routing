import { describe, expect, it } from 'vitest'
import { formatDuration, formatMiles, formatTime, nextHour, toIsoWithOffset } from './format'

describe('format', () => {
  it.each([
    [59 * 60, '59 min'],
    [3600, '1 h 00 min'],
    [14 * 3600 + 20 * 60, '14 h 20 min'],
  ])('duration %s s -> %s', (s, out) => expect(formatDuration(s)).toBe(out))

  it.each([
    [5.25, '5.3 mi'],
    [42.4, '42 mi'],
    [2070.8, '2,071 mi'],
  ])('miles %s -> %s', (mi, out) => expect(formatMiles(mi)).toBe(out))

  it('formats times in an explicit zone', () => {
    // 2026-11-04T14:00Z is 08:00 in Chicago (CST, UTC-6)
    expect(formatTime(Date.UTC(2026, 10, 4, 14) / 1000, 'America/Chicago')).toBe('Wed 8:00 AM')
  })

  it('serialises local time with its UTC offset', () => {
    const d = new Date(2026, 10, 4, 8, 30)
    const iso = toIsoWithOffset(d)
    expect(new Date(iso).getTime()).toBe(d.getTime())
    expect(iso.startsWith('2026-11-04T08:30:00')).toBe(true)
  })

  it('nextHour rounds up to the next whole hour', () => {
    const n = nextHour(new Date(2026, 10, 4, 8, 1))
    expect([n.getHours(), n.getMinutes()]).toEqual([9, 0])
  })
})
