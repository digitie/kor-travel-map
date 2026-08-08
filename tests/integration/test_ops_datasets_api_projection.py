"""datasets/pipeline API가 canonical dataset membership을 넘긴다는 회귀."""

from __future__ import annotations

import inspect

import pytest
from kortravelmap.api import ops_dataset_service

from kortravelmap.infra import feature_operation_repo, provider_refresh_policy_repo

pytestmark = pytest.mark.integration


def test_dataset_mutation_and_operation_tracking_share_dataset_id_contract() -> None:
    policy_upsert = inspect.signature(ops_dataset_service.upsert_dataset_refresh_policy)
    repository_upsert = inspect.signature(
        provider_refresh_policy_repo.upsert_provider_refresh_policy
    )
    ensure = inspect.signature(feature_operation_repo.ensure_dagster_feature_operation)

    assert "provider_dataset_id" in policy_upsert.parameters
    assert "provider_dataset_id" in repository_upsert.parameters
    assert "selected_memberships" in ensure.parameters
    assert "operation_key" in ensure.parameters
