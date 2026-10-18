"""
Business logic lives HERE, not in views or serializers (service-layer pattern).
Views translate HTTP <-> these functions; tests can call them directly.
"""
from datetime import timedelta

from django.db import transaction
from django.db.models import F
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.accounts.models import STAFF_ROLES, Role, User
from apps.core.exceptions import ConflictError, InvalidTransition

from .models import (
    Attachment,
    Comment,
    EventType,
    Priority,
    SLAPolicy,
    Status,
    Ticket,
    TicketEvent,
)
from .notifications import broadcast_on_commit, notify, org_managers

CLOSED_STATUSES = (Status.RESOLVED, Status.CLOSED)

# Ticket state machine: current status -> statuses it may move to.
ALLOWED_TRANSITIONS = {
    Status.OPEN: {Status.IN_PROGRESS, Status.WAITING_CUSTOMER, Status.RESOLVED, Status.CLOSED},
    Status.IN_PROGRESS: {Status.OPEN, Status.WAITING_CUSTOMER, Status.RESOLVED},
    Status.WAITING_CUSTOMER: {Status.IN_PROGRESS, Status.RESOLVED},
    Status.RESOLVED: {Status.OPEN, Status.CLOSED},  # OPEN here == "reopen"
    Status.CLOSED: set(),
}

# What a customer may do to their own ticket: cancel it, accept the fix, or reopen.
CUSTOMER_TRANSITIONS = {
    (Status.OPEN, Status.CLOSED),
    (Status.RESOLVED, Status.CLOSED),
    (Status.RESOLVED, Status.OPEN),
}

# priority -> (first response minutes, resolution minutes)
DEFAULT_SLA = {
    Priority.URGENT: (30, 4 * 60),
    Priority.HIGH: (60, 8 * 60),
    Priority.MEDIUM: (4 * 60, 24 * 60),
    Priority.LOW: (8 * 60, 72 * 60),
}


def create_default_sla_policies(organization):
    SLAPolicy.objects.bulk_create(
        [
            SLAPolicy(
                organization=organization,
                priority=priority,
                first_response_minutes=first_response,
                resolution_minutes=resolution,
            )
            for priority, (first_response, resolution) in DEFAULT_SLA.items()
        ],
        ignore_conflicts=True,
    )


def record_event(ticket_id, actor, event_type, from_value="", to_value=""):
    return TicketEvent.objects.create(
        ticket_id=ticket_id,
        actor=actor,
        event_type=event_type,
        from_value=str(from_value),
        to_value=str(to_value),
    )


def _guarded_update(ticket, expected_version, **fields):
    """
    Optimistic concurrency control (compare-and-swap):
    UPDATE ... WHERE id=? AND version=? - if zero rows match, someone else
    changed the ticket first, and we raise 409 instead of silently overwriting.
    """
    if expected_version is None:
        expected_version = ticket.version
    fields["version"] = F("version") + 1
    fields["updated_at"] = timezone.now()
    updated = Ticket.objects.filter(pk=ticket.pk, version=expected_version).update(**fields)
    if not updated:
        raise ConflictError()
    ticket.refresh_from_db()
    return ticket


# ------------------------------------------------------------------ operations
@transaction.atomic
def create_ticket(*, requester, subject, description, priority=Priority.MEDIUM):
    if requester.organization_id is None:
        raise ValidationError("Your account does not belong to an organization.")

    now = timezone.now()
    ticket = Ticket(
        organization_id=requester.organization_id,
        requester=requester,
        subject=subject,
        description=description,
        priority=priority,
    )
    policy = SLAPolicy.objects.filter(organization_id=requester.organization_id, priority=priority).first()
    if policy:
        ticket.first_response_due_at = now + timedelta(minutes=policy.first_response_minutes)
        ticket.resolution_due_at = now + timedelta(minutes=policy.resolution_minutes)
    ticket.save()

    record_event(ticket.pk, requester, EventType.CREATED, to_value=ticket.status)
    managers = list(org_managers(ticket.organization_id).exclude(pk=requester.pk))
    notify(managers, ticket, f"New {priority} ticket #{ticket.pk}: {subject}")
    broadcast_on_commit(ticket.pk, "created", {"ticket_id": ticket.pk, "status": ticket.status}, staff_only=True)
    return ticket


