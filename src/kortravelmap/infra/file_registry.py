"""``ops.managed_files`` repository — 시스템 저장 파일 registry (PR-D).

파일 실체(filesystem/S3)는 그대로 두고 메타데이터·이력만 관리한다. 행 최신성은
생산/소비 코드 hook + 주기 reconciliation scan 이중화. hook은 본작업을 절대
실패시키지 않는다 — 호출부에서 :func:`registry_guard` 로 감싼다.

ADR 참조
--------
- ADR-004 — ORM 매핑만, 쿼리는 raw SQL ``text()``
- docs/architecture/file-registry.md — location·scanner 소유권, orphan rule
"""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Final

from sqlalchemy import text

from kortravelmap.core.managed_file_states import (
    MANAGED_FILE_EVENT_KIND_VALUES,
    MANAGED_FILE_KIND_VALUES,
    MANAGED_FILE_ORPHAN_REASON_VALUES,
    MANAGED_FILE_STATUS_VALUES,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "ManagedFile",
    "ManagedFileEvent",
    "ManagedFilePage",
    "ManagedFileSummary",
    "get_managed_file",
    "list_managed_file_events",
    "list_managed_files",
    "mark_deleted",
    "mark_missing",
    "mark_orphan",
    "record_event",
    "register_file",
    "registry_guard",
    "summarize_managed_files",
    "sweep_missing",
    "touch_loaded",
]

logger = logging.getLogger(__name__)

_COLUMNS: Final[str] = (
    "mf.file_id, mf.storage_backend, mf.location, mf.path, mf.is_directory, mf.kind, "
    "mf.provider_dataset_id, COALESCE(pd.provider, mf.provider_name) AS provider, "
    "pd.dataset_key, "
    "mf.status, mf.orphan_reason, mf.registered_by, mf.byte_size, "
    "mf.checksum_sha256, mf.upload_id, mf.origin_import_job_id, "
    "mf.origin_dagster_run_id, mf.downloaded_at, mf.last_loaded_at, "
    "mf.last_seen_at, mf.deleted_at, mf.meta, mf.created_at, mf.updated_at"
)

_SORT_COLUMNS: Final[dict[str, str]] = {
    "downloaded_at": "downloaded_at",
    "last_loaded_at": "last_loaded_at",
    "last_seen_at": "last_seen_at",
    "byte_size": "byte_size",
    "updated_at": "updated_at",
}


@dataclass(frozen=True, slots=True)
class ManagedFile:
    """``ops.managed_files`` 1행."""

    file_id: int
    storage_backend: str
    location: str
    path: str
    is_directory: bool
    kind: str
    provider_dataset_id: int | None
    provider: str | None
    dataset_key: str | None
    status: str
    orphan_reason: str | None
    registered_by: str
    byte_size: int | None
    checksum_sha256: str | None
    upload_id: str | None
    origin_import_job_id: str | None
    origin_dagster_run_id: str | None
    downloaded_at: datetime | None
    last_loaded_at: datetime | None
    last_seen_at: datetime | None
    deleted_at: datetime | None
    meta: dict[str, Any]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ManagedFileEvent:
    """``ops.managed_file_events`` 1행."""

    event_id: int
    file_id: int
    event_kind: str
    occurred_at: datetime
    import_job_id: str | None
    dagster_run_id: str | None
    actor: str | None
    detail: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ManagedFilePage:
    """목록 페이지 + 총 건수(offset 페이지네이션, offline-uploads 규약)."""

    items: list[ManagedFile]
    total_count: int


@dataclass(frozen=True, slots=True)
class ManagedFileSummary:
    """요약 카드 데이터."""

    by_kind: list[dict[str, Any]] = field(default_factory=list)
    by_status: list[dict[str, Any]] = field(default_factory=list)
    by_location: list[dict[str, Any]] = field(default_factory=list)


