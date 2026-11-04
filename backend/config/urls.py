"""Root URL configuration: the JSON API lives under /api/, everything else is the React SPA."""

from django.urls import include, path, re_path

from trips.api.views import spa_index

urlpatterns = [
    path("api/", include("trips.api.urls")),
    # Client-side routes fall through to the SPA's index.html (production build only).
    re_path(r"^(?!api/|static/).*$", spa_index, name="spa"),
]
