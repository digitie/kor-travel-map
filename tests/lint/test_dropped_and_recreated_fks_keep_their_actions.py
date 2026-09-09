"""한 마이그레이션이 DROP했다가 다시 ADD하는 FK가 참조 액션을 그대로 갖는지 본다.

## 왜

타입 재키는 FK를 건드릴 생각이 없어도 전부 떨어뜨려야 한다 — 크로스 표 타입 불일치
때문이다. T-VN-39는 그렇게 40개를 떨어뜨리고 34개를 되살린다. 되살리는 쪽은
**보존 작업**이지 재설계가 아니다.

그런데 `ON DELETE CASCADE`를 하나 빠뜨려도 DDL은 조용히 성공한다. 실패는 한참 뒤
런타임에서, 그것도 엉뚱한 얼굴로 온다. 실제 사례:
`feature.purge_manual_feature`는 블로커/캡처를 `pg_constraint.confdeltype`으로 가른다.
`fk_feature_aliases_feature`가 CASCADE에서 NO ACTION으로 바뀌면 모든 Feature의 legacy
alias 1행이 블로커로 세어져 **모든 purge가 100% 실패**한다. 부분 회귀가 아니다.
그리고 그 실패 메시지는 `ck_manual_feature_purge_evidence_bound`를 가리킨다 — FK
액션을 의심할 이유를 아무도 못 얻는다.

## 규칙

같은 마이그레이션 안에서 DROP되고 다시 ADD되는 이름은 액션이 같아야 한다. 정말로
바꿀 생각이면 이름을 바꿔라 — 그러면 이 검사가 비켜 주고, diff를 읽는 사람도 의도를
본다. "같은 이름으로 조용히 다른 것"이 이 검사가 막으려는 전부다.

정본은 `alembic/head-schema.sql`이다. 마이그레이션의 DROP 문에는 액션이 안 적히므로
떨어뜨리기 전 모습을 head에서 읽는다.
"""

from __future__ import annotations

import importlib.util
import pathlib
import re
from typing import Any, Final

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_VERSIONS = _ROOT / "alembic" / "versions"
_HEAD_SCHEMA = _ROOT / "alembic" / "head-schema.sql"

_DROP_FK = re.compile(r"DROP\s+CONSTRAINT\s+(\w+)", re.IGNORECASE)
_ADD_FK = re.compile(r"ADD\s+CONSTRAINT\s+(\w+)\s+FOREIGN KEY\s+(.*)$", re.IGNORECASE | re.DOTALL)
_HEAD_FK = re.compile(r"ADD CONSTRAINT (\w+) FOREIGN KEY (.*?);", re.DOTALL)

#: 참조 액션을 이루는 조각들. 적히지 않으면 PostgreSQL 기본값이 정답이다.
_DEFAULTS: Final[dict[str, str]] = {
    "ON DELETE": "NO ACTION",
    "ON UPDATE": "NO ACTION",
    "MATCH": "SIMPLE",
}


def _actions(clause: str) -> dict[str, str]:
    flat = " ".join(clause.split())
    found: dict[str, str] = {}
    for key, default in _DEFAULTS.items():
        match = re.search(rf"{key}\s+([A-Z]+(?:\s+[A-Z]+)?)", flat)
        found[key] = match.group(1).strip() if match is not None else default
    found["DEFERRABLE"] = "YES" if "DEFERRABLE" in flat else "NO"
    return found


def _head_actions() -> dict[str, dict[str, str]]:
    text = _HEAD_SCHEMA.read_text(encoding="utf-8")
    return {m.group(1): _actions(m.group(2)) for m in _HEAD_FK.finditer(text)}


def _migrations() -> list[tuple[str, Any]]:
    loaded: list[tuple[str, Any]] = []
    for path in sorted(_VERSIONS.glob("*.py")):
        spec = importlib.util.spec_from_file_location(f"_lint_{path.stem}", path)
        assert spec is not None, path
        assert spec.loader is not None, path
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        loaded.append((path.name, module))
    return loaded


def _statements(module: Any) -> tuple[str, ...]:
    statements = getattr(module, "_UPGRADE_STATEMENTS", None)
    return tuple(statements) if statements is not None else ()


def test_recreated_foreign_keys_keep_their_referential_actions() -> None:
    head = _head_actions()
    drifted: list[str] = []

    for name, module in _migrations():
        statements = _statements(module)
        if not statements:
            continue
        dropped = {
            match.group(1)
            for statement in statements
            for match in _DROP_FK.finditer(statement)
        }
        for statement in statements:
            add = _ADD_FK.search(" ".join(statement.split()))
            if add is None:
                continue
            constraint = add.group(1)
            if constraint not in dropped or constraint not in head:
                continue
            before, after = head[constraint], _actions(add.group(2))
            for key in sorted(set(before) | set(after)):
                if before.get(key) != after.get(key):
                    drifted.append(
                        f"{name} {constraint}: {key} {before.get(key)} → {after.get(key)}"
                    )

    assert not drifted, (
        "DROP 후 재생성된 FK가 참조 액션을 잃었다:\n  "
        + "\n  ".join(drifted)
        + "\n\n같은 이름으로 다른 액션을 만드는 것은 DDL 단계에서 조용히 성공하고 "
        "런타임에서 엉뚱한 얼굴로 실패한다. 액션을 정말 바꿀 생각이면 제약 이름을 "
        "바꿔라 — 그래야 diff를 읽는 사람이 의도를 본다."
    )


def test_dropped_foreign_keys_are_either_recreated_or_accounted_for() -> None:
    """되살리지 않은 FK는 마이그레이션이 그 사실을 문서로 들고 있어야 한다."""
    head = _head_actions()
    unexplained: list[str] = []

    for name, module in _migrations():
        statements = _statements(module)
        if not statements:
            continue
        dropped = {
            match.group(1)
            for statement in statements
            for match in _DROP_FK.finditer(statement)
            if match.group(1) in head
        }
        recreated = {
            add.group(1)
            for statement in statements
            if (add := _ADD_FK.search(" ".join(statement.split()))) is not None
        }
        source = (_VERSIONS / name).read_text(encoding="utf-8")
        for constraint in sorted(dropped - recreated):
            # 사라진 제약은 마이그레이션 안에서 이름으로 설명돼야 한다. `_FK_DROP`
            # 목록의 등장은 설명이 아니므로, 주석/docstring에 한 번 더 나와야 한다.
            mentions = source.count(constraint)
            if mentions < 2:
                unexplained.append(f"{name} {constraint}")

    assert not unexplained, (
        "FK를 떨어뜨리고 되살리지도, 왜 안 되살리는지 적지도 않았다:\n  "
        + "\n  ".join(unexplained)
        + "\n\n참조 무결성이 하나 사라지는 일은 diff에서 한 줄이지만 데이터에서는 "
        "영구적이다. 마이그레이션 본문에 그 이름과 이유를 남겨라."
    )
