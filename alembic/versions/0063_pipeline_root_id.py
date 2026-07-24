"""pipeline root 멤버십을 import_jobs에 stamp하고 2단계 lineage를 lock한다.

ADR-077: root/component 멤버십을 read-time 재귀 lineage로 파생하지 않고, write
시점에 ``root_id``/``root_kind``로 저장한다. 세 job 계열 모두 CHECK 제약으로 강제된
≤2단계 트리라, root는 insert 시점에 이미 안다(자식은 부모의 root 승계, root는 자기
자신). DB 트리거가 parent에서 파생하므로 writer는 값을 줄 필요가 없고, 값을 줘도
트리거가 덮어써 절대 틀릴 수 없다. batch 자식은 insert 후 ``attach``가 parent를
back-stamp하므로 ``UPDATE OF parent_job_id``에서도 재파생한다.

Revision ID: 0063_pipeline_root_id
Revises: 0062_feature_row_revision
Create Date: 2026-07-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0063_pipeline_root_id"
down_revision: str | Sequence[str] | None = "0062_feature_row_revision"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_STAMP_FUNCTION = """
CREATE FUNCTION ops.stamp_import_job_root()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
  parent_root_id uuid;
  parent_root_kind text;
  parent_is_root boolean;
BEGIN
  IF NEW.parent_job_id IS NULL THEN
    NEW.root_id := NEW.job_id;
    NEW.root_kind := CASE
      WHEN NEW.kind = 'feature_update_request' THEN 'update_request'
      ELSE 'import_job'
    END;
  ELSE
    SELECT p.root_id, p.root_kind, (p.parent_job_id IS NULL)
      INTO parent_root_id, parent_root_kind, parent_is_root
      FROM ops.import_jobs AS p
      WHERE p.job_id = NEW.parent_job_id;
    IF parent_root_id IS NULL THEN
      RAISE EXCEPTION 'import job % references missing parent %',
        NEW.job_id, NEW.parent_job_id
        USING ERRCODE = 'foreign_key_violation';
    END IF;
    IF NOT parent_is_root THEN
      RAISE EXCEPTION
        'import job lineage must be at most 2 levels: parent % of % is not a root',
        NEW.parent_job_id, NEW.job_id
        USING ERRCODE = 'check_violation';
    END IF;
    NEW.root_id := parent_root_id;
    NEW.root_kind := parent_root_kind;
  END IF;
  RETURN NEW;
