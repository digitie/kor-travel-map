"""run 완주 게이트의 탐침 job — **아무것도 하지 않고 끝나는 run 하나**.

``scripts/dagster_run_completion_gate.py``는 배포된 세대가 run을 실제로 완주시키는지 재려고
매번 새 run을 하나 띄워 ``SUCCESS``를 기다린다. 그 run이 무엇을 하느냐는 게이트의 질문이
아니다. 질문은 "launch → 큐 → run launcher → run worker → step 실행 → 종결 이벤트 기록"이라는
**경로**가 살아 있는가이고, 그 경로는 job 내용과 무관하다.

그래서 탐침은 일을 하지 않는 job이어야 한다. 종전 탐침들은 그렇지 않았다.

- ``current_weather_summary_refresh`` — DB에 summary를 쓰는 분당 job. ADR-105로 사라졌다.
- ``cache_target_snapshot_gc`` — prod에서 한 번도 돈 적 없는 GC다. 첫 실행이 최대 2,000 batch의
  backlog를 지울 수 있다. 게이트를 돌리는 것이 파괴적 정리를 시작시키고, 600초 탐침 상한을
  넘겨 "run이 안 끝난다"는 거짓 red를 낼 수 있다(2026-10-02 적대 리뷰 지적).

**이 job의 부작용이 없는 이유.**

- Map resource를 하나도 요구하지 않는다(op 출력 때문에 Dagster 기본 ``io_manager``만 요구한다).
  Dagster는 run이 요구하는 resource만 초기화하므로
  ``kor_travel_map_client``·provider record resource·geo client는 이 run에서 만들어지지 않는다.
  DB connection도, upstream 호출도 생길 자리가 없다.
- op 모듈은 ``dagster``와 표준 라이브러리 typing 외에 아무것도 import하지 않는다 — Map의
  infra·provider 코드에 닿을 이름이 이 모듈에 없다.
- run config가 없다. 게이트는 config 없이 launch한다.
- ``kor_travel_map.operation_key`` tag가 없다. 그래서 feature operation 상태 sensor와 reconcile
  sensor는 이 run을 ``panel_only``로 보고 ``ops.import_jobs``에 행을 만들지 않는다
  (``feature_operation_sensors._apply_run_record``). coalescing schedule은 operation key로
  좁히므로 이 run을 세지 않는다.
- pool을 선언하지 않는다. pool에 넣으면 탐침이 몇 시간짜리 적재 뒤에 줄을 서서 "run 경로"가
  아니라 "pool이 비었는가"를 재게 된다.
- retry policy가 없다. 재시도는 실패를 늦게, 혹은 초록으로 보이게 만든다 — 탐침은 정직하게
  한 번에 실패해야 한다.

남는 쓰기는 Dagster 자신의 것뿐이다. run·event log 행(metadata DB)과, op 출력 하나가 기본
``io_manager``(filesystem)를 거쳐 ``local_artifact_storage`` 아래에 남는 작은 pickle이다. 뒤의
것은 의도다 — 2026-09-11 사고는 바로 그 로컬 쓰기 자리가 봉인된 ``DAGSTER_HOME``으로 가서 모든
run이 실패한 것이었다. 탐침이 그 자리에 실제로 한 번 쓰고 끝나야 그 축이 실측된다.

이 성질은 ``tests/lint/test_run_completion_gate_measures_what_it_claims.py``가 게이트의 기본
탐침 이름에서 출발해 Definitions의 job을 풀어 결박한다(이름이 아니라 성질).
"""

# ``from __future__ import annotations``를 쓰지 않는다 — Dagster가 op의 ``context`` 주석을
# 실제 타입으로 검사하므로 문자열 주석이면 정의 시점에 거부한다(maintenance.py와 같다).
from typing import Final

from dagster import MAX_RUNTIME_SECONDS_TAG, OpExecutionContext, job, op

__all__ = [
    "RUN_HEARTBEAT_JOBS",
    "RUN_HEARTBEAT_JOB_NAME",
    "RUN_HEARTBEAT_JOB_TAGS",
    "emit_run_heartbeat_op",
    "run_heartbeat_job",
]

RUN_HEARTBEAT_JOB_NAME: Final[str] = "map_run_heartbeat"
"""게이트(``scripts/dagster_run_completion_gate.py``)의 기본 탐침 job 이름."""

#: 회수 상한. 이 run은 수 초면 끝난다 — 5분을 넘겨 STARTED로 남아 있으면 그것 자체가 고장이고,
#: ``run_monitoring``이 전역 6시간이 아니라 이 상한으로 슬롯을 돌려준다.
_RUN_HEARTBEAT_MAX_RUNTIME_SECONDS: Final[int] = 300

RUN_HEARTBEAT_JOB_TAGS: Final[dict[str, str]] = {
    "kor_travel_map.job_scope": "maintenance",
    "kor_travel_map.job_kind": "run_heartbeat",
    MAX_RUNTIME_SECONDS_TAG: str(_RUN_HEARTBEAT_MAX_RUNTIME_SECONDS),
}
"""탐침 job tag. ``kor_travel_map.operation_key``를 일부러 달지 않는다(모듈 docstring)."""


@op(
    name="emit_run_heartbeat",
    description="아무것도 읽거나 쓰지 않고 run id만 출력한다 — run 실행 경로 탐침.",
)
def emit_run_heartbeat_op(context: OpExecutionContext) -> dict[str, str]:
    """run 경로가 step 실행과 출력 기록까지 닿았음을 남긴다."""
    context.log.info("run heartbeat: run_id=%s", context.run_id)
    return {"run_id": context.run_id}


@job(
    name=RUN_HEARTBEAT_JOB_NAME,
    tags=RUN_HEARTBEAT_JOB_TAGS,
    description=(
        "run 완주 게이트 탐침. resource·run config·upstream 호출·DB 쓰기 없이 수 초 안에 "
        "끝나며, launch부터 종결 이벤트까지 run 실행 경로만 지난다. schedule이 없다."
    ),
)
def run_heartbeat_job() -> None:
    """``scripts/dagster_run_completion_gate.py``가 GraphQL로 띄우는 탐침 job."""
    emit_run_heartbeat_op()


RUN_HEARTBEAT_JOBS: Final = [run_heartbeat_job]
"""Definitions에 싣는 탐침 job 목록. schedule은 없다 — 게이트가 필요할 때만 띄운다."""
