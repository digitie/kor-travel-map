"""Map API의 Dagster tick 조회가 **창 안에서만** storage를 읽는지 본다.

``ticks(limit: N)``에 ``afterTimestamp``가 없으면 Dagster는 instigator의 전체 tick 이력을
storage에서 읽는다. 공유 ``dagster_shared``의 ``job_ticks``가 커지자(2026-10-13 약 40만 행)
``/v1/ops/pipeline/overview`` 한 번이 cold 10초를 넘겨 ``bounded_request`` 상한에 걸렸고,
관리자 UI는 큐 sensor를 신뢰할 수 없다며 갱신 요청을 막았다(live D1 실패의 원인).

세 가지를 본다.

1. 효과: 세 문서를 이 location을 in-process로 실은 Dagster에 **실제로 실행**해 storage
   ``get_ticks``가 받는 ``after``를 기록한다. 창이 빠지면 ``after=None``이 되거나(statuses 경로)
   batch 경로로 빠져 ``get_ticks``가 아예 불리지 않으므로 둘 다 빨갛다.
2. 창의 **비용 상한** — storage 비용은 창 안의 tick 수에 비례하므로, 배포되는 Definitions의
   가장 조밀한 schedule(최단 cron 간격)·sensor(최소 간격)가 창 안에 남길 tick 수가
   ``MAX_TICKS_IN_WINDOW`` 이하여야 한다. 더 조밀한 instigator를 더하면 여기서 빨갛고, 창을
   줄이거나(주간·월간 tick이 더 자주 빈다) 상한을 근거와 함께 올리는 선택을 강제한다. sensor
   창은 가장 느린 sensor 간격의 10배 이상이어야 정상 sensor가 비지 않는다.
3. tick을 고르는 문서가 이 세 개뿐인가 — 새 문서가 생기면 여기에 더해야 1이 그것을 본다.
4. 관리자 UI의 창 표지 값이 API 창과 같은가.

dagster 비공개 경로(``instance_for_test``·``InProcessCodeLocationOrigin``·
``cron_string_iterator``)는 ``docker/constraints-dagster.txt``의 버전에서 확인했다. 올릴 때
이 파일을 함께 본다.
"""

from __future__ import annotations

import ast
import math
import re
import warnings
from collections import Counter
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
_ADMIN_FRONTEND = _ROOT / "packages" / "kor-travel-map-admin" / "frontend"
_ADMIN_WINDOW_TS = _ADMIN_FRONTEND / "src" / "lib" / "dagster-tick-window.ts"
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


_NOW = 1_800_000_000.0


