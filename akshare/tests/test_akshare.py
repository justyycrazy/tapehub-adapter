import asyncio
import sys
from typing import Any

import pytest
from fastapi.testclient import TestClient
from stub_akshare import StubAkshare

from tapehub_adapter_akshare.adapter import AkshareAdapter
from tapehub_adapter_common.app import create_app
from tapehub_adapter_common.errors import ProviderNotImplementedError, UnsupportedCapabilityError
from tapehub_adapter_common.models import BarQuery


def query(**overrides: Any) -> BarQuery:
    values: dict[str, Any] = {
        "operation": "stock_zh_a_hist",
        "asset_type": "stock",
        "instrument": "CN-SSE-600000",
        "interval": "P1D",
        "start": "2026-01-01T00:00:00+08:00",
        "end": "2026-01-10T00:00:00+08:00",
        "adjust": "qfq",
        "variant": "eastmoney",
    }
    values.update(overrides)
    return BarQuery(**values)


def install(monkeypatch: pytest.MonkeyPatch, stub: StubAkshare) -> None:
    monkeypatch.setitem(sys.modules, "akshare", stub)


def em_rows(days: list[str]) -> list[dict[str, Any]]:
    return [
        {
            "日期": day,
            "开盘": 10.0,
            "最高": 10.3,
            "最低": 9.9,
            "收盘": 10.2,
            "成交量": 12345.0,
            "成交额": 12345678.0,
            "涨跌幅": 2.0,
            "换手率": 1.5,
            "未白名单字段": 99,
        }
        for day in days
    ]


def test_em_stock_mapping(monkeypatch: pytest.MonkeyPatch, stub: StubAkshare) -> None:
    install(monkeypatch, stub)
    stub.set_rows("stock_zh_a_hist", em_rows(["2026-01-01", "2026-01-02"]))
    result = asyncio.run(AkshareAdapter().fetch_bars(query()))
    operation, kwargs = stub.calls[0]
    assert operation == "stock_zh_a_hist"
    assert kwargs == {
        "symbol": "600000",
        "period": "daily",
        "start_date": "20260101",
        "end_date": "20260110",
        "adjust": "qfq",
    }
    assert result.bars[0].volume == 1234500.0
    assert result.bars[0].extensions == {"pct_change": 2.0, "turnover_rate": 1.5}
    assert result.partial is False


@pytest.mark.parametrize(
    ("variant", "operation", "symbol"),
    [
        ("sina", "stock_zh_a_daily", "sh600000"),
        ("tencent", "stock_zh_a_hist_tx", "sh600000"),
    ],
)
def test_stock_variants(
    monkeypatch: pytest.MonkeyPatch,
    stub: StubAkshare,
    variant: str,
    operation: str,
    symbol: str,
) -> None:
    install(monkeypatch, stub)
    rows = [{"date": "2026-01-02", "open": 1, "high": 2, "low": 1, "close": 2, "volume": 10}]
    stub.set_rows(operation, rows)
    result = asyncio.run(AkshareAdapter().fetch_bars(query(operation=operation, variant=variant)))
    assert stub.calls[0][1]["symbol"] == symbol
    assert result.bars[0].volume == 10


def test_sina_bse_and_tencent_bse_boundary(
    monkeypatch: pytest.MonkeyPatch, stub: StubAkshare
) -> None:
    install(monkeypatch, stub)
    stub.set_rows("stock_zh_a_daily", [])
    asyncio.run(
        AkshareAdapter().fetch_bars(
            query(operation="stock_zh_a_daily", variant="sina", instrument="CN-BSE-920000")
        )
    )
    assert stub.calls[0][1]["symbol"] == "bj920000"
    with pytest.raises(UnsupportedCapabilityError):
        asyncio.run(
            AkshareAdapter().fetch_bars(
                query(operation="stock_zh_a_hist_tx", variant="tencent", instrument="CN-BSE-920000")
            )
        )


