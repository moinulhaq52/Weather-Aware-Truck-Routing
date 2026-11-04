import { useMutation } from '@tanstack/react-query'
import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ApiError, describeValidation, planTrip } from './api/client'
import type { PlanRequestBody, PlanResponse } from './api/types'
import { DepartureWindow } from './components/DepartureWindow'
import { ForecastPanel } from './components/ForecastPanel'
import { RouteList } from './components/RouteList'
import { TripForm } from './components/TripForm'
import {
  defaultValues,
  toRequestBody,
  validateTrip,
  type TripFormValues,
} from './components/tripForm.logic'
import { nearestFrame, useHeatmapFrames } from './hooks/useHeatmapFrames'
import { useMediaQuery } from './hooks/useMediaQuery'
import { formatDateTime } from './lib/format'
import { fromQuery, toQuery } from './lib/urlState'
import type { HeatmapMode } from './map/heatmap'

// The map (MapLibre ~800 KB) loads in its own chunk so the form is interactive immediately.
const MapView = lazy(() => import('./map/MapView').then((m) => ({ default: m.MapView })))

export default function App() {
  const [values, setValues] = useState<TripFormValues>(
    () => fromQuery(window.location.search, defaultValues()) ?? defaultValues(),
  )
  const [plan, setPlan] = useState<PlanResponse | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [hour, setHour] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [mode, setMode] = useState<HeatmapMode>('risk')
  const [opacity, setOpacity] = useState(0.8)
  const [heatVisible, setHeatVisible] = useState(true)
  const abortRef = useRef<AbortController | null>(null)
  const mobile = useMediaQuery('(max-width: 820px)')

  const mutation = useMutation({
    mutationFn: (body: PlanRequestBody) => {
      abortRef.current?.abort()
      const ctrl = new AbortController()
      abortRef.current = ctrl
      return planTrip(body, ctrl.signal)
    },
    onSuccess: (data) => {
      setPlan(data)
      setSelectedId(data.recommended_route_id)
      setHour(0)
      setPlaying(false)
    },
  })

  // Stable callback (mutate is stable; latest values read via ref) so the memoised form
  // doesn't re-render on every forecast-slider step.
  const valuesRef = useRef(values)
  useEffect(() => {
    valuesRef.current = values
  }, [values])
  const { mutate } = mutation
  const submit = useCallback(
    (body: PlanRequestBody) => {
      window.history.replaceState(null, '', `?${toQuery(valuesRef.current)}`)
      mutate(body)
    },
    [mutate],
  )

  // A shared link with a valid trip plans immediately.
  useEffect(() => {
    if (window.location.search && Object.keys(validateTrip(values)).length === 0) {
      mutation.mutate(toRequestBody(values))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- run once on mount
  }, [])

  const heatmap = plan?.heatmap ?? null
  const { frames, corners, rendered, total } = useHeatmapFrames(
    heatmap,
    mode,
    hour,
    plan?.request.load_weight_lb ?? 0,
  )
  const frame = useMemo(() => nearestFrame(frames, hour), [frames, hour])
  const truckTime = heatmap ? heatmap.start_time + hour * 3600 : null
  const padding = useMemo(
    () =>
      mobile
        ? { top: 40, bottom: 170, left: 30, right: 30 }
        : { top: 60, bottom: 190, left: 60, right: 70 },
    [mobile],
  )

  const error = mutation.error
  const errorLines = error instanceof ApiError ? describeValidation(error.details) : []

  return (
    <div className="app">
      <aside className="sidebar">
        <header className="brand">
          <div className="logo" aria-hidden>
            ⛟
          </div>
          <div>
            <h1>Truck Weather Router</h1>
            <p>Safest route using the forecast at your ETA, not the weather now.</p>
          </div>
        </header>

        <TripForm
          values={values}
          onChange={setValues}
          onSubmit={submit}
          busy={mutation.isPending}
        />

        {error && (
          <div className="alert error" role="alert">
            <strong>{error instanceof ApiError ? error.message : 'Something went wrong.'}</strong>
            {errorLines.length > 0 && (
              <ul>
                {errorLines.map((l) => (
                  <li key={l}>{l}</li>
                ))}
              </ul>
            )}
          </div>
        )}

        {plan && (
          <section className="results" aria-live="polite">
            {plan.meta.weather_source === 'simulated' && (
              <div className="alert simulated" role="note">
                <strong>Simulated weather.</strong> These results use a synthetic demo storm, not a
                real forecast.
              </div>
            )}
            <div className="recommendation">
              <div className="rec-title">Recommended: {plan.recommended_route_id}</div>
              <p>{plan.recommendation_reason}</p>
              <p className="muted small">
                Departing {formatDateTime(plan.request.departure_time)} ·{' '}
                {plan.request.load_weight_lb.toLocaleString('en-US')} lb · weather every{' '}
                {plan.request.interval_miles} mi
              </p>
            </div>
            {plan.warnings
              .filter((w) => !w.startsWith('Weather is SIMULATED'))
              .map((w) => (
                <div key={w} className="alert warn">
                  {w}
                </div>
              ))}
            <RouteList routes={plan.routes} selectedId={selectedId} onSelect={setSelectedId} />
            {plan.departure_options && plan.departure_options.length > 0 && (
              <DepartureWindow options={plan.departure_options} advice={plan.departure_advice} />
            )}
          </section>
        )}

        {!plan && !mutation.isPending && !error && (
          <section className="how">
            <h2>How it works</h2>
            <ol>
              <li>Three route options are generated between your places.</li>
              <li>
                Each route is sampled every 10, 25 or 50 miles; each checkpoint gets the truck's
                ETA.
              </li>
              <li>
                The forecast valid at that ETA is classified Low → No Travel, with heavier loads
                penalised in high wind.
              </li>
              <li>
                The route with the fewest Severe, then High miles, then lowest average risk, then
                shortest time wins.
              </li>
            </ol>
          </section>
        )}

        <footer className="credits muted small">
          Routing © OSRM / OpenStreetMap · Weather © Open-Meteo (CC BY 4.0) · Map © OpenFreeMap
        </footer>
      </aside>

      <main className="map-area">
        <div className="map-canvas">
          <Suspense fallback={<div className="map-loading">Loading map…</div>}>
            <MapView
              plan={plan}
              selectedId={selectedId}
              onSelectRoute={setSelectedId}
              heatFrame={frame}
              heatCorners={corners}
              heatOpacity={opacity}
              heatVisible={heatVisible}
              truckTime={truckTime}
              padding={padding}
            />
          </Suspense>
          {mutation.isPending && (
            <div className="map-busy" role="status">
              <span className="spinner" aria-hidden /> Fetching routes and forecasts at each ETA…
            </div>
          )}
        </div>
        {plan && heatmap && (
          <ForecastPanel
            hour={hour}
            hours={heatmap.hours}
            startTime={heatmap.start_time}
            onHour={setHour}
            playing={playing}
            onPlaying={setPlaying}
            mode={mode}
            onMode={setMode}
            opacity={opacity}
            onOpacity={setOpacity}
            visible={heatVisible}
            onVisible={setHeatVisible}
            rendered={Math.min(rendered, total)}
          />
        )}
      </main>
    </div>
  )
}
