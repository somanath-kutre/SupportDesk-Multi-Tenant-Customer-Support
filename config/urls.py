from django.contrib import admin
from django.db import connection
from django.http import JsonResponse
from django.urls import include, path
from django.views.generic import TemplateView
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView


def health(request):
    """Liveness/readiness probe used by Docker and load balancers."""
    try:
        connection.ensure_connection()
        return JsonResponse({"status": "ok", "database": "ok"})
    except Exception:  # noqa: BLE001
        return JsonResponse({"status": "degraded", "database": "down"}, status=503)


urlpatterns = [
    path("", TemplateView.as_view(template_name="frontend/index.html"), name="frontend"),
    path("admin/", admin.site.urls),
    path("health/", health, name="health"),
    path("api/v1/", include("apps.accounts.urls")),
    path("api/v1/", include("apps.tickets.urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
]
