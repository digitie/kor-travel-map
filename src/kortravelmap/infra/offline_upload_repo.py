"""``ops.offline_uploads`` repository.

Admin/API가 RustFS에 보존한 오프라인 원본 파일의 메타데이터와 validation/load
``ops.import_jobs`` 연결을 관리한다. 실제 바이너리는 DB에 넣지 않고
``storage_backend`` + ``storage_key``로만 참조한다(D-14).

ADR 참조
--------
- ADR-004 — ORM 매핑만, 쿼리는 raw SQL ``text()``
- ADR-011 — load 실행 상태는 ``ops.import_jobs``와 연결
- ADR-045 D-14 — offline upload 파일은 RustFS ``kor-travel-map-uploads``에 무기한 보존
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Final

from sqlalchemy import text

from kortravelmap.core.offline_upload_states import (
    OFFLINE_UPLOAD_DELETABLE_STATES,
    OFFLINE_UPLOAD_LOAD_FINISH_SOURCE_STATES,
    OFFLINE_UPLOAD_LOAD_FINISH_STATES,
    OFFLINE_UPLOAD_LOADABLE_STATES,
    OFFLINE_UPLOAD_VALIDATABLE_STATES,
    OFFLINE_UPLOAD_VALIDATION_FINISH_SOURCE_STATES,
    OFFLINE_UPLOAD_VALIDATION_FINISH_STATES,
)
from kortravelmap.infra.jobs_repo import start_import_job

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "OfflineUpload",
    "OfflineUploadPage",
    "OfflineUploadStatusConflict",
    "attach_offline_upload_load_job",
    "create_offline_upload",
    "delete_offline_upload",
    "finish_offline_upload_load",
    "finish_offline_upload_validation",
    "get_offline_upload",
    "get_offline_upload_by_checksum",
    "list_offline_uploads",
    "mark_offline_upload_loading",
    "mark_offline_upload_validating",
    "reserve_offline_upload_load",
]

_RETURN_COLUMNS: Final[str] = (
    "upload_id, provider, dataset_key, sync_scope, original_filename, "
    "storage_backend, storage_key, byte_size, checksum_sha256, detected_format, "
    "detected_encoding, status, validation_job_id, load_job_id, created_by, "
    "created_at, updated_at"
)

_MAX_LIST_LIMIT: Final[int] = 200


@dataclass(frozen=True)
class OfflineUpload:
    """``ops.offline_uploads`` 행 표현."""

    upload_id: str
    provider: str
    dataset_key: str
    sync_scope: str
    original_filename: str
    storage_backend: str
    storage_key: str
    byte_size: int
    checksum_sha256: str
    detected_format: str | None
    detected_encoding: str | None
    status: str
    validation_job_id: str | None
    load_job_id: str | None
    created_by: str | None
    created_at: datetime
    updated_at: datetime

    def as_metadata(self) -> dict[str, object]:
        """Dagster/OpenAPI metadata로 쓰기 쉬운 축약 표현."""
        return {
            "upload_id": self.upload_id,
            "provider": self.provider,
            "dataset_key": self.dataset_key,
            "sync_scope": self.sync_scope,
            "original_filename": self.original_filename,
            "storage_backend": self.storage_backend,
            "storage_key": self.storage_key,
            "byte_size": self.byte_size,
            "checksum_sha256": self.checksum_sha256,
            "detected_format": self.detected_format,
            "detected_encoding": self.detected_encoding,
            "status": self.status,
            "validation_job_id": self.validation_job_id,
            "load_job_id": self.load_job_id,
        }


@dataclass(frozen=True)
class OfflineUploadPage:
    """Keyset cursor 기반 ``ops.offline_uploads`` 목록."""

    items: tuple[OfflineUpload, ...]
    next_cursor: str | None


class OfflineUploadStatusConflict(ValueError):
    """offline upload가 요청한 상태 전이를 허용하지 않을 때 발생."""

    def __init__(
        self,
        *,
        upload_id: str,
        current_status: str,
        target_status: str,
        allowed_statuses: frozenset[str],
    ) -> None:
        self.upload_id = upload_id
        self.current_status = current_status
        self.target_status = target_status
        self.allowed_statuses = allowed_statuses
        super().__init__(
            f"offline upload {upload_id!r}는 {target_status!r} 전이를 허용하지 않음: "
            f"status={current_status!r}, allowed={sorted(allowed_statuses)}"
        )


def _row_to_upload(row: Any) -> OfflineUpload:
    data = row._mapping
    return OfflineUpload(
        upload_id=str(data["upload_id"]),
        provider=str(data["provider"]),
        dataset_key=str(data["dataset_key"]),
        sync_scope=str(data["sync_scope"]),
        original_filename=str(data["original_filename"]),
        storage_backend=str(data["storage_backend"]),
        storage_key=str(data["storage_key"]),
        byte_size=int(data["byte_size"]),
        checksum_sha256=str(data["checksum_sha256"]),
        detected_format=data["detected_format"],
        detected_encoding=data["detected_encoding"],
        status=str(data["status"]),
        validation_job_id=(
            str(data["validation_job_id"]) if data["validation_job_id"] is not None else None
        ),
        load_job_id=str(data["load_job_id"]) if data["load_job_id"] is not None else None,
        created_by=data["created_by"],
        created_at=data["created_at"],
        updated_at=data["updated_at"],
    )


def _encode_cursor(item: OfflineUpload) -> str:
    payload = {
        "created_at": item.created_at.isoformat(),
        "upload_id": item.upload_id,
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str | None) -> tuple[datetime | None, str | None]:
    if cursor is None:
        return None, None
    padded = cursor + ("=" * (-len(cursor) % 4))
    try:
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        created_at = datetime.fromisoformat(str(payload["created_at"]))
        upload_id = str(payload["upload_id"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("invalid offline upload cursor") from exc
    return created_at, upload_id


_INSERT_SQL: Final[str] = f"""
INSERT INTO ops.offline_uploads (
    upload_id, provider, dataset_key, sync_scope, original_filename,
    storage_backend, storage_key, byte_size, checksum_sha256,
    detected_format, detected_encoding, created_by
) VALUES (
    COALESCE(CAST(:upload_id AS uuid), x_extension.gen_random_uuid()),
    :provider, :dataset_key, :sync_scope, :original_filename,
    :storage_backend, :storage_key, :byte_size, :checksum_sha256,
    :detected_format, :detected_encoding, :created_by
)
RETURNING {_RETURN_COLUMNS}
"""

_GET_SQL: Final[str] = f"""
SELECT {_RETURN_COLUMNS}
FROM ops.offline_uploads
WHERE upload_id = :upload_id
"""

_GET_STATE_SQL: Final[str] = """
SELECT upload_id, status
FROM ops.offline_uploads
WHERE upload_id = :upload_id
FOR UPDATE
"""

_GET_BY_CHECKSUM_SQL: Final[str] = f"""
SELECT {_RETURN_COLUMNS}
FROM ops.offline_uploads
WHERE provider = :provider
  AND dataset_key = :dataset_key
  AND sync_scope = :sync_scope
  AND checksum_sha256 = :checksum_sha256
