"""TqSdk 历史 K 线与实时快照适配器。"""

import asyncio
import time
from typing import Any

from tapehub_adapter_common.base import BaseAdapter
from tapehub_adapter_common.errors import (
    AdapterError,
    ProviderDisabledError,
    ProviderNotImplementedError,
    QuoteNotReadyError,
    UpstreamError,
)
from tapehub_adapter_common.models import BarQuery, BarsResult, QuoteQuery, QuoteResult
from tapehub_adapter_tqsdk.request_mapper import UPSTREAM_MAX_BARS, build_request, quote_symbol
from tapehub_adapter_tqsdk.response_mapper import to_standard_bars, to_standard_quote
from tapehub_adapter_tqsdk.runtime import RuntimeStatus, TqSdkRuntime

_RUNTIME_REPLACE_GRACE_SECONDS = 120.0
_SNAPSHOT_POLL_INTERVAL = 0.05


class TqsdkAdapter(BaseAdapter):
    def __init__(
        self,
        *,
        auth_user: str = "",
        auth_password: str = "",
        conn_mode: str = "shared",
        max_inflight: int = 16,
        first_snapshot_timeout: float = 5.0,
        subscription_limit: int = 64,
        construct_timeout: float = 30.0,
    ) -> None:
        super().__init__("tqsdk", max_inflight=max_inflight)
        if conn_mode not in ("shared", "per_request"):
            raise ValueError("TAPEHUB_TQSDK_CONN_MODE must be shared or per_request")
        self._auth_user = auth_user.strip()
        self._auth_password = auth_password
        self._conn_mode = conn_mode
        self._max_inflight = max_inflight
        self._first_snapshot_timeout = first_snapshot_timeout
        self._subscription_limit = subscription_limit
        self._construct_timeout = construct_timeout
        self._runtime: TqSdkRuntime | None = None
        self._runtime_lock = asyncio.Lock()
        self._runtime_created_at = 0.0

    async def fetch_bars(self, query: BarQuery) -> BarsResult:
        auth = self._ensure_ready()
        kwargs = build_request(query)
        try:
            if self._conn_mode == "shared":
                runtime = await self._ensure_runtime(auth)
                rows = await runtime.fetch_async(kwargs)
            else:
                rows = await self.call_in_thread(self._fetch_rows_per_request, auth, kwargs)
            bars = to_standard_bars(rows)
        except AdapterError:
            raise
        except Exception as exc:
            raise UpstreamError(
                "tqsdk kline request failed.", details={"provider": "tqsdk"}
            ) from exc
        partial = len(bars) >= UPSTREAM_MAX_BARS and (
            not bars or min(bar.timestamp for bar in bars) > query.start
        )
        window = [bar for bar in bars if query.start <= bar.timestamp <= query.end]
        return BarsResult(bars=window, partial=partial)

    async def fetch_quote(self, query: QuoteQuery) -> QuoteResult:
        auth = self._ensure_ready()
        symbol = quote_symbol(query)
        try:
            if self._conn_mode == "shared":
                runtime = await self._ensure_runtime(auth)
                runtime.subscribe(symbol)
                try:
                    snapshot = await self._await_snapshot(runtime, symbol)
                finally:
                    runtime.unsubscribe(symbol)
            else:
                snapshot = await self.call_in_thread(
                    self._fetch_quote_per_request, auth, symbol
                )
            return QuoteResult(quote=to_standard_quote(snapshot))
        except AdapterError:
            raise
        except Exception as exc:
            raise UpstreamError(
                "tqsdk quote request failed.", details={"provider": "tqsdk"}
            ) from exc

    def shutdown(self) -> None:
        if self._runtime is not None:
            self._runtime.shutdown()

    def _ensure_ready(self) -> tuple[str, str]:
        missing = []
        if not self._auth_user:
            missing.append("TAPEHUB_TQSDK_AUTH_USER")
        if not self._auth_password.strip():
            missing.append("TAPEHUB_TQSDK_AUTH_PASSWORD")
        if missing:
            raise ProviderDisabledError(
                "TqSdk auth is not fully configured.",
                details={"provider": "tqsdk", "missing_credentials": missing},
            )
        return self._auth_user, self._auth_password

    async def _ensure_runtime(self, auth: tuple[str, str]) -> TqSdkRuntime:
        async with self._runtime_lock:
            runtime = self._runtime
            if runtime is not None:
                replace = runtime.status is RuntimeStatus.FATAL or (
                    runtime.status is not RuntimeStatus.READY
                    and time.monotonic() - self._runtime_created_at > _RUNTIME_REPLACE_GRACE_SECONDS
                )
                if replace:
                    runtime.shutdown(timeout=0)
                    runtime = None
                    self._runtime = None
            if runtime is None:
                runtime = TqSdkRuntime(
                    auth_user=auth[0],
                    auth_password=auth[1],
                    max_inflight=self._max_inflight,
                    construct_timeout=self._construct_timeout,
                    subscription_limit=self._subscription_limit,
                )
                try:
                    await self.call_in_thread(
                        runtime.start, abandon_on_cancel=False
                    )
                except BaseException:
                    runtime.shutdown(timeout=0)
                    raise
                self._runtime = runtime
                self._runtime_created_at = time.monotonic()
            return runtime

    async def _await_snapshot(self, runtime: TqSdkRuntime, symbol: str) -> dict[str, Any]:
        deadline = time.monotonic() + self._first_snapshot_timeout
        while True:
            snapshot = runtime.latest(symbol)
            if snapshot is not None:
                return snapshot
            if time.monotonic() >= deadline:
                raise QuoteNotReadyError(
                    "Quote snapshot not ready within the first-packet timeout.",
                    details={
                        "provider": "tqsdk",
                        "symbol": symbol,
                        "timeout_s": self._first_snapshot_timeout,
                    },
                )
            await asyncio.sleep(_SNAPSHOT_POLL_INTERVAL)

    def _fetch_rows_per_request(
        self, auth: tuple[str, str], kwargs: dict[str, Any]
    ) -> list[dict[str, Any]]:
        try:
            from tqsdk import TqApi, TqAuth
        except ImportError as exc:
            raise ProviderNotImplementedError(
                "Provider SDK 'tqsdk' is not installed.",
                details={"provider": "tqsdk", "sdk": "tqsdk"},
            ) from exc
        api = TqApi(auth=TqAuth(auth[0], auth[1]), disable_print=True)
        try:
            frame = api.get_kline_serial(**kwargs)
            return [] if frame is None else list(frame.to_dict("records"))
        finally:
            api.close()

    def _fetch_quote_per_request(
        self, auth: tuple[str, str], symbol: str
    ) -> dict[str, Any]:
        try:
            from tqsdk import TqApi, TqAuth
        except ImportError as exc:
            raise ProviderNotImplementedError(
                "Provider SDK 'tqsdk' is not installed.",
                details={"provider": "tqsdk", "sdk": "tqsdk"},
            ) from exc
        api = TqApi(auth=TqAuth(auth[0], auth[1]), disable_print=True)
        try:
            return dict(api.get_quote(symbol))
        finally:
            api.close()
