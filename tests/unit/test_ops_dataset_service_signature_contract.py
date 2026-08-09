"""``upsert``/``ensure`` 3종이 **같은 identity 인자 이름**을 쓰는지만 본다.

이 파일은 원래 `tests/integration/test_ops_datasets_api_projection.py`였고,
992줄짜리 datasets/pipeline REST 교차 통합 회귀였다. T-VN-33 WIP 커밋
``2e76b80c``("do not merge")가 그것을 지우고 25줄만 남겼는데, 남은 것은 DB를
전혀 건드리지 않으면서 ``@pytest.mark.integration``과 "membership을 넘긴다는
회귀"라는 docstring을 달고 있었다 — `load_datasets_grid`/`load_dataset_detail`의
projection이 전부 틀려도 초록인 테스트가 **커버된 것처럼 보이게** 했다
(9라운드 적대 리뷰 BLOCKER-1).

그래서 이름·위치·마커를 실제로 하는 일에 맞췄다. 이건 signature 계약 검사이지
통합 회귀가 아니다. 지워진 992줄의 복원은 `docs/tasks.md`가 추적한다.
"""

from __future__ import annotations

import inspect

import pytest
from kortravelmap.api import ops_dataset_service

from kortravelmap.infra import feature_operation_repo, provider_refresh_policy_repo

pytestmark = pytest.mark.unit


def test_dataset_mutation_and_operation_tracking_share_identity_argument_names() -> None:
    policy_upsert = inspect.signature(ops_dataset_service.upsert_dataset_refresh_policy)
    repository_upsert = inspect.signature(
        provider_refresh_policy_repo.upsert_provider_refresh_policy
    )
    ensure = inspect.signature(feature_operation_repo.ensure_dagster_feature_operation)

    assert "provider_dataset_id" in policy_upsert.parameters
    assert "provider_dataset_id" in repository_upsert.parameters
    assert "selected_memberships" in ensure.parameters
    assert "operation_key" in ensure.parameters
