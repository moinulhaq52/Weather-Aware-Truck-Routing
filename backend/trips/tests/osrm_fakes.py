"""Builders for fake OSRM responses (shape matches the real API, verified against live responses)."""

from trips.domain.geo import METERS_PER_MILE, haversine_mi
from trips.domain.types import LatLon


def osrm_route(points: list[LatLon], speed_mph: float = 60.0, summary: str = "I 35", legs: int = 1):
    """One OSRM route dict through ``points`` at a constant speed."""
    seg_mi = [haversine_mi(points[i], points[i + 1]) for i in range(len(points) - 1)]
    durs = [m / speed_mph * 3600 for m in seg_mi]
    dists = [m * METERS_PER_MILE for m in seg_mi]
    # Split annotations across legs like OSRM does (legs share their joining vertex).
    cut = len(durs) // legs
    leg_objs = []
    for k in range(legs):
        lo, hi = k * cut, (len(durs) if k == legs - 1 else (k + 1) * cut)
        leg_objs.append(
            {"summary": summary, "annotation": {"duration": durs[lo:hi], "distance": dists[lo:hi]}}
        )
    return {
        "geometry": {"type": "LineString", "coordinates": [[p.lon, p.lat] for p in points]},
        "legs": leg_objs,
        "distance": sum(dists),
        # Real OSRM totals include turn penalties not present in annotations.
        "duration": sum(durs) * 1.01,
    }


def line(a: LatLon, b: LatLon, n: int = 60) -> list[LatLon]:
    return [
        LatLon(a.lat + (b.lat - a.lat) * i / n, a.lon + (b.lon - a.lon) * i / n)
        for i in range(n + 1)
    ]


def dogleg(a: LatLon, via: LatLon, b: LatLon, n: int = 40) -> list[LatLon]:
    return line(a, via, n) + line(via, b, n)[1:]


def ok(*routes):
    return {"code": "Ok", "routes": list(routes), "waypoints": []}
