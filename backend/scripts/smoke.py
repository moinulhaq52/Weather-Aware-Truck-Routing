"""Live smoke test against the REAL third-party APIs (not part of the unit test suite).

Usage:  python scripts/smoke.py [base_url]     (default http://127.0.0.1:8000)

Plans three real trips (short, medium, long) and prints a compact summary with timings, so the
whole pipeline can be sanity-checked by eye. Exits non-zero if any trip fails.
"""

import json
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
TRIPS = [
    ("Dallas, TX → Fort Worth, TX", (32.7767, -96.797), (32.7555, -97.3308), 25),
    ("Dallas, TX → Denver, CO", (32.7767, -96.797), (39.7392, -104.9903), 25),
    ("Chicago, IL → Seattle, WA", (41.8781, -87.6298), (47.6062, -122.3321), 50),
]
LEVELS = ["low", "moderate", "high", "severe", "no_travel"]


def post(path, payload):
    req = urllib.request.Request(
        BASE + path, json.dumps(payload).encode(), {"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def main() -> int:
    departure = (datetime.now(timezone.utc) + timedelta(hours=1)).replace(minute=0, second=0)
    failed = 0
    for name, o, d, interval in TRIPS:
        t = time.time()
        status, data = post(
            "/api/plan",
            {
                "origin": {"lat": o[0], "lon": o[1], "label": name.split(" → ")[0]},
                "destination": {"lat": d[0], "lon": d[1], "label": name.split(" → ")[1]},
                "departure_time": departure.isoformat(),
                "load_weight_lb": 38_000,
                "interval_miles": interval,
            },
        )
        dt = time.time() - t
        if status != 200:
            failed += 1
            print(f"✗ {name}: HTTP {status} {data.get('error')}")
            continue
        size = len(json.dumps(data)) // 1024
        print(
            f"✓ {name}: {len(data['routes'])} routes in {dt:.1f}s, {size} KB, meta={data['meta']}"
        )
        for r in data["routes"]:
            s = r["summary"]
            mix = " ".join(f"{k[:2]}={s['miles_by_level'][k]:.0f}" for k in LEVELS)
            star = "★" if r["recommended"] else " "
            print(
                f"   {star} {r['name']} via {r['via'][:40]:40} {s['distance_mi']:7.1f} mi "
                f"{s['duration_s'] / 3600:5.1f} h  cps={len(r['checkpoints']):3}  "
                f"avg={s['avg_risk']:.2f}  {mix}"
            )
        print(f"   reason: {data['recommendation_reason']}")
        hm = data["heatmap"]
        print(f"   heatmap: {len(hm['nodes'])} nodes x {hm['hours']} h")
        print(f"   warnings: {data['warnings']}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
