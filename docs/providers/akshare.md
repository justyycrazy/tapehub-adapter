# AkShare adapter 运行说明

服务入口为 `tapehub_adapter_akshare.app:app`，容器单 worker，仅实现 `/internal/v1/bars`。`TAPEHUB_AKSHARE_MAX_INFLIGHT` 默认 4；无上游凭据。同步 SDK 调用在有界线程池中执行，客户端取消不会强杀已开始的上游调用。

代码、复权、单位、时区和全量拉取接口的详细行为以 TapeHub 主仓库 `docs/providers/akshare.md` 为公共说明，以本服务 `request_mapper.py`/`response_mapper.py` 为实现。SDK 未安装或缺少已解析 operation 时返回 `PROVIDER_NOT_IMPLEMENTED`，未知标的映射返回 `UNSUPPORTED_CAPABILITY`。
