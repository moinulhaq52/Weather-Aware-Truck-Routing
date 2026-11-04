import { describe, expect, it } from 'vitest'
import { toDatetimeLocal } from '../lib/format'
import {
  defaultValues,
  EXAMPLES,
  MAX_LOAD_LB,
  toRequestBody,
  validateTrip,
  type TripFormValues,
} from './tripForm.logic'

const NOW = new Date('2026-11-03T12:00:00')
const valid = (): TripFormValues => ({
  ...defaultValues(NOW),
  origin: EXAMPLES[0].origin,
  destination: EXAMPLES[0].destination,
})
const inHours = (h: number) => toDatetimeLocal(new Date(NOW.getTime() + h * 3600_000))

describe('validateTrip (mirrors the API rules)', () => {
  it('accepts a complete trip', () => {
    expect(validateTrip(valid(), NOW)).toEqual({})
  })
  it('requires places to be chosen from the list', () => {
    const e = validateTrip({ ...valid(), origin: null, destination: null }, NOW)
    expect(e.origin).toBeTruthy()
    expect(e.destination).toBeTruthy()
  })
  it('rejects identical origin and destination', () => {
    expect(validateTrip({ ...valid(), destination: valid().origin }, NOW).destination).toMatch(
      /differ/,
    )
  })
  it.each([
    [-0.5, undefined], // within the 1 h grace
    [-2, /past/],
    [24 * 7 - 1, undefined],
    [24 * 7 + 1, /7 days/],
  ])('departure %s h from now', (h, msg) => {
    const e = validateTrip({ ...valid(), departure: inHours(h) }, NOW)
    if (msg) expect(e.departure).toMatch(msg)
    else expect(e.departure).toBeUndefined()
  })
  it.each([
    ['', /Enter/],
    ['0', /between/],
    ['1', undefined],
    [String(MAX_LOAD_LB), undefined],
    [String(MAX_LOAD_LB + 1), /between/],
    ['abc', /Enter/],
  ])('load %j', (load, msg) => {
    const e = validateTrip({ ...valid(), loadLb: load }, NOW)
    if (msg) expect(e.loadLb).toMatch(msg)
    else expect(e.loadLb).toBeUndefined()
  })
})

describe('toRequestBody', () => {
  it('sends an ISO timestamp with a UTC offset and numeric load', () => {
    const body = toRequestBody({
      ...valid(),
      loadLb: '35000',
      interval: 10,
      hos: true,
      simulate: true,
    })
    expect(body.departure_time).toMatch(/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d$/)
    expect(new Date(body.departure_time).getTime()).toBe(new Date(valid().departure).getTime())
    expect(body).toMatchObject({
      load_weight_lb: 35000,
      interval_miles: 10,
      hos: true,
      simulate_storm: true,
    })
  })
})

describe('defaultValues', () => {
  it('suggests the next whole hour', () => {
    expect(defaultValues(new Date('2026-11-03T12:20:00')).departure).toBe('2026-11-03T13:00')
  })
})
