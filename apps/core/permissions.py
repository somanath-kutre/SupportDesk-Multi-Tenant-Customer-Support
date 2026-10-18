"""
RBAC building blocks.

Layer 1 (this file):  "is this role allowed to call this endpoint at all?"
Layer 2 (views):      queryset scoping - "which rows may this user see?"
Layer 3 (services):   business rules - "may this user do this to THIS ticket?"
"""
from rest_framework.permissions import BasePermission

from apps.accounts.models import Role


class IsOrgMember(BasePermission):
    message = "You do not belong to an organization."

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and (user.is_superuser or user.organization_id))


def roles_allowed(*roles):
    """Permission-class factory: roles_allowed(Role.MANAGER, Role.ORG_ADMIN)."""
    allowed = tuple(roles)

    class RoleAllowed(BasePermission):
        message = "Your role does not permit this action."

        def has_permission(self, request, view):
            user = request.user
            return bool(user and user.is_authenticated and (user.is_superuser or user.role in allowed))

    return RoleAllowed


IsStaff = roles_allowed(Role.ORG_ADMIN, Role.MANAGER, Role.AGENT)
IsManager = roles_allowed(Role.ORG_ADMIN, Role.MANAGER)
IsOrgAdmin = roles_allowed(Role.ORG_ADMIN)
