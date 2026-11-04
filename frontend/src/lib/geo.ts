// Minimal spherical geometry for display purposes ([lon, lat] positions, miles).

export type Position = [number, number]

const R_MI = 3958.8
const rad = (d: number) => (d * Math.PI) / 180

export function haversineMi(a: Position, b: Position): number {
  const dLat = rad(b[1] - a[1])
  const dLon = rad(b[0] - a[0])
  const h =
    Math.sin(dLat / 2) ** 2 + Math.cos(rad(a[1])) * Math.cos(rad(b[1])) * Math.sin(dLon / 2) ** 2
  return 2 * R_MI * Math.asin(Math.min(1, Math.sqrt(h)))
}

// Route geometries are immutable once received, so their cumulative distances are cached by
// identity (the forecast slider asks for them on every hour step).
const cumulativeCache = new WeakMap<Position[], number[]>()

export function cumulativeMi(line: Position[]): number[] {
  const cached = cumulativeCache.get(line)
  if (cached) return cached
  const out = computeCumulative(line)
  cumulativeCache.set(line, out)
  return out
}

function computeCumulative(line: Position[]): number[] {
  const out = [0]
  for (let i = 1; i < line.length; i++) out.push(out[i - 1] + haversineMi(line[i - 1], line[i]))
  return out
}

function segmentAt(cum: number[], d: number): number {
  // Binary search for i with cum[i] <= d <= cum[i+1].
  let lo = 0
  let hi = cum.length - 2
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1
    if (cum[mid] <= d) lo = mid
    else hi = mid - 1
  }
  return Math.max(0, lo)
}

export function pointAtDistance(line: Position[], cum: number[], d: number): Position {
  if (line.length === 1) return line[0]
  const dd = Math.min(Math.max(d, 0), cum[cum.length - 1])
  const i = segmentAt(cum, dd)
  const seg = cum[i + 1] - cum[i]
  const f = seg > 0 ? (dd - cum[i]) / seg : 0
  return [
    line[i][0] + (line[i + 1][0] - line[i][0]) * f,
    line[i][1] + (line[i + 1][1] - line[i][1]) * f,
  ]
}

/** Sub-line between distances d0 and d1 (miles along the line). */
export function sliceByDistance(
  line: Position[],
  cum: number[],
  d0: number,
  d1: number,
): Position[] {
  if (d1 <= d0) return [pointAtDistance(line, cum, d0)]
  const out: Position[] = [pointAtDistance(line, cum, d0)]
  const i0 = segmentAt(cum, d0)
  const i1 = segmentAt(cum, d1)
  for (let i = i0 + 1; i <= i1; i++) out.push(line[i])
  out.push(pointAtDistance(line, cum, d1))
  return out
}

export function bounds(points: Position[]): [[number, number], [number, number]] {
  let w = Infinity
  let s = Infinity
  let e = -Infinity
  let n = -Infinity
  for (const [x, y] of points) {
    if (x < w) w = x
    if (x > e) e = x
    if (y < s) s = y
    if (y > n) n = y
  }
  return [
    [w, s],
    [e, n],
  ]
}
