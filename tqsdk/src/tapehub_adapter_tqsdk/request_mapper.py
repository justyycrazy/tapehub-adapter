"""标准标的与查询参数到 TqSdk 原生形式的映射。"""

import re
from collections.abc import Callable
from typing import Any

from tapehub_adapter_common.errors import UnsupportedCapabilityError
from tapehub_adapter_common.models import Adjust, AssetType, BarQuery, Instrument, QuoteQuery

UPSTREAM_MAX_BARS = 5000
_DURATION_SECONDS = {
    "PT1M": 60,
    "PT5M": 300,
    "PT15M": 900,
    "PT30M": 1800,
    "PT1H": 3600,
    "P1D": 86400,
}
_ADJ_TYPE = {Adjust.NONE: None, Adjust.QFQ: "F", Adjust.HFQ: "B"}
_CZCE_MONTH_CODE_RE = re.compile(r"^([A-Z]{1,2})(\d{2})(\d{2})$")
_OPTION_SYMBOL_RE = re.compile(r"^([A-Z]+)(\d{2})(\d{2})([CP])(\d+(?:\.\d+)?)$")
_OPTION_ASSET_TYPES = frozenset(
    {AssetType.COMMODITY_OPTION, AssetType.INDEX_OPTION, AssetType.ETF_OPTION}
)


def _rewrite_czce_symbol(symbol: str) -> str:
    matched = _CZCE_MONTH_CODE_RE.fullmatch(symbol)
    if matched is None:
        return symbol
    product, year, month = matched.groups()
    return f"{product}{year[1]}{month}"


_SYMBOL_REWRITES: dict[str, Callable[[str], str]] = {
    "SHFE": str.lower,
    "INE": str.lower,
    "DCE": str.lower,
    "GFEX": str.lower,
    "CZCE": _rewrite_czce_symbol,
}


def _unsupported(query: BarQuery | QuoteQuery, reason: str) -> UnsupportedCapabilityError:
    return UnsupportedCapabilityError(
        f"tqsdk does not support the requested mapping: {reason}",
        details={
            "provider": "tqsdk",
            "instrument": query.instrument.code,
            "asset_type": query.asset_type.value,
        },
    )


def _option_native_symbol(query: BarQuery | QuoteQuery) -> str:
    matched = _OPTION_SYMBOL_RE.fullmatch(query.instrument.symbol)
    if matched is None:
        raise _unsupported(query, "invalid unified option symbol")
    product, year, month, cp, strike = matched.groups()
    exchange = query.instrument.exchange
    if exchange in ("SHFE", "INE"):
        return f"{product.lower()}{year}{month}{cp}{strike}"
    if exchange == "CZCE":
        return f"{product}{year[1]}{month}{cp}{strike}"
    if exchange in ("DCE", "GFEX"):
        return f"{product.lower()}{year}{month}-{cp}-{strike}"
    if exchange == "CFFEX":
        return f"{product}{year}{month}-{cp}-{strike}"
    raise _unsupported(query, f"option exchange {exchange!r} is not supported")


def upstream_symbol(query: BarQuery | QuoteQuery) -> str:
    instrument: Instrument = query.instrument
    symbol = _SYMBOL_REWRITES.get(instrument.exchange, lambda value: value)(instrument.symbol)
    base = f"{instrument.exchange}.{symbol}"
    if query.asset_type is AssetType.CONTRACT:
        return base
    if query.asset_type is AssetType.CONTINUOUS:
        return f"KQ.m@{base}"
    if query.asset_type is AssetType.WEIGHTED_INDEX:
        return f"KQ.i@{base}"
    if query.asset_type in (AssetType.STOCK, AssetType.INDEX, AssetType.ETF):
        return base
    if query.asset_type in _OPTION_ASSET_TYPES:
        if instrument.exchange in ("SSE", "SZSE"):
            return f"{instrument.exchange}.{instrument.symbol}"
        return f"{instrument.exchange}.{_option_native_symbol(query)}"
    raise _unsupported(query, f"asset type {query.asset_type.value!r} is not supported")


def build_request(query: BarQuery) -> dict[str, Any]:
    if query.operation != "get_kline_serial":
        raise _unsupported(query, f"unknown operation {query.operation!r}")
    duration = _DURATION_SECONDS.get(query.interval)
    if duration is None:
        raise _unsupported(query, f"interval {query.interval!r} is not supported")
    return {
        "symbol": upstream_symbol(query),
        "duration_seconds": duration,
        "data_length": UPSTREAM_MAX_BARS,
        "adj_type": _ADJ_TYPE[query.adjust],
    }


def quote_symbol(query: QuoteQuery) -> str:
    if query.operation != "get_quote":
        raise _unsupported(query, f"unknown operation {query.operation!r}")
    return upstream_symbol(query)
