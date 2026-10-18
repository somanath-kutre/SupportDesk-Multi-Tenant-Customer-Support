import os

from django.conf import settings
from rest_framework import serializers

from apps.accounts.serializers import UserMiniSerializer

from .models import Attachment, Comment, Notification, Priority, SLAPolicy, Status, Ticket, TicketEvent


class TicketSerializer(serializers.ModelSerializer):
    requester = UserMiniSerializer(read_only=True)
    assignee = UserMiniSerializer(read_only=True)

    class Meta:
        model = Ticket
        fields = (
            "id", "subject", "description", "status", "priority", "requester", "assignee",
            "first_response_due_at", "resolution_due_at", "first_response_at", "resolved_at",
            "first_response_breached", "resolution_breached", "version", "created_at", "updated_at",
        )
        read_only_fields = fields


class TicketCreateSerializer(serializers.Serializer):
    subject = serializers.CharField(min_length=5, max_length=200)
    description = serializers.CharField(min_length=10)
    priority = serializers.ChoiceField(choices=Priority.choices, default=Priority.MEDIUM)


class AssignSerializer(serializers.Serializer):
    assignee_id = serializers.IntegerField(allow_null=True, help_text="User id, or null to unassign.")
    version = serializers.IntegerField(required=False, min_value=1, help_text="Ticket version you last saw.")


class StatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=Status.choices)
    version = serializers.IntegerField(required=False, min_value=1, help_text="Ticket version you last saw.")


class CommentSerializer(serializers.ModelSerializer):
    author = UserMiniSerializer(read_only=True)

    class Meta:
        model = Comment
        fields = ("id", "author", "body", "is_internal", "created_at")
        read_only_fields = ("id", "author", "created_at")


class TicketEventSerializer(serializers.ModelSerializer):
    actor = UserMiniSerializer(read_only=True)

    class Meta:
        model = TicketEvent
        fields = ("id", "event_type", "actor", "from_value", "to_value", "created_at")
        read_only_fields = fields


class AttachmentSerializer(serializers.ModelSerializer):
    uploaded_by = UserMiniSerializer(read_only=True)

    class Meta:
        model = Attachment
        fields = ("id", "file", "original_name", "size", "uploaded_by", "created_at")
        read_only_fields = ("id", "original_name", "size", "uploaded_by", "created_at")
        extra_kwargs = {"file": {"write_only": True}}

    def validate_file(self, uploaded):
        extension = os.path.splitext(uploaded.name)[1].lower()
        if extension not in settings.ALLOWED_ATTACHMENT_EXTENSIONS:
            allowed = ", ".join(sorted(settings.ALLOWED_ATTACHMENT_EXTENSIONS))
            raise serializers.ValidationError(f"File type '{extension}' is not allowed. Allowed: {allowed}.")
        limit = settings.MAX_ATTACHMENT_MB * 1024 * 1024
        if uploaded.size > limit:
            raise serializers.ValidationError(f"File is larger than {settings.MAX_ATTACHMENT_MB} MB.")
        return uploaded


class NotificationSerializer(serializers.ModelSerializer):
    ticket_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = Notification
        fields = ("id", "ticket_id", "message", "is_read", "created_at")
        read_only_fields = fields


class SLAPolicySerializer(serializers.ModelSerializer):
    class Meta:
        model = SLAPolicy
        fields = ("id", "priority", "first_response_minutes", "resolution_minutes")
        read_only_fields = ("id", "priority")
        extra_kwargs = {
            "first_response_minutes": {"min_value": 1},
            "resolution_minutes": {"min_value": 1},
        }

    def validate(self, attrs):
        first = attrs.get("first_response_minutes", getattr(self.instance, "first_response_minutes", None))
        resolution = attrs.get("resolution_minutes", getattr(self.instance, "resolution_minutes", None))
        if first and resolution and first > resolution:
            raise serializers.ValidationError("First-response time cannot exceed resolution time.")
        return attrs
