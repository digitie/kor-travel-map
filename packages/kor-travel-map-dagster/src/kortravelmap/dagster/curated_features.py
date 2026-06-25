"""curated_features Dagster asset group (T-223c-2).

테마형 curated overlay는 provider feature 적재 뒤 별도 배치로 갱신한다. 본 asset
group은 ① source metadata refresh ② source rule 후보화 ③ inactive/deleted feature
archive sweep ④ curated feature detail snapshot cache materialize 순서로 실행된다.
"""

# NOTE: ``from __future__ import annotations`` 금지 — Dagster가 asset 함수의
# ``context`` 어노테이션을 런타임 타입으로 검증한다(assets.py와 동일).
from typing import TYPE_CHECKING, Any, Final, cast

from dagster import (
    AssetExecutionContext,
    AssetSelection,
    DefaultScheduleStatus,
    ScheduleDefinition,
    asset,
    define_asset_job,
)

from .etl import _add_output_metadata
from .maintenance import MAINTENANCE_RETRY_POLICY
from .schedules import KST_TIMEZONE

if TYPE_CHECKING:
    from kortravelmap.client import AsyncKorTravelMapClient

__all__ = [
    "CURATED_FEATURE_ASSETS",
    "CURATED_FEATURE_JOB_TAGS",
    "CURATED_FEATURE_JOBS",
    "CURATED_FEATURE_SCHEDULES",
    "curated_feature_candidates",
    "curated_feature_status_sweep",
    "curated_features_refresh_job",
    "curated_source_metadata",
    "curated_feature_detail_snapshots",
    "run_curated_feature_candidates",
    "run_curated_feature_status_sweep",
    "run_curated_source_metadata",
    "run_curated_feature_detail_snapshots",
]

_RESOURCE_KEYS: Final[set[str]] = {"kor_travel_map_client"}
_GROUP_NAME: Final[str] = "curated_features"

CURATED_FEATURE_JOB_TAGS: Final[dict[str, str]] = {
    "kor_travel_map.job_scope": _GROUP_NAME,
    "kor_travel_map.job_kind": "curated_features_refresh",
    "kor_travel_map.timezone": KST_TIMEZONE,
}
"""curated_features Dagster job 공통 tag."""


async def run_curated_source_metadata(
    context: AssetExecutionContext,
) -> dict[str, object]:
    """curated source metadata를 source_records 기준으로 갱신한다."""

    result = await _client(context).refresh_curated_source_metadata()
    metadata = result.as_metadata()
    _add_output_metadata(context, metadata)
    return metadata


@asset(
    group_name=_GROUP_NAME,
    required_resource_keys=_RESOURCE_KEYS,
    retry_policy=MAINTENANCE_RETRY_POLICY,
)
async def curated_source_metadata(
    context: AssetExecutionContext,
) -> dict[str, object]:
    return await run_curated_source_metadata(context)


async def run_curated_feature_candidates(
    context: AssetExecutionContext,
) -> dict[str, object]:
    """enabled source rule을 적용해 curated 후보/선정 row를 갱신한다."""

    result = await _client(context).apply_curated_source_rules()
    metadata = result.as_metadata()
    _add_output_metadata(context, metadata)
    return metadata


@asset(
    group_name=_GROUP_NAME,
    required_resource_keys=_RESOURCE_KEYS,
    retry_policy=MAINTENANCE_RETRY_POLICY,
    deps=[curated_source_metadata],
)
async def curated_feature_candidates(
    context: AssetExecutionContext,
) -> dict[str, object]:
    return await run_curated_feature_candidates(context)


async def run_curated_feature_status_sweep(
    context: AssetExecutionContext,
) -> dict[str, object]:
    """inactive/deleted feature가 가리키는 curated overlay를 archive한다."""

    result = await _client(context).sweep_curated_feature_status()
    metadata = result.as_metadata()
    _add_output_metadata(context, metadata)
    return metadata


@asset(
    group_name=_GROUP_NAME,
    required_resource_keys=_RESOURCE_KEYS,
    retry_policy=MAINTENANCE_RETRY_POLICY,
    deps=[curated_feature_candidates],
)
async def curated_feature_status_sweep(
    context: AssetExecutionContext,
) -> dict[str, object]:
    return await run_curated_feature_status_sweep(context)


async def run_curated_feature_detail_snapshots(
    context: AssetExecutionContext,
) -> dict[str, object]:
    """curated feature detail snapshot cache를 materialize한다."""

    result = await _client(context).materialize_curated_feature_detail_snapshots()
    metadata = result.as_metadata()
    _add_output_metadata(context, metadata)
    return metadata


@asset(
    group_name=_GROUP_NAME,
    required_resource_keys=_RESOURCE_KEYS,
    retry_policy=MAINTENANCE_RETRY_POLICY,
    deps=[curated_feature_status_sweep],
)
async def curated_feature_detail_snapshots(
    context: AssetExecutionContext,
) -> dict[str, object]:
    return await run_curated_feature_detail_snapshots(context)


CURATED_FEATURE_ASSETS: Final = [
    curated_source_metadata,
    curated_feature_candidates,
    curated_feature_status_sweep,
    curated_feature_detail_snapshots,
]
"""curated_features asset group."""

curated_features_refresh_job = define_asset_job(
    name="curated_features_refresh",
    selection=AssetSelection.groups(_GROUP_NAME),
    tags=CURATED_FEATURE_JOB_TAGS,
    description=(
        "curated source metadata, 후보화 rule, 상태 sweep, curated feature detail snapshot "
        "cache를 순서대로 갱신한다."
    ),
)
"""운영자가 Dagster UI/API에서 실행하는 curated_features refresh asset job."""

CURATED_FEATURE_JOBS: Final = [curated_features_refresh_job]

CURATED_FEATURE_SCHEDULES: Final = [
    ScheduleDefinition(
        name="curated_features_refresh_daily_schedule",
        job=curated_features_refresh_job,
        cron_schedule="55 4 * * *",
        execution_timezone=KST_TIMEZONE,
        default_status=DefaultScheduleStatus.STOPPED,
        tags={
            **CURATED_FEATURE_JOB_TAGS,
            "kor_travel_map.schedule_scope": "system",
        },
        description=(
            "curated_features overlay와 curated feature detail snapshot cache를 일 1회 갱신한다. "
            "운영 enable 전까지 STOPPED."
        ),
    )
]
"""curated_features refresh schedule. 운영 enable 전까지 STOPPED."""


def _client(context: AssetExecutionContext) -> "AsyncKorTravelMapClient":
    resources = cast(Any, context.resources)
    if not hasattr(resources, "kor_travel_map_client"):
        raise AttributeError("Dagster resource 없음: kor_travel_map_client")
    return cast("AsyncKorTravelMapClient", resources.kor_travel_map_client)
