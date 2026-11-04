import type { Checkpoint, Route } from '../api/types'
import { formatMiles, formatTime } from '../lib/format'
import { levelColor, levelLabel } from '../lib/risk'

/** Hover card for one checkpoint: ETA, forecast values and why it got its risk level (E2). */
export function CheckpointPopup({
  route,
  checkpoint: cp,
}: {
  route: Route
  checkpoint: Checkpoint
}) {
  const level = cp.risk?.level ?? -1
  const isLast = cp.index === route.checkpoints.length - 1
  return (
    <div className="popup">
      <div className="popup-head">
        <span className="popup-route">{route.name}</span>
        <span className="muted">
          {cp.index === 0
            ? 'Origin'
            : isLast
              ? 'Destination'
              : `Mile ${formatMiles(cp.distance_mi)}`}
        </span>
      </div>
      <div className="popup-eta">
        ETA <strong>{formatTime(cp.eta)}</strong>
      </div>
      <span className="pill" style={{ background: levelColor(level) }}>
        {levelLabel(level)}
      </span>
      {cp.weather ? (
        <dl className="popup-wx">
          <dt>Wind</dt>
          <dd>
            {cp.weather.wind_mph.toFixed(0)} mph
            {cp.weather.gust_mph !== null && (
              <span className="muted"> (gusts {cp.weather.gust_mph.toFixed(0)})</span>
            )}
          </dd>
          <dt>Rain</dt>
          <dd>{cp.weather.rain_in_hr.toFixed(2)} in/hr</dd>
          <dt>Snow</dt>
          <dd>{cp.weather.snow_in_hr.toFixed(2)} in/hr</dd>
        </dl>
      ) : (
        <p className="muted">No forecast available for this time and place.</p>
      )}
      {cp.risk && (
        <ul className="popup-reasons">
          {cp.risk.reasons.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
      )}
      {cp.weather && (
        <div className="muted popup-foot">
          Forecast hour ending {formatTime(cp.weather.valid_time)}
        </div>
      )}
    </div>
  )
}
