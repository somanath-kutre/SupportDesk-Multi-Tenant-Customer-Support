"""The most important tests in a multi-tenant system: data must never cross tenants."""
import pytest

from apps.accounts.models import Role
from apps.tickets import services
from tests.conftest import make_user

pytestmark = pytest.mark.django_db


def test_other_org_cannot_read_ticket(ticket, other_agent, client_for):
    response = client_for(other_agent).get(f"/api/v1/tickets/{ticket.pk}/")
    assert response.status_code == 404


def test_other_org_list_is_empty(ticket, other_agent, client_for):
    response = client_for(other_agent).get("/api/v1/tickets/")
    assert response.status_code == 200
    assert response.data["count"] == 0


def test_other_org_cannot_comment_or_change_status(ticket, other_agent, client_for):
    client = client_for(other_agent)
    assert client.post(f"/api/v1/tickets/{ticket.pk}/comments/", {"body": "hi"}, format="json").status_code == 404
    assert client.post(f"/api/v1/tickets/{ticket.pk}/status/", {"status": "resolved"}, format="json").status_code == 404


def test_cannot_assign_agent_from_another_org(ticket, manager, other_agent, client_for):
    response = client_for(manager).post(
        f"/api/v1/tickets/{ticket.pk}/assign/", {"assignee_id": other_agent.pk}, format="json"
    )
    assert response.status_code == 400


def test_user_list_is_scoped_to_org(admin_user, other_agent, client_for):
    response = client_for(admin_user).get("/api/v1/users/")
    usernames = [user["username"] for user in response.data["results"]]
    assert "admin" in usernames
    assert "globex_agent" not in usernames


def test_customer_sees_only_own_tickets(org, customer, client_for):
    second_customer = make_user(org, Role.CUSTOMER, "customer2")
    mine = services.create_ticket(requester=customer, subject="Mine one", description="This is my ticket", priority="low")
    services.create_ticket(requester=second_customer, subject="Not yours", description="Someone else's ticket", priority="low")

    response = client_for(customer).get("/api/v1/tickets/")
    assert [t["id"] for t in response.data["results"]] == [mine.pk]
    other = services.create_ticket(requester=second_customer, subject="Hidden", description="Hidden from customer1", priority="low")
    assert client_for(customer).get(f"/api/v1/tickets/{other.pk}/").status_code == 404


def test_other_org_cannot_read_sla_policies_of_this_org(org, other_agent, client_for):
    response = client_for(other_agent).get("/api/v1/sla-policies/")
    assert response.status_code == 200
    assert response.data["count"] == 4  # only Globex's own 4 policies
