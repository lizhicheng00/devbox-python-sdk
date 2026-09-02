from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, NoReturn

import httpx


@dataclass(frozen=True, slots=True)
class ErrorDetail:
    code: str
    message: str
    target: str | None = None


class DevBoxError(Exception):
    """Base exception returned by the DevBox SDK."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "",
        status_code: int | None = None,
        target: str | None = None,
        details: tuple[ErrorDetail, ...] = (),
        request_id: str | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.target = target
        self.details = details
        self.request_id = request_id
        self.retry_after = retry_after

    def __str__(self) -> str:
        suffix = f" [{self.code}]" if self.code else ""
        return self.message + suffix


class ConfigurationError(DevBoxError):
    pass


class AuthenticationError(DevBoxError):
    pass


class PermissionDeniedError(DevBoxError):
    pass


class ValidationError(DevBoxError):
    pass


class NotFoundError(DevBoxError):
    pass


class ConflictError(DevBoxError):
    pass


class RateLimitError(DevBoxError):
    pass


class RequestTimeoutError(DevBoxError):
    pass


class ServiceUnavailableError(DevBoxError):
    pass


class ProtocolError(DevBoxError):
    pass


class CommandExitError(DevBoxError):
    def __init__(self, result: Any) -> None:
        super().__init__(f"command exited with status {result.exit_code}", code="COMMAND_EXIT")
        self.result = result


def transport_error(error: Exception) -> DevBoxError:
    if isinstance(error, httpx.TimeoutException):
        return RequestTimeoutError("request timed out")
    if isinstance(error, httpx.HTTPError):
        return ServiceUnavailableError("unable to reach DevBox service")
    if isinstance(error, DevBoxError):
        return error
    return ServiceUnavailableError("DevBox request failed")


def raise_for_response(response: httpx.Response) -> NoReturn:
    payload: Mapping[str, Any] = {}
    try:
        decoded = response.json()
        if isinstance(decoded, Mapping):
            payload = decoded
    except ValueError:
        pass

    raw_error = payload.get("error", payload)
    error = raw_error if isinstance(raw_error, Mapping) else payload
    message = str(
        error.get("message")
        or error.get("error_message")
        or f"request failed with status {response.status_code}"
    )
    code = str(
        error.get("code") or error.get("error_code") or error.get("error") or response.status_code
    )
    target = str(error["target"]) if error.get("target") is not None else None
    details = _details(error.get("details"))
    request_id = response.headers.get("X-Request-Id") or response.headers.get("X-Request-ID")
    retry_after = _retry_after(response.headers.get("Retry-After"))
    exception_type: type[DevBoxError] = {
        400: ValidationError,
        401: AuthenticationError,
        403: PermissionDeniedError,
        404: NotFoundError,
        408: RequestTimeoutError,
        409: ConflictError,
        422: ValidationError,
        429: RateLimitError,
    }.get(response.status_code, DevBoxError)
    if response.status_code >= 500:
        exception_type = ServiceUnavailableError
    raise exception_type(
        message,
        code=code,
        status_code=response.status_code,
        target=target,
        details=details,
        request_id=request_id,
        retry_after=retry_after,
    )


def _details(value: object) -> tuple[ErrorDetail, ...]:
    if not isinstance(value, list):
        return ()
    result: list[ErrorDetail] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        result.append(
            ErrorDetail(
                code=str(item.get("code", "")),
                message=str(item.get("message", "")),
                target=str(item["target"]) if item.get("target") is not None else None,
            )
        )
    return tuple(result)


def _retry_after(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None
