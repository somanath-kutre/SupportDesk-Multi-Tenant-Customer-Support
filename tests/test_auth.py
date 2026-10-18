import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from apps.accounts.models import User
from tests.conftest import PASSWORD

pytestmark = pytest.mark.django_db


def test_register_organization_creates_admin_and_default_sla_policies():
    response = APIClient().post(
        "/api/v1/auth/register-organization/",
        {"organization_name": "Initech", "username": "boss", "email": "boss@initech.test", "password": "Str0ng!Pass99"},
        format="json",
    )
    assert response.status_code == 201
    assert response.data["role"] == "org_admin"
    user = User.objects.get(username="boss")
    assert user.organization.slug == "initech"
    assert user.organization.sla_policies.count() == 4


def test_register_rejects_weak_password():
    response = APIClient().post(
        "/api/v1/auth/register-organization/",
        {"organization_name": "Weak", "username": "weak", "email": "weak@x.test", "password": "12345678"},
        format="json",
    )
    assert response.status_code == 400
    assert response.data["error"]["code"] == "validation_error"


def test_customer_self_registration(org):
    response = APIClient().post(
        "/api/v1/auth/register/",
        {"org_slug": "acme", "username": "newbie", "email": "newbie@x.test", "password": "Str0ng!Pass99"},
        format="json",
    )
    assert response.status_code == 201
    assert response.data["role"] == "customer"


def test_customer_registration_unknown_org():
    response = APIClient().post(
        "/api/v1/auth/register/",
        {"org_slug": "nope", "username": "x1", "email": "x1@x.test", "password": "Str0ng!Pass99"},
        format="json",
    )
    assert response.status_code == 400


def test_login_returns_jwt_with_role_and_org_claims(agent):
    response = APIClient().post(
        "/api/v1/auth/login/", {"username": agent.username, "password": PASSWORD}, format="json"
    )
    assert response.status_code == 200
    claims = AccessToken(response.data["access"])
    assert claims["role"] == "agent"
    assert claims["org_id"] == agent.organization_id


def test_login_wrong_password(agent):
    response = APIClient().post(
        "/api/v1/auth/login/", {"username": agent.username, "password": "wrong"}, format="json"
    )
    assert response.status_code == 401


def test_me_requires_authentication_and_uses_error_envelope():
    response = APIClient().get("/api/v1/auth/me/")
    assert response.status_code == 401
    assert response.data["error"]["code"] == "unauthorized"


def test_me_with_real_jwt(agent):
    client = APIClient()
    token = client.post(
        "/api/v1/auth/login/", {"username": agent.username, "password": PASSWORD}, format="json"
    ).data["access"]
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    response = client.get("/api/v1/auth/me/")
    assert response.status_code == 200
    assert response.data["username"] == "agent1"


def test_logout_blacklists_refresh_token(agent):
    client = APIClient()
    tokens = client.post(
        "/api/v1/auth/login/", {"username": agent.username, "password": PASSWORD}, format="json"
    ).data
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    assert client.post("/api/v1/auth/logout/", {"refresh": tokens["refresh"]}, format="json").status_code == 204
    reuse = APIClient().post("/api/v1/auth/refresh/", {"refresh": tokens["refresh"]}, format="json")
    assert reuse.status_code == 401


def test_org_admin_can_create_user_in_own_org(admin_user, client_for, org):
    response = client_for(admin_user).post(
        "/api/v1/users/",
        {"username": "newagent", "email": "newagent@x.test", "password": "Str0ng!Pass99", "role": "agent"},
        format="json",
    )
    assert response.status_code == 201
    assert User.objects.get(username="newagent").organization_id == org.pk


def test_agent_cannot_create_user(agent, client_for):
    response = client_for(agent).post(
        "/api/v1/users/",
        {"username": "evil", "email": "evil@x.test", "password": "Str0ng!Pass99", "role": "org_admin"},
        format="json",
    )
    assert response.status_code == 403
    assert response.data["error"]["code"] == "forbidden"


def test_admin_cannot_deactivate_self(admin_user, client_for):
    response = client_for(admin_user).patch(f"/api/v1/users/{admin_user.pk}/", {"is_active": False}, format="json")
    assert response.status_code == 400
