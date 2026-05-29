"""fix source_links.source_role CHECK — DTO SourceRole와 정합 (코드 정합 수정).

Revision ID: 0004_fix_source_role_check
Revises: 0003_consistency_reports
Create Date: 2026-05-29

마이그레이션 0002의 ``ck_source_links_role`` CHECK가 DTO ``SourceRole`` enum
(= ``docs/feature-model.md §3`` 정본)과 불일치했다:

- **0002 CHECK (오류)**: primary / enrichment / **geocoded** / **phone** / media /
  weather_context / **observation** / **external_link**
- **DTO SourceRole / feature-model.md / data-model.md (정본)**: primary /
  **base_address** / **base_coordinate** / enrichment / **correction** /
  **duplicate_candidate** / media / weather_context

``geocoded`` / ``phone`` / ``observation`` / ``external_link``은 코드/테스트/문서
어디에서도 사용되지 않는 잘못 들어간 값이었고, ``base_address`` 등 DTO가 실제로
만들 수 있는 값은 DB CHECK가 거부했다 (잠재 적재 버그). CHECK를 정본으로 교체한다.

기존 행 영향: 현재까지 적재 코드는 ``primary`` / ``enrichment``만 emit하므로
(둘 다 양쪽 CHECK에 공통) 기존 데이터는 새 CHECK를 위반하지 않는다.

ADR 참조: ADR-018(DTO 계약) / ``docs/feature-model.md §3``.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0004_fix_source_role_check"
down_revision: str | Sequence[str] | None = "0003_consistency_reports"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINT = "ck_source_links_role"
_TABLE = "source_links"
_SCHEMA = "provider_sync"

# 정본 (DTO SourceRole / feature-model.md §3 / data-model.md).
_NEW_CHECK = (
    "source_role IN ('primary','base_address','base_coordinate',"
    "'enrichment','correction','duplicate_candidate','media','weather_context')"
)
# 0002의 잘못된 값 (downgrade 복원용).
_OLD_CHECK = (
    "source_role IN ('primary','enrichment','geocoded','phone',"
    "'media','weather_context','observation','external_link')"
)


def upgrade() -> None:
    op.drop_constraint(_CONSTRAINT, _TABLE, schema=_SCHEMA, type_="check")
    op.create_check_constraint(_CONSTRAINT, _TABLE, _NEW_CHECK, schema=_SCHEMA)


def downgrade() -> None:
    op.drop_constraint(_CONSTRAINT, _TABLE, schema=_SCHEMA, type_="check")
    op.create_check_constraint(_CONSTRAINT, _TABLE, _OLD_CHECK, schema=_SCHEMA)
