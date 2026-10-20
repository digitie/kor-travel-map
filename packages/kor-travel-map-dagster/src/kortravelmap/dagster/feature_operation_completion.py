"""Dagster SUCCESS run의 root 완결을 sensor tick 밖에서 하는 job (ADR-112 결정 0-1).

sensor는 SUCCESS run에 ensure만 하고, root 완결(``reconcile_dagster_feature_run`` 안의
``CALL feature.finalize_provider_curation_root``)은 이 job의 run이 한다. 이 run은 sensor 평가
timeout(60초)에 묶이지 않는다.

run 하나는 **sweep 한 번**이다. reconcile sensor의 DB page와 같은 목록(active, 취소 marker·
quarantine 없음)을 처음부터 끝까지 훑고, Dagster run이 SUCCESS인 root를 하나씩 완결한다. 반영
함수는 sensor가 FAILURE·CANCELED에 쓰는 것과 같다
(``feature_operation_sensors.apply_completion_record``).
완결은 어차피 lineage lock 하나로 직렬화되므로 run도 pool 하나로 한 번에 하나만 돈다 — 여분의
요청은 QUEUED로 기다렸다가 할 일이 없으면 바로 끝난다.

이 run은 ``kor_travel_map.operation_key`` tag를 달지 않는다. 그래서 상태 sensor와 reconcile
sensor는 이 run 자체를 ``panel_only``로 본다. 자동 재시도는 두지 않는다 — 실패한 root는 active로
남고 다음 sweep이 다시 집는다.
"""

# ``from __future__ import annotations``를 쓰지 않는다 — Dagster가 op의 ``context`` 주석을
# 실제 타입으로 검사하므로 문자열 주석이면 정의 시점에 거부한다(maintenance.py와 같다).
from typing import TYPE_CHECKING, Any, Final, cast

from kortravelcommon.dagster import RecoveryPolicy

from dagster import DagsterRunStatus, Failure, OpExecutionContext, job, op

from .assets import MAP_POOL_PREFIX

if TYPE_CHECKING:
    from kortravelmap.client import AsyncKorTravelMapClient

__all__ = [
    "FEATURE_OPERATION_COMPLETION_JOBS",
    "FEATURE_OPERATION_COMPLETION_JOB_NAME",
    "FEATURE_OPERATION_COMPLETION_PAGE_SIZE",
    "FEATURE_OPERATION_COMPLETION_POOL",
    "complete_succeeded_feature_operations_op",
    "feature_operation_completion_job",
    "sweep_succeeded_feature_operations",
]

FEATURE_OPERATION_COMPLETION_JOB_NAME: Final[str] = "feature_operation_completion"
"""SUCCESS run의 root 완결 sweep job."""

FEATURE_OPERATION_COMPLETION_POOL: Final[str] = f"{MAP_POOL_PREFIX}feature_operation_completion"
"""completion run을 인스턴스 전역에서 하나씩 돌리는 pool(``concurrency.pools.default_limit: 1``)."""

FEATURE_OPERATION_COMPLETION_PAGE_SIZE: Final[int] = 200
"""sweep이 active root 목록을 읽는 page 크기(reconcile sensor DB page와 같다)."""

_COMPLETION_MAX_RUNTIME_SECONDS: Final[int] = 3_600
"""run 상한. 완결 하나는 statement timeout(600초) 안에 끝나야 한다. 넘기면 run monitoring이
슬롯을 돌려주고, 남은 root는 다음 sweep이 다시 집는다."""


@op(
    name="complete_succeeded_feature_operations",
    required_resource_keys={"kor_travel_map_client"},
    pool=FEATURE_OPERATION_COMPLETION_POOL,
    description="Dagster SUCCESS인데 아직 active인 operation root를 하나씩 완결한다.",
)
async def complete_succeeded_feature_operations_op(context: OpExecutionContext) -> int:
    """active root를 한 바퀴 훑어 SUCCESS run의 root를 완결하고 완결한 수를 돌려준다."""
    client = cast("AsyncKorTravelMapClient", context.resources.kor_travel_map_client)
    completed, failed = await sweep_succeeded_feature_operations(
        context.instance, client, context.log
    )
    if failed:
        raise Failure(
            description=(
                f"operation root 완결 {len(failed)}건 실패(다음 sweep에 다시 시도): "
                + ", ".join(failed[:10])
            )
        )
    return completed


async def sweep_succeeded_feature_operations(
    instance: Any,
    client: "AsyncKorTravelMapClient",
    log: Any,
) -> tuple[int, list[str]]:
    """active root 목록을 끝까지 한 번 훑는다. (완결한 수, 실패한 run id)를 돌려준다.

    한 root의 실패는 다음 root를 막지 않는다. 실패한 root는 active로 남아 다음 sweep이 다시 집는다.
    """
    # 순환 import 회피: sensor 모듈이 이 job을 요청 대상으로 import한다.
    from .feature_operation_sensors import apply_completion_record

    completed = 0
    failed: list[str] = []
    cursor = None
    while True:
        page = await client.list_reconcilable_dagster_feature_runs(
            cursor=cursor, page_size=FEATURE_OPERATION_COMPLETION_PAGE_SIZE
        )
        for operation in page.items:
            run_id = operation.dagster_run_id
            try:
                record = instance.get_run_record_by_id(run_id)
                if record is None or record.dagster_run.status != DagsterRunStatus.SUCCESS:
                    continue
                outcome = await apply_completion_record(record, client)
            except Exception as exc:
                # 원문은 남기지 않는다(DSN·SQL 조각이 섞일 수 있다).
                failed.append(run_id)
                log.error(
                    f"operation root 완결 실패: run_id={run_id} "
                    f"error_type={type(exc).__name__}"
                )
                continue
            completed += 1
            log.info(f"operation root 완결: run_id={run_id} outcome={outcome}")
        if page.next_cursor is None:
            break
        cursor = page.next_cursor
    return completed, failed


@job(
    name=FEATURE_OPERATION_COMPLETION_JOB_NAME,
    tags={
        **RecoveryPolicy(max_runtime_seconds=_COMPLETION_MAX_RUNTIME_SECONDS).tags(
            project="map", job_name=FEATURE_OPERATION_COMPLETION_JOB_NAME
        ),
        "kor_travel_map.job_scope": "maintenance",
        "kor_travel_map.job_kind": "feature_operation_completion",
    },
)
def feature_operation_completion_job() -> None:
    """run 하나가 완결 대기 root 전체를 한 번 훑는다."""
    complete_succeeded_feature_operations_op()


FEATURE_OPERATION_COMPLETION_JOBS: Final = [feature_operation_completion_job]
"""root 완결 job 목록(definitions가 등록한다)."""
