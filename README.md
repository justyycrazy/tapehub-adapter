# tapehub-adapter

TapeHub 的 Python SDK 远程适配器仓库。AkShare、Baostock、TqSdk 分别运行在独立 Docker 容器中，通过版本化内部 REST 协议向 Go 网关提供标准 K 线与快照；本项目不是第二个公共网关。

## 边界

- `common/`：内部请求/响应 DTO、统一错误、FastAPI 装配和有界线程执行。
- `akshare/`：历史 K 线，支持 eastmoney/sina/tencent variant。
- `baostock/`：历史 K 线，维护全局单会话锁和一次恢复重试。
- `tqsdk/`：历史 K 线与快照，维护单线程共享 Runtime；本期不提供 SSE。
- TapeHub 独占 manifest、公共路由、公共鉴权/限流、北京时间复核、排序分页和最终响应。Python 不透传原始 DataFrame，不维护第二份能力清单。

内部协议见 [docs/protocol.md](docs/protocol.md)。三个 adapter 不发布宿主机端口，不实现内部 API Key 鉴权；公共客户端只访问 TapeHub。

## 开发与测试

要求 Python 3.12 和 uv 0.11.24：

```bash
uv sync --locked
uv run ruff check .
uv run pytest
```

测试全部使用 SDK 桩/假 Runtime，零外网、零真实凭据、零 `.env` 依赖。真实行情探针不属于测试门禁。

本机单服务示例：

```bash
uv run uvicorn tapehub_adapter_akshare.app:app --host 127.0.0.1 --port 8101 --workers 1
curl http://127.0.0.1:8101/health
```

## Docker

```bash
cp .env.example .env
# 仅按需选择 akshare、baostock、tqsdk
docker compose --profile akshare up --build -d
```

也可以从 TapeHub 主项目启动完整栈。主项目 Compose 使用 sibling 路径 `../tapehub-adapter` 构建镜像，并通过以下 URL 启用 Provider：

```dotenv
COMPOSE_PROFILES=akshare,baostock,tqsdk
TAPEHUB_AKSHARE_ADAPTER_URL=http://tapehub-akshare-adapter:8000
TAPEHUB_BAOSTOCK_ADAPTER_URL=http://tapehub-baostock-adapter:8000
TAPEHUB_TQSDK_ADAPTER_URL=http://tapehub-tqsdk-adapter:8000
```

`TAPEHUB_TQSDK_AUTH_USER` 和 `TAPEHUB_TQSDK_AUTH_PASSWORD` 只配置并注入 `tapehub-tqsdk-adapter`；TapeHub 不读取、不保存、不转发。URL 非空即表示 TapeHub 启用 tqsdk，adapter 缺凭据时数据请求返回 `PROVIDER_DISABLED`，执行阶段不换源。
