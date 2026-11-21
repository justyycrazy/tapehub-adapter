"""内部协议错误；只向 TapeHub 暴露受控错误码与摘要。"""

from typing import Any


class AdapterError(Exception):
    code = "UPSTREAM_ERROR"
    status = 502

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        code: str | None = None,
        status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}
        if code is not None:
            self.code = code
        if status is not None:
            self.status = status


class InvalidRequestError(AdapterError):
    code = "INVALID_REQUEST"
    status = 422


class ProviderDisabledError(AdapterError):
    code = "PROVIDER_DISABLED"
    status = 409


class ProviderNotImplementedError(AdapterError):
    code = "PROVIDER_NOT_IMPLEMENTED"
    status = 501


class UnsupportedCapabilityError(AdapterError):
    code = "UNSUPPORTED_CAPABILITY"
    status = 422


class UpstreamTimeoutError(AdapterError):
    code = "UPSTREAM_TIMEOUT"
    status = 504


class UpstreamRateLimitedError(AdapterError):
    code = "UPSTREAM_RATE_LIMITED"
    status = 429


class UpstreamError(AdapterError):
    code = "UPSTREAM_ERROR"
    status = 502


class QuoteNotReadyError(AdapterError):
    code = "QUOTE_NOT_READY"
    status = 408


class ConcurrencyLimitError(AdapterError):
    code = "CONCURRENCY_LIMIT"
    status = 429


def truncate_message(value: object, limit: int = 200) -> str:
    text = "" if value is None else str(value)
    if len(text) <= limit:
        return text
    return text[:limit] + "…[truncated]"
