from typing import Any


class StubFrame:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def to_dict(self, _: str) -> list[dict[str, Any]]:
        return list(self.rows)


class StubAkshare:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.responses: dict[str, list[dict[str, Any]]] = {}

    def set_rows(self, operation: str, rows: list[dict[str, Any]]) -> None:
        self.responses[operation] = rows

    def __getattr__(self, operation: str) -> Any:
        def call(**kwargs: Any) -> StubFrame:
            self.calls.append((operation, kwargs))
            return StubFrame(self.responses.get(operation, []))

        return call
