"""AppError hierarchy. The global handler in main.py maps each to the `Error` schema."""

from __future__ import annotations


class AppError(Exception):
    status_code: int = 500
    code: str = "internal_error"
    default_message: str = "Something went wrong"

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        fields: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.message = message or self.default_message
        if code is not None:
            self.code = code
        self.fields = fields
        self.headers = headers
        super().__init__(self.message)


class ValidationFailed(AppError):
    status_code = 400
    code = "validation_error"
    default_message = "Some fields are invalid"


class BadRequest(AppError):
    status_code = 400
    code = "bad_request"
    default_message = "The request could not be processed"


class Unauthorized(AppError):
    status_code = 401
    code = "unauthorized"
    default_message = "Sign in to continue"


class InvalidCredentials(Unauthorized):
    code = "invalid_credentials"
    default_message = "Email or password is incorrect"


class Forbidden(AppError):
    status_code = 403
    code = "forbidden"
    default_message = "You don't have permission to do that"


class NotFound(AppError):
    status_code = 404
    code = "not_found"
    default_message = "Not found"


class Conflict(AppError):
    status_code = 409
    code = "conflict"
    default_message = "The request conflicts with the current state"


class PayloadTooLarge(AppError):
    status_code = 413
    code = "payload_too_large"
    default_message = "The request is too large"


class TooManyAttempts(AppError):
    status_code = 429
    code = "too_many_attempts"
    default_message = "Too many attempts. Please wait and try again"


class ServiceUnavailable(AppError):
    status_code = 503
    code = "service_unavailable"
    default_message = "A required service is unavailable"
