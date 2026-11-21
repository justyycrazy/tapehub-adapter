"""TqSdk 单线程共享 Runtime：历史取数、订阅快照与代际回收。"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import queue
import threading
import time
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from tapehub_adapter_common.errors import ConcurrencyLimitError, UpstreamError
from tapehub_adapter_common.models import CN_TIMEZONE

_WATCHDOG_STREAK_LIMIT = 3
_REBUILD_BACKOFF_SECONDS = 2.0
_CONSTRUCT_BACKOFF_CAP_SECONDS = 60.0
logger = logging.getLogger("tapehub_adapter_tqsdk.runtime")


def _scrub(text: str, values: tuple[str, ...]) -> str:
    for value in values:
        if value:
            text = text.replace(value, "***")
    return text


class _GenerationReset(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class RuntimeStatus(StrEnum):
    IDLE = "idle"
    STARTING = "starting"
    READY = "ready"
    RECYCLING = "recycling"
    FATAL = "fatal"


class _StopSignal:
    pass


class _Subscribe:
    def __init__(self, symbol: str) -> None:
        self.symbol = symbol


class TqSdkRuntime:
    def __init__(
        self,
        *,
        auth_user: str,
        auth_password: str,
        max_inflight: int = 16,
        construct_timeout: float = 30.0,
        subscription_limit: int = 64,
    ) -> None:
        self._auth_user = auth_user
        self._auth_password = auth_password
        self._scrub_values = (auth_user, auth_password)
        self._max_inflight = max_inflight
        self._construct_timeout = construct_timeout
        self._subscription_limit = subscription_limit
        self._jobs: queue.Queue[
            tuple[dict[str, Any], concurrent.futures.Future] | _StopSignal | _Subscribe
        ] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self._stop_requested = False
        self._status = RuntimeStatus.IDLE
        self._last_error: Exception | None = None
        self._inflight = 0
        self._pending: set[concurrent.futures.Future] = set()
        self._generation = 0
        self._attempt = 0
        self._peek_attr_missing_logged = False
        self._sub_refs: dict[str, int] = {}
        self._live_quotes: dict[str, Any] = {}
        self._dormant_quotes: dict[str, Any] = {}
        self._snapshots: dict[str, dict[str, Any]] = {}

    @property
    def status(self) -> RuntimeStatus:
        with self._lock:
            return self._status

    @property
    def generation(self) -> int:
        with self._lock:
            return self._generation

    def start(self) -> None:
        with self._lock:
            if self._thread is not None or self._stop_requested:
                return
            self._status = RuntimeStatus.STARTING
            self._thread = threading.Thread(
                target=self._thread_main, name="tqsdk-runtime", daemon=True
            )
            self._thread.start()
        if not self._ready.wait(self._construct_timeout):
            with self._lock:
                self._last_error = UpstreamError(
                    "tqsdk runtime construction timed out.",
                    details={"timeout_s": self._construct_timeout},
                )

    def fetch(self, kwargs: dict[str, Any]) -> concurrent.futures.Future[list[dict[str, Any]]]:
        with self._lock:
            thread = self._thread
            if (
                self._status in (RuntimeStatus.READY, RuntimeStatus.RECYCLING)
                and thread is not None
                and not thread.is_alive()
            ):
                self._status = RuntimeStatus.FATAL
            if self._status in (RuntimeStatus.IDLE, RuntimeStatus.STARTING):
                raise UpstreamError("tqsdk runtime is not ready.")
            if self._status is RuntimeStatus.FATAL:
                reason = (
                    _scrub(str(self._last_error), self._scrub_values)
                    if self._last_error
                    else "unknown"
                )
                raise UpstreamError(
                    "tqsdk runtime is in fatal state.", details={"reason": reason}
                )
            if self._inflight >= self._max_inflight:
                raise ConcurrencyLimitError(
                    "tqsdk runtime inflight limit reached.",
                    details={"provider": "tqsdk", "limit": self._max_inflight},
                )
            self._inflight += 1
            cf: concurrent.futures.Future[list[dict[str, Any]]] = concurrent.futures.Future()
            self._pending.add(cf)
        self._jobs.put((kwargs, cf))
        return cf

    async def fetch_async(self, kwargs: dict[str, Any]) -> list[dict[str, Any]]:
        return await asyncio.wrap_future(self.fetch(kwargs))

    def subscribe(self, symbol: str) -> None:
        with self._lock:
            if self._status in (RuntimeStatus.IDLE, RuntimeStatus.STARTING):
                raise UpstreamError("tqsdk runtime is not ready.")
            if self._status is RuntimeStatus.FATAL:
                raise UpstreamError("tqsdk runtime is in fatal state.")
            refs = self._sub_refs.get(symbol, 0)
            self._sub_refs[symbol] = refs + 1
            if refs == 0 and symbol not in self._live_quotes:
                self._jobs.put(_Subscribe(symbol))

    def unsubscribe(self, symbol: str) -> None:
        with self._lock:
            refs = self._sub_refs.get(symbol, 0)
            if refs <= 1:
                self._sub_refs.pop(symbol, None)
                quote = self._live_quotes.pop(symbol, None)
                self._snapshots.pop(symbol, None)
                if quote is not None:
                    self._dormant_quotes[symbol] = quote
            else:
                self._sub_refs[symbol] = refs - 1

    def latest(self, symbol: str) -> dict[str, Any] | None:
        with self._lock:
            return self._snapshots.get(symbol)

    def shutdown(self, timeout: float = 10.0) -> None:
        with self._lock:
            self._stop_requested = True
        self._jobs.put(_StopSignal())
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout)

    def _thread_main(self) -> None:
        try:
            self._thread_main_inner()
        except Exception as exc:
            with self._lock:
                self._last_error = exc
                self._status = RuntimeStatus.FATAL
            scrubbed = _scrub(repr(exc), self._scrub_values)
            logger.error("tqsdk runtime thread died: %s", scrubbed)
            self._ready.set()
            self._fail_inflight(f"tqsdk runtime thread died: {scrubbed}")

    def _thread_main_inner(self) -> None:
        from tqsdk import TqApi, TqAuth

        backoff = 0.0
        while not self._stop_requested:
            if backoff:
                self._sleep_interruptible(backoff)
                backoff = 0.0
                continue
            with self._lock:
                self._status = RuntimeStatus.RECYCLING
            gen_loop = asyncio.SelectorEventLoop()
            asyncio.set_event_loop(gen_loop)
            try:
                api = TqApi(
                    auth=TqAuth(self._auth_user, self._auth_password),
                    disable_print=True,
                    loop=gen_loop,
                )
            except Exception as exc:
                gen_loop.close()
                asyncio.set_event_loop(None)
                with self._lock:
                    self._last_error = exc
                    self._attempt += 1
                    attempt = self._attempt
                self._ready.set()
                self._fail_inflight("tqsdk runtime construction failed")
                backoff = min(
                    _REBUILD_BACKOFF_SECONDS * (2 ** min(attempt - 1, 5)),
                    _CONSTRUCT_BACKOFF_CAP_SECONDS,
                )
                logger.warning(
                    "tqsdk runtime construction failed (attempt %d): %s; retrying in %.1fs",
                    attempt,
                    _scrub(repr(exc), self._scrub_values),
                    backoff,
                )
                continue
            with self._lock:
                self._generation += 1
                self._status = RuntimeStatus.READY
                self._last_error = None
                self._attempt = 0
                generation = self._generation
            logger.info("tqsdk runtime generation %d ready", generation)
            self._ready.set()
            self._on_generation_ready()
            try:
                self._tick_loop(api, self._next_recycle_ts())
                self._fail_inflight("tqsdk runtime stopped")
                self._close_api(api)
                asyncio.set_event_loop(None)
                if not gen_loop.is_closed():
                    gen_loop.close()
                return
            except _GenerationReset as exc:
                reason = exc.reason
            except Exception as exc:
                reason = f"unexpected tick-loop error: {_scrub(repr(exc), self._scrub_values)}"
                with self._lock:
                    self._last_error = exc
            self._fail_inflight(f"tqsdk runtime recycling: {reason}")
            self._close_api(api)
            if not gen_loop.is_closed():
                gen_loop.close()
            asyncio.set_event_loop(None)
            backoff = _REBUILD_BACKOFF_SECONDS

    def _tick_loop(self, api: Any, next_recycle: float) -> None:
        wait_exc_streak = 0
        silent_ticks = 0
        while not self._stop_requested:
            self._drain_jobs(api)
            if time.time() >= next_recycle:
                raise _GenerationReset("cross-trading-day recycle (CN 04:00)")
            if self._dormant_subscription_recycle_due():
                raise _GenerationReset("dormant subscription recycle")
            if hasattr(api, "_pending_peek"):
                api._pending_peek = False
            elif not self._peek_attr_missing_logged:
                self._peek_attr_missing_logged = True
                logger.error("tqsdk _pending_peek attribute missing; quote pushes may stall")
            with self._lock:
                busy = self._inflight > 0 or not self._jobs.empty() or bool(self._live_quotes)
            tick = 0.05 if busy else (0.5 if silent_ticks < 3 else 2.0)
            try:
                got_data = api.wait_update(deadline=time.time() + tick)
                wait_exc_streak = 0
                silent_ticks = 0 if got_data else min(silent_ticks + 1, 4)
                if got_data:
                    self._publish_changed_snapshots(api)
            except Exception as exc:
                with self._lock:
                    wait_exc_streak += 1
                    self._last_error = exc
                if wait_exc_streak >= _WATCHDOG_STREAK_LIMIT:
                    raise _GenerationReset("watchdog: consecutive wait_update failures") from exc

    def _drain_jobs(self, api: Any) -> None:
        while True:
            try:
                item = self._jobs.get_nowait()
            except queue.Empty:
                return
            if isinstance(item, _StopSignal):
                self._jobs.put(item)
                return
            if isinstance(item, _Subscribe):
                self._handle_subscribe(api, item.symbol)
                continue
            kwargs, cf = item
            api.create_task(self._fetch_coro(api, kwargs, cf))

    def _handle_subscribe(self, api: Any, symbol: str) -> None:
        with self._lock:
            if symbol in self._live_quotes:
                return
            quote = self._dormant_quotes.pop(symbol, None)
            refs = self._sub_refs.get(symbol, 0)
            if quote is not None and refs > 0:
                self._live_quotes[symbol] = quote
                self._snapshots[symbol] = self._stamp_snapshot(quote)
            elif quote is not None:
                self._dormant_quotes[symbol] = quote
        if quote is not None or refs <= 0:
            return
        api.create_task(self._subscribe_coro(api, symbol))

    async def _subscribe_coro(self, api: Any, symbol: str) -> None:
        try:
            quote = await api.get_quote(symbol)
        except Exception as exc:
            logger.warning(
                "tqsdk quote subscribe failed for %s: %s",
                symbol,
                _scrub(repr(exc), self._scrub_values),
            )
            with self._lock:
                self._last_error = exc
            return
        with self._lock:
            if self._sub_refs.get(symbol, 0) > 0:
                self._live_quotes[symbol] = quote
                self._snapshots[symbol] = self._stamp_snapshot(quote)
            else:
                self._dormant_quotes[symbol] = quote

    def _publish_changed_snapshots(self, api: Any) -> None:
        with self._lock:
            live = list(self._live_quotes.items())
        for symbol, quote in live:
            try:
                if not api.is_changing(quote):
                    continue
                snapshot = self._stamp_snapshot(quote)
            except Exception as exc:
                logger.warning(
                    "tqsdk is_changing failed for %s: %s",
                    symbol,
                    _scrub(repr(exc), self._scrub_values),
                )
                continue
            with self._lock:
                if symbol in self._live_quotes:
                    self._snapshots[symbol] = snapshot

    def _on_generation_ready(self) -> None:
        with self._lock:
            active = [symbol for symbol, refs in self._sub_refs.items() if refs > 0]
            self._live_quotes.clear()
            self._dormant_quotes.clear()
            self._snapshots.clear()
        for symbol in active:
            self._jobs.put(_Subscribe(symbol))

    def _dormant_subscription_recycle_due(self) -> bool:
        if self._subscription_limit <= 0:
            return False
        with self._lock:
            return len(self._dormant_quotes) >= self._subscription_limit

    async def _fetch_coro(
        self,
        api: Any,
        kwargs: dict[str, Any],
        cf: concurrent.futures.Future[list[dict[str, Any]]],
    ) -> None:
        try:
            if cf.cancelled():
                return
            try:
                frame = await api.get_kline_serial(**kwargs)
                if not cf.done():
                    cf.set_result(list(frame.to_dict("records")))
            except Exception as exc:
                if not cf.done():
                    cf.set_exception(exc)
        finally:
            with self._lock:
                self._inflight = max(0, self._inflight - 1)
                self._pending.discard(cf)

    def _fail_inflight(self, reason: str) -> None:
        with self._lock:
            self._inflight = 0
            pending = list(self._pending)
            self._pending.clear()
        for cf in pending:
            if not cf.done():
                cf.set_exception(UpstreamError(reason))
        while True:
            try:
                item = self._jobs.get_nowait()
            except queue.Empty:
                return
            if isinstance(item, _StopSignal):
                self._jobs.put(item)
                return
            if isinstance(item, _Subscribe):
                continue
            _, cf = item
            if not cf.done():
                cf.set_exception(UpstreamError(reason))

    def _stamp_snapshot(self, raw: dict[str, Any]) -> dict[str, Any]:
        snapshot = dict(raw)
        snapshot["_arrival"] = time.time()
        return snapshot

    def _sleep_interruptible(self, seconds: float) -> None:
        remaining = seconds
        while remaining > 0 and not self._stop_requested:
            chunk = min(remaining, 0.5)
            time.sleep(chunk)
            remaining -= chunk

    def _close_api(self, api: Any) -> None:
        try:
            api.close()
        except Exception as exc:
            with self._lock:
                self._last_error = exc
            logger.warning("tqsdk close failed: %s", type(exc).__name__)

    def _next_recycle_ts(self) -> float:
        now = datetime.now(CN_TIMEZONE)
        target = now.replace(hour=4, minute=0, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return target.timestamp()
