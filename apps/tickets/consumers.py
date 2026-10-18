from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from .models import Ticket


class TicketConsumer(AsyncJsonWebsocketConsumer):
    """
    ws://host/ws/tickets/<id>/?token=<access JWT>

    Staff join "ticket_<id>_staff" (see internal notes + SLA alerts);
    customers join "ticket_<id>_public" (public events only).
    """

    async def connect(self):
        user = self.scope.get("user")
        self.ticket_id = self.scope["url_route"]["kwargs"]["ticket_id"]
        self.group = None

        if user is None or user.is_anonymous:
            await self.close(code=4401)  # unauthenticated
            return
        if not await self._can_access(user, self.ticket_id):
            await self.close(code=4403)  # no access to this ticket (or other tenant)
            return

        self.group = f"ticket_{self.ticket_id}_{'staff' if user.is_support_staff else 'public'}"
        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.accept()

    async def disconnect(self, code):
        if getattr(self, "group", None):
            await self.channel_layer.group_discard(self.group, self.channel_name)

    # Handler for messages sent with {"type": "ticket.event", ...}
    async def ticket_event(self, message):
        await self.send_json({"event": message["event"], "payload": message["payload"]})

    @database_sync_to_async
    def _can_access(self, user, ticket_id):
        queryset = Ticket.objects.filter(pk=ticket_id)
        if user.is_superuser:
            return queryset.exists()
        queryset = queryset.filter(organization_id=user.organization_id)
        if not user.is_support_staff:
            queryset = queryset.filter(requester=user)
        return queryset.exists()
