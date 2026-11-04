"""Record real OSRM routes for the example trips into trips/fixtures/routes.json.gz (extra E3).

Usage:  python scripts/record_fixtures.py

Geometry is simplified (~5 m tolerance) for size, but ETAs stay exact: each kept segment's
duration is the sum of the original segment durations it replaces.
"""

import gzip
import itertools
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from trips.domain.geo import simplify_indices  # noqa: E402
from trips.domain.types import LatLon  # noqa: E402
from trips.providers.demo import FIXTURE_FILE, fixture_key  # noqa: E402
from trips.providers.routing import OsrmProvider  # noqa: E402

# Must match EXAMPLES in frontend/src/components/tripForm.logic.ts
EXAMPLES = [
    (LatLon(32.7767, -96.797), LatLon(39.7392, -104.9903)),  # Dallas -> Denver
    (LatLon(41.8781, -87.6298), LatLon(33.749, -84.388)),  # Chicago -> Atlanta
    (LatLon(47.6062, -122.3321), LatLon(43.615, -116.2023)),  # Seattle -> Boise
]


def encode(route) -> dict:
    keep = simplify_indices(route.points, 5e-5)
    durations = [round(sum(route.seg_durations_s[a:b]), 2) for a, b in itertools.pairwise(keep)]
    return {
        "points": [[round(route.points[i].lat, 5), round(route.points[i].lon, 5)] for i in keep],
        "seg_durations_s": durations,
        "distance_mi": round(route.distance_mi, 3),
        "duration_s": round(route.duration_s, 1),
        "label": route.label,
        "source": route.source,
    }


def main() -> None:
    provider = OsrmProvider()
    out: dict[str, list[dict]] = {}
    for a, b in EXAMPLES:
        for o, d in ((a, b), (b, a)):  # both directions (the UI has a swap button)
            routes = provider.routes(o, d)
            out[fixture_key(o, d)] = [encode(r) for r in routes]
            print(f"{fixture_key(o, d)}: {len(routes)} routes")
    FIXTURE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(FIXTURE_FILE, "wt", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"))
    print(f"wrote {FIXTURE_FILE} ({FIXTURE_FILE.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
