"""T-VN-M05-3 — manual/provider dedup 후보 탐지 job.

계약·스키마·ACL·프로시저는 이미 배포돼 있었는데 **그것을 부르는 코드가 없었다**
(2026-09-07 실측: `feature.record_manual_provider_dedup_candidate`의 프로덕션
호출자 0건). 이 모듈이 그 호출자다.

**스케줄은 재심 차단이 켜진 뒤에 붙였다(migration 305).**
프로시저의 멱등성은 `evidence_fingerprint`가 같고 **그 case가 아직 미해결**일 때만
성립하므로, 차단이 없던 동안에는 admin이 `kept`로 판정한 쌍이 다음 실행에서 새
case로 다시 올라왔다 — 그 상태로 주기화하면 admin 큐가 쳇바퀴가 된다. 305의
`decision_fingerprint` 차단이 그것을 막고, 억눌린 수는 `suppressed_case_count`로
보고된다(`T-VN-M05-RELITIGATION` R5).

**집계는 case와 무관하게 남긴다.** 후보가 0건이어도 훑은 manual 수·provider 수·
점수 낸 쌍 수·잘림 여부를 materialization metadata로 남긴다. case에만 실으면
"후보가 없다"와 "아무것도 안 훑었다"가 같아 보인다.
"""

# NOTE: 이 모듈은 ``from __future__ import annotations``를 쓰지 않는다 — Dagster
# ``@op``는 ``context: OpExecutionContext`` 주석을 런타임에 실제 타입으로 읽어야
# 한다(문자열 주석이면 DagsterInvalidDefinitionError). file_registry_scan.py와 동일 제약.
from typing import Final

from kortravelmap.infra.db import make_async_engine, require_pg_dsn
from kortravelmap.infra.manual_provider_dedup_repo import (
    DEFAULT_BLOCK_RADIUS_METERS,
    DEFAULT_PROVIDER_BLOCK_LIMIT,
    DetectionOutcome,
    detect_manual_provider_candidates,
)
from kortravelmap.settings import KorTravelMapSettings
from sqlalchemy.ext.asyncio import AsyncSession

from dagster import (
    DefaultScheduleStatus,
    JobDefinition,
    OpExecutionContext,
    RetryPolicy,
    ScheduleDefinition,
    job,
    op,
)

from .schedule_overrides import cron_for_schedule
from .schedules import KST_TIMEZONE

__all__ = [
    "MANUAL_PROVIDER_DEDUP_JOBS",
    "MANUAL_PROVIDER_DEDUP_SCHEDULES",
    "detect_manual_provider_dedup_candidates_op",
    "manual_provider_dedup_detection_job",
    "run_manual_provider_dedup_detection",
]

MANUAL_PROVIDER_DEDUP_JOB_TAGS: Final[dict[str, str]] = {
    "kor_travel_map/domain": "m05-manual-provider-dedup",
}


async def run_manual_provider_dedup_detection(
    settings: KorTravelMapSettings,
    *,
    run_id: str,
    radius_meters: float = DEFAULT_BLOCK_RADIUS_METERS,
    block_limit: int = DEFAULT_PROVIDER_BLOCK_LIMIT,
) -> DetectionOutcome:
    """탐지 1회 — op/테스트 공용 헬퍼.

    프로시저가 READ COMMITTED를 요구하므로(격리 수준을 올리면
    `ck_m05_detector_isolation`으로 거부한다) 기본 격리 수준을 바꾸지 않는다.
    """

    engine = make_async_engine(require_pg_dsn(settings))
    try:
        # **런 전체를 한 트랜잭션으로 묶지 않는다.** 후보 기록 프로시저가 호출마다
        # xact-scoped advisory fence(`feature-curation-m05`)를 잡으므로, 하나로 묶으면
        # 첫 후보에서 잡은 fence가 런 끝까지 유지돼 admin의 판정 경로가 막힌다.
        # 탐지기가 case 단위로 커밋한다. READ COMMITTED라 하나로 묶어도 읽기 일관성
        # 이득은 애초에 없었다.
        async with AsyncSession(engine) as session:
            outcome = await detect_manual_provider_candidates(
                session,
                run_id=run_id,
                radius_meters=radius_meters,
                block_limit=block_limit,
            )
            await session.commit()
            return outcome
    finally:
        await engine.dispose()


