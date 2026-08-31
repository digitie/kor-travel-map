"""승인 근거(``match_basis``) 정의가 한 곳에만 있는지 고정한다.

`0072`가 근거 축을 넣은 뒤 판정이 세 곳에 흩어졌다 — DB CHECK, 공개 표면 술어,
merge 재타게팅 whitelist. 값이 하나 늘 때 한 곳만 고치면 **아무도 오류를 내지 않고**
"공개 표면은 믿는데 merge가 끊는" 상태가 된다. 그 조합을 여기서 막는다.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType

from sqlalchemy import CheckConstraint

from kortravelmap.infra.curation_link_basis import (
    ALL_LINK_BASES,
    TRUSTED_LINK_BASES,
    UNATTRIBUTED_LINK_BASIS,
    trusted_basis_sql,
)

#: DB CHECK의 현행 정본 — `302`가 `manual_feature_child`를 widen했다(T-VN-M03).
#: 종전 정본이던 legacy `0073`은 아카이브 이력이다.
_MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "302_m03_import_child_issuance.py"
)


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_h40_migration", _MIGRATION)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _check_values(clause: str) -> set[str]:
    return set(re.findall(r"'([a-z_]+)'", clause))


def test_db_check_and_python_definition_agree() -> None:
    """DB CHECK가 허용하는 값과 Python이 아는 값이 같아야 한다."""
    migration = _load_migration()
    assert _check_values(migration._MATCH_BASIS_ADD_NOT_VALID) == set(ALL_LINK_BASES)


def test_downgrade_check_drops_exactly_the_new_basis() -> None:
    """downgrade CHECK는 `manual_feature_child`만 빠진 집합이어야 한다."""
    migration = _load_migration()
    assert _check_values(migration._MATCH_BASIS_NARROW) == set(ALL_LINK_BASES) - {
        "manual_feature_child"
    }


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