ORDER BY created_at DESC, upload_id DESC
LIMIT 1
"""

_LIST_SQL: Final[str] = f"""
SELECT {_RETURN_COLUMNS}
FROM ops.offline_uploads
WHERE (CAST(:status AS text) IS NULL OR status = CAST(:status AS text))
  AND (CAST(:provider AS text) IS NULL OR provider = CAST(:provider AS text))
  AND (CAST(:dataset_key AS text) IS NULL OR dataset_key = CAST(:dataset_key AS text))
  AND (
    CAST(:cursor_created_at AS timestamptz) IS NULL
    OR (created_at, upload_id) < (
        CAST(:cursor_created_at AS timestamptz),
        CAST(:cursor_upload_id AS uuid)
    )
  )
ORDER BY created_at DESC, upload_id DESC
LIMIT :limit_plus_one
"""

_DELETE_SQL: Final[str] = f"""
DELETE FROM ops.offline_uploads
WHERE upload_id = :upload_id
  AND status = ANY(CAST(:allowed_statuses AS text[]))
RETURNING {_RETURN_COLUMNS}
"""

_MARK_LOADING_SQL: Final[str] = f"""
UPDATE ops.offline_uploads
SET status = 'loading',
    load_job_id = :load_job_id,
    updated_at = now()
