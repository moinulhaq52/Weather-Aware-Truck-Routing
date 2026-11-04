// Mirrors the Django API contract (backend/trips/services/planner.py, docs/PLAN.md §1).
// Times are UTC epoch seconds; coordinates in route geometry are GeoJSON [lon, lat].

export type RiskLevel = 0 | 1 | 2 | 3 | 4 // Low, Moderate, High, Severe, No Travel
export type LevelKey = 'low' | 'moderate' | 'high' | 'severe' | 'no_travel'
export type Interval = 10 | 25 | 50

export interface Place {
  label: string
  lat: number
  lon: number
  kind?: string
}

export interface PlanRequestBody {
  origin: Place
  destination: Place
  departure_time: string // ISO-8601 with offset
  load_weight_lb: number
  interval_miles: Interval
  hos?: boolean // extra E5: Hours-of-Service breaks
  simulate_storm?: boolean // extra E3: synthetic storm scenario for demos
}

export interface CheckpointWeather {
  wind_mph: number
  gust_mph: number | null
  rain_in_hr: number
  snow_in_hr: number
  valid_time: number
}

export interface CheckpointRisk {
  level: RiskLevel
  label: string
  wind_level: RiskLevel
  rain_level: RiskLevel
  snow_level: RiskLevel
  load_rule: string | null
  reasons: string[]
}

export interface Checkpoint {
  index: number
  distance_mi: number
  lat: number
  lon: number
  eta: number
  weather: CheckpointWeather | null
  risk: CheckpointRisk | null
}

export interface RouteSummary {
  distance_mi: number
  duration_s: number
  departure: number
  arrival: number
  miles_by_level: Record<LevelKey, number>
  unknown_miles: number
  avg_risk: number
  max_level: RiskLevel | null
  no_travel: boolean
}

export interface Route {
  id: string
  name: string
  via: string
  source: 'native' | 'via'
  rank: number
  recommended: boolean
  geometry: [number, number][]
  summary: RouteSummary
  checkpoints: Checkpoint[]
  why_not: string | null // extra E2: why this route lost to the recommended one
  stops: RestStop[] // extra E5 (empty unless Hours-of-Service is on)
}

export interface RestStop {
  kind: 'break' | 'rest'
  label: string
  distance_mi: number
  lat: number
  lon: number
  start: number
  end: number
}

export interface HeatmapGrid {
  lat0: number
  lon0: number
  dlat: number
  dlon: number
  n_lat: number
  n_lon: number
}

export interface Heatmap {
  grid: HeatmapGrid
  core: (0 | 1)[] // full grid, row-major
  nodes: number[] // grid indices that have forecast values
  start_time: number
  step_s: number
  hours: number
  levels: string[]
  level: number[][] // [hour][node], -1 = no data
  wind_mph: (number | null)[][]
  rain_in_hr: (number | null)[][]
  snow_in_hr: (number | null)[][]
}

export interface DepartureOption {
  offset_h: number
  departure: number
  route_id: string
  miles_by_level: Record<LevelKey, number>
  avg_risk: number
  duration_s: number
  no_travel: boolean
  best: boolean
}

export interface PlanResponse {
  request: {
    origin: Place
    destination: Place
    departure_time: number
    load_weight_lb: number
    interval_miles: Interval
    simulate_storm?: boolean
    hos?: boolean
  }
  routes: Route[]
  recommended_route_id: string
  recommendation_reason: string
  heatmap: Heatmap
  warnings: string[]
  departure_options?: DepartureOption[] // extra E4
  departure_advice?: string | null
  meta: {
    weather_source?: 'open-meteo' | 'simulated'
    routing_source?: 'osrm' | 'recorded'
    demo_mode?: boolean
    [key: string]: unknown
  }
}

export interface ApiErrorBody {
  error: { code: string; message: string; details?: Record<string, unknown> }
}