def _row_to_file(row: Any) -> ManagedFile:
    return ManagedFile(
        file_id=row.file_id,
        storage_backend=row.storage_backend,
        location=row.location,
        path=row.path,
        is_directory=row.is_directory,
        kind=row.kind,
        provider_dataset_id=(
            int(row.provider_dataset_id) if row.provider_dataset_id is not None else None
        ),
        provider=row.provider,
        dataset_key=row.dataset_key,
        status=row.status,
        orphan_reason=row.orphan_reason,
        registered_by=row.registered_by,
        byte_size=row.byte_size,
        checksum_sha256=row.checksum_sha256,
        upload_id=str(row.upload_id) if row.upload_id is not None else None,
        origin_import_job_id=(
            str(row.origin_import_job_id)
            if row.origin_import_job_id is not None
            else None
        ),
        origin_dagster_run_id=row.origin_dagster_run_id,
        downloaded_at=row.downloaded_at,
        last_loaded_at=row.last_loaded_at,
        last_seen_at=row.last_seen_at,
        deleted_at=row.deleted_at,
        meta=dict(row.meta or {}),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _row_to_event(row: Any) -> ManagedFileEvent:
    return ManagedFileEvent(
        event_id=row.event_id,
        file_id=row.file_id,
        event_kind=row.event_kind,
        occurred_at=row.occurred_at,
        import_job_id=(
            str(row.import_job_id) if row.import_job_id is not None else None
        ),
        dagster_run_id=row.dagster_run_id,
        actor=row.actor,
        detail=dict(row.detail or {}),
    )


@asynccontextmanager
async def registry_guard(operation: str) -> AsyncIterator[None]:
    """registry hook 무해화 래퍼 — 본작업(백업/업로드/sync)을 절대 죽이지 않는다."""

    try:
        yield
    except Exception:  # noqa: BLE001 — hook 실패는 관측만 하고 삼킨다(설계 §0.3).
        logger.warning("managed-file registry hook 실패(무시): %s", operation, exc_info=True)


# -- 등록/이벤트 ---------------------------------------------------------


_UPSERT_SQL: Final[str] = f"""
WITH prior AS (
    SELECT file_id, status
    FROM ops.managed_files
    WHERE storage_backend = :storage_backend
      AND location = :location
      AND path = :path
), upserted AS (
    INSERT INTO ops.managed_files (
        storage_backend, location, path, is_directory, kind, provider_dataset_id,
        provider_name, status, registered_by, byte_size, checksum_sha256,
        upload_id, origin_import_job_id, origin_dagster_run_id,
        downloaded_at, last_loaded_at, last_seen_at, meta
    ) VALUES (
        :storage_backend, :location, :path, :is_directory, :kind, :provider_dataset_id,
        :provider_name, 'active', :registered_by, :byte_size, :checksum_sha256,
        CAST(:upload_id AS uuid), CAST(:origin_import_job_id AS uuid),
        :origin_dagster_run_id, :downloaded_at, NULL, now(), CAST(:meta AS jsonb)
    )
    ON CONFLICT (storage_backend, location, path) DO UPDATE SET
        is_directory = EXCLUDED.is_directory,
        kind = EXCLUDED.kind,
        provider_dataset_id = CASE
            WHEN EXCLUDED.provider_dataset_id IS NOT NULL
              OR EXCLUDED.provider_name IS NOT NULL
            THEN EXCLUDED.provider_dataset_id
            ELSE ops.managed_files.provider_dataset_id
        END,
        provider_name = CASE
            WHEN EXCLUDED.provider_dataset_id IS NOT NULL
              OR EXCLUDED.provider_name IS NOT NULL
            THEN EXCLUDED.provider_name
            ELSE ops.managed_files.provider_name
        END,
        -- 재등록 = 물리 실체 확인 → deleted/missing/orphan 모두 active 부활.
        status = 'active',
        orphan_reason = NULL,
        deleted_at = NULL,
        byte_size = COALESCE(EXCLUDED.byte_size, ops.managed_files.byte_size),
        checksum_sha256 = COALESCE(
            EXCLUDED.checksum_sha256, ops.managed_files.checksum_sha256
        ),
        upload_id = COALESCE(EXCLUDED.upload_id, ops.managed_files.upload_id),
        origin_import_job_id = COALESCE(
            EXCLUDED.origin_import_job_id, ops.managed_files.origin_import_job_id
        ),
        origin_dagster_run_id = COALESCE(
            EXCLUDED.origin_dagster_run_id, ops.managed_files.origin_dagster_run_id
        ),
        downloaded_at = COALESCE(
            EXCLUDED.downloaded_at, ops.managed_files.downloaded_at
        ),
        last_seen_at = now(),
        meta = ops.managed_files.meta || EXCLUDED.meta,
        updated_at = now()
    RETURNING *
)
SELECT {_COLUMNS}, prior.status AS prior_status
FROM upserted AS mf
LEFT JOIN provider_sync.provider_datasets AS pd
  ON pd.provider_dataset_id = mf.provider_dataset_id
LEFT JOIN prior ON prior.file_id = mf.file_id
"""


async def register_file(
    session: AsyncSession,
    *,
    storage_backend: str,
    location: str,
    path: str,
    kind: str,
    registered_by: str = "hook",
    is_directory: bool = False,
    provider_dataset_id: int | None = None,
    provider_name: str | None = None,
    byte_size: int | None = None,
    checksum_sha256: str | None = None,
    upload_id: str | None = None,
    origin_import_job_id: str | None = None,
    origin_dagster_run_id: str | None = None,
    downloaded_at: datetime | None = None,
    meta: dict[str, Any] | None = None,
    event_kind: str | None = "registered",
    actor: str | None = None,
    event_detail: dict[str, Any] | None = None,
) -> ManagedFile:
    """파일을 upsert 등록한다.

    - 신규 행: ``registered`` 이벤트(또는 ``event_kind`` 인자, 예: ``downloaded``).
    - 기존 행: last_seen_at/메타 갱신. 이전 status가 deleted/missing/orphan이면
      active 부활 + ``reappeared`` 이벤트를 추가로 남긴다.
    """

    if kind not in MANAGED_FILE_KIND_VALUES:
        raise ValueError(f"unknown managed file kind: {kind!r}")
    row = (
        await session.execute(
            text(_UPSERT_SQL),
            {
                "storage_backend": storage_backend,
                "location": location,
                "path": path,
                "is_directory": is_directory,
                "kind": kind,
                "provider_dataset_id": provider_dataset_id,
                "provider_name": provider_name,
                "registered_by": registered_by,
                "byte_size": byte_size,
                "checksum_sha256": checksum_sha256,
                "upload_id": upload_id,
                "origin_import_job_id": origin_import_job_id,
                "origin_dagster_run_id": origin_dagster_run_id,
                "downloaded_at": downloaded_at,
                "meta": json.dumps(meta or {}),
            },
        )
    ).one()
    managed = _row_to_file(row)
    prior_status: str | None = row.prior_status

    if prior_status is None:
        if event_kind is not None:
            await record_event(
                session,
                file_id=managed.file_id,
                event_kind=event_kind,
                actor=actor,
                dagster_run_id=origin_dagster_run_id,
                import_job_id=origin_import_job_id,
                detail=event_detail or {},
            )
    else:
        if prior_status in ("deleted", "missing", "orphan"):
            await record_event(
                session,
                file_id=managed.file_id,
                event_kind="reappeared",
                actor=actor,
                detail={"prior_status": prior_status},
            )
        if event_kind is not None and event_kind != "registered":
            # 재등록이라도 downloaded 같은 실질 이벤트는 남긴다(예: 백업 재생성).
            await record_event(
                session,
                file_id=managed.file_id,
                event_kind=event_kind,
                actor=actor,
                dagster_run_id=origin_dagster_run_id,
                import_job_id=origin_import_job_id,
                detail=event_detail or {},
            )
    return managed


async def record_event(
    session: AsyncSession,
    *,
    file_id: int,
    event_kind: str,
    actor: str | None = None,
    import_job_id: str | None = None,
    dagster_run_id: str | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    """이벤트 append. ``dagster_run_id``가 있으면 run당 1개로 dedupe."""

    if event_kind not in MANAGED_FILE_EVENT_KIND_VALUES:
        raise ValueError(f"unknown managed file event kind: {event_kind!r}")
    await session.execute(
        text(
            """
            INSERT INTO ops.managed_file_events (
                file_id, event_kind, import_job_id, dagster_run_id, actor, detail
            ) VALUES (
                :file_id, :event_kind, CAST(:import_job_id AS uuid),
                :dagster_run_id, :actor, CAST(:detail AS jsonb)
            )
            ON CONFLICT (file_id, event_kind, dagster_run_id)
                WHERE dagster_run_id IS NOT NULL
                DO NOTHING
            """
        ),
        {
            "file_id": file_id,
            "event_kind": event_kind,
            "import_job_id": import_job_id,
            "dagster_run_id": dagster_run_id,
            "actor": actor,
            "detail": json.dumps(detail or {}),
        },
    )


async def touch_loaded(
    session: AsyncSession,
    *,
    storage_backend: str,
    location: str,
    path: str,
    event_kind: str = "loaded",
    actor: str | None = None,
    import_job_id: str | None = None,
    dagster_run_id: str | None = None,
    detail: dict[str, Any] | None = None,
) -> bool:
    """소비(적재/검증/복원) 기록 — ``last_loaded_at`` 갱신 + dedupe 이벤트.

    등록되지 않은 파일이면 False (hook 순서 역전 시 조용히 무시 — scan이 회수).
    """

    row = (
        await session.execute(
            text(
                """
                UPDATE ops.managed_files
                SET last_loaded_at = now(), last_seen_at = now(), updated_at = now()
                WHERE storage_backend = :storage_backend
                  AND location = :location
                  AND path = :path
                RETURNING file_id
                """
            ),
            {
                "storage_backend": storage_backend,
                "location": location,
                "path": path,
            },
        )
    ).first()
    if row is None:
        return False
    await record_event(
        session,
        file_id=row.file_id,
        event_kind=event_kind,
        actor=actor,
        import_job_id=import_job_id,
        dagster_run_id=dagster_run_id,
        detail=detail or {},
    )
    return True


# -- 상태 전이 ------------------------------------------------------------


async def _transition(
    session: AsyncSession,
    *,
    file_id: int,
    new_status: str,
    event_kind: str,
    orphan_reason: str | None = None,
    actor: str | None = None,
    detail: dict[str, Any] | None = None,
    set_deleted_at: bool = False,
) -> bool:
    """멱등 상태 전이 — 이미 동일 상태면 no-op(False)."""

    if new_status not in MANAGED_FILE_STATUS_VALUES:
        raise ValueError(f"unknown managed file status: {new_status!r}")
    row = (
        await session.execute(
            text(
                """
                UPDATE ops.managed_files
                SET status = :new_status,
                    orphan_reason = :orphan_reason,
                    deleted_at = CASE
                        WHEN :set_deleted_at THEN now() ELSE deleted_at END,
                    updated_at = now()
                WHERE file_id = :file_id AND status <> :new_status
                RETURNING file_id
                """
            ),
            {
                "file_id": file_id,
                "new_status": new_status,
                "orphan_reason": orphan_reason,
                "set_deleted_at": set_deleted_at,
            },
        )
    ).first()
    if row is None:
        return False
    await record_event(
        session,
        file_id=file_id,
        event_kind=event_kind,
        actor=actor,
        detail=detail or {},
    )
    return True


async def mark_deleted(
    session: AsyncSession,
    *,
    file_id: int,
    actor: str | None = None,
    detail: dict[str, Any] | None = None,
    purged: bool = False,
) -> bool:
    """삭제 확인 기록(파일 실체가 지워졌음을 registry에 반영)."""

    return await _transition(
        session,
        file_id=file_id,
        new_status="deleted",
        event_kind="purged" if purged else "deleted",
        actor=actor,
        detail=detail,
        set_deleted_at=True,
    )


async def mark_missing(
    session: AsyncSession,
    *,
    file_id: int,
    actor: str | None = None,
    detail: dict[str, Any] | None = None,
) -> bool:
    """등록된 파일이 물리적으로 사라짐(스캔 sweep 판정)."""

    return await _transition(
        session,
        file_id=file_id,
        new_status="missing",
        event_kind="marked_missing",
        actor=actor,
        detail=detail,
    )


async def mark_orphan(
    session: AsyncSession,
    *,
    file_id: int,
    reason: str,
    actor: str | None = None,
    detail: dict[str, Any] | None = None,
) -> bool:
    """파일은 있으나 소유 레코드/근거가 없음(orphan rule 판정)."""

    if reason not in MANAGED_FILE_ORPHAN_REASON_VALUES:
        raise ValueError(f"unknown orphan reason: {reason!r}")
    return await _transition(
        session,
        file_id=file_id,
        new_status="orphan",
        event_kind="marked_orphan",
        orphan_reason=reason,
        actor=actor,
        detail={**(detail or {}), "reason": reason},
    )


async def sweep_missing(
    session: AsyncSession,
    *,
    location: str,
    scan_started_at: datetime,
    actor: str,
) -> int:
    """스캔이 **실제 열거를 마친 location에 한해** 미발견 행을 missing 처리.

    location 밖 sweep 금지가 핵심 정합성 규칙 — 스캐너가 못 훑은 location의
    행을 missing으로 만드는 사고를 방지한다(호출부가 열거 성공 후에만 호출).
    """

    rows = (
        await session.execute(
            text(
                """
                UPDATE ops.managed_files
                SET status = 'missing', updated_at = now()
                WHERE location = :location
                  AND status IN ('active', 'orphan')
                  AND (last_seen_at IS NULL OR last_seen_at < :scan_started_at)
                RETURNING file_id
                """
            ),
            {"location": location, "scan_started_at": scan_started_at},
        )
    ).all()
    for row in rows:
        await record_event(
            session,
            file_id=row.file_id,
            event_kind="marked_missing",
            actor=actor,
            detail={"sweep_location": location},
        )
    return len(rows)


# -- 조회 -----------------------------------------------------------------


async def list_managed_files(
    session: AsyncSession,
    *,
    kinds: Sequence[str] | None = None,
    statuses: Sequence[str] | None = None,
    provider_dataset_id: int | None = None,
    location: str | None = None,
    registered_by: str | None = None,
    q: str | None = None,
    min_age_days: int | None = None,
    max_age_days: int | None = None,
    sort: str = "downloaded_at",
    limit: int = 50,
    offset: int = 0,
) -> ManagedFilePage:
    """필터 목록 + 총 건수(offset 페이지네이션)."""

    sort_column = _SORT_COLUMNS.get(sort, "downloaded_at")
    rows = (
        await session.execute(
            text(
                f"""
                SELECT {_COLUMNS}, count(*) OVER () AS total_count
                FROM ops.managed_files AS mf
                LEFT JOIN provider_sync.provider_datasets AS pd
                  ON pd.provider_dataset_id = mf.provider_dataset_id
                WHERE (CAST(:kinds AS text[]) IS NULL OR mf.kind = ANY(CAST(:kinds AS text[])))
                  AND (CAST(:statuses AS text[]) IS NULL
                       OR mf.status = ANY(CAST(:statuses AS text[])))
                  AND (CAST(:provider_dataset_id AS bigint) IS NULL
                       OR mf.provider_dataset_id = CAST(:provider_dataset_id AS bigint))
                  AND (CAST(:location AS text) IS NULL OR mf.location = CAST(:location AS text))
                  AND (CAST(:registered_by AS text) IS NULL
                       OR mf.registered_by = CAST(:registered_by AS text))
                  AND (
                       CAST(:q AS text) IS NULL
                       OR mf.path ILIKE '%' || CAST(:q AS text) || '%'
                       OR COALESCE(pd.provider, mf.provider_name)
                          ILIKE '%' || CAST(:q AS text) || '%'
                       OR pd.dataset_key ILIKE '%' || CAST(:q AS text) || '%'
                  )
                  AND (CAST(:min_age_days AS int) IS NULL OR mf.downloaded_at
                       <= now() - make_interval(days => CAST(:min_age_days AS int)))
                  AND (CAST(:max_age_days AS int) IS NULL OR mf.downloaded_at
                       >= now() - make_interval(days => CAST(:max_age_days AS int)))
                ORDER BY mf.{sort_column} DESC NULLS LAST, mf.file_id DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            {
                "kinds": list(kinds) if kinds else None,
                "statuses": list(statuses) if statuses else None,
                "provider_dataset_id": provider_dataset_id,
                "location": location,
                "registered_by": registered_by,
                "q": q,
                "min_age_days": min_age_days,
                "max_age_days": max_age_days,
                "limit": limit,
                "offset": offset,
            },
        )
    ).all()
    total = rows[0].total_count if rows else 0
    return ManagedFilePage(items=[_row_to_file(row) for row in rows], total_count=total)


async def get_managed_file(
    session: AsyncSession, file_id: int
) -> ManagedFile | None:
    row = (
        await session.execute(
            text(
                f"""SELECT {_COLUMNS}
                FROM ops.managed_files AS mf
                LEFT JOIN provider_sync.provider_datasets AS pd
                  ON pd.provider_dataset_id = mf.provider_dataset_id
                WHERE mf.file_id = :file_id"""
            ),
            {"file_id": file_id},
        )
    ).first()
    return _row_to_file(row) if row is not None else None


async def get_managed_file_by_path(
    session: AsyncSession,
    *,
    storage_backend: str,
    location: str,
    path: str,
) -> ManagedFile | None:
    row = (
        await session.execute(
            text(
                f"""
                SELECT {_COLUMNS}
                FROM ops.managed_files AS mf
                LEFT JOIN provider_sync.provider_datasets AS pd
                  ON pd.provider_dataset_id = mf.provider_dataset_id
                WHERE mf.storage_backend = :storage_backend
                  AND mf.location = :location AND mf.path = :path
                """
            ),
            {
                "storage_backend": storage_backend,
                "location": location,
                "path": path,
            },
        )
    ).first()
    return _row_to_file(row) if row is not None else None


async def list_managed_file_events(
    session: AsyncSession,
    *,
    file_id: int,
    limit: int = 50,
    offset: int = 0,
) -> list[ManagedFileEvent]:
    rows = (
        await session.execute(
            text(
                """
                SELECT event_id, file_id, event_kind, occurred_at, import_job_id,
                       dagster_run_id, actor, detail
                FROM ops.managed_file_events
                WHERE file_id = :file_id
                ORDER BY occurred_at DESC, event_id DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            {"file_id": file_id, "limit": limit, "offset": offset},
        )
    ).all()
    return [_row_to_event(row) for row in rows]


async def summarize_managed_files(session: AsyncSession) -> ManagedFileSummary:
    """요약 카드 집계 — kind/status/location 3개 GROUP BY."""

    by_kind = (
        await session.execute(
            text(
                """
                SELECT kind, count(*) AS count,
                       COALESCE(sum(byte_size), 0) AS byte_size
                FROM ops.managed_files
                WHERE status <> 'deleted'
                GROUP BY kind ORDER BY byte_size DESC
                """
            )
        )
    ).all()
    by_status = (
        await session.execute(
            text(
                """
                SELECT status, count(*) AS count
                FROM ops.managed_files
                GROUP BY status ORDER BY count DESC
                """
            )
        )
    ).all()
    by_location = (
        await session.execute(
            text(
                """
                SELECT location, count(*) AS count, max(last_seen_at) AS last_seen_at
                FROM ops.managed_files
                GROUP BY location ORDER BY location
                """
            )
        )
    ).all()
    return ManagedFileSummary(
        by_kind=[
            {"kind": r.kind, "count": r.count, "byte_size": int(r.byte_size)}
            for r in by_kind
        ],
        by_status=[{"status": r.status, "count": r.count} for r in by_status],
        by_location=[
            {
                "location": r.location,
                "count": r.count,
                "last_seen_at": r.last_seen_at,
            }
            for r in by_location
        ],
    )
