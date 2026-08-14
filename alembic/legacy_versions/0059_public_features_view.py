"""공개 정본 projection ``feature.public_features`` VIEW를 만든다 (ADR-067, T-VN-04).

Revision ID: 0059_public_features_view
Revises: 0058_poi_target_lock_version
Create Date: 2026-07-19

배경 (F-1 양방향 오분류, ADR-067 / D-3)
--------------------------------------
endpoint마다 공개 술어가 달랐다: API 단건/batch는 ``status NOT IN
('hidden','deleted') AND deleted_at IS NULL``, bbox/search/cluster는
``deleted_at IS NULL``만, nearby는 caller 제공 status 필터. 그 결과

- provider retire(``status='inactive'`` + ``deleted_at=now()``)는 경로마다
  다르게 은닉되고,
- admin deactivate(``status='inactive'``, ``deleted_at`` 미세팅)·draft·broken은
  일부 공개 경로에 그대로 노출됐다.

ADR-067은 공개 가능한 행을 ``lifecycle=active AND publication=published AND
quality=valid`` 단일 술어로 정의한다. 직교 3축 컬럼은 T-VN-34에서 도입되고,
Wave 0(T-VN-04)에서는 **현행 컬럼 위에** 그 술어를 매핑한 VIEW만 만든다:

- ``publication=published`` → 현행 ``status``에서 draft/hidden 아님
- ``lifecycle=active``      → 현행 ``status``에서 inactive/deleted 아님 + soft-delete 아님
- ``quality=valid``         → 현행 ``status``에서 broken 아님

세 조건의 교집합은 현행 CHECK(DB 제약명 ``ck_features_status``, 0002에서 생성:
draft/active/inactive/hidden/broken/deleted) 아래에서 정확히 ``status = 'active'``다.
(``models.py``의 선언명 ``features_status``와 DB 제약명이 어긋나는 것은 기존
드리프트로 F-10 소관이다.) ``deleted_at IS NULL``은
status와 deleted_at 사이 결합 CHECK가 아직 없어(불변식 미보장) 방어적으로
함께 요구한다 — provider retire 경로는 둘을 함께 세팅하지만 강제 장치가 없다.

Wave 0 제약 (docs/reports/system-structure-api-schema-review-2026-07-16.md §6.2)
------------------------------------------------------------------------------
이 revision의 DDL은 ``CREATE VIEW`` 하나뿐이다. 같은 술어의 base-table partial
index는 T-VN-34 소유 — 여기서 만들지 않는다. 테이블 변경 0, 완전 가역
(downgrade = DROP VIEW).

``SELECT *``는 뷰 생성 시점에 컬럼 목록으로 고정(expand)된다. 이후 base 컬럼
추가는 뷰에 자동 반영되지 않으므로 컬럼 추가 migration은 뷰 재정의를 함께
검토해야 한다(의도된 강제 — 공개 projection에 새 컬럼이 무심코 노출되는 것을
막는다).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0059_public_features_view"
down_revision: str | Sequence[str] | None = "0058_poi_target_lock_version"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE VIEW feature.public_features AS
        SELECT *
        FROM feature.features
        WHERE status = 'active'
          AND deleted_at IS NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS feature.public_features")
