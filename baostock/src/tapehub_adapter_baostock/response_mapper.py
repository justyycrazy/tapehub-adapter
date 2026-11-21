"""Baostock 字符串行到内部标准 K 线的映射。"""

import math
from datetime import datetime
from typing import Any

from tapehub_adapter_common.errors import UpstreamError
from tapehub_adapter_common.models import CN_TIMEZONE, AssetType, Bar

_MINUTE_INTERVALS = frozenset({"PT5M", "PT15M", "PT30M", "PT1H"})
_COLUMNS = {
    "date": "timestamp",
    "open": "open",
    "high": "high",
    "low": "low",
    "close": "close",
    "volume": "volume",
    "amount": "amount",
}
_STOCK_DAILY_EXTENSIONS = {
    "preclose": "prev_close",
    "turn": "turnover_rate",
    "pctChg": "pct_change",
    "tradestatus": "trade_status",
    "isST": "is_st",
    "peTTM": "pe_ttm",
    "pbMRQ": "pb_mrq",
    "psTTM": "ps_ttm",
    "pcfNcfTTM": "pcf_ncf_ttm",
}
_INDEX_DAILY_EXTENSIONS = {"preclose": "prev_close", "pctChg": "pct_change"}
_WEEKLY_MONTHLY_EXTENSIONS = {"turn": "turnover_rate", "pctChg": "pct_change"}


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _daily_timestamp(row: dict[str, Any]) -> datetime:
    text = str(row.get("date") or "")
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").replace(tzinfo=CN_TIMEZONE)
    except ValueError as exc:
        raise UpstreamError(
            "baostock row is missing a valid date field.",
            details={"provider": "baostock", "field": "date"},
        ) from exc


def _minute_timestamp(row: dict[str, Any]) -> datetime:
    text = str(row.get("time") or "")
    if len(text) < 14 or not text[:14].isdigit():
        raise UpstreamError(
            "baostock minute row is missing a valid time field.",
            details={"provider": "baostock", "field": "time"},
        )
    try:
        return datetime(
            year=int(text[0:4]),
            month=int(text[4:6]),
            day=int(text[6:8]),
            hour=int(text[8:10]),
            minute=int(text[10:12]),
            second=int(text[12:14]),
            microsecond=int(text[14:17].ljust(6, "0")),
            tzinfo=CN_TIMEZONE,
        )
    except ValueError as exc:
        raise UpstreamError(
            "baostock minute row contains an invalid time field.",
            details={"provider": "baostock", "field": "time"},
        ) from exc


def _extensions_for(asset_type: AssetType, interval: str) -> dict[str, str]:
    if interval in _MINUTE_INTERVALS:
        return {}
    if interval == "P1D":
        return _STOCK_DAILY_EXTENSIONS if asset_type is AssetType.STOCK else _INDEX_DAILY_EXTENSIONS
    return _WEEKLY_MONTHLY_EXTENSIONS


def to_standard_bars(
    asset_type: AssetType, interval: str, rows: list[dict[str, Any]]
) -> list[Bar]:
    bars: list[Bar] = []
    whitelist = _extensions_for(asset_type, interval)
    for row in rows:
        timestamp = (
            _minute_timestamp(row) if interval in _MINUTE_INTERVALS else _daily_timestamp(row)
        )
        values = {field: _to_float(row.get(source)) for source, field in _COLUMNS.items()}
        extensions: dict[str, Any] = {}
        for source, name in whitelist.items():
            value = _to_float(row.get(source))
            if value is not None:
                extensions[name] = value
        bars.append(
            Bar(
                timestamp=timestamp,
                open=values.get("open"),
                high=values.get("high"),
                low=values.get("low"),
                close=values.get("close"),
                volume=values.get("volume"),
                amount=values.get("amount"),
                extensions=extensions or None,
            )
        )
    return bars
