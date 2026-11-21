import sys
import types
from datetime import datetime, timezone
from typing import Any


def to_ns(day: str) -> int:
    value = datetime.fromisoformat(day).replace(tzinfo=timezone.utc)
    return int(value.timestamp() * 1_000_000_000)


def kline_rows(days: list[str]) -> list[dict[str, Any]]:
    return [
        {
            "datetime": to_ns(day),
            "open": 3000.0,
            "high": 3010.0,
            "low": 2990.0,
            "close": 3005.0,
            "volume": 500,
            "open_oi": 100000,
            "close_oi": 101000,
        }
        for day in days
    ]


DEFAULT_QUOTE_FIELDS: dict[str, Any] = {
    "datetime": "2026-11-04 10:14:46.500000",
    "last_price": 848.24,
    "bid_price1": 848.26,
    "bid_volume1": 2,
    "ask_price1": 848.3,
    "ask_volume1": 2,
    "ask_price5": 848.6,
    "ask_volume5": 3,
    "bid_price5": 848.16,
    "bid_volume5": 1,
    "highest": 853.64,
    "lowest": 843.14,
    "open": 846.0,
    "average": 848.47,
    "volume": 200250,
    "amount": 169906871060.0,
    "open_interest": 160306,
    "pre_open_interest": 160467,
    "upper_limit": 964.56,
    "lower_limit": 727.66,
    "pre_settlement": 846.12,
    "pre_close": 841.8,
}


class StubFrame:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def to_dict(self, _: str) -> list[dict[str, Any]]:
        return list(self.rows)


class StubTqAuth:
    def __init__(self, user: str = "", password: str = "") -> None:
        self.user = user
        self.password = password


class StubTqApi:
    instances: list["StubTqApi"] = []
    rows: list[dict[str, Any]] = []
    quote_fields = dict(DEFAULT_QUOTE_FIELDS)

    def __init__(self, auth: Any = None, **kwargs: Any) -> None:
        self.auth = auth
        self.calls: list[dict[str, Any]] = []
        self.quote_calls: list[str] = []
        self.closed = False
        type(self).instances.append(self)

    def get_kline_serial(self, **kwargs: Any) -> StubFrame:
        self.calls.append(dict(kwargs))
        return StubFrame(type(self).rows)

    def get_quote(self, _: str) -> dict[str, Any]:
        self.quote_calls.append(_)
        return dict(type(self).quote_fields)

    def close(self) -> None:
        self.closed = True


def install(monkeypatch: Any) -> type[StubTqApi]:
    module = types.ModuleType("tqsdk")
    module.TqApi = StubTqApi  # type: ignore[attr-defined]
    module.TqAuth = StubTqAuth  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "tqsdk", module)
    StubTqApi.instances = []
    StubTqApi.rows = kline_rows(["2026-01-02", "2026-01-05"])
    StubTqApi.quote_fields = dict(DEFAULT_QUOTE_FIELDS)
    return StubTqApi