@op(
    name="detect_manual_provider_dedup_candidates",
    retry_policy=RetryPolicy(max_retries=1, delay=60),
    description=(
        "manual origin Feature와 provider Feature를 따로 읽어 THRESHOLD_MANUAL "
        "이상 쌍을 candidate로만 기록한다. 자동 병합하지 않는다."
    ),
)
async def detect_manual_provider_dedup_candidates_op(
    context: OpExecutionContext,
) -> dict[str, object]:
    """탐지 op — 훑은 범위를 case 유무와 무관하게 metadata로 노출한다."""

    settings = KorTravelMapSettings()
    outcome = await run_manual_provider_dedup_detection(
        settings, run_id=context.run_id
    )
    metadata: dict[str, object] = {
        "manual_input_count": outcome.manual_input_count,
        "provider_input_count": outcome.provider_input_count,
        "scored_pair_count": outcome.scored_pair_count,
        "created_case_count": len(outcome.created_case_ids),
        "idempotent_case_count": len(outcome.idempotent_case_ids),
        # admin이 이미 판정해 억눌린 쌍. 세지 않으면 "후보가 없다"와
        # "이미 판정됐다"가 같아 보인다(T-VN-M05-RELITIGATION R1).
        "suppressed_case_count": len(outcome.suppressed_case_ids),
        "incomplete_block_count": len(outcome.incomplete_blocks),
        "raced_pair_count": outcome.raced_pair_count,
        "manual_scan_truncated": outcome.manual_scan_truncated,
        # 이 한 값이 "후보가 이게 전부다"라고 말할 수 있는지를 정한다.
        "complete_set": outcome.complete_set,
    }
    context.add_output_metadata(metadata)
    return metadata


@job(
    name="manual_provider_dedup_detection",
    tags=MANUAL_PROVIDER_DEDUP_JOB_TAGS,
    description=(
        "manual/provider dedup 후보 탐지. 자동 병합하지 않고 후보로만 올린다. "
        "admin이 판정한 쌍은 migration 305의 재심 차단이 막고, 억눌린 수는 "
        "suppressed_case_count로 보고된다."
    ),
)
def manual_provider_dedup_detection_job() -> None:
    """운영자가 실행하는 M05 후보 탐지 job."""

    detect_manual_provider_dedup_candidates_op()


MANUAL_PROVIDER_DEDUP_JOBS: Final[list[JobDefinition]] = [
    manual_provider_dedup_detection_job
]

#: 하루 한 번이면 충분하다 — 후보는 provider 적재와 수동 생성이 만들고 둘 다
#: 분 단위로 쏟아지지 않는다. 기본 상태는 `STOPPED`다(저장소의 다른 스케줄과 같다):
#: 운영자가 켜는 행위가 곧 "이 환경에서 M05 판정을 받겠다"는 선언이다.
MANUAL_PROVIDER_DEDUP_SCHEDULES: Final[list[ScheduleDefinition]] = [
    ScheduleDefinition(
        name="manual_provider_dedup_detection_daily_schedule",
        job=manual_provider_dedup_detection_job,
        cron_schedule=cron_for_schedule(
            "manual_provider_dedup_detection_daily_schedule",
            "20 4 * * *",
        ),
        execution_timezone=KST_TIMEZONE,
        default_status=DefaultScheduleStatus.STOPPED,
        tags=MANUAL_PROVIDER_DEDUP_JOB_TAGS,
        description="manual/provider dedup 후보 탐지를 매일 04:20 KST에 실행한다.",
    )
]
