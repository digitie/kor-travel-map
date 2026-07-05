"""파일 registry reconciliation scan job — dagster 소유 location (PR-D §2.2).

dagster 컨테이너가 볼 수 있는 location(MOIS 소스 sqlite, RustFS S3 버킷)과
DB-side backfill(``ops.offline_uploads`` 회수), EXTRA_ROOTS를 6시간 주기로
reconcile한다. **backup_root는 api 컨테이너만 보이므로** 이 job의 대상이 아니다 —
rescan API(``POST /v1/admin/files/rescan``)가 동기 실행한다(scanner 소유권 분리,
docs/architecture/file-registry.md).

Cadence 근거: 파일 변동은 시간 단위(백업/업로드/주간 MOIS sync)라 6시간이면
충분하고, S3 LIST·sqlite stat 비용은 무시 가능. 즉시성은 UI 재스캔 버튼.
"""

# NOTE: 이 모듈은 ``from __future__ import annotations``를 쓰지 않는다 — Dagster ``@op``는
# ``context: OpExecutionContext`` 주석을 런타임에 실제 타입으로 읽어야 하기 때문이다(문자열
# 주석이면 DagsterInvalidDefinitionError). mois_source_sync.py와 동일 제약.
from typing import Any, Final, cast

from kortravelmap.core.managed_file_states import (
    MANAGED_FILE_LOCATION_OBJECT_STORE,
    MANAGED_FILE_LOCATION_OFFLINE_UPLOADS,
)
from kortravelmap.infra.db import make_async_engine
from kortravelmap.infra.file_registry_scan import (
    ScanLocationResult,
    backfill_offline_upload_rows,
    parse_extra_roots,
    scan_extra_root,
    scan_mois_source,
    scan_s3_location,
)
from kortravelmap.infra.file_store import S3ObjectStore, build_s3_object_store
from kortravelmap.settings import KorTravelMapSettings
from sqlalchemy.ext.asyncio import AsyncSession

from dagster import (
    DefaultScheduleStatus,
    OpExecutionContext,
    RetryPolicy,
    ScheduleDefinition,
    job,
    op,
)

from .schedule_overrides import cron_for_schedule
from .schedules import KST_TIMEZONE

__all__ = [
    "FILE_REGISTRY_SCAN_JOBS",
    "FILE_REGISTRY_SCAN_SCHEDULES",
    "managed_file_scan_job",
    "scan_managed_files_op",
]

FILE_REGISTRY_SCAN_JOB_TAGS: Final[dict[str, str]] = {
    "kor_travel_map.job_scope": "maintenance",
    "kor_travel_map.job_kind": "managed_file_scan",
    "kor_travel_map.timezone": KST_TIMEZONE,
}


def _upload_store(settings: KorTravelMapSettings) -> S3ObjectStore:
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
    )


def _object_store(settings: KorTravelMapSettings) -> S3ObjectStore:
    return build_s3_object_store(
        bucket=settings.object_store_bucket,
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
    )


async def run_managed_file_scan(
    settings: KorTravelMapSettings,
    *,
    actor: str = "scan:dagster",
) -> list[ScanLocationResult]:
    """dagster-가시 location 전체 scan + DB backfill — op/테스트 공용 헬퍼."""

    results: list[ScanLocationResult] = []
    engine = make_async_engine(settings.pg_dsn)
    try:
        async with AsyncSession(engine) as session:
            # location별로 독립 커밋 — 한 location 실패가 다른 location의
            # 반영을 막지 않는다(sweep은 열거 성공 location에만 적용됨).
            async with session.begin():
                results.append(
                    await scan_mois_source(
                        session, db_path=settings.mois_source_db_path, actor=actor
                    )
                )
            try:
                async with session.begin():
                    results.append(
                        await scan_s3_location(
                            session,
                            store=_upload_store(settings),
                            location=MANAGED_FILE_LOCATION_OFFLINE_UPLOADS,
                            prefix=settings.offline_upload_prefix.strip("/") + "/",
                            actor=actor,
                        )
                    )
                async with session.begin():
                    results.append(
                        await scan_s3_location(
                            session,
                            store=_object_store(settings),
                            location=MANAGED_FILE_LOCATION_OBJECT_STORE,
                            prefix=settings.object_store_prefix.strip("/") + "/",
                            actor=actor,
                        )
                    )
            except Exception as exc:  # noqa: BLE001 — S3 불가 시 나머지 pass 유지
                results.append(
                    ScanLocationResult(
                        location="s3", details={"error": str(exc)}
                    )
                )
            async with session.begin():
                backfilled = await backfill_offline_upload_rows(
                    session, actor=actor
                )
            if backfilled:
                results.append(
                    ScanLocationResult(
                        location="db_backfill", registered=backfilled
                    )
                )
            for logical, root in parse_extra_roots(
                settings.file_registry_extra_roots
            ):
                async with session.begin():
                    results.append(
                        await scan_extra_root(
                            session, logical=logical, root=root, actor=actor
                        )
                    )
    finally:
        await engine.dispose()
    return results


@op(
    name="scan_managed_files",
    retry_policy=RetryPolicy(max_retries=1, delay=60),
    description=(
        "dagster-가시 파일 location(MOIS 소스 DB, RustFS 버킷)과 DB backfill을 "
        "reconcile한다. backup_root는 api rescan이 담당한다."
    ),
)
async def scan_managed_files_op(context: OpExecutionContext) -> dict[str, object]:
    """managed file registry scan op — 요약을 run metadata로 노출한다."""

    settings = KorTravelMapSettings()
    results = await run_managed_file_scan(settings)
    metadata: dict[str, object] = {
        result.location: cast(Any, str(result.as_dict())) for result in results
    }
    metadata["locations_scanned"] = len(results)
    context.add_output_metadata(metadata)
    return metadata


@job(
    name="managed_file_scan",
    tags=FILE_REGISTRY_SCAN_JOB_TAGS,
    description=(
        "파일 registry reconciliation scan — 등록/orphan/missing 판정 + "
        "offline-uploads DB backfill."
    ),
)
def managed_file_scan_job() -> None:
    """운영자/스케줄이 실행하는 managed file scan job."""

    scan_managed_files_op()


FILE_REGISTRY_SCAN_SCHEDULES: Final = [
    ScheduleDefinition(
        name="managed_file_scan_six_hourly_schedule",
        job=managed_file_scan_job,
        cron_schedule=cron_for_schedule(
            "managed_file_scan_six_hourly_schedule",
            "0 */6 * * *",
        ),
        execution_timezone=KST_TIMEZONE,
        default_status=DefaultScheduleStatus.STOPPED,
        tags=FILE_REGISTRY_SCAN_JOB_TAGS,
        description="파일 registry scan을 6시간 주기로 실행한다.",
    )
]
"""managed file scan schedule 목록. 운영 enable 전까지 STOPPED."""

FILE_REGISTRY_SCAN_JOBS: Final = [managed_file_scan_job]
