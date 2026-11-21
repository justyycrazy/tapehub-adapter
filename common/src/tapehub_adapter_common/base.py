"""远程适配器共用执行边界。"""

import functools
from collections.abc import Callable
from typing import Any

import anyio
import anyio.to_thread

from tapehub_adapter_common.errors import (
    ConcurrencyLimitError,
    ProviderNotImplementedError,
)


class BaseAdapter:
    def __init__(self, name: str, *, max_inflight: int = 4) -> None:
        if max_inflight < 1:
            raise ValueError("max_inflight must be positive")
        self.name = name
        self._thread_limiter = anyio.CapacityLimiter(max_inflight)

    async def call_in_thread(
        self,
        func: Callable[..., Any],
        /,
        *args: Any,
        abandon_on_cancel: bool = True,
    ) -> Any:
        if self._thread_limiter.borrowed_tokens >= self._thread_limiter.total_tokens:
            raise ConcurrencyLimitError(
                "Adapter execution capacity reached; retry later.",
                details={
                    "provider": self.name,
                    "limit": self._thread_limiter.total_tokens,
                },
            )
        return await anyio.to_thread.run_sync(
            functools.partial(func, *args),
            abandon_on_cancel=abandon_on_cancel,
            limiter=self._thread_limiter,
        )

    async def fetch_bars(self, query: Any) -> Any:
        raise ProviderNotImplementedError(
            f"Provider {self.name!r} does not implement bars.",
            details={"provider": self.name},
        )

    async def fetch_quote(self, query: Any) -> Any:
        raise ProviderNotImplementedError(
            f"Provider {self.name!r} does not implement quotes.",
            details={"provider": self.name},
        )

    def shutdown(self) -> None:
        return None
