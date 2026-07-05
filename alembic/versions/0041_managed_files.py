"""Managed file registry — 시스템 저장 파일 추적 (ops.managed_files/_events).

파일 관리 페이지(PR-D)의 저장소. 파일 실체는 filesystem/S3에 그대로 두고
Postgres는 메타데이터·이력만 가진다. 행 최신성은 (a) 생산/소비 코드의
instrumentation hook + (b) 주기 reconciliation scan 이중화로 유지한다.

설계 노트(§ = docs/architecture/file-registry.md):
- ``location``(논리 루트 키) + ``path``(루트 상대) — 물리 경로를 직접 넣지
  않는다: 같은 코드가 배포마다 다른 물리 경로/버킷명을 쓰므로(logical:
  ``backup_root``/``mois_source``/``object_store``/``offline_uploads``)
  경로 변경이 전체 행을 고아로 만들지 않게 한다. 물리 스냅샷은 ``meta``.
- ``status``는 lifecycle(active/orphan/missing/deleted)만 담당 — "임시"는
  분류이므로 ``kind='temp'``가 담당한다. ``missing``(등록됐는데 파일이
  사라짐)은 ``orphan``(파일은 있는데 주인이 없음)과 정반대라 분리.
- ``upload_id``는 의도적으로 FK 없음: offline-uploads DELETE가 row를
  hard-delete하므로 FK면 provenance가 지워지거나 기존 API가 깨진다.
  soft ref + scan이 owner 부재를 ``orphan(owner_row_deleted)``로 표시.
- events는 상태 전이 시에만 기록(append-only). scan "봤음" no-op은 부모
  ``last_seen_at``으로만 반영해 bloat를 막는다. run당 loaded 이벤트는
  partial unique로 dedupe(MOIS fetch가 run 내 42회 반복 호출되는 경로).
- ``fillfactor=90`` + ``last_seen_at`` 비인덱스 — scan마다 도는 UPDATE의
  HOT 유지. 데이터 backfill은 migration이 아니라 배포 후 첫 scan이 수행
  (api-entrypoint의 기동 시 upgrade에 파일시스템 walk를 결합하지 않는다).

Revision ID: 0041_managed_files
Revises: 0039_expand_curated_theme_sets
Create Date: 2026-07-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0041_managed_files"
down_revision: str | Sequence[str] | None = "0040_notice_dedup_cleanup"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KINDS = (
    "provider_download",
    "backup",
    "upload",
    "feature_file",
    "report",
    "temp",
    "other",
)
_STATUSES = ("active", "orphan", "missing", "deleted")
_ORPHAN_REASONS = (
    "zombie_object",
    "owner_row_deleted",
    "manifest_missing",
    "e2e_backup_expired",
    "scan_unregistered",
    "temp_expired",
)
_REGISTERED_BY = ("hook", "scan", "backfill")
_EVENT_KINDS = (
    "registered",
    "downloaded",
    "validated",
    "loaded",
    "restored",
    "marked_orphan",
    "marked_missing",
    "reappeared",
    "deleted",
    "delete_failed",
    "purged",
)


def _literals(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    op.create_table(
        "managed_files",
        sa.Column(
            "file_id",
            sa.BigInteger(),
            sa.Identity(always=True),
            primary_key=True,
        ),
        sa.Column("storage_backend", sa.Text(), nullable=False),
        sa.Column("location", sa.Text(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column(
            "is_directory",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=True),
        sa.Column("dataset_key", sa.Text(), nullable=True),
        sa.Column(
            "status", sa.Text(), nullable=False, server_default=sa.text("'active'")
        ),
        sa.Column("orphan_reason", sa.Text(), nullable=True),
        sa.Column("registered_by", sa.Text(), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=True),
        sa.Column("checksum_sha256", sa.Text(), nullable=True),
        sa.Column("upload_id", postgresql.UUID(as_uuid=False), nullable=True),
        sa.Column(
            "origin_import_job_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("ops.import_jobs.job_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("origin_dagster_run_id", sa.Text(), nullable=True),
        sa.Column("downloaded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_loaded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "meta",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "storage_backend IN ('filesystem', 's3')",
            name="ck_managed_files_storage_backend",
        ),
        sa.CheckConstraint(
            f"kind IN ({_literals(_KINDS)})",
            name="ck_managed_files_kind",
        ),
        sa.CheckConstraint(
            f"status IN ({_literals(_STATUSES)})",
            name="ck_managed_files_status",
        ),
        sa.CheckConstraint(
            f"orphan_reason IS NULL OR orphan_reason IN ({_literals(_ORPHAN_REASONS)})",
            name="ck_managed_files_orphan_reason",
        ),
        sa.CheckConstraint(
            f"registered_by IN ({_literals(_REGISTERED_BY)})",
            name="ck_managed_files_registered_by",
        ),
        sa.CheckConstraint("byte_size >= 0", name="ck_managed_files_byte_size"),
        sa.CheckConstraint(
            "checksum_sha256 IS NULL OR checksum_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_managed_files_checksum_sha256",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(meta) = 'object'",
            name="ck_managed_files_meta_object",
        ),
        sa.UniqueConstraint(
            "storage_backend",
            "location",
            "path",
            name="uq_managed_files_backend_location_path",
        ),
        schema="ops",
        postgresql_with={"fillfactor": "90"},
    )
    op.create_index(
        "idx_managed_files_status_kind",
        "managed_files",
        ["status", "kind", sa.text("updated_at DESC")],
        schema="ops",
    )
    op.create_index(
        "idx_managed_files_kind_downloaded",
        "managed_files",
        ["kind", sa.text("downloaded_at DESC")],
        schema="ops",
    )
    op.create_index(
        "idx_managed_files_provider",
        "managed_files",
        ["provider"],
        schema="ops",
        postgresql_where=sa.text("provider IS NOT NULL"),
    )
    op.create_index(
        "idx_managed_files_origin_job",
        "managed_files",
        ["origin_import_job_id"],
        schema="ops",
        postgresql_where=sa.text("origin_import_job_id IS NOT NULL"),
    )
    op.create_index(
        "idx_managed_files_upload",
        "managed_files",
        ["upload_id"],
        schema="ops",
        postgresql_where=sa.text("upload_id IS NOT NULL"),
    )

    op.create_table(
        "managed_file_events",
        sa.Column(
            "event_id",
            sa.BigInteger(),
            sa.Identity(always=True),
            primary_key=True,
        ),
        sa.Column(
            "file_id",
            sa.BigInteger(),
            sa.ForeignKey("ops.managed_files.file_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_kind", sa.Text(), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "import_job_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("ops.import_jobs.job_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("dagster_run_id", sa.Text(), nullable=True),
        sa.Column("actor", sa.Text(), nullable=True),
        sa.Column(
            "detail",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.CheckConstraint(
            f"event_kind IN ({_literals(_EVENT_KINDS)})",
            name="ck_managed_file_events_event_kind",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(detail) = 'object'",
            name="ck_managed_file_events_detail_object",
        ),
        schema="ops",
    )
    op.create_index(
        "idx_managed_file_events_file",
        "managed_file_events",
        ["file_id", sa.text("occurred_at DESC")],
        schema="ops",
    )
    op.create_index(
        "idx_managed_file_events_job",
        "managed_file_events",
        ["import_job_id"],
        schema="ops",
        postgresql_where=sa.text("import_job_id IS NOT NULL"),
    )
    # run당 loaded 이벤트 1개 dedupe (INSERT ... ON CONFLICT DO NOTHING 대상).
    op.create_index(
        "uq_managed_file_events_run_dedupe",
        "managed_file_events",
        ["file_id", "event_kind", "dagster_run_id"],
        unique=True,
        schema="ops",
        postgresql_where=sa.text("dagster_run_id IS NOT NULL"),
    )


def downgrade() -> None:
    # registry는 파생 메타데이터 — 파일 실체는 불변이므로 DROP이 안전하다.
    op.drop_table("managed_file_events", schema="ops")
    op.drop_table("managed_files", schema="ops")
