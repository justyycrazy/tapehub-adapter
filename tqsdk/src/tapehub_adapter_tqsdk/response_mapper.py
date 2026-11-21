"""TqSdk K 线与快照到内部标准模型的映射。"""

import math
import time
from datetime import datetime
from typing import Any

from tapehub_adapter_common.errors import UpstreamError
from tapehub_adapter_common.models import CN_TIMEZONE, Bar, Quote

_BAR_EXTENSIONS = ("open_oi", "close_oi")
_QUOTE_EXTENSIONS = (
    "open",
    "highest",
    "lowest",
    "average",
    "pre_settlement",
    "pre_close",
    "open_interest",
    "pre_open_interest",
    "upper_limit",
    "lower_limit",
)


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _to_timestamp_ns(value: Any) -> datetime:
    try:
        seconds = int(value) / 1_000_000_000
        return datetime.fromtimestamp(seconds, CN_TIMEZONE)
    except (TypeError, ValueError, OverflowError, OSError) as exc:
        raise UpstreamError(
            "tqsdk row has no valid nanosecond datetime.",
            details={"provider": "tqsdk", "field": "datetime"},
        ) from exc


def _to_quote_datetime(value: Any) -> datetime:
    text = "" if value is None else str(value).strip()
    if not text or text.lower() == "nan":
        raise UpstreamError(
            "tqsdk quote has no valid datetime.",
            details={"provider": "tqsdk", "field": "datetime"},
        )
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise UpstreamError(
            "tqsdk quote has no valid datetime.",
            details={"provider": "tqsdk", "field": "datetime"},
        ) from exc
    if parsed.tzinfo is not None:
        return parsed.astimezone(CN_TIMEZONE)
    return parsed.replace(tzinfo=CN_TIMEZONE)


def to_standard_bars(rows: list[dict[str, Any]]) -> list[Bar]:
    bars: list[Bar] = []
    for row in rows:
        extensions: dict[str, Any] = {}
        for field in _BAR_EXTENSIONS:
            value = _to_float(row.get(field))
            if value is not None:
                extensions[field] = value
        bars.append(
            Bar(
                timestamp=_to_timestamp_ns(row.get("datetime")),
                open=_to_float(row.get("open")),
                high=_to_float(row.get("high")),
                low=_to_float(row.get("low")),
                close=_to_float(row.get("close")),
                volume=_to_float(row.get("volume")),
                amount=None,
                extensions=extensions or None,
            )
        )
    return bars


def to_standard_quote(snapshot: dict[str, Any]) -> Quote:
    values: dict[str, float | None] = {}
    for level in range(1, 6):
        for side in ("bid", "ask"):
            for field in ("price", "volume"):
                name = f"{side}_{field}{level}"
                values[name] = _to_float(snapshot.get(name))
    extensions: dict[str, Any] = {}
    for field in _QUOTE_EXTENSIONS:
        value = _to_float(snapshot.get(field))
        if value is not None:
            extensions[field] = value
    arrival = snapshot.get("_arrival")
    if (
        isinstance(arrival, (int, float))
        and not isinstance(arrival, bool)
        and math.isfinite(arrival)
    ):
        extensions["snapshot_age_ms"] = max(0, round((time.time() - arrival) * 1000))
    return Quote(
        timestamp=_to_quote_datetime(snapshot.get("datetime")),
        last_price=_to_float(snapshot.get("last_price")),
        volume=_to_float(snapshot.get("volume")),
        amount=_to_float(snapshot.get("amount")),
        extensions=extensions or None,
        **values,
    )