@pytest.mark.parametrize("name", sorted(_DOCUMENTS))
def test_every_tick_selection_reaches_storage_with_its_own_window(
    name: str,
    dagster_process: tuple[Any, list[float | None]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """instigator 종류마다 **자기** 창이 storage에 닿는다 — 두 변수를 서로 바꿔도 빨갛다."""

    from dagster_graphql.test.utils import execute_dagster_graphql

    process, seen_after = dagster_process
    document, base, schedules, sensors = _DOCUMENTS[name]
    seen_after.clear()
    monkeypatch.setattr(dagster_graphql, "time", lambda: _NOW)
    variables = {
        **base,
        **dagster_graphql.tick_window_variables(schedules=schedules, sensors=sensors),
    }
    result = execute_dagster_graphql(process.create_request_context(), document, variables)

    assert not result.errors, result.errors
    repository = result.data["repositoryOrError"]
    assert repository["__typename"] == "Repository", repository
    expected: Counter[float | None] = Counter()
    if schedules:
        expected[_NOW - dagster_graphql.SCHEDULE_TICK_WINDOW_SECONDS] += len(
            repository["schedules"]
        )
    if sensors:
        expected[_NOW - dagster_graphql.SENSOR_TICK_WINDOW_SECONDS] += len(repository["sensors"])
    # 하한: instigator를 하나도 못 봤으면 아래 단언이 항진명제다.
    assert sum(expected.values()) > 0
    # 두 창 값이 같으면 종류를 구분하지 못한다(바꿔치기를 놓친다).
    assert (
        dagster_graphql.SCHEDULE_TICK_WINDOW_SECONDS != dagster_graphql.SENSOR_TICK_WINDOW_SECONDS
    )
    assert Counter(seen_after) == expected, (
        f"{name}: storage `get_ticks`가 받은 after {Counter(seen_after)} != 기대 {expected} "
        "(None은 창 없음, 건수 부족은 batch 경로로 빠진 것)"
    )


def _cron_gaps_seconds(cron: str, timezone: str | None) -> tuple[float, float]:
    """연속 실행 사이의 (가장 짧은, 가장 긴) 간격(초). 월간 cron은 1년치를 봐야 31일 달을 만난다."""

    from dagster._utils.schedules import cron_string_iterator

    fires = list(
        islice(
            cron_string_iterator(
                start_timestamp=_NOW, cron_string=cron, execution_timezone=timezone
            ),
            400,
        )
    )
    gaps = [(later - earlier).total_seconds() for earlier, later in pairwise(fires)]
    return min(gaps), max(gaps)


def _schedule_gaps() -> dict[str, tuple[float, float]]:
    from kortravelmap.dagster.definitions import defs

    gaps: dict[str, tuple[float, float]] = {}
    for schedule in defs.get_repository_def().schedule_defs:
        crons = (
            [schedule.cron_schedule]
            if isinstance(schedule.cron_schedule, str)
            else list(schedule.cron_schedule)
        )
        per_cron = [_cron_gaps_seconds(cron, schedule.execution_timezone) for cron in crons]
        gaps[schedule.name] = (min(g[0] for g in per_cron), max(g[1] for g in per_cron))
    assert gaps, "schedule이 하나도 없다"
    return gaps


def _sensor_intervals() -> dict[str, int]:
    from dagster._core.definitions.sensor_definition import DEFAULT_SENSOR_DAEMON_INTERVAL
    from kortravelmap.dagster.definitions import defs

    intervals = {
        sensor.name: sensor.minimum_interval_seconds or DEFAULT_SENSOR_DAEMON_INTERVAL
        for sensor in defs.get_repository_def().sensor_defs
    }
    assert intervals, "sensor가 하나도 없다"
    return intervals


def test_schedule_window_cost_is_bounded_by_the_densest_cron() -> None:
    gaps = _schedule_gaps()
    densest = min(gaps, key=lambda name: gaps[name][0])
    ticks = dagster_graphql.SCHEDULE_TICK_WINDOW_SECONDS / gaps[densest][0]
    assert ticks <= dagster_graphql.MAX_TICKS_IN_WINDOW, (
        f"{densest}(최단 간격 {gaps[densest][0]:.0f}초)가 SCHEDULE_TICK_WINDOW_SECONDS 안에 "
        f"tick {ticks:.0f}개를 남긴다 > MAX_TICKS_IN_WINDOW={dagster_graphql.MAX_TICKS_IN_WINDOW}"
    )


def test_schedule_window_covers_two_periods_of_some_schedules() -> None:
    """창이 어떤 schedule의 2주기도 못 덮으면 의미가 없다.

    나머지(주간·월간)는 관리자 UI가 "창 안 tick 없음" 표지로 보인다.
    """

    gaps = _schedule_gaps()
    covered = [
        name
        for name, (_, longest) in gaps.items()
        if longest * 2 <= dagster_graphql.SCHEDULE_TICK_WINDOW_SECONDS
    ]
    assert covered, "창이 어느 schedule의 2주기도 덮지 못한다"


def test_sensor_window_is_bounded_and_covers_ten_intervals() -> None:
    intervals = _sensor_intervals()
    window = dagster_graphql.SENSOR_TICK_WINDOW_SECONDS
    fastest = min(intervals, key=intervals.__getitem__)
    assert window / intervals[fastest] <= dagster_graphql.MAX_TICKS_IN_WINDOW, (
        f"{fastest}(최소 간격 {intervals[fastest]}초)가 SENSOR_TICK_WINDOW_SECONDS 안에 "
        f"tick {window / intervals[fastest]:.0f}개를 남긴다"
    )
    slowest = max(intervals, key=intervals.__getitem__)
    assert intervals[slowest] * 10 <= window, (
        f"{slowest}의 최소 간격 {intervals[slowest]}초 × 10 > SENSOR_TICK_WINDOW_SECONDS={window}"
    )


def test_every_tick_selecting_document_is_covered() -> None:
    """API 소스에서 ``ticks(``를 고르는 문자열 상수는 위 효과 검사가 실행하는 것뿐이다.

    ``X = "..."``뿐 아니라 ``X: Final = "..."``(AnnAssign)도 본다.
    """

    found: set[str] = set()
    for path in sorted(_API_SRC.rglob("*.py")):
        module = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(module):
            targets: list[ast.expr]
            if isinstance(node, ast.Assign):
                targets, value = list(node.targets), node.value
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                targets, value = [node.target], node.value
            else:
                continue
            if (
                isinstance(value, ast.Constant)
                and isinstance(value.value, str)
                and "ticks(" in value.value
            ):
                found.update(target.id for target in targets if isinstance(target, ast.Name))
    assert found, "tick 선택 문서를 하나도 못 찾았다 — 탐지가 깨졌다"
    assert found == set(_DOCUMENTS), found ^ set(_DOCUMENTS)


def test_admin_ui_window_labels_match_the_api_windows() -> None:
    source = _ADMIN_WINDOW_TS.read_text(encoding="utf-8")
    for name, value in (
        ("SCHEDULE_TICK_WINDOW_SECONDS", dagster_graphql.SCHEDULE_TICK_WINDOW_SECONDS),
        ("SENSOR_TICK_WINDOW_SECONDS", dagster_graphql.SENSOR_TICK_WINDOW_SECONDS),
    ):
        match = re.search(rf"export const {name} = ([0-9 *]+);", source)
        assert match is not None, f"{_ADMIN_WINDOW_TS}에 {name}이 없다"
        factors = [int(part) for part in match.group(1).split("*")]
        assert math.prod(factors) == value, (name, match.group(1), value)
    for label, seconds in (
        ("SCHEDULE_TICK_WINDOW_LABEL", dagster_graphql.SCHEDULE_TICK_WINDOW_SECONDS),
        ("SENSOR_TICK_WINDOW_LABEL", dagster_graphql.SENSOR_TICK_WINDOW_SECONDS),
    ):
        text = re.search(rf'export const {label} = "([^"]+)";', source)
        assert text is not None, label
        human = f"{seconds // 86400}일" if seconds % 86400 == 0 else f"{seconds // 3600}시간"
        assert human in text.group(1), (label, text.group(1), human)
