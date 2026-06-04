"""T-200 full-load batch consistency gate Dagster job."""

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, Final, cast

from dagster import (
    Array,
    Bool,
    Failure,
    Field,
    Int,
    OpExecutionContext,
    Permissive,
    job,
    op,
)
from krtour.map.infra.batch_dag import BatchDagRunResult
from krtour.map.infra.consistency import DEDUP_PENDING_WARN_THRESHOLD

if TYPE_CHECKING:
    from krtour.map.client import AsyncKrtourMapClient

_PERMISSIVE_CONFIG = cast(Any, Permissive)

__all__ = [
    "BATCH_DAG_JOBS",
    "FULL_LOAD_BATCH_CONSISTENCY_GATE_JOB_TAGS",
    "full_load_batch_consistency_gate_job",
    "run_full_load_batch_consistency_gate_op",
]

FULL_LOAD_BATCH_CONSISTENCY_GATE_JOB_TAGS: Final[dict[str, str]] = {
    "krtour_map.job_scope": "maintenance",
    "krtour_map.job_kind": "full_load_batch_consistency_gate",
}

_BATCH_GATE_CONFIG_SCHEMA: Final[dict[str, object]] = {
    "child_job_ids": Field(
        Array(str),
        default_value=[],
        description="이미 실행된 source load import job id 목록. 모두 done이어야 gate 통과.",
    ),
    "load_batch_id": Field(
        str,
        is_required=False,
        description="외부에서 지정한 batch UUID. 없으면 krtour-map이 생성.",
    ),
    "root_kind": Field(
        str,
        default_value="full_load_batch",
        description="root import job kind.",
    ),
    "root_payload": Field(
        _PERMISSIVE_CONFIG(),
        default_value={},
        description="root import job payload에 병합할 운영 메타데이터.",
    ),
    "plan_only": Field(
        Bool,
        default_value=False,
        description="DB write 없이 child job 존재 여부만 확인.",
    ),
    "persist": Field(
        Bool,
        default_value=True,
        description="ops.feature_consistency_reports에 gate report 저장 여부.",
    ),
    "sample_limit": Field(
        Int,
        default_value=20,
        description="consistency case별 sample id 상한.",
    ),
    "dedup_pending_threshold": Field(
        Int,
        default_value=DEDUP_PENDING_WARN_THRESHOLD,
        description="F4 pending dedup backlog WARN 임계값.",
    ),
    "materialized_views": Field(
        Array(str),
        default_value=[],
        description="gate 통과 뒤 refresh할 schema.view 목록.",
    ),
    "mv_refresh_strategy": Field(
        str,
        default_value="swap",
        description="mv_refresh 전략. swap은 현재 REFRESH MATERIALIZED VIEW CONCURRENTLY로 매핑.",
    ),
}


@op(
    name="run_full_load_batch_consistency_gate",
    required_resource_keys={"krtour_map_client"},
    config_schema=_BATCH_GATE_CONFIG_SCHEMA,
)
async def run_full_load_batch_consistency_gate_op(
    context: OpExecutionContext,
) -> dict[str, object]:
    """T-200 root/child import job batch를 검증하고 consistency gate를 실행한다."""
    client = cast("AsyncKrtourMapClient", _resource_object(context, "krtour_map_client"))
    config = cast(Mapping[str, object], context.op_config)
    result = await client.run_batch_dag_consistency_gate(
        child_job_ids=_string_tuple_config(config.get("child_job_ids")),
        load_batch_id=(
            str(config["load_batch_id"]) if "load_batch_id" in config else None
        ),
        root_kind=str(config.get("root_kind", "full_load_batch")),
        root_payload=cast(Mapping[str, Any], config.get("root_payload", {})),
        dagster_run_id=context.run_id,
        plan_only=bool(config.get("plan_only", False)),
        consistency_persist=bool(config.get("persist", True)),
        sample_limit=_int_config(config.get("sample_limit"), default=20),
        dedup_pending_threshold=_int_config(
            config.get("dedup_pending_threshold"),
            default=DEDUP_PENDING_WARN_THRESHOLD,
        ),
        materialized_views=_string_tuple_config(config.get("materialized_views")),
        mv_refresh_strategy=str(config.get("mv_refresh_strategy", "swap")),
    )
    metadata = _metadata(result)
    context.add_output_metadata(metadata)
    if result.state == "failed":
        raise Failure(description=result.error_message or "batch consistency gate failed")
    return metadata


@job(
    name="full_load_batch_consistency_gate",
    tags=FULL_LOAD_BATCH_CONSISTENCY_GATE_JOB_TAGS,
    description=(
        "기존 source load import job들을 batch root 아래 묶고 consistency gate와 "
        "mv_refresh 단계를 실행한다."
    ),
)
def full_load_batch_consistency_gate_job() -> None:
    """운영자가 Dagster UI/API에서 실행하는 T-200 gate job."""
    run_full_load_batch_consistency_gate_op()


BATCH_DAG_JOBS: Final = [full_load_batch_consistency_gate_job]


def _resource_object(context: OpExecutionContext, name: str) -> object:
    resources = cast(Any, context.resources)
    if not hasattr(resources, name):
        raise AttributeError(f"Dagster resource 없음: {name}")
    return getattr(resources, name)


def _int_config(value: object, *, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        raise TypeError("정수 config에 boolean은 사용할 수 없음")
    if isinstance(value, int | str):
        return int(value)
    raise TypeError("정수 config 값이어야 함")


def _string_tuple_config(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if not isinstance(value, Sequence):
        raise TypeError("문자열 목록 config 값이어야 함")
    return tuple(str(item) for item in value if str(item))


def _metadata(result: BatchDagRunResult) -> dict[str, object]:
    return result.as_metadata()
