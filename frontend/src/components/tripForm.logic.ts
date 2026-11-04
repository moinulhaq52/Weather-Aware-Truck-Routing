// Trip form state, validation and request mapping (kept free of React for unit testing).
import type { Interval, Place, PlanRequestBody } from '../api/types'
import { nextHour, toDatetimeLocal, toIsoWithOffset } from '../lib/format'

export interface TripFormValues {
  origin: Place | null
  destination: Place | null
  departure: string // datetime-local value (browser local time)
  loadLb: string
  interval: Interval
  hos: boolean
  simulate: boolean // extra E3: synthetic storm (demo) instead of the live forecast
}

export type TripFormErrors = Partial<
  Record<'origin' | 'destination' | 'departure' | 'loadLb', string>
>

// Mirrors the server-side validation (backend/trips/api/serializers.py).
export const MAX_LOAD_LB = 80_000
const PAST_GRACE_MS = 60 * 60 * 1000
const MAX_AHEAD_MS = 7 * 24 * 60 * 60 * 1000

export function validateTrip(v: TripFormValues, now = new Date()): TripFormErrors {
  const e: TripFormErrors = {}
  if (!v.origin) e.origin = 'Choose a starting place from the list.'
  if (!v.destination) e.destination = 'Choose a destination from the list.'
  if (
    v.origin &&
    v.destination &&
    v.origin.lat === v.destination.lat &&
    v.origin.lon === v.destination.lon
  )
    e.destination = 'Destination must differ from the origin.'
  const dep = new Date(v.departure)
  if (!v.departure || Number.isNaN(dep.getTime())) e.departure = 'Enter a departure date and time.'
  else if (dep.getTime() < now.getTime() - PAST_GRACE_MS) e.departure = 'Departure is in the past.'
  else if (dep.getTime() > now.getTime() + MAX_AHEAD_MS)
    e.departure = 'Forecasts only reach 7 days ahead.'
  const load = Number(v.loadLb)
  if (!v.loadLb.trim() || !Number.isFinite(load)) e.loadLb = 'Enter the load weight in pounds.'
  else if (load < 1 || load > MAX_LOAD_LB)
    e.loadLb = `Load must be between 1 and ${MAX_LOAD_LB.toLocaleString('en-US')} lb.`
  return e
}

export function toRequestBody(v: TripFormValues): PlanRequestBody {
  return {
    origin: v.origin!,
    destination: v.destination!,
    departure_time: toIsoWithOffset(new Date(v.departure)),
    load_weight_lb: Number(v.loadLb),
    interval_miles: v.interval,
    hos: v.hos,
    simulate_storm: v.simulate,
  }
}

export function defaultValues(now = new Date()): TripFormValues {
  return {
    origin: null,
    destination: null,
    departure: toDatetimeLocal(nextHour(now)),
    loadLb: '38000',
    interval: 25,
    hos: false,
    simulate: false,
  }
}

export const EXAMPLES: { name: string; origin: Place; destination: Place }[] = [
  {
    name: 'Dallas → Denver',
    origin: { label: 'Dallas, Texas', lat: 32.7767, lon: -96.797 },
    destination: { label: 'Denver, Colorado', lat: 39.7392, lon: -104.9903 },
  },
  {
    name: 'Chicago → Atlanta',
    origin: { label: 'Chicago, Illinois', lat: 41.8781, lon: -87.6298 },
    destination: { label: 'Atlanta, Georgia', lat: 33.749, lon: -84.388 },
  },
  {
    name: 'Seattle → Boise',
    origin: { label: 'Seattle, Washington', lat: 47.6062, lon: -122.3321 },
    destination: { label: 'Boise, Idaho', lat: 43.615, lon: -116.2023 },
  },
]
