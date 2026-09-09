"""자동 적재를 끈 provider가 실제로 꺼져 있는지 검사한다.

## 왜

Dagster의 ``default_status=STOPPED``는 "기본값이 중지"가 아니다. UI에서 한 번 켜면
그 상태가 인스턴스에 저장되어 **배포를 넘어 살아남고**, 코드에는 그 사실이 남지
않는다. 즉 "왜 이 provider가 돌고 있지"의 답이 저장소 어디에도 없게 된다.

그래서 끄는 결정을 이름으로 적고(``DISABLED_FEATURE_LOAD_SCHEDULES``), 그 이름은
schedule 자체가 만들어지지 않게 한다 — 켤 대상이 없으면 켤 수 없다.

이 검사는 두 방향을 다 본다: 껐다고 적은 것이 정말 없는지, 그리고 목록의 이름이
**실재하는 schedule 이름인지**. 오타 하나가 "껐다고 적었는데 계속 도는" 상태를
만들고, 그건 목록이 있다는 사실 때문에 오히려 더 오래 안 보인다.
"""

from __future__ import annotations

from kortravelmap.dagster.definitions import defs
from kortravelmap.dagster.schedules import (
    DISABLED_FEATURE_LOAD_SCHEDULES,
    FEATURE_LOAD_SCHEDULE_SPECS,
    FEATURE_LOAD_SCHEDULES,
)


def test_disabled_names_are_real_schedule_names() -> None:
    declared = {spec.schedule_name for spec in FEATURE_LOAD_SCHEDULE_SPECS}
    unknown = sorted(DISABLED_FEATURE_LOAD_SCHEDULES - declared)
    assert not unknown, (
        "끈다고 적었는데 그런 schedule이 없다: "
        + ", ".join(unknown)
        + " — 오타면 그 provider는 계속 돌면서, 목록에 이름이 있다는 사실 때문에 "
        "꺼진 줄로 읽힌다."
    )


def test_disabled_schedules_are_not_built() -> None:
    built = {schedule.name for schedule in FEATURE_LOAD_SCHEDULES}
    leaked = sorted(DISABLED_FEATURE_LOAD_SCHEDULES & built)
    assert not leaked, "끈 schedule이 만들어졌다: " + ", ".join(leaked)


def test_disabled_schedules_are_absent_from_definitions() -> None:
    """code location 전체에서도 없어야 한다 — 다른 목록을 타고 들어올 수 있다."""
    exposed = {schedule.name for schedule in defs.schedules}
    leaked = sorted(DISABLED_FEATURE_LOAD_SCHEDULES & exposed)
    assert not leaked, (
        "끈 schedule이 code location에 노출됐다: "
        + ", ".join(leaked)
        + " — FEATURE_LOAD_SCHEDULES 말고 다른 경로로 들어왔다."
    )


def test_disabled_providers_keep_their_jobs() -> None:
    """시계를 끄는 것이지 능력을 끄는 것이 아니다 — 백필은 계속 가능해야 한다."""
    job_names = {job.name for job in defs.jobs}
    missing = sorted(
        spec.job_name
        for spec in FEATURE_LOAD_SCHEDULE_SPECS
        if spec.schedule_name in DISABLED_FEATURE_LOAD_SCHEDULES
        and spec.job_name not in job_names
    )
    assert not missing, (
        "끈 provider의 job까지 사라졌다: "
        + ", ".join(missing)
        + " — 일회성 재적재 수단이 없으면 끈 것을 되돌릴 방법도 없다."
    )
