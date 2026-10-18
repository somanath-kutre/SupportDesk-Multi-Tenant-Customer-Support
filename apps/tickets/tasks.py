"""
Celery tasks. Kept thin on purpose: they import business logic lazily so that
services -> notifications -> tasks never forms an import cycle.
"""
import logging

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mass_mail

logger = logging.getLogger(__name__)


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 3})
def send_notification_emails(self, recipients, subject, message):
    """One email per recipient (never expose recipients' addresses to each other)."""
    messages = [(subject, message, settings.DEFAULT_FROM_EMAIL, [address]) for address in recipients]
    return send_mass_mail(messages, fail_silently=False)


@shared_task
def check_sla_breaches():
    """Celery Beat: runs every minute and flags tickets that missed an SLA target."""
    from .sla import run_sla_check

    result = run_sla_check()
    logger.info("SLA check finished: %s", result)
    return result


@shared_task
def auto_close_resolved_tickets():
    """Celery Beat (nightly): close tickets that stayed RESOLVED for N days."""
    from .sla import auto_close_resolved

    closed = auto_close_resolved()
    logger.info("Auto-closed %s resolved tickets", closed)
    return closed
