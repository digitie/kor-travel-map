"""Map API의 Dagster tick 조회가 **창 안에서만** storage를 읽는지 본다.

``ticks(limit: N)``에 ``afterTimestamp``가 없으면 Dagster는 instigator의 전체 tick 이력을
storage에서 읽는다. 공유 ``dagster_shared``의 ``job_ticks``가 커지자(2026-10-13 약 40만 행)
``/v1/ops/pipeline/overview`` 한 번이 cold 10초를 넘겨 ``bounded_request`` 상한에 걸렸고,
관리자 UI는 큐 sensor를 신뢰할 수 없다며 갱신 요청을 막았다(live D1 실패의 원인).

세 가지를 본다.

1. 효과: 세 문서를 이 location을 in-process로 실은 Dagster에 **실제로 실행**해 storage
   ``get_ticks``가 받는 ``after``를 기록한다. 창이 빠지면 ``after=None``이 되거나(statuses 경로)
   batch 경로로 빠져 ``get_ticks``가 아예 불리지 않으므로 둘 다 빨갛다.
2. 창이 배포되는 Definitions를 덮는가 — schedule 창 ≥ 가장 긴 cron 주기의 2배, sensor 창 ≥
   가장 느린 최소 간격의 10배. 창이 짧으면 정상 instigator가 "최근 tick 없음"으로 보인다.
3. tick을 고르는 문서가 이 세 개뿐인가 — 새 문서가 생기면 여기에 더해야 1이 그것을 본다.

dagster 비공개 경로(``instance_for_test``·``InProcessCodeLocationOrigin``·
``cron_string_iterator``)는 ``docker/constraints-dagster.txt``의 버전에서 확인했다. 올릴 때
이 파일을 함께 본다.
"""

from __future__ import annotations

import ast
import time
import warnings
from collections.abc import Callable, Iterator
from itertools import islice, pairwise
from pathlib import Path
from typing import Any

import pytest
from kortravelmap.api import dagster_graphql
from kortravelmap.api import dagster_query_service as summary_mod
from kortravelmap.api.routers import ops_pipeline as pipeline_mod

pytestmark = [
    pytest.mark.unit,
    # Definitions를 로드하면 sensor `owners`의 BetaWarning이 난다 — 루트 설정은 경고를
    # 오류로 바꾸므로 Dagster 패키지 테스트와 같은 필터를 단다.
    pytest.mark.filterwarnings(
        "ignore:Parameter `owners` of initializer `SensorDefinition.__init__`"
        ".*:dagster_shared.utils.warnings.BetaWarning"
    ),
    # in-process code location이 schedule snapshot을 만들 때 Dagster 자신이 deprecated
    # 속성을 읽는다(1.13.24). 우리 정의가 쓰는 것이 아니다 — 이 메시지 하나만 무시한다.
    pytest.mark.filterwarnings(
        "ignore:Property `ScheduleDefinition.environment_vars` is deprecated:DeprecationWarning"
    ),
]

_ROOT = Path(__file__).resolve().parents[2]
_API_SRC = _ROOT / "packages" / "kor-travel-map-api" / "src" / "kortravelmap" / "api"
_LOCATION = "kortravelmap.dagster.definitions"
_SELECTOR = {"repositoryName": "__repository__", "repositoryLocationName": _LOCATION}
_RUN_TAG = {"key": ".dagster/repository", "value": f"__repository__@{_LOCATION}"}

#: 문서 → (호출 지점이 보내는 tick 외 변수, schedule 창 사용, sensor 창 사용).
#: tick 변수는 ``tick_window_variables``가 만든다 — 호출 지점과 같은 함수다.
_DOCUMENTS: dict[str, tuple[str, dict[str, Any], bool, bool]] = {
    "_PIPELINE_OVERVIEW_QUERY": (
        pipeline_mod._PIPELINE_OVERVIEW_QUERY,
        {"limit": 5, "repositorySelector": _SELECTOR, "runsFilter": {"tags": [_RUN_TAG]}},
        False,
        True,
    ),
    "_PIPELINE_SCHEDULES_QUERY": (
        pipeline_mod._PIPELINE_SCHEDULES_QUERY,
        {"repositorySelector": _SELECTOR},
        True,
        True,
    ),
    "_DAGSTER_SUMMARY_QUERY": (
        summary_mod._DAGSTER_SUMMARY_QUERY,
        {
            "limit": 3,
            "repositorySelector": _SELECTOR,
            "runsFilter": {"tags": [_RUN_TAG]},
            "activeRunsFilter": {
                "tags": [_RUN_TAG],
                "statuses": dagster_graphql.ACTIVE_RUN_STATUSES,
            },
        },
        True,
        True,
    ),
}


