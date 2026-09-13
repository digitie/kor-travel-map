"""자동 적재를 끈 provider가 **큐 경로로도** 나가지 않게 한다.

2026-09-09에 사용자가 KMA·AirKorea 자동 적재를 중지시켰고 그 결정이
:data:`~.schedules.DISABLED_FEATURE_LOAD_SCHEDULES`에 기록됐다. 그런데 그 목록은
**시계만** 껐다 — `FEATURE_LOAD_SCHEDULES` 생성에서 이름을 빼는 것이 전부였다.

**이 저장소의 prod는 cron이 아니라 큐로 돈다.** schedule은 전부
`default_status=STOPPED`이고 켜진 적이 없는 반면 `feature_update_request_queue_sensor`는
기본 RUNNING이다(2026-09-14 prod 실측: instigator state 11개가 전부 센서 + 분당 job
하나). 그리고 큐 runner에는 꺼진 operation의 spec이 그대로 있었고, 실행 전 정책
게이트는 `provider_refresh_policies` row가 없으면 `allow_targeted`로 **fail-open**한다
(baseline seed에 row가 0건이다).

즉 **사용자가 끈 provider가 살아 있는 경로로 그대로 나가고 있었다.** PinVi cache
target refresh 하나가 반경 안 KMA weather feature를 잡으면 격자 순회가 나간다.

여기서 재는 것은 "목록에 이름이 있는가"가 아니라 **그 요청이 실제로 건너뛰어지는가**다.
목록만 보는 검사는 이 결함을 통과시켰을 것이다 — 목록은 처음부터 맞았고 그것을
읽는 실행 경계가 없었던 것이 결함이다.
"""

from __future__ import annotations

import asyncio
from typing import Any, cast

import pytest
from kortravelmap.infra.feature_update_executor import ProviderDatasetRefreshScope

from kortravelmap.dagster.feature_update_runner import FeatureUpdateAssetRunner
from kortravelmap.dagster.schedules import (
    DISABLED_FEATURE_LOAD_OPERATION_KEYS,
    DISABLED_FEATURE_LOAD_SCHEDULES,
    FEATURE_LOAD_SCHEDULE_SPECS,
)

pytestmark = pytest.mark.filterwarnings(
    "ignore:Parameter `owners` of initializer `SensorDefinition.__init__`"
    ".*:dagster_shared.utils.warnings.BetaWarning"
)


def _scope(operation_key: str, *, scope_type: str = "provider_dataset") -> Any:
    request_scope: dict[str, object]
    if scope_type == "provider_dataset":
        request_scope = {
            "type": "provider_dataset",
            "provider_dataset_id": 1,
            "sync_scope": "dataset_wide",
        }
    else:
        request_scope = {
            "type": "center_radius",
            "center": {"lon": 127.0, "lat": 37.0},
            "radius_km": 1.0,
        }
    return ProviderDatasetRefreshScope(
        request_id="11111111-1111-4111-8111-111111111111",
        provider_dataset_id=1,
        sync_scope="dataset_wide",
        operation_key=operation_key,
        provider="python-kma-api",
        dataset_key="kma_ultra_short_nowcast",
        scope_type=scope_type,
        request_scope=request_scope,
        update_policy={"prevent_provider_reactivation": True},
        feature_ids=("feature-1",),
        feature_count=1,
        prevent_provider_reactivation=True,
    )


def test_the_derivation_is_not_empty_and_matches_the_recorded_decision() -> None:
    """항진명제 방지 — 유도가 비면 아래 결박이 아무것도 재지 않는다."""

    assert DISABLED_FEATURE_LOAD_SCHEDULES, "끈 provider 기록이 비었다"
    assert len(DISABLED_FEATURE_LOAD_OPERATION_KEYS) == len(DISABLED_FEATURE_LOAD_SCHEDULES), (
        f"schedule {len(DISABLED_FEATURE_LOAD_SCHEDULES)}개에서 operation key "
        f"{len(DISABLED_FEATURE_LOAD_OPERATION_KEYS)}개가 나왔다 — 이름이 어긋나면 "
        "그 provider는 큐에서 막히지 않는다."
    )
    by_schedule = {spec.schedule_name: spec.job_name for spec in FEATURE_LOAD_SCHEDULE_SPECS}
    for name in DISABLED_FEATURE_LOAD_SCHEDULES:
        assert name in by_schedule, f"끈 schedule 이름이 spec에 없다: {name}"
        assert by_schedule[name] in DISABLED_FEATURE_LOAD_OPERATION_KEYS


@pytest.mark.parametrize("operation_key", sorted(DISABLED_FEATURE_LOAD_OPERATION_KEYS))
@pytest.mark.parametrize("scope_type", ["provider_dataset", "center_radius"])
def test_the_queue_skips_a_provider_whose_auto_load_is_off(
    operation_key: str, scope_type: str
) -> None:
    """끈 provider의 큐 요청은 **어느 scope로 와도** upstream을 치지 않는다.

    `spec.run`을 부르기 전에 돌려보내는지를 본다 — runner에 spec이 그대로 있으므로
    "spec이 없어서 못 돈다"가 아니라 **의도해서 건너뛴다**는 것을 재야 한다.
    """

    runner = FeatureUpdateAssetRunner(
        common_resources={},
        log=None,
        settings_factory=lambda: pytest.fail("끈 provider인데 settings를 만들었다"),
    )

    result = asyncio.run(runner(cast(Any, None), _scope(operation_key, scope_type=scope_type)))

    assert result.status == "skipped"
    assert result.metadata["skip_reason"] == "provider_auto_load_disabled", (
        f"{operation_key}({scope_type})가 건너뛰어지지 않았다 — 사용자가 끈 provider가 "
        "큐 경로로 나간다."
    )


def test_an_enabled_provider_is_not_skipped_by_this_gate() -> None:
    """대조군 — 이 게이트가 모든 것을 막아 버리면 그것도 결함이다.

    끄지 않은 operation은 이 분기를 지나야 한다. 여기서는 그 뒤의 실행이 아니라
    **이 분기가 잡지 않는다**는 것만 본다(settings 팩토리가 불리면 지난 것이다).
    """

    enabled = [
        spec.job_name
        for spec in FEATURE_LOAD_SCHEDULE_SPECS
        if spec.schedule_name not in DISABLED_FEATURE_LOAD_SCHEDULES
    ]
    assert enabled, "켜진 operation이 하나도 없다 — 대조군이 성립하지 않는다"

    reached: list[str] = []

    def _settings() -> Any:
        reached.append("yes")
        raise RuntimeError("여기까지 왔으면 이 게이트는 통과한 것이다")

    runner = FeatureUpdateAssetRunner(
        common_resources={},
        log=None,
        settings_factory=_settings,
    )
    with pytest.raises(Exception):  # noqa: B017, PT011 - 게이트 통과 여부만 본다
        asyncio.run(runner(cast(Any, None), _scope(enabled[0])))
    assert reached == ["yes"], (
        "켜진 provider가 이 게이트에 잡혔다 — 끄지 않은 것까지 막고 있다."
    )
