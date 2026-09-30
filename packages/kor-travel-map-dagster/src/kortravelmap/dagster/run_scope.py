"""Map의 Dagster run 조회를 Map code location으로 좁힌다.

공유 Dagster plane(Manager ADR-54)에서는 daemon·run storage 하나가 여러 프로젝트의
run을 싣는다. ``instance.get_runs``·``get_run_records``·``get_run_ids``를 filter 없이
부르면 weather·PinVi·geo의 run까지 읽는다 — reconcile sensor는 남의 run을 watermark로
삼고, coalescing schedule은 남의 active run을 보고 tick을 생략한다. 그래서 인스턴스
전역 run 조회는 전부 이 모듈의 filter를 거친다(``tests/unit/test_dagster_code_location_is_one_name.py``
가 강제한다).

좁히는 손잡이는 ``dagster/code_location`` tag다. Dagster는 remote origin이 있는 run
(daemon·sensor·schedule·GraphQL launch — Map prod run 전부)을 만들 때 이 tag에 code
location 이름을 단다(``RunDomain.create_run``). 2026-10-01 n150 실측: Map 전용 instance의
run 1,825건 전부가 ``kortravelmap.dagster.definitions``를 달고 있었다 — 오늘 배포에서도
결과가 바뀌지 않는다.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Final

from dagster import DagsterRunStatus, RunsFilter

MAP_CODE_LOCATION_NAME: Final[str] = "kortravelmap.dagster.definitions"
"""Map의 Dagster code location 이름. ``docker/workspace.yaml``의 ``location_name``이 정본이다
(``tests/unit/test_dagster_code_location_is_one_name.py``가 결박)."""

CODE_LOCATION_RUN_TAG: Final[str] = "dagster/code_location"
"""Dagster ``CODE_LOCATION_TAG``. 공개 이름이 없어 문자열로 두고 테스트가 설치본과 대조한다."""


def map_runs_filter(
    *,
    job_name: str | None = None,
    statuses: Sequence[DagsterRunStatus] | None = None,
    tags: Mapping[str, str] | None = None,
) -> RunsFilter:
    """Map code location의 run만 고르는 ``RunsFilter``.

    호출자의 ``tags``와 AND로 합친다. 호출자가 location tag를 직접 넘기면 거부한다 —
    다른 location을 가리키게 덮어쓰는 길을 남기지 않는다.
    """

    extra = dict(tags or {})
    if CODE_LOCATION_RUN_TAG in extra:
        raise ValueError(f"{CODE_LOCATION_RUN_TAG}는 map_runs_filter가 정한다")
    return RunsFilter(
        job_name=job_name,
        statuses=list(statuses) if statuses else None,
        tags={**extra, CODE_LOCATION_RUN_TAG: MAP_CODE_LOCATION_NAME},
    )


__all__ = ["CODE_LOCATION_RUN_TAG", "MAP_CODE_LOCATION_NAME", "map_runs_filter"]
