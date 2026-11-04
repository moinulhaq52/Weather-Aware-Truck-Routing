# Truck Weather Router

A React + Django web app that helps a truck driver pick the **safest route** using the weather
forecast **at the time the truck will actually be at each point**, plus load weight and travel
time.

Enter an origin, a destination, a departure time and the load weight. The app:

1. gets **three route options** from a routing API;
2. samples each route every **10 / 25 / 50 miles** and works out the truck's **ETA** at each
   checkpoint;
3. looks up the **hourly forecast valid at each ETA** and classifies it with the brief's
   wind / rain / snow thresholds and **load rules**;
4. **recommends** the route with the fewest Severe miles, then the fewest High miles, then the
   lowest average risk, then the shortest time;
5. shows everything on an interactive map, with a **weather-risk heatmap along the trip corridor**
   and a **0–48 h forecast slider**.

No API keys are needed: routing, geocoding, weather and map tiles all use free public services.

> **Docs:** [task](docs/TASK.md) · [understanding & requirements](docs/UNDERSTANDING.md) ·
> [research](docs/RESEARCH.md) · [plan](docs/PLAN.md) · [walkthrough script](docs/WALKTHROUGH.md)

---

## Features

### Core (from the brief)

| Requirement | How it's met |
|---|---|
| Origin, destination, departure, load | Place autocomplete (Photon, falling back to Nominatim), `datetime-local` in your time zone, load in lb (1–80,000) with presets around the 30k/40k load-rule thresholds. Validated in the browser **and** on the server. |
| 3 route options from a routing API | OSRM. Its public server returns at most 2 alternatives, so the backend makes the third by routing through a via-point pushed to the side of the trip midpoint, then drops near-duplicates (>85% overlap), routes >1.6× slower and out-and-back spurs. |
| Weather every 10 / 25 / 50 mi at the truck's ETA | Checkpoints at 0, d, 2d, … and the destination. ETAs come from OSRM per-segment durations, interpolated within segments and **capped at truck speed (65 mph)**. Open-Meteo hourly forecast at each ETA: precipitation uses the *preceding-hour* row that contains the ETA, wind the nearest hour. |
| Risk & load rules | Implemented as data tables (`backend/trips/domain/risk.py`) with every boundary unit-tested. The overall level is the worst of wind (after load rules), rain and snow. |
| Recommendation | Lexicographic: **No Travel miles → Severe miles → High miles → average risk → travel time**, with tolerances so noise can't decide it. A plain-English reason explains the choice. |
| Map: routes, checkpoints, risk, ETAs, summaries | MapLibre (WebGL). The selected route is drawn coloured by risk along its length. Checkpoints are coloured by level; hover shows ETA, wind/gust/rain/snow, level and the reasons. Route cards show distance, time, arrival, a miles-per-level bar, average and worst risk. |
| Weather heatmap along the corridor, 0–48 h slider | A grid within ~40 mi of all routes. All 49 hourly frames are rendered **once in a Web Worker**, so the slider just swaps a GPU texture. Each pixel shows the true risk level for the weather interpolated there (same rules, including load). Layers: Risk / Wind / Rain / Snow, with play, opacity and legend. |

### Extras (plus points)

| # | Extra | What it adds |
|---|---|---|
| E1 | **Truck position on the slider** | A marker per route shows where each truck will be at the slider time, on the road and coloured by local risk, so you can see whether you'll meet the storm. Arrived trucks stay dimmed at the destination. |
| E2 | **Explainable risk** | Every checkpoint says *why* (e.g. "Wind 47 mph → Severe; Load rule: wind 45–54 mph with load over 30,000 lb → No Travel"). Each losing route says why it lost. Each route card has a risk-vs-distance strip and its notable checkpoints. |
| E3 | **Demo mode & storm simulation** | "Simulate a storm" swaps in a deterministic synthetic storm across the corridor, so the logic can be demonstrated on a calm-weather day. It's labelled everywhere and never presented as a forecast. `DEMO_MODE=true` also replays recorded real OSRM routes for the example trips, and falls back to the simulation if the weather API is down. |
| E4 | **Best time to leave** | Re-scores all routes for departures +0…+24 h using forecasts already fetched (no extra API calls) and recommends the safest start with the same ranking. |
| E5 | **Hours-of-Service ETAs** | Optional FMCSA breaks (30 min after 8 h driving, 10 h off after 11 h) are inserted into the ETA timeline. On long hauls this changes *which* forecast applies. Stops are shown on the map, and the truck marker stays parked during them. |

