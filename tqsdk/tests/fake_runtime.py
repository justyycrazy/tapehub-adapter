import asyncio
import sys
import time
import types
from typing import Any

FETCH_DELAY = 0.0
TICKS_PER_FETCH = 2


def quote_fields() -> dict[str, Any]:
    return {
        "datetime": "2026-11-04 10:14:46.500000",
        "last_price": 848.24,
        "bid_price1": 848.26,
        "bid_volume1": 2,
        "ask_price1": 848.3,
        "ask_volume1": 2,
        "bid_price5": 848.16,
        "bid_volume5": 1,
        "ask_price5": 848.6,
        "ask_volume5": 3,
        "volume": 200250,
        "amount": 169906871060.0,
        "open_interest": 160306,
        "upper_limit": 964.56,
    }


class FakeQuote(dict):
    def __await__(self) -> Any:
        async def wait() -> "FakeQuote":
            while self.get("datetime", "") == "":
                await asyncio.sleep(0.005)
            return self

        return wait().__await__()


class FakeFrame:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def to_dict(self, _: str) -> list[dict[str, Any]]:
        return list(self.rows)


class FakeSerial:
    def __init__(self, api: "FakeTqApi", rows: list[dict[str, Any]]) -> None:
        self.api = api
        self.rows = rows

    def __await__(self) -> Any:
        async def fetch() -> FakeFrame:
            try:
                for _ in range(TICKS_PER_FETCH):
                    await asyncio.sleep(FETCH_DELAY / max(1, TICKS_PER_FETCH))
                return FakeFrame(self.rows)
            finally:
                self.api.inflight_fetches = max(0, self.api.inflight_fetches - 1)

        return fetch().__await__()


class FakeTqApi:
    instances: list["FakeTqApi"] = []
    fail_wait_update_times = 0
    quote_first_packet_ticks = 2
    rows_per_call = 3

    def __init__(self, auth: Any = None, loop: Any = None, **_: Any) -> None:
        self.auth = auth
        self.loop = (
            loop if isinstance(loop, asyncio.AbstractEventLoop) else asyncio.new_event_loop()
        )
        self.tasks: list[asyncio.Task] = []
        self.closed = False
        self._pending_peek = True
        self.quotes: dict[str, FakeQuote] = {}
        self.quote_due: dict[str, int] = {}
        self.changed_ids: set[int] = set()
        self.quote_calls: list[str] = []
        self.inflight_fetches = 0
        type(self).instances.append(self)

    def create_task(self, coro: Any) -> asyncio.Task:
        task = self.loop.create_task(coro)
        self.tasks.append(task)
        return task

    def get_kline_serial(self, **kwargs: Any) -> FakeSerial:
        base = 1767254400000000000
        rows = [
            {
                "datetime": base + index * 86400 * 1_000_000_000,
                "open": 1.0,
                "high": 1.0,
                "low": 1.0,
                "close": 1.0,
                "volume": 100.0,
                "symbol": kwargs["symbol"],
            }
            for index in range(type(self).rows_per_call)
        ]
        self.inflight_fetches += 1
        return FakeSerial(self, rows)

    def get_quote(self, symbol: str) -> FakeQuote:
        self.quote_calls.append(symbol)
        if symbol not in self.quotes:
            self.quotes[symbol] = FakeQuote({"datetime": "", "last_price": float("nan")})
            self.quote_due[symbol] = max(1, type(self).quote_first_packet_ticks)
        if not self.loop.is_running():
            guard = 0
            while not self.quotes[symbol].get("datetime"):
                self.wait_update()
                guard += 1
                if guard > 1000:
                    raise RuntimeError("fake quote never arrived")
        return self.quotes[symbol]

    def wait_update(self, deadline: float | None = None) -> bool:
        if type(self).fail_wait_update_times > 0:
            type(self).fail_wait_update_times -= 1
            raise RuntimeError("connection broken")
        self.changed_ids = set()
        for symbol, quote in self.quotes.items():
            if not quote.get("datetime"):
                self.quote_due[symbol] -= 1
                if self.quote_due[symbol] <= 0:
                    quote.update(quote_fields())
                    self.changed_ids.add(id(quote))
        pending = [task for task in self.tasks if not task.done()]
        if pending:
            self.loop.run_until_complete(asyncio.wait(pending, timeout=0.05))
        else:
            time.sleep(0.005)
        return True

    def is_changing(self, value: Any) -> bool:
        return id(value) in self.changed_ids

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        for task in self.tasks:
            task.cancel()
        if self.tasks:
            self.loop.run_until_complete(asyncio.gather(*self.tasks, return_exceptions=True))
        self.loop.close()


def install(monkeypatch: Any) -> types.ModuleType:
    module = types.ModuleType("tqsdk")

    class FakeTqAuth:
        def __init__(self, user_name: str = "", password: str = "") -> None:
            self.user_name = user_name
            self.password = password

    module.TqApi = FakeTqApi  # type: ignore[attr-defined]
    module.TqAuth = FakeTqAuth  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "tqsdk", module)
    FakeTqApi.instances = []
    FakeTqApi.fail_wait_update_times = 0
    FakeTqApi.quote_first_packet_ticks = 2
    FakeTqApi.rows_per_call = 3
    global FETCH_DELAY, TICKS_PER_FETCH
    FETCH_DELAY = 0.0
    TICKS_PER_FETCH = 2
    return module
