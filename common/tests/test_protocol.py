import pytest
from pydantic import ValidationError

from tapehub_adapter_common.models import CN_TIMEZONE, BarQuery, Instrument


def test_instrument_normalization() -> None:
    instrument = Instrument.parse("cn-shfe-cu2701")
    assert instrument.code == "CN-SHFE-CU2701"


def test_bar_query_normalizes_boundaries() -> None:
    query = BarQuery(
        operation="get_kline_serial",
        asset_type="contract",
        instrument="CN-SHFE-CU2701",
        interval="P1D",
        start="2026-01-01T00:00:00Z",
        end="2026-01-02T00:00:00Z",
        adjust="none",
        variant="tqsdk",
    )
    assert query.start.utcoffset() == CN_TIMEZONE.utcoffset(None)
    assert query.start.hour == 8


def test_query_rejects_unknown_fields_and_naive_time() -> None:
    with pytest.raises(ValidationError):
        BarQuery(
            operation="x",
            asset_type="stock",
            instrument="CN-SSE-600000",
            interval="P1D",
            start="2026-01-01T00:00:00",
            end="2026-01-02T00:00:00+08:00",
            adjust="none",
            variant="x",
        )
    with pytest.raises(ValidationError):
        BarQuery(
            operation="x",
            asset_type="stock",
            instrument="CN-SSE-600000",
            interval="P1D",
            start="2026-01-01T00:00:00+08:00",
            end="2026-01-02T00:00:00+08:00",
            adjust="none",
            variant="x",
            offset=0,
        )


def test_option_symbol_contract() -> None:
    with pytest.raises(ValidationError):
        BarQuery(
            operation="x",
            asset_type="commodity-option",
            instrument="CN-SHFE-CU2701-C-102000",
            interval="P1D",
            start="2026-01-01T00:00:00+08:00",
            end="2026-01-02T00:00:00+08:00",
            adjust="none",
            variant="x",
        )
