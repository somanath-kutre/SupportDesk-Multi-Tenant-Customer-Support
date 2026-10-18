"""Test settings: fast, isolated, no external services."""
import tempfile

from .settings import *  # noqa: F401,F403
from .settings import REST_FRAMEWORK

CELERY_TASK_ALWAYS_EAGER = True
CELERY_BROKER_URL = "memory://"
CELERY_RESULT_BACKEND = None
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
MEDIA_ROOT = tempfile.mkdtemp(prefix="supportdesk_test_media_")
DEBUG = False
SECURE_SSL_REDIRECT = False

REST_FRAMEWORK = {
    **REST_FRAMEWORK,
    "DEFAULT_THROTTLE_RATES": {"anon": "100000/min", "user": "100000/min", "auth": "100000/min"},
}
