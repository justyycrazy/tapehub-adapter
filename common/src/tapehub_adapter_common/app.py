"""内部 REST 服务装配；公共客户端契约仍由 TapeHub 负责。"""

import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from tapehub_adapter_common.errors import AdapterError
from tapehub_adapter_common.models import CN_TIMEZONE, BarQuery, BarsResult, QuoteQuery, QuoteResult

logger = logging.getLogger("tapehub_adapter")


def _error_body(
    request: Request, code: str, message: str, details: dict[str, Any]
) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "request_id": getattr(request.state, "request_id", ""),
            "details": details,
        }
    }


def create_app(service: str, adapter: Any, *, version: str = "0.1.0") -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            adapter.shutdown()

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)

    @app.middleware("http")
    async def request_context(request: Request, call_next: Any) -> Any:
        request.state.request_id = "req_" + uuid.uuid4().hex[:24]
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @app.exception_handler(AdapterError)
    async def adapter_error(request: Request, exc: AdapterError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status,
            content=_error_body(request, exc.code, exc.message, exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, _: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=_error_body(
                request,
                "INVALID_REQUEST",
                "Invalid adapter request.",
                {"reason": "request schema validation failed"},
            ),
        )

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.error("adapter request failed: %s", type(exc).__name__)
        return JSONResponse(
            status_code=502,
            content=_error_body(request, "UPSTREAM_ERROR", "Adapter upstream request failed.", {}),
        )

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "service": service,
            "version": version,
            "api_version": "adapter_v1",
            "timestamp": datetime.now(CN_TIMEZONE),
        }

    @app.post("/internal/v1/bars", response_model=BarsResult)
    async def bars(query: BarQuery) -> Any:
        return await adapter.fetch_bars(query)

    @app.post("/internal/v1/quotes", response_model=QuoteResult)
    async def quotes(query: QuoteQuery) -> Any:
        return await adapter.fetch_quote(query)

    return app
