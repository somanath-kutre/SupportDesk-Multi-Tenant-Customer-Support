from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from django.utils.text import slugify
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from .models import Organization, Role, User


class UserMiniSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("id", "username")
        read_only_fields = fields


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("id", "username", "email", "first_name", "last_name", "role", "organization", "is_active")
        read_only_fields = fields


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Adds role / org to the JWT so clients (and the WebSocket layer) can use them."""

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["role"] = user.role
        token["org_id"] = user.organization_id
        token["username"] = user.username
        return token

    def validate(self, attrs):
        data = super().validate(attrs)
        organization = self.user.organization
        if organization is not None and not organization.is_active:
            raise serializers.ValidationError("Your organization is deactivated.")
        return data


class LogoutSerializer(serializers.Serializer):
    refresh = serializers.CharField()


class _UniqueUserFieldsMixin:
    def validate_email(self, value):
        value = value.lower()
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value

    def validate_username(self, value):
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError("This username is taken.")
        return value

    def validate_password(self, value):
        validate_password(value)
        return value


class OrganizationRegisterSerializer(_UniqueUserFieldsMixin, serializers.Serializer):
    """Self-service tenant onboarding: creates the organization AND its first admin."""

    organization_name = serializers.CharField(max_length=150)
    username = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=8)

    @staticmethod
    def _unique_slug(name: str) -> str:
        base = slugify(name)[:50] or "org"
        slug, counter = base, 1
        while Organization.objects.filter(slug=slug).exists():
            counter += 1
            slug = f"{base}-{counter}"
        return slug

    def create(self, validated_data):
        from apps.tickets.services import create_default_sla_policies

        with transaction.atomic():
            organization = Organization.objects.create(
                name=validated_data["organization_name"],
                slug=self._unique_slug(validated_data["organization_name"]),
            )
            user = User.objects.create_user(
                username=validated_data["username"],
                email=validated_data["email"],
                password=validated_data["password"],
                organization=organization,
                role=Role.ORG_ADMIN,
            )
            create_default_sla_policies(organization)
        return user


class CustomerRegisterSerializer(_UniqueUserFieldsMixin, serializers.Serializer):
    """Customers self-register against an organization's public slug."""

    org_slug = serializers.SlugField()
    username = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=8)

    def validate(self, attrs):
        organization = Organization.objects.filter(slug=attrs["org_slug"], is_active=True).first()
        if organization is None:
            raise serializers.ValidationError({"org_slug": "Organization not found."})
        attrs["organization"] = organization
        return attrs

    def create(self, validated_data):
        return User.objects.create_user(
            username=validated_data["username"],
            email=validated_data["email"],
            password=validated_data["password"],
            organization=validated_data["organization"],
            role=Role.CUSTOMER,
        )


class UserCreateSerializer(_UniqueUserFieldsMixin, serializers.ModelSerializer):
    """Org admin creates staff (or customer) accounts inside their own organization."""

    password = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model = User
        fields = ("username", "email", "password", "first_name", "last_name", "role")

    def validate(self, attrs):
        if self.context["request"].user.organization_id is None:
            raise serializers.ValidationError("Platform super admins must create users in Django admin.")
        return attrs

    def create(self, validated_data):
        organization = self.context["request"].user.organization
        return User.objects.create_user(organization=organization, **validated_data)


class UserUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("first_name", "last_name", "role", "is_active")

    def validate(self, attrs):
        request = self.context["request"]
        if self.instance and self.instance.pk == request.user.pk:
            if ("role" in attrs and attrs["role"] != self.instance.role) or attrs.get("is_active") is False:
                raise serializers.ValidationError("You cannot change your own role or deactivate yourself.")
        return attrs
