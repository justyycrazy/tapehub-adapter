"""AkShare DataFrame 行到内部标准 K 线的映射。"""

import math
from datetime import date as date_type
from datetime import datetime, tzinfo
from typing import Any
from zoneinfo import ZoneInfo

from tapehub_adapter_common.errors import UpstreamError
from tapehub_adapter_common.models import CN_TIMEZONE, Bar

NEW_YORK_TIMEZONE = ZoneInfo("America/New_York")
_STOCK_EM_COLUMNS = {
    "日期": "timestamp",
    "开盘": "open",
    "最高": "high",
    "最低": "low",
    "收盘": "close",
    "成交量": "volume",
    "成交额": "amount",
}
_STOCK_EM_EXTENSIONS = {
    "振幅": "amplitude",
    "涨跌幅": "pct_change",
    "涨跌额": "change",
    "换手率": "turnover_rate",
}
_STOCK_SINA_COLUMNS = {
    "date": "timestamp",
    "open": "open",
    "high": "high",
    "low": "low",
    "close": "close",
    "volume": "volume",
    "amount": "amount",
}
_STOCK_SINA_EXTENSIONS = {"outstanding_share": "outstanding_share", "turnover": "turnover"}
_INDEX_SINA_COLUMNS = {
    "date": "timestamp",
    "open": "open",
    "high": "high",
    "low": "low",
    "close": "close",
    "volume": "volume",
}
_INDEX_TX_COLUMNS = {
    "date": "timestamp",
    "open": "open",
    "high": "high",
    "low": "low",
    "close": "close",
    "amount": "volume",
}
_MAPPINGS: dict[str, dict[str, Any]] = {
    "stock_zh_a_hist": {
        "columns": _STOCK_EM_COLUMNS,
        "extensions": _STOCK_EM_EXTENSIONS,
        "volume_scale": 100.0,
    },
    "fund_etf_hist_em": {
        "columns": _STOCK_EM_COLUMNS,
        "extensions": _STOCK_EM_EXTENSIONS,
        "volume_scale": 100.0,
    },
    "index_zh_a_hist": {"columns": _STOCK_EM_COLUMNS, "extensions": _STOCK_EM_EXTENSIONS},
    "stock_hk_hist": {"columns": _STOCK_EM_COLUMNS, "extensions": _STOCK_EM_EXTENSIONS},
    "stock_us_hist": {
        "columns": _STOCK_EM_COLUMNS,
        "extensions": _STOCK_EM_EXTENSIONS,
        "timestamp_tz": NEW_YORK_TIMEZONE,
    },
    "stock_zh_a_daily": {"columns": _STOCK_SINA_COLUMNS, "extensions": _STOCK_SINA_EXTENSIONS},
    "stock_zh_a_hist_tx": {"columns": _STOCK_SINA_COLUMNS, "extensions": {"turnover": "turnover"}},
    "stock_zh_index_daily": {"columns": _INDEX_SINA_COLUMNS},
    "stock_zh_index_daily_tx": {"columns": _INDEX_TX_COLUMNS},
    "futures_zh_daily_sina": {
        "columns": _INDEX_SINA_COLUMNS,
        "extensions": {"hold": "hold", "settle": "settle"},
    },
}


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _to_timestamp(value: Any, zone: tzinfo) -> datetime:
    try:
        if isinstance(value, datetime):
            naive = value.replace(tzinfo=None)
        elif isinstance(value, date_type):
            naive = datetime(value.year, value.month, value.day)
        else:
            naive = datetime.strptime(str(value)[:10], "%Y-%m-%d")
        return datetime(naive.year, naive.month, naive.day, tzinfo=zone)
    except (TypeError, ValueError) as exc:
        raise UpstreamError(
            "akshare row has no valid timestamp.",
            details={"provider": "akshare", "field": "timestamp"},
        ) from exc


def to_bar(
    row: dict[str, Any],
    *,
    columns: dict[str, str],
    extensions: dict[str, str] | None = None,
    volume_scale: float | None = None,
    timestamp_tz: tzinfo = CN_TIMEZONE,
) -> Bar:
    source_timestamp = next(source for source, field in columns.items() if field == "timestamp")
    values: dict[str, float | None] = {}
    for source, field in columns.items():
        if field != "timestamp":
            values[field] = _to_float(row.get(source))
    if volume_scale is not None and values.get("volume") is not None:
        values["volume"] *= volume_scale
    bar_extensions: dict[str, Any] = {}
    for source, name in (extensions or {}).items():
        value = _to_float(row.get(source))
        if value is not None:
            bar_extensions[name] = value
    return Bar(
        timestamp=_to_timestamp(row.get(source_timestamp), timestamp_tz),
        open=values.get("open"),
        high=values.get("high"),
        low=values.get("low"),
        close=values.get("close"),
        volume=values.get("volume"),
        amount=values.get("amount"),
        extensions=bar_extensions or None,
    )


def to_standard_bars(operation: str, rows: list[dict[str, Any]]) -> list[Bar]:
    config = _MAPPINGS.get(operation)
    if config is None:
        raise UpstreamError(
            "akshare has no response mapping for the resolved operation.",
            details={"provider": "akshare"},
        )
    return [to_bar(row, **config) for row in rows]