@transaction.atomic
def change_status(*, ticket, actor, new_status, expected_version=None):
    old_status = ticket.status
    if new_status == old_status:
        raise ValidationError({"status": "Ticket is already in this status."})
    if new_status not in ALLOWED_TRANSITIONS[old_status]:
        raise InvalidTransition(f"Cannot move a ticket from '{old_status}' to '{new_status}'.")
    if not actor.is_support_staff and (old_status, new_status) not in CUSTOMER_TRANSITIONS:
        raise PermissionDenied("Customers may only close, accept or reopen their own tickets.")

    fields = {"status": new_status}
    if new_status == Status.RESOLVED:
        fields["resolved_at"] = timezone.now()
    elif old_status == Status.RESOLVED and new_status == Status.OPEN:
        fields["resolved_at"] = None  # reopened

    _guarded_update(ticket, expected_version, **fields)
    record_event(ticket.pk, actor, EventType.STATUS_CHANGED, old_status, new_status)

    recipients = [ticket.requester, ticket.assignee]
    notify(
        [user for user in recipients if user is not None and user.pk != actor.pk],
        ticket,
        f"Ticket #{ticket.pk} moved from {old_status} to {new_status}.",
    )
    broadcast_on_commit(
        ticket.pk,
        "status_changed",
        {"ticket_id": ticket.pk, "from": old_status, "to": new_status, "version": ticket.version},
    )
    return ticket


@transaction.atomic
def assign_ticket(*, ticket, actor, assignee_id, expected_version=None):
    if assignee_id is None:
        assignee = None
    else:
        assignee = User.objects.filter(
            pk=assignee_id, organization_id=ticket.organization_id, is_active=True, role__in=STAFF_ROLES
        ).first()
        if assignee is None:
            raise ValidationError({"assignee_id": "Not an active staff member of this organization."})

    if actor.role == Role.AGENT and not actor.is_superuser:
        # Agents may only "claim" an unassigned ticket for themselves.
        if assignee is None or assignee.pk != actor.pk:
            raise PermissionDenied("Agents can only assign tickets to themselves.")
        if ticket.assignee_id and ticket.assignee_id != actor.pk:
            raise PermissionDenied("This ticket is already assigned to another agent.")

    if (assignee.pk if assignee else None) == ticket.assignee_id:
        raise ValidationError({"assignee_id": "Ticket is already assigned to this user."})

    previous = ticket.assignee.username if ticket.assignee else ""
    _guarded_update(ticket, expected_version, assignee=assignee)
    record_event(ticket.pk, actor, EventType.ASSIGNED, previous, assignee.username if assignee else "")

    if assignee is not None and assignee.pk != actor.pk:
        notify([assignee], ticket, f"Ticket #{ticket.pk} was assigned to you: {ticket.subject}")
    broadcast_on_commit(
        ticket.pk,
        "assigned",
        {"ticket_id": ticket.pk, "assignee": assignee.username if assignee else None, "version": ticket.version},
        staff_only=True,
    )
    return ticket


@transaction.atomic
def add_comment(*, ticket, author, body, is_internal=False):
    if is_internal and not author.is_support_staff:
        raise PermissionDenied("Only staff can add internal notes.")

    comment = Comment.objects.create(ticket=ticket, author=author, body=body, is_internal=is_internal)
    record_event(ticket.pk, author, EventType.COMMENTED, to_value="internal" if is_internal else "public")

    now = timezone.now()
    is_staff_reply = author.is_support_staff and not is_internal and author.pk != ticket.requester_id

    # First public staff reply stops the first-response SLA clock.
    if is_staff_reply and ticket.first_response_at is None:
        fields = {"first_response_at": now}
        if ticket.first_response_due_at and now > ticket.first_response_due_at:
            fields["first_response_breached"] = True
        Ticket.objects.filter(pk=ticket.pk, first_response_at__isnull=True).update(**fields)

    # A customer answering a "waiting for customer" ticket puts it back in progress.
    if author.pk == ticket.requester_id and ticket.status == Status.WAITING_CUSTOMER:
        _guarded_update(ticket, ticket.version, status=Status.IN_PROGRESS)
        record_event(ticket.pk, author, EventType.STATUS_CHANGED, Status.WAITING_CUSTOMER, Status.IN_PROGRESS)

    if not is_internal:
        if is_staff_reply:
            notify([ticket.requester], ticket, f"New reply on ticket #{ticket.pk}: {ticket.subject}")
        elif author.pk == ticket.requester_id:
            targets = [ticket.assignee] if ticket.assignee else list(org_managers(ticket.organization_id))
            notify(targets, ticket, f"Customer replied on ticket #{ticket.pk}: {ticket.subject}")

    broadcast_on_commit(
        ticket.pk,
        "comment_added",
        {
            "id": comment.pk,
            "ticket_id": ticket.pk,
            "author": author.username,
            "body": body,
            "is_internal": is_internal,
            "created_at": comment.created_at.isoformat(),
        },
        staff_only=is_internal,
    )
    return comment


@transaction.atomic
def add_attachment(*, ticket, uploader, file):
    attachment = Attachment.objects.create(
        ticket=ticket, uploaded_by=uploader, file=file, original_name=file.name[:255], size=file.size
    )
    record_event(ticket.pk, uploader, EventType.ATTACHMENT_ADDED, to_value=attachment.original_name)
    return attachment
