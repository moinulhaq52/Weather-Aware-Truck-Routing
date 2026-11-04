import { memo, useState } from 'react'
import type { Interval, PlanRequestBody } from '../api/types'
import { PlaceInput } from './PlaceInput'
import {
  EXAMPLES,
  MAX_LOAD_LB,
  toRequestBody,
  validateTrip,
  type TripFormValues,
} from './tripForm.logic'

const LOAD_PRESETS = [
  { lb: 20_000, hint: 'Light' },
  { lb: 35_000, hint: '>30k: 45–54 mph wind = No Travel' },
  { lb: 45_000, hint: '>40k: 35–44 mph wind = Severe' },
]

interface Props {
  values: TripFormValues
  onChange: (v: TripFormValues) => void
  onSubmit: (body: PlanRequestBody) => void
  busy: boolean
}

function TripFormImpl({ values: v, onChange, onSubmit, busy }: Props) {
  const [touched, setTouched] = useState(false)
  const errors = validateTrip(v)
  const shown = touched ? errors : {}
  const set = <K extends keyof TripFormValues>(k: K, x: TripFormValues[K]) =>
    onChange({ ...v, [k]: x })

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    setTouched(true)
    if (Object.keys(errors).length === 0) onSubmit(toRequestBody(v))
  }

  return (
    <form className="trip-form" onSubmit={submit} noValidate aria-label="Trip details">
      <div className="examples" aria-label="Example trips">
        <span className="muted">Try:</span>
        {EXAMPLES.map((x) => (
          <button
            key={x.name}
            type="button"
            className="chip"
            onClick={() => onChange({ ...v, origin: x.origin, destination: x.destination })}
          >
            {x.name}
          </button>
        ))}
      </div>

      <div className="od">
        <PlaceInput
          label="Origin"
          value={v.origin}
          onChange={(p) => set('origin', p)}
          placeholder="City or address"
          error={shown.origin}
        />
        <button
          type="button"
          className="swap"
          title="Swap origin and destination"
          aria-label="Swap origin and destination"
          onClick={() => onChange({ ...v, origin: v.destination, destination: v.origin })}
        >
          ⇅
        </button>
        <PlaceInput
          label="Destination"
          value={v.destination}
          onChange={(p) => set('destination', p)}
          placeholder="City or address"
          error={shown.destination}
        />
      </div>

      <div className="row">
        <div className="field">
          <label htmlFor="departure">Departure</label>
          <input
            id="departure"
            type="datetime-local"
            value={v.departure}
            onChange={(e) => set('departure', e.target.value)}
            aria-invalid={Boolean(shown.departure)}
          />
          {shown.departure && <div className="field-error">{shown.departure}</div>}
        </div>
        <div className="field">
          <label htmlFor="load">Load weight</label>
          <div className="suffix-input">
            <input
              id="load"
              type="number"
              inputMode="numeric"
              min={1}
              max={MAX_LOAD_LB}
              step={500}
              value={v.loadLb}
              onChange={(e) => set('loadLb', e.target.value)}
              aria-invalid={Boolean(shown.loadLb)}
            />
            <span>lb</span>
          </div>
          {shown.loadLb && <div className="field-error">{shown.loadLb}</div>}
        </div>
      </div>
      <div className="load-presets" aria-label="Load presets">
        {LOAD_PRESETS.map((p) => (
          <button
            key={p.lb}
            type="button"
            className={`chip ${Number(v.loadLb) === p.lb ? 'on' : ''}`}
            title={p.hint}
            onClick={() => set('loadLb', String(p.lb))}
          >
            {(p.lb / 1000).toFixed(0)}k
          </button>
        ))}
      </div>

      <div className="row">
        <fieldset className="field segmented">
          <legend>Weather every</legend>
          {([10, 25, 50] as Interval[]).map((i) => (
            <label key={i} className={v.interval === i ? 'on' : ''}>
              <input
                type="radio"
                name="interval"
                value={i}
                checked={v.interval === i}
                onChange={() => set('interval', i)}
              />
              {i} mi
            </label>
          ))}
        </fieldset>
        <label
          className="toggle"
          title="Insert FMCSA Hours-of-Service breaks: 30 min after 8 h driving, 10 h off after 11 h"
        >
          <input type="checkbox" checked={v.hos} onChange={(e) => set('hos', e.target.checked)} />
          <span>HOS breaks</span>
        </label>
      </div>

      <label
        className="toggle demo-toggle"
        title="Replaces the live forecast with a synthetic storm placed across the trip, so you can see how risk, load rules and the recommendation react. Clearly labelled; never a real forecast."
      >
        <input
          type="checkbox"
          checked={v.simulate}
          onChange={(e) => set('simulate', e.target.checked)}
        />
        <span>
          Simulate a storm <span className="muted">(demo: not a real forecast)</span>
        </span>
      </label>

      <button type="submit" className="primary" disabled={busy}>
        {busy ? (
          <>
            <span className="spinner" aria-hidden /> Checking routes & forecasts…
          </>
        ) : (
          'Find safest route'
        )}
      </button>
    </form>
  )
}

/** Memoised: the forecast slider re-renders App every hour step; the form must not follow. */
export const TripForm = memo(TripFormImpl)
