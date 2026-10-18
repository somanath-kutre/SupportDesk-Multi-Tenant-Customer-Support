import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Organization, Role, User
from apps.tickets import services

PASSWORD = "Pass@12345"


def make_user(organization, role, username):
    return User.objects.create_user(
        username=username,
        email=f"{username}@example.com",
        password=PASSWORD,
        organization=organization,
        role=role,
    )


@pytest.fixture
def org(db):
    organization = Organization.objects.create(name="Acme", slug="acme")
    services.create_default_sla_policies(organization)
    return organization


@pytest.fixture
def other_org(db):
    organization = Organization.objects.create(name="Globex", slug="globex")
    services.create_default_sla_policies(organization)
    return organization


@pytest.fixture
def admin_user(org):
    return make_user(org, Role.ORG_ADMIN, "admin")


@pytest.fixture
def manager(org):
    return make_user(org, Role.MANAGER, "manager")


@pytest.fixture
def agent(org):
    return make_user(org, Role.AGENT, "agent1")


@pytest.fixture
def agent2(org):
    return make_user(org, Role.AGENT, "agent2")


@pytest.fixture
def customer(org):
    return make_user(org, Role.CUSTOMER, "customer1")


@pytest.fixture
def other_agent(other_org):
    return make_user(other_org, Role.AGENT, "globex_agent")


@pytest.fixture
def other_customer(other_org):
    return make_user(other_org, Role.CUSTOMER, "globex_customer")


@pytest.fixture
def client_for():
    def _client(user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    return _client


@pytest.fixture
def ticket(customer):
    return services.create_ticket(
        requester=customer,
        subject="Cannot log in",
        description="Login fails with a server error",
        priority="high",
    )
