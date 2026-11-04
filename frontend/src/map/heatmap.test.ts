import { describe, expect, it } from 'vitest'
import type { HeatmapGrid } from '../api/types'
import { makeRaster, rampColor, RAMPS, renderFrame, sample, toGrid } from './heatmap'

const grid: HeatmapGrid = { lat0: 30, lon0: -100, dlat: 0.5, dlon: 0.5, n_lat: 3, n_lon: 3 }
const allCore = [1, 1, 1, 1, 1, 1, 1, 1, 1]
const allNodes = [0, 1, 2, 3, 4, 5, 6, 7, 8]

describe('sample', () => {
  const field = Float32Array.from([0, 0, 0, 0, 4, 0, 0, 0, 0])
  it('returns node values exactly at nodes', () => {
    expect(sample(field, 3, 3, 1, 1)).toBe(4)
    expect(sample(field, 3, 3, 0, 0)).toBe(0)
  })
  it('interpolates bilinearly between nodes', () => {
    expect(sample(field, 3, 3, 0.5, 0.5)).toBeCloseTo(1) // one of four corners is 4
    expect(sample(field, 3, 3, 1, 0.5)).toBeCloseTo(2)
  })
  it('skips missing nodes instead of treating them as zero', () => {
    const f = Float32Array.from([NaN, 2, NaN, NaN, 2, NaN, NaN, NaN, NaN])
    expect(sample(f, 3, 3, 0.5, 0.5)).toBeCloseTo(2)
  })
  it('returns NaN outside the grid', () => {
    expect(sample(field, 3, 3, -0.1, 1)).toBeNaN()
  })
})

describe('toGrid', () => {
  it('scatters node values and marks -1 / null as missing', () => {
    const g = toGrid(grid, [0, 4, 8], [3, -1, null])
    expect(g[0]).toBe(3)
    expect(g[4]).toBeNaN()
    expect(g[8]).toBeNaN()
    expect(g[1]).toBeNaN()
  })
})

describe('rampColor', () => {
  it('Low risk is fully transparent so the basemap stays readable', () => {
    expect(rampColor(RAMPS.risk, 0)[3]).toBe(0)
  })
  it('alpha increases with risk', () => {
    const a = [1, 2, 3, 4].map((v) => rampColor(RAMPS.risk, v)[3])
    expect(a).toEqual([...a].sort((x, y) => x - y))
  })
  it('wind ramp changes colour at the brief thresholds', () => {
    expect(rampColor(RAMPS.wind, 24)[3]).toBeLessThan(rampColor(RAMPS.wind, 25)[3] + 1e-9)
    expect(rampColor(RAMPS.wind, 55)).toEqual(rampColor(RAMPS.wind, 80)) // clamps above max
  })
})

describe('makeRaster', () => {
  it('georeferences corners in MapLibre order (TL, TR, BR, BL)', () => {
    const r = makeRaster({ grid, core: allCore, nodes: allNodes })
    expect(r.corners).toEqual([
      [-100, 31],
      [-99, 31],
      [-99, 30],
      [-100, 30],
    ])
  })
  it('spaces rows in Mercator, so row 0 maps near the north edge', () => {
    const tall: HeatmapGrid = { lat0: 25, lon0: -100, dlat: 1, dlon: 1, n_lat: 25, n_lon: 3 }
    const r = makeRaster({ grid: tall, core: new Array(75).fill(1), nodes: [] })
    expect(r.rowY[0]).toBeGreaterThan(23.5)
    expect(r.rowY[r.height - 1]).toBeLessThan(0.5)
    // Mercator: the latitude midpoint is below the vertical pixel midpoint.
    expect(r.rowY[Math.floor(r.height / 2)]).toBeGreaterThan(12)
  })
})

describe('renderFrame', () => {
  it('is transparent outside the corridor and coloured inside it', () => {
    const core = [0, 0, 0, 0, 1, 0, 0, 0, 0]
    const r = makeRaster({ grid, core, nodes: allNodes })
    const wind = toGrid(grid, allNodes, new Array(9).fill(50)) // Severe wind everywhere
    const zero = toGrid(grid, allNodes, new Array(9).fill(0))
    const px = renderFrame(r, grid, [wind, zero, zero], 'risk', 20_000)
    const at = (x: number, y: number) => px[(y * r.width + x) * 4 + 3]
    expect(at(0, 0)).toBe(0) // corner is outside the corridor
    expect(at(Math.floor(r.width / 2), Math.floor(r.height / 2))).toBeGreaterThan(100)
  })
  it('renders all-calm weather as fully transparent', () => {
    const r = makeRaster({ grid, core: allCore, nodes: allNodes })
    const zero = toGrid(grid, allNodes, new Array(9).fill(0))
    const px = renderFrame(r, grid, [zero, zero, zero], 'risk', 20_000)
    expect(px.filter((_, i) => i % 4 === 3).every((a) => a === 0)).toBe(true)
  })
})

describe('risk mode classifies interpolated weather per pixel', () => {
  it('applies the load rule: 47 mph is Severe light, No Travel heavy', () => {
    const r = makeRaster({ grid, core: allCore, nodes: allNodes })
    const wind = toGrid(grid, allNodes, new Array(9).fill(47))
    const zero = toGrid(grid, allNodes, new Array(9).fill(0))
    const centre = (load: number) => {
      const px = renderFrame(r, grid, [wind, zero, zero], 'risk', load)
      const o = (Math.floor(r.height / 2) * r.width + Math.floor(r.width / 2)) * 4
      return [px[o], px[o + 1], px[o + 2]]
    }
    expect(centre(20_000)).toEqual([0xd6, 0x28, 0x28]) // Severe red
    expect(centre(35_000)).toEqual([0x7b, 0x2c, 0xbf]) // No Travel purple
  })

  it('shows missing data as transparent, not Low', () => {
    const r = makeRaster({ grid, core: allCore, nodes: allNodes })
    const nan = toGrid(grid, allNodes, new Array(9).fill(null))
    const px = renderFrame(r, grid, [nan, nan, nan], 'risk', 20_000)
    expect(px.filter((_, i) => i % 4 === 3).every((a) => a === 0)).toBe(true)
  })
})
