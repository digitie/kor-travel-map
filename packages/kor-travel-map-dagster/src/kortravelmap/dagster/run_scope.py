"""Map의 Dagster run 조회를 Map의 run으로 좁힌다.

공유 Dagster plane(Manager ADR-54)에서는 daemon·run storage 하나가 여러 프로젝트의
run을 싣는다. ``instance.get_runs``·``get_run_records``·``get_run_ids``를 filter 없이
부르면 weather·PinVi·geo의 run까지 읽는다 — reconcile sensor는 남의 run을 watermark로
삼고, coalescing schedule은 남의 active run을 보고 tick을 생략한다. 그래서 인스턴스
전역 run 조회는 전부 이 모듈의 두 filter 중 하나를 거친다
(``tests/unit/test_dagster_code_location_is_one_name.py``가 강제한다).

- ``map_runs_filter``: ``dagster/code_location`` tag로 좁힌다. Dagster는 remote origin이 있는
  run(daemon·sensor·schedule·GraphQL launch — Map prod run 전부)을 만들 때 이 tag에 code
  location 이름을 단다(``RunDomain.create_run``). 2026-10-01 n150 실측: Map 전용 instance의
  run 1,825건 전부가 ``kortravelmap.dagster.definitions``를 달고 있었다. 이 filter는 배포된
  location 이름이 ``MAP_CODE_LOCATION_NAME``과 같다는 데 기댄다 — 그래서 쓰는 쪽(reconcile
  sensor)은 평가 context의 ``code_location_origin``과 대조해 다르면 실패한다.
- ``map_owned_runs_filter``: Map job이 스스로 다는 ``kor_travel_map.*`` tag로 좁힌다. location
  이름에 기대지 않는다. schedule 평가 context에는 code location이 없어 대조할 수 없으므로,
  coalescing schedule은 이것을 쓴다(2026-10-01 n150 실측: 당시 weather summary run 1,000건 전부
  ``kor_travel_map.job_kind``를 달고 있었다 — 그 schedule은 같은 날 weather 제거(ADR-105)로
  사라졌고, 지금 쓰는 쪽은 ``schedules``의 coalescing feature-load schedule이다).
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

MAP_RUN_TAG_PREFIX: Final[str] = "kor_travel_map."
"""Map만 다는 run tag의 접두사. 다른 프로젝트의 run에는 없다."""


class MapRunScopeMismatch(RuntimeError):
    """평가 중인 code location이 ``MAP_CODE_LOCATION_NAME``과 다르다.

    좁힌 조회가 조용히 0건을 돌려 아무 일도 하지 않는 대신 tick을 실패로 올린다.
    """


def require_map_code_location(location_name: str | None) -> None:
    """평가 context가 location을 알려 주면 ``MAP_CODE_LOCATION_NAME``과 같은지 본다."""

    if location_name is not None and location_name != MAP_CODE_LOCATION_NAME:
        raise MapRunScopeMismatch(
            "Dagster code location이 Map run 조회 범위와 다름: "
            f"deployed={location_name} expected={MAP_CODE_LOCATION_NAME}"
        )


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


def map_owned_runs_filter(
    *,
    tags: Mapping[str, str],
    job_name: str | None = None,
    statuses: Sequence[DagsterRunStatus] | None = None,
) -> RunsFilter:
    """Map job이 스스로 다는 ``kor_travel_map.*`` tag로 좁힌 ``RunsFilter``.

    tag가 하나도 없거나 Map 소유가 아닌 key가 섞이면 거부한다 — 그 filter는 다른 프로젝트의
    run을 고를 수 있다.
    """

    owned = dict(tags)
    if not owned or not all(key.startswith(MAP_RUN_TAG_PREFIX) for key in owned):
        raise ValueError(f"map_owned_runs_filter에는 {MAP_RUN_TAG_PREFIX}* tag만 준다")
    return RunsFilter(
        job_name=job_name,
        statuses=list(statuses) if statuses else None,
        tags=owned,
    )


__all__ = [
    "CODE_LOCATION_RUN_TAG",
    "MAP_CODE_LOCATION_NAME",
    "MAP_RUN_TAG_PREFIX",
    "MapRunScopeMismatch",
    "map_owned_runs_filter",
    "map_runs_filter",
    "require_map_code_location",
]
