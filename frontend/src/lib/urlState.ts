// Shareable links: trip inputs round-trip through the query string.
import type { Interval, Place } from '../api/types'
import type { TripFormValues } from '../components/tripForm.logic'

const enc = (p: Place) => `${p.lat.toFixed(5)},${p.lon.toFixed(5)},${p.label}`

function dec(s: string | null): Place | null {
  if (!s) return null
  const [lat, lon, ...rest] = s.split(',')
  const la = Number(lat)
  const lo = Number(lon)
  if (!Number.isFinite(la) || !Number.isFinite(lo) || Math.abs(la) > 90 || Math.abs(lo) > 180)
    return null
  return { lat: la, lon: lo, label: rest.join(',') || `${la.toFixed(3)}, ${lo.toFixed(3)}` }
}

export function toQuery(v: TripFormValues): string {
  const q = new URLSearchParams()
  if (v.origin) q.set('from', enc(v.origin))
  if (v.destination) q.set('to', enc(v.destination))
  q.set('depart', v.departure)
  q.set('load', v.loadLb)
  q.set('every', String(v.interval))
  if (v.hos) q.set('hos', '1')
  if (v.simulate) q.set('storm', '1')
  return q.toString()
}

/** Parse a query string onto defaults; returns null when there is no trip in the URL. */
export function fromQuery(search: string, defaults: TripFormValues): TripFormValues | null {
  const q = new URLSearchParams(search)
  if (!q.has('from') && !q.has('to')) return null
  const every = Number(q.get('every'))
  return {
    origin: dec(q.get('from')),
    destination: dec(q.get('to')),
    departure: q.get('depart') || defaults.departure,
    loadLb: q.get('load') || defaults.loadLb,
    interval: ([10, 25, 50].includes(every) ? every : defaults.interval) as Interval,
    hos: q.get('hos') === '1',
    simulate: q.get('storm') === '1',
  }
}
