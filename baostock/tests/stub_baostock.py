import copy
from typing import Any


class StubResultData:
    def __init__(
        self,
        rows: list[dict[str, Any]] | None = None,
        *,
        error_code: str = "0",
        error_msg: str = "success",
    ) -> None:
        self.rows = rows or []
        self.fields = list(self.rows[0]) if self.rows else []
        self.error_code = error_code
        self.error_msg = error_msg
        self._index = -1

    def next(self) -> bool:
        self._index += 1
        return self._index < len(self.rows)

    def get_row_data(self) -> list[Any]:
        return [self.rows[self._index].get(field, "") for field in self.fields]


class StubBaostock:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.result = StubResultData()
        self.pending_errors: list[StubResultData] = []
        self.login_count = 0
        self.login_error_code = "0"
        self.login_error_msg = "success"

    def login(self) -> StubResultData:
        self.login_count += 1
        self.calls.append(("login", {}))
        return StubResultData(error_code=self.login_error_code, error_msg=self.login_error_msg)

    def query_history_k_data_plus(self, **kwargs: Any) -> StubResultData:
        self.calls.append(("query_history_k_data_plus", kwargs))
        if self.pending_errors:
            return self.pending_errors.pop(0)
        return copy.deepcopy(self.result)
