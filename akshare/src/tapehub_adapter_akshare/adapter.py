"""AkShare SDK 调用与结果标准化。"""

from typing import Any

from tapehub_adapter_akshare.request_mapper import build_request
from tapehub_adapter_akshare.response_mapper import to_standard_bars
from tapehub_adapter_common.base import BaseAdapter
from tapehub_adapter_common.errors import ProviderNotImplementedError
from tapehub_adapter_common.models import BarQuery, BarsResult


class AkshareAdapter(BaseAdapter):
    def __init__(self, *, max_inflight: int = 4) -> None:
        super().__init__("akshare", max_inflight=max_inflight)

    async def fetch_bars(self, query: BarQuery) -> BarsResult:
        return await self.call_in_thread(self._fetch_sync, query)

    def _fetch_sync(self, query: BarQuery) -> BarsResult:
        kwargs = build_request(query.operation, query)
        try:
            import akshare as ak
        except ImportError as exc:
            raise ProviderNotImplementedError(
                "Provider SDK 'akshare' is not installed.",
                details={"provider": "akshare", "sdk": "akshare"},
            ) from exc
        func = getattr(ak, query.operation, None)
        if func is None:
            raise ProviderNotImplementedError(
                "Resolved AkShare operation is unavailable in the installed SDK.",
                details={"provider": "akshare"},
            )
        frame = func(**kwargs)
        rows = [] if frame is None else list(frame.to_dict("records"))
        bars = to_standard_bars(query.operation, rows)
        window = [bar for bar in bars if query.start <= bar.timestamp <= query.end]
        return BarsResult(bars=window, partial=False)

    def _to_rows(self, frame: Any) -> list[dict[str, Any]]:
        return [] if frame is None else list(frame.to_dict("records"))
