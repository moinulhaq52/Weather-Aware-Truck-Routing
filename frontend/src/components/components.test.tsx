import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Place, Route } from '../api/types'
import { ForecastPanel } from './ForecastPanel'
import { PlaceInput } from './PlaceInput'
import { RouteList } from './RouteList'
import { TripForm } from './TripForm'
import { defaultValues, type TripFormValues } from './tripForm.logic'

afterEach(() => vi.restoreAllMocks())

function withQuery(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
}

function FormHarness({ onSubmit }: { onSubmit: (b: unknown) => void }) {
  const [v, setV] = useState<TripFormValues>(defaultValues())
  return <TripForm values={v} onChange={setV} onSubmit={onSubmit} busy={false} />
}

describe('TripForm', () => {
  it('shows validation errors instead of submitting an incomplete trip', async () => {
    const onSubmit = vi.fn()
    render(withQuery(<FormHarness onSubmit={onSubmit} />))
    await userEvent.click(screen.getByRole('button', { name: 'Find safest route' }))
    expect(onSubmit).not.toHaveBeenCalled()
    expect(screen.getByText('Choose a starting place from the list.')).toBeInTheDocument()
  })

  it('submits a valid request after picking an example trip', async () => {
    const onSubmit = vi.fn()
    render(withQuery(<FormHarness onSubmit={onSubmit} />))
    await userEvent.click(screen.getByRole('button', { name: 'Dallas → Denver' }))
    await userEvent.click(screen.getByRole('radio', { name: '10 mi' }))
    await userEvent.click(screen.getByRole('button', { name: '45k' }))
    await userEvent.click(screen.getByRole('button', { name: 'Find safest route' }))
    expect(onSubmit).toHaveBeenCalledTimes(1)
    expect(onSubmit.mock.calls[0][0]).toMatchObject({
      origin: { label: 'Dallas, Texas' },
      destination: { label: 'Denver, Colorado' },
      load_weight_lb: 45000,
      interval_miles: 10,
    })
  })

  it('swaps origin and destination', async () => {
    render(withQuery(<FormHarness onSubmit={vi.fn()} />))
    await userEvent.click(screen.getByRole('button', { name: 'Dallas → Denver' }))
    await userEvent.click(screen.getByRole('button', { name: 'Swap origin and destination' }))
    expect(screen.getByLabelText('Origin')).toHaveValue('Denver, Colorado')
  })
})

describe('PlaceInput', () => {
  it('searches after typing and selects a result with the keyboard', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({ results: [{ label: 'Denver, Colorado', lat: 39.74, lon: -104.99 }] }),
      ),
    )
    let chosen: Place | null = null
    render(
      withQuery(<PlaceInput label="Destination" value={null} onChange={(p) => (chosen = p)} />),
    )
    const input = screen.getByLabelText('Destination')
    await userEvent.type(input, 'denv')
    const option = await screen.findByRole(
      'option',
      { name: 'Denver, Colorado' },
      { timeout: 2000 },
    )
    expect(option).toBeInTheDocument()
    fireEvent.keyDown(input, { key: 'Enter' })
    await waitFor(() =>
      expect(chosen).toEqual({ label: 'Denver, Colorado', lat: 39.74, lon: -104.99 }),
    )
  })
})

const route = (id: string, rank: number, extra: Partial<Route> = {}): Route => ({
  id,
  name: id,
  via: 'I 25',
  source: 'native',
  rank,
  recommended: rank === 1,
  geometry: [
    [-100, 30],
    [-100, 31],
  ],
  summary: {
    distance_mi: 100,
    duration_s: 7200,
    departure: 1_800_000_000,
    arrival: 1_800_007_200,
    miles_by_level: { low: 80, moderate: 0, high: 20, severe: 0, no_travel: 0 },
    unknown_miles: 0,
    avg_risk: 0.4,
    max_level: 2,
    no_travel: false,
  },
  checkpoints: [],
  why_not: rank === 1 ? null : 'More High miles than Route A: 20 mi vs 0.0 mi.',
  stops: [],
  ...extra,
})

describe('RouteList', () => {
  it('orders by rank, marks the recommendation and explains the others', async () => {
    const onSelect = vi.fn()
    render(
      <RouteList
        routes={[route('Route B', 2), route('Route A', 1)]}
        selectedId="Route A"
        onSelect={onSelect}
      />,
    )
    const cards = screen.getAllByRole('button')
    expect(within(cards[0]).getByText('★ Recommended')).toBeInTheDocument()
    expect(within(cards[1]).getByText(/More High miles than Route A/)).toBeInTheDocument()
    await userEvent.click(cards[1])
    expect(onSelect).toHaveBeenCalledWith('Route B')
  })

  it('flags No Travel routes', () => {
    const r = route('Route A', 1)
    r.summary.no_travel = true
    render(<RouteList routes={[r]} selectedId={null} onSelect={vi.fn()} />)
    expect(screen.getByText('No Travel')).toBeInTheDocument()
  })
})

describe('ForecastPanel', () => {
  it('labels the hour and reports slider moves', () => {
    const onHour = vi.fn()
    const onPlaying = vi.fn()
    render(
      <ForecastPanel
        hour={6}
        hours={49}
        startTime={1_800_000_000}
        onHour={onHour}
        playing={false}
        onPlaying={onPlaying}
        mode="risk"
        onMode={vi.fn()}
        opacity={0.8}
        onOpacity={vi.fn()}
        visible
        onVisible={vi.fn()}
        rendered={49}
      />,
    )
    expect(screen.getByText('+6 h')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Forecast hour after departure'), {
      target: { value: '12' },
    })
    expect(onHour).toHaveBeenCalledWith(12)
    expect(onPlaying).toHaveBeenCalledWith(false) // dragging stops playback
    expect(screen.getByText('No Travel')).toBeInTheDocument() // risk legend
  })
})