def test_etf_weekly_mapping(monkeypatch: pytest.MonkeyPatch, stub: StubAkshare) -> None:
    install(monkeypatch, stub)
    stub.set_rows("fund_etf_hist_em", em_rows(["2026-01-09"]))
    asyncio.run(
        AkshareAdapter().fetch_bars(
            query(
                operation="fund_etf_hist_em",
                instrument="CN-SZSE-159915",
                interval="P1W",
                adjust="none",
            )
        )
    )
    assert stub.calls[0][1] == {
        "symbol": "159915",
        "period": "weekly",
        "start_date": "20260101",
        "end_date": "20260110",
        "adjust": "",
    }


def test_index_variants(monkeypatch: pytest.MonkeyPatch, stub: StubAkshare) -> None:
    install(monkeypatch, stub)
    stub.set_rows("stock_zh_index_daily_tx", [{"date": "2026-01-02", "amount": 999}])
    result = asyncio.run(
        AkshareAdapter().fetch_bars(
            query(
                operation="stock_zh_index_daily_tx",
                asset_type="index",
                instrument="CN-SSE-000001",
                adjust="none",
                variant="tencent",
            )
        )
    )
    assert stub.calls[0][1]["symbol"] == "sh000001"
    assert result.bars[0].volume == 999
    assert result.bars[0].amount is None


def test_hk_and_us_mappings(monkeypatch: pytest.MonkeyPatch, stub: StubAkshare) -> None:
    install(monkeypatch, stub)
    for operation in ("stock_hk_hist", "stock_us_hist"):
        stub.set_rows(operation, em_rows(["2026-01-02", "2026-07-01"]))
    hk = asyncio.run(
        AkshareAdapter().fetch_bars(
            query(operation="stock_hk_hist", instrument="HK-HKEX-700", adjust="none")
        )
    )
    assert stub.calls[0][1]["symbol"] == "00700"
    assert hk.bars[0].timestamp.hour == 0
    us = asyncio.run(
        AkshareAdapter().fetch_bars(
            query(
                operation="stock_us_hist",
                instrument="US-NASDAQ-AAPL",
                adjust="none",
                end="2026-07-10T00:00:00+08:00",
            )
        )
    )
    assert stub.calls[1][1]["symbol"] == "105.AAPL"
    assert [bar.timestamp.hour for bar in us.bars] == [13, 12]


def test_futures_continuous_and_window_filter(
    monkeypatch: pytest.MonkeyPatch, stub: StubAkshare
) -> None:
    install(monkeypatch, stub)
    stub.set_rows(
        "futures_zh_daily_sina",
        [
            {"date": "2025-12-31", "close": 1},
            {"date": "2026-01-02", "close": 4005, "hold": 100000, "settle": 4004},
            {"date": "2026-02-01", "close": 2},
        ],
    )
    result = asyncio.run(
        AkshareAdapter().fetch_bars(
            query(
                operation="futures_zh_daily_sina",
                asset_type="continuous",
                instrument="CN-SHFE-RB",
                adjust="none",
                variant="sina",
            )
        )
    )
    assert stub.calls[0][1] == {"symbol": "RB0"}
    assert len(result.bars) == 1
    assert result.bars[0].extensions == {"hold": 100000.0, "settle": 4004.0}


def test_missing_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "akshare", None)
    with pytest.raises(ProviderNotImplementedError):
        asyncio.run(AkshareAdapter().fetch_bars(query()))


def test_http_contract_and_health(
    monkeypatch: pytest.MonkeyPatch, stub: StubAkshare
) -> None:
    install(monkeypatch, stub)
    stub.set_rows("stock_zh_a_hist", em_rows(["2026-01-02"]))
    app = create_app("tapehub-akshare-adapter", AkshareAdapter())
    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["api_version"] == "adapter_v1"
        assert stub.calls == []
        payload = query().model_dump(mode="json")
        response = client.post("/internal/v1/bars", json=payload)
        assert response.status_code == 200
        body = response.json()
        assert body["bars"][0]["volume"] == 1234500.0
        assert body["bars"][0]["extensions"]["pct_change"] == 2.0
        assert "provider" not in body
        invalid = client.post("/internal/v1/bars", json={**payload, "offset": 0})
        assert invalid.status_code == 422
        assert invalid.json()["error"]["code"] == "INVALID_REQUEST"
