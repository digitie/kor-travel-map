"""``/admin/offline-uploads`` 운영 라우터 (ADR-045 T-208h).

오프라인 원본 파일을 RustFS/S3 호환 bucket에 저장하고 ``ops.offline_uploads``
메타데이터로 추적한다. 실제 FeatureBundle 적재는 Dagster
``offline_upload_load`` job을 GraphQL로 실행해 처리한다.
"""

from __future__ import annotations

import importlib
import mimetypes
from pathlib import PurePath
from time import perf_counter
from typing import Annotated, Any, Final, Literal, cast
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
from krtour.map.infra.file_store import S3ObjectStore
from krtour.map.infra.offline_upload_repo import (
    OfflineUpload,
    OfflineUploadPage,
    create_offline_upload,
    get_offline_upload,
    list_offline_uploads,
)
from krtour.map.settings import KrtourMapSettings
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from krtour.map_admin.db import get_session
from krtour.map_admin.settings import AdminSettings

__all__ = [
    "router",
    "OfflineUploadRecord",
    "OfflineUploadListResponse",
    "OfflineUploadWriteResponse",
    "OfflineUploadLaunchResponse",
]


router = APIRouter(prefix="/admin/offline-uploads", tags=["admin-offline-uploads"])

OfflineUploadState = Literal[
    "uploaded",
    "validating",
    "validated",
    "validation_failed",
    "loading",
    "loaded",
    "load_failed",
    "cancelled",
]

_LOADABLE_STATES: Final[frozenset[str]] = frozenset(
    {"uploaded", "validated", "loaded", "load_failed"}
)
_WRITEABLE_FORMATS: Final[frozenset[str]] = frozenset({"json", "jsonl"})
_DAGSTER_REPOSITORY_NAME: Final[str] = "__repository__"
_DAGSTER_REPOSITORY_LOCATION_NAME: Final[str] = "krtour.map_dagster.definitions"
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
    state: str
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
    bucket: str
    object_key: str
    content_type: str


class OfflineUploadLaunchMeta(BaseModel):
    """Dagster load 실행 응답 metadata."""

    model_config = ConfigDict(extra="forbid")

    duration_ms: int
    dagster_run_id: str
    dagster_status: str


class OfflineUploadWriteResponse(BaseModel):
    """`POST /admin/offline-uploads` 응답."""

    model_config = ConfigDict(extra="forbid")

    data: OfflineUploadRecord
    meta: OfflineUploadWriteMeta


class OfflineUploadLaunchResponse(BaseModel):
    """`POST /admin/offline-uploads/{upload_id}/load` 응답."""

    model_config = ConfigDict(extra="forbid")

    data: OfflineUploadRecord
    meta: OfflineUploadLaunchMeta


class OfflineUploadListResponse(BaseModel):
    """`GET /admin/offline-uploads` 응답."""

    model_config = ConfigDict(extra="forbid")

    count: int
    items: list[OfflineUploadRecord]
    next_cursor: str | None = None


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
        state=row.state,
        validation_job_id=row.validation_job_id,
        load_job_id=row.load_job_id,
        created_by=row.created_by,
        created_at=row.created_at.isoformat(),
        updated_at=row.updated_at.isoformat(),
        status_url=f"/admin/offline-uploads/{row.upload_id}",
        load_url=f"/admin/offline-uploads/{row.upload_id}/load",
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
        char if char.isalnum() or char in {" ", ".", "_", "-"} else "_"
        for char in raw
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
    guessed, _encoding = mimetypes.guess_type(filename)
    return guessed or "application/octet-stream"


def _storage_key(settings: KrtourMapSettings, upload_id: str, filename: str) -> str:
    prefix = settings.offline_upload_prefix.strip("/")
    if prefix:
        return f"{prefix}/{upload_id}/{filename}"
    return f"{upload_id}/{filename}"


