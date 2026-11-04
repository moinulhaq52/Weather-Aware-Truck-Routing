/**
 * Heatmap frame rendering: turns one forecast hour on the corridor grid into an RGBA image.
 *
 * Why images (RESEARCH §2): the slider must feel instant, so every hour is rendered once (in a Web
 * Worker) and moving the slider just swaps a pre-decoded bitmap on a MapLibre image source.
 *
 * Correctness details:
 * - The image is georeferenced by its four corners. MapLibre draws an image source linearly in
 *   Web Mercator space, so pixel rows are spaced in Mercator y (not latitude) and each row is
 *   converted back to a latitude before sampling. Otherwise the field would drift north/south on
 *   tall corridors.
 * - Values are bilinearly interpolated between grid nodes; nodes without data are skipped and the
 *   remaining weights renormalised, so missing data never reads as "calm".
 * - Risk mode interpolates the *physical* fields (wind, rain, snow) and classifies every pixel
 *   with the same rules as the backend (incl. load), instead of blurring discrete levels. Level
 *   boundaries then follow the weather itself and each pixel shows its true level.
 * - The corridor mask is interpolated too, giving a soft fade at the corridor edge.
 * This module is pure (no DOM) so it runs identically in the worker, the main thread and tests.
 */
import type { HeatmapGrid } from '../api/types'
import { LEVEL_RGB, riskIndex } from '../lib/risk'

export type HeatmapMode = 'risk' | 'wind' | 'rain' | 'snow'

export interface RasterSpec {
  grid: HeatmapGrid
  core: ArrayLike<number> // full grid 0/1, row-major
  nodes: ArrayLike<number> // grid indices with values
}

export interface Raster {
  width: number
  height: number
  /** [lon, lat] corners: top-left, top-right, bottom-right, bottom-left (MapLibre order). */
  corners: [[number, number], [number, number], [number, number], [number, number]]
  rowY: Float32Array // fractional grid row for each pixel row
  colX: Float32Array // fractional grid column for each pixel column
  coreField: Float32Array // core mask resampled per pixel (0..1)
}

type Stop = [value: number, r: number, g: number, b: number, a: number]

/**
 * Colour ramps. Risk uses the shared risk palette (Low is transparent so the basemap stays
 * readable). Wind/rain/snow stops sit on the brief's thresholds, so a colour change on the map
 * matches a risk level change in the table.
 */
export const RAMPS: Record<HeatmapMode, Stop[]> = {
  // Risk pixels use discrete level colours (RISK_ALPHA); this ramp is kept for completeness.
  risk: [
    [0, ...LEVEL_RGB[0], 0],
    [0.6, ...LEVEL_RGB[0], 0],
    [1, ...LEVEL_RGB[1], 0.5],
    [2, ...LEVEL_RGB[2], 0.62],
    [3, ...LEVEL_RGB[3], 0.7],
    [4, ...LEVEL_RGB[4], 0.78],
  ],
  wind: [
    [0, 120, 200, 230, 0],
    [12, 120, 200, 230, 0],
    [25, 64, 160, 220, 0.45],
    [35, 40, 100, 200, 0.58],
    [45, 110, 60, 190, 0.68],
    [55, 150, 30, 150, 0.78],
  ],
  rain: [
    [0, 80, 180, 120, 0],
    [0.02, 80, 180, 120, 0],
    [0.1, 60, 170, 110, 0.45],
    [0.25, 30, 130, 200, 0.58],
    [0.5, 20, 70, 180, 0.68],
    [1, 120, 30, 160, 0.78],
  ],
  snow: [
    [0, 150, 210, 255, 0],
    [0.1, 150, 210, 255, 0],
    [0.5, 120, 190, 255, 0.45],
    [1, 70, 130, 240, 0.58],
    [2, 90, 70, 210, 0.68],
    [3, 150, 40, 180, 0.78],
  ],
}

/** Opacity per risk level: Low is transparent so the basemap stays readable. */
export const RISK_ALPHA = [0, 0.5, 0.62, 0.72, 0.8]

const MAX_SIDE = 640
const PX_PER_CELL = 14

const mercY = (lat: number) => Math.log(Math.tan(Math.PI / 4 + (lat * Math.PI) / 360))
const invMercY = (y: number) => (360 / Math.PI) * Math.atan(Math.exp(y)) - 90

/** Pixel geometry shared by every frame of one plan (computed once). */
export function makeRaster(spec: RasterSpec): Raster {
  const { grid } = spec
  const west = grid.lon0
  const east = grid.lon0 + (grid.n_lon - 1) * grid.dlon
  const south = grid.lat0
  const north = grid.lat0 + (grid.n_lat - 1) * grid.dlat
  const yN = mercY(north)
  const yS = mercY(south)
  const xSpan = ((east - west) * Math.PI) / 180
  const ySpan = yN - yS

  const width = Math.max(2, Math.min(MAX_SIDE, Math.round((grid.n_lon - 1) * PX_PER_CELL)))
  const height = Math.max(2, Math.min(MAX_SIDE * 2, Math.round((width * ySpan) / xSpan)))

  const colX = new Float32Array(width)
  for (let x = 0; x < width; x++) colX[x] = ((x + 0.5) / width) * (grid.n_lon - 1)
  const rowY = new Float32Array(height)
  for (let y = 0; y < height; y++) {
    const lat = invMercY(yN - ((y + 0.5) / height) * ySpan)
    rowY[y] = (lat - grid.lat0) / grid.dlat
  }

  const coreGrid = Float32Array.from(spec.core as ArrayLike<number>)
  const coreField = new Float32Array(width * height)
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const v = sample(coreGrid, grid.n_lat, grid.n_lon, rowY[y], colX[x])
      coreField[y * width + x] = Number.isNaN(v) ? 0 : v
    }
  }

  return {
    width,
    height,
    corners: [
      [west, north],
      [east, north],
      [east, south],
      [west, south],
    ],
    rowY,
    colX,
    coreField,
  }
}

