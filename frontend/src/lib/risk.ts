import type { LevelKey, RiskLevel } from '../api/types'

export const LEVEL_KEYS: LevelKey[] = ['low', 'moderate', 'high', 'severe', 'no_travel']
export const LEVEL_LABELS = ['Low', 'Moderate', 'High', 'Severe', 'No Travel'] as const

/**
 * Risk colours: a green → yellow → orange → red → purple ramp that stays distinguishable for the
 * common forms of colour-vision deficiency because lightness also decreases monotonically.
 * Labels are always shown next to colours, so colour is never the only cue.
 */
export const LEVEL_COLORS = ['#2f9e5b', '#e8b10b', '#f07316', '#d62828', '#7b2cbf'] as const

/** RGB triples for the heatmap renderer (same ramp). */
export const LEVEL_RGB: [number, number, number][] = LEVEL_COLORS.map(hexToRgb)

export function levelColor(level: RiskLevel | number | null | undefined): string {
  if (level === null || level === undefined || level < 0) return '#8a94a6'
  return LEVEL_COLORS[Math.min(4, Math.max(0, Math.round(level)))]
}

export function levelLabel(level: RiskLevel | number | null | undefined): string {
  if (level === null || level === undefined || level < 0) return 'No data'
  return LEVEL_LABELS[Math.min(4, Math.max(0, Math.round(level)))]
}

export function hexToRgb(hex: string): [number, number, number] {
  const n = parseInt(hex.slice(1), 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

// ---------------------------------------------------------------------------------------------
// Continuous risk index for the heatmap. floor(index) is EXACTLY the backend's risk level
// (backend/trips/domain/risk.py) for the same wind/rain/snow/load, so a heatmap pixel's colour is
// the true level for the weather interpolated at that pixel. The fractional part only exists so
// interpolation is monotone between thresholds.

type Band = { at: number; inclusive: boolean } // reaching `at` enters the next level

const WIND: Band[] = [
  { at: 25, inclusive: true },
  { at: 35, inclusive: true },
  { at: 45, inclusive: true },
  { at: 55, inclusive: true },
]
const RAIN: Band[] = [
  { at: 0.1, inclusive: true },
  { at: 0.25, inclusive: true },
  { at: 0.5, inclusive: true },
  { at: 1.0, inclusive: false }, // No Travel is "> 1.00"
]
const SNOW: Band[] = [
  { at: 0.5, inclusive: true },
  { at: 1.0, inclusive: true },
  { at: 2.0, inclusive: true },
  { at: 3.0, inclusive: false }, // No Travel is "> 3.0"
]
const JUST_BELOW = 0.999

function bandIndex(v: number, bands: Band[]): number {
  let lo = 0
  for (let level = 0; level < bands.length; level++) {
    const b = bands[level]
    const reached = b.inclusive ? v >= b.at : v > b.at
    if (!reached)
      return level + Math.min(JUST_BELOW, Math.max(0, (v - lo) / (b.at - lo)) * JUST_BELOW)
    lo = b.at
  }
  return 4
}

/** Continuous index in [0, 4]; floor() equals the backend risk level including load rules. */
export function riskIndex(
  windMph: number,
  rainInHr: number,
  snowInHr: number,
  loadLb: number,
): number {
  let wind = bandIndex(windMph, WIND)
  if (loadLb > 30_000 && windMph >= 45 && windMph < 55) wind = 4
  else if (loadLb > 40_000 && windMph >= 35 && windMph < 45)
    wind = Math.max(wind, 3 + ((windMph - 35) / 10) * JUST_BELOW)
  return Math.max(wind, bandIndex(rainInHr, RAIN), bandIndex(snowInHr, SNOW))
}
