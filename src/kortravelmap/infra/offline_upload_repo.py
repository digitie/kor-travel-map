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
from sqlalchemy.exc import IntegrityError

from kortravelmap.core.offline_upload_states import (
    OFFLINE_UPLOAD_DELETABLE_STATES,
    OFFLINE_UPLOAD_LOAD_FINISH_SOURCE_STATES,
    OFFLINE_UPLOAD_LOAD_FINISH_STATES,
    OFFLINE_UPLOAD_LOADABLE_STATES,
    OFFLINE_UPLOAD_VALIDATABLE_STATES,
    OFFLINE_UPLOAD_VALIDATION_FINISH_SOURCE_STATES,
    OFFLINE_UPLOAD_VALIDATION_FINISH_STATES,
)
from kortravelmap.infra.feature_update_active_repo import _driver_constraint_identity
from kortravelmap.infra.jobs_repo import (
    ImportJobDatasetTarget,
    start_provider_dataset_import_job,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "INACTIVE_DATASET_MEMBERSHIP_CONSTRAINTS",
    "OfflineUploadScopeOperationUnresolved",
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
    "is_inactive_dataset_membership_violation",
    "list_offline_uploads",
    "mark_offline_upload_loading",
    "mark_offline_upload_validating",
    "finalize_offline_upload_reservation",
    "reserve_offline_upload",
    "reserve_offline_upload_delete",
    "reserve_offline_upload_load",
    "resolve_offline_upload_operation_key",
]

# 0091이 만든 활성 가드가 비활성 dataset/disabled operation 앞에서 쓰는 두
# constraint 이름. offline upload 한 요청이 두 이름을 모두 볼 수 있다:
# ``ops.offline_uploads`` 자신의 가드는 ``ck_provider_dataset_scope_active_write``를,
# 같은 요청이 만드는 ``ops.import_job_datasets`` membership 행의 가드
# (``reject_inactive_import_job_dataset_membership``)는
# ``ck_provider_dataset_active_write``를 쓴다. 후자가 먼저 터지므로 둘 다 봐야 한다.
INACTIVE_DATASET_MEMBERSHIP_CONSTRAINTS: Final[frozenset[str]] = frozenset(
    {
        "ck_provider_dataset_active_write",
        "ck_provider_dataset_scope_active_write",
    }
)


def is_inactive_dataset_membership_violation(exc: BaseException) -> bool:
    """비활성 membership 가드의 ``23514``만 driver metadata로 판정한다.

    문자열 매칭이 아니라 SQLSTATE + constraint 이름으로 좁힌다 — 같은 예외 타입에
    실려 오는 다른 CHECK 위반(예: ``ck_offline_uploads_status``)을 상태 오류로
    오분류하면 진짜 버그가 4xx로 숨는다.
    """

    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, IntegrityError):
            sqlstate, constraint_name = _driver_constraint_identity(current)
            if (
                sqlstate == "23514"
                and constraint_name in INACTIVE_DATASET_MEMBERSHIP_CONSTRAINTS
            ):
                return True
        current = current.__cause__ or current.__context__
    return False

_RETURN_COLUMNS: Final[str] = (
    "upload_id, provider_dataset_id, sync_scope, operation_key, original_filename, "
    "storage_backend, storage_key, byte_size, checksum_sha256, detected_format, "
    "detected_encoding, status, validation_job_id, load_job_id, created_by, "
    "delete_command_id, created_at, updated_at"
)

_MAX_LIST_LIMIT: Final[int] = 200


@dataclass(frozen=True)
class OfflineUpload:
    """``ops.offline_uploads`` 행 표현."""

    upload_id: str
    provider_dataset_id: int
    sync_scope: str
    operation_key: str
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
    delete_command_id: int | None = None

    def as_metadata(self) -> dict[str, object]:
        """Dagster/OpenAPI metadata로 쓰기 쉬운 축약 표현."""
        return {
            "upload_id": self.upload_id,
            "provider_dataset_id": self.provider_dataset_id,
            "sync_scope": self.sync_scope,
            "operation_key": self.operation_key,
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
            "delete_command_id": self.delete_command_id,
        }


@dataclass(frozen=True)
class OfflineUploadPage:
    """Keyset cursor 기반 ``ops.offline_uploads`` 목록."""

    items: tuple[OfflineUpload, ...]
    next_cursor: str | None


