"""T-READ-03 — 공개 읽기 마감의 배선과 예산 계산(DB 없음).

- 범위 안 route(계획 §8.4 T-READ-03 변경 9)는 새 공개 읽기 의존성을, 그 밖의 route는 쓰지 않는다.
  격리 수준은 그대로다 — 새 의존성은 옛 의존성(``get_session``·``get_read_snapshot_session``)을
  감싼다.
- 문장 상한 = 남은 시간 − 0.3초(바닥 250 ms), 여유 이하면 SQL 전에 ``ReadBudgetExceeded``.
실제 PostgreSQL 동작은 ``tests/integration/test_api_public_read_deadline.py``가 본다.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from kortravelmap.api import db as api_db
from kortravelmap.api.app import create_app
from kortravelmap.api.route_policy import _iter_flattened_routes, _resolve_route
from kortravelmap.api.settings import ApiSettings
from kortravelmap.infra import public_read_budget

pytestmark = pytest.mark.unit

_PUBLIC = api_db.get_public_read_session
_SNAPSHOT = api_db.get_public_read_snapshot_session
_SLOW = api_db.get_public_read_slow_snapshot_session

#: (method, path) → 새 의존성. 옛 의존성과의 대응(격리 수준 불변)은 PR 본문의 표와 같다.
EXPECTED: dict[tuple[str, str], Callable[..., Any]] = {
    ("GET", "/v1/features"): _PUBLIC,
    ("GET", "/v1/features/in-bounds"): _PUBLIC,
    ("GET", "/v1/features/search"): _SNAPSHOT,
    ("GET", "/v1/features/nearby"): _PUBLIC,
    ("GET", "/v1/features/nearby/by-target"): _SNAPSHOT,
    ("GET", "/v1/features/{feature_id}"): _SNAPSHOT,
    ("GET", "/v1/features/{feature_id}/contained-features"): _SNAPSHOT,
    ("GET", "/v1/features/{feature_id}/price"): _SNAPSHOT,
    ("GET", "/v1/features/{feature_id}/price/snapshot"): _SNAPSHOT,
    ("POST", "/v1/features/batch"): _SNAPSHOT,
    ("GET", "/v1/categories"): _PUBLIC,
    ("GET", "/v1/providers"): _PUBLIC,
    ("GET", "/v1/providers/{provider}/last-sync"): _PUBLIC,
    ("GET", "/v1/public/beaches"): _PUBLIC,
    ("GET", "/v1/public/beaches/map-markers"): _PUBLIC,
    ("GET", "/v1/public/beaches/{feature_id}"): _SNAPSHOT,
    ("GET", "/v1/public/festivals/monthly"): _SLOW,
    ("GET", "/v1/public/festivals/map-markers"): _PUBLIC,
    ("GET", "/v1/public/festivals/{feature_id}"): _SNAPSHOT,
    ("GET", "/v1/curations"): _SNAPSHOT,
    ("GET", "/v1/curations/collections"): _PUBLIC,
    ("GET", "/v1/curations/collections/{collection_id}"): _SNAPSHOT,
    ("GET", "/v1/curations/features/{feature_id}"): _SNAPSHOT,
    ("GET", "/v1/place-attributes"): _PUBLIC,
}
_PUBLIC_DEPS = {_PUBLIC, _SNAPSHOT, _SLOW}


def _calls(dependant: Any) -> Iterator[Callable[..., Any]]:
    for dep in getattr(dependant, "dependencies", []) or []:
        if dep.call is not None:
            yield dep.call
        yield from _calls(dep)


def _route_deps() -> dict[tuple[str, str], set[Callable[..., Any]]]:
    app = create_app(ApiSettings(public_api_key_required=False, vworld_api_key=None))
    table: dict[tuple[str, str], set[Callable[..., Any]]] = {}
    for entry in _iter_flattened_routes(app):
        path, _schema_path, methods, is_websocket, _schema, dependant = _resolve_route(entry)
        if path is None or is_websocket:
            continue
        for method in methods:
            table[(method, path)] = set(_calls(dependant))
    return table


def test_scoped_public_routes_use_public_read_dependencies() -> None:
    table = _route_deps()
    missing = sorted(key for key in EXPECTED if key not in table)
    assert missing == [], missing
    for key, dependency in EXPECTED.items():
        assert dependency in table[key], key
        others = (_PUBLIC_DEPS - {dependency}) & table[key]
        assert not others, (key, others)


def test_no_route_outside_scope_uses_public_read_dependencies() -> None:
    table = _route_deps()
    leaked = sorted(
        key for key, calls in table.items() if key not in EXPECTED and calls & _PUBLIC_DEPS
    )
    assert leaked == [], leaked


def test_public_dependencies_wrap_the_old_isolation_dependencies() -> None:
    import inspect

    for wrapper, inner in (
        (_PUBLIC, api_db.get_session),
        (_SNAPSHOT, api_db.get_read_snapshot_session),
        (_SLOW, api_db.get_read_snapshot_session),
    ):
        default = inspect.signature(wrapper).parameters["session"].annotation
        assert inner.__name__ in str(default), (wrapper, default)


class _FakeSession:
    def __init__(self, deadline: float | None) -> None:
        self.info: dict[str, object] = {}
        if deadline is not None:
            self.info[public_read_budget.PUBLIC_READ_DEADLINE_INFO_KEY] = deadline


def test_statement_timeout_is_remaining_minus_margin_with_floor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(public_read_budget.time, "monotonic", lambda: 100.0)

    def ms(deadline: float | None) -> int | None:
        return public_read_budget.public_read_statement_timeout_ms(
            _FakeSession(deadline)  # type: ignore[arg-type]
        )

    assert ms(None) is None
    assert ms(104.5) == 4200
    assert ms(100.4) == 250
    with pytest.raises(public_read_budget.ReadBudgetExceeded):
        ms(100.3)
    with pytest.raises(public_read_budget.ReadBudgetExceeded):
        ms(99.0)


def test_session_without_info_has_no_deadline() -> None:
    assert public_read_budget.public_read_deadline(SimpleNamespace()) is None  # type: ignore[arg-type]
