"""TqSdk 适配器 HTTP 入口。"""

import os

from tapehub_adapter_common.app import create_app as create_adapter_app
from tapehub_adapter_common.config import env_float, env_int
from tapehub_adapter_tqsdk.adapter import TqsdkAdapter


def create_app() -> object:
    adapter = TqsdkAdapter(
        auth_user=os.getenv("TAPEHUB_TQSDK_AUTH_USER", ""),
        auth_password=os.getenv("TAPEHUB_TQSDK_AUTH_PASSWORD", ""),
        conn_mode=os.getenv("TAPEHUB_TQSDK_CONN_MODE", "shared").strip() or "shared",
        max_inflight=env_int("TAPEHUB_TQSDK_MAX_INFLIGHT_FETCH", 16),
        first_snapshot_timeout=env_float("TAPEHUB_TQSDK_FIRST_SNAPSHOT_TIMEOUT", 5.0),
        subscription_limit=env_int("TAPEHUB_TQSDK_SUBSCRIPTION_LIMIT", 64),
        construct_timeout=env_float("TAPEHUB_TQSDK_CONSTRUCT_TIMEOUT", 30.0),
    )
    return create_adapter_app("tapehub-tqsdk-adapter", adapter)


app = create_app()
