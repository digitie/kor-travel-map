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
from uuid import UUID, uuid5

import httpx
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from kortravelmap.core.exceptions import FileStoreError
from kortravelmap.core.managed_file_states import (
    MANAGED_FILE_LOCATION_OFFLINE_UPLOADS,
)
from kortravelmap.core.offline_upload_states import (
    OFFLINE_UPLOAD_LOADABLE_STATES,
    OFFLINE_UPLOAD_TABULAR_FORMATS,
    OFFLINE_UPLOAD_TABULAR_LOADABLE_STATES,
    OFFLINE_UPLOAD_WRITEABLE_FORMATS,
    OfflineUploadState,
)
from kortravelmap.geocoding import (
    KorTravelGeoRestClient,
    kor_travel_geo_address_resolver,
    kor_travel_geo_reverse_geocoder,
)
from kortravelmap.infra import file_registry
from kortravelmap.infra.domain_command_execution_repo import (
    complete_offline_upload_command_effect,
    create_offline_upload_command_execution,
    get_offline_upload_command_execution,
    start_offline_upload_command_effect,
)
from kortravelmap.infra.domain_command_repo import (
    DomainCommandClaim,
    canonical_domain_command_fingerprint,
)
from kortravelmap.infra.file_store import (
    S3ObjectStore,
    build_s3_object_store,
)
from kortravelmap.infra.jobs_repo import finish_import_job, get_import_job
from kortravelmap.infra.offline_upload_repo import (
    OfflineUpload,
    OfflineUploadPage,
    OfflineUploadStatusConflict,
    delete_offline_upload,
    finalize_offline_upload_reservation,
    finish_offline_upload_load,
    get_offline_upload,
    get_offline_upload_by_checksum,
    list_offline_uploads,
    reserve_offline_upload,
    reserve_offline_upload_load,
)
from kortravelmap.offline_upload import (
    preview_offline_tabular_upload,
    run_offline_upload_validation_job,
)
from kortravelmap.settings import KorTravelMapSettings
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.api import dagster_graphql, domain_command_service
from kortravelmap.api.auth import (
    AdminProxyContext,
    require_admin_destructive_enabled,
    require_admin_frontend,
)
from kortravelmap.api.db import get_session
from kortravelmap.api.domain_command_service import (
    domain_command_transaction,
    idempotent_domain_command,
)
from kortravelmap.api.response import Meta, make_meta
from kortravelmap.api.settings import ApiSettings

__all__ = [
    "router",
    "OfflineUploadRecord",
    "OfflineUploadListResponse",
    "OfflineUploadWriteResponse",
    "OfflineUploadDeleteResponse",
    "OfflineUploadPreviewResponse",
    "OfflineUploadValidationResponse",
    "OfflineUploadLaunchResponse",
]


router = APIRouter(prefix="/admin/offline-uploads", tags=["admin-offline-uploads"])
_LOG = logging.getLogger(__name__)
_OFFLINE_UPLOAD_COMMAND_NAMESPACE = UUID("4d3855a2-855d-4a69-bf69-151dfae6e2f8")

