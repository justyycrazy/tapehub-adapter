# Baostock adapter 运行说明

服务入口为 `tapehub_adapter_baostock.app:app`，容器单 worker，仅实现 `/internal/v1/bars`。`TAPEHUB_BAOSTOCK_MAX_INFLIGHT` 默认 4，无上游凭据。

SDK 全局 socket 非线程安全，服务使用模块级锁串行化登录、查询和行收集；会话懒登录并复用，未登录/网络类错误重登一次、重试一次。不要以多 worker 或多 replica 方式共享该状态。达 5000 原始行时 `partial=true`。宽分钟查询超时由 TapeHub 总超时控制。
