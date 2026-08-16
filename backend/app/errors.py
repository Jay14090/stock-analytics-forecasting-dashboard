"""Error types and the JSON error envelope.

Every failure leaving the API has the same shape, so the frontend only ever
writes one error path::

    {"error": {"code": "not_found", "message": "...", "details": {...}}}
"""

from __future__ import annotations

import logging
from typing import Any

from flask import Flask, jsonify
from marshmallow import ValidationError
from werkzeug.exceptions import HTTPException

logger = logging.getLogger(__name__)


class APIError(Exception):
    """Base class for errors that map onto a deliberate HTTP response."""

    status_code = 500
    code = "internal_error"
    message = "An unexpected error occurred."

    def __init__(
        self,
        message: str | None = None,
        *,
        details: dict[str, Any] | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message or self.message)
        self.message = message or self.message
        self.details = details or {}
        if status_code is not None:
            self.status_code = status_code

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details:
            payload["details"] = self.details
        return {"error": payload}


class BadRequestError(APIError):
    status_code = 400
    code = "bad_request"
    message = "The request could not be understood."


class NotFoundError(APIError):
    status_code = 404
    code = "not_found"
    message = "The requested resource does not exist."


class ConflictError(APIError):
    status_code = 409
    code = "conflict"
    message = "The resource already exists."


class UpstreamError(APIError):
    """A dependency we do not control (Yahoo Finance) failed or timed out."""

    status_code = 502
    code = "upstream_error"
    message = "The market data provider is unavailable."


class InsufficientDataError(APIError):
    """The symbol resolved, but there is not enough history to do the work."""

    status_code = 422
    code = "insufficient_data"
    message = "Not enough historical data to complete this operation."


class ModelUnavailableError(APIError):
    """Forecasting was requested but the deep-learning stack is missing."""

    status_code = 503
    code = "model_unavailable"
    message = "The forecasting engine is not available on this deployment."


def register_error_handlers(app: Flask) -> None:
    """Attach handlers that normalise every failure into the envelope."""

    @app.errorhandler(APIError)
    def _handle_api_error(exc: APIError):
        if exc.status_code >= 500:
            logger.error("api_error code=%s message=%s", exc.code, exc.message)
        else:
            logger.info("api_error code=%s message=%s", exc.code, exc.message)
        return jsonify(exc.to_dict()), exc.status_code

    @app.errorhandler(ValidationError)
    def _handle_validation_error(exc: ValidationError):
        error = BadRequestError(
            "Request validation failed.", details={"fields": exc.messages}
        )
        return jsonify(error.to_dict()), error.status_code

    @app.errorhandler(HTTPException)
    def _handle_http_exception(exc: HTTPException):
        payload = {
            "error": {
                "code": (exc.name or "http_error").lower().replace(" ", "_"),
                "message": exc.description or "Request failed.",
            }
        }
        return jsonify(payload), exc.code or 500

    @app.errorhandler(Exception)
    def _handle_unexpected(exc: Exception):
        logger.exception("unhandled_exception: %s", exc)
        error = APIError()
        return jsonify(error.to_dict()), error.status_code