WHERE upload_id = :upload_id
  AND status = ANY(CAST(:allowed_statuses AS text[]))
RETURNING {_RETURN_COLUMNS}
"""

_ATTACH_LOAD_JOB_SQL: Final[str] = f"""
UPDATE ops.offline_uploads
SET load_job_id = :load_job_id,
    updated_at = now()
WHERE upload_id = :upload_id
  AND status = 'loading'
  AND load_job_id IS NULL
RETURNING {_RETURN_COLUMNS}
"""

_MARK_VALIDATING_SQL: Final[str] = f"""
UPDATE ops.offline_uploads
SET status = 'validating',
    validation_job_id = :validation_job_id,
    updated_at = now()
WHERE upload_id = :upload_id
  AND status = ANY(CAST(:allowed_statuses AS text[]))
RETURNING {_RETURN_COLUMNS}
"""

_FINISH_VALIDATION_SQL: Final[str] = f"""
UPDATE ops.offline_uploads
SET status = :status,
    updated_at = now()
WHERE upload_id = :upload_id
  AND status = ANY(CAST(:allowed_statuses AS text[]))
RETURNING {_RETURN_COLUMNS}
"""

_FINISH_LOAD_SQL: Final[str] = f"""
UPDATE ops.offline_uploads
SET status = :status,
    updated_at = now()
WHERE upload_id = :upload_id
  AND status = ANY(CAST(:allowed_statuses AS text[]))