/** Scatter per-node values for one hour into a full grid (NaN where there's no data). */
export function toGrid(
  grid: HeatmapGrid,
  nodes: ArrayLike<number>,
  values: ArrayLike<number | null>,
  missing = -1,
): Float32Array {
  const out = new Float32Array(grid.n_lat * grid.n_lon).fill(NaN)
  for (let i = 0; i < nodes.length; i++) {
    const v = values[i]
    out[nodes[i]] = v === null || v === missing ? NaN : v
  }
  return out
}

/** Bilinear sample at fractional (row, col); NaN-aware with renormalised weights. */
export function sample(
  field: Float32Array,
  nLat: number,
  nLon: number,
  r: number,
  c: number,
): number {
  if (r < 0 || c < 0 || r > nLat - 1 || c > nLon - 1) return NaN
  const r0 = Math.min(Math.floor(r), nLat - 2)
  const c0 = Math.min(Math.floor(c), nLon - 2)
  const fr = r - r0
  const fc = c - c0
  let sum = 0
  let wsum = 0
  const acc = (rr: number, cc: number, w: number) => {
    const v = field[rr * nLon + cc]
    if (w > 0 && !Number.isNaN(v)) {
      sum += v * w
      wsum += w
    }
  }
  acc(r0, c0, (1 - fr) * (1 - fc))
  acc(r0, c0 + 1, (1 - fr) * fc)
  acc(r0 + 1, c0, fr * (1 - fc))
  acc(r0 + 1, c0 + 1, fr * fc)
  return wsum < 0.2 ? NaN : sum / wsum
}

/** Map a value onto a ramp → [r, g, b, a(0..1)]. */
export function rampColor(stops: Stop[], v: number): [number, number, number, number] {
  if (v <= stops[0][0]) return [stops[0][1], stops[0][2], stops[0][3], stops[0][4]]
  for (let i = 1; i < stops.length; i++) {
    if (v <= stops[i][0]) {
      const a = stops[i - 1]
      const b = stops[i]
      const t = (v - a[0]) / (b[0] - a[0])
      return [
        a[1] + (b[1] - a[1]) * t,
        a[2] + (b[2] - a[2]) * t,
        a[3] + (b[3] - a[3]) * t,
        a[4] + (b[4] - a[4]) * t,
      ]
    }
  }
  const last = stops[stops.length - 1]
  return [last[1], last[2], last[3], last[4]]
}

/**
 * Render one frame into an RGBA buffer of raster.width × raster.height.
 * ``fields`` is ``[wind, rain, snow]`` for risk mode, or the single variable otherwise.
 */
export function renderFrame(
  raster: Raster,
  grid: HeatmapGrid,
  fields: Float32Array[],
  mode: HeatmapMode,
  loadLb: number,
  out: Uint8ClampedArray = new Uint8ClampedArray(raster.width * raster.height * 4),
): Uint8ClampedArray {
  const stops = RAMPS[mode]
  const { width, height, rowY, colX, coreField } = raster
  const { n_lat: nLat, n_lon: nLon } = grid
  for (let y = 0; y < height; y++) {
    const r = rowY[y]
    for (let x = 0; x < width; x++) {
      const p = y * width + x
      const mask = coreField[p]
      const o = p * 4
      out[o + 3] = 0
      if (mask <= 0.01) continue
      const c = colX[x]
      let cr: number, cg: number, cb: number, ca: number
      if (mode === 'risk') {
        const w = sample(fields[0], nLat, nLon, r, c)
        const rn = sample(fields[1], nLat, nLon, r, c)
        const sn = sample(fields[2], nLat, nLon, r, c)
        if (Number.isNaN(w) || Number.isNaN(rn) || Number.isNaN(sn)) continue
        const level = Math.min(4, Math.floor(riskIndex(w, rn, sn, loadLb)))
        ;[cr, cg, cb] = LEVEL_RGB[level]
        ca = RISK_ALPHA[level]
      } else {
        const v = sample(fields[0], nLat, nLon, r, c)
        if (Number.isNaN(v)) continue
        ;[cr, cg, cb, ca] = rampColor(stops, v)
      }
      out[o] = cr
      out[o + 1] = cg
      out[o + 2] = cb
      // Smoothstep the mask so the corridor edge fades instead of stepping.
      const m = mask * mask * (3 - 2 * mask)
      out[o + 3] = Math.round(ca * m * 255)
    }
  }
  return out
}

/** Per-hour, per-node value series needed to render a mode (risk needs all three fields). */
export function modeSeries(
  hm: {
    wind_mph: (number | null)[][]
    rain_in_hr: (number | null)[][]
    snow_in_hr: (number | null)[][]
  },
  mode: HeatmapMode,
): (number | null)[][][] {
  switch (mode) {
    case 'risk':
      return [hm.wind_mph, hm.rain_in_hr, hm.snow_in_hr]
    case 'wind':
      return [hm.wind_mph]
    case 'rain':
      return [hm.rain_in_hr]
    case 'snow':
      return [hm.snow_in_hr]
  }
}
