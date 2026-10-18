from django.db.models import Count

from .models import Priority, Status, Ticket
from .services import CLOSED_STATUSES


def build_summary(organization_id):
    tickets = Ticket.objects.filter(organization_id=organization_id)

    by_status = {status: 0 for status in Status.values}
    by_status.update({row["status"]: row["total"] for row in tickets.values("status").annotate(total=Count("id"))})

    by_priority = {priority: 0 for priority in Priority.values}
    by_priority.update(
        {row["priority"]: row["total"] for row in tickets.values("priority").annotate(total=Count("id"))}
    )

    workload = list(
        tickets.exclude(status__in=CLOSED_STATUSES)
        .filter(assignee__isnull=False)
        .values("assignee__username")
        .annotate(open_tickets=Count("id"))
        .order_by("-open_tickets")
    )

    # Averages computed in Python over the latest 1000 rows: portable across MySQL/SQLite.
    # (At larger scale, pre-aggregate into a daily stats table via Celery.)
    rows = (
        tickets.filter(first_response_at__isnull=False)
        .order_by("-created_at")
        .values_list("created_at", "first_response_at")[:1000]
    )
    minutes = [(responded - created).total_seconds() / 60 for created, responded in rows]
    avg_first_response = round(sum(minutes) / len(minutes), 1) if minutes else None

    return {
        "total_tickets": sum(by_status.values()),
        "by_status": by_status,
        "by_priority": by_priority,
        "sla_first_response_breaches": tickets.filter(first_response_breached=True).count(),
        "sla_resolution_breaches": tickets.filter(resolution_breached=True).count(),
        "avg_first_response_minutes": avg_first_response,
        "agent_workload": [
            {"agent": row["assignee__username"], "open_tickets": row["open_tickets"]} for row in workload
        ],
    }
