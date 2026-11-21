import asyncio
import time
from collections.abc import Iterator
from typing import Any

import fake_runtime as fake_rt
import pytest
import stub_tqsdk
from fake_runtime import FakeTqApi
from fastapi.testclient import TestClient

from tapehub_adapter_common.app import create_app
from tapehub_adapter_common.errors import QuoteNotReadyError, UpstreamError
from tapehub_adapter_common.models import BarQuery, QuoteQuery
from tapehub_adapter_tqsdk.adapter import TqsdkAdapter
from tapehub_adapter_tqsdk.request_mapper import build_request, quote_symbol
from tapehub_adapter_tqsdk.runtime import RuntimeStatus, TqSdkRuntime


@pytest.fixture(autouse=True)
def shutdown_runtimes(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    started: list[TqSdkRuntime] = []
    original = TqSdkRuntime.start

    def recording_start(self: TqSdkRuntime) -> None:
        started.append(self)
        original(self)

    monkeypatch.setattr(TqSdkRuntime, "start", recording_start)
    yield
    for runtime in started:
        runtime.shutdown()


def bars_query(**overrides: Any) -> BarQuery:
    values: dict[str, Any] = {
        "operation": "get_kline_serial",
        "asset_type": "contract",
        "instrument": "CN-SHFE-CU2701",
        "interval": "P1D",
        "start": "2026-01-01T00:00:00+08:00",
        "end": "2026-01-10T00:00:00+08:00",
        "adjust": "none",
        "variant": "tqsdk",
    }
    values.update(overrides)
    return BarQuery(**values)


def quote_query(**overrides: Any) -> QuoteQuery:
    values: dict[str, Any] = {
        "operation": "get_quote",
        "asset_type": "contract",
        "instrument": "CN-SHFE-AU2612",
        "variant": "tqsdk",
    }
    values.update(overrides)
    return QuoteQuery(**values)


def adapter(**overrides: Any) -> TqsdkAdapter:
    values: dict[str, Any] = {
        "auth_user": "user@example.com",
        "auth_password": "secret",
        "conn_mode": "shared",
        "construct_timeout": 2.0,
    }
    values.update(overrides)
    return TqsdkAdapter(**values)


@pytest.mark.parametrize(
    ("asset_type", "instrument", "expected"),
    [
        ("contract", "CN-SHFE-CU2701", "SHFE.cu2701"),
        ("contract", "CN-CZCE-MA2701", "CZCE.MA701"),
        ("continuous", "CN-DCE-M", "KQ.m@DCE.m"),
        ("weighted-index", "CN-CFFEX-IF", "KQ.i@CFFEX.IF"),
        ("stock", "CN-SSE-600000", "SSE.600000"),
        ("commodity-option", "CN-DCE-M2701C3500", "DCE.m2701-C-3500"),
        ("index-option", "CN-CFFEX-IO2612C4000", "CFFEX.IO2612-C-4000"),
        ("etf-option", "CN-SSE-10012437", "SSE.10012437"),
    ],
)
def test_symbol_matrix(asset_type: str, instrument: str, expected: str) -> None:
    query = bars_query(asset_type=asset_type, instrument=instrument)
    assert build_request(query)["symbol"] == expected
    assert quote_symbol(quote_query(asset_type=asset_type, instrument=instrument)) == expected


def test_per_request_bars_and_quote(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = stub_tqsdk.install(monkeypatch)
    client = adapter(conn_mode="per_request")
    result = asyncio.run(client.fetch_bars(bars_query(adjust="qfq")))
    assert len(result.bars) == 2
    assert result.bars[0].amount is None
    assert result.bars[0].extensions == {"open_oi": 100000.0, "close_oi": 101000.0}
    assert stub.instances[0].calls[0]["adj_type"] == "F"
    assert stub.instances[0].closed
    quote = asyncio.run(client.fetch_quote(quote_query()))
    assert quote.quote.last_price == 848.24
    assert quote.quote.ask_price5 == 848.6
    assert quote.quote.extensions["open_interest"] == 160306
    assert stub.instances[1].closed
    assert stub.instances[0].auth.user == "user@example.com"


def test_partial_when_latest_limit_does_not_cover_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = stub_tqsdk.install(monkeypatch)
    stub.rows = stub_tqsdk.kline_rows(["2026-01-02"] * 5000)
    result = asyncio.run(adapter(conn_mode="per_request").fetch_bars(bars_query()))
    assert result.partial is True


def test_shared_bars_quotes_and_lease_release(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_rt.install(monkeypatch)
    client = adapter()
    result = asyncio.run(client.fetch_bars(bars_query()))
    assert len(result.bars) == 3
    first = asyncio.run(client.fetch_quote(quote_query()))
    second = asyncio.run(client.fetch_quote(quote_query()))
    assert first.quote.last_price == 848.24
    assert second.quote.timestamp.isoformat() == "2026-11-04T10:14:46.500000+08:00"
    assert len(FakeTqApi.instances) == 1
    assert FakeTqApi.instances[0].quote_calls == ["SHFE.au2612"]
    assert "SHFE.au2612" not in client._runtime._sub_refs
    client.shutdown()
    assert FakeTqApi.instances[0].closed


def test_quote_not_ready_releases_subscription(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_rt.install(monkeypatch)
    FakeTqApi.quote_first_packet_ticks = 100_000
    client = adapter(first_snapshot_timeout=0.1)
    with pytest.raises(QuoteNotReadyError) as caught:
        asyncio.run(client.fetch_quote(quote_query()))
    assert caught.value.details["symbol"] == "SHFE.au2612"
    assert "SHFE.au2612" not in client._runtime._sub_refs
    client.shutdown()


def test_missing_credentials_managed_by_adapter() -> None:
    client = adapter(auth_user="", auth_password="")
    with TestClient(create_app("tapehub-tqsdk-adapter", client)) as http:
        assert http.get("/health").status_code == 200
        response = http.post("/internal/v1/bars", json=bars_query().model_dump(mode="json"))
        assert response.status_code == 409
        error = response.json()["error"]
        assert error["code"] == "PROVIDER_DISABLED"
        assert error["details"]["missing_credentials"] == [
            "TAPEHUB_TQSDK_AUTH_USER",
            "TAPEHUB_TQSDK_AUTH_PASSWORD",
        ]


def test_watchdog_rebuilds_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_rt.install(monkeypatch)
    FakeTqApi.fail_wait_update_times = 5
    runtime = TqSdkRuntime(auth_user="u", auth_password="p", construct_timeout=2)
    runtime.start()
    try:
        deadline = time.monotonic() + 10
        while runtime.generation < 2 and time.monotonic() < deadline:
            time.sleep(0.05)
        assert runtime.generation >= 2
        assert runtime.status is RuntimeStatus.READY
    finally:
        runtime.shutdown()


def test_dormant_subscription_recycle(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_rt.install(monkeypatch)
    runtime = TqSdkRuntime(
        auth_user="u", auth_password="p", construct_timeout=2, subscription_limit=1
    )
    runtime.start()
    try:
        runtime.subscribe("SHFE.au2612")
        deadline = time.monotonic() + 3
        while runtime.latest("SHFE.au2612") is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert runtime.latest("SHFE.au2612") is not None
        runtime.unsubscribe("SHFE.au2612")
        deadline = time.monotonic() + 10
        while runtime.generation < 2 and time.monotonic() < deadline:
            time.sleep(0.05)
        assert runtime.generation >= 2
    finally:
        runtime.shutdown()


def test_shutdown_fails_pending_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_rt.install(monkeypatch)
    fake_rt.FETCH_DELAY = 5.0
    runtime = TqSdkRuntime(auth_user="u", auth_password="p", construct_timeout=2)
    runtime.start()
    pending = runtime.fetch({"symbol": "SLOW"})
    runtime.shutdown()
    assert pending.done()
    with pytest.raises(UpstreamError):
        pending.result()
