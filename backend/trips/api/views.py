"""HTTP layer: thin views that validate input, call the service layer and serialise output."""

from django.conf import settings
from django.http import FileResponse, Http404
from rest_framework.decorators import api_view, throttle_classes
from rest_framework.request import Request
from rest_framework.response import Response

from ..domain.types import LatLon
from ..providers import geocoding
from ..providers.http import UpstreamError
from ..services import planner
from .exceptions import PlanUnprocessable, UpstreamUnavailable
from .serializers import GeocodeQuerySerializer, PlanRequestSerializer
from .throttles import GeocodeThrottle, PlanThrottle


@api_view(["GET"])
def health(request: Request) -> Response:
    return Response({"status": "ok", "demo_mode": settings.TRIPS["DEMO_MODE"]})


@api_view(["GET"])
@throttle_classes([GeocodeThrottle])
def geocode(request: Request) -> Response:
    """Place autocomplete: ``GET /api/geocode?q=dallas`` → ``{"results": [Place, ...]}``."""
    params = GeocodeQuerySerializer(data=request.query_params)
    params.is_valid(raise_exception=True)
    try:
        places = geocoding.search(params.validated_data["q"])
    except UpstreamError as exc:
        raise UpstreamUnavailable("Place search is temporarily unavailable.") from exc
    return Response({"results": [p.to_dict() for p in places]})


@api_view(["POST"])
@throttle_classes([PlanThrottle])
def plan(request: Request) -> Response:
    """Plan a trip: three routes with checkpoints, risk, recommendation and heatmap frames."""
    body = PlanRequestSerializer(data=request.data)
    body.is_valid(raise_exception=True)
    v = body.validated_data
    req = planner.PlanRequest(
        origin=LatLon(v["origin"]["lat"], v["origin"]["lon"]),
        destination=LatLon(v["destination"]["lat"], v["destination"]["lon"]),
        origin_label=v["origin"]["label"],
        destination_label=v["destination"]["label"],
        departure=v["departure_time"].timestamp(),
        load_lb=v["load_weight_lb"],
        interval_mi=int(v["interval_miles"]),
        simulate_storm=v["simulate_storm"],
        hos=v["hos"],
    )
    try:
        result = planner.plan_trip(req, *planner.providers_for(req))
    except planner.PlanError as exc:
        raise PlanUnprocessable(exc.message, exc.code) from exc
    except UpstreamError as exc:
        raise UpstreamUnavailable(_upstream_message(exc)) from exc
    return Response(result)


def _upstream_message(exc: UpstreamError) -> str:
    what = {"routing": "Routing", "weather": "Weather", "geocoding": "Place search"}.get(
        exc.service, "A third-party"
    )
    if exc.status == 429 or "rate limit" in str(exc):
        return f"{what} service is rate-limiting requests. Please try again in a minute."
    return f"{what} service is temporarily unavailable. Please try again shortly."


def spa_index(request):
    """Serve the built React app's index.html for any non-API path (production only).

    Returned as a file (not a Django template) so nothing in it is interpreted, and marked
    no-cache so a redeploy is picked up at once; the hashed assets it references are immutable.
    """
    index = settings.FRONTEND_DIST / "index.html"
    if not index.exists():
        raise Http404("Frontend not built. Run `npm run build` in frontend/ or use Vite.")
    response = FileResponse(index.open("rb"), content_type="text/html; charset=utf-8")
    response["Cache-Control"] = "no-cache"
    return response