RETURNING {_RETURN_COLUMNS}
"""


async def _missing_or_status_conflict(
    session: AsyncSession,
    *,
    upload_id: str,
    target_status: str,
    allowed_statuses: frozenset[str],
) -> None:
    row = (
        (
            await session.execute(
                text(_GET_STATE_SQL),
                {"upload_id": upload_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        return
    raise OfflineUploadStatusConflict(
        upload_id=str(row["upload_id"]),
        current_status=str(row["status"]),
        target_status=target_status,
        allowed_statuses=allowed_statuses,
    )


async def create_offline_upload(
    session: AsyncSession,
    *,
    upload_id: str | None = None,
    provider: str,
    dataset_key: str,
    original_filename: str,
    storage_backend: str,
    storage_key: str,
    byte_size: int,
    checksum_sha256: str,
    sync_scope: str = "default",
    detected_format: str | None = None,
    detected_encoding: str | None = None,
    created_by: str | None = None,
) -> OfflineUpload:
    """업로드 메타데이터를 생성한다. commit은 호출자 책임."""
    result = await session.execute(
        text(_INSERT_SQL),
        {
            "upload_id": upload_id,
            "provider": provider,
            "dataset_key": dataset_key,
            "sync_scope": sync_scope,
            "original_filename": original_filename,
            "storage_backend": storage_backend,
            "storage_key": storage_key,
            "byte_size": byte_size,
            "checksum_sha256": checksum_sha256,
            "detected_format": detected_format,
            "detected_encoding": detected_encoding,
            "created_by": created_by,
        },
    )
    return _row_to_upload(result.one())


async def delete_offline_upload(
    session: AsyncSession,
    *,
    upload_id: str,
) -> OfflineUpload | None:
    """업로드 메타데이터 row를 삭제한다. commit은 호출자 책임.

    validation/load가 진행 중(``validating``/``loading``)이면
    :class:`OfflineUploadStatusConflict`를 던지고, row가 없으면 ``None``을
    반환한다. 연관 ``ops.import_jobs`` row는 audit 기록으로 보존한다
    (FK는 upload→job 방향 ``ON DELETE SET NULL`` — row 삭제로 job은 안 지워짐).
    """
    result = await session.execute(
        text(_DELETE_SQL),
        {
            "upload_id": upload_id,
            "allowed_statuses": list(OFFLINE_UPLOAD_DELETABLE_STATES),
        },
    )
    row = result.one_or_none()
    if row is not None:
        return _row_to_upload(row)
    await _missing_or_status_conflict(
        session,
        upload_id=upload_id,
        target_status="deleted",
        allowed_statuses=OFFLINE_UPLOAD_DELETABLE_STATES,
    )
    return None


async def get_offline_upload(
    session: AsyncSession,
    upload_id: str,
) -> OfflineUpload | None:
    """``upload_id``로 오프라인 업로드 메타데이터를 조회한다."""
    result = await session.execute(text(_GET_SQL), {"upload_id": upload_id})
    row = result.one_or_none()
    return _row_to_upload(row) if row is not None else None


async def get_offline_upload_by_checksum(
    session: AsyncSession,
    *,
    provider: str,
    dataset_key: str,
    sync_scope: str,
    checksum_sha256: str,
) -> OfflineUpload | None:
    """provider/dataset/scope/checksum 조합으로 기존 업로드를 조회한다."""
    result = await session.execute(
        text(_GET_BY_CHECKSUM_SQL),
        {
            "provider": provider,
            "dataset_key": dataset_key,
            "sync_scope": sync_scope,
            "checksum_sha256": checksum_sha256,
        },
    )
    row = result.one_or_none()
    return _row_to_upload(row) if row is not None else None


async def list_offline_uploads(
    session: AsyncSession,
    *,
    status: str | None = None,
    provider: str | None = None,
    dataset_key: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> OfflineUploadPage:
    """``created_at DESC, upload_id DESC`` keyset cursor로 업로드 목록을 조회한다."""
    if limit <= 0:
        raise ValueError("limit must be greater than 0")
    effective_limit = min(limit, _MAX_LIST_LIMIT)
    cursor_created_at, cursor_upload_id = _decode_cursor(cursor)
    rows = (
        await session.execute(
            text(_LIST_SQL),
            {
                "status": status,
                "provider": provider,
                "dataset_key": dataset_key,
                "cursor_created_at": cursor_created_at,
                "cursor_upload_id": cursor_upload_id,
                "limit_plus_one": effective_limit + 1,
            },
        )
    ).all()
    uploads = tuple(_row_to_upload(row) for row in rows[:effective_limit])
    next_cursor = _encode_cursor(uploads[-1]) if len(rows) > effective_limit and uploads else None
    return OfflineUploadPage(items=uploads, next_cursor=next_cursor)


async def mark_offline_upload_loading(
    session: AsyncSession,
    *,
    upload_id: str,
    load_job_id: str,
) -> OfflineUpload | None:
    """load import job과 연결하고 ``status='loading'``으로 전이한다."""
    result = await session.execute(
        text(_MARK_LOADING_SQL),
        {
            "upload_id": upload_id,
            "load_job_id": load_job_id,
            "allowed_statuses": list(OFFLINE_UPLOAD_LOADABLE_STATES),
        },
    )
    row = result.one_or_none()
    if row is not None:
        return _row_to_upload(row)
    await _missing_or_status_conflict(
        session,
        upload_id=upload_id,
        target_status="loading",
        allowed_statuses=OFFLINE_UPLOAD_LOADABLE_STATES,
    )
    return None


async def reserve_offline_upload_load(
    session: AsyncSession,
    *,
    upload_id: str,
    job_kind: str = "offline_upload_load",
) -> OfflineUpload | None:
    """Dagster launch 전에 load job과 upload row를 같은 트랜잭션에서 선점한다."""
    upload = await get_offline_upload(session, upload_id)
    if upload is None:
        return None

    job = await start_import_job(
        session,
        kind=job_kind,
        payload={
            "upload_id": upload.upload_id,
            "provider": upload.provider,
            "dataset_key": upload.dataset_key,
            "sync_scope": upload.sync_scope,
            "storage_backend": upload.storage_backend,
            "storage_key": upload.storage_key,
            "dagster_run_id": None,
        },
        source_checksum=upload.checksum_sha256,
    )
    return await mark_offline_upload_loading(
        session,
        upload_id=upload.upload_id,
        load_job_id=job.job_id,
    )


async def attach_offline_upload_load_job(
    session: AsyncSession,
    *,
    upload_id: str,
    load_job_id: str,
) -> OfflineUpload | None:
    """이미 ``loading``으로 선점된 upload row에 load job id를 연결한다."""
    result = await session.execute(
        text(_ATTACH_LOAD_JOB_SQL),
        {
            "upload_id": upload_id,
            "load_job_id": load_job_id,
        },
    )
    row = result.one_or_none()
    if row is not None:
        return _row_to_upload(row)
    await _missing_or_status_conflict(
        session,
        upload_id=upload_id,
        target_status="loading",
        allowed_statuses=frozenset({"loading"}),
    )
    return None


async def mark_offline_upload_validating(
    session: AsyncSession,
    *,
    upload_id: str,
    validation_job_id: str,
) -> OfflineUpload | None:
    """validation import job과 연결하고 ``status='validating'``으로 전이한다."""
    result = await session.execute(
        text(_MARK_VALIDATING_SQL),
        {
            "upload_id": upload_id,
            "validation_job_id": validation_job_id,
            "allowed_statuses": list(OFFLINE_UPLOAD_VALIDATABLE_STATES),
        },
    )
    row = result.one_or_none()
    if row is not None:
        return _row_to_upload(row)
    await _missing_or_status_conflict(
        session,
        upload_id=upload_id,
        target_status="validating",
        allowed_statuses=OFFLINE_UPLOAD_VALIDATABLE_STATES,
    )
    return None


async def finish_offline_upload_validation(
    session: AsyncSession,
    *,
    upload_id: str,
    status: str,
) -> OfflineUpload | None:
    """validation 종료 상태를 기록한다. ``validated``/``validation_failed``만 허용."""
    if status not in OFFLINE_UPLOAD_VALIDATION_FINISH_STATES:
        raise ValueError(
            "offline upload validation status는 ['validated', 'validation_failed'] "
            f"중 하나여야 함, got {status!r}."
        )
    result = await session.execute(
        text(_FINISH_VALIDATION_SQL),
        {
            "upload_id": upload_id,
            "status": status,
            "allowed_statuses": list(OFFLINE_UPLOAD_VALIDATION_FINISH_SOURCE_STATES),
        },
    )
    row = result.one_or_none()
    if row is not None:
        return _row_to_upload(row)
    await _missing_or_status_conflict(
        session,
        upload_id=upload_id,
        target_status=status,
        allowed_statuses=OFFLINE_UPLOAD_VALIDATION_FINISH_SOURCE_STATES,
    )
    return None


async def finish_offline_upload_load(
    session: AsyncSession,
    *,
    upload_id: str,
    status: str,
) -> OfflineUpload | None:
    """load 종료 상태를 기록한다. ``loaded``/``load_failed``/``cancelled``만 허용."""
    if status not in OFFLINE_UPLOAD_LOAD_FINISH_STATES:
        raise ValueError(
            "offline upload load status는 "
            f"{sorted(OFFLINE_UPLOAD_LOAD_FINISH_STATES)} 중 하나여야 함, got {status!r}."
        )
    result = await session.execute(
        text(_FINISH_LOAD_SQL),
        {
            "upload_id": upload_id,
            "status": status,
            "allowed_statuses": list(OFFLINE_UPLOAD_LOAD_FINISH_SOURCE_STATES),
        },
    )
    row = result.one_or_none()
    if row is not None:
        return _row_to_upload(row)
    await _missing_or_status_conflict(
        session,
        upload_id=upload_id,
        target_status=status,
        allowed_statuses=OFFLINE_UPLOAD_LOAD_FINISH_SOURCE_STATES,
    )
    return None
