"""receipt head CHECK가 **실제로 실행되는 DDL**로 graph의 모든 revision을 받는지.

## 왜 이 게이트가 필요한가

`ops.application_schema_operation_receipts.destination_head`에는 값 열거 CHECK가 있다.
같은 표의 다른 CHECK 열 개는 전부 형식 검사인데(`~ '^[0-9a-f]{64}$'` 등) head만 값
열거인 이유는 그 자리가 정확한 동등성을 요구하기 때문이고, 그 엄격함은 옳다.

문제는 열거가 아니라 **갱신 의무를 아무것도 강제하지 않는다는 것**이었다. migration을
더하며 잊으면 코드는 전부 통과하고, 프로덕션 fresh 설치만
``new row violates check constraint``로 죽는다.

## 종전 버전이 왜 부족했는가

첫 버전은 `alembic/versions/*.py`를 **정규식으로 훑었다.** 적대 리뷰가 실행으로 셋을
뚫었다.

| 우회 | 왜 통과했나 |
|---|---|
| `_RECEIPT_HEAD_CHECK` 상수는 선언했지만 `_UPGRADE_STATEMENTS`에 넣지 않음 | 텍스트만 봤다 |
| CHECK를 **docstring 안에만** 적음 | 텍스트만 봤다 |
| `303`이 재작성하며 중간 head를 빠뜨림(`IN ('300','303')`) | head 포함만 봤다 |

앞의 둘은 "복사·붙여넣기하다 마지막 원소를 빠뜨린다"는 가장 흔한 실수 형태다. 세 번째는
원래 버그보다 **나쁘다** — `301`/`302` receipt 행이 있는 설치에서는 `ADD CONSTRAINT`
자체가 실패해 배포 도중에 멈춘다.

또 파일명 정렬(`sorted(glob("*.py"))`)로 "마지막 선언"을 골랐는데, 이 저장소의 과거
관례(`0200`~`0236`)를 따라 `0303_...py`로 이름 지으면 `300_schema_baseline.py`보다 앞서
정렬돼 **올바른 migration에서 게이트가 실패한다.**

## 그래서 무엇을 바꿨나

- **모듈을 import해 `_UPGRADE_STATEMENTS`를 본다.** 실행되지 않는 선언은 존재하지 않는
  것으로 취급한다. 텍스트 우회 둘이 함께 닫힌다.
- **graph 위상 순서**로 마지막 선언을 고른다. 파일명과 무관해진다.
- **graph의 모든 revision**이 열거에 있어야 한다. 결손 방향도 잡는다.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path
from types import ModuleType

import pytest

from kortravelmap.infra.application_schema_head import (
    BASELINE_ROOT_REVISION,
    application_schema_head,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
VERSIONS = REPO_ROOT / "alembic" / "versions"
GRAPH_PATH = REPO_ROOT / "src" / "kortravelmap" / "_application_migration_graph.json"

_CONSTRAINT = "ck_application_schema_operation_receipts_head"
_ALLOWED = re.compile(
    r"ADD\s+CONSTRAINT\s+" + _CONSTRAINT + r"\s+CHECK\s*\(\s*destination_head\s+(.*?)\)",
    re.IGNORECASE | re.DOTALL,
)
_LITERAL = re.compile(r"'([^']+)'")


def _graph_order() -> tuple[str, ...]:
    """root → head 위상 순서. 파일명 정렬에 기대지 않는다."""
    payload = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
    revisions = payload["revisions"]
    parents = {
        str(entry["revision"]): tuple(str(p) for p in (entry.get("down_revision") or ()))
        for entry in revisions
    }
    ordered: list[str] = []
    remaining = dict(parents)
    while remaining:
        ready = sorted(
            revision
            for revision, downs in remaining.items()
            if all(down in ordered for down in downs)
        )
        if not ready:
            raise AssertionError(f"migration graph에 순환이 있다: {sorted(remaining)}")
        ordered.extend(ready)
        for revision in ready:
            remaining.pop(revision)
    return tuple(ordered)


def _load(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"_migration_probe_{path.stem}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _revision_modules() -> dict[str, ModuleType]:
    modules: dict[str, ModuleType] = {}
    for path in sorted(VERSIONS.glob("*.py")):
        module = _load(path)
        revision = getattr(module, "revision", None)
        assert isinstance(revision, str) and revision, f"{path.name}: revision이 없다"
        assert revision not in modules, f"revision 중복: {revision}"
        modules[revision] = module
    return modules


def _executed_upgrade_sql(module: ModuleType) -> str:
    """**실행되는** upgrade DDL만 이어 붙인다.

    `_UPGRADE_STATEMENTS`에 들어가지 않은 상수도, docstring에 적힌 SQL도 여기 없다 —
    실행되지 않는 선언은 계약이 아니다.
    """
    statements = getattr(module, "_UPGRADE_STATEMENTS", None)
    if statements is None:
        return ""
    assert isinstance(statements, tuple), "_UPGRADE_STATEMENTS는 tuple이어야 한다"
    return "\n".join(str(item) for item in statements)


def _allowed_heads() -> tuple[str, ...]:
    """graph 위상 순서상 **마지막으로 실행되는** 허용 head 집합."""
    modules = _revision_modules()
    latest: tuple[str, ...] = (BASELINE_ROOT_REVISION,)
    for revision in _graph_order():
        module = modules.get(revision)
        if module is None:
            continue
        for match in _ALLOWED.finditer(_executed_upgrade_sql(module)):
            latest = tuple(_LITERAL.findall(match.group(1)))
    return latest


def test_receipt_head_check_admits_every_revision_in_the_graph() -> None:
    """**이 게이트의 본체.**

    현재 head가 빠지면 fresh 설치가 receipt를 쓰는 순간 죽고, **중간 revision이 빠지면**
    그 head로 설치된 DB에서 `ADD CONSTRAINT` 자체가 실패해 배포가 도중에 멈춘다.
    후자가 더 나쁘므로 둘 다 본다.
    """
    allowed = set(_allowed_heads())
    missing = [revision for revision in _graph_order() if revision not in allowed]

    assert not missing, (
        f"receipt head CHECK 허용 집합에 없는 revision {missing} — 새 migration의 "
        f"`_UPGRADE_STATEMENTS`에 `ADD CONSTRAINT {_CONSTRAINT} "
        "CHECK (destination_head IN (…))`를 넣고, **graph의 모든 revision**을 열거할 것. "
        "현재 head만 넣으면 중간 revision으로 설치된 DB에서 ALTER가 실패한다."
    )
    assert application_schema_head() in allowed


def test_the_check_must_be_an_executed_statement_not_a_declaration() -> None:
    """선언만 하고 `_UPGRADE_STATEMENTS`에 넣지 않는 실수를 잡는다.

    적대 리뷰가 실증한 두 형태 — 상수 미배선, docstring 전용 — 를 함께 막는다.
    모듈 텍스트에 CHECK가 있는데 실행 문장에는 없으면 실패한다.
    """
    offenders: list[str] = []
    for revision, module in _revision_modules().items():
        source = Path(str(module.__file__)).read_text(encoding="utf-8")
        declared = bool(_ALLOWED.search(source))
        executed = bool(_ALLOWED.search(_executed_upgrade_sql(module)))
        if declared and not executed:
            offenders.append(revision)

    assert not offenders, (
        f"receipt head CHECK가 선언만 되고 실행되지 않는다: {offenders} — "
        "`_UPGRADE_STATEMENTS`에 넣을 것. 실행되지 않는 선언은 계약이 아니다."
    )


def test_the_check_is_a_value_enumeration_not_a_pattern() -> None:
    """열거를 형식 검사로 **낮추지** 못하게 한다.

    갱신 의무는 이미 위에서 강제되므로, DB 층 fail-close를 형식 검사와 맞바꿀 이유가
    없다.
    """
    for revision, module in _revision_modules().items():
        for match in _ALLOWED.finditer(_executed_upgrade_sql(module)):
            body = match.group(1)
            assert "~" not in body, (
                f"{revision}: receipt head CHECK를 형식 검사로 낮췄다 — 정확한 head "
                "동등성은 DB 층에 남겨 둘 것"
            )
            assert _LITERAL.findall(body), f"{revision}: 허용 head 리터럴이 없다"


def test_baseline_root_stays_admitted() -> None:
    """`300`에서 멈춘 기존 설치의 receipt 행이 이미 존재한다."""
    assert BASELINE_ROOT_REVISION in _allowed_heads()


def test_the_gate_is_not_vacuous() -> None:
    """graph에 revision이 하나뿐이면 이 게이트는 아무것도 보지 않는다.

    그 상태를 조용히 통과시키지 않는다 — 게이트가 공회전 중임을 드러내야 한다.
    """
    order = _graph_order()

    assert order, "migration graph가 비었다"
    assert order[0] == BASELINE_ROOT_REVISION
    if len(order) == 1:
        pytest.skip(
            "graph에 baseline root뿐이라 receipt head 게이트가 볼 것이 없다. "
            "migration이 추가되면 자동으로 활성화된다."
        )
