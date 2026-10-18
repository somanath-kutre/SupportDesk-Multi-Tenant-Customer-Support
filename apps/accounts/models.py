from django.contrib.auth.models import AbstractUser
from django.db import models

from apps.core.models import TimeStampedModel


class Organization(TimeStampedModel):
    """A tenant. All business data hangs off an organization."""

    name = models.CharField(max_length=150)
    slug = models.SlugField(max_length=60, unique=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class Role(models.TextChoices):
    ORG_ADMIN = "org_admin", "Organization Admin"
    MANAGER = "manager", "Manager"
    AGENT = "agent", "Agent"
    CUSTOMER = "customer", "Customer"


STAFF_ROLES = (Role.ORG_ADMIN, Role.MANAGER, Role.AGENT)


class User(AbstractUser):
    """
    One user belongs to exactly one organization (kept simple on purpose).
    Platform super admins (is_superuser) have organization=None.
    """

    email = models.EmailField(unique=True)
    organization = models.ForeignKey(
        Organization, null=True, blank=True, on_delete=models.CASCADE, related_name="users"
    )
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.CUSTOMER)

    class Meta:
        indexes = [models.Index(fields=["organization", "role"])]

    @property
    def is_support_staff(self) -> bool:
        return self.is_superuser or self.role in STAFF_ROLES

    def __str__(self):
        return f"{self.username} ({self.role})"
