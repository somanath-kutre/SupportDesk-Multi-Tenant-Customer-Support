"""python manage.py seed_demo  ->  demo organization, users and tickets (idempotent)."""
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounts.models import Organization, Role, User
from apps.tickets import services
from apps.tickets.models import Priority, Status, Ticket

PASSWORD = "Pass@12345"

USERS = [
    ("admin", Role.ORG_ADMIN),
    ("manager", Role.MANAGER),
    ("agent1", Role.AGENT),
    ("agent2", Role.AGENT),
    ("customer1", Role.CUSTOMER),
    ("customer2", Role.CUSTOMER),
]

TICKETS = [
    ("customer1", "Cannot log in to the dashboard", "I get an error after entering my password.", Priority.HIGH),
    ("customer1", "Invoice shows wrong amount", "March invoice is higher than the agreed plan.", Priority.MEDIUM),
    ("customer2", "Production API is down", "All requests return 502 since 10:00.", Priority.URGENT),
    ("customer2", "Feature request: dark mode", "Please add a dark theme to the portal.", Priority.LOW),
]


class Command(BaseCommand):
    help = "Create a demo organization with users, SLA policies and sample tickets."

    @transaction.atomic
    def handle(self, *args, **options):
        org, created = Organization.objects.get_or_create(slug="acme", defaults={"name": "Acme Corp"})
        if created:
            services.create_default_sla_policies(org)

        users = {}
        for username, role in USERS:
            user, was_created = User.objects.get_or_create(
                username=username,
                defaults={"email": f"{username}@acme.test", "organization": org, "role": role},
            )
            if was_created:
                user.set_password(PASSWORD)
                user.save()
            users[username] = user

        if not Ticket.objects.filter(organization=org).exists():
            for requester, subject, description, priority in TICKETS:
                ticket = services.create_ticket(
                    requester=users[requester], subject=subject, description=description, priority=priority
                )
                if priority == Priority.URGENT:
                    services.assign_ticket(ticket=ticket, actor=users["manager"], assignee_id=users["agent1"].pk)
                    services.add_comment(ticket=ticket, author=users["agent1"], body="Looking into it right now.")
                    services.change_status(ticket=ticket, actor=users["agent1"], new_status=Status.IN_PROGRESS)

        self.stdout.write(self.style.SUCCESS("Demo data ready."))
        self.stdout.write(f"Organization slug: acme | password for every demo user: {PASSWORD}")
        self.stdout.write("Users: " + ", ".join(u for u, _ in USERS))
