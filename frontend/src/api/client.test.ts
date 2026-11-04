import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, describeValidation, geocode, planTrip } from './client'

const respond = (status: number, body: unknown) =>
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify(body), { status }))

afterEach(() => vi.restoreAllMocks())

describe('api client', () => {
  it('returns geocode results', async () => {
    respond(200, { results: [{ label: 'Denver', lat: 39.7, lon: -105 }] })
    expect(await geocode('denver')).toEqual([{ label: 'Denver', lat: 39.7, lon: -105 }])
  })
  it('maps API errors to ApiError with code and message', async () => {
    respond(422, { error: { code: 'no_route', message: 'No drivable route.' } })
    const err = await planTrip({} as never).catch((e) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(err).toMatchObject({ status: 422, code: 'no_route', message: 'No drivable route.' })
  })
  it('handles non-JSON error pages', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response('<html>Bad gateway</html>', { status: 502 }),
    )
    await expect(geocode('x')).rejects.toMatchObject({ status: 502, code: 'http_error' })
  })
  it('reports network failures clearly', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new TypeError('Failed to fetch'))
    await expect(geocode('x')).rejects.toMatchObject({ code: 'network' })
  })
  it('flattens nested validation details', () => {
    expect(
      describeValidation({ load_weight_lb: ['Too big.'], origin: { lat: ['Out of range.'] } }),
    ).toEqual(['load_weight_lb: Too big.', 'origin.lat: Out of range.'])
  })
})
