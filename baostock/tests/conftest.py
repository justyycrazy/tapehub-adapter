import pytest
from stub_baostock import StubBaostock


@pytest.fixture()
def stub() -> StubBaostock:
    return StubBaostock()
