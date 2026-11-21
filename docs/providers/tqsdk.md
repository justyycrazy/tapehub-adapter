# TqSdk adapter 运行说明

服务入口为 `tapehub_adapter_tqsdk.app:app`，容器单 worker，实现 bars 与 quotes，不实现 SSE。

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `TAPEHUB_TQSDK_AUTH_USER` | 空 | 快期账户，只在本服务使用 |
| `TAPEHUB_TQSDK_AUTH_PASSWORD` | 空 | 快期密码，只在本服务使用 |
| `TAPEHUB_TQSDK_CONN_MODE` | `shared` | 共享 Runtime；可选 `per_request` 回滚 |
| `TAPEHUB_TQSDK_MAX_INFLIGHT_FETCH` | `16` | 在飞 K 线上限 |
| `TAPEHUB_TQSDK_FIRST_SNAPSHOT_TIMEOUT` | `5` | 快照首包秒数 |
| `TAPEHUB_TQSDK_SUBSCRIPTION_LIMIT` | `64` | 休眠订阅回收阈值 |
| `TAPEHUB_TQSDK_CONSTRUCT_TIMEOUT` | `30` | 单次 Runtime 构造等待秒数 |

两个凭据任一缺失时数据请求返回 409 `PROVIDER_DISABLED`，健康检查仍正常。Runtime 使用专属线程、peek 门闩复位、watchdog、04:00 与休眠订阅代际回收；停机显式失败在飞请求并关闭 SDK。不要把密码写入日志、内部 RPC 或 TapeHub 服务环境。
