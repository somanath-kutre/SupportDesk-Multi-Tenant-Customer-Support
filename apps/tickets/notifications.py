"""In-app notifications, email fan-out and WebSocket broadcasts."""
import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction

from apps.accounts.models import Role, User

from .models import Notification
from .tasks import send_notification_emails

logger = logging.getLogger(__name__)


def org_managers(organization_id):
    return User.objects.filter(
        organization_id=organization_id, role__in=[Role.ORG_ADMIN, Role.MANAGER], is_active=True
    )


def notify(users, ticket, message, subject=None):
    """Create in-app notifications now; send emails only AFTER the DB transaction commits."""
    unique = {user.pk: user for user in users if user is not None}
    if not unique:
        return
    Notification.objects.bulk_create(
        [Notification(user=user, ticket=ticket, message=message[:300]) for user in unique.values()]
    )
    emails = [user.email for user in unique.values() if user.email]
    if emails:
        email_subject = subject or f"[SupportDesk] Ticket #{ticket.pk}"
        transaction.on_commit(lambda: send_notification_emails.delay(emails, email_subject, message))


def broadcast(ticket_id, event, payload, *, staff_only=False):
    """
    Push an event to everyone watching a ticket over WebSocket.
    Staff and customers join different groups so internal notes never leak.
    """
    layer = get_channel_layer()
    if layer is None:
        return
    groups = [f"ticket_{ticket_id}_staff"]
    if not staff_only:
        groups.append(f"ticket_{ticket_id}_public")
    message = {"type": "ticket.event", "event": event, "payload": payload}
    try:
        for group in groups:
            async_to_sync(layer.group_send)(group, message)
    except Exception:  # noqa: BLE001 - a broken channel layer must never fail the API request
        logger.exception("WebSocket broadcast failed for ticket %s", ticket_id)


def broadcast_on_commit(ticket_id, event, payload, *, staff_only=False):
    transaction.on_commit(lambda: broadcast(ticket_id, event, payload, staff_only=staff_only))
