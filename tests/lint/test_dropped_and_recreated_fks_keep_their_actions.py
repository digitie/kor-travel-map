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

## 정본을 한 번 틀렸다

이 검사는 처음에 "떨어뜨리기 전 모습"을 `alembic/head-schema.sql`에서 읽었다.
**그것이 항진명제였다.** head-schema는 마이그레이션을 전부 적용한 뒤 덤프한 결과다.
즉 309가 만든 `ADD CONSTRAINT`가 곧 head의 그 줄이므로, 둘을 비교하면 언제나 같다.
CASCADE를 하나 빠뜨리면 **양쪽이 함께** 바뀌어서 이 검사는 초록으로 남는다 — 막으려던
바로 그 사고를 못 본다. 적대 리뷰가 집었다.

그래서 재키 **이전**의 액션을 얼려 정본으로 삼는다:
`contracts/vnext/foreign-key-referential-actions-v1.json` (308 시점,
커밋 25808bcf). 이 파일은 마이그레이션이 만들지 않으므로 함께 움직이지 않는다.
아래 sha 핀이 있어서, 검사를 통과시키려고 얼린 값을 고치는 일은 두 자리를 함께
고치는 일이 된다 — diff에서 보인다.

head-schema 대조는 버리지 않고 **이름을 사실대로 바꿔** 남긴다. 그것이 실제로
보장하는 것은 액션 보존이 아니라 "마이그레이션을 고치고 head-schema 재생성을
잊지 않았다"이고, 그건 그것대로 쓸모가 있다.

## 규칙

같은 마이그레이션 안에서 DROP되고 다시 ADD되는 이름은 액션이 같아야 한다. 정말로
바꿀 생각이면 이름을 바꿔라 — 그러면 이 검사가 비켜 주고, diff를 읽는 사람도 의도를
본다. "같은 이름으로 조용히 다른 것"이 이 검사가 막으려는 전부다.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import pathlib
import re
from typing import Any, Final

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_VERSIONS = _ROOT / "alembic" / "versions"
_HEAD_SCHEMA = _ROOT / "alembic" / "head-schema.sql"
_FROZEN = _ROOT / "contracts" / "vnext" / "foreign-key-referential-actions-v1.json"

#: 얼린 정본의 내용 핀. 값을 고쳐 검사를 통과시키려면 여기도 함께 고쳐야 한다.
_FROZEN_SHA256: Final[str] = (
    "80704719d1dcf9b65e7d242a650481ca43333eaa691c6b8f7700ed049e57a6a5"
)

_DROP_FK = re.compile(r"DROP\s+CONSTRAINT\s+(\w+)", re.IGNORECASE)
_ADD_FK = re.compile(
    r"ADD\s+CONSTRAINT\s+(\w+)\s+FOREIGN KEY\s+(.*)$", re.IGNORECASE | re.DOTALL
)
_HEAD_FK = re.compile(r"ADD CONSTRAINT (\w+) FOREIGN KEY (.*?);", re.DOTALL)

#: 참조 액션을 이루는 조각들. 적히지 않으면 PostgreSQL 기본값이 정답이다.
_DEFAULTS: Final[dict[str, str]] = {
    "ON DELETE": "NO ACTION",
    "ON UPDATE": "NO ACTION",
    "MATCH": "SIMPLE",
}

#: 하한 — 대상이 사라지면 초록이 아니라 빨강이어야 한다. 항진명제였던 판이
#: 조용히 초록으로 남았던 것과 같은 부류를 여기서 한 번 더 막는다.
_MINIMUM_FROZEN_CONSTRAINTS: Final[int] = 200
_MINIMUM_COMPARED_PAIRS: Final[int] = 30


def _actions(clause: str) -> dict[str, str]:
    flat = " ".join(clause.split())
    found: dict[str, str] = {}
    for key, default in _DEFAULTS.items():
        match = re.search(rf"{key}\s+([A-Z]+(?:\s+[A-Z]+)?)", flat)
        found[key] = match.group(1).strip() if match is not None else default
    found["DEFERRABLE"] = "YES" if "DEFERRABLE" in flat else "NO"
    return found