class OfflineUploadScopeOperationUnresolved(ValueError):
    """scope가 정확히 하나의 operation으로 해석되지 않는다.

    도달하는 경우는 두 가지다: 활성 후보가 **0개**(scope 행이 없거나, 있어도
    operation이 disabled·dataset이 inactive라 후보에서 빠짐)이거나 **2개 이상**이다.
    어느 쪽이 얼마나 흔한지는 카탈로그 상태에 달렸고 배포된 DB마다 다르다 — 그래서
    이 파일에는 그 분포를 수치로 박지 않는다.

    호출자가 운영자에게 무엇을 고쳐야 하는지 말할 수 있도록 개수를 들고 간다 —
    이 값이 없으면 라우터가 "알 수 없는 오류"밖에 못 낸다.
    """

    def __init__(self, message: str, *, resolved: int) -> None:
        super().__init__(message)
        self.resolved = resolved


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
        provider_dataset_id=int(data["provider_dataset_id"]),
        sync_scope=str(data["sync_scope"]),
        operation_key=str(data["operation_key"]),
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
        delete_command_id=(
            int(data["delete_command_id"])
            if data["delete_command_id"] is not None
            else None
        ),
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
    upload_id, provider_dataset_id, sync_scope, operation_key, original_filename,
    storage_backend, storage_key, byte_size, checksum_sha256,
    detected_format, detected_encoding, created_by
) VALUES (
    COALESCE(CAST(:upload_id AS uuid), x_extension.gen_random_uuid()),
    :provider_dataset_id, :sync_scope, :operation_key, :original_filename,
    :storage_backend, :storage_key, :byte_size, :checksum_sha256,
    :detected_format, :detected_encoding, :created_by
)
RETURNING {_RETURN_COLUMNS}
"""

_RESERVE_SQL: Final[str] = f"""
INSERT INTO ops.offline_uploads (
    upload_id, provider_dataset_id, sync_scope, operation_key, original_filename,
    storage_backend, storage_key, byte_size, checksum_sha256,
    detected_format, detected_encoding, status, created_by
) VALUES (
    CAST(:upload_id AS uuid), :provider_dataset_id, :sync_scope, :operation_key,
    :original_filename, :storage_backend, :storage_key, :byte_size,
    :checksum_sha256, :detected_format, :detected_encoding, 'uploading',
    :created_by
)
ON CONFLICT (provider_dataset_id, sync_scope, operation_key, checksum_sha256) DO NOTHING
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

# 멱등 키는 identity triple + checksum 4열이다 —
# ``uq_offline_uploads_dataset_scope_checksum``(alembic 0092). 이 read는 "여러 후보 중
# 최신 하나"가 아니라 **그 unique 제약이 가리키는 정확히 그 행**을 읽는다. 그래서
# ``operation_key``까지 술어에 든다: 빼면 형제 operation에 결박된 행까지 걸려
# ``one_or_none()``이 터지거나(중복) 409가 엉뚱한 upload를 가리킨다.
# ``ORDER BY ... LIMIT 1``을 두면 제약이 바뀌거나 사라져도 임의의 행을 조용히 골라
# 같은 오작동을 숨긴다. 정렬을 빼고 ``one_or_none()``으로 받아 드러나게 한다.
_GET_BY_CHECKSUM_SQL: Final[str] = f"""
SELECT {_RETURN_COLUMNS}
FROM ops.offline_uploads
WHERE provider_dataset_id = :provider_dataset_id
  AND sync_scope = :sync_scope
  AND operation_key = :operation_key
  AND checksum_sha256 = :checksum_sha256
"""

_LIST_SQL: Final[str] = f"""
SELECT {_RETURN_COLUMNS}
FROM ops.offline_uploads
WHERE (CAST(:status AS text) IS NULL OR status = CAST(:status AS text))
  AND (
      CAST(:provider_dataset_id AS bigint) IS NULL
      OR provider_dataset_id = CAST(:provider_dataset_id AS bigint)
  )
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
  AND status = 'deleting'
  AND delete_command_id = :command_id
RETURNING {_RETURN_COLUMNS}
"""

_RESERVE_DELETE_SQL: Final[str] = f"""
UPDATE ops.offline_uploads
SET status = 'deleting',
    delete_command_id = :command_id,
    updated_at = now()
WHERE upload_id = :upload_id
  AND status = ANY(CAST(:allowed_statuses AS text[]))
  AND delete_command_id IS NULL
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

_FINALIZE_RESERVATION_SQL: Final[str] = f"""
UPDATE ops.offline_uploads
SET status = 'uploaded',
    updated_at = now()
