import { describe, expect, it } from 'vitest'
import type { Checkpoint, Route } from '../api/types'
import { cumulativeMi, haversineMi } from '../lib/geo'
import { distanceAtTime, drivingTime, riskSegmentsFC, routesFC, stopsFC, trucksFC } from './geojson'

const T0 = 1_800_000_000
// A due-north route: 0.1° of latitude per vertex (~6.9 mi), 10 vertices.
const geometry: [number, number][] = Array.from({ length: 11 }, (_, i) => [-100, 30 + i * 0.1])
const total = cumulativeMi(geometry)[10]

function cp(index: number, d: number, level: number | null): Checkpoint {
  return {
    index,
    distance_mi: d,
    lat: 30 + (d / total) * 1,
    lon: -100,
    eta: T0 + d * 60, // 60 mph
    weather: null,
    risk:
      level === null
        ? null
        : {
            level: level as 0,
            label: '',
            wind_level: 0,
            rain_level: 0,
            snow_level: 0,
            load_rule: null,
            reasons: [],
          },
  }
}

function route(id: string, levels: (number | null)[]): Route {
  const n = levels.length
  return {
    id,
    name: id,
    via: '',
    source: 'native',
    rank: 1,
    recommended: id === 'Route A',
    geometry,
    summary: {
      distance_mi: total,
      duration_s: total * 60,
      departure: T0,
      arrival: T0 + total * 60,
      miles_by_level: { low: total, moderate: 0, high: 0, severe: 0, no_travel: 0 },
      unknown_miles: 0,
      avg_risk: 0,
      max_level: 0,
      no_travel: false,
    },
    checkpoints: levels.map((l, i) => cp(i, (i / (n - 1)) * total, l)),
    why_not: null,
    stops: [],
  }
}

describe('riskSegmentsFC', () => {
  it('splits the route half-way between checkpoints and colours by risk', () => {
    const fc = riskSegmentsFC(route('Route A', [0, 3, 0]))
    expect(fc.features.map((f) => f.properties.level)).toEqual([0, 3, 0])
    const lengths = fc.features.map((f) =>
      cumulativeMi(f.geometry.coordinates as [number, number][]).at(-1)!,
    )
    // Owned stretches: quarter, half, quarter of the route.
    expect(lengths[0]).toBeCloseTo(total / 4, 1)
    expect(lengths[1]).toBeCloseTo(total / 2, 1)
    expect(lengths.reduce((a, b) => a + b, 0)).toBeCloseTo(total, 1)
  })
  it('marks checkpoints without a forecast as no data', () => {
    const fc = riskSegmentsFC(route('Route A', [0, null]))
    expect(fc.features[1].properties.level).toBe(-1)
  })
})

describe('routesFC', () => {
  it('draws the selected route last (on top)', () => {
    const fc = routesFC([route('Route A', [0, 0]), route('Route B', [0, 0])], 'Route A')
    expect(fc.features.at(-1)!.properties.id).toBe('Route A')
  })
})

describe('trucks (extra E1)', () => {
  const r = route('Route A', [0, 2, 4])
  it('interpolates distance from checkpoint ETAs', () => {
    expect(distanceAtTime(r.checkpoints, T0 + 30 * 60)).toBeCloseTo(30, 5)
    expect(distanceAtTime(r.checkpoints, T0 - 1)).toBeNull()
  })
  it('places the truck on the road at the slider time with the local risk', () => {
    const fc = trucksFC([r], T0 + (total / 2) * 60, null)
    const [lon, lat] = fc.features[0].geometry.coordinates
    expect(lon).toBe(-100)
    expect(haversineMi([-100, 30], [lon, lat])).toBeCloseTo(total / 2, 1)
    expect(fc.features[0].properties.level).toBe(2)
    expect(fc.features[0].properties.arrived).toBe(false)
  })
  it('parks arrived trucks at the destination', () => {
    const fc = trucksFC([r], T0 + 10 * 3600, null)
    expect(fc.features[0].properties.arrived).toBe(true)
    expect(fc.features[0].geometry.coordinates[1]).toBeCloseTo(31, 5)
  })
})

describe('Hours-of-Service stops (extra E5)', () => {
  const stop = {
    kind: 'break' as const,
    label: '30-min break',
    distance_mi: 30,
    lat: 30.4,
    lon: -100,
    start: T0 + 30 * 60,
    end: T0 + 60 * 60,
  }
  it('driving time stands still during a stop', () => {
    expect(drivingTime(T0 + 40 * 60, [stop])).toBe(T0 + 30 * 60)
    expect(drivingTime(T0 + 90 * 60, [stop])).toBe(T0 + 60 * 60)
  })
  it('keeps the truck parked at the stop', () => {
    // Checkpoints after the stop are 30 min later than without it.
    const r = route('Route A', [0, 0, 0])
    r.stops = [stop]
    r.checkpoints = r.checkpoints.map((c) => (c.distance_mi > 30 ? { ...c, eta: c.eta + 1800 } : c))
    const during1 = distanceAtTime(r.checkpoints, T0 + 35 * 60, r.stops)!
    const during2 = distanceAtTime(r.checkpoints, T0 + 55 * 60, r.stops)!
    expect(during1).toBeCloseTo(30, 5)
    expect(during2).toBeCloseTo(30, 5)
    expect(distanceAtTime(r.checkpoints, T0 + 70 * 60, r.stops)!).toBeCloseTo(40, 5)
  })
  it('builds stop markers for the selected route', () => {
    const r = route('Route A', [0, 0])
    r.stops = [stop]
    expect(stopsFC(r).features[0].properties.label).toBe('30m')
    expect(stopsFC(undefined).features).toEqual([])
  })
})