_MULTIPART_CONTENT_LENGTH_MARGIN_BYTES: Final[int] = 64 * 1024
_DAGSTER_OFFLINE_UPLOAD_JOB_NAME: Final[str] = "offline_upload_load"
_DAGSTER_LAUNCH_MUTATION: Final[str] = """
mutation KorTravelMapLaunchOfflineUploadLoad($executionParams: ExecutionParams!) {
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
    # ADR-066 D-2 (T-VN-20): 감사 actor는 인증 principal에서만 파생한다. body의
    # operator 필드는 제거했다(옛 caller가 보내면 extra="forbid"로 422). offline
    # upload은 admin frontend 전용이고 PinVi는 호출하지 않는다.


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


class OfflineUploadDeleteResponse(BaseModel):
    """`DELETE /admin/offline-uploads/{upload_id}` 응답 (삭제된 row snapshot)."""

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
        status=row.status,
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
    if row.status not in OFFLINE_UPLOAD_LOADABLE_STATES:
        return False
    if _is_tabular_upload(row):
        return (
            row.validation_job_id is not None
            and row.status in OFFLINE_UPLOAD_TABULAR_LOADABLE_STATES
        )
    return True


def _load_reject_detail(row: OfflineUpload) -> str:
    if _is_tabular_upload(row) and row.validation_job_id is None:
        return "CSV/TSV offline upload은 load 전 validate가 필요합니다."
    return f"load 가능한 status가 아닙니다: {row.status}"


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
            _string(payload.get("job_status")) if payload.get("job_status") is not None else None
        ),
        column_mapping=OfflineUploadColumnMappingRecord.model_validate(
            _dict(payload.get("column_mapping"))
        ),
        valid_rows=_int(payload.get("valid_rows")),
        error_rows=_int(payload.get("error_rows")),
        issues=_issues(payload.get("issues")),
    )


def _settings_from_request(request: Request) -> ApiSettings:
    settings = getattr(request.app.state, "settings", None)
    if isinstance(settings, ApiSettings):
        return settings
    return ApiSettings()


def _validated_graphql_url(settings: ApiSettings) -> str:
    try:
        return dagster_graphql.dagster_urls(settings).graphql_url
    except dagster_graphql.DagsterUrlConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Dagster GraphQL URL 설정이 올바르지 않습니다.",
        ) from exc


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


def _storage_key(settings: KorTravelMapSettings, upload_id: str, filename: str) -> str:
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


def build_offline_upload_store(settings: KorTravelMapSettings) -> S3ObjectStore:
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


def _kor_travel_map_settings_from_request(request: Request) -> KorTravelMapSettings:
    settings = getattr(request.app.state, "kor_travel_map_settings", None)
    if isinstance(settings, KorTravelMapSettings):
        return settings
    settings = KorTravelMapSettings()
    request.app.state.kor_travel_map_settings = settings
    return settings


def _offline_upload_store_from_request(request: Request) -> S3ObjectStore:
    store = getattr(request.app.state, "offline_upload_store", None)
    if store is not None:
        return cast(S3ObjectStore, store)
    store = build_offline_upload_store(_kor_travel_map_settings_from_request(request))
    request.app.state.offline_upload_store = store
    return store


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


def _launch_variables(settings: ApiSettings, upload_id: str) -> dict[str, object]:
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
                    {"key": "kor_travel_map.job_kind", "value": "offline_upload_load"},
                    {"key": "kor_travel_map.upload_id", "value": upload_id},
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
    graphql_url = _validated_graphql_url(settings)
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
            detail="Dagster GraphQL launch 호출에 실패했습니다.",
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
    context: Annotated[AdminProxyContext, Depends(require_admin_frontend)],
    session: Annotated[AsyncSession, Depends(get_session)],
    file: Annotated[
        UploadFile,
        File(description="JSON/JSONL FeatureBundle 또는 CSV/TSV tabular 파일"),
    ],
    provider: Annotated[str, Form(min_length=1)],
    dataset_key: Annotated[str, Form(min_length=1)],
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
    sync_scope: Annotated[str, Form(min_length=1)] = "default",
) -> OfflineUploadWriteResponse:
    started_at = perf_counter()
    settings = _kor_travel_map_settings_from_request(request)
    max_bytes = settings.offline_upload_max_bytes
    _guard_upload_content_length(request, max_bytes=max_bytes)
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
    operation = "admin.offline-upload.create"
    upload_id = str(
        uuid5(
            _OFFLINE_UPLOAD_COMMAND_NAMESPACE,
            f"{context.actor}:{operation}:{idempotency_key}",
        )
    )
    storage_key = _storage_key(settings, upload_id, filename)
    store = _offline_upload_store_from_request(request)
    object_metadata = {
        "content-sha256": checksum_sha256,
        "dataset-key": dataset_key,
        "provider": provider,
        "sync-scope": sync_scope,
        "upload-id": upload_id,
    }
    metadata_digest = canonical_domain_command_fingerprint(object_metadata)
    payload = {
        "provider": provider,
        "dataset_key": dataset_key,
        "sync_scope": sync_scope,
        "filename": filename,
        "storage_backend": "rustfs",
        "bucket": store.bucket,
        "storage_key": storage_key,
        "content_type": content_type,
        "byte_size": len(body),
        "content_sha256": checksum_sha256,
        "metadata_digest": metadata_digest,
    }
    write_object = False
    async with session.begin():
        try:
            command = await domain_command_service.begin_domain_command(
                session,
                actor=context.actor,
                operation=operation,
                idempotency_key=idempotency_key,
                payload=payload,
            )
            execution = await create_offline_upload_command_execution(
                session,
                command_id=command.command_id,
                effect_kind="create",
                upload_id=upload_id,
                storage_backend="rustfs",
                bucket=store.bucket,
                storage_key=storage_key,
                content_type=content_type,
                byte_size=len(body),
                content_sha256=checksum_sha256,
                metadata_digest=metadata_digest,
                load_job_id=None,
                input_digest=command.request_fingerprint,
            )
            upload = await reserve_offline_upload(
                session,
                upload_id=upload_id,
                provider=provider,
                dataset_key=dataset_key,
                sync_scope=sync_scope,
                original_filename=filename,
                storage_backend="rustfs",
                storage_key=storage_key,
                byte_size=len(body),
                checksum_sha256=checksum_sha256,
                detected_format=detected_format,
                detected_encoding=None,
                created_by=context.actor,
            )
            if upload is None:
                duplicate = await get_offline_upload_by_checksum(
                    session,
                    provider=provider,
                    dataset_key=dataset_key,
                    sync_scope=sync_scope,
                    checksum_sha256=checksum_sha256,
                )
                if duplicate is None:
                    raise RuntimeError(
                        "offline upload checksum reservation conflict row is missing"
                    )
                raise _duplicate_upload_conflict(duplicate)
            write_object = True
        except domain_command_service.DomainCommandPending as pending:
            command = domain_command_service.DomainCommandHandle(
                command_id=pending.claim.command_id,
                actor=pending.claim.actor,
                operation=pending.claim.operation,
                idempotency_key=pending.claim.idempotency_key,
                request_fingerprint=pending.claim.request_fingerprint,
            )
            recovered_execution = await get_offline_upload_command_execution(
                session, command.command_id
            )
            if recovered_execution is None:
                raise
            execution = recovered_execution
            upload = await get_offline_upload(session, upload_id)
            if upload is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="offline upload reservation is missing",
                ) from pending
    if (
        execution.effect_kind != "create"
        or execution.upload_id != upload_id
        or execution.storage_backend != "rustfs"
        or execution.bucket != store.bucket
        or execution.storage_key != storage_key
        or execution.content_type != content_type
        or execution.byte_size != len(body)
        or execution.content_sha256 != checksum_sha256
        or execution.metadata_digest != metadata_digest
        or execution.input_digest != command.request_fingerprint
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="offline upload command execution identity mismatch",
        )

    if execution.phase == "prepared":
        async with session.begin():
            execution = await start_offline_upload_command_effect(
                session, command.command_id
            )
        write_object = True

    if execution.phase not in {"effect_started", "effect_succeeded"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="offline upload command phase is invalid",
        )

    if write_object:
        try:
            await store.write_bytes(
                storage_key,
                body,
                content_type=content_type,
                metadata=object_metadata,
            )
        except FileStoreError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=str(exc),
            ) from exc

    try:
        stored = await store.inspect_object(storage_key)
        proof_body = await store.read_bytes(storage_key)
    except (FileStoreError, KeyError) as exc:
        raise domain_command_service.DomainCommandPending(
            DomainCommandClaim(
                command_id=command.command_id,
                actor=command.actor,
                operation=command.operation,
                idempotency_key=command.idempotency_key,
                fingerprint_version=1,
                request_fingerprint=command.request_fingerprint,
                created_at=execution.prepared_at,
            )
        ) from exc
    if (
        stored.bucket != store.bucket
        or stored.object_key != storage_key
        or stored.byte_size != len(body)
        or stored.content_type != content_type
        or stored.metadata != object_metadata
        or canonical_domain_command_fingerprint(stored.metadata)
        != metadata_digest
        or hashlib.sha256(proof_body).hexdigest() != checksum_sha256
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="idempotent offline upload object proof mismatch",
        )

    async with session.begin():
        upload = await finalize_offline_upload_reservation(
            session,
            upload_id=upload_id,
        )
        if upload is None:
            raise HTTPException(status_code=404, detail="offline upload을 찾을 수 없습니다.")
        response = OfflineUploadWriteResponse(
            data=_record_from_upload(upload),
            meta=OfflineUploadWriteMeta(
                duration_ms=max(0, int((perf_counter() - started_at) * 1000)),
                bucket=stored.bucket,
                object_key=stored.object_key,
                content_type=content_type,
            ),
        )
        if execution.phase == "effect_started":
            await complete_offline_upload_command_effect(
                session,
                command.command_id,
                output_digest=canonical_domain_command_fingerprint(
                    response.model_dump(mode="json")
                ),
            )
        await domain_command_service.complete_domain_command(
            session,
            command=command,
            response=response,
            status_code=status.HTTP_201_CREATED,
        )
    # 파일 registry 등록 hook (H4) — 본 업로드 성공 후 별도 트랜잭션, 실패 무해.
    async with file_registry.registry_guard("offline-upload:register"), session.begin():
        await file_registry.register_file(
            session,
            storage_backend="s3",
            location=MANAGED_FILE_LOCATION_OFFLINE_UPLOADS,
            path=stored.object_key,
            kind="upload",
            provider=provider,
            dataset_key=dataset_key,
            byte_size=stored.byte_size,
            checksum_sha256=checksum_sha256,
            upload_id=upload_id,
            downloaded_at=upload.created_at,
            actor="api:admin",
            meta={
                "physical": {"bucket": stored.bucket},
                "original_filename": filename,
                "sync_scope": sync_scope,
            },
        )
    return response


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
            status=status_filter,
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


@router.delete(
    "/{upload_id}",
    response_model=OfflineUploadDeleteResponse,
    summary="오프라인 업로드 삭제 (정리 lifecycle)",
    dependencies=[Depends(require_admin_destructive_enabled)],
    responses={
        403: {"description": "파괴적 admin 작업 비활성"},
        404: {"description": "upload_id 없음"},
        409: {"description": "validation/load 진행 중 — 종료 후 재시도"},
    },
)
async def delete_offline_upload_request(
    upload_id: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> OfflineUploadDeleteResponse:
    """업로드 메타데이터 row를 지우고 저장 객체를 best-effort로 정리한다.

    객체가 이미 없어도(예: RustFS 교체로 원본이 소실된 좀비 업로드, #397)
    삭제는 성공한다. 진행 중(``validating``/``loading``) 업로드는 409.
    같은 checksum 재업로드의 멱등 가드(409)는 row 삭제로 풀린다.
    """
    started_at = perf_counter()
    try:
        async with session.begin():
            row = await delete_offline_upload(session, upload_id=upload_id)
            if row is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"offline upload 없음: {upload_id!r}",
                )
    except OfflineUploadStatusConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    # DB row 삭제 확정 후 객체 best-effort 삭제. S3 DeleteObject는 미존재 키에도
    # 성공(멱등)하고, 저장소 오류는 정리 lifecycle을 막지 않도록 기록만 한다.
    store = _offline_upload_store_from_request(request)
    object_deleted = True
    try:
        await store.delete_object(row.storage_key)
    except FileStoreError:
        object_deleted = False
        _LOG.warning(
            "offline upload object delete failed (best-effort): upload_id=%s, storage_key=%s",
            upload_id,
            row.storage_key,
            exc_info=True,
        )
    # 파일 registry hook (H7): 삭제 성공 → deleted, 실패 → delete_failed +
    # orphan(owner_row_deleted) — #397 zombie object를 발생 즉시 가시화한다.
    async with file_registry.registry_guard("offline-upload:delete"), session.begin():
        registered = await file_registry.register_file(
            session,
            storage_backend="s3",
            location=MANAGED_FILE_LOCATION_OFFLINE_UPLOADS,
            path=row.storage_key,
            kind="upload",
            provider=row.provider,
            dataset_key=row.dataset_key,
            byte_size=row.byte_size,
            checksum_sha256=row.checksum_sha256,
            upload_id=row.upload_id,
            event_kind=None,
            actor="api:admin",
        )
        if object_deleted:
            await file_registry.mark_deleted(
                session,
                file_id=registered.file_id,
                actor="api:admin",
                detail={"upload_id": upload_id},
            )
        else:
            await file_registry.record_event(
                session,
                file_id=registered.file_id,
                event_kind="delete_failed",
                actor="api:admin",
                detail={"upload_id": upload_id},
            )
            await file_registry.mark_orphan(
                session,
                file_id=registered.file_id,
                reason="owner_row_deleted",
                actor="api:admin",
                detail={"upload_id": upload_id},
            )
    return OfflineUploadDeleteResponse(
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
@idempotent_domain_command("admin.offline-upload.validate")
async def validate_offline_upload_request(
    upload_id: str,
    request: Request,
    request_body: OfflineUploadValidationRequest,
    context: Annotated[AdminProxyContext, Depends(require_admin_frontend)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> OfflineUploadValidationResponse:
    started_at = perf_counter()
    settings = _kor_travel_map_settings_from_request(request)
    store = _offline_upload_store_from_request(request)
    try:
        if settings.kor_travel_geo_base_url:
            async with httpx.AsyncClient(
                base_url=settings.kor_travel_geo_base_url.get_secret_value(),
                timeout=settings.kor_travel_geo_timeout_seconds,
            ) as http:
                kraddr = KorTravelGeoRestClient(
                    http,
                    api_key=settings.kor_travel_geo_api_key,
                )
                async with domain_command_transaction(session):
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
                        operator=context.actor,
                        address_resolver=kor_travel_geo_address_resolver(kraddr, fallback="api"),
                        reverse_geocoder=kor_travel_geo_reverse_geocoder(kraddr),
                    )
        else:
            async with domain_command_transaction(session):
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
                    operator=context.actor,
                )
    except HTTPException:
        raise
    except FileStoreError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
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
    _validated_graphql_url(_settings_from_request(request))
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
    except OfflineUploadStatusConflict as exc:
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
                    status="failed",
                    error_message=str(exc.detail),
                )
            await finish_offline_upload_load(session, upload_id=upload_id, status="load_failed")
        raise
    return OfflineUploadLaunchResponse(
        data=_record_from_upload(loading),
        meta=OfflineUploadLaunchMeta(
            duration_ms=max(0, int((perf_counter() - started_at) * 1000)),
            dagster_run_id=launch.run_id,
            dagster_status=launch.status,
        ),
    )
