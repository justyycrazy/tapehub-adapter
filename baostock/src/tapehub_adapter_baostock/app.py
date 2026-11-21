"""Baostock 适配器 HTTP 入口。"""

from tapehub_adapter_baostock.adapter import BaostockAdapter
from tapehub_adapter_common.app import create_app as create_adapter_app
from tapehub_adapter_common.config import env_int


def create_app() -> object:
    adapter = BaostockAdapter(max_inflight=env_int("TAPEHUB_BAOSTOCK_MAX_INFLIGHT", 4))
    return create_adapter_app("tapehub-baostock-adapter", adapter)


app = create_app()