def _frozen_actions() -> dict[str, dict[str, str]]:
    """재키 이전(308) FK 액션 — 마이그레이션과 함께 움직이지 않는 정본."""
    raw = _FROZEN.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    assert digest == _FROZEN_SHA256, (
        f"얼린 FK 액션 정본이 바뀌었습니다: {digest} (기대 {_FROZEN_SHA256}). "
        "이 파일은 308 시점의 사실을 담고 있어서 바뀔 이유가 없습니다. 정말로 "
        "다시 뜬 것이라면 이 핀도 같은 커밋에서 함께 고치세요."
    )
    document = json.loads(raw.decode("utf-8"))
    constraints: dict[str, dict[str, str]] = document["constraints"]
    assert len(constraints) >= _MINIMUM_FROZEN_CONSTRAINTS, (
        f"얼린 정본이 FK {len(constraints)}개뿐입니다 — 정본이 비었습니다."
    )
    return constraints


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


def _drop_add_pairs() -> list[tuple[str, str, dict[str, str]]]:
    """(마이그레이션 파일명, 제약 이름, 다시 만든 액션) — DROP과 ADD가 짝인 것만."""
    pairs: list[tuple[str, str, dict[str, str]]] = []
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
            if add is None or add.group(1) not in dropped:
                continue
            pairs.append((name, add.group(1), _actions(add.group(2))))
    return pairs


def test_recreated_foreign_keys_keep_their_referential_actions() -> None:
    frozen = _frozen_actions()
    drifted: list[str] = []
    compared = 0

    for name, constraint, after in _drop_add_pairs():
        before = frozen.get(constraint)
        if before is None:
            # 얼린 시점 이후에 태어난 FK. 비교할 "이전"이 없다.
            continue
        compared += 1
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
    assert compared >= _MINIMUM_COMPARED_PAIRS, (
        f"얼린 정본과 실제로 대조한 FK가 {compared}개뿐입니다 "
        f"(하한 {_MINIMUM_COMPARED_PAIRS}). 재생성 짝이 사라졌거나 이름이 전부 "
        "정본 밖으로 나갔다는 뜻이고, 어느 쪽이든 이 검사는 더 이상 아무것도 "
        "재지 않습니다."
    )


def test_head_schema_matches_the_migrations_that_recreate_foreign_keys() -> None:
    """head-schema 재생성을 잊지 않았는지 본다.

    이것은 액션 **보존** 보장이 아니다 — 마이그레이션과 head-schema는 함께
    움직이므로 둘이 같다는 사실은 보존을 말해 주지 않는다. 보존은 위 검사가
    얼린 정본으로 본다. 여기서 보는 것은 "마이그레이션만 고치고 덤프를 다시
    뜨지 않은" 상태이고, 그 상태는 head 오라클을 쓰는 다른 검사 전부를 조용히
    거짓말하게 만든다.
    """
    head = _head_actions()
    stale: list[str] = []
    for name, constraint, after in _drop_add_pairs():
        landed = head.get(constraint)
        if landed is None:
            stale.append(f"{name} {constraint}: head-schema에 없음")
            continue
        if landed != after:
            stale.append(f"{name} {constraint}: head {landed} ≠ 마이그레이션 {after}")
    assert not stale, (
        "마이그레이션이 만든 FK와 head-schema가 어긋난다:\n  "
        + "\n  ".join(stale)
        + "\n\n`KTM_WRITE_HEAD_SCHEMA=1`로 head-schema를 다시 뜨세요."
    )


def test_dropped_foreign_keys_are_either_recreated_or_accounted_for() -> None:
    """되살리지 않은 FK는 마이그레이션이 그 사실을 문서로 들고 있어야 한다."""
    frozen = _frozen_actions()
    unexplained: list[str] = []

    for name, module in _migrations():
        statements = _statements(module)
        if not statements:
            continue
        dropped = {
            match.group(1)
            for statement in statements
            for match in _DROP_FK.finditer(statement)
            if match.group(1) in frozen
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
