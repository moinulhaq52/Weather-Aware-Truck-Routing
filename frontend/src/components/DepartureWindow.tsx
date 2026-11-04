import { memo } from 'react'
import type { DepartureOption } from '../api/types'
import { formatTime } from '../lib/format'
import { LEVEL_COLORS, LEVEL_KEYS, LEVEL_LABELS } from '../lib/risk'

/**
 * Extra E4: how risk changes if the driver leaves later. The backend re-scores every route for
 * each later start using forecasts it already fetched, and picks the best start with the same
 * ranking as the route recommendation; this component only presents it.
 */
function DepartureWindowImpl({
  options,
  advice,
}: {
  options: DepartureOption[]
  advice?: string | null
}) {
  return (
    <section className="depwin" aria-label="Departure time options">
      <h3>Best time to leave</h3>
      {advice && <p className="small">{advice}</p>}
      <table>
        <thead>
          <tr>
            <th scope="col">Leave</th>
            <th scope="col">Safest route</th>
            <th scope="col">Risk mix</th>
          </tr>
        </thead>
        <tbody>
          {options.map((o) => (
            <tr
              key={o.offset_h}
              className={o.best ? 'best' : undefined}
              aria-current={o.best ? 'true' : undefined}
            >
              <td>
                {o.offset_h === 0 ? 'Planned' : `+${o.offset_h} h`}
                <span className="muted"> {formatTime(o.departure)}</span>
                {o.best && <span className="badge rec small-badge">Best</span>}
              </td>
              <td>{o.route_id}</td>
              <td>
                <MiniBar option={o} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}

export const DepartureWindow = memo(DepartureWindowImpl)

function MiniBar({ option }: { option: DepartureOption }) {
  const total = LEVEL_KEYS.reduce((s, k) => s + option.miles_by_level[k], 0) || 1
  const label = LEVEL_KEYS.filter((k) => option.miles_by_level[k] > 0)
    .map((k) => `${LEVEL_LABELS[LEVEL_KEYS.indexOf(k)]} ${option.miles_by_level[k].toFixed(0)} mi`)
    .join(', ')
  return (
    <div className="riskbar mini" role="img" aria-label={label}>
      {LEVEL_KEYS.map((k, i) =>
        option.miles_by_level[k] > 0 ? (
          <span
            key={k}
            style={{
              width: `${(option.miles_by_level[k] / total) * 100}%`,
              background: LEVEL_COLORS[i],
            }}
          />
        ) : null,
      )}
    </div>
  )
}
