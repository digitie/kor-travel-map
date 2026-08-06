"""Feature load definition이 DB operation-key 경계만 가진다는 회귀."""

from __future__ import annotations

from kortravelmap.dagster.schedules import (
    FEATURE_LOAD_JOBS,
    FEATURE_LOAD_SCHEDULE_SPECS,
    FEATURE_LOAD_SCHEDULES,
)


def test_every_feature_definition_uses_its_job_name_as_operation_key() -> None:
    assert len(FEATURE_LOAD_SCHEDULE_SPECS) == len(FEATURE_LOAD_JOBS)
    assert len(FEATURE_LOAD_JOBS) == len(FEATURE_LOAD_SCHEDULES)
    assert len({spec.job_name for spec in FEATURE_LOAD_SCHEDULE_SPECS}) == len(
        FEATURE_LOAD_SCHEDULE_SPECS
    )

    for spec, job, schedule in zip(
        FEATURE_LOAD_SCHEDULE_SPECS,
        FEATURE_LOAD_JOBS,
        FEATURE_LOAD_SCHEDULES,
        strict=True,
    ):
        assert job.name == spec.job_name
        assert job.tags["kor_travel_map.operation_key"] == spec.job_name
        assert schedule.tags["kor_travel_map.operation_key"] == spec.job_name
        assert schedule.tags["kor_travel_map.trigger_kind"] == "schedule"


def test_definition_tags_do_not_embed_provider_dataset_membership() -> None:
    for job, schedule in zip(FEATURE_LOAD_JOBS, FEATURE_LOAD_SCHEDULES, strict=True):
        assert set(job.tags).issuperset({"kor_travel_map.operation_key"})
        assert set(schedule.tags).issuperset(
            {"kor_travel_map.operation_key", "kor_travel_map.trigger_kind"}
        )
        assert not any("provider" in key or "dataset" in key for key in job.tags)
        assert not any("provider" in key or "dataset" in key for key in schedule.tags)
