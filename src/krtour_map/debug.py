from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from krtour_map.fixtures import jsonable, redact_sensitive


@dataclass(frozen=True)
class DebugRun:
    function: str
    input: dict[str, Any]
    request: dict[str, Any]
    response: dict[str, Any]
    parsed: Any
    processed: Any
    trace: list[str] = field(default_factory=list)
    error: dict[str, Any] | None = None

    def to_fixture_payload(self) -> dict[str, Any]:
        return {
            "function": self.function,
            "input": redact_sensitive(jsonable(self.input)),
            "request": redact_sensitive(jsonable(self.request)),
            "response": redact_sensitive(jsonable(self.response)),
            "parsed": jsonable(self.parsed),
            "processed": jsonable(self.processed),
            "trace": self.trace,
            "error": redact_sensitive(jsonable(self.error)),
        }
