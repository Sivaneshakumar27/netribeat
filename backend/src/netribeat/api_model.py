"""ApiModel: base for every request/response schema (camelCase JSON, snake_case Python)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class ApiModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
        extra="forbid",
    )


class ErrorBody(ApiModel):
    code: str
    message: str
    fields: dict[str, str] | None = None


_ERROR_DESCRIPTIONS = {
    400: "Validation failed (`validation_error` with `fields`) or a bad request",
    401: "Missing, invalid or expired credentials",
    403: "Forbidden (role or CSRF check)",
    404: "Not found (or not visible to you)",
    409: "Conflict with the current state",
    413: "Request too large",
    429: "Too many attempts",
}


def error_responses(*codes: int) -> dict[int | str, dict[str, Any]]:
    """OpenAPI `responses=` entries using the shared Error schema."""
    return {c: {"model": ErrorBody, "description": _ERROR_DESCRIPTIONS[c]} for c in codes}
