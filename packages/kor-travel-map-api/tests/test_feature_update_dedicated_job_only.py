"""MOIS 같은 전용 job 전용 operation만 담은 큐 요청은 접수 시점에 거부한다 (ADR-108)."""

from __future__ import annotations

import pytest
from kortravelmap.core.feature_operation import DEDICATED_JOB_ONLY_OPERATION_KEYS
from kortravelmap.infra.feature_update_repo import FeatureUpdateRequestDataset

from kortravelmap.api import feature_update_service
from kortravelmap.api.feature_update_http import to_http_exception


def _member(provider_dataset_id: int, operation_key: str) -> FeatureUpdateRequestDataset:
    return FeatureUpdateRequestDataset(
        feature_update_request_dataset_id=None,
        provider_dataset_id=provider_dataset_id,
        sync_scope="dataset_wide",
        provider="python-mois-api",
        dataset_key="mois_license_features_bulk",
        operation_key=operation_key,
    )


_MOIS_JOB = next(iter(sorted(DEDICATED_JOB_ONLY_OPERATION_KEYS)))


def test_plan_of_only_dedicated_job_operations_is_rejected_with_a_409_naming_the_job() -> None:
    with pytest.raises(feature_update_service.FeatureUpdateDedicatedJobOnly) as caught:
        feature_update_service._reject_dedicated_job_only_plan(  # noqa: SLF001
            (_member(1, _MOIS_JOB),)
        )

    http = to_http_exception(caught.value)
    assert http.status_code == 409
    assert isinstance(http.detail, dict)
    assert http.detail["code"] == "PROVIDER_DEDICATED_JOB_ONLY"
    assert http.detail["details"] == {"dagster_jobs": [_MOIS_JOB]}


@pytest.mark.parametrize(
    "members",
    [
        (),
        ((1, "feature_place_khoa_beaches_job"),),
        ((1, _MOIS_JOB), (2, "feature_place_khoa_beaches_job")),
    ],
    ids=["empty", "other-only", "mixed"],
)
def test_other_and_mixed_plans_are_accepted(members: tuple[tuple[int, str], ...]) -> None:
    """섞인 계획은 받는다 — MOIS 부분은 실행기가 건너뛰고 terminal 상세에 남긴다."""
    feature_update_service._reject_dedicated_job_only_plan(  # noqa: SLF001
        tuple(_member(dataset_id, key) for dataset_id, key in members)
    )
