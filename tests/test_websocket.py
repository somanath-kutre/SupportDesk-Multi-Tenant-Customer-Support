import pytest
from asgiref.sync import sync_to_async
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from rest_framework_simplejwt.tokens import AccessToken

from apps.tickets import services
from apps.tickets.middleware import JWTAuthMiddleware
from apps.tickets.routing import websocket_urlpatterns

application = JWTAuthMiddleware(URLRouter(websocket_urlpatterns))


def _url(ticket_id, user=None):
    token = f"?token={AccessToken.for_user(user)}" if user else ""
    return f"/ws/tickets/{ticket_id}/{token}"


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_connection_without_token_is_rejected(ticket):
    communicator = WebsocketCommunicator(application, _url(ticket.pk))
    connected, code = await communicator.connect()
    assert connected is False
    assert code == 4401


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_other_tenant_cannot_subscribe(ticket, other_customer):
    communicator = WebsocketCommunicator(application, _url(ticket.pk, other_customer))
    connected, code = await communicator.connect()
    assert connected is False
    assert code == 4403


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_customer_gets_public_comments_but_never_internal_notes(ticket, customer, agent):
    communicator = WebsocketCommunicator(application, _url(ticket.pk, customer))
    connected, _ = await communicator.connect()
    assert connected is True

    await sync_to_async(services.add_comment)(ticket=ticket, author=agent, body="internal only", is_internal=True)
    assert await communicator.receive_nothing(timeout=0.3) is True

    await sync_to_async(services.add_comment)(ticket=ticket, author=agent, body="Hello customer")
    message = await communicator.receive_json_from(timeout=2)
    assert message["event"] == "comment_added"
    assert message["payload"]["body"] == "Hello customer"

    await communicator.disconnect()