END;
$$
"""

# 0053의 identity immutability guard에 root_id/root_kind를 추가한 버전.
_IDENTITY_GUARD_WITH_ROOT = """
CREATE OR REPLACE FUNCTION ops.reject_import_job_identity_change()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  IF NEW.kind IS DISTINCT FROM OLD.kind
     OR NEW.provider IS DISTINCT FROM OLD.provider
     OR NEW.dataset_key IS DISTINCT FROM OLD.dataset_key
     OR NEW.sync_scope IS DISTINCT FROM OLD.sync_scope
     OR NEW.root_id IS DISTINCT FROM OLD.root_id
     OR NEW.root_kind IS DISTINCT FROM OLD.root_kind
     OR (
       OLD.kind = 'feature_update_request'
       AND NEW.payload IS DISTINCT FROM OLD.payload
     ) THEN
    RAISE EXCEPTION
      'import job kind/provider/dataset/scope/root/payload identity is immutable for job %',
      OLD.job_id
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END;
$$
"""

# 0053 원본 guard(root 없음) — downgrade 복원용.
_IDENTITY_GUARD_WITHOUT_ROOT = """
CREATE OR REPLACE FUNCTION ops.reject_import_job_identity_change()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  IF NEW.kind IS DISTINCT FROM OLD.kind
     OR NEW.provider IS DISTINCT FROM OLD.provider
     OR NEW.dataset_key IS DISTINCT FROM OLD.dataset_key
     OR NEW.sync_scope IS DISTINCT FROM OLD.sync_scope
     OR (
       OLD.kind = 'feature_update_request'
       AND NEW.payload IS DISTINCT FROM OLD.payload
     ) THEN
    RAISE EXCEPTION
      'import job kind/provider/dataset/scope/payload identity is immutable for job %',
      OLD.job_id
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END;
$$
"""


def upgrade() -> None:
    # 1. 컬럼 추가(backfill 위해 우선 nullable).
    op.add_column(
        "import_jobs",
        sa.Column("root_id", postgresql.UUID(as_uuid=False), nullable=True),
        schema="ops",
    )
    op.add_column(
        "import_jobs",
        sa.Column("root_kind", sa.Text(), nullable=True),
        schema="ops",
    )

    # 2. backfill: ≤2단계라 자식의 parent가 곧 root. root_id = COALESCE(parent, self).
    op.execute(
        """
        UPDATE ops.import_jobs AS j
           SET root_id = COALESCE(j.parent_job_id, j.job_id)
        """
    )
    # 3. backfill root_kind: root job의 kind로 결정.
    op.execute(
        """
        UPDATE ops.import_jobs AS j
           SET root_kind = CASE
             WHEN root.kind = 'feature_update_request' THEN 'update_request'
             ELSE 'import_job'
           END
          FROM ops.import_jobs AS root
         WHERE root.job_id = j.root_id
        """
    )

    # 4. NOT NULL + CHECK + index.
    op.alter_column("import_jobs", "root_id", nullable=False, schema="ops")
    op.alter_column("import_jobs", "root_kind", nullable=False, schema="ops")
    op.create_check_constraint(
        "ck_import_jobs_root_kind",
        "import_jobs",
        "root_kind IN ('import_job','update_request')",
        schema="ops",
    )
    # root_id 선두 — scoped source의 ``WHERE root_id IN (...)`` member 조회가
    # 인덱스 스캔을 타게 한다(bounded access). root_kind는 보조.
    op.create_index(
        "idx_import_jobs_root", "import_jobs", ["root_id", "root_kind"], schema="ops"
    )

    # 5. write 시점 자동 stamp + 2단계 lock 트리거(insert + batch attach의 parent 변경).
    op.execute(_STAMP_FUNCTION)
    op.execute(
        """
        CREATE TRIGGER trg_import_jobs_stamp_root
        BEFORE INSERT OR UPDATE OF parent_job_id ON ops.import_jobs
        FOR EACH ROW EXECUTE FUNCTION ops.stamp_import_job_root()
        """
    )

    # 6. identity immutability guard에 root_id/root_kind 편입(직접 변경 금지).
    #    stamp 트리거의 attach 재파생은 SET 절에 root_id가 없어 이 guard를 안 건드린다.
    op.execute("DROP TRIGGER trg_import_jobs_identity_immutable ON ops.import_jobs")
    op.execute(_IDENTITY_GUARD_WITH_ROOT)
    op.execute(
        """
        CREATE TRIGGER trg_import_jobs_identity_immutable
        BEFORE UPDATE OF kind, provider, dataset_key, sync_scope, root_id, root_kind, payload
        ON ops.import_jobs
        FOR EACH ROW EXECUTE FUNCTION ops.reject_import_job_identity_change()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER trg_import_jobs_identity_immutable ON ops.import_jobs")
    op.execute(_IDENTITY_GUARD_WITHOUT_ROOT)
    op.execute(
        """
        CREATE TRIGGER trg_import_jobs_identity_immutable
        BEFORE UPDATE OF kind, provider, dataset_key, sync_scope, payload
        ON ops.import_jobs
        FOR EACH ROW EXECUTE FUNCTION ops.reject_import_job_identity_change()
        """
    )
    op.execute("DROP TRIGGER trg_import_jobs_stamp_root ON ops.import_jobs")
    op.execute("DROP FUNCTION ops.stamp_import_job_root()")
    op.drop_index("idx_import_jobs_root", table_name="import_jobs", schema="ops")
    op.drop_constraint("ck_import_jobs_root_kind", "import_jobs", schema="ops")
    op.drop_column("import_jobs", "root_kind", schema="ops")
    op.drop_column("import_jobs", "root_id", schema="ops")
