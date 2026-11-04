/**
 * Pure builders from API data to GeoJSON for MapLibre sources. They are memoised by callers, so
 * sources are only re-uploaded to the GPU when the underlying plan or selection actually changes.
 */
import type { Feature, FeatureCollection, LineString, Point } from 'geojson'
import type { Checkpoint, Place, RestStop, Route } from '../api/types'
import { cumulativeMi, pointAtDistance, sliceByDistance, type Position } from '../lib/geo'
import { levelColor } from '../lib/risk'

export type RouteProps = { id: string; name: string; recommended: boolean; selected: boolean }
export type CheckpointProps = {
  routeId: string
  index: number
  level: number
  color: string
  selected: boolean
}

export function routesFC(
  routes: Route[],
  selectedId: string | null,
): FeatureCollection<LineString, RouteProps> {
  // Selected route last, so it draws on top of the others.
  const ordered = [...routes].sort(
    (a, b) => Number(a.id === selectedId) - Number(b.id === selectedId),
  )
  return {
    type: 'FeatureCollection',
    features: ordered.map((r) => ({
      type: 'Feature',
      properties: {
        id: r.id,
        name: r.name,
        recommended: r.recommended,
        selected: r.id === selectedId,
      },
      geometry: { type: 'LineString', coordinates: r.geometry },
    })),
  }
}

/**
 * The route split into stretches coloured by the risk of the checkpoint that "owns" them: half-way
 * to the neighbouring checkpoints, which is the same rule the backend uses to count miles, so the
 * colours agree with the per-level mileage in the route card.
 */
export function riskSegmentsFC(
  route: Route | undefined,
): FeatureCollection<LineString, { color: string; level: number }> {
  if (!route || route.geometry.length < 2) return { type: 'FeatureCollection', features: [] }
  const line = route.geometry as Position[]
  const cum = cumulativeMi(line)
  const total = cum[cum.length - 1]
  const scale = route.summary.distance_mi > 0 ? total / route.summary.distance_mi : 1
  const cps = route.checkpoints
  const features: Feature<LineString, { color: string; level: number }>[] = []
  cps.forEach((cp, i) => {
    const d = cp.distance_mi * scale
    const d0 = i === 0 ? 0 : (cps[i - 1].distance_mi * scale + d) / 2
    const d1 = i === cps.length - 1 ? total : (d + cps[i + 1].distance_mi * scale) / 2
    if (d1 - d0 <= 0) return
    const level = cp.risk?.level ?? -1
    features.push({
      type: 'Feature',
      properties: { color: levelColor(level), level },
      geometry: { type: 'LineString', coordinates: sliceByDistance(line, cum, d0, d1) },
    })
  })
  return { type: 'FeatureCollection', features }
}

/** Stable numeric feature id (needed for MapLibre feature-state hover). */
export const checkpointFeatureId = (routeIdx: number, cpIdx: number) => routeIdx * 10_000 + cpIdx

export function checkpointsFC(
  routes: Route[],
  selectedId: string | null,
): FeatureCollection<Point, CheckpointProps> {
  const features: Feature<Point, CheckpointProps>[] = []
  routes.forEach((r, ri) => {
    r.checkpoints.forEach((cp) => {
      const level = cp.risk?.level ?? -1
      features.push({
        type: 'Feature',
        id: checkpointFeatureId(ri, cp.index),
        properties: {
          routeId: r.id,
          index: cp.index,
          level,
          color: levelColor(level),
          selected: r.id === selectedId,
        },
        geometry: { type: 'Point', coordinates: [cp.lon, cp.lat] },
      })
    })
  })
  // Selected route's checkpoints on top.
  features.sort((a, b) => Number(a.properties.selected) - Number(b.properties.selected))
  return { type: 'FeatureCollection', features }
}

