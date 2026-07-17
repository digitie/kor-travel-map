"""``/admin/files`` 관리 파일 레지스트리 라우터 (개편 D 3/4).

provider 다운로드·백업·offline 업로드·MOIS 소스 등 시스템에 적재되는 파일을
`ops.managed_files` 레지스트리로 **보고 추적**하는 읽기 위주 라우터다. 각 파일이
어디에(location/backend) 어떻게 연결됐는지(provenance links), 사용 중인지 임시인지
(status/kind), 언제 받았고 마지막으로 로드됐는지(downloaded_at/last_loaded_at)를
노출한다.

스캐너 소유권 분리(docs/architecture/file-registry.md):

* ``backup_root`` 는 **api 컨테이너만** 볼 수 있으므로 ``POST /admin/files/rescan``
  이 동기 스캔한다.
* ``mois_source`` · S3 버킷(object_store/offline_uploads 실체)은 **dagster 컨테이너**
  가 소유 — ``managed_file_scan`` job(6시간 스케줄 + 수동)이 reconcile한다. rescan은
  이 location들을 ``deferred_locations`` 로 안내한다.

물리 삭제(zombie S3 object hard-delete)는 S3 자격이 dagster 쪽에만 있으므로 여기서
하지 않는다. ``purge`` 는 좁은 gate(orphan S3 zombie)에서 레지스트리 행만
``deleted``(purged) 로 플래그하고, 실체 제거는 소유 스캐너가 reconcile한다.
"""

from __future__ import annotations

from time import perf_counter
from typing import Annotated, Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from kortravelmap.core.managed_file_states import (
    MANAGED_FILE_KIND_VALUES,
    MANAGED_FILE_LOCATION_BACKUP_ROOT,
    MANAGED_FILE_LOCATION_MOIS_SOURCE,
    MANAGED_FILE_LOCATION_OBJECT_STORE,
    MANAGED_FILE_LOCATION_OFFLINE_UPLOADS,
    MANAGED_FILE_LOCATION_VALUES,
    MANAGED_FILE_REGISTERED_BY_VALUES,
    MANAGED_FILE_STATUS_VALUES,
)
from kortravelmap.infra import file_registry
from kortravelmap.infra.file_registry_scan import (
    ScanLocationResult,
    backfill_offline_upload_rows,
    scan_backup_root,
)
from kortravelmap.settings import KorTravelMapSettings
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.api.auth import require_admin_destructive_enabled
from kortravelmap.api.db import get_session
from kortravelmap.api.response import Meta, make_meta
from kortravelmap.api.settings import ApiSettings

__all__ = [
    "router",
    "ManagedFileModel",
    "ManagedFileListResponse",
    "ManagedFileDetailResponse",
    "ManagedFileSummaryResponse",
    "ManagedFileRescanResponse",
    "ManagedFilePurgeResponse",
]

router = APIRouter(prefix="/admin/files", tags=["admin-files"])

SortField = Literal[
    "downloaded_at", "last_loaded_at", "last_seen_at", "byte_size", "updated_at"
]

# rescan이 동기 스캔할 수 있는(api-가시) location. 나머지는 dagster 소유 → deferred.
_API_SCANNABLE: frozenset[str] = frozenset({MANAGED_FILE_LOCATION_BACKUP_ROOT})
_DAGSTER_OWNED: frozenset[str] = frozenset(
    {
        MANAGED_FILE_LOCATION_MOIS_SOURCE,
        MANAGED_FILE_LOCATION_OBJECT_STORE,
        MANAGED_FILE_LOCATION_OFFLINE_UPLOADS,
    }
)

# purge 허용 orphan_reason — 소유 행이 사라진 S3 zombie만 좁게 허용.
_PURGEABLE_ORPHAN_REASONS: frozenset[str] = frozenset(
    {"zombie_object", "owner_row_deleted"}
)


# ---------------------------------------------------------------------------
# 응답 모델
# ---------------------------------------------------------------------------
class ManagedFileLink(BaseModel):
    """파일이 연결된 다른 엔티티로의 서버 조립 deep-link."""

    model_config = ConfigDict(extra="forbid")

    rel: str
    label: str
    href: str | None = None


class ManagedFileModel(BaseModel):
    """레지스트리 파일 1건 (list/detail 공용)."""

    model_config = ConfigDict(extra="forbid")

    file_id: int
    storage_backend: str
    location: str
    path: str
    is_directory: bool
    kind: str
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
    downloaded_at: str | None
    last_loaded_at: str | None
    last_seen_at: str | None
    deleted_at: str | None
    meta: dict[str, Any]
    created_at: str
    updated_at: str


