from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Organization, User


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_active", "created_at")
    search_fields = ("name", "slug")


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ("username", "email", "organization", "role", "is_active")
    list_filter = ("role", "is_active", "organization")
    fieldsets = UserAdmin.fieldsets + (("Support desk", {"fields": ("organization", "role")}),)
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("Support desk", {"fields": ("email", "organization", "role")}),
    )
