from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.tickets import services
from apps.tickets.models import EventType, Notification, Status, Ticket

pytestmark = pytest.mark.django_db


def test_create_ticket_sets_sla_deadlines(customer, client_for):
    response = client_for(customer).post(
        "/api/v1/tickets/",
        {"subject": "Printer broken", "description": "The office printer is jammed", "priority": "urgent"},
        format="json",
    )
    assert response.status_code == 201
    created = Ticket.objects.get(pk=response.data["id"])
    first_response_window = created.first_response_due_at - created.created_at
    assert timedelta(minutes=29) < first_response_window < timedelta(minutes=31)  # urgent = 30 min


def test_create_ticket_validation_error_envelope(customer, client_for):
    response = client_for(customer).post("/api/v1/tickets/", {"subject": "no", "description": "short"}, format="json")
    assert response.status_code == 400
    assert response.data["error"]["code"] == "validation_error"
    assert "subject" in response.data["error"]["details"]


def test_new_ticket_notifies_managers(customer, manager):
    services.create_ticket(requester=customer, subject="Need help", description="Please help me out", priority="low")
    assert Notification.objects.filter(user=manager).count() == 1


def test_email_is_sent_only_after_commit(customer, manager, mailoutbox, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        services.create_ticket(requester=customer, subject="Need help", description="Please help me out", priority="low")
    assert len(mailoutbox) == 1
    assert mailoutbox[0].to == [manager.email]


# ------------------------------------------------------------ state machine
def test_valid_status_flow(ticket, agent, client_for):
    client = client_for(agent)
    assert client.post(f"/api/v1/tickets/{ticket.pk}/status/", {"status": "in_progress"}, format="json").status_code == 200
    response = client.post(f"/api/v1/tickets/{ticket.pk}/status/", {"status": "resolved"}, format="json")
    assert response.status_code == 200
    ticket.refresh_from_db()
    assert ticket.status == Status.RESOLVED
    assert ticket.resolved_at is not None


def test_invalid_transition_is_rejected(ticket, agent, client_for):
    client = client_for(agent)
    client.post(f"/api/v1/tickets/{ticket.pk}/status/", {"status": "in_progress"}, format="json")
    response = client.post(f"/api/v1/tickets/{ticket.pk}/status/", {"status": "closed"}, format="json")
    assert response.status_code == 400
    assert response.data["error"]["code"] == "invalid_transition"


def test_closed_ticket_is_final(ticket, agent, client_for):
    client = client_for(agent)
    client.post(f"/api/v1/tickets/{ticket.pk}/status/", {"status": "closed"}, format="json")
    response = client.post(f"/api/v1/tickets/{ticket.pk}/status/", {"status": "open"}, format="json")
    assert response.status_code == 400


def test_customer_cannot_resolve_but_can_close_own_ticket(ticket, customer, client_for):
    client = client_for(customer)
    assert client.post(f"/api/v1/tickets/{ticket.pk}/status/", {"status": "resolved"}, format="json").status_code == 403
    assert client.post(f"/api/v1/tickets/{ticket.pk}/status/", {"status": "closed"}, format="json").status_code == 200


# ------------------------------------------------------------- assignment
def test_manager_can_assign_agent(ticket, manager, agent, client_for):
    response = client_for(manager).post(f"/api/v1/tickets/{ticket.pk}/assign/", {"assignee_id": agent.pk}, format="json")
    assert response.status_code == 200
    assert response.data["assignee"]["username"] == "agent1"
    assert Notification.objects.filter(user=agent).exists()


def test_agent_can_claim_but_not_assign_to_others(ticket, agent, agent2, client_for):
    client = client_for(agent)
    assert client.post(f"/api/v1/tickets/{ticket.pk}/assign/", {"assignee_id": agent2.pk}, format="json").status_code == 403
    assert client.post(f"/api/v1/tickets/{ticket.pk}/assign/", {"assignee_id": agent.pk}, format="json").status_code == 200


def test_customer_cannot_assign(ticket, customer, agent, client_for):
    response = client_for(customer).post(f"/api/v1/tickets/{ticket.pk}/assign/", {"assignee_id": agent.pk}, format="json")
    assert response.status_code == 403


def test_optimistic_locking_returns_409_on_stale_version(ticket, manager, agent, agent2, client_for):
    stale_version = ticket.version
    client_for(manager).post(f"/api/v1/tickets/{ticket.pk}/assign/", {"assignee_id": agent.pk}, format="json")
    response = client_for(agent2).post(
        f"/api/v1/tickets/{ticket.pk}/status/", {"status": "in_progress", "version": stale_version}, format="json"
    )
    assert response.status_code == 409
    assert response.data["error"]["code"] == "conflict"


# --------------------------------------------------------------- comments
def test_internal_notes_are_hidden_from_customer(ticket, agent, customer, client_for):
    client_for(agent).post(
        f"/api/v1/tickets/{ticket.pk}/comments/", {"body": "Customer is on a trial plan", "is_internal": True}, format="json"
    )
    assert client_for(customer).get(f"/api/v1/tickets/{ticket.pk}/comments/").data["count"] == 0
    assert client_for(agent).get(f"/api/v1/tickets/{ticket.pk}/comments/").data["count"] == 1


def test_customer_cannot_post_internal_note(ticket, customer, client_for):
    response = client_for(customer).post(
        f"/api/v1/tickets/{ticket.pk}/comments/", {"body": "secret", "is_internal": True}, format="json"
    )
    assert response.status_code == 403


def test_public_staff_reply_records_first_response(ticket, agent, client_for):
    client_for(agent).post(f"/api/v1/tickets/{ticket.pk}/comments/", {"body": "Looking into it"}, format="json")
    ticket.refresh_from_db()
    assert ticket.first_response_at is not None


def test_internal_note_does_not_count_as_first_response(ticket, agent, client_for):
    client_for(agent).post(
        f"/api/v1/tickets/{ticket.pk}/comments/", {"body": "note to self", "is_internal": True}, format="json"
    )
    ticket.refresh_from_db()
    assert ticket.first_response_at is None


def test_customer_reply_moves_waiting_ticket_back_to_in_progress(ticket, agent, customer, client_for):
    services.change_status(ticket=ticket, actor=agent, new_status=Status.WAITING_CUSTOMER)
    client_for(customer).post(f"/api/v1/tickets/{ticket.pk}/comments/", {"body": "Here is the info"}, format="json")
    ticket.refresh_from_db()
    assert ticket.status == Status.IN_PROGRESS


# ---------------------------------------------- list / filter / search / page
def test_filter_search_and_ordering(customer, agent, client_for):
    services.create_ticket(requester=customer, subject="Printer jammed", description="Paper stuck in tray two", priority="urgent")
    services.create_ticket(requester=customer, subject="Wi-Fi is slow", description="Speeds are bad on floor 3", priority="low")
    client = client_for(agent)

    assert client.get("/api/v1/tickets/?priority=urgent").data["count"] == 1
    assert client.get("/api/v1/tickets/?search=wi-fi").data["count"] == 1
    assert client.get("/api/v1/tickets/?unassigned=true").data["count"] == 2
    ordered = client.get("/api/v1/tickets/?ordering=created_at").data["results"]
    assert ordered[0]["subject"] == "Printer jammed"


def test_pagination(customer, agent, client_for):
    for number in range(25):
        services.create_ticket(
            requester=customer, subject=f"Ticket number {number}", description="Some long enough description", priority="low"
        )
    response = client_for(agent).get("/api/v1/tickets/?page_size=10")
    assert response.data["count"] == 25
    assert len(response.data["results"]) == 10
    assert response.data["next"] is not None


# ------------------------------------------------------------- attachments
def test_attachment_upload_and_private_download(ticket, customer, client_for):
    client = client_for(customer)
    upload = SimpleUploadedFile("log.txt", b"hello world", content_type="text/plain")
    response = client.post(f"/api/v1/tickets/{ticket.pk}/attachments/", {"file": upload}, format="multipart")
    assert response.status_code == 201
    assert response.data["original_name"] == "log.txt"
    assert "file" not in response.data  # storage path is never exposed

    download = client.get(f"/api/v1/tickets/{ticket.pk}/attachments/{response.data['id']}/download/")
    assert download.status_code == 200
    assert b"".join(download.streaming_content) == b"hello world"


def test_attachment_with_dangerous_extension_is_rejected(ticket, customer, client_for):
    upload = SimpleUploadedFile("virus.exe", b"MZ...", content_type="application/octet-stream")
    response = client_for(customer).post(f"/api/v1/tickets/{ticket.pk}/attachments/", {"file": upload}, format="multipart")
    assert response.status_code == 400


def test_attachment_too_large_is_rejected(ticket, customer, client_for, settings):
    settings.MAX_ATTACHMENT_MB = 1
    upload = SimpleUploadedFile("big.txt", b"a" * (1024 * 1024 + 1), content_type="text/plain")
    response = client_for(customer).post(f"/api/v1/tickets/{ticket.pk}/attachments/", {"file": upload}, format="multipart")
    assert response.status_code == 400


# ---------------------------------------------------------------- timeline
def test_timeline_is_staff_only_and_complete(ticket, agent, customer, client_for):
    assert client_for(customer).get(f"/api/v1/tickets/{ticket.pk}/timeline/").status_code == 403
    response = client_for(agent).get(f"/api/v1/tickets/{ticket.pk}/timeline/")
    assert response.status_code == 200
    assert response.data[0]["event_type"] == EventType.CREATED


# ------------------------------------------------------------------ notifications
def test_notifications_list_and_mark_read(ticket, manager, client_for):
    client = client_for(manager)
    listing = client.get("/api/v1/notifications/")
    assert listing.data["count"] == 1
    notification_id = listing.data["results"][0]["id"]
    assert client.post(f"/api/v1/notifications/{notification_id}/read/").data["is_read"] is True
    assert client.get("/api/v1/notifications/?is_read=false").data["count"] == 0
