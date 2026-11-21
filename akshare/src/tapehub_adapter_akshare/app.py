"""AkShare 适配器 HTTP 入口。"""

from tapehub_adapter_akshare.adapter import AkshareAdapter
from tapehub_adapter_common.app import create_app as create_adapter_app
from tapehub_adapter_common.config import env_int


def create_app() -> object:
    adapter = AkshareAdapter(max_inflight=env_int("TAPEHUB_AKSHARE_MAX_INFLIGHT", 4))
    return create_adapter_app("tapehub-akshare-adapter", adapter)


app = create_app()
