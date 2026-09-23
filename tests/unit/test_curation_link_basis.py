"""승인 근거(``match_basis``) 정의가 한 곳에만 있는지 고정한다.

`0072`가 근거 축을 넣은 뒤 판정이 세 곳에 흩어졌다 — DB CHECK, 공개 표면 술어,
merge 재타게팅 whitelist. 값이 하나 늘 때 한 곳만 고치면 **아무도 오류를 내지 않고**
"공개 표면은 믿는데 merge가 끊는" 상태가 된다. 그 조합을 여기서 막는다.
"""

from __future__ import annotations

import re
from pathlib import Path

from sqlalchemy import CheckConstraint

from kortravelmap.infra.curation_link_basis import (
    ALL_LINK_BASES,
    TRUSTED_LINK_BASES,
    UNATTRIBUTED_LINK_BASIS,
    trusted_basis_sql,
)

#: DB CHECK의 현행 정본 — **배포되는 카탈로그 그 자체**다.
#:
#: 종전에는 이 값을 `302` migration의 모듈 상수에서 읽었다. 스쿼시로 그 파일이
#: 사라졌지만, 애초에 그것은 CHECK가 되기 **전**의 문자열이었다. 덤프는 DB가
#: 정규화해 돌려준 CHECK 본문이므로 한 칸 더 가깝다.
_HEAD_SCHEMA = Path(__file__).resolve().parents[2] / "alembic" / "head-schema.sql"

_MATCH_BASIS_CHECK = re.compile(
    r"CONSTRAINT \S*curation_link_decisions\S*basis CHECK \(\(match_basis = ANY \(ARRAY\[([^]]+)\]"
)


def _head_check_values() -> set[str]:
    found = _MATCH_BASIS_CHECK.search(_HEAD_SCHEMA.read_text(encoding="utf-8"))
    assert found is not None, (
        "head 덤프에서 `match_basis` CHECK를 찾지 못했다 — 제약 이름이나 덤프 형태가 "
        "바뀌었다면 이 정규식을 갱신하라. 유도가 비면 아래 검사가 공허해진다."
    )
    return _check_values(found.group(1))


def _check_values(clause: str) -> set[str]:
    return set(re.findall(r"'([a-z_]+)'", clause))


def test_db_check_and_python_definition_agree() -> None:
    """DB CHECK가 허용하는 값과 Python이 아는 값이 같아야 한다."""
    assert _head_check_values() == set(ALL_LINK_BASES)


def test_unattributed_basis_is_never_trusted() -> None:
    """근거를 복구할 수 없는 값은 어떤 경로에서도 공개 승인 근거가 아니다."""
    assert UNATTRIBUTED_LINK_BASIS not in TRUSTED_LINK_BASES
    assert UNATTRIBUTED_LINK_BASIS not in trusted_basis_sql("d.match_basis")


def test_orm_metadata_check_matches_python_definition() -> None:
    """SQLAlchemy metadata의 CHECK도 같은 집합이어야 한다.

    alembic autogenerate는 CHECK 변경을 감지하지 못하므로, 여기가 어긋나도
    `alembic check`는 조용히 통과한다. 그래서 테스트로 잡는다.
    """
    from kortravelmap.infra.models import CurationLinkDecisionRow

    clauses = [
        str(constraint.sqltext)
        for constraint in CurationLinkDecisionRow.__table__.constraints
        if isinstance(constraint, CheckConstraint) and "match_basis" in str(constraint.sqltext)
    ]
    assert len(clauses) == 1
    assert _check_values(clauses[0]) == set(ALL_LINK_BASES)


def test_public_surface_and_merge_share_one_definition() -> None:
    """공개 표면과 merge 재타게팅이 같은 술어를 쓴다.

    각자 문자열을 열거하면 값이 늘 때 조용히 갈라진다 — 그것이 H40에서 실제로
    일어날 뻔한 일이다.
    """
    from kortravelmap.infra import curation_repo, merge_repo

    predicate_fragment = trusted_basis_sql("x").removeprefix("x ")
    assert predicate_fragment in curation_repo._trusted_link_sql("item")
    assert predicate_fragment in merge_repo._MOVE_CURATION_ITEMS_SQL


def test_trusted_basis_sql_is_deterministic() -> None:
    """값 순서가 흔들리면 SQL 텍스트를 비교하는 위 검사가 무의미해진다."""
    assert trusted_basis_sql("d.basis") == trusted_basis_sql("d.basis")
    assert trusted_basis_sql("d.basis").startswith("d.basis IN (")
