from django.urls import include, path
from rest_framework.routers import SimpleRouter

from .views import NotificationViewSet, SLAPolicyViewSet, SummaryReportView, TicketViewSet

router = SimpleRouter()
router.register("tickets", TicketViewSet, basename="ticket")
router.register("notifications", NotificationViewSet, basename="notification")
router.register("sla-policies", SLAPolicyViewSet, basename="sla-policy")

urlpatterns = [
    path("reports/summary/", SummaryReportView.as_view(), name="report-summary"),
    path("", include(router.urls)),
]
