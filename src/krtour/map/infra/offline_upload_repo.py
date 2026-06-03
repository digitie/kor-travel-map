"""``ops.offline_uploads`` repository.

Admin/API가 RustFS에 보존한 오프라인 원본 파일의 메타데이터와 validation/load
``ops.import_jobs`` 연결을 관리한다. 실제 바이너리는 DB에 넣지 않고
``storage_backend`` + ``storage_key``로만 참조한다(D-14).

ADR 참조
--------
- ADR-004 — ORM 매핑만, 쿼리는 raw SQL ``text()``
- ADR-011 — load 실행 상태는 ``ops.import_jobs``와 연결
- ADR-045 D-14 — offline upload 파일은 RustFS ``krtour-uploads``에 무기한 보존
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Final

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "OfflineUpload",
    "OfflineUploadPage",
    "create_offline_upload",
    "finish_offline_upload_load",
    "get_offline_upload",
    "list_offline_uploads",
    "mark_offline_upload_loading",
]

_RETURN_COLUMNS: Final[str] = (
    "upload_id, provider, dataset_key, sync_scope, original_filename, "
    "storage_backend, storage_key, byte_size, checksum_sha256, detected_format, "
    "detected_encoding, state, validation_job_id, load_job_id, created_by, "
    "created_at, updated_at"
)

_LOAD_FINISH_STATES: Final[frozenset[str]] = frozenset(
    {"loaded", "load_failed", "cancelled"}
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
    state: str
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
            "state": self.state,
            "validation_job_id": self.validation_job_id,
            "load_job_id": self.load_job_id,
        }


@dataclass(frozen=True)
class OfflineUploadPage:
    """Keyset cursor 기반 ``ops.offline_uploads`` 목록."""

    items: tuple[OfflineUpload, ...]
    next_cursor: str | None


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
        state=str(data["state"]),
        validation_job_id=(
            str(data["validation_job_id"])
            if data["validation_job_id"] is not None
            else None
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

_LIST_SQL: Final[str] = f"""
SELECT {_RETURN_COLUMNS}
FROM ops.offline_uploads
WHERE (CAST(:state AS text) IS NULL OR state = CAST(:state AS text))
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

_MARK_LOADING_SQL: Final[str] = f"""
UPDATE ops.offline_uploads
SET state = 'loading',
    load_job_id = :load_job_id,
    updated_at = now()
WHERE upload_id = :upload_id
RETURNING {_RETURN_COLUMNS}
"""

_FINISH_LOAD_SQL: Final[str] = f"""
UPDATE ops.offline_uploads
SET state = :state,
    updated_at = now()
WHERE upload_id = :upload_id
RETURNING {_RETURN_COLUMNS}
"""


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


async def get_offline_upload(
    session: AsyncSession,
    upload_id: str,
) -> OfflineUpload | None:
    """``upload_id``로 오프라인 업로드 메타데이터를 조회한다."""
    result = await session.execute(text(_GET_SQL), {"upload_id": upload_id})
    row = result.one_or_none()
    return _row_to_upload(row) if row is not None else None


async def list_offline_uploads(
    session: AsyncSession,
    *,
    state: str | None = None,
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
                "state": state,
                "provider": provider,
                "dataset_key": dataset_key,
                "cursor_created_at": cursor_created_at,
                "cursor_upload_id": cursor_upload_id,
                "limit_plus_one": effective_limit + 1,
            },
        )
    ).all()
    uploads = tuple(_row_to_upload(row) for row in rows[:effective_limit])
    next_cursor = (
        _encode_cursor(uploads[-1])
        if len(rows) > effective_limit and uploads
        else None
    )
    return OfflineUploadPage(items=uploads, next_cursor=next_cursor)


async def mark_offline_upload_loading(
    session: AsyncSession,
    *,
    upload_id: str,
    load_job_id: str,
) -> OfflineUpload | None:
    """load import job과 연결하고 ``state='loading'``으로 전이한다."""
    result = await session.execute(
        text(_MARK_LOADING_SQL),
        {"upload_id": upload_id, "load_job_id": load_job_id},
    )
    row = result.one_or_none()
    return _row_to_upload(row) if row is not None else None


async def finish_offline_upload_load(
    session: AsyncSession,
    *,
    upload_id: str,
    state: str,
) -> OfflineUpload | None:
    """load 종료 상태를 기록한다. ``loaded``/``load_failed``/``cancelled``만 허용."""
    if state not in _LOAD_FINISH_STATES:
        raise ValueError(
            f"offline upload load state는 {sorted(_LOAD_FINISH_STATES)} 중 하나여야 함, "
            f"got {state!r}."
        )
    result = await session.execute(
        text(_FINISH_LOAD_SQL),
        {"upload_id": upload_id, "state": state},
    )
    row = result.one_or_none()
    return _row_to_upload(row) if row is not None else None
