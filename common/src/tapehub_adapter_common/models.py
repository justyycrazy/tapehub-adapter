"""TapeHub 与 Python 适配器之间的版本化数据模型。"""

import re
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

CN_TIMEZONE = timezone(timedelta(hours=8), name="CST")
_INSTRUMENT_RE = re.compile(
    r"^([A-Za-z][A-Za-z0-9]{0,7})-([A-Za-z][A-Za-z0-9]{0,15})-([A-Za-z0-9/][A-Za-z0-9/._-]{0,31})$"
)
_OPTION_SYMBOL_RE = re.compile(r"^[A-Z]+\d{4}[CP]\d+(?:\.\d+)?$")
_CZCE_CONTRACT_RE = re.compile(r"^[A-Z]{1,2}\d{4}$")
_MARKET_EXCHANGES = {
    "CN": {"SSE", "SZSE", "BSE", "SHFE", "DCE", "CZCE", "INE", "GFEX", "CFFEX", "CSI"},
    "HK": {"HKEX"},
    "US": {"NYSE", "NASDAQ", "CBOE", "AMEX", "OTC", "IEX"},
    "GLOBAL": {"OTC", "CRYPTO"},
}
_OPTION_EXCHANGES = {
    "commodity-option": {"SHFE", "INE", "DCE", "CZCE", "GFEX"},
    "index-option": {"CFFEX"},
    "etf-option": {"SSE", "SZSE"},
}


class AssetType(StrEnum):
    ETF = "etf"
    INDEX = "index"
    STOCK = "stock"
    CONTRACT = "contract"
    CONTINUOUS = "continuous"
    WEIGHTED_INDEX = "weighted-index"
    COMMODITY_OPTION = "commodity-option"
    INDEX_OPTION = "index-option"
    ETF_OPTION = "etf-option"
    FOREX = "forex"
    CRYPTO = "crypto"


class Adjust(StrEnum):
    NONE = "none"
    QFQ = "qfq"
    HFQ = "hfq"


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must include a timezone offset")
    return value.astimezone(CN_TIMEZONE)


def _validate_symbol(asset_type: AssetType, instrument: "Instrument") -> None:
    allowed = _OPTION_EXCHANGES.get(asset_type.value)
    if allowed is not None and instrument.exchange not in allowed:
        raise ValueError("asset_type does not apply to the instrument exchange")
    if asset_type in (AssetType.COMMODITY_OPTION, AssetType.INDEX_OPTION):
        if not _OPTION_SYMBOL_RE.fullmatch(instrument.symbol):
            raise ValueError("option symbol must match {PRODUCT}{YYMM}{C|P}{STRIKE}")
    if asset_type is AssetType.CONTRACT and instrument.exchange == "CZCE":
        if not _CZCE_CONTRACT_RE.fullmatch(instrument.symbol):
            raise ValueError("CZCE contract symbol must match {PRODUCT}{YYMM}")


class Instrument(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    market: str
    exchange: str
    symbol: str

    @model_validator(mode="before")
    @classmethod
    def parse_code(cls, value: object) -> object:
        if isinstance(value, str):
            matched = _INSTRUMENT_RE.fullmatch(value)
            if matched is None:
                raise ValueError("instrument must match {MARKET}-{EXCHANGE}-{SYMBOL}")
            return {
                key: item.upper()
                for key, item in zip(
                    ("market", "exchange", "symbol"), matched.groups(), strict=True
                )
            }
        if isinstance(value, dict):
            return {
                key: item.upper() if isinstance(item, str) else item
                for key, item in value.items()
            }
        return value

    @model_validator(mode="after")
    def validate_exchange(self) -> "Instrument":
        if self.exchange not in _MARKET_EXCHANGES.get(self.market, set()):
            raise ValueError("exchange is not valid for market")
        return self

    @classmethod
    def parse(cls, value: str) -> "Instrument":
        return cls.model_validate(value)

    @property
    def code(self) -> str:
        return f"{self.market}-{self.exchange}-{self.symbol}"


class BarQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: str
    asset_type: AssetType
    instrument: Instrument
    interval: str
    start: datetime
    end: datetime
    adjust: Adjust
    variant: str

    @field_validator("start", "end")
    @classmethod
    def normalize_boundary(cls, value: datetime) -> datetime:
        return _aware(value)

    @model_validator(mode="after")
    def validate_query(self) -> "BarQuery":
        if not self.operation or not self.interval or not self.variant:
            raise ValueError("operation, interval and variant must not be empty")
        if self.start >= self.end:
            raise ValueError("start must be earlier than end")
        _validate_symbol(self.asset_type, self.instrument)
        return self


class QuoteQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: str
    asset_type: AssetType
    instrument: Instrument
    variant: str

    @model_validator(mode="after")
    def validate_query(self) -> "QuoteQuery":
        if not self.operation or not self.variant:
            raise ValueError("operation and variant must not be empty")
        _validate_symbol(self.asset_type, self.instrument)
        return self


class Bar(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    timestamp: datetime
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    volume: float | None = None
    amount: float | None = None
    extensions: dict[str, Any] | None = None

    @field_validator("timestamp")
    @classmethod
    def normalize_timestamp(cls, value: datetime) -> datetime:
        return _aware(value)


class BarsResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bars: list[Bar]
    source_time: datetime | None = None
    partial: bool = False

    @field_validator("source_time")
    @classmethod
    def normalize_source_time(cls, value: datetime | None) -> datetime | None:
        return _aware(value) if value is not None else None


class Quote(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    timestamp: datetime
    last_price: float | None = None
    bid_price1: float | None = None
    bid_volume1: float | None = None
    bid_price2: float | None = None
    bid_volume2: float | None = None
    bid_price3: float | None = None
    bid_volume3: float | None = None
    bid_price4: float | None = None
    bid_volume4: float | None = None
    bid_price5: float | None = None
    bid_volume5: float | None = None
    ask_price1: float | None = None
    ask_volume1: float | None = None
    ask_price2: float | None = None
    ask_volume2: float | None = None
    ask_price3: float | None = None
    ask_volume3: float | None = None
    ask_price4: float | None = None
    ask_volume4: float | None = None
    ask_price5: float | None = None
    ask_volume5: float | None = None
    volume: float | None = None
    amount: float | None = None
    extensions: dict[str, Any] | None = None

    @field_validator("timestamp")
    @classmethod
    def normalize_timestamp(cls, value: datetime) -> datetime:
        return _aware(value)


class QuoteResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quote: Quote
