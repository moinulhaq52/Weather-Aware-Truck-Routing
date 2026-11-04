import type { ApiErrorBody, Place, PlanRequestBody, PlanResponse } from './types'

/** Error carrying the API's machine-readable code and a user-facing message. */
export class ApiError extends Error {
  readonly code: string
  readonly status: number
  readonly details?: Record<string, unknown>

  constructor(status: number, code: string, message: string, details?: Record<string, unknown>) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.details = details
  }
}

const BASE = import.meta.env.VITE_API_BASE ?? ''

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${BASE}${path}`, {
      ...init,
      headers: { Accept: 'application/json', ...(init.headers ?? {}) },
    })
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') throw err
    throw new ApiError(0, 'network', 'Cannot reach the server. Check your connection.')
  }
  const text = await res.text()
  let data: unknown = null
  try {
    data = text ? JSON.parse(text) : null
  } catch {
    // fall through: non-JSON error page
  }
  if (!res.ok) {
    const body = data as ApiErrorBody | null
    throw new ApiError(
      res.status,
      body?.error?.code ?? 'http_error',
      body?.error?.message ?? `Request failed (HTTP ${res.status}).`,
      body?.error?.details,
    )
  }
  return data as T
}

export function geocode(q: string, signal?: AbortSignal): Promise<Place[]> {
  return request<{ results: Place[] }>(`/api/geocode?q=${encodeURIComponent(q)}`, { signal }).then(
    (r) => r.results,
  )
}

export function planTrip(body: PlanRequestBody, signal?: AbortSignal): Promise<PlanResponse> {
  return request<PlanResponse>('/api/plan', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  })
}

/** Flatten DRF validation details ({field: [msg]} or nested) into "field: message" strings. */
export function describeValidation(details?: Record<string, unknown>): string[] {
  if (!details) return []
  const out: string[] = []
  const walk = (prefix: string, v: unknown) => {
    if (Array.isArray(v))
      v.forEach((x) => (typeof x === 'string' ? out.push(`${prefix}: ${x}`) : walk(prefix, x)))
    else if (v && typeof v === 'object')
      Object.entries(v).forEach(([k, x]) => walk(prefix ? `${prefix}.${k}` : k, x))
    else if (typeof v === 'string') out.push(`${prefix}: ${v}`)
  }
  walk('', details)
  return out
}
