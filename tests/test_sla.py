from datetime import timedelta

import pytest
from django.utils import timezone

from apps.tickets import services
from apps.tickets.models import EventType, Notification, Status, Ticket
from apps.tickets.sla import auto_close_resolved, run_sla_check
from apps.tickets.tasks import check_sla_breaches

pytestmark = pytest.mark.django_db


def _overdue(ticket, **extra):
    Ticket.objects.filter(pk=ticket.pk).update(
        first_response_due_at=timezone.now() - timedelta(minutes=1), **extra
    )


def test_first_response_breach_is_flagged_once_and_alerts_managers(ticket, manager):
    _overdue(ticket)
    assert run_sla_check()["first_response_breaches"] == 1

    ticket.refresh_from_db()
    assert ticket.first_response_breached is True
    assert ticket.events.filter(event_type=EventType.SLA_FIRST_RESPONSE_BREACHED).count() == 1
    assert Notification.objects.filter(user=manager, message__contains="SLA breach").exists()

    assert run_sla_check()["first_response_breaches"] == 0  # idempotent


def test_answered_ticket_is_not_flagged(ticket, agent):
    services.add_comment(ticket=ticket, author=agent, body="On it")
    _overdue(ticket)
    assert run_sla_check()["first_response_breaches"] == 0


def test_resolved_ticket_is_ignored(ticket, agent):
    services.change_status(ticket=ticket, actor=agent, new_status=Status.RESOLVED)
    _overdue(ticket)
    Ticket.objects.filter(pk=ticket.pk).update(resolution_due_at=timezone.now() - timedelta(minutes=1))
    result = run_sla_check()
    assert result == {"first_response_breaches": 0, "resolution_breaches": 0}


def test_resolution_breach(ticket):
    Ticket.objects.filter(pk=ticket.pk).update(resolution_due_at=timezone.now() - timedelta(minutes=1))
    assert run_sla_check()["resolution_breaches"] == 1


def test_auto_close_resolved_tickets(ticket, agent):
    services.change_status(ticket=ticket, actor=agent, new_status=Status.RESOLVED)
    Ticket.objects.filter(pk=ticket.pk).update(resolved_at=timezone.now() - timedelta(days=8))
    assert auto_close_resolved() == 1
    ticket.refresh_from_db()
    assert ticket.status == Status.CLOSED
    assert ticket.events.filter(event_type=EventType.AUTO_CLOSED).exists()


def test_celery_task_wrapper_runs(ticket):
    _overdue(ticket)
    assert check_sla_breaches()["first_response_breaches"] == 1


def test_report_summary_requires_manager_and_counts(ticket, agent, manager, client_for):
    assert client_for(agent).get("/api/v1/reports/summary/").status_code == 403
    response = client_for(manager).get("/api/v1/reports/summary/")
    assert response.status_code == 200
    assert response.data["total_tickets"] == 1
    assert response.data["by_status"]["open"] == 1
    assert response.data["by_priority"]["high"] == 1


def test_sla_policy_update_only_by_org_admin(admin_user, manager, org, client_for):
    policy = org.sla_policies.get(priority="urgent")
    assert client_for(manager).patch(f"/api/v1/sla-policies/{policy.pk}/", {"first_response_minutes": 10}, format="json").status_code == 403
    response = client_for(admin_user).patch(f"/api/v1/sla-policies/{policy.pk}/", {"first_response_minutes": 10}, format="json")
    assert response.status_code == 200
    assert response.data["first_response_minutes"] == 10
