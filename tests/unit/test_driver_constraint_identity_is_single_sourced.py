"""드라이버 예외에서 constraint 이름을 꺼내는 방법이 한 곳에만 있는지 본다.

이 저장소는 `postgresql+asyncpg`로 돈다. asyncpg 예외는 `.sqlstate`와
`.constraint_name`을 **직접** 들고 있고 `.diag`가 없다 — `.diag`는 psycopg의
API다. 그래서 `getattr(orig, "diag", None)`로 constraint 이름을 읽는 코드는
런타임에서 **항상 `None`**을 얻는다. sqlstate는 같은 자리에서 잘 읽히므로
아무도 이상을 느끼지 못한다.

이 결함이 실제로 있었다. `feature_request_repo._procedure_error`의
`ck_feature_request_pending` 분기가 한 번도 발화하지 않아, 이미 처리된 요청을
다시 넣으면 "이미 처리되었습니다"(상태 충돌) 대신 "값이 올바르지 않습니다"
(검증 오류)가 나갔다. `feature_reference_reconciliation_repo`의 M05 allow-list도
같은 이유로 통째로 죽어 있었다. PostGIS 통합 테스트의 헬퍼도 같았고, 그 때문에
`test_dedup_candidate_rejects_uuid_identity_and_accepts_text_feature_id`가
2026-09-01부터 main을 red로 잡아 두고 있었다 — 스키마는 내내 정상이었다.

정본은 `feature_update_active_repo._driver_constraint_identity` 하나다. asyncpg와
psycopg를 모두 다루고 `orig`/`__cause__`/`__context__` 체인까지 걷는다. 이
게이트는 그 사실이 다시 네 곳으로 흩어지는 것을 막는다.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]
_CANONICAL = _ROOT / "src" / "kortravelmap" / "infra" / "feature_update_active_repo.py"
_SCANNED = (_ROOT / "src" / "kortravelmap", _ROOT / "tests", _ROOT / "packages")
_DIAG_READ = re.compile(r'"diag"|\.diag\b')
# 이 게이트 자신은 규칙을 **설명**하느라 그 이름을 적는다. 정본과 함께 면제한다.
_EXEMPT = frozenset({_CANONICAL, Path(__file__).resolve()})


def _offenders() -> list[str]:
    found: list[str] = []
    for root in _SCANNED:
        for path in sorted(root.rglob("*.py")):
            if path in _EXEMPT or "__pycache__" in path.parts:
                continue
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            ):
                if _DIAG_READ.search(line):
                    found.append(f"{path.relative_to(_ROOT).as_posix()}:{number}")
    return found


def test_the_canonical_reader_handles_both_drivers() -> None:
    """정본이 asyncpg 직속 속성과 psycopg의 `diag`를 모두 읽어야 한다."""
    source = _CANONICAL.read_text(encoding="utf-8")
    body_start = source.index("def _driver_constraint_identity(")
    body = source[body_start : source.index("\ndef ", body_start + 1)]
    assert 'getattr(candidate, "constraint_name", None)' in body
    assert 'getattr(diag, "constraint_name", None)' in body
    assert 'getattr(candidate, "sqlstate", None)' in body


def test_nothing_else_reads_the_psycopg_only_diag_attribute() -> None:
    assert _offenders() == [], _offenders()
