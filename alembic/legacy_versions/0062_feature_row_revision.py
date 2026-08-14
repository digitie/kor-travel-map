"""Feature row에 server-owned monotonic ``row_revision``을 추가한다 (T-VN-13).

report D-10-3 / D-9-8: 모든 Feature write(create/patch/delete/deactivate/review·
provider upsert 포함)에서 단조 증가하는 server-owned revision을 두어 correction
PATCH/DELETE의 If-Match/412·read의 ETag/304 낙관적 동시성 검증을 뒷받침한다.

``0058_poi_target_lock_version``의 lock_version 패턴을 미러링한다 —
``BEFORE UPDATE`` 트리거가 revision을 강제 증가시켜 어떤 write 경로도 이를
우회하지 못한다(F-2: provider-owned ``data_version``은 provider load에서 0이라
validator로 부적합, #727 policy revision(0056)은 갱신정책 CAS라 별개 자원이다 —
합치지 않는다).

online-safety(D-12): ``ADD COLUMN ... DEFAULT 1``은 PG11+에서 rewrite 없는
메타데이터 변경이라 대형 ``feature.features``에서도 즉시 적용된다(기존 행은 카탈로그
default로 1을 읽어 별도 backfill UPDATE가 필요 없다). CHECK는 ``NOT VALID`` 후
같은 migration transaction에서 ``VALIDATE``한다. 실패 시 revision 전체가 rollback되어
부분 적용 상태를 남기지 않는다.

Revision ID: 0062_feature_row_revision
Revises: 0061_gist_brin_index_audit
Create Date: 2026-07-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0062_feature_row_revision"
down_revision: str | Sequence[str] | None = "0061_gist_brin_index_audit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1) server-owned monotonic column. DEFAULT 1은 PG11+에서 메타데이터 전용이라
    #    대형 테이블 rewrite/backfill 없이 즉시 적용된다.
    op.add_column(
        "features",
        sa.Column(
            "row_revision",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        schema="feature",
    )
    # require_review 요청은 제출 시 확인한 feature revision을 승인 시점까지 보존한다.
    # add와 0062 이전 legacy 요청은 NULL이며, legacy update/delete 승인은 fail-closed한다.
    op.add_column(
        "feature_change_requests",
        sa.Column("base_row_revision", sa.BigInteger(), nullable=True),
        schema="ops",
    )
    # 2) CHECK는 NOT VALID로 먼저 붙인 뒤 같은 transaction에서 VALIDATE한다.
    op.execute(
        """
        ALTER TABLE feature.features
        ADD CONSTRAINT ck_features_row_revision
        CHECK (row_revision >= 1)
        NOT VALID
        """
    )
    # 3) 모든 UPDATE에서 revision을 강제 증가시키는 트리거. 애플리케이션이 값을
    #    무엇으로 보내든 서버가 OLD+1로 덮어써 우회 불가·server-owned를 보장한다.
    #    (기존 trg_features_coord_precision은 coord 컬럼 한정 BEFORE 트리거라 서로
    #    독립적으로 실행된다.)
    op.execute(
        """
        CREATE FUNCTION feature.force_features_row_revision()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            NEW.row_revision := OLD.row_revision + 1;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_features_row_revision "
        "BEFORE UPDATE ON feature.features "
        "FOR EACH ROW EXECUTE FUNCTION feature.force_features_row_revision()"
    )
    # 4) 0059의 SELECT * view는 생성 시 컬럼 목록이 고정되므로 새 revision을 공개
    #    projection 끝에 명시적으로 추가한다.
    op.execute(
        """
        CREATE OR REPLACE VIEW feature.public_features AS
        SELECT *
        FROM feature.features
        WHERE status = 'active'
          AND deleted_at IS NULL
        """
    )
    # autocommit_block을 쓰지 않는다. VALIDATE 실패 시 위 DDL까지 함께 rollback돼
    # Alembic revision과 실제 schema가 어긋나는 재시도 불능 상태를 막는다.
    op.execute(
        "ALTER TABLE feature.features VALIDATE CONSTRAINT ck_features_row_revision"
    )


def downgrade() -> None:
    # row_revision을 참조하는 view를 먼저 제거하고 column 제거 뒤 0059 shape로 복원한다.
    op.execute("DROP VIEW IF EXISTS feature.public_features")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_features_row_revision ON feature.features"
    )
    op.execute("DROP FUNCTION IF EXISTS feature.force_features_row_revision()")
    op.execute(
        "ALTER TABLE feature.features "
        "DROP CONSTRAINT IF EXISTS ck_features_row_revision"
    )
    op.drop_column("feature_change_requests", "base_row_revision", schema="ops")
    op.drop_column("features", "row_revision", schema="feature")
    op.execute(
        """
        CREATE VIEW feature.public_features AS
        SELECT *
        FROM feature.features
        WHERE status = 'active'
          AND deleted_at IS NULL
        """
    )
