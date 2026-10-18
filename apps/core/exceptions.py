"""Domain exceptions + one consistent JSON error envelope for the whole API."""
import logging

from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

logger = logging.getLogger(__name__)


class ConflictError(APIException):
    """Optimistic-concurrency failure (HTTP 409)."""

    status_code = status.HTTP_409_CONFLICT
    default_detail = "The resource was modified by someone else. Reload and retry."
    default_code = "conflict"


class InvalidTransition(APIException):
    """Illegal ticket state-machine transition (HTTP 400)."""

    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "This status change is not allowed."
    default_code = "invalid_transition"


_CODES = {
    400: "validation_error",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    429: "throttled",
}


def custom_exception_handler(exc, context):
    """
    Every error looks like:
        {"error": {"code": "...", "message": "...", "details": {...} | null}}
    Unhandled exceptions are logged with a traceback and returned as a clean 500.
    """
    response = drf_exception_handler(exc, context)

    if response is None:
        logger.exception("Unhandled exception in %s", context.get("view"), exc_info=exc)
        return Response(
            {"error": {"code": "server_error", "message": "Internal server error", "details": None}},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    data = response.data
    if isinstance(data, dict) and "detail" in data:
        message, details = str(data["detail"]), None
    else:
        message, details = "Validation failed" if response.status_code == 400 else "Request failed", data

    code = exc.default_code if isinstance(exc, (ConflictError, InvalidTransition)) else None
    response.data = {
        "error": {
            "code": code or _CODES.get(response.status_code, "error"),
            "message": message,
            "details": details,
        }
    }
    return response