def build_offline_upload_store(settings: KrtourMapSettings) -> S3ObjectStore:
    """admin upload API용 RustFS/S3 store를 설정에서 만든다."""
    access_key = settings.object_store_access_key_id
    secret_key = settings.object_store_secret_access_key
    if (access_key is None) != (secret_key is None):
        raise RuntimeError(
            "KRTOUR_MAP_OBJECT_STORE_ACCESS_KEY_ID와 "
            "KRTOUR_MAP_OBJECT_STORE_SECRET_ACCESS_KEY는 함께 설정해야 함."
        )

    boto3 = cast(Any, importlib.import_module("boto3"))
    botocore_config = cast(Any, importlib.import_module("botocore.config"))
    kwargs: dict[str, Any] = {
        "region_name": settings.object_store_region,
        "config": botocore_config.Config(signature_version="s3v4"),
    }
    if settings.object_store_endpoint_url:
        kwargs["endpoint_url"] = settings.object_store_endpoint_url
    if access_key is not None and secret_key is not None:
        kwargs["aws_access_key_id"] = access_key.get_secret_value()
        kwargs["aws_secret_access_key"] = secret_key.get_secret_value()

    return S3ObjectStore(
        s3_client=boto3.client("s3", **kwargs),
        bucket=settings.offline_upload_bucket,
        public_base_url=None,
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


def _launch_variables(upload_id: str) -> dict[str, object]:
    return {
        "executionParams": {
            "selector": {
                "jobName": _DAGSTER_OFFLINE_UPLOAD_JOB_NAME,
                "repositoryName": _DAGSTER_REPOSITORY_NAME,
                "repositoryLocationName": _DAGSTER_REPOSITORY_LOCATION_NAME,
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
            variables=_launch_variables(upload_id),
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
    summary="오프라인 FeatureBundle 원본 업로드",
)
async def create_offline_upload_request(
    session: Annotated[AsyncSession, Depends(get_session)],
    file: Annotated[UploadFile, File(description="JSON/JSONL FeatureBundle 파일")],
    provider: Annotated[str, Form(min_length=1)],
    dataset_key: Annotated[str, Form(min_length=1)],
    sync_scope: Annotated[str, Form(min_length=1)] = "default",
    created_by: Annotated[str | None, Form()] = None,
) -> OfflineUploadWriteResponse:
    started_at = perf_counter()
    settings = KrtourMapSettings()
    upload_id = str(uuid4())
    filename = _safe_filename(file.filename)
    detected_format = _detected_format(filename)
    if detected_format not in _WRITEABLE_FORMATS:
        raise HTTPException(
            status_code=422,
            detail="offline upload은 현재 JSON/JSONL FeatureBundle 파일만 지원합니다.",
        )
    body = await file.read()
    if not body:
        raise HTTPException(
            status_code=422,
            detail="offline upload 파일이 비어 있습니다.",
        )

    content_type = file.content_type or _content_type(filename, detected_format)
    storage_key = _storage_key(settings, upload_id, filename)
    store = build_offline_upload_store(settings)
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
            checksum_sha256=stored.checksum_sha256,
            detected_format=detected_format,
            detected_encoding="utf-8",
            created_by=created_by,
        )
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
    state: Annotated[OfflineUploadState | None, Query()] = None,
    provider: Annotated[str | None, Query()] = None,
    dataset_key: Annotated[str | None, Query()] = None,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query()] = None,
) -> OfflineUploadListResponse:
    try:
        page: OfflineUploadPage = await list_offline_uploads(
            session,
            state=state,
            provider=provider,
            dataset_key=dataset_key,
            limit=page_size,
            cursor=cursor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return OfflineUploadListResponse(
        count=len(page.items),
        items=[_record_from_upload(item) for item in page.items],
        next_cursor=page.next_cursor,
    )


@router.get(
    "/{upload_id}",
    response_model=OfflineUploadRecord,
    summary="오프라인 업로드 단건 조회",
    responses={404: {"description": "upload_id 없음"}},
)
async def get_offline_upload_request(
    upload_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> OfflineUploadRecord:
    row = await get_offline_upload(session, upload_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"offline upload 없음: {upload_id!r}",
        )
    return _record_from_upload(row)


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
    row = await get_offline_upload(session, upload_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"offline upload 없음: {upload_id!r}",
        )
    if row.state not in _LOADABLE_STATES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"load 가능한 상태가 아닙니다: {row.state}",
        )

    launch = await launch_offline_upload_load(request, upload_id)
    return OfflineUploadLaunchResponse(
        data=_record_from_upload(row),
        meta=OfflineUploadLaunchMeta(
            duration_ms=max(0, int((perf_counter() - started_at) * 1000)),
            dagster_run_id=launch.run_id,
            dagster_status=launch.status,
        ),
    )
