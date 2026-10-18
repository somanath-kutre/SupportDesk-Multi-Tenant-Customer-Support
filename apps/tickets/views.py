from django.conf import settings
from django.core.cache import cache
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.mixins import TenantScopedMixin
from apps.core.permissions import IsManager, IsOrgAdmin, IsOrgMember, IsStaff

from . import reports, services
from .filters import TicketFilter
from .models import Notification, SLAPolicy, Ticket
from .serializers import (
    AssignSerializer,
    AttachmentSerializer,
    CommentSerializer,
    NotificationSerializer,
    SLAPolicySerializer,
    StatusSerializer,
    TicketCreateSerializer,
    TicketEventSerializer,
    TicketSerializer,
)


class TicketViewSet(
    TenantScopedMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """
    Tickets. Visibility rules:
      * Customers see only tickets they opened.
      * Staff (agent / manager / org admin) see every ticket in their organization.
      * Nobody ever sees another organization's tickets.
    """

    queryset = Ticket.objects.select_related("requester", "assignee")
    serializer_class = TicketSerializer
    permission_classes = [IsAuthenticated, IsOrgMember]
    filterset_class = TicketFilter
    search_fields = ["subject", "description"]
    ordering_fields = ["created_at", "updated_at", "first_response_due_at", "resolution_due_at"]
    ordering = ["-created_at"]

    def get_queryset(self):
        queryset = super().get_queryset()
        if getattr(self, "swagger_fake_view", False):
            return queryset
        if not self.request.user.is_support_staff:
            queryset = queryset.filter(requester=self.request.user)
        return queryset

    @extend_schema(request=TicketCreateSerializer, responses={201: TicketSerializer})
    def create(self, request, *args, **kwargs):
        serializer = TicketCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ticket = services.create_ticket(requester=request.user, **serializer.validated_data)
        return Response(TicketSerializer(ticket).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=AssignSerializer, responses=TicketSerializer)
    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated, IsOrgMember, IsStaff])
    def assign(self, request, pk=None):
        ticket = self.get_object()
        serializer = AssignSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ticket = services.assign_ticket(
            ticket=ticket,
            actor=request.user,
            assignee_id=serializer.validated_data["assignee_id"],
            expected_version=serializer.validated_data.get("version"),
        )
        return Response(TicketSerializer(ticket).data)

    @extend_schema(request=StatusSerializer, responses=TicketSerializer)
    @action(detail=True, methods=["post"], url_path="status")
    def change_status(self, request, pk=None):
        ticket = self.get_object()
        serializer = StatusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ticket = services.change_status(
            ticket=ticket,
            actor=request.user,
            new_status=serializer.validated_data["status"],
            expected_version=serializer.validated_data.get("version"),
        )
        return Response(TicketSerializer(ticket).data)

    @extend_schema(methods=["GET"], responses=CommentSerializer(many=True))
    @extend_schema(methods=["POST"], request=CommentSerializer, responses={201: CommentSerializer})
    @action(detail=True, methods=["get", "post"], url_path="comments")
    def comments(self, request, pk=None):
        ticket = self.get_object()
        if request.method == "POST":
            serializer = CommentSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            comment = services.add_comment(
                ticket=ticket,
                author=request.user,
                body=serializer.validated_data["body"],
                is_internal=serializer.validated_data.get("is_internal", False),
            )
            return Response(CommentSerializer(comment).data, status=status.HTTP_201_CREATED)

        queryset = ticket.comments.select_related("author").order_by("created_at", "id")
        if not request.user.is_support_staff:
            queryset = queryset.filter(is_internal=False)  # customers never see internal notes
        page = self.paginate_queryset(queryset)
        return self.get_paginated_response(CommentSerializer(page, many=True).data)

    @extend_schema(methods=["GET"], responses=AttachmentSerializer(many=True))
    @extend_schema(methods=["POST"], request=AttachmentSerializer, responses={201: AttachmentSerializer})
    @action(
        detail=True,
        methods=["get", "post"],
        url_path="attachments",
        parser_classes=[MultiPartParser, FormParser],
    )
    def attachments(self, request, pk=None):
        ticket = self.get_object()
        if request.method == "POST":
            serializer = AttachmentSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            attachment = services.add_attachment(
                ticket=ticket, uploader=request.user, file=serializer.validated_data["file"]
            )
            return Response(AttachmentSerializer(attachment).data, status=status.HTTP_201_CREATED)
        queryset = ticket.attachments.select_related("uploaded_by").order_by("id")
        return Response(AttachmentSerializer(queryset, many=True).data)

    @extend_schema(responses=OpenApiTypes.BINARY)
    @action(detail=True, methods=["get"], url_path=r"attachments/(?P<attachment_id>\d+)/download")
    def download_attachment(self, request, pk=None, attachment_id=None):
        """Files are private: they are streamed only after the ticket permission check passes."""
        ticket = self.get_object()
        attachment = get_object_or_404(ticket.attachments.all(), pk=attachment_id)
        return FileResponse(attachment.file.open("rb"), as_attachment=True, filename=attachment.original_name)

    @extend_schema(responses=TicketEventSerializer(many=True))
    @action(detail=True, methods=["get"], permission_classes=[IsAuthenticated, IsOrgMember, IsStaff])
    def timeline(self, request, pk=None):
        """Full audit trail of the ticket (staff only)."""
        ticket = self.get_object()
        events = ticket.events.select_related("actor")
        return Response(TicketEventSerializer(events, many=True).data)


class NotificationViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = NotificationSerializer
    queryset = Notification.objects.all()
    filterset_fields = ["is_read"]
    ordering = ["-created_at"]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Notification.objects.none()
        return Notification.objects.filter(user=self.request.user)

    @extend_schema(request=None, responses=NotificationSerializer)
    @action(detail=True, methods=["post"])
    def read(self, request, pk=None):
        notification = self.get_object()
        notification.is_read = True
        notification.save(update_fields=["is_read", "updated_at"])
        return Response(NotificationSerializer(notification).data)

    @extend_schema(request=None, responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"], url_path="read-all")
    def read_all(self, request):
        updated = self.get_queryset().filter(is_read=False).update(is_read=True)
        return Response({"updated": updated})


class SLAPolicyViewSet(
    TenantScopedMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """View SLA targets (staff) and change them (org admin). Changes apply to NEW tickets only."""

    queryset = SLAPolicy.objects.all().order_by("id")
    serializer_class = SLAPolicySerializer
    http_method_names = ["get", "patch", "head", "options"]

    def get_permissions(self):
        if self.action in ("update", "partial_update"):
            classes = [IsAuthenticated, IsOrgMember, IsOrgAdmin]
        else:
            classes = [IsAuthenticated, IsOrgMember, IsStaff]
        return [cls() for cls in classes]


class SummaryReportView(APIView):
    """Dashboard numbers for managers. Cached for a short time to protect the database."""

    permission_classes = [IsAuthenticated, IsOrgMember, IsManager]

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def get(self, request):
        organization_id = request.user.organization_id
        if organization_id is None:
            raise ValidationError("Reports are per organization; this account has none.")
        cache_key = f"report:summary:{organization_id}"
        data = cache.get(cache_key)
        if data is None:
            data = reports.build_summary(organization_id)
            cache.set(cache_key, data, settings.REPORT_CACHE_SECONDS)
        return Response(data)
