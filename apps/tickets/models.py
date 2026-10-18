import os
import uuid

from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel


class Priority(models.TextChoices):
    LOW = "low", "Low"
    MEDIUM = "medium", "Medium"
    HIGH = "high", "High"
    URGENT = "urgent", "Urgent"


class Status(models.TextChoices):
    OPEN = "open", "Open"
    IN_PROGRESS = "in_progress", "In progress"
    WAITING_CUSTOMER = "waiting_customer", "Waiting for customer"
    RESOLVED = "resolved", "Resolved"
    CLOSED = "closed", "Closed"


class EventType(models.TextChoices):
    CREATED = "created", "Created"
    ASSIGNED = "assigned", "Assigned"
    STATUS_CHANGED = "status_changed", "Status changed"
    COMMENTED = "commented", "Commented"
    ATTACHMENT_ADDED = "attachment_added", "Attachment added"
    SLA_FIRST_RESPONSE_BREACHED = "sla_first_response_breached", "First-response SLA breached"
    SLA_RESOLUTION_BREACHED = "sla_resolution_breached", "Resolution SLA breached"
    AUTO_CLOSED = "auto_closed", "Auto-closed"


class SLAPolicy(TimeStampedModel):
    """Per-organization response/resolution targets for each priority."""

    organization = models.ForeignKey("accounts.Organization", on_delete=models.CASCADE, related_name="sla_policies")
    priority = models.CharField(max_length=10, choices=Priority.choices)
    first_response_minutes = models.PositiveIntegerField()
    resolution_minutes = models.PositiveIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "priority"], name="uniq_sla_per_org_priority")
        ]

    def __str__(self):
        return f"{self.organization_id}:{self.priority}"


class Ticket(TimeStampedModel):
    organization = models.ForeignKey("accounts.Organization", on_delete=models.CASCADE, related_name="tickets")
    subject = models.CharField(max_length=200)
    description = models.TextField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.MEDIUM)
    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="requested_tickets"
    )
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="assigned_tickets"
    )

    # SLA tracking
    first_response_due_at = models.DateTimeField(null=True, blank=True)
    resolution_due_at = models.DateTimeField(null=True, blank=True)
    first_response_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    first_response_breached = models.BooleanField(default=False)
    resolution_breached = models.BooleanField(default=False)

    # Optimistic concurrency control: bumped on every guarded update.
    version = models.PositiveIntegerField(default=1)

    class Meta:
        indexes = [
            models.Index(fields=["organization", "status"], name="ticket_org_status_idx"),
            models.Index(fields=["organization", "assignee"], name="ticket_org_assignee_idx"),
            models.Index(fields=["organization", "created_at"], name="ticket_org_created_idx"),
            models.Index(fields=["first_response_breached", "first_response_due_at"], name="ticket_fr_sla_idx"),
            models.Index(fields=["resolution_breached", "resolution_due_at"], name="ticket_res_sla_idx"),
        ]

    def __str__(self):
        return f"#{self.pk} {self.subject}"


class Comment(TimeStampedModel):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="comments")
    body = models.TextField()
    is_internal = models.BooleanField(default=False)  # internal notes are staff-only


class TicketEvent(models.Model):
    """Append-only audit trail. Rows are never updated or deleted by the app."""

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="events")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    event_type = models.CharField(max_length=40, choices=EventType.choices)
    from_value = models.CharField(max_length=100, blank=True)
    to_value = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["created_at", "id"]


def attachment_path(instance, filename):
    extension = os.path.splitext(filename)[1].lower()
    return f"org_{instance.ticket.organization_id}/ticket_{instance.ticket_id}/{uuid.uuid4().hex}{extension}"


class Attachment(TimeStampedModel):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="attachments")
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    file = models.FileField(upload_to=attachment_path)  # swap storage for S3 via django-storages in prod
    original_name = models.CharField(max_length=255)
    size = models.PositiveIntegerField()


class Notification(TimeStampedModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    ticket = models.ForeignKey(Ticket, null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    message = models.CharField(max_length=300)
    is_read = models.BooleanField(default=False)

    class Meta:
        indexes = [models.Index(fields=["user", "is_read"], name="notif_user_read_idx")]
