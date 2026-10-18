"""SLA engine: scans for breached tickets (called by Celery Beat)."""
import logging
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .models import EventType, Status, Ticket
from .notifications import broadcast_on_commit, notify, org_managers
from .services import CLOSED_STATUSES, record_event

logger = logging.getLogger(__name__)


@transaction.atomic
def _mark_breached(ticket_id, flag_field, event_type, label):
    """Flip the breach flag exactly once (idempotent) and alert the right people."""
    flipped = (
        Ticket.objects.filter(pk=ticket_id, **{flag_field: False})
        .exclude(status__in=CLOSED_STATUSES)
        .update(**{flag_field: True})
    )
    if not flipped:
        return False

    ticket = Ticket.objects.select_related("assignee").get(pk=ticket_id)
    record_event(ticket.pk, None, event_type)
    recipients = list(org_managers(ticket.organization_id))
    if ticket.assignee:
        recipients.append(ticket.assignee)
    notify(recipients, ticket, f"SLA breach ({label}) on ticket #{ticket.pk}: {ticket.subject}")
    broadcast_on_commit(
        ticket.pk, "sla_breached", {"ticket_id": ticket.pk, "sla": label}, staff_only=True
    )
    return True


def run_sla_check():
    now = timezone.now()
    active = Ticket.objects.exclude(status__in=CLOSED_STATUSES)

    first_response_ids = list(
        active.filter(
            first_response_breached=False, first_response_at__isnull=True, first_response_due_at__lt=now
        ).values_list("pk", flat=True)
    )
    resolution_ids = list(
        active.filter(resolution_breached=False, resolution_due_at__lt=now).values_list("pk", flat=True)
    )

    first_response_count = sum(
        _mark_breached(pk, "first_response_breached", EventType.SLA_FIRST_RESPONSE_BREACHED, "first response")
        for pk in first_response_ids
    )
    resolution_count = sum(
        _mark_breached(pk, "resolution_breached", EventType.SLA_RESOLUTION_BREACHED, "resolution")
        for pk in resolution_ids
    )
    return {"first_response_breaches": first_response_count, "resolution_breaches": resolution_count}


def auto_close_resolved():
    now = timezone.now()
    cutoff = now - timedelta(days=settings.AUTO_CLOSE_RESOLVED_DAYS)
    ids = list(
        Ticket.objects.filter(status=Status.RESOLVED, resolved_at__lt=cutoff).values_list("pk", flat=True)
    )
    closed = 0
    for pk in ids:
        with transaction.atomic():
            updated = Ticket.objects.filter(pk=pk, status=Status.RESOLVED).update(
                status=Status.CLOSED, version=F("version") + 1, updated_at=now
            )
            if updated:
                record_event(pk, None, EventType.AUTO_CLOSED, Status.RESOLVED, Status.CLOSED)
                closed += 1
    return closed