Also: shareable URLs (`?from=…&to=…&depart=…`), example trips, swap origin/destination,
keyboard-accessible controls, a phone layout, per-IP rate limiting, and caching of routes,
weather and geocoding.

---

## How the logic works (the part graded for correctness)

**Threshold boundaries.** The brief's ranges share endpoints (rain 0.25 is in both Moderate and
High). A shared endpoint goes to the **higher** level. The exception is where No Travel is written
as `>` (rain > 1.00, snow > 3.0), which makes 1.00 and 3.0 themselves Severe:

| | Low | Moderate | High | Severe | No Travel |
|---|---|---|---|---|---|
| Wind (mph) | < 25 | [25, 35) | [35, 45) | [45, 55) | ≥ 55 |
| Rain (in/hr) | < 0.10 | [0.10, 0.25) | [0.25, 0.50) | [0.50, 1.00] | > 1.00 |
| Snow (in/hr) | < 0.5 | [0.5, 1.0) | [1.0, 2.0) | [2.0, 3.0] | > 3.0 |

Load rules raise only the wind level: 45–54 mph with > 30,000 lb → No Travel; 35–44 mph with
> 40,000 lb → Severe. Wind is the sustained 10 m speed; gusts are shown but not scored (confirmed
with the requester).

**Miles per level.** Each checkpoint owns the stretch of road half-way to its neighbours, so
per-level miles always add up to the route length. The map's risk-coloured route uses the same
rule. The average risk is distance-weighted (Low 0 … No Travel 4).

**Ranking tolerances.** 0.5 mi for level miles, 0.05 for average risk, 60 s for time. The 0.05
came from live testing: without it, a route 5.6 h longer with the *same* 50 Moderate miles won
Chicago→Seattle purely because its exposure was spread over more miles.

