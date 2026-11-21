"""标准查询到 AkShare 接口参数的映射。"""

from tapehub_adapter_common.errors import UnsupportedCapabilityError
from tapehub_adapter_common.models import Adjust, BarQuery

_EXCHANGE_PREFIXES = {"SSE": "sh", "SZSE": "sz", "CSI": "csi", "BSE": "bj"}
_US_EM_MARKET_CODES = {"NASDAQ": "105", "NYSE": "106"}
_STOCK_PREFIX_EXCHANGES = {
    "sina": ("SSE", "SZSE", "BSE"),
    "tencent": ("SSE", "SZSE"),
}
_INDEX_PREFIX_EXCHANGES = {
    "eastmoney": ("SSE", "SZSE", "CSI", "BSE"),
    "sina": ("SSE", "SZSE"),
    "tencent": ("SSE", "SZSE"),
}
_PERIOD_BY_INTERVAL = {"P1D": "daily", "P1W": "weekly", "P1M": "monthly"}
_ADJUST_CODES = {Adjust.NONE: "", Adjust.QFQ: "qfq", Adjust.HFQ: "hfq"}


def _unsupported(query: BarQuery, reason: str) -> UnsupportedCapabilityError:
    return UnsupportedCapabilityError(
        f"akshare does not support the requested symbol mapping: {reason}",
        details={
            "provider": "akshare",
            "instrument": query.instrument.code,
            "asset_type": query.asset_type.value,
            "variant": query.variant,
            "interval": query.interval,
            "adjust": query.adjust.value,
        },
    )


def date_window(query: BarQuery) -> tuple[str, str]:
    return query.start.strftime("%Y%m%d"), query.end.strftime("%Y%m%d")


def adjust_param(adjust: Adjust) -> str:
    return _ADJUST_CODES[adjust]


def period_param(interval: str) -> str:
    period = _PERIOD_BY_INTERVAL.get(interval)
    if period is None:
        raise UnsupportedCapabilityError(
            f"akshare does not support interval {interval}.",
            details={"interval": interval},
        )
    return period


def _prefixed_symbol(query: BarQuery, allowed_exchanges: tuple[str, ...]) -> str:
    prefix = _EXCHANGE_PREFIXES.get(query.instrument.exchange)
    if prefix is None or query.instrument.exchange not in allowed_exchanges:
        raise _unsupported(query, f"exchange {query.instrument.exchange!r} is not supported here")
    return f"{prefix}{query.instrument.symbol}"


def stock_symbol(query: BarQuery) -> str:
    if query.variant == "eastmoney":
        if query.instrument.exchange not in ("SSE", "SZSE", "BSE"):
            raise _unsupported(
                query, f"exchange {query.instrument.exchange!r} is not supported here"
            )
        return query.instrument.symbol
    return _prefixed_symbol(query, _STOCK_PREFIX_EXCHANGES.get(query.variant, ()))


def index_symbol(query: BarQuery) -> str:
    if query.variant == "eastmoney":
        if query.instrument.exchange not in _INDEX_PREFIX_EXCHANGES["eastmoney"]:
            raise _unsupported(
                query, f"exchange {query.instrument.exchange!r} is not supported here"
            )
        return query.instrument.symbol
    return _prefixed_symbol(query, _INDEX_PREFIX_EXCHANGES.get(query.variant, ()))


def hk_symbol(query: BarQuery) -> str:
    symbol = query.instrument.symbol
    if query.instrument.exchange != "HKEX" or not symbol.isdigit():
        raise _unsupported(query, f"exchange {query.instrument.exchange!r} is not supported here")
    return symbol.zfill(5)


def us_symbol(query: BarQuery) -> str:
    market_code = _US_EM_MARKET_CODES.get(query.instrument.exchange)
    if market_code is None:
        raise _unsupported(query, f"exchange {query.instrument.exchange!r} is not supported here")
    return f"{market_code}.{query.instrument.symbol.upper()}"


def futures_symbol(query: BarQuery) -> str:
    if query.asset_type.value == "continuous":
        return f"{query.instrument.symbol}0"
    return query.instrument.symbol


def build_request(operation: str, query: BarQuery) -> dict[str, str]:
    start_date, end_date = date_window(query)
    if operation == "stock_zh_a_hist":
        return {
            "symbol": stock_symbol(query),
            "period": period_param(query.interval),
            "start_date": start_date,
            "end_date": end_date,
            "adjust": adjust_param(query.adjust),
        }
    if operation == "fund_etf_hist_em":
        return {
            "symbol": stock_symbol(query),
            "period": period_param(query.interval),
            "start_date": start_date,
            "end_date": end_date,
            "adjust": adjust_param(query.adjust),
        }
    if operation == "stock_hk_hist":
        return {
            "symbol": hk_symbol(query),
            "period": period_param(query.interval),
            "start_date": start_date,
            "end_date": end_date,
            "adjust": adjust_param(query.adjust),
        }
    if operation == "stock_us_hist":
        return {
            "symbol": us_symbol(query),
            "period": period_param(query.interval),
            "start_date": start_date,
            "end_date": end_date,
            "adjust": adjust_param(query.adjust),
        }
    if operation == "stock_zh_a_daily":
        return {
            "symbol": stock_symbol(query),
            "start_date": start_date,
            "end_date": end_date,
            "adjust": adjust_param(query.adjust),
        }
    if operation == "stock_zh_a_hist_tx":
        return {
            "symbol": stock_symbol(query),
            "start_date": start_date,
            "end_date": end_date,
            "adjust": adjust_param(query.adjust),
        }
    if operation == "index_zh_a_hist":
        return {
            "symbol": index_symbol(query),
            "period": period_param(query.interval),
            "start_date": start_date,
            "end_date": end_date,
        }
    if operation == "stock_zh_index_daily":
        return {"symbol": index_symbol(query)}
    if operation == "stock_zh_index_daily_tx":
        return {"symbol": index_symbol(query), "start_date": start_date, "end_date": end_date}
    if operation == "futures_zh_daily_sina":
        return {"symbol": futures_symbol(query)}
    raise _unsupported(query, f"unknown operation {operation!r}")
