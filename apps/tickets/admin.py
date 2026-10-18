from django.contrib import admin

from .models import Attachment, Comment, Notification, SLAPolicy, Ticket, TicketEvent


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ("id", "subject", "organization", "status", "priority", "assignee", "created_at")
    list_filter = ("status", "priority", "organization")
    search_fields = ("subject", "description")


@admin.register(SLAPolicy)
class SLAPolicyAdmin(admin.ModelAdmin):
    list_display = ("organization", "priority", "first_response_minutes", "resolution_minutes")


admin.site.register([Comment, TicketEvent, Attachment, Notification])
