"""Baostock 全局会话与历史 K 线调用。"""

import logging
import threading
from typing import Any

from tapehub_adapter_baostock.request_mapper import build_request
from tapehub_adapter_baostock.response_mapper import to_standard_bars
from tapehub_adapter_common.base import BaseAdapter
from tapehub_adapter_common.errors import (
    ProviderNotImplementedError,
    UpstreamError,
    truncate_message,
)
from tapehub_adapter_common.models import BarQuery, BarsResult

logger = logging.getLogger(__name__)
_UPSTREAM_ROW_LIMIT = 5000
_SESSION_LOCK = threading.Lock()
_SESSION_LOGGED_IN = False
_SESSION_OWNER: Any = None
_NO_LOGIN_ERROR_CODE = "10001001"
_NETWORK_ERROR_CODE_PREFIX = "10002"


def _import_sdk() -> Any:
    try:
        import baostock as bs
    except ImportError as exc:
        raise ProviderNotImplementedError(
            "Provider SDK 'baostock' is not installed.",
            details={"provider": "baostock", "sdk": "baostock"},
        ) from exc
    return bs


def _error_code(result: Any) -> str:
    return str(getattr(result, "error_code", "") or "")


def _error_msg(result: Any) -> str:
    return str(getattr(result, "error_msg", "") or "")


def _upstream_error(message: str, result: Any) -> UpstreamError:
    code = _error_code(result)
    logger.warning("baostock upstream error: error_code=%s", code)
    return UpstreamError(
        message,
        details={
            "provider": "baostock",
            "upstream_error_code": code,
            "upstream_error_msg": truncate_message(_error_msg(result)),
        },
    )


def _ensure_session(bs: Any) -> None:
    global _SESSION_LOGGED_IN, _SESSION_OWNER
    if _SESSION_LOGGED_IN and _SESSION_OWNER is bs:
        return
    result = bs.login()
    if _error_code(result) != "0":
        _SESSION_LOGGED_IN = False
        _SESSION_OWNER = None
        raise _upstream_error("baostock login failed.", result)
    _SESSION_LOGGED_IN = True
    _SESSION_OWNER = bs


def _force_relogin(bs: Any) -> None:
    global _SESSION_LOGGED_IN
    _SESSION_LOGGED_IN = False
    _ensure_session(bs)


def _recoverable(code: str) -> bool:
    return code == _NO_LOGIN_ERROR_CODE or code.startswith(_NETWORK_ERROR_CODE_PREFIX)


class BaostockAdapter(BaseAdapter):
    def __init__(self, *, max_inflight: int = 4) -> None:
        super().__init__("baostock", max_inflight=max_inflight)

    async def fetch_bars(self, query: BarQuery) -> BarsResult:
        return await self.call_in_thread(self._fetch_sync, query)

    def _fetch_sync(self, query: BarQuery) -> BarsResult:
        kwargs = build_request(query.operation, query)
        bs = _import_sdk()
        with _SESSION_LOCK:
            _ensure_session(bs)
            result = self._query_with_recovery(bs, kwargs)
            rows = self._collect_rows(result)
        bars = to_standard_bars(query.asset_type, query.interval, rows)
        window = [bar for bar in bars if query.start <= bar.timestamp <= query.end]
        return BarsResult(bars=window, partial=len(rows) >= _UPSTREAM_ROW_LIMIT)

    def _query_with_recovery(self, bs: Any, kwargs: dict[str, str]) -> Any:
        result = bs.query_history_k_data_plus(**kwargs)
        code = _error_code(result)
        if code == "0":
            return result
        if _recoverable(code):
            _force_relogin(bs)
            result = bs.query_history_k_data_plus(**kwargs)
            code = _error_code(result)
            if code == "0":
                return result
        raise _upstream_error("baostock query failed.", result)

    def _collect_rows(self, result: Any) -> list[dict[str, Any]]:
        fields = list(getattr(result, "fields", None) or [])
        rows: list[dict[str, Any]] = []
        while result.next():
            values = result.get_row_data()
            if len(fields) != len(values):
                raise UpstreamError(
                    "baostock response row does not match its fields.",
                    details={"provider": "baostock", "field": "fields"},
                )
            rows.append(dict(zip(fields, values, strict=True)))
        return rows
