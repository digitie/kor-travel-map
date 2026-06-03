"""offline upload load Dagster job."""

from typing import TYPE_CHECKING, Any, Final, cast

from dagster import Failure, OpExecutionContext, job, op

if TYPE_CHECKING:
    from krtour.map.client import AsyncKrtourMapClient
    from krtour.map.offline_upload import OfflineUploadObjectStore

__all__ = [
    "OFFLINE_UPLOAD_JOBS",
    "OFFLINE_UPLOAD_LOAD_JOB_TAGS",
    "load_offline_upload_op",
    "offline_upload_load_job",
]

OFFLINE_UPLOAD_LOAD_JOB_TAGS: Final[dict[str, str]] = {
    "krtour_map.job_scope": "maintenance",
    "krtour_map.job_kind": "offline_upload_load",
}
"""offline upload load Dagster job 공통 tag."""


@op(
    name="load_offline_upload",
    required_resource_keys={"krtour_map_client", "offline_upload_store"},
    config_schema={"upload_id": str},
)
async def load_offline_upload_op(context: OpExecutionContext) -> dict[str, object]:
    """업로드 원본 파일을 FeatureBundle로 파싱해 적재한다."""
    upload_id = str(context.op_config["upload_id"])
    client = cast("AsyncKrtourMapClient", _resource_object(context, "krtour_map_client"))
    store = cast(
        "OfflineUploadObjectStore",
        _resource_object(context, "offline_upload_store"),
    )

    result = await client.run_offline_upload_load_job(
        upload_id,
        store=store,
        dagster_run_id=context.run_id,
    )
    metadata = result.as_metadata()
    context.add_output_metadata(metadata)
    if result.error_message:
        raise Failure(description=result.error_message)
    return metadata


@job(
    name="offline_upload_load",
    tags=OFFLINE_UPLOAD_LOAD_JOB_TAGS,
    description="ops.offline_uploads 원본 파일을 읽어 FeatureBundle로 적재한다.",
)
def offline_upload_load_job() -> None:
    """운영자가 Dagster UI/API에서 upload_id를 지정해 실행하는 load job."""
    load_offline_upload_op()


OFFLINE_UPLOAD_JOBS: Final = [offline_upload_load_job]


def _resource_object(context: OpExecutionContext, name: str) -> object:
    resources = cast(Any, context.resources)
    if not hasattr(resources, name):
        raise AttributeError(f"Dagster resource 없음: {name}")
    return getattr(resources, name)