Every assumption is listed with its reasoning in
[docs/UNDERSTANDING.md §4](docs/UNDERSTANDING.md#4-assumptions-decisions-on-gaps-to-be-confirmed-at-plan-approval).

---

## Architecture

```
React (Vite, TS, MapLibre) ──/api──▶ Django + DRF (stateless)
  TripForm · RouteList · MapView        api/        validation, throttles, error JSON
  ForecastPanel (0–48 h slider)         services/   planner: orchestration
  heatmap.worker (49 frames)            domain/     pure logic: risk, sampling, forecast,
                                                    scoring, corridor, hos (no I/O, fully tested)
                                        providers/  OSRM · Open-Meteo · Photon/Nominatim · demo
```

- **One request per plan.** Checkpoints and the heatmap grid share **one** batched weather
  fetch. Points snap to 0.05° cells, are deduplicated, and are cached per (cell, UTC day), so
  re-plans with a different time or load are almost free.
- **The slider never touches the network.** Frames are pre-rendered `ImageBitmap`s in a Web
  Worker; the map's image source just swaps textures. Measured on a production build: **~1.7 ms
  of JavaScript per slider step**, with no long tasks.
- **Production:** one Docker image, in which gunicorn + WhiteNoise serve the API and SPA from
  one origin.

```
backend/
  config/              settings (env-driven), urls
  trips/domain/        risk.py sampling.py forecast.py scoring.py corridor.py hos.py geo.py types.py
  trips/providers/     http.py routing.py weather.py geocoding.py demo.py
  trips/services/      planner.py
  trips/api/           views.py serializers.py throttles.py exceptions.py
  trips/tests/         190 tests (unit, provider with mocked HTTP, API integration)
  scripts/             smoke.py (live APIs), record_fixtures.py (demo routes)
frontend/src/
  api/ components/ hooks/ lib/ map/ (MapView, layers, geojson builders, heatmap + worker)
docs/                  TASK, UNDERSTANDING, RESEARCH, PLAN, WALKTHROUGH
Dockerfile · render.yaml · Makefile
```

---

## Setup

Requirements: **Python 3.10+**, **Node 20+**, and optionally Docker.

```bash
make setup          # creates backend/.venv, installs Python + npm deps, copies backend/.env.example
```

Or by hand:

```bash
python3 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements-dev.txt
cp backend/.env.example backend/.env     # DJANGO_DEBUG=true for local dev
cd frontend && npm ci
```

## Run (development)

```bash
make dev            # Django on :8000 and Vite on :5173 (proxying /api), in parallel
# or in two terminals:
make backend
make frontend
```

Open http://localhost:5173 and click an example trip (e.g. **Dallas → Denver**), then
**Find safest route**. Tick **Simulate a storm** to see the risk logic with dramatic weather.

## Test, lint, format

```bash
make test           # backend pytest (190 tests) + frontend vitest (102 tests)
make lint           # ruff check + ruff format --check · oxlint + tsc + prettier --check
make format         # auto-fix formatting

# coverage (backend ≈ 99%)
cd backend && .venv/bin/pytest --cov=trips

# live smoke test against the REAL APIs (needs the backend running)
cd backend && .venv/bin/python scripts/smoke.py
```

## Deploy

**Docker (any host):**

```bash
docker build -t weather-truck-routing .
docker run -p 8000:8000 -e DJANGO_SECRET_KEY=change-me -e DJANGO_ALLOWED_HOSTS=localhost weather-truck-routing
# → http://localhost:8000
```

**Render:** push to GitHub, then *New → Blueprint* and select the repo. `render.yaml` builds the
Dockerfile, generates a secret key and sets the env vars below. Health check: `/api/health`.

### Configuration (environment variables)

| Variable | Default | Purpose |
|---|---|---|
| `DJANGO_SECRET_KEY` | — (required when `DJANGO_DEBUG=false`) | Django secret |
| `DJANGO_DEBUG` | `false` | Development mode |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma-separated hosts |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | — | e.g. `https://*.onrender.com` |
| `REDIS_URL` | — | Shared cache (needed only for more than one gunicorn worker) |
| `DEMO_MODE` | `false` | Recorded routes for the example trips + simulated-weather fallback |
| `OPEN_METEO_API_KEY` | — | Commercial Open-Meteo key (removes free-tier limits) |
| `OSRM_BASE_URL` | `https://router.project-osrm.org` | Self-hosted OSRM, if you have one |
| `TRUCK_SPEED_CAP_MPH` | `65` | Truck speed cap applied to car-profile durations |
| `THROTTLE_PLAN` / `THROTTLE_GEOCODE` | `20/min` / `60/min` | Per-IP rate limits |

## API

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/health` | `{"status": "ok", "demo_mode": false}` |
| `GET` | `/api/geocode?q=denver` | `{"results": [{label, lat, lon, kind}]}` |
| `POST` | `/api/plan` | Body: `{origin:{lat,lon,label}, destination:{…}, departure_time: ISO-8601 with offset, load_weight_lb, interval_miles: 10\|25\|50, hos?: bool, simulate_storm?: bool}`. Returns routes with checkpoints, weather, risk and reasons, summaries, recommendation and reason, heatmap frames, departure options and warnings. |

Errors are always `{"error": {"code", "message", "details?"}}`: 400 invalid input, 415 non-JSON,
422 unplannable (`no_route`, `same_place`, `too_long`, `beyond_forecast`), 429 rate limited,
502 upstream service unavailable.

---

## Known limitations

- **Car-based routing.** Public OSRM has no truck profile (no bridge heights, weight limits or
  hazmat restrictions); a 65 mph cap approximates truck speed. The `RoutingProvider` interface is
  ready for TomTom/HERE truck routing with a key.
- **Free-tier quotas.** Open-Meteo counts each location as a call (600/min, 10,000/day per IP).
  A cold long trip uses about 300 locations, so a busy shared host can hit the limit. The app then
  shows a clear "rate-limiting" message. Caching reduces repeats, and `OPEN_METEO_API_KEY` removes
  the limit.
- **Forecast horizon.** Departures up to 7 days ahead, trips ending within 15 days. Beyond about
  3 days forecasts are less reliable, and the app warns.
- **HOS model is simplified.** Only the 8 h/30 min and 11 h/10 h driving rules. No 14-hour window,
  weekly limits or loading time. Weather during a 10 h rest is not scored (the truck is parked).
- **Heatmap resolution** adapts to stay within the API budget (about 0.15° on short trips, up to
  about 0.6° cross-country). Values between grid nodes are interpolated.
- **Third route.** For some trips (few parallel highways, or very short hops) only one or two
  genuinely different routes exist. The app then shows what it found and says so, rather than
  inventing a duplicate.
- **Hosting and Loom walkthrough** are provided as configuration (`render.yaml`) and a script
  ([docs/WALKTHROUGH.md](docs/WALKTHROUGH.md)); publishing them needs the owner's accounts.

## Credits

Routing © [OSRM](https://project-osrm.org/) / OpenStreetMap contributors (ODbL) · Weather ©
[Open-Meteo](https://open-meteo.com/) (CC BY 4.0) · Geocoding: [Photon](https://photon.komoot.io/),
[Nominatim](https://nominatim.org/) · Map tiles © [OpenFreeMap](https://openfreemap.org/) /
OpenMapTiles / OpenStreetMap.
