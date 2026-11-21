# TapeHub adapter 内部协议 v1

本协议只用于 TapeHub 与三个 Python adapter 的 Compose 内部通信，不是公共 API，不承诺供第三方直接调用。能力目录、auto 选源、公共鉴权、公共错误 envelope 和分页由 TapeHub 负责。

## 端点

```http
POST /internal/v1/bars
POST /internal/v1/quotes
GET  /health
```

`/health` 只报告进程状态，不导入/登录 SDK、不访问真实上游。数据端点不实现 API Key 鉴权，adapter 不得发布宿主机端口。

bars 请求：

```json
{
  "operation": "stock_zh_a_hist",
  "asset_type": "stock",
  "instrument": "CN-SSE-600000",
  "interval": "P1D",
  "start": "2026-01-01T00:00:00+08:00",
  "end": "2026-01-31T00:00:00+08:00",
  "adjust": "qfq",
  "variant": "eastmoney"
}
```

`operation` 由 TapeHub manifest 解析，adapter 仍按自家白名单拒绝未知值。请求不带 `offset/limit`，也不带任何上游凭据。quotes 请求只有 `operation/asset_type/instrument/variant`。

bars 响应：

```json
{
  "bars": [{
    "timestamp": "2026-01-05T00:00:00+08:00",
    "open": 10.0,
    "high": 10.1,
    "low": 9.9,
    "close": 10.05,
    "volume": 1000000.0,
    "amount": 10050000.0,
    "extensions": null
  }],
  "source_time": null,
  "partial": false
}
```

quotes 响应为 `{"quote": {...}}`，quote 使用 TapeHub 标准字段，但不包含由网关填充的 `provider/received_at`。模型禁止未知字段；时间必须带时区；数值只允许有限 JSON number 或 null，禁止 NaN/Inf。

## 标准化职责

Python adapter 负责：

- 标准代码到上游代码、所有相关上游参数显式映射；
- SDK 调用、字段名与单位换算、上游时间语义、extensions 白名单；
- 根据上游原始响应计算 `partial`，不得根据分页后数量推断；
- 可为减少传输先过滤 `[start,end]`，但不排序分页。

TapeHub 负责：严格 JSON 解码、缺 timestamp loud fail、北京时间归一、再次闭区间复核、升序、`offset/limit`、公共 meta/warnings 和最终 JSON。远程响应限制 64 MiB。

## 错误

错误响应为：

```json
{
  "error": {
    "code": "UPSTREAM_ERROR",
    "message": "Adapter upstream request failed.",
    "request_id": "req_...",
    "details": {}
  }
}
```

允许的代码/HTTP 组合：`INVALID_REQUEST` 422、`UNSUPPORTED_CAPABILITY` 422、`PROVIDER_DISABLED` 409、`PROVIDER_NOT_IMPLEMENTED` 501、`QUOTE_NOT_READY` 408、`UPSTREAM_RATE_LIMITED` 429、`CONCURRENCY_LIMIT` 429、`UPSTREAM_TIMEOUT` 504、`UPSTREAM_ERROR` 502。Go 只映射白名单组合，其他状态、非 JSON、网络失败统一转成公共 `UPSTREAM_ERROR`；上游原始异常和凭据不得穿透。

HTTP 取消会中断连接，但不能强杀 Python 同步 SDK 工作线程。各服务使用有界并发；不做通用自动重试，只有 Baostock 会话恢复与 TqSdk Runtime 自有恢复例外。