class ManagedFileEventModel(BaseModel):
    """파일 생애 이벤트 1건."""

    model_config = ConfigDict(extra="forbid")

    event_id: int
    file_id: int
    event_kind: str
    occurred_at: str
    import_job_id: str | None
    dagster_run_id: str | None
    actor: str | None
    detail: dict[str, Any]


class ManagedFileListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: list[ManagedFileModel]
    meta: Meta


class ManagedFileDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file: ManagedFileModel
    links: list[ManagedFileLink]
    events: list[ManagedFileEventModel]


class ManagedFileDetailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: ManagedFileDetail
    meta: Meta


class ManagedFileEventsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: list[ManagedFileEventModel]
    meta: Meta


class SummaryBucket(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    count: int
    byte_size: int | None = None
    last_seen_at: str | None = None


class ManagedFileSummaryData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    by_kind: list[SummaryBucket]
    by_status: list[SummaryBucket]
    by_location: list[SummaryBucket]


class ManagedFileSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: ManagedFileSummaryData
    meta: Meta


class RescanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    locations: list[str] | None = Field(
        default=None,
        description=(
            "재스캔할 location 목록. 생략 시 api-가시 location(backup_root) 동기 스캔 "
            "+ DB backfill. dagster 소유 location은 deferred_locations로 안내."
        ),
    )


class RescanData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    results: list[dict[str, Any]]
    deferred_locations: list[str]
    note: str | None = None


class ManagedFileRescanResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: RescanData
    meta: Meta


class ManagedFilePurgeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: ManagedFileModel
    meta: Meta


# ---------------------------------------------------------------------------
# 매핑 헬퍼
# ---------------------------------------------------------------------------
def _settings(request: Request) -> ApiSettings:
    settings = getattr(request.app.state, "settings", None)
    return settings if isinstance(settings, ApiSettings) else ApiSettings()


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def _file_model(row: file_registry.ManagedFile) -> ManagedFileModel:
    return ManagedFileModel(
        file_id=row.file_id,
        storage_backend=row.storage_backend,
        location=row.location,
        path=row.path,
        is_directory=row.is_directory,
        kind=row.kind,
        provider=row.provider,
        dataset_key=row.dataset_key,
        status=row.status,
        orphan_reason=row.orphan_reason,
        registered_by=row.registered_by,
        byte_size=row.byte_size,
        checksum_sha256=row.checksum_sha256,
        upload_id=row.upload_id,
        origin_import_job_id=row.origin_import_job_id,
        origin_dagster_run_id=row.origin_dagster_run_id,
        downloaded_at=_iso(row.downloaded_at),
        last_loaded_at=_iso(row.last_loaded_at),
        last_seen_at=_iso(row.last_seen_at),
        deleted_at=_iso(row.deleted_at),
        meta=row.meta,
        created_at=row.created_at.isoformat(),
        updated_at=row.updated_at.isoformat(),
    )


def _event_model(row: file_registry.ManagedFileEvent) -> ManagedFileEventModel:
    return ManagedFileEventModel(
        event_id=row.event_id,
        file_id=row.file_id,
        event_kind=row.event_kind,
        occurred_at=row.occurred_at.isoformat(),
        import_job_id=row.import_job_id,
        dagster_run_id=row.dagster_run_id,
        actor=row.actor,
        detail=row.detail,
    )


def _build_links(row: file_registry.ManagedFile) -> list[ManagedFileLink]:
    """파일 → 연결 엔티티 deep-link(admin 프론트 라우트 규약). 물리적 근원을 추적."""

    links: list[ManagedFileLink] = []
    if row.origin_import_job_id:
        links.append(
            ManagedFileLink(
                rel="import-job",
                label="적재 작업",
                href=(
                    "/ops/pipeline?execution=import_job:"
                    f"{quote(str(row.origin_import_job_id), safe='')}"
                ),
            )
        )
    if row.upload_id:
        links.append(
            ManagedFileLink(
                rel="offline-upload",
                label="오프라인 업로드",
                href=f"/admin/offline-uploads/{row.upload_id}",
            )
        )
    if (
        row.location == MANAGED_FILE_LOCATION_BACKUP_ROOT
        and row.kind == "backup"
    ):
        links.append(
            ManagedFileLink(
                rel="backup",
                label="백업",
                href=f"/admin/backups/{row.path}",
            )
        )
    if row.provider:
        links.append(
            ManagedFileLink(
                rel="provider",
                label="데이터셋 상태",
                href=f"/ops/datasets?provider={quote(row.provider, safe='')}",
            )
        )
    if row.origin_dagster_run_id:
        # Dagster run은 외부 webserver — 내부 admin href를 억지로 만들지 않고
        # label만 노출(프론트가 dagster base가 있으면 링크로 승격).
        links.append(
            ManagedFileLink(
                rel="dagster-run",
                label=f"Dagster 실행 {row.origin_dagster_run_id[:12]}",
                href=None,
            )
        )
    return links


def _validate_enum(
    values: list[str] | None, allowed: tuple[str, ...], field: str
) -> list[str] | None:
    if values is None:
        return None
    unknown = [v for v in values if v not in allowed]
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"알 수 없는 {field} 값: {', '.join(unknown)}",
        )
    return values


