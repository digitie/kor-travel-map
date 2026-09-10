"""Feature load definition이 DB operation-key 경계만 가진다는 회귀."""

from __future__ import annotations

from kortravelmap.dagster.schedules import (
    DISABLED_FEATURE_LOAD_SCHEDULES,
    FEATURE_LOAD_JOBS,
    FEATURE_LOAD_SCHEDULE_SPECS,
    FEATURE_LOAD_SCHEDULES,
)


def test_every_feature_definition_uses_its_job_name_as_operation_key() -> None:
    # 시계를 끈 provider는 schedule이 만들어지지 않는다
    # (`DISABLED_FEATURE_LOAD_SCHEDULES`). **job은 남는다** — 끄는 것은 시계이지
    # 능력이 아니므로 job 쪽 단언은 spec 전량을 그대로 본다.
    assert len(FEATURE_LOAD_SCHEDULE_SPECS) == len(FEATURE_LOAD_JOBS)
    scheduled = [
        spec
        for spec in FEATURE_LOAD_SCHEDULE_SPECS
        if spec.schedule_name not in DISABLED_FEATURE_LOAD_SCHEDULES
    ]
    assert len(scheduled) == len(FEATURE_LOAD_SCHEDULES)
    assert len(scheduled) < len(FEATURE_LOAD_SCHEDULE_SPECS), (
        "끈 목록이 비었다 — 이 분기가 공회전한다."
    )
    assert len({spec.job_name for spec in FEATURE_LOAD_SCHEDULE_SPECS}) == len(
        FEATURE_LOAD_SCHEDULE_SPECS
    )

    for spec, job in zip(FEATURE_LOAD_SCHEDULE_SPECS, FEATURE_LOAD_JOBS, strict=True):
        assert job.name == spec.job_name
        assert job.tags["kor_travel_map.operation_key"] == spec.job_name

    for spec, schedule in zip(scheduled, FEATURE_LOAD_SCHEDULES, strict=True):
        assert schedule.tags["kor_travel_map.operation_key"] == spec.job_name
        assert schedule.tags["kor_travel_map.trigger_kind"] == "schedule"


def test_definition_tags_do_not_embed_provider_dataset_membership() -> None:
    for job in FEATURE_LOAD_JOBS:
        assert set(job.tags).issuperset({"kor_travel_map.operation_key"})
        assert not any("provider" in key or "dataset" in key for key in job.tags)
    for schedule in FEATURE_LOAD_SCHEDULES:
        assert set(schedule.tags).issuperset(
            {"kor_travel_map.operation_key", "kor_travel_map.trigger_kind"}
        )
        assert not any("provider" in key or "dataset" in key for key in schedule.tags)
