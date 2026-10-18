class TenantScopedMixin:
    """
    Multi-tenancy guard: every queryset is filtered to the caller's organization.
    The view must define `queryset` and the model must have an `organization` FK.
    """

    def get_queryset(self):
        queryset = super().get_queryset()
        if getattr(self, "swagger_fake_view", False):  # schema generation has no real user
            return queryset.none()
        user = self.request.user
        if user.is_superuser:
            return queryset
        return queryset.filter(organization_id=user.organization_id)