# ---------------------------------------------------------------------------
# 라우트
# ---------------------------------------------------------------------------
@router.get("", response_model=ManagedFileListResponse)
async def list_files(
    session: Annotated[AsyncSession, Depends(get_session)],
    request: Request,
    kind: Annotated[list[str] | None, Query()] = None,
    file_status: Annotated[list[str] | None, Query(alias="status")] = None,
    provider: str | None = None,
    location: str | None = None,
    registered_by: str | None = None,
    q: str | None = None,
    min_age_days: Annotated[int | None, Query(ge=0)] = None,
    max_age_days: Annotated[int | None, Query(ge=0)] = None,
    sort: SortField = "downloaded_at",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ManagedFileListResponse:
    """레지스트리 파일 목록 — kind/status/provider/location/기간 필터 + 검색."""

    started = perf_counter()
    kinds = _validate_enum(kind, MANAGED_FILE_KIND_VALUES, "kind")
    statuses = _validate_enum(file_status, MANAGED_FILE_STATUS_VALUES, "status")
    if location is not None and location not in MANAGED_FILE_LOCATION_VALUES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"알 수 없는 location 값: {location}",
        )
    if (
        registered_by is not None
        and registered_by not in MANAGED_FILE_REGISTERED_BY_VALUES
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"알 수 없는 registered_by 값: {registered_by}",
        )

    page = await file_registry.list_managed_files(
        session,
        kinds=kinds,
        statuses=statuses,
        provider=provider,
        location=location,
        registered_by=registered_by,
        q=q,
        min_age_days=min_age_days,
        max_age_days=max_age_days,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    return ManagedFileListResponse(
        data=[_file_model(item) for item in page.items],
        meta=make_meta(
            request,
            started_at=started,
            page_size=limit,
            total=page.total_count,
        ),
    )


@router.get("/summary", response_model=ManagedFileSummaryResponse)
async def files_summary(
    session: Annotated[AsyncSession, Depends(get_session)],
    request: Request,
) -> ManagedFileSummaryResponse:
    """요약 카드 집계 — kind/status/location 별 건수·용량."""

    started = perf_counter()
    summary = await file_registry.summarize_managed_files(session)

    def _buckets(rows: list[dict[str, Any]], key_field: str) -> list[SummaryBucket]:
        out: list[SummaryBucket] = []
        for row in rows:
            out.append(
                SummaryBucket(
                    key=str(row.get(key_field, "")),
                    count=int(row.get("count", 0)),
                    byte_size=(
                        int(row["byte_size"])
                        if row.get("byte_size") is not None
                        else None
                    ),
                    last_seen_at=_iso(row.get("last_seen_at")),
                )
            )
        return out

    return ManagedFileSummaryResponse(
        data=ManagedFileSummaryData(
            by_kind=_buckets(summary.by_kind, "kind"),
            by_status=_buckets(summary.by_status, "status"),
            by_location=_buckets(summary.by_location, "location"),
        ),
        meta=make_meta(request, started_at=started),
    )


@router.get("/{file_id}", response_model=ManagedFileDetailResponse)
async def file_detail(
    file_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    request: Request,
) -> ManagedFileDetailResponse:
    """파일 상세 — provenance links + 최근 이벤트(50건)."""

    started = perf_counter()
    row = await file_registry.get_managed_file(session, file_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"파일 {file_id}를 찾을 수 없음",
        )
    events = await file_registry.list_managed_file_events(
        session, file_id=file_id, limit=50, offset=0
    )
    return ManagedFileDetailResponse(
        data=ManagedFileDetail(
            file=_file_model(row),
            links=_build_links(row),
            events=[_event_model(event) for event in events],
        ),
        meta=make_meta(request, started_at=started),
    )


@router.get("/{file_id}/events", response_model=ManagedFileEventsResponse)
async def file_events(
    file_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    request: Request,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ManagedFileEventsResponse:
    """파일 이벤트 페이지네이션."""

    started = perf_counter()
    if await file_registry.get_managed_file(session, file_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"파일 {file_id}를 찾을 수 없음",
        )
    events = await file_registry.list_managed_file_events(
        session, file_id=file_id, limit=limit, offset=offset
    )
    return ManagedFileEventsResponse(
        data=[_event_model(event) for event in events],
        meta=make_meta(request, started_at=started, page_size=limit),
    )


@router.post("/rescan", response_model=ManagedFileRescanResponse)
async def rescan_files(
    body: RescanRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    request: Request,
) -> ManagedFileRescanResponse:
    """api-가시 location(backup_root) 동기 재스캔 + DB backfill.

    dagster 소유 location(mois_source/object_store/offline_uploads 실체)은 여기서
    스캔할 수 없으므로 ``deferred_locations`` 로 안내한다 — 즉시성이 필요하면
    Dagster ``managed_file_scan`` job을 수동 실행한다(6시간 스케줄과 동일 로직).
    """

    started = perf_counter()
    requested = body.locations
    if requested is not None:
        unknown = [v for v in requested if v not in MANAGED_FILE_LOCATION_VALUES]
        if unknown:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"알 수 없는 location 값: {', '.join(unknown)}",
            )

    settings = _settings(request)
    # TTL 노브는 코어 라이브러리 설정 소관(ApiSettings에 없음) — db.py/curated.py와
    # 동일하게 KorTravelMapSettings를 직접 읽는다.
    core_settings = KorTravelMapSettings()
    results: list[ScanLocationResult] = []
    deferred: list[str] = []

    scan_backup = requested is None or MANAGED_FILE_LOCATION_BACKUP_ROOT in requested
    if scan_backup:
        async with session.begin():
            results.append(
                await scan_backup_root(
                    session,
                    backup_root=settings.backup_root,
                    e2e_backup_ttl_days=(
                        core_settings.file_registry_e2e_backup_ttl_days
                    ),
                    temp_ttl_days=core_settings.file_registry_temp_ttl_days,
                    swap_env_file=settings.backup_root / ".env.restore-swap",
                    actor="scan:api:rescan",
                )
            )

    # offline-uploads DB backfill은 순수 DB 작업이라 api도 실행 가능(실체 S3 스캔 아님).
    backfill_requested = (
        requested is None
        or MANAGED_FILE_LOCATION_OFFLINE_UPLOADS in requested
    )
    if backfill_requested:
        async with session.begin():
            backfilled = await backfill_offline_upload_rows(
                session, actor="scan:api:rescan"
            )
        if backfilled:
            results.append(
                ScanLocationResult(location="db_backfill", registered=backfilled)
            )

    # dagster 소유 실체 스캔은 api에서 불가 → deferred 안내.
    for loc in _DAGSTER_OWNED:
        if requested is None or loc in requested:
            deferred.append(loc)

    note = (
        "mois_source·S3 버킷 실체 스캔은 Dagster managed_file_scan job 소관입니다. "
        "즉시 반영이 필요하면 작업 자동화에서 수동 실행하세요."
        if deferred
        else None
    )
    return ManagedFileRescanResponse(
        data=RescanData(
            results=[r.as_dict() for r in results],
            deferred_locations=sorted(deferred),
            note=note,
        ),
        meta=make_meta(request, started_at=started),
    )


@router.post(
    "/{file_id}/purge",
    response_model=ManagedFilePurgeResponse,
    dependencies=[Depends(require_admin_destructive_enabled)],
)
async def purge_file(
    file_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    request: Request,
) -> ManagedFilePurgeResponse:
    """좁은 gate — 소유 행이 사라진 S3 zombie orphan만 레지스트리에서 purge.

    실체 S3 object hard-delete는 S3 자격이 있는 dagster 스캐너가 reconcile한다.
    여기서는 서버가 최신 상태를 재검증한 뒤 레지스트리 행을 ``deleted``(purged)로
    플래그하고 ``purged`` 이벤트를 남긴다.
    """

    started = perf_counter()
    row = await file_registry.get_managed_file(session, file_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"파일 {file_id}를 찾을 수 없음",
        )
    # 서버측 재검증 — 클라이언트가 보낸 상태가 아니라 DB 최신 상태로 gate.
    if row.storage_backend != "s3":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="purge는 S3 backend 파일에만 허용됩니다.",
        )
    if row.status != "orphan":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="purge는 orphan 상태 파일에만 허용됩니다.",
        )
    if row.orphan_reason not in _PURGEABLE_ORPHAN_REASONS:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "purge 가능한 orphan_reason이 아닙니다("
                f"허용: {', '.join(sorted(_PURGEABLE_ORPHAN_REASONS))})."
            ),
        )
    async with session.begin():
        await file_registry.mark_deleted(
            session,
            file_id=file_id,
            actor="api:admin:purge",
            detail={"reason": row.orphan_reason, "via": "admin_files.purge"},
            purged=True,
        )
    refreshed = await file_registry.get_managed_file(session, file_id)
    assert refreshed is not None  # 방금 갱신 — 존재 보장
    return ManagedFilePurgeResponse(
        data=_file_model(refreshed),
        meta=make_meta(request, started_at=started),
    )
