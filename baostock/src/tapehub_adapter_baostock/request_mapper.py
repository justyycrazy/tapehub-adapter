"""标准查询到 Baostock 历史 K 线参数的映射。"""

from tapehub_adapter_common.errors import UnsupportedCapabilityError
from tapehub_adapter_common.models import Adjust, BarQuery

_EXCHANGE_PREFIXES = {"SSE": "sh", "SZSE": "sz"}
_PERIOD_BY_INTERVAL = {
    "P1D": "d",
    "P1W": "w",
    "P1M": "m",
    "PT5M": "5",
    "PT15M": "15",
    "PT30M": "30",
    "PT1H": "60",
}
_ADJUST_CODES = {Adjust.NONE: "3", Adjust.QFQ: "2", Adjust.HFQ: "1"}
_MINUTE_INTERVALS = frozenset({"PT5M", "PT15M", "PT30M", "PT1H"})
_DAILY_STOCK_FIELDS = (
    "date,code,open,high,low,close,preclose,volume,amount,adjustflag,"
    "turn,tradestatus,pctChg,isST,peTTM,pbMRQ,psTTM,pcfNcfTTM"
)
_DAILY_INDEX_FIELDS = "date,code,open,high,low,close,preclose,volume,amount,adjustflag,pctChg"
_WEEKLY_MONTHLY_FIELDS = "date,code,open,high,low,close,volume,amount,adjustflag,turn,pctChg"
_MINUTE_FIELDS = "date,time,code,open,high,low,close,volume,amount,adjustflag"


def _unsupported(query: BarQuery, reason: str) -> UnsupportedCapabilityError:
    return UnsupportedCapabilityError(
        f"baostock does not support the requested symbol mapping: {reason}",
        details={
            "provider": "baostock",
            "instrument": query.instrument.code,
            "asset_type": query.asset_type.value,
            "variant": query.variant,
            "interval": query.interval,
            "adjust": query.adjust.value,
        },
    )


def date_window(query: BarQuery) -> tuple[str, str]:
    return query.start.strftime("%Y-%m-%d"), query.end.strftime("%Y-%m-%d")


def frequency_param(query: BarQuery) -> str:
    frequency = _PERIOD_BY_INTERVAL.get(query.interval)
    if frequency is None:
        raise _unsupported(query, f"interval {query.interval!r} is not supported")
    return frequency


def fields_param(query: BarQuery) -> str:
    if query.interval in _MINUTE_INTERVALS:
        return _MINUTE_FIELDS
    if query.interval == "P1D" and query.asset_type.value == "stock":
        return _DAILY_STOCK_FIELDS
    if query.interval == "P1D":
        return _DAILY_INDEX_FIELDS
    return _WEEKLY_MONTHLY_FIELDS


def code_param(query: BarQuery) -> str:
    prefix = _EXCHANGE_PREFIXES.get(query.instrument.exchange)
    if prefix is None:
        raise _unsupported(query, f"exchange {query.instrument.exchange!r} is not supported")
    return f"{prefix}.{query.instrument.symbol}"


def build_request(operation: str, query: BarQuery) -> dict[str, str]:
    if operation != "history_k_data_plus":
        raise _unsupported(query, f"unknown operation {operation!r}")
    start_date, end_date = date_window(query)
    return {
        "code": code_param(query),
        "fields": fields_param(query),
        "start_date": start_date,
        "end_date": end_date,
        "frequency": frequency_param(query),
        "adjustflag": _ADJUST_CODES[query.adjust],
    }