WHERE upload_id = :upload_id
  AND status = 'uploading'
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
    provider_dataset_id: int,
    original_filename: str,
    storage_backend: str,
    storage_key: str,
    byte_size: int,
    checksum_sha256: str,
    sync_scope: str = "dataset_wide",
    detected_format: str | None = None,
    detected_encoding: str | None = None,
    created_by: str | None = None,
) -> OfflineUpload:
    """업로드 메타데이터를 생성한다. commit은 호출자 책임."""
    operation_key = await resolve_offline_upload_operation_key(
        session, provider_dataset_id=provider_dataset_id, sync_scope=sync_scope
    )
    result = await session.execute(
        text(_INSERT_SQL),
        {
            "upload_id": upload_id,
            "provider_dataset_id": provider_dataset_id,
            "sync_scope": sync_scope,
            "operation_key": operation_key,
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


_RESOLVE_SCOPE_OPERATION_SQL: Final[str] = """
SELECT scope.operation_key
FROM provider_sync.provider_dataset_operation_scopes AS scope
JOIN provider_sync.provider_dataset_operations AS operation
  ON operation.provider_dataset_id = scope.provider_dataset_id
 AND operation.operation_key = scope.operation_key
 AND operation.operation_kind = scope.operation_kind
JOIN provider_sync.provider_datasets AS dataset
  ON dataset.provider_dataset_id = scope.provider_dataset_id
WHERE scope.provider_dataset_id = :provider_dataset_id
  AND scope.sync_scope = :sync_scope
  AND operation.is_enabled
  AND dataset.is_active
ORDER BY scope.operation_key
"""


async def resolve_offline_upload_operation_key(
    session: AsyncSession,
    *,
    provider_dataset_id: int,
    sync_scope: str,
) -> str:
    """upload가 가리키는 scope의 operation을 유도한다.

    업로드 요청 표면에는 operation이 없다 — 운영자는 dataset과 scope로 파일을
    올린다. 그런데 ``ops.offline_uploads``는 scope PK와 같은 triple을 참조하므로
    (ADR-088) 쓰기 시점에 operation이 정해져야 한다.

    "scope에 operation이 정확히 하나일 때만 그것을 쓴다"는 모호성 규칙은 alembic
    0089의 ``_preflight_offline_upload_operation_is_unambiguous``와 같다. 둘 이상이면
    어느 것을 골라도 임의 선택이므로 조용히 고르지 않고 실패시킨다 — 잘못 고르면
    upload가 엉뚱한 실행에 결박된다.

    다만 **후보 집합은 그 preflight보다 좁다.** 여기서는 ``is_enabled``/``is_active``
    까지 보고 활성인 것만 센다. 0089 preflight의 SQL은 ``offline_uploads``와
    ``provider_dataset_operation_scopes``만 조인하고 ``provider_dataset_operations``·
    ``provider_datasets``는 아예 조인하지 않아 활성 여부를 보지 않는다. 두 판정이
    갈리는 입력은 두 가지다: (1) scope의 유일한 operation이 ``is_enabled=false`` —
    preflight는 count=1로 통과하지만 여기서는 ``resolved=0``으로 거부한다,
    (2) operation이 둘인데 하나가 disabled — preflight는 "모호"로 보지만 여기서는
    유일한 활성 operation을 고른다.

    활성까지 보는 이유: 안 보면 (a) 유일한 operation이 disabled일 때 typed 오류 대신
    DB 트리거가 23514로 터져 500이 되고, (b) disabled 형제가 후보 수를 부풀려 멀쩡한
    scope를 "둘 이상"으로 오판한다. 활성 술어 자체는 DB 가드
    (``reject_inactive_offline_upload_membership``)의 ``NOT EXISTS`` 술어와 같은
    조건이다 — 두 판정이 갈리면 하나가 반드시 거짓말을 한다. (가드는 이 술어를
    INSERT와 ``validating``/``loading``으로 가는 UPDATE에만 적용하고 정리 write는
    면제한다 — alembic 0092. 유도는 INSERT 경로에서만 쓰이므로 그 면제와 무관하다.)
    """

    keys = (
        await session.execute(
            text(_RESOLVE_SCOPE_OPERATION_SQL),
            {"provider_dataset_id": provider_dataset_id, "sync_scope": sync_scope},
        )
    ).scalars().all()
    if len(keys) != 1:
        raise OfflineUploadScopeOperationUnresolved(
            f"offline upload scope resolves to {len(keys)} operations "
            f"(provider_dataset_id={provider_dataset_id}, sync_scope={sync_scope!r})",
            resolved=len(keys),
        )
    return str(keys[0])


async def reserve_offline_upload(
    session: AsyncSession,
    *,
    upload_id: str,
    provider_dataset_id: int,
    original_filename: str,
    storage_backend: str,
    storage_key: str,
    byte_size: int,
    checksum_sha256: str,
    sync_scope: str = "dataset_wide",
    detected_format: str | None = None,
    detected_encoding: str | None = None,
    created_by: str | None = None,
) -> OfflineUpload | None:
    """외부 저장 전에 ``uploading`` row와 checksum 소유권을 원자적으로 선점한다."""
    operation_key = await resolve_offline_upload_operation_key(
        session, provider_dataset_id=provider_dataset_id, sync_scope=sync_scope
    )
    result = await session.execute(
        text(_RESERVE_SQL),
        {
            "upload_id": upload_id,
            "provider_dataset_id": provider_dataset_id,
            "sync_scope": sync_scope,
            "operation_key": operation_key,
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
    row = result.one_or_none()
    return _row_to_upload(row) if row is not None else None


async def finalize_offline_upload_reservation(
    session: AsyncSession,
    *,
    upload_id: str,
) -> OfflineUpload | None:
    """증명된 object의 예약 row를 ``uploaded``로 확정한다."""
    result = await session.execute(
        text(_FINALIZE_RESERVATION_SQL),
        {"upload_id": upload_id},
    )
    row = result.one_or_none()
    if row is not None:
        return _row_to_upload(row)
    upload = await get_offline_upload(session, upload_id)
    if upload is not None and upload.status == "uploaded":
        return upload
    await _missing_or_status_conflict(
        session,
        upload_id=upload_id,
        target_status="uploaded",
        allowed_statuses=frozenset({"uploading", "uploaded"}),
    )
    return None


async def delete_offline_upload(
    session: AsyncSession,
    *,
    upload_id: str,
    command_id: int,
) -> OfflineUpload | None:
    """소유 command가 예약한 업로드 메타데이터 row를 삭제한다.

    ``status='deleting'``과 ``delete_command_id``가 모두 일치해야 한다. row가
    없으면 ``None``을 반환한다. 연관 ``ops.import_jobs`` row는 audit 기록으로 보존한다
    (FK는 upload→job 방향 ``ON DELETE SET NULL`` — row 삭제로 job은 안 지워짐).
    """
    result = await session.execute(
        text(_DELETE_SQL),
        {
            "upload_id": upload_id,
            "command_id": command_id,
        },
    )
    row = result.one_or_none()
    if row is not None:
        return _row_to_upload(row)
    await _missing_or_status_conflict(
        session,
        upload_id=upload_id,
        target_status="deleted",
        allowed_statuses=frozenset({"deleting"}),
    )
    return None


async def reserve_offline_upload_delete(
    session: AsyncSession,
    *,
    upload_id: str,
    command_id: int,
) -> OfflineUpload | None:
    """삭제 command가 resource row를 원자적으로 소유하고 ``deleting``으로 전이한다."""
    result = await session.execute(
        text(_RESERVE_DELETE_SQL),
        {
            "upload_id": upload_id,
            "command_id": command_id,
            "allowed_statuses": list(OFFLINE_UPLOAD_DELETABLE_STATES),
        },
    )
    row = result.one_or_none()
    if row is not None:
        return _row_to_upload(row)
    await _missing_or_status_conflict(
        session,
        upload_id=upload_id,
        target_status="deleting",
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
    provider_dataset_id: int,
    sync_scope: str,
    operation_key: str,
    checksum_sha256: str,
) -> OfflineUpload | None:
    """canonical identity triple + checksum으로 기존 업로드를 조회한다.

    ``operation_key``가 필수인 이유: 멱등 UNIQUE가 4열이라(alembic 0092) 같은
    (dataset, scope, checksum)에 형제 operation 행이 **동시에 존재할 수 있다**.
    triple을 지정하지 않으면 어느 행이 ``ON CONFLICT``를 일으켰는지 알 수 없고,
    중복 409가 엉뚱한 operation에 결박된 upload를 가리키게 된다.
    """
    result = await session.execute(
        text(_GET_BY_CHECKSUM_SQL),
        {
            "provider_dataset_id": provider_dataset_id,
            "sync_scope": sync_scope,
            "operation_key": operation_key,
            "checksum_sha256": checksum_sha256,
        },
    )
    row = result.one_or_none()
    return _row_to_upload(row) if row is not None else None


async def list_offline_uploads(
    session: AsyncSession,
    *,
    status: str | None = None,
    provider_dataset_id: int | None = None,
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
                "provider_dataset_id": provider_dataset_id,
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

    job = await start_provider_dataset_import_job(
        session,
        kind=job_kind,
        payload={
            "upload_id": upload.upload_id,
            "provider_dataset_id": upload.provider_dataset_id,
            "sync_scope": upload.sync_scope,
            "storage_backend": upload.storage_backend,
            "storage_key": upload.storage_key,
            "dagster_run_id": None,
        },
        source_checksum=upload.checksum_sha256,
        dataset_membership=ImportJobDatasetTarget(
            provider_dataset_id=upload.provider_dataset_id,
            sync_scope=upload.sync_scope,
            operation_key=upload.operation_key,
        ),
        trigger_kind="manual",
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
