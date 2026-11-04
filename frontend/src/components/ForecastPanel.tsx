import { useEffect, type Dispatch, type SetStateAction } from 'react'
import type { HeatmapMode } from '../map/heatmap'
import { RAMPS } from '../map/heatmap'
import { formatTime } from '../lib/format'
import { LEVEL_COLORS, LEVEL_LABELS } from '../lib/risk'

interface Props {
  hour: number
  hours: number
  startTime: number
  onHour: Dispatch<SetStateAction<number>>
  playing: boolean
  onPlaying: (p: boolean) => void
  mode: HeatmapMode
  onMode: (m: HeatmapMode) => void
  opacity: number
  onOpacity: (o: number) => void
  visible: boolean
  onVisible: (v: boolean) => void
  rendered: number
}

const MODES: { id: HeatmapMode; label: string }[] = [
  { id: 'risk', label: 'Risk' },
  { id: 'wind', label: 'Wind' },
  { id: 'rain', label: 'Rain' },
  { id: 'snow', label: 'Snow' },
]

const UNITS: Record<Exclude<HeatmapMode, 'risk'>, string> = {
  wind: 'mph',
  rain: 'in/hr',
  snow: 'in/hr',
}
const PLAY_MS_PER_HOUR = 350

/** 0–48 h forecast slider with playback, layer selection and a legend. */
export function ForecastPanel(p: Props) {
  const max = p.hours - 1
  const { playing, onHour } = p

  // Playback advances one forecast hour per tick and loops.
  useEffect(() => {
    if (!playing) return
    const t = setInterval(() => onHour((h) => (h + 1) % (max + 1)), PLAY_MS_PER_HOUR)
    return () => clearInterval(t)
  }, [playing, max, onHour])

  const t = p.startTime + p.hour * 3600
  return (
    <section className="forecast-panel" aria-label="Weather forecast timeline">
      <div className="fp-top">
        <button
          type="button"
          className="play"
          onClick={() => p.onPlaying(!p.playing)}
          aria-label={p.playing ? 'Pause forecast animation' : 'Play forecast animation'}
        >
          {p.playing ? '❚❚' : '▶'}
        </button>
        <div className="fp-time" aria-live="polite">
          <strong>+{p.hour} h</strong>
          <span>{formatTime(t)}</span>
        </div>
        <div className="segmented small" role="radiogroup" aria-label="Heatmap layer">
          {MODES.map((m) => (
            <label key={m.id} className={p.mode === m.id ? 'on' : ''}>
              <input
                type="radio"
                name="hm-mode"
                checked={p.mode === m.id}
                onChange={() => p.onMode(m.id)}
              />
              {m.label}
            </label>
          ))}
        </div>
        <label className="toggle small">
          <input
            type="checkbox"
            checked={p.visible}
            onChange={(e) => p.onVisible(e.target.checked)}
          />
          <span>Heatmap</span>
        </label>
      </div>

      <div className="fp-slider">
        <input
          type="range"
          min={0}
          max={max}
          step={1}
          value={p.hour}
          onChange={(e) => {
            p.onPlaying(false)
            p.onHour(Number(e.target.value))
          }}
          aria-label="Forecast hour after departure"
          aria-valuetext={`${p.hour} hours after departure, ${formatTime(t)}`}
        />
        <div className="fp-ticks" aria-hidden>
          {[0, 12, 24, 36, 48].map((h) => (
            <span key={h} style={{ left: `${(h / max) * 100}%` }}>
              {h === 0 ? 'Depart' : `+${h}h`}
            </span>
          ))}
        </div>
      </div>

      <div className="fp-bottom">
        <Legend mode={p.mode} />
        <label className="opacity">
          <span className="muted">Opacity</span>
          <input
            type="range"
            min={0.2}
            max={1}
            step={0.05}
            value={p.opacity}
            onChange={(e) => p.onOpacity(Number(e.target.value))}
          />
        </label>
        {p.rendered < p.hours && (
          <span className="muted small">
            Rendering {p.rendered}/{p.hours}…
          </span>
        )}
      </div>
    </section>
  )
}

export function Legend({ mode }: { mode: HeatmapMode }) {
  if (mode === 'risk') {
    return (
      <ul className="legend" aria-label="Risk levels">
        {LEVEL_LABELS.map((l, i) => (
          <li key={l}>
            <span className="swatch" style={{ background: LEVEL_COLORS[i] }} />
            {l}
          </li>
        ))}
      </ul>
    )
  }
  // Stops from index 2 on sit exactly on the brief's thresholds and are evenly spaced in the
  // gradient, so each label lines up with its colour.
  const stops = RAMPS[mode].slice(2)
  const gradient = stops
    .map((s) => `rgba(${s[1]},${s[2]},${s[3]},${Math.max(s[4], 0.15)})`)
    .join(',')
  return (
    <div className="legend-ramp">
      <div className="ramp" style={{ background: `linear-gradient(90deg, ${gradient})` }} />
      <div className="ramp-labels">
        {stops.map((s) => (
          <span key={s[0]}>{s[0]}</span>
        ))}
        <span className="muted">{UNITS[mode]}</span>
      </div>
    </div>
  )
}
