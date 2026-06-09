"""``/admin/offline-uploads`` 운영 라우터 (ADR-045 T-208h).

오프라인 원본 파일을 RustFS/S3 호환 bucket에 저장하고 ``ops.offline_uploads``
메타데이터로 추적한다. 실제 FeatureBundle 적재는 Dagster
``offline_upload_load`` job을 GraphQL로 실행해 처리한다.
"""

from __future__ import annotations

import hashlib
import logging
import mimetypes
from pathlib import PurePath
from time import perf_counter
from typing import Annotated, Any, Final, cast
from uuid import uuid4

import httpx
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from krtour.map.core.exceptions import FileStoreError
from krtour.map.core.offline_upload_states import (
    OFFLINE_UPLOAD_LOADABLE_STATES,
    OFFLINE_UPLOAD_TABULAR_FORMATS,
    OFFLINE_UPLOAD_TABULAR_LOADABLE_STATES,
    OFFLINE_UPLOAD_WRITEABLE_FORMATS,
    OfflineUploadState,
)
from krtour.map.geocoding import (
    KraddrGeoRestClient,
    kraddr_geo_address_resolver,
    kraddr_geo_reverse_geocoder,
)
from krtour.map.infra.file_store import S3ObjectStore, build_s3_object_store
from krtour.map.infra.jobs_repo import finish_import_job, get_import_job
from krtour.map.infra.offline_upload_repo import (
    OfflineUpload,
    OfflineUploadPage,
    OfflineUploadStateConflict,
    create_offline_upload,
    finish_offline_upload_load,
    get_offline_upload,
    get_offline_upload_by_checksum,
    list_offline_uploads,
    reserve_offline_upload_load,
)
from krtour.map.offline_upload import (
    preview_offline_tabular_upload,
    run_offline_upload_validation_job,
)
from krtour.map.settings import KrtourMapSettings
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from krtour.map_admin.db import get_session
from krtour.map_admin.response import Meta, make_meta
from krtour.map_admin.settings import AdminSettings

__all__ = [
    "router",
    "OfflineUploadRecord",
    "OfflineUploadListResponse",
    "OfflineUploadWriteResponse",
    "OfflineUploadPreviewResponse",
    "OfflineUploadValidationResponse",
    "OfflineUploadLaunchResponse",
]


router = APIRouter(prefix="/admin/offline-uploads", tags=["admin-offline-uploads"])
_LOG = logging.getLogger(__name__)

_MULTIPART_CONTENT_LENGTH_MARGIN_BYTES: Final[int] = 64 * 1024
_DAGSTER_OFFLINE_UPLOAD_JOB_NAME: Final[str] = "offline_upload_load"
_DAGSTER_LAUNCH_MUTATION: Final[str] = """
mutation KrtourMapLaunchOfflineUploadLoad($executionParams: ExecutionParams!) {
  launchRun(executionParams: $executionParams) {
    __typename
    ... on LaunchRunSuccess {
      run {
        runId
        status
      }
    }
    ... on RunConfigValidationInvalid {
      errors {
        message
      }
    }
    ... on PipelineNotFoundError {
      message
    }
    ... on RunConflict {
      message
    }
    ... on UnauthorizedError {
      message
    }
    ... on InvalidSubsetError {
      message
    }
    ... on PresetNotFoundError {
      message
    }
    ... on ConflictingExecutionParamsError {
      message
    }
    ... on NoModeProvidedError {
      message
    }
    ... on PythonError {
      message
    }
  }
}
"""


class OfflineUploadRecord(BaseModel):
    """``ops.offline_uploads`` 행의 HTTP 표현."""

    model_config = ConfigDict(extra="forbid")

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
    created_at: str
    updated_at: str
    status_url: str
    load_url: str


class OfflineUploadWriteMeta(BaseModel):
    """업로드 생성 응답 metadata."""

    model_config = ConfigDict(extra="forbid")

    duration_ms: int
    request_id: str = ""
    bucket: str
    object_key: str
    content_type: str


