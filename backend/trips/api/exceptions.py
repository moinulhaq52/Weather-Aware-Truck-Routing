"""Uniform JSON error responses.

Every error has the shape ``{"error": {"code": str, "message": str, "details"?: ...}}``
so the frontend can show a friendly message without parsing DRF's varied default formats.
"""

import logging

from rest_framework import status
from rest_framework.exceptions import APIException, Throttled, ValidationError
from rest_framework.response import Response
from rest_framework.views import exception_handler

logger = logging.getLogger(__name__)


class UpstreamUnavailable(APIException):
    """A third-party provider (routing / weather / geocoding) failed or timed out."""

    status_code = status.HTTP_502_BAD_GATEWAY
    default_code = "upstream_unavailable"
    default_detail = "A third-party service is unavailable. Please try again shortly."


class PlanUnprocessable(APIException):
    """Valid input that can't be planned (no route, too long, beyond forecast...)."""

    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    default_code = "unprocessable"
    default_detail = "This trip cannot be planned."


def api_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is None:
        # Unexpected exception: log it with the stack trace, never leak internals to the client.
        logger.exception("Unhandled API error", exc_info=exc)
        return Response(
            {"error": {"code": "internal_error", "message": "Something went wrong on our side."}},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    if isinstance(exc, ValidationError):
        body = {
            "error": {
                "code": "invalid_input",
                "message": "Some inputs are invalid.",
                "details": response.data,
            }
        }
    elif isinstance(exc, Throttled):
        body = {
            "error": {
                "code": "rate_limited",
                "message": f"Too many requests. Try again in {int(exc.wait or 1)} s.",
            }
        }
    else:
        detail = getattr(exc, "detail", str(exc))
        code = exc.get_codes() if isinstance(exc, APIException) else "error"
        body = {
            "error": {"code": code if isinstance(code, str) else "error", "message": str(detail)}
        }
    response.data = body
    return response
