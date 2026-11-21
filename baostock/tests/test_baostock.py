import asyncio
import sys
from typing import Any

import pytest
from fastapi.testclient import TestClient
from stub_baostock import StubBaostock, StubResultData

from tapehub_adapter_baostock.adapter import BaostockAdapter
from tapehub_adapter_common.app import create_app
from tapehub_adapter_common.errors import UnsupportedCapabilityError, UpstreamError
from tapehub_adapter_common.models import BarQuery

DAILY_STOCK_FIELDS = (
    "date,code,open,high,low,close,preclose,volume,amount,adjustflag,"
    "turn,tradestatus,pctChg,isST,peTTM,pbMRQ,psTTM,pcfNcfTTM"
)


def query(**overrides: Any) -> BarQuery:
    values: dict[str, Any] = {
        "operation": "history_k_data_plus",
        "asset_type": "stock",
        "instrument": "CN-SSE-600000",
        "interval": "P1D",
        "start": "2026-01-01T00:00:00+08:00",
        "end": "2026-01-10T00:00:00+08:00",
        "adjust": "qfq",
        "variant": "baostock",
    }
    values.update(overrides)
    return BarQuery(**values)


def rows(days: list[str]) -> list[dict[str, Any]]:
    return [
        {
            "date": day,
            "code": "sh.600000",
            "open": "12.64",
            "high": "12.70",
            "low": "12.50",
            "close": "12.56",
            "preclose": "12.65",
            "volume": "38778949",
            "amount": "486264672",
            "turn": "0.137985",
            "tradestatus": "1",
            "pctChg": "-0.711456",
            "isST": "0",
            "peTTM": "5.123456",
            "pcfNcfTTM": "",
            "unknown": "99",
        }
        for day in days
    ]


def install(monkeypatch: pytest.MonkeyPatch, stub: StubBaostock) -> None:
    monkeypatch.setitem(sys.modules, "baostock", stub)


def test_daily_mapping_and_explicit_params(
    monkeypatch: pytest.MonkeyPatch, stub: StubBaostock
) -> None:
    install(monkeypatch, stub)
    stub.result = StubResultData(rows(["2026-01-05", "2026-01-06"]))
    result = asyncio.run(BaostockAdapter().fetch_bars(query()))
    assert stub.calls[1][1] == {
        "code": "sh.600000",
        "fields": DAILY_STOCK_FIELDS,
        "start_date": "2026-01-01",
        "end_date": "2026-01-10",
        "frequency": "d",
        "adjustflag": "2",
    }
    bar = result.bars[0]
    assert bar.volume == 38778949
    assert bar.extensions["prev_close"] == 12.65
    assert bar.extensions["trade_status"] == 1
    assert "pcf_ncf_ttm" not in bar.extensions
    assert "unknown" not in bar.extensions


@pytest.mark.parametrize(
    ("interval", "frequency"),
    [
        ("P1D", "d"),
        ("P1W", "w"),
        ("P1M", "m"),
        ("PT5M", "5"),
        ("PT15M", "15"),
        ("PT30M", "30"),
        ("PT1H", "60"),
    ],
)
def test_interval_mapping(
    monkeypatch: pytest.MonkeyPatch,
    stub: StubBaostock,
    interval: str,
    frequency: str,
) -> None:
    install(monkeypatch, stub)
    if interval.startswith("PT"):
        stub.result = StubResultData(
            [{"date": "2026-01-05", "time": "20260105093500000", "close": "10"}]
        )
    else:
        stub.result = StubResultData(rows(["2026-01-05"]))
    result = asyncio.run(BaostockAdapter().fetch_bars(query(interval=interval)))
    assert stub.calls[-1][1]["frequency"] == frequency
    assert len(result.bars) == 1


def test_minute_timestamp_and_extensions(
    monkeypatch: pytest.MonkeyPatch, stub: StubBaostock
) -> None:
    install(monkeypatch, stub)
    stub.result = StubResultData(
        [
            {"date": "2026-01-05", "time": "20260105093500000", "close": "10"},
            {"date": "2026-01-05", "time": "20260105101500123", "close": "11"},
        ]
    )
    result = asyncio.run(BaostockAdapter().fetch_bars(query(interval="PT5M")))
    assert result.bars[0].timestamp.hour == 9
    assert result.bars[1].timestamp.microsecond == 123000
    assert result.bars[0].extensions is None


def test_session_reuse_and_recovery(
    monkeypatch: pytest.MonkeyPatch, stub: StubBaostock
) -> None:
    install(monkeypatch, stub)
    stub.result = StubResultData(rows(["2026-01-05"]))
    adapter = BaostockAdapter()
    asyncio.run(adapter.fetch_bars(query()))
    asyncio.run(adapter.fetch_bars(query()))
    assert stub.login_count == 1
    stub.pending_errors = [StubResultData(error_code="10001001", error_msg="未登录")]
    asyncio.run(adapter.fetch_bars(query()))
    assert stub.login_count == 2
    stub.pending_errors = [StubResultData(error_code="10002004", error_msg="网络错误")]
    asyncio.run(adapter.fetch_bars(query()))
    assert stub.login_count == 3


def test_nonrecoverable_error(monkeypatch: pytest.MonkeyPatch, stub: StubBaostock) -> None:
    install(monkeypatch, stub)
    stub.pending_errors = [StubResultData(error_code="10004011", error_msg="无效代码")]
    with pytest.raises(UpstreamError) as caught:
        asyncio.run(BaostockAdapter().fetch_bars(query()))
    assert caught.value.details["upstream_error_code"] == "10004011"
    assert stub.login_count == 1


def test_bse_rejected() -> None:
    with pytest.raises(UnsupportedCapabilityError):
        asyncio.run(BaostockAdapter().fetch_bars(query(instrument="CN-BSE-920000")))


def test_window_filter_and_partial(
    monkeypatch: pytest.MonkeyPatch, stub: StubBaostock
) -> None:
    install(monkeypatch, stub)
    stub.result = StubResultData(rows(["2025-12-31", "2026-01-05", "2026-02-01"]))
    result = asyncio.run(BaostockAdapter().fetch_bars(query()))
    assert [bar.timestamp.day for bar in result.bars] == [5]
    assert result.partial is False
    stub.result = StubResultData(rows(["2026-01-05"] * 5000))
    result = asyncio.run(BaostockAdapter().fetch_bars(query()))
    assert result.partial is True


def test_http_chain(monkeypatch: pytest.MonkeyPatch, stub: StubBaostock) -> None:
    install(monkeypatch, stub)
    stub.result = StubResultData(rows(["2026-01-05"]))
    with TestClient(create_app("tapehub-baostock-adapter", BaostockAdapter())) as client:
        response = client.post("/internal/v1/bars", json=query().model_dump(mode="json"))
        assert response.status_code == 200
        assert response.json()["bars"][0]["volume"] == 38778949
        assert response.json()["partial"] is False
        assert client.get("/health").status_code == 200
