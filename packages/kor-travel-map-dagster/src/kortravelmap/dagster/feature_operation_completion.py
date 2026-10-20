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
from kortravelmap.infra.transaction_limits import connection_check_interval

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

_CONNECTION_CHECK_SECONDS: Final[int] = 10
"""sweep 트랜잭션의 ``client_connection_check_interval``(초)."""

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
    """active root를 한 바퀴 훑어 SUCCESS run의 root를 완결하고 완결한 수를 돌려준다.

    root 하나의 완결 실패는 run을 FAILURE로 만들지 않는다. 고칠 수 없는 root 하나가 SUCCESS run마다
    FAILURE run을 쌓아 진짜 실패를 묻지 않게 하기 위해서다. 실패는 root마다 error 로그와 output
    metadata(`failed_run_ids`)에 남고, 그 root는 active로 남아 다음 sweep이 다시 시도한다.
    멈춤 알림은 ADR-112 결정 3의 몫이다. 목록 조회 자체가 실패하면 run을 실패시킨다.
    """
    client = cast("AsyncKorTravelMapClient", context.resources.kor_travel_map_client)
    try:
        completed, failed = await sweep_succeeded_feature_operations(
            context.instance, client, context.log
        )
    except _SweepListUnavailable as exc:
        raise Failure(description=str(exc)) from None
    context.add_output_metadata(
        {"completed": completed, "failed": len(failed), "failed_run_ids": ", ".join(failed[:20])}
    )
    return completed


class _SweepListUnavailable(RuntimeError):
    """active root 목록을 읽지 못했다(원문 없이 오류 종류만 싣는다)."""


async def sweep_succeeded_feature_operations(
    instance: Any,
    client: "AsyncKorTravelMapClient",
    log: Any,
) -> tuple[int, list[str]]:
    """active root 목록을 끝까지 한 번 훑는다. (완결한 root 수, 실패한 run id)를 돌려준다.

    한 root의 실패는 다음 root를 막지 않는다. 실패한 root는 active로 남아 다음 sweep이 다시 집는다.
    ``applied``만 완결로 센다(경쟁으로 이미 끝났거나 막힌 root는 세지 않는다).
    """
    # 순환 import 회피: sensor 모듈이 이 job을 요청 대상으로 import한다.
    from .feature_operation_sensors import _classify_failure, apply_completion_record

    # 이 run이 죽으면(worker kill·OOM) 들고 있던 완결 CALL은 서버가 ~10초 안에 스스로 취소한다 —
    # lineage lock을 statement_timeout(600초)까지 붙들지 않는다(geo #591과 같은 자리).
    with connection_check_interval(_CONNECTION_CHECK_SECONDS):
        return await _sweep(instance, client, log, apply_completion_record, _classify_failure)


async def _sweep(
    instance: Any,
    client: "AsyncKorTravelMapClient",
    log: Any,
    apply_completion_record: Any,
    classify_failure: Any,
) -> tuple[int, list[str]]:
    completed = 0
    failed: list[str] = []
    cursor = None
    while True:
        try:
            page = await client.list_reconcilable_dagster_feature_runs(
                cursor=cursor, page_size=FEATURE_OPERATION_COMPLETION_PAGE_SIZE
            )
        except Exception as exc:
            # 원문은 남기지 않는다(DSN·SQL 조각이 섞일 수 있다).
            raise _SweepListUnavailable(
                f"active root 목록 조회 실패: error_type={type(exc).__name__}"
            ) from None
        for operation in page.items:
            run_id = operation.dagster_run_id
            try:
                record = instance.get_run_record_by_id(run_id)
                if record is None or record.dagster_run.status != DagsterRunStatus.SUCCESS:
                    continue
                outcome = await apply_completion_record(record, client)
            except Exception as exc:
                failed.append(run_id)
                # gate 바쁨(55P03 + 표지)과 lock 대기를 가른 분류를 남긴다(ADR-112 결정 5).
                category = classify_failure(exc, at_head=False)["category"]
                log.error(
                    f"operation root 완결 실패: run_id={run_id} "
                    f"error_type={type(exc).__name__} category={category}"
                )
                continue
            if outcome == "applied":
                completed += 1
            log.info(f"operation root 완결 시도: run_id={run_id} outcome={outcome}")
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
