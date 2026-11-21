import pytest
from stub_akshare import StubAkshare


@pytest.fixture()
def stub() -> StubAkshare:
    return StubAkshare()
