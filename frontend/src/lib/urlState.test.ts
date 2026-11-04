import { describe, expect, it } from 'vitest'
import { defaultValues, EXAMPLES } from '../components/tripForm.logic'
import { fromQuery, toQuery } from './urlState'

describe('shareable URL state', () => {
  it('round-trips a trip, including labels with commas', () => {
    const v = {
      ...defaultValues(),
      origin: { ...EXAMPLES[0].origin, label: 'Dallas, Texas' },
      destination: EXAMPLES[0].destination,
      interval: 10 as const,
      hos: true,
      simulate: true,
    }
    const back = fromQuery(`?${toQuery(v)}`, defaultValues())!
    expect(back.origin).toEqual({ ...v.origin })
    expect(back.destination!.lat).toBeCloseTo(v.destination.lat, 5)
    expect(back).toMatchObject({ interval: 10, hos: true, simulate: true, loadLb: v.loadLb })
  })
  it('returns null when the URL has no trip', () => {
    expect(fromQuery('?foo=1', defaultValues())).toBeNull()
  })
  it('ignores invalid coordinates and intervals', () => {
    const v = fromQuery('?from=999,0,X&to=abc&every=30', defaultValues())!
    expect(v.origin).toBeNull()
    expect(v.destination).toBeNull()
    expect(v.interval).toBe(25)
  })
})