class OfflineUploadLaunchMeta(BaseModel):
    """Dagster load 실행 응답 metadata."""

    model_config = ConfigDict(extra="forbid")

    duration_ms: int
    request_id: str = ""
    dagster_run_id: str
    dagster_status: str


class OfflineUploadColumnMappingRecord(BaseModel):
    """CSV/TSV column mapping HTTP 표현."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    lon: str = Field(min_length=1)
    lat: str = Field(min_length=1)
    address: str | None = None
    source_id: str | None = None
    bjd_code: str | None = None
    category: str | None = None
    default_category: str = "02020101"
    default_marker_icon: str = "marker"
    default_marker_color: str = "P-01"
    default_place_kind: str = "offline_upload"


class OfflineUploadPreviewMeta(BaseModel):
    """CSV/TSV preview metadata."""

    model_config = ConfigDict(extra="forbid")

    duration_ms: int
    request_id: str = ""
    parsed_format: str
    encoding: str
    delimiter: str
    headers: list[str]
    sample_rows: list[dict[str, str]]
    rows_total: int
    rows_sampled: int
    bytes_read: int
    checksum_sha256_actual: str


class OfflineUploadValidationIssueRecord(BaseModel):
    """CSV/TSV validation issue HTTP 표현."""

    model_config = ConfigDict(extra="forbid")

    severity: str
    code: str
    message: str
    row_number: int | None = None
    column: str | None = None


class OfflineUploadValidationRequest(BaseModel):
    """`POST /admin/offline-uploads/{upload_id}/validate` 요청."""

    model_config = ConfigDict(extra="forbid")

    sample_size: int = Field(default=1000, ge=1, le=10_000)
    column_mapping: OfflineUploadColumnMappingRecord
    operator: str | None = None


class OfflineUploadValidationMeta(OfflineUploadPreviewMeta):
    """CSV/TSV validation response metadata."""

    job_id: str | None
    job_status: str | None
    column_mapping: OfflineUploadColumnMappingRecord
    valid_rows: int
    error_rows: int
    issues: list[OfflineUploadValidationIssueRecord]


class OfflineUploadWriteResponse(BaseModel):
    """`POST /admin/offline-uploads` 응답."""

    model_config = ConfigDict(extra="forbid")

    data: OfflineUploadRecord
    meta: OfflineUploadWriteMeta


class OfflineUploadPreviewResponse(BaseModel):
    """`GET /admin/offline-uploads/{upload_id}/preview` 응답."""

    model_config = ConfigDict(extra="forbid")

    data: OfflineUploadRecord
    meta: OfflineUploadPreviewMeta


class OfflineUploadValidationResponse(BaseModel):
    """`POST/GET /admin/offline-uploads/{upload_id}/validation` 응답."""

    model_config = ConfigDict(extra="forbid")

    data: OfflineUploadRecord
    meta: OfflineUploadValidationMeta


class OfflineUploadLaunchResponse(BaseModel):
    """`POST /admin/offline-uploads/{upload_id}/load` 응답."""

    model_config = ConfigDict(extra="forbid")

    data: OfflineUploadRecord
    meta: OfflineUploadLaunchMeta


class OfflineUploadDetailMeta(BaseModel):
    """단건 조회 응답 metadata."""

    model_config = ConfigDict(extra="forbid")

    duration_ms: int
    request_id: str = ""


class OfflineUploadDetailResponse(BaseModel):
    """`GET /admin/offline-uploads/{upload_id}` 응답 (DA-D-03 envelope)."""

    model_config = ConfigDict(extra="forbid")

    data: OfflineUploadRecord
    meta: Meta


class OfflineUploadListData(BaseModel):
    """오프라인 업로드 목록 data."""

    model_config = ConfigDict(extra="forbid")

    items: list[OfflineUploadRecord]


class OfflineUploadListResponse(BaseModel):
    """`GET /admin/offline-uploads` 응답 (DA-D-03 envelope)."""

    model_config = ConfigDict(extra="forbid")

    data: OfflineUploadListData
    meta: Meta


class _DagsterLaunch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    status: str


def _record_from_upload(row: OfflineUpload) -> OfflineUploadRecord:
    return OfflineUploadRecord(
        upload_id=row.upload_id,
        provider=row.provider,
        dataset_key=row.dataset_key,
        sync_scope=row.sync_scope,
        original_filename=row.original_filename,
        storage_backend=row.storage_backend,
        storage_key=row.storage_key,
        byte_size=row.byte_size,
        checksum_sha256=row.checksum_sha256,
        detected_format=row.detected_format,
        detected_encoding=row.detected_encoding,
        status=row.state,
        validation_job_id=row.validation_job_id,
        load_job_id=row.load_job_id,
        created_by=row.created_by,
        created_at=row.created_at.isoformat(),
        updated_at=row.updated_at.isoformat(),
        status_url=f"/v1/admin/offline-uploads/{row.upload_id}",
        load_url=f"/v1/admin/offline-uploads/{row.upload_id}/load",
    )


def _is_tabular_upload(row: OfflineUpload) -> bool:
    detected = (row.detected_format or _detected_format(row.original_filename) or "").lower()
    return detected in OFFLINE_UPLOAD_TABULAR_FORMATS


def _can_load(row: OfflineUpload) -> bool:
    if row.state not in OFFLINE_UPLOAD_LOADABLE_STATES:
        return False
    if _is_tabular_upload(row):
        return (
            row.validation_job_id is not None
            and row.state in OFFLINE_UPLOAD_TABULAR_LOADABLE_STATES
        )
    return True


def _load_reject_detail(row: OfflineUpload) -> str:
    if _is_tabular_upload(row) and row.validation_job_id is None:
        return "CSV/TSV offline upload은 load 전 validate가 필요합니다."
    return f"load 가능한 status가 아닙니다: {row.state}"


def _require_tabular(row: OfflineUpload) -> None:
    if not _is_tabular_upload(row):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"CSV/TSV 업로드가 아닙니다: {row.detected_format}",
        )


def _validate_stored_body(row: OfflineUpload, body: bytes) -> tuple[int, str]:
    checksum_actual = hashlib.sha256(body).hexdigest()
    if len(body) != row.byte_size:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(f"offline upload size mismatch: expected={row.byte_size}, actual={len(body)}"),
        )
    if checksum_actual.lower() != row.checksum_sha256.lower():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "offline upload checksum mismatch: "
                f"expected={row.checksum_sha256}, actual={checksum_actual}"
            ),
        )
    return len(body), checksum_actual


def _int(value: object, default: int = 0) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdecimal():
        return int(value)
    return default


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _sample_rows(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, str]] = []
    for item in value:
        if isinstance(item, dict):
            rows.append({str(key): str(raw) for key, raw in item.items()})
    return rows


def _issues(value: object) -> list[OfflineUploadValidationIssueRecord]:
    return [
        OfflineUploadValidationIssueRecord(
            severity=_string(_dict(item).get("severity"), "error"),
            code=_string(_dict(item).get("code"), "unknown"),
            message=_string(_dict(item).get("message")),
            row_number=(
                _int(_dict(item).get("row_number"))
                if _dict(item).get("row_number") is not None
                else None
            ),
            column=(
                _string(_dict(item).get("column"))
                if _dict(item).get("column") is not None
                else None
            ),
        )
        for item in _list(value)
    ]


def _validation_meta_from_payload(
    payload: dict[str, Any],
    *,
    duration_ms: int,
) -> OfflineUploadValidationMeta:
    return OfflineUploadValidationMeta(
        duration_ms=duration_ms,
        parsed_format=_string(payload.get("parsed_format")),
        encoding=_string(payload.get("encoding")),
        delimiter=_string(payload.get("delimiter"), ","),
        headers=_string_list(payload.get("headers")),
        sample_rows=_sample_rows(payload.get("sample_rows")),
        rows_total=_int(payload.get("rows_total")),
        rows_sampled=_int(payload.get("rows_sampled")),
        bytes_read=_int(payload.get("bytes_read")),
        checksum_sha256_actual=_string(payload.get("checksum_sha256_actual")),
        job_id=(_string(payload.get("job_id")) if payload.get("job_id") is not None else None),
        job_status=(
            _string(payload.get("job_state")) if payload.get("job_state") is not None else None
        ),
        column_mapping=OfflineUploadColumnMappingRecord.model_validate(
            _dict(payload.get("column_mapping"))
        ),
        valid_rows=_int(payload.get("valid_rows")),
        error_rows=_int(payload.get("error_rows")),
        issues=_issues(payload.get("issues")),
    )


def _settings_from_request(request: Request) -> AdminSettings:
    settings = getattr(request.app.state, "settings", None)
    if isinstance(settings, AdminSettings):
        return settings
    return AdminSettings()


def _graphql_url(settings: AdminSettings) -> str:
    if settings.dagster_graphql_url:
        return settings.dagster_graphql_url
    return f"{settings.dagster_url.rstrip('/')}/graphql"


def _dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _string(value: object, default: str = "") -> str:
    return value if isinstance(value, str) else default


def _safe_filename(filename: str | None) -> str:
    raw = PurePath(filename or "offline-upload.jsonl").name.replace("\\", "_").strip()
    safe = "".join(
        char if char.isalnum() or char in {" ", ".", "_", "-"} else "_" for char in raw
    ).strip()
    return safe[:160] or "offline-upload.jsonl"


def _detected_format(filename: str) -> str | None:
    suffix = PurePath(filename).suffix.lower()
    if suffix in {".jsonl", ".ndjson"}:
        return "jsonl"
    if suffix == ".json":
        return "json"
    if suffix == ".csv":
        return "csv"
    if suffix == ".tsv":
        return "tsv"
    return None


def _content_type(filename: str, detected_format: str | None) -> str:
    if detected_format == "jsonl":
        return "application/x-ndjson"
    if detected_format == "json":
        return "application/json"
    if detected_format == "csv":
        return "text/csv; charset=utf-8"
    if detected_format == "tsv":
        return "text/tab-separated-values; charset=utf-8"
    guessed, _encoding = mimetypes.guess_type(filename)
    return guessed or "application/octet-stream"


def _content_length(request: Request) -> int | None:
    value = request.headers.get("content-length")
    if value is None:
        return None
    try:
        content_length = int(value)
    except ValueError:
        return None
    return content_length if content_length >= 0 else None


def _upload_too_large(max_bytes: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
        detail=f"offline upload 파일은 최대 {max_bytes} bytes까지 허용합니다.",
    )


def _guard_upload_content_length(request: Request, *, max_bytes: int) -> None:
    content_length = _content_length(request)
    if content_length is None:
        return
    # multipart/form-data의 field/header overhead 때문에 실제 파일 상한보다 약간 큰
    # request body는 실제 read 상한에서 다시 판정한다.
    if content_length > max_bytes + _MULTIPART_CONTENT_LENGTH_MARGIN_BYTES:
        raise _upload_too_large(max_bytes)


async def _read_upload_body(file: UploadFile, *, max_bytes: int) -> bytes:
    body = await file.read(max_bytes + 1)
    if len(body) > max_bytes:
        raise _upload_too_large(max_bytes)
    return body


def _storage_key(settings: KrtourMapSettings, upload_id: str, filename: str) -> str:
    prefix = settings.offline_upload_prefix.strip("/")
    if prefix:
        return f"{prefix}/{upload_id}/{filename}"
    return f"{upload_id}/{filename}"


def _duplicate_upload_conflict(upload: OfflineUpload) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "OFFLINE_UPLOAD_DUPLICATE",
            "message": "동일 provider/dataset/scope/checksum offline upload가 이미 있습니다.",
            "details": {
                "upload_id": upload.upload_id,
                "provider": upload.provider,
                "dataset_key": upload.dataset_key,
                "sync_scope": upload.sync_scope,
                "checksum_sha256": upload.checksum_sha256,
            },
        },
    )


def build_offline_upload_store(settings: KrtourMapSettings) -> S3ObjectStore:
    """admin upload API용 RustFS/S3 store를 설정에서 만든다."""
    return build_s3_object_store(
        bucket=settings.offline_upload_bucket,
        region_name=settings.object_store_region,
        endpoint_url=settings.object_store_endpoint_url,
        access_key_id=(
            settings.object_store_access_key_id.get_secret_value()
            if settings.object_store_access_key_id is not None
            else None
        ),
        secret_access_key=(
            settings.object_store_secret_access_key.get_secret_value()
            if settings.object_store_secret_access_key is not None
            else None
        ),
        public_base_url=None,
    )


def _krtour_map_settings_from_request(request: Request) -> KrtourMapSettings:
    settings = getattr(request.app.state, "krtour_map_settings", None)
    if isinstance(settings, KrtourMapSettings):
        return settings
    settings = KrtourMapSettings()
    request.app.state.krtour_map_settings = settings
    return settings


def _offline_upload_store_from_request(request: Request) -> S3ObjectStore:
    store = getattr(request.app.state, "offline_upload_store", None)
    if store is not None:
        return cast(S3ObjectStore, store)
    store = build_offline_upload_store(_krtour_map_settings_from_request(request))
    request.app.state.offline_upload_store = store
    return store


async def _rollback_uploaded_object(
    store: S3ObjectStore,
    object_key: str,
) -> None:
    """DB metadata 생성 실패 시 방금 쓴 offline upload object만 보상 삭제한다."""
    try:
        await store.delete_object(object_key)
    except FileStoreError:
        _LOG.exception(
            "offline upload object rollback delete failed: object_key=%s",
            object_key,
        )


async def _post_graphql(
    graphql_url: str,
    *,
    query: str,
    variables: dict[str, object],
    timeout_seconds: float,
) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        response = await client.post(
            graphql_url,
            json={"query": query, "variables": variables},
        )
        response.raise_for_status()
        payload = response.json()
    return _dict(payload)


def _launch_variables(settings: AdminSettings, upload_id: str) -> dict[str, object]:
    return {
        "executionParams": {
            "selector": {
                "jobName": _DAGSTER_OFFLINE_UPLOAD_JOB_NAME,
                "repositoryName": settings.dagster_repository_name,
                "repositoryLocationName": settings.dagster_repository_location_name,
            },
            "runConfigData": {
                "ops": {
                    "load_offline_upload": {
                        "config": {"upload_id": upload_id},
                    },
                },
            },
            "mode": "default",
            "executionMetadata": {
                "tags": [
                    {"key": "krtour_map.job_kind", "value": "offline_upload_load"},
                    {"key": "krtour_map.upload_id", "value": upload_id},
                ],
            },
        },
    }


def _launch_error_detail(result: dict[str, Any]) -> str:
    typename = _string(result.get("__typename"), "UnknownDagsterLaunchError")
    message = result.get("message")
    if isinstance(message, str) and message:
        return f"{typename}: {message}"
    validation_messages = [
        _string(_dict(item).get("message"))
        for item in _list(result.get("errors"))
        if _string(_dict(item).get("message"))
    ]
    if validation_messages:
        return f"{typename}: {'; '.join(validation_messages)}"
    return f"Dagster launch failed: {typename}"


async def launch_offline_upload_load(
    request: Request,
    upload_id: str,
) -> _DagsterLaunch:
    """Dagster ``offline_upload_load`` run을 시작한다."""
    settings = _settings_from_request(request)
    graphql_url = _graphql_url(settings)
    try:
        payload = await _post_graphql(
            graphql_url,
            query=_DAGSTER_LAUNCH_MUTATION,
            variables=_launch_variables(settings, upload_id),
            timeout_seconds=settings.dagster_request_timeout_seconds,
        )
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Dagster GraphQL launch 호출 실패: {exc}",
        ) from exc

    errors = payload.get("errors")
    if isinstance(errors, list) and errors:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Dagster GraphQL 오류: {errors}",
        )

    result = _dict(_dict(payload.get("data")).get("launchRun"))
    if _string(result.get("__typename")) != "LaunchRunSuccess":
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=_launch_error_detail(result),
        )

    run = _dict(result.get("run"))
    return _DagsterLaunch(
        run_id=_string(run.get("runId")),
        status=_string(run.get("status"), "UNKNOWN"),
    )


@router.post(
    "",
    response_model=OfflineUploadWriteResponse,
    status_code=status.HTTP_201_CREATED,
    summary="오프라인 원본 업로드",
    responses={
        413: {"description": "offline upload 파일 크기 상한 초과"},
    },
)
async def create_offline_upload_request(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    file: Annotated[
        UploadFile,
        File(description="JSON/JSONL FeatureBundle 또는 CSV/TSV tabular 파일"),
    ],
    provider: Annotated[str, Form(min_length=1)],
    dataset_key: Annotated[str, Form(min_length=1)],
    sync_scope: Annotated[str, Form(min_length=1)] = "default",
    created_by: Annotated[str | None, Form()] = None,
) -> OfflineUploadWriteResponse:
    started_at = perf_counter()
    settings = _krtour_map_settings_from_request(request)
    max_bytes = settings.offline_upload_max_bytes
    _guard_upload_content_length(request, max_bytes=max_bytes)
    upload_id = str(uuid4())
    filename = _safe_filename(file.filename)
    detected_format = _detected_format(filename)
    if detected_format not in OFFLINE_UPLOAD_WRITEABLE_FORMATS:
        raise HTTPException(
            status_code=422,
            detail="offline upload은 JSON/JSONL FeatureBundle 또는 CSV/TSV 파일만 지원합니다.",
        )
    body = await _read_upload_body(file, max_bytes=max_bytes)
    if not body:
        raise HTTPException(
            status_code=422,
            detail="offline upload 파일이 비어 있습니다.",
        )

    content_type = file.content_type or _content_type(filename, detected_format)
    checksum_sha256 = hashlib.sha256(body).hexdigest()
    storage_key = _storage_key(settings, upload_id, filename)
    store = _offline_upload_store_from_request(request)
    try:
        stored = await store.write_bytes(
            storage_key,
            body,
            content_type=content_type,
            metadata={
                "upload_id": upload_id,
                "provider": provider,
                "dataset_key": dataset_key,
                "sync_scope": sync_scope,
            },
        )
    except FileStoreError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    try:
        async with session.begin():
            upload = await create_offline_upload(
                session,
                upload_id=upload_id,
                provider=provider,
                dataset_key=dataset_key,
                sync_scope=sync_scope,
                original_filename=filename,
                storage_backend="rustfs",
                storage_key=stored.object_key,
                byte_size=stored.byte_size,
                checksum_sha256=checksum_sha256,
                detected_format=detected_format,
                detected_encoding=None,
                created_by=created_by,
            )
    except IntegrityError as exc:
        await _rollback_uploaded_object(store, stored.object_key)
        duplicate = await get_offline_upload_by_checksum(
            session,
            provider=provider,
            dataset_key=dataset_key,
            sync_scope=sync_scope,
            checksum_sha256=checksum_sha256,
        )
        if duplicate is not None:
            raise _duplicate_upload_conflict(duplicate) from exc
        raise
    except Exception:  # noqa: BLE001 - DB 원인 보존 + object 보상 삭제
        await _rollback_uploaded_object(store, stored.object_key)
        raise
    return OfflineUploadWriteResponse(
        data=_record_from_upload(upload),
        meta=OfflineUploadWriteMeta(
            duration_ms=max(0, int((perf_counter() - started_at) * 1000)),
            bucket=stored.bucket,
            object_key=stored.object_key,
            content_type=content_type,
        ),
    )


@router.get(
    "",
    response_model=OfflineUploadListResponse,
    summary="오프라인 업로드 목록",
)
async def list_offline_upload_requests(
    session: Annotated[AsyncSession, Depends(get_session)],
    status_filter: Annotated[OfflineUploadState | None, Query(alias="status")] = None,
    provider: Annotated[str | None, Query()] = None,
    dataset_key: Annotated[str | None, Query()] = None,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query()] = None,
) -> OfflineUploadListResponse:
    started_at = perf_counter()
    try:
        page: OfflineUploadPage = await list_offline_uploads(
            session,
            state=status_filter,
            provider=provider,
            dataset_key=dataset_key,
            limit=page_size,
            cursor=cursor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return OfflineUploadListResponse(
        data=OfflineUploadListData(items=[_record_from_upload(item) for item in page.items]),
        meta=make_meta(
            started_at=started_at,
            page_size=page_size,
            next_cursor=page.next_cursor,
        ),
    )


@router.get(
    "/{upload_id}",
    response_model=OfflineUploadDetailResponse,
    summary="오프라인 업로드 단건 조회",
    responses={404: {"description": "upload_id 없음"}},
)
async def get_offline_upload_request(
    upload_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> OfflineUploadDetailResponse:
    started_at = perf_counter()
    row = await get_offline_upload(session, upload_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"offline upload 없음: {upload_id!r}",
        )
    return OfflineUploadDetailResponse(
        data=_record_from_upload(row),
        meta=make_meta(started_at=started_at),
    )


@router.get(
    "/{upload_id}/preview",
    response_model=OfflineUploadPreviewResponse,
    summary="CSV/TSV 오프라인 업로드 header/sample preview",
    responses={
        404: {"description": "upload_id 없음"},
        409: {"description": "CSV/TSV 업로드가 아니거나 저장 원본 불일치"},
        502: {"description": "객체 저장소 읽기 실패"},
    },
)
async def preview_offline_upload_request(
    upload_id: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    sample_size: Annotated[int, Query(ge=1, le=200)] = 20,
) -> OfflineUploadPreviewResponse:
    started_at = perf_counter()
    row = await get_offline_upload(session, upload_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"offline upload 없음: {upload_id!r}",
        )
    _require_tabular(row)

    store = _offline_upload_store_from_request(request)
    try:
        body = await store.read_bytes(row.storage_key)
    except FileStoreError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    bytes_read, checksum_actual = _validate_stored_body(row, body)
    try:
        preview = preview_offline_tabular_upload(
            body,
            detected_format=row.detected_format,
            detected_encoding=row.detected_encoding,
            original_filename=row.original_filename,
            sample_size=sample_size,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    payload = preview.as_payload()
    return OfflineUploadPreviewResponse(
        data=_record_from_upload(row),
        meta=OfflineUploadPreviewMeta(
            duration_ms=max(0, int((perf_counter() - started_at) * 1000)),
            parsed_format=_string(payload.get("parsed_format")),
            encoding=_string(payload.get("encoding")),
            delimiter=_string(payload.get("delimiter"), ","),
            headers=_string_list(payload.get("headers")),
            sample_rows=_sample_rows(payload.get("sample_rows")),
            rows_total=_int(payload.get("rows_total")),
            rows_sampled=_int(payload.get("rows_sampled")),
            bytes_read=bytes_read,
            checksum_sha256_actual=checksum_actual,
        ),
    )


@router.post(
    "/{upload_id}/validate",
    response_model=OfflineUploadValidationResponse,
    summary="CSV/TSV 오프라인 업로드 column mapping 검증",
    responses={
        404: {"description": "upload_id 없음"},
        409: {"description": "validation 가능한 상태 아님"},
        502: {"description": "객체 저장소 읽기 실패"},
    },
)
async def validate_offline_upload_request(
    upload_id: str,
    request: Request,
    request_body: OfflineUploadValidationRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> OfflineUploadValidationResponse:
    started_at = perf_counter()
    settings = _krtour_map_settings_from_request(request)
    store = _offline_upload_store_from_request(request)
    try:
        if settings.kraddr_geo_base_url:
            async with httpx.AsyncClient(
                base_url=settings.kraddr_geo_base_url,
                timeout=settings.kraddr_geo_timeout_seconds,
            ) as http:
                kraddr = KraddrGeoRestClient(http)
                async with session.begin():
                    row = await get_offline_upload(session, upload_id)
                    if row is None:
                        raise HTTPException(
                            status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"offline upload 없음: {upload_id!r}",
                        )
                    _require_tabular(row)
                    result = await run_offline_upload_validation_job(
                        session,
                        upload_id,
                        store=store,
                        column_mapping=request_body.column_mapping.model_dump(),
                        sample_size=request_body.sample_size,
                        operator=request_body.operator,
                        address_resolver=kraddr_geo_address_resolver(kraddr, fallback="api"),
                        reverse_geocoder=kraddr_geo_reverse_geocoder(kraddr),
                    )
        else:
            async with session.begin():
                row = await get_offline_upload(session, upload_id)
                if row is None:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"offline upload 없음: {upload_id!r}",
                    )
                _require_tabular(row)
                result = await run_offline_upload_validation_job(
                    session,
                    upload_id,
                    store=store,
                    column_mapping=request_body.column_mapping.model_dump(),
                    sample_size=request_body.sample_size,
                    operator=request_body.operator,
                )
    except HTTPException:
        raise
    except FileStoreError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"kraddr-geo geocode 호출 실패: {exc}",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    return OfflineUploadValidationResponse(
        data=_record_from_upload(result.upload),
        meta=_validation_meta_from_payload(
            result.as_payload(),
            duration_ms=max(0, int((perf_counter() - started_at) * 1000)),
        ),
    )


@router.get(
    "/{upload_id}/validation",
    response_model=OfflineUploadValidationResponse,
    summary="CSV/TSV 오프라인 업로드 최근 validation 결과 조회",
    responses={
        404: {"description": "upload_id 또는 validation job 없음"},
        409: {"description": "validation payload 없음"},
    },
)
async def get_offline_upload_validation_request(
    upload_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> OfflineUploadValidationResponse:
    started_at = perf_counter()
    row = await get_offline_upload(session, upload_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"offline upload 없음: {upload_id!r}",
        )
    _require_tabular(row)
    if row.validation_job_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="validation job이 아직 없습니다.",
        )
    job = await get_import_job(session, row.validation_job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"validation job 없음: {row.validation_job_id!r}",
        )
    if "column_mapping" not in job.payload:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="validation job payload에 column_mapping이 없습니다.",
        )
    return OfflineUploadValidationResponse(
        data=_record_from_upload(row),
        meta=_validation_meta_from_payload(
            job.payload,
            duration_ms=max(0, int((perf_counter() - started_at) * 1000)),
        ),
    )


@router.post(
    "/{upload_id}/load",
    response_model=OfflineUploadLaunchResponse,
    summary="Dagster offline_upload_load job 실행",
    responses={
        404: {"description": "upload_id 없음"},
        409: {"description": "load 가능한 상태 아님"},
        502: {"description": "Dagster GraphQL launch 실패"},
    },
)
async def load_offline_upload_request(
    upload_id: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> OfflineUploadLaunchResponse:
    started_at = perf_counter()
    try:
        async with session.begin():
            row = await get_offline_upload(session, upload_id)
            if row is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"offline upload 없음: {upload_id!r}",
                )
            if not _can_load(row):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=_load_reject_detail(row),
                )
            loading = await reserve_offline_upload_load(session, upload_id=upload_id)
            if loading is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"offline upload 없음: {upload_id!r}",
                )
    except OfflineUploadStateConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    try:
        launch = await launch_offline_upload_load(request, upload_id)
    except HTTPException as exc:
        async with session.begin():
            if loading.load_job_id is not None:
                await finish_import_job(
                    session,
                    loading.load_job_id,
                    state="failed",
                    error_message=str(exc.detail),
                )
            await finish_offline_upload_load(session, upload_id=upload_id, state="load_failed")
        raise
    return OfflineUploadLaunchResponse(
        data=_record_from_upload(loading),
        meta=OfflineUploadLaunchMeta(
            duration_ms=max(0, int((perf_counter() - started_at) * 1000)),
            dagster_run_id=launch.run_id,
            dagster_status=launch.status,
        ),
    )
