import { describe, expect, it } from 'vitest'
import { nearestFrame, renderOrder } from './useHeatmapFrames'

describe('renderOrder', () => {
  it('renders the current hour first, then outward', () => {
    expect(renderOrder(7, 3)).toEqual([3, 4, 2, 5, 1, 6, 0])
    expect(renderOrder(4, 0)).toEqual([0, 1, 2, 3])
  })
  it('covers every hour exactly once', () => {
    const order = renderOrder(49, 30)
    expect([...order].sort((a, b) => a - b)).toEqual(Array.from({ length: 49 }, (_, i) => i))
  })
})

describe('nearestFrame', () => {
  it('falls back to the closest rendered frame so the map never flashes empty', () => {
    const a = document.createElement('canvas')
    const b = document.createElement('canvas')
    expect(nearestFrame([null, a, null, null, b], 3)).toBe(b)
    expect(nearestFrame([null, a, null, null, b], 2)).toBe(a)
    expect(nearestFrame([null, null], 1)).toBeNull()
  })
})
