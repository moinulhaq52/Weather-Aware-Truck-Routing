import { memo } from 'react'
import type { Route } from '../api/types'
import { formatDuration, formatMiles, formatTime } from '../lib/format'
import { LEVEL_COLORS, LEVEL_KEYS, LEVEL_LABELS, levelColor, levelLabel } from '../lib/risk'

/** Stacked bar of miles per risk level (always sums to the route length). */
export function RiskBar({ route }: { route: Route }) {
  const s = route.summary
  const total = s.distance_mi || 1
  const parts = LEVEL_KEYS.map((k, i) => ({ k, i, mi: s.miles_by_level[k] })).filter(
    (p) => p.mi > 0,
  )
  const label = parts.map((p) => `${LEVEL_LABELS[p.i]} ${formatMiles(p.mi)}`).join(', ')
  return (
    <div className="riskbar" role="img" aria-label={`Miles by risk: ${label}`}>
      {parts.map((p) => (
        <span
          key={p.k}
          style={{ width: `${(p.mi / total) * 100}%`, background: LEVEL_COLORS[p.i] }}
          title={`${LEVEL_LABELS[p.i]}: ${formatMiles(p.mi)}`}
        />
      ))}
      {s.unknown_miles > 0 && (
        <span
          style={{ width: `${(s.unknown_miles / total) * 100}%`, background: '#c7ced8' }}
          title={`No data: ${formatMiles(s.unknown_miles)}`}
        />
      )}
    </div>
  )
}

/**
 * Extra E2: risk along the route, like an elevation profile. Each checkpoint is a column whose
 * width is the road it represents and whose height is its risk level.
 */
export function RiskStrip({ route }: { route: Route }) {
  const cps = route.checkpoints
  const total = route.summary.distance_mi || 1
  return (
    <svg
      className="riskstrip"
      viewBox="0 0 100 24"
      preserveAspectRatio="none"
      role="img"
      aria-label="Risk along the route"
    >
      {cps.map((cp, i) => {
        const x0 = i === 0 ? 0 : (cps[i - 1].distance_mi + cp.distance_mi) / 2
        const x1 = i === cps.length - 1 ? total : (cp.distance_mi + cps[i + 1].distance_mi) / 2
        const level = cp.risk?.level ?? -1
        const h = level < 0 ? 2 : 4 + level * 5
        return (
          <rect
            key={cp.index}
            x={(x0 / total) * 100}
            width={Math.max(((x1 - x0) / total) * 100, 0.2)}
            y={24 - h}
            height={h}
            fill={levelColor(level)}
          >
            <title>{`Mile ${cp.distance_mi.toFixed(0)} · ${formatTime(cp.eta)} · ${levelLabel(level)}`}</title>
          </rect>
        )
      })}
    </svg>
  )
}

function RouteCardImpl({
  route,
  selected,
  onSelect,
}: {
  route: Route
  selected: boolean
  onSelect: (id: string) => void
}) {
  const s = route.summary
  const notable = route.checkpoints.filter((c) => (c.risk?.level ?? 0) >= 2)
  const stops = route.stops ?? []
  return (
    <li>
      <button
        type="button"
        className={`route-card ${selected ? 'selected' : ''} ${route.recommended ? 'recommended' : ''}`}
        onClick={() => onSelect(route.id)}
        aria-pressed={selected}
      >
        <div className="rc-head">
          <span className="rc-name">{route.name}</span>
          {route.recommended ? (
            <span className="badge rec">★ Recommended</span>
          ) : (
            <span className="badge">#{route.rank}</span>
          )}
          {s.no_travel && <span className="badge danger">No Travel</span>}
        </div>
        {route.via && <div className="rc-via">via {route.via}</div>}
        {route.why_not && <div className="rc-whynot">{route.why_not}</div>}
        <div className="rc-stats">
          <div>
            <strong>{formatMiles(s.distance_mi)}</strong>
            <span>distance</span>
          </div>
          <div>
            <strong>{formatDuration(s.duration_s)}</strong>
            <span>{route.stops?.length ? 'trip time' : 'drive time'}</span>
          </div>
          <div>
            <strong>{formatTime(s.arrival)}</strong>
            <span>arrival</span>
          </div>
        </div>
        <RiskBar route={route} />
        <div className="rc-risk">
          <span>
            Worst: <b style={{ color: levelColor(s.max_level) }}>{levelLabel(s.max_level)}</b>
          </span>
          <span>Avg risk {s.avg_risk.toFixed(2)} / 4</span>
          <span>
            Severe {formatMiles(s.miles_by_level.severe)} · High{' '}
            {formatMiles(s.miles_by_level.high)}
          </span>
        </div>
        {selected && (
          <div className="rc-detail">
            <RiskStrip route={route} />
            <div className="strip-axis">
              <span>Start</span>
              <span>{formatMiles(s.distance_mi)}</span>
            </div>
            {stops.length > 0 && (
              <ul className="stops" aria-label="Hours-of-Service stops">
                {stops.map((st) => (
                  <li key={st.start}>
                    <span className="stop-dot" aria-hidden>
                      {st.kind === 'rest' ? '10h' : '30m'}
                    </span>
                    {st.label} at mile {st.distance_mi.toFixed(0)} · {formatTime(st.start)} –{' '}
                    {formatTime(st.end)}
                  </li>
                ))}
              </ul>
            )}
            {notable.length > 0 ? (
              <ul className="notable">
                {notable.slice(0, 6).map((c) => (
                  <li key={c.index}>
                    <span className="dot" style={{ background: levelColor(c.risk!.level) }} />
                    <span>
                      <b>Mile {c.distance_mi.toFixed(0)}</b> · {formatTime(c.eta)} —{' '}
                      {c.risk!.reasons.join('; ')}
                    </span>
                  </li>
                ))}
                {notable.length > 6 && (
                  <li className="muted">…and {notable.length - 6} more on the map</li>
                )}
              </ul>
            ) : (
              <p className="muted small">No High, Severe or No Travel checkpoints on this route.</p>
            )}
          </div>
        )}
      </button>
    </li>
  )
}

const RouteCard = memo(RouteCardImpl)

function RouteListImpl({
  routes,
  selectedId,
  onSelect,
}: {
  routes: Route[]
  selectedId: string | null
  onSelect: (id: string) => void
}) {
  const ordered = [...routes].sort((a, b) => a.rank - b.rank)
  return (
    <ul className="route-list" aria-label="Route options">
      {ordered.map((r) => (
        <RouteCard key={r.id} route={r} selected={r.id === selectedId} onSelect={onSelect} />
      ))}
    </ul>
  )
}

export const RouteList = memo(RouteListImpl)