@pytest.fixture(scope="module")
def dagster_process() -> Iterator[tuple[Any, list[float | None]]]:
    """Map code location을 in-process로 실은 Dagster와 ``get_ticks``의 ``after`` 기록."""

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        from dagster._core.instance_for_test import instance_for_test
        from dagster._core.remote_origin import InProcessCodeLocationOrigin
        from dagster._core.types.loadable_target_origin import LoadableTargetOrigin
        from dagster._core.workspace.context import WorkspaceProcessContext
        from dagster._core.workspace.load_target import InProcessWorkspaceLoadTarget

    seen_after: list[float | None] = []
    with instance_for_test() as instance:
        storage = instance.schedule_storage
        assert storage is not None
        real_get_ticks: Callable[..., Any] = storage.get_ticks

        def recording_get_ticks(
            origin_id: str,
            selector_id: str,
            before: float | None = None,
            after: float | None = None,
            limit: int | None = None,
            statuses: Any = None,
        ) -> Any:
            seen_after.append(after)
            return real_get_ticks(
                origin_id, selector_id, before=before, after=after, limit=limit, statuses=statuses
            )

        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(storage, "get_ticks", recording_get_ticks)
            origin = InProcessCodeLocationOrigin(
                LoadableTargetOrigin(module_name=_LOCATION), location_name=_LOCATION
            )
            with WorkspaceProcessContext(
                instance, InProcessWorkspaceLoadTarget([origin])
            ) as process:
                yield process, seen_after


@pytest.mark.parametrize("name", sorted(_DOCUMENTS))
def test_every_tick_selection_reaches_storage_with_a_window(
    name: str, dagster_process: tuple[Any, list[float | None]]
) -> None:
    from dagster_graphql.test.utils import execute_dagster_graphql

    process, seen_after = dagster_process
    document, base, schedules, sensors = _DOCUMENTS[name]
    seen_after.clear()
    started = time.time()
    variables = {
        **base,
        **dagster_graphql.tick_window_variables(schedules=schedules, sensors=sensors),
    }
    result = execute_dagster_graphql(process.create_request_context(), document, variables)
    finished = time.time()

    assert not result.errors, result.errors
    repository = result.data["repositoryOrError"]
    assert repository["__typename"] == "Repository", repository
    selected = (len(repository["schedules"]) if schedules else 0) + (
        len(repository["sensors"]) if sensors else 0
    )
    # 하한: instigator를 하나도 못 봤으면 아래 단언이 항진명제다.
    assert selected > 0
    assert len(seen_after) == selected, (
        f"{name}: tick 조회 {len(seen_after)}건이 storage `get_ticks`에 닿았다 — "
        f"instigator {selected}개 각각 창을 실어야 한다(창이 없으면 batch 경로로 빠진다)"
    )
    widest = max(
        dagster_graphql.SCHEDULE_TICK_WINDOW_SECONDS if schedules else 0,
        dagster_graphql.SENSOR_TICK_WINDOW_SECONDS if sensors else 0,
    )
    for after in seen_after:
        assert after is not None, f"{name}: tick 조회가 창 없이 storage에 닿았다"
        assert started - widest <= after <= finished


def _cron_period_seconds(cron: str, timezone: str | None) -> float:
    """연속 실행 사이의 가장 긴 간격(초) — 월간 cron은 1년치를 봐야 31일 달을 만난다."""

    from dagster._utils.schedules import cron_string_iterator

    fires = list(
        islice(
            cron_string_iterator(
                start_timestamp=time.time(), cron_string=cron, execution_timezone=timezone
            ),
            400,
        )
    )
    return max((later - earlier).total_seconds() for earlier, later in pairwise(fires))


def test_schedule_window_covers_twice_the_longest_cron_period() -> None:
    from kortravelmap.dagster.definitions import defs

    periods: dict[str, float] = {}
    for schedule in defs.get_repository_def().schedule_defs:
        crons = (
            [schedule.cron_schedule]
            if isinstance(schedule.cron_schedule, str)
            else list(schedule.cron_schedule)
        )
        periods[schedule.name] = max(
            _cron_period_seconds(cron, schedule.execution_timezone) for cron in crons
        )
    assert periods, "schedule이 하나도 없다"
    longest = max(periods, key=periods.__getitem__)
    window = dagster_graphql.SCHEDULE_TICK_WINDOW_SECONDS
    assert periods[longest] * 2 <= window, (
        f"{longest}의 주기 {periods[longest]:.0f}초 × 2 > SCHEDULE_TICK_WINDOW_SECONDS={window}"
    )


def test_sensor_window_covers_ten_sensor_intervals() -> None:
    from dagster._core.definitions.sensor_definition import DEFAULT_SENSOR_DAEMON_INTERVAL
    from kortravelmap.dagster.definitions import defs

    intervals = {
        sensor.name: sensor.minimum_interval_seconds or DEFAULT_SENSOR_DAEMON_INTERVAL
        for sensor in defs.get_repository_def().sensor_defs
    }
    assert intervals, "sensor가 하나도 없다"
    slowest = max(intervals, key=intervals.__getitem__)
    window = dagster_graphql.SENSOR_TICK_WINDOW_SECONDS
    assert intervals[slowest] * 10 <= window, (
        f"{slowest}의 최소 간격 {intervals[slowest]}초 × 10 > SENSOR_TICK_WINDOW_SECONDS={window}"
    )


def test_every_tick_selecting_document_is_covered() -> None:
    """API 소스에서 ``ticks(``를 고르는 문자열 상수는 위 효과 검사가 실행하는 것뿐이다."""

    found: set[str] = set()
    for path in sorted(_API_SRC.rglob("*.py")):
        module = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(module):
            if (
                isinstance(node, ast.Assign)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
                and "ticks(" in node.value.value
            ):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        found.add(target.id)
    assert found, "tick 선택 문서를 하나도 못 찾았다 — 탐지가 깨졌다"
    assert found == set(_DOCUMENTS), found ^ set(_DOCUMENTS)
