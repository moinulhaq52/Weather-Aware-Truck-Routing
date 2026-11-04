"""Per-IP rate limits, so one client can't exhaust the shared free-tier API quotas."""

from rest_framework.throttling import SimpleRateThrottle


class _IpThrottle(SimpleRateThrottle):
    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class PlanThrottle(_IpThrottle):
    scope = "plan"


class GeocodeThrottle(_IpThrottle):
    scope = "geocode"
