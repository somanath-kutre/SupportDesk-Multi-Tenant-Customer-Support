from django.db.models import Q
from django_filters import rest_framework as filters

from .models import Ticket


class TicketFilter(filters.FilterSet):
    created_after = filters.IsoDateTimeFilter(field_name="created_at", lookup_expr="gte")
    created_before = filters.IsoDateTimeFilter(field_name="created_at", lookup_expr="lte")
    unassigned = filters.BooleanFilter(method="filter_unassigned")
    breached = filters.BooleanFilter(method="filter_breached")
    assigned_to_me = filters.BooleanFilter(method="filter_assigned_to_me")

    class Meta:
        model = Ticket
        fields = ["status", "priority", "assignee", "requester"]

    def filter_unassigned(self, queryset, name, value):
        return queryset.filter(assignee__isnull=True) if value else queryset.filter(assignee__isnull=False)

    def filter_breached(self, queryset, name, value):
        condition = Q(first_response_breached=True) | Q(resolution_breached=True)
        return queryset.filter(condition) if value else queryset.exclude(condition)

    def filter_assigned_to_me(self, queryset, name, value):
        user = self.request.user
        return queryset.filter(assignee=user) if value else queryset.exclude(assignee=user)
