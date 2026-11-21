FROM ghcr.io/astral-sh/uv:0.11.24 AS uv
FROM python:3.12-slim AS build

COPY --from=uv /uv /uvx /usr/local/bin/
WORKDIR /src
ENV UV_PROJECT_ENVIRONMENT=/opt/venv UV_COMPILE_BYTECODE=1
COPY pyproject.toml uv.lock ./
COPY common/pyproject.toml common/pyproject.toml
COPY akshare/pyproject.toml akshare/pyproject.toml
COPY baostock/pyproject.toml baostock/pyproject.toml
COPY tqsdk/pyproject.toml tqsdk/pyproject.toml
COPY common/src common/src
COPY tqsdk/src tqsdk/src
RUN uv sync --package tapehub-tqsdk-adapter --locked --no-dev --no-editable

FROM python:3.12-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system tapehub \
    && useradd --system --gid tapehub tapehub
COPY --from=build /opt/venv /opt/venv
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER tapehub
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).read()" || exit 1
ENTRYPOINT ["/opt/venv/bin/uvicorn", "tapehub_adapter_tqsdk.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