export function endpointsFC(
  origin: Place,
  destination: Place,
): FeatureCollection<Point, { role: string; label: string }> {
  const short = (l: string) => l.split(',')[0]
  return {
    type: 'FeatureCollection',
    features: [
      {
        type: 'Feature',
        properties: { role: 'origin', label: short(origin.label) || 'Origin' },
        geometry: { type: 'Point', coordinates: [origin.lon, origin.lat] },
      },
      {
        type: 'Feature',
        properties: { role: 'destination', label: short(destination.label) || 'Destination' },
        geometry: { type: 'Point', coordinates: [destination.lon, destination.lat] },
      },
    ],
  }
}

/**
 * Clock time minus the time spent stopped so far (extra E5): constant while the truck is parked,
 * so interpolating in this "driving time" keeps the truck at the stop instead of creeping forward.
 */
export function drivingTime(t: number, stops: RestStop[] = []): number {
  let parked = 0
  for (const s of stops) parked += Math.min(Math.max(t - s.start, 0), s.end - s.start)
  return t - parked
}

/** Distance along the route (miles) at epoch `t`, interpolated between checkpoint ETAs. */
export function distanceAtTime(
  cps: Checkpoint[],
  t: number,
  stops: RestStop[] = [],
): number | null {
  if (cps.length === 0 || t < cps[0].eta || t > cps[cps.length - 1].eta) return null
  const dt = drivingTime(t, stops)
  for (let i = 1; i < cps.length; i++) {
    if (t <= cps[i].eta) {
      const a = cps[i - 1]
      const b = cps[i]
      const ta = drivingTime(a.eta, stops)
      const span = drivingTime(b.eta, stops) - ta
      return a.distance_mi + (span > 0 ? ((dt - ta) / span) * (b.distance_mi - a.distance_mi) : 0)
    }
  }
  return cps[cps.length - 1].distance_mi
}

/** Extra E5: rest-stop markers for the selected route. */
export function stopsFC(
  route: Route | undefined,
): FeatureCollection<Point, { kind: string; label: string }> {
  return {
    type: 'FeatureCollection',
    features: (route?.stops ?? []).map((s) => ({
      type: 'Feature',
      properties: { kind: s.kind, label: s.kind === 'rest' ? '10h' : '30m' },
      geometry: { type: 'Point', coordinates: [s.lon, s.lat] },
    })),
  }
}

/**
 * Extra E1: where each truck is at epoch `t`, following the road geometry (not straight chords
 * between checkpoints). Trucks that have arrived stay parked at the destination, flagged so the
 * map can dim them.
 */
export type TruckProps = {
  id: string
  name: string
  selected: boolean
  level: number
  arrived: boolean
}

export function trucksFC(
  routes: Route[],
  t: number,
  selectedId: string | null,
): FeatureCollection<Point, TruckProps> {
  const features: Feature<Point, TruckProps>[] = []
  for (const r of routes) {
    const cps = r.checkpoints
    if (cps.length === 0 || r.geometry.length < 2 || t < cps[0].eta) continue
    const arrived = t > cps[cps.length - 1].eta
    const d = arrived ? r.summary.distance_mi : (distanceAtTime(cps, t, r.stops) ?? 0)
    const line = r.geometry as Position[]
    const cum = cumulativeMi(line)
    const scale = r.summary.distance_mi > 0 ? cum[cum.length - 1] / r.summary.distance_mi : 1
    // Risk at the truck's location = the checkpoint owning that stretch.
    let nearest = cps[0]
    for (const cp of cps)
      if (Math.abs(cp.distance_mi - d) < Math.abs(nearest.distance_mi - d)) nearest = cp
    features.push({
      type: 'Feature',
      properties: {
        id: r.id,
        name: r.name,
        selected: r.id === selectedId,
        level: nearest.risk?.level ?? -1,
        arrived,
      },
      geometry: { type: 'Point', coordinates: pointAtDistance(line, cum, d * scale) },
    })
  }
  return { type: 'FeatureCollection', features }
}
