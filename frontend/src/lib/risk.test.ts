import { describe, expect, it } from 'vitest'
import { levelColor, levelLabel, riskIndex } from './risk'

const lvl = (w: number, r: number, s: number, load = 20_000) => Math.floor(riskIndex(w, r, s, load))

// Same boundary cases as backend/trips/tests/test_risk.py: the two implementations must agree.
describe('riskIndex matches the backend rules', () => {
  it.each([
    [24.9, 0],
    [25, 1],
    [34.9, 1],
    [35, 2],
    [44.99, 2],
    [45, 3],
    [54.9, 3],
    [55, 4],
    [120, 4],
  ])('wind %s mph -> level %s', (w, expected) => expect(lvl(w, 0, 0)).toBe(expected))

  it.each([
    [0.099, 0],
    [0.1, 1],
    [0.249, 1],
    [0.25, 2],
    [0.499, 2],
    [0.5, 3],
    [1.0, 3],
    [1.001, 4],
  ])('rain %s in/hr -> level %s', (r, expected) => expect(lvl(0, r, 0)).toBe(expected))

  it.each([
    [0.49, 0],
    [0.5, 1],
    [0.99, 1],
    [1.0, 2],
    [1.99, 2],
    [2.0, 3],
    [3.0, 3],
    [3.01, 4],
  ])('snow %s in/hr -> level %s', (s, expected) => expect(lvl(0, 0, s)).toBe(expected))

  it.each([
    [45, 30_000, 3],
    [45, 30_001, 4],
    [54.9, 45_000, 4],
    [44.9, 45_000, 3],
    [35, 40_000, 2],
    [35, 40_001, 3],
    [34.9, 80_000, 1],
    [40, 10_000, 2],
    [50, 10_000, 3],
  ])('load rules: wind %s mph, %s lb -> level %s', (w, load, expected) =>
    expect(lvl(w, 0, 0, load)).toBe(expected),
  )

  it('takes the worst condition', () => {
    expect(lvl(26, 0.3, 2.5)).toBe(3)
  })

  it('is monotone in each input', () => {
    let prev = -1
    for (let w = 0; w <= 70; w += 0.5) {
      const v = riskIndex(w, 0, 0, 20_000)
      expect(v).toBeGreaterThanOrEqual(prev)
      prev = v
    }
  })
})

describe('labels and colours', () => {
  it('handles missing data', () => {
    expect(levelLabel(-1)).toBe('No data')
    expect(levelLabel(null)).toBe('No data')
    expect(levelColor(4)).toBe('#7b2cbf')
  })
})
