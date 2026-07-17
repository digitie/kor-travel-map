"""datasets와 pipeline REST의 canonical operation 교차 통합 회귀."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

import httpx
import pytest
from kortravelmap.api.app import create_app
from kortravelmap.api.auth import ADMIN_ACTOR_HEADER, ADMIN_PROXY_SECRET_HEADER
from kortravelmap.api.db import get_session
from kortravelmap.api.ops_dataset_preview import DatasetPreviewResult
from kortravelmap.api.settings import ApiSettings
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from kortravelmap.core.feature_operation import (
    DagsterFeatureOperationMutation,
    ProviderDatasetOperationKey,
)
from kortravelmap.infra.feature_operation_repo import ensure_dagster_feature_operation
from kortravelmap.infra.feature_update_repo import enqueue_feature_update_request
from kortravelmap.infra.provider_refresh_policy_repo import (
    upsert_provider_refresh_policy,
)
from kortravelmap.infra.sync_state_repo import record_sync_success
from kortravelmap.providers.feature_operation_registry import (
    feature_operation_launch_tags,
    resolve_feature_operation_launch,
)
from kortravelmap.providers.mois import (
    DATASET_KEY_BULK,
    DATASET_KEY_HISTORY,
    PROVIDER_NAME,
)
from tests.integration._db_cleanup import truncate_committed_test_rows

pytestmark = pytest.mark.integration

_PAGE_SIZE = 10
_SCHEDULE_JOB_NAME = "feature_place_mois_licenses_job"
_SCHEDULE_NAME = "feature_place_mois_licenses_monthly_schedule"
_SCHEDULE_TICK = 2_000_000_000.0
_PROXY_SECRET = "c3e-c-rest-proof-secret"
_OPERATOR = "integration-test"
_CLEANUP_SQL = """
TRUNCATE
    provider_sync.provider_sync_state,
    ops.provider_refresh_policies,
    ops.pipeline_cancellation_members,
    ops.pipeline_cancellation_runs,
    ops.feature_update_requests,
    ops.import_job_events,
    ops.import_jobs,
    ops.pipeline_cancellations
RESTART IDENTITY CASCADE
"""


@dataclass(frozen=True)
class _ExpectedOperation:
    kind: str
    id: str
    provider: str
    dataset_key: str
    sync_scope: str | None
    status: str
    created_at: datetime
    started_at: datetime | None
    dagster_run_id: str | None
    dagster_run_status: str | None
    trigger_kind: str
    registry_version: str | None
    operation_member_id: str
    pair_status: str
    progress: int | None
    current_stage: str | None
    scope_type: str | None
    priority: int | None
    run_mode: str | None
    operator: str | None
    requested_job_id: str | None
    linked_job_count: int
    projected_id: str
    projected_kind: str
    projected_status: str
    projected_progress: int
    projected_stage: str | None
    projected_created_at: datetime
    projected_started_at: datetime | None
    projected_dagster_run_id: str | None
    projected_dagster_run_status: str | None
    projected_trigger_kind: str
    projected_registry_version: str | None

    @property
    def key(self) -> tuple[str, str]:
        return self.kind, self.id


@dataclass(frozen=True)
class _SeedState:
    target_operations: tuple[_ExpectedOperation, ...]
    update_job_id: str
    decoy_root_id: str
    decoy_member_ids: tuple[str, ...]
    orphan_operation: _ExpectedOperation
    orphan_provider: str
    orphan_dataset_key: str


def _timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _assert_timestamp(actual: str | None, expected: datetime | None) -> None:
    if expected is None:
        assert actual is None
    else:
        assert actual is not None
        assert _timestamp(actual) == expected


def _expected_order(
    operations: Sequence[_ExpectedOperation],
) -> list[_ExpectedOperation]:
    return sorted(
        operations,
        key=lambda item: (item.created_at, UUID(item.id), item.kind),
        reverse=True,
    )


def _assert_common_projection(
    item: dict[str, Any],
    expected: _ExpectedOperation,
) -> None:
    assert (item["kind"], item["id"]) == expected.key
    assert item["detail_url"] == (
        f"/v1/ops/pipeline/executions/{expected.kind}/{expected.id}"
    )
    assert item["status"] == expected.status
    assert item["providers"] == [expected.provider]
    assert item["dataset_keys"] == [expected.dataset_key]
    assert len(item["providers"]) == 1
    assert len(item["dataset_keys"]) == 1
    assert item["provider_datasets"] == [
        {
            "provider": expected.provider,
            "dataset_key": expected.dataset_key,
            "sync_scope": expected.sync_scope,
            "operation_member_id": expected.operation_member_id,
            "status": expected.pair_status,
        }
    ]
    assert item["dagster_run_id"] == expected.dagster_run_id
    assert item["dagster_run_status"] == expected.dagster_run_status
    assert item["trigger_kind"] == expected.trigger_kind
    assert item["operation_registry_version"] == expected.registry_version
    assert item["finished_at"] is None
    assert item["error_message"] is None
    assert item["cancellation"] is None
    _assert_timestamp(item["created_at"], expected.created_at)
    _assert_timestamp(item["started_at"], expected.started_at)

    projected = item["projected_job"]
    assert projected["id"] == expected.projected_id
    assert projected["job_kind"] == expected.projected_kind
    assert projected["status"] == expected.projected_status
    assert projected["progress"] == expected.projected_progress
    assert projected["current_stage"] == expected.projected_stage
    assert projected["error_message"] is None
    assert projected["finished_at"] is None
    assert projected["dagster_run_id"] == expected.projected_dagster_run_id
    assert (
        projected["dagster_run_status"]
        == expected.projected_dagster_run_status
    )
    assert projected["trigger_kind"] == expected.projected_trigger_kind
    assert (
        projected["operation_registry_version"]
        == expected.projected_registry_version
    )
    assert projected["depth"] == 0
    assert projected["detail_url"] == (
        f"/v1/ops/pipeline/executions/import_job/{expected.projected_id}"
    )
    _assert_timestamp(projected["created_at"], expected.projected_created_at)
    _assert_timestamp(projected["started_at"], expected.projected_started_at)


def _assert_dataset_projection(
    item: dict[str, Any],
    expected: _ExpectedOperation,
) -> None:
    _assert_common_projection(item, expected)
    assert item["pair_status"] == expected.pair_status
    assert item["operation_member_id"] == expected.operation_member_id


def _assert_pipeline_projection(
    item: dict[str, Any],
    expected: _ExpectedOperation,
) -> None:
    _assert_common_projection(item, expected)
    assert item["progress"] == expected.progress
    assert item["current_stage"] == expected.current_stage
    assert item["scope_type"] == expected.scope_type
    assert item["priority"] == expected.priority
    assert item["run_mode"] == expected.run_mode
    assert item["operator"] == expected.operator
    assert item["requested_job_id"] == expected.requested_job_id
    assert item["linked_job_count"] == expected.linked_job_count
    assert item["projected_job"]["load_batch_id"] is None
    assert item["projected_job"]["parent_job_id"] is None


def _feature_expectation(
    mutation: DagsterFeatureOperationMutation,
    *,
    pair: ProviderDatasetOperationKey,
    run_id: str,
    engine_created_at: datetime,
    registry_version: str,
) -> _ExpectedOperation:
    operation = mutation.operation
    assert mutation.outcome == "applied"
    assert mutation.block_reason is None
    assert operation.dagster_run_id == run_id
    assert operation.status == "running"
    assert operation.dagster_run_status == "STARTED"
    assert operation.progress == 0
    assert operation.current_stage == "loading"
    assert operation.created_at == engine_created_at
    assert operation.started_at == engine_created_at
    assert operation.finished_at is None
    assert operation.trigger_kind == "manual"
    assert operation.registry_version == registry_version
    assert len(operation.members) == 1
    member = operation.members[0]
    assert member.pair == pair
    assert member.status == "running"
    assert member.progress == 0
    assert member.current_stage == "loading"
    assert member.started_at == engine_created_at
    assert member.finished_at is None
    return _ExpectedOperation(
        kind="import_job",
        id=operation.root_job_id,
        provider=pair.provider,
        dataset_key=pair.dataset_key,
        sync_scope=None,
        status="running",
        created_at=engine_created_at,
        started_at=engine_created_at,
        dagster_run_id=run_id,
        dagster_run_status="STARTED",
        trigger_kind="manual",
        registry_version=registry_version,
        operation_member_id=member.job_id,
        pair_status="running",
        progress=0,
        current_stage="loading",
        scope_type=None,
        priority=None,
        run_mode=None,
        operator=None,
        requested_job_id=None,
        linked_job_count=2,
        projected_id=operation.root_job_id,
        projected_kind="provider_feature_load_run",
        projected_status="running",
        projected_progress=0,
        projected_stage="loading",
        projected_created_at=engine_created_at,
        projected_started_at=engine_created_at,
        projected_dagster_run_id=run_id,
        projected_dagster_run_status="STARTED",
        projected_trigger_kind="manual",
        projected_registry_version=registry_version,
    )


async def _seed_committed_operations(engine: AsyncEngine) -> _SeedState:
    pair = ProviderDatasetOperationKey(PROVIDER_NAME, DATASET_KEY_BULK)
    token = uuid4().hex
    registry_version = f"c3e-c-rest-proof-{token}"
    target_operations: list[_ExpectedOperation] = []

    async with (
        AsyncSession(engine, expire_on_commit=False) as session,
        session.begin(),
    ):
        update_request = await enqueue_feature_update_request(
            session,
            scope={
                "type": "provider_dataset",
                "provider": pair.provider,
                "dataset_key": pair.dataset_key,
            },
            effective_sync_scope="dataset_wide",
            operator=_OPERATOR,
            reason="canonical REST projection proof",
        )
        target_operations.append(
            _ExpectedOperation(
                kind="update_request",
                id=update_request.request_id,
                provider=pair.provider,
                dataset_key=pair.dataset_key,
                sync_scope="dataset_wide",
                status="queued",
                created_at=update_request.created_at,
                started_at=None,
                dagster_run_id=None,
                dagster_run_status=None,
                trigger_kind="update_request",
                registry_version=None,
                operation_member_id=update_request.job_id,
                pair_status="queued",
                progress=None,
                current_stage=None,
                scope_type="provider_dataset",
                priority=50,
                run_mode="queued",
                operator=_OPERATOR,
                requested_job_id=update_request.job_id,
                linked_job_count=1,
                projected_id=update_request.job_id,
                projected_kind="feature_update_request",
                projected_status="queued",
                projected_progress=0,
                projected_stage=None,
                projected_created_at=update_request.created_at,
                projected_started_at=None,
                projected_dagster_run_id=None,
                projected_dagster_run_status=None,
                projected_trigger_kind="update_request",
                projected_registry_version=None,
            )
        )

        # 같은 created_at 동률을 포함해 detail 고정 10개보다 많은 11개 root를 만든다.
        offsets_us = (4, 4, 3, 3, 2, 1, -1, -1, -2, -3, -4)
        for index, offset_us in enumerate(offsets_us):
            created_at = update_request.created_at + timedelta(
                microseconds=offset_us
            )
            run_id = f"c3e-c-rest-proof-{token}-{index}"
            mutation = await ensure_dagster_feature_operation(
                session,
                dagster_run_id=run_id,
                trigger_kind="manual",
                selected_pairs=(pair,),
                registry_version=registry_version,
                engine_created_at=created_at,
                engine_started_at=created_at,
                observed_status="STARTED",
            )
            target_operations.append(
                _feature_expectation(
                    mutation,
                    pair=pair,
                    run_id=run_id,
                    engine_created_at=created_at,
                    registry_version=registry_version,
                )
            )

        orphan_provider = f"c3e/고립 provider+&=#{token[:8]}"
        orphan_dataset_key = f"예약/데이터?+&=%-{token[:8]}"
        orphan_pair = ProviderDatasetOperationKey(
            orphan_provider, orphan_dataset_key
        )
        await record_sync_success(
            session,
            provider=orphan_provider,
            dataset_key=orphan_dataset_key,
            cursor={"proof": token},
        )
        orphan_created_at = update_request.created_at + timedelta(microseconds=30)
        orphan_run_id = f"c3e-c-rest-proof-{token}-orphan"
        orphan_mutation = await ensure_dagster_feature_operation(
            session,
            dagster_run_id=orphan_run_id,
            trigger_kind="manual",
            selected_pairs=(orphan_pair,),
            registry_version=registry_version,
            engine_created_at=orphan_created_at,
            engine_started_at=orphan_created_at,
            observed_status="STARTED",
        )
        orphan_operation = _feature_expectation(
            orphan_mutation,
            pair=orphan_pair,
            run_id=orphan_run_id,
            engine_created_at=orphan_created_at,
            registry_version=registry_version,
        )

        # provider와 dataset이 각각 다른 member에만 존재하는 cross-product decoy다.
        # exact pair AND가 깨지면 target filter에 잘못 포함된다.
        decoy = await ensure_dagster_feature_operation(
            session,
            dagster_run_id=f"c3e-c-rest-proof-{token}-decoy",
            trigger_kind="manual",
            selected_pairs=(
                ProviderDatasetOperationKey(PROVIDER_NAME, DATASET_KEY_HISTORY),
                ProviderDatasetOperationKey(
                    f"c3e-c-decoy-provider-{token}", DATASET_KEY_BULK
                ),
            ),
            registry_version=registry_version,
            engine_created_at=(
                update_request.created_at + timedelta(microseconds=20)
            ),
            engine_started_at=(
                update_request.created_at + timedelta(microseconds=20)
            ),
            observed_status="STARTED",
        )
        await session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))

        root_ids = {item.id for item in target_operations}
        member_ids = {item.operation_member_id for item in target_operations}
        decoy_member_ids = tuple(
            member.job_id for member in decoy.operation.members
        )
        assert len(root_ids) == 12
        assert len(member_ids) == 12
        assert root_ids.isdisjoint(member_ids)
        assert orphan_operation.id not in root_ids | member_ids
        assert orphan_operation.operation_member_id not in root_ids | member_ids
        assert orphan_operation.id != orphan_operation.operation_member_id
        canonical_ids = root_ids | member_ids | {
            orphan_operation.id,
            orphan_operation.operation_member_id,
        }
        assert len(canonical_ids) == 26
        assert decoy.operation.root_job_id not in canonical_ids
        assert len(decoy_member_ids) == 2
        assert len(set(decoy_member_ids)) == 2
        assert decoy.operation.root_job_id not in decoy_member_ids
        assert set(decoy_member_ids).isdisjoint(canonical_ids)
        assert update_request.request_id != update_request.job_id
        return _SeedState(
            target_operations=tuple(target_operations),
            update_job_id=update_request.job_id,
            decoy_root_id=decoy.operation.root_job_id,
            decoy_member_ids=decoy_member_ids,
            orphan_operation=orphan_operation,
            orphan_provider=orphan_provider,
            orphan_dataset_key=orphan_dataset_key,
        )


async def _cleanup_committed_operations(engine: AsyncEngine) -> None:
    """append-only 행은 저장소 integration 관례의 TRUNCATE로 별도 commit 정리한다."""
    async with AsyncSession(engine) as session, session.begin():
        await truncate_committed_test_rows(session, _CLEANUP_SQL)
        await session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


def _schedule_payload() -> dict[str, Any]:
    launch = resolve_feature_operation_launch(job_name=_SCHEDULE_JOB_NAME)
    assert launch is not None
    identity, _ = launch
    schedule_tags = {
        **feature_operation_launch_tags(identity, trigger_kind="schedule"),
        "kor_travel_map.timezone": "Asia/Seoul",
    }
    return {
        "data": {
            "repositoriesOrError": {
                "__typename": "RepositoryConnection",
                "nodes": [
                    {
                        "schedules": [
                            {
                                "name": _SCHEDULE_NAME,
                                "pipelineName": _SCHEDULE_JOB_NAME,
                                "tags": [
                                    {"key": key, "value": value}
                                    for key, value in sorted(
                                        schedule_tags.items()
                                    )
                                ],
                                "scheduleState": {"status": "RUNNING"},
                                "futureTicks": {
                                    "results": [{"timestamp": _SCHEDULE_TICK}]
                                },
                            }
                        ]
                    }
                ],
            }
        }
    }


def _assert_schedule(summary: dict[str, Any]) -> None:
    assert summary["source"] == "dagster_graphql"
    assert summary["basis"] == "dagster_definition_tags"
    assert summary["status"] == "RUNNING"
    assert summary["schedule_names"] == [_SCHEDULE_NAME]
    assert summary["active_schedule_names"] == [_SCHEDULE_NAME]
    assert _timestamp(summary["next_scheduled_at"]) == datetime.fromtimestamp(
        _SCHEDULE_TICK, tz=UTC
    )


async def test_datasets_and_pipeline_rest_share_committed_canonical_operations(
    migrated_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_sessions: list[AsyncSession] = []

    async def _request_session() -> AsyncIterator[AsyncSession]:
        async with AsyncSession(
            migrated_engine, expire_on_commit=False
        ) as session:
            request_sessions.append(session)
            yield session

    schedule_requests: list[httpx.Request] = []

    def _dagster_schedule(request: httpx.Request) -> httpx.Response:
        schedule_requests.append(request)
        assert request.method == "POST"
        assert request.url.path == "/graphql"
        assert b"KorTravelMapDatasetSchedules" in request.content
        return httpx.Response(200, json=_schedule_payload())

    app = create_app(
        ApiSettings(
            _env_file=None,
            debug_routes_enabled=False,
            features_routes_enabled=False,
            admin_routes_enabled=False,
            ops_routes_enabled=True,
            api_call_log_enabled=False,
            prometheus_metrics_enabled=False,
            admin_proxy_secret=SecretStr(_PROXY_SECRET),
            admin_trusted_proxy_cidrs=["127.0.0.1/32"],
            dagster_url="http://127.0.0.1:12702",
            dagster_graphql_url=None,
            dagster_allowed_hosts=["127.0.0.1"],
        )
    )
    app.dependency_overrides[get_session] = _request_session
    auth_headers = {
        ADMIN_ACTOR_HEADER: "admin:integration-test",
        ADMIN_PROXY_SECRET_HEADER: _PROXY_SECRET,
    }

    # seed commit 자체를 포함해 이후 예외·취소는 같은 finally 정리 경계에 둔다.
    try:
        seed = await _seed_committed_operations(migrated_engine)

        from kortravelmap.api import ops_dataset_service as dataset_service
        from kortravelmap.api.routers import ops_datasets as datasets_router

        preview_calls: list[tuple[str, str, int]] = []

        def _preview_catalog(provider: str, dataset_key: str) -> object:
            assert provider == seed.orphan_provider
            assert dataset_key == seed.orphan_dataset_key
            return SimpleNamespace(preview="fixture")

        async def _preview_fixture(
            provider: str,
            dataset_key: str,
            *,
            max_items: int,
        ) -> DatasetPreviewResult:
            preview_calls.append((provider, dataset_key, max_items))
            return DatasetPreviewResult(
                provider=provider,
                dataset=dataset_key,
                variant="slash-query-proof",
                description="주입한 fixture 실행 경계의 query identity 증거",
                items=(
                    {
                        "provider": provider,
                        "dataset_key": dataset_key,
                    },
                ),
                total_items=1,
                max_items=max_items,
            )

        monkeypatch.setattr(
            datasets_router, "find_catalog_entry", _preview_catalog
        )
        monkeypatch.setattr(
            datasets_router,
            "run_dataset_fixture_preview",
            _preview_fixture,
        )

        policy_provider = f"{seed.orphan_provider}/policy+&=#"
        policy_dataset_key = f"{seed.orphan_dataset_key}/policy?+&=%"
        original_find_catalog_entry = dataset_service.find_catalog_entry

        def _policy_catalog(provider: str, dataset_key: str) -> object | None:
            if (provider, dataset_key) == (
                policy_provider,
                policy_dataset_key,
            ):
                return SimpleNamespace()
            return original_find_catalog_entry(provider, dataset_key)

        monkeypatch.setattr(
            dataset_service, "find_catalog_entry", _policy_catalog
        )

        async with AsyncSession(migrated_engine) as policy_seed, policy_seed.begin():
            await upsert_provider_refresh_policy(
                policy_seed,
                provider=policy_provider,
                dataset_key=policy_dataset_key,
                source_kind="manual",
                rate_limit_source={"proof": "server-provider-contract"},
            )

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(_dagster_schedule),
        ) as dagster_client:
            app.state.dagster_http_client = dagster_client
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(
                    app=app,
                    client=("127.0.0.1", 43123),
                ),
                base_url="http://testserver",
            ) as client:
                denied_response = await client.get("/v1/ops/datasets")
                grid_response = await client.get(
                    "/v1/ops/datasets", headers=auth_headers
                )
                detail_response = await client.get(
                    "/v1/ops/datasets/detail",
                    headers=auth_headers,
                    params={
                        "provider": PROVIDER_NAME,
                        "dataset_key": DATASET_KEY_BULK,
                        "sync_scope": "default",
                    },
                )
                pipeline_first_response = await client.get(
                    "/v1/ops/pipeline/executions",
                    headers=auth_headers,
                    params={
                        "provider": PROVIDER_NAME,
                        "dataset_key": DATASET_KEY_BULK,
                        "sync_scope": "default",
                        "page_size": _PAGE_SIZE,
                    },
                )
                legacy_detail_response = await client.get(
                    "/v1/ops/datasets/legacy/removed",
                    headers=auth_headers,
                )
                legacy_preview_response = await client.post(
                    "/v1/ops/datasets/legacy/removed/preview",
                    headers=auth_headers,
                    json={"source": "fixture", "max_items": 1},
                )
                legacy_policy_response = await client.put(
                    "/v1/ops/datasets/legacy/removed/refresh-policy",
                    headers=auth_headers,
                    json={"source_kind": "manual"},
                )
                preview_response = await client.post(
                    "/v1/ops/datasets/preview",
                    headers=auth_headers,
                    params={
                        "provider": seed.orphan_provider,
                        "dataset_key": seed.orphan_dataset_key,
                    },
                    json={"source": "fixture", "max_items": 1},
                )
                policy_response = await client.put(
                    "/v1/ops/datasets/refresh-policy",
                    headers=auth_headers,
                    params={
                        "provider": policy_provider,
                        "dataset_key": policy_dataset_key,
                    },
                    json={
                        "source_kind": "manual",
                        "targeted_policy": "allow_targeted",
                        "stale_after_minutes": 137,
                        "max_concurrent": 3,
                        "config_source": "c3e-c-integration",
                        "enabled": False,
                    },
                )

                assert denied_response.status_code == 403
                assert legacy_detail_response.status_code == 404
                assert legacy_preview_response.status_code == 404
                assert legacy_policy_response.status_code == 404
                for response in (
                    grid_response,
                    detail_response,
                    pipeline_first_response,
                    preview_response,
                    policy_response,
                ):
                    assert response.status_code == 200, response.text

                preview_request_query = parse_qs(
                    preview_response.request.url.query.decode(),
                    strict_parsing=True,
                )
                assert preview_request_query == {
                    "provider": [seed.orphan_provider],
                    "dataset_key": [seed.orphan_dataset_key],
                }
                assert preview_calls == [
                    (
                        seed.orphan_provider,
                        seed.orphan_dataset_key,
                        1,
                    )
                ]
                preview_data = preview_response.json()["data"]
                assert preview_data["provider"] == seed.orphan_provider
                assert preview_data["dataset_key"] == seed.orphan_dataset_key
                assert preview_data["items"] == [
                    {
                        "provider": seed.orphan_provider,
                        "dataset_key": seed.orphan_dataset_key,
                    }
                ]

                policy_request_query = parse_qs(
                    policy_response.request.url.query.decode(),
                    strict_parsing=True,
                )
                assert policy_request_query == {
                    "provider": [policy_provider],
                    "dataset_key": [policy_dataset_key],
                }
                policy_data = policy_response.json()["data"]
                assert policy_data["provider"] == policy_provider
                assert policy_data["dataset_key"] == policy_dataset_key
                assert policy_data["source_kind"] == "manual"
                assert policy_data["targeted_policy"] == "allow_targeted"
                assert policy_data["stale_after_minutes"] == 137
                assert policy_data["max_concurrent"] == 3
                assert policy_data["rate_limit_source"] == {
                    "proof": "server-provider-contract"
                }
                assert policy_data["config_source"] == "c3e-c-integration"
                assert policy_data["enabled"] is False

                async with AsyncSession(migrated_engine) as verify_session:
                    saved_policy = (
                        await verify_session.execute(
                            text(
                                """
                                SELECT provider, dataset_key, source_kind,
                                       targeted_policy, stale_after_minutes,
                                       max_concurrent, rate_limit_source,
                                       config_source, enabled
                                FROM ops.provider_refresh_policies
                                WHERE provider = :provider
                                  AND dataset_key = :dataset_key
                                """
                            ),
                            {
                                "provider": policy_provider,
                                "dataset_key": policy_dataset_key,
                            },
                        )
                    ).mappings().one()
                assert dict(saved_policy) == {
                    "provider": policy_provider,
                    "dataset_key": policy_dataset_key,
                    "source_kind": "manual",
                    "targeted_policy": "allow_targeted",
                    "stale_after_minutes": 137,
                    "max_concurrent": 3,
                    "rate_limit_source": {"proof": "server-provider-contract"},
                    "config_source": "c3e-c-integration",
                    "enabled": False,
                }

                grid = grid_response.json()["data"]
                detail = detail_response.json()["data"]
                pipeline_first = pipeline_first_response.json()
                first_items = pipeline_first["data"]["items"]
                detail_cursor = detail["recent_runs_next_cursor"]
                first_cursor = pipeline_first["meta"]["page"]["next_cursor"]
                assert detail_cursor is not None
                assert first_cursor == detail_cursor

                history = urlsplit(detail["pipeline_history_url"])
                history_query = parse_qs(history.query, strict_parsing=True)
                assert history.path == "/v1/ops/pipeline/executions"
                assert history_query == {
                    "provider": [PROVIDER_NAME],
                    "dataset_key": [DATASET_KEY_BULK],
                    "sync_scope": ["default"],
                }
                pipeline_second_response = await client.get(
                    history.path,
                    headers=auth_headers,
                    params={
                        "provider": history_query["provider"][0],
                        "dataset_key": history_query["dataset_key"][0],
                        "sync_scope": history_query["sync_scope"][0],
                        "page_size": _PAGE_SIZE,
                        "cursor": detail_cursor,
                    },
                )

                orphan_detail_response = await client.get(
                    "/v1/ops/datasets/detail",
                    headers=auth_headers,
                    params={
                        "provider": seed.orphan_provider,
                        "dataset_key": seed.orphan_dataset_key,
                        "sync_scope": "default",
                    },
                )
                assert orphan_detail_response.status_code == 200, (
                    orphan_detail_response.text
                )
                orphan_detail = orphan_detail_response.json()["data"]
                orphan_history = urlsplit(
                    orphan_detail["pipeline_history_url"]
                )
                assert orphan_history.scheme == ""
                assert orphan_history.netloc == ""
                assert orphan_history.fragment == ""
                assert orphan_history.path == "/v1/ops/pipeline/executions"
                orphan_history_query = parse_qs(
                    orphan_history.query, strict_parsing=True
                )
                assert orphan_history_query == {
                    "provider": [seed.orphan_provider],
                    "dataset_key": [seed.orphan_dataset_key],
                    "sync_scope": ["default"],
                }
                orphan_pipeline_response = await client.get(
                    orphan_history.path,
                    headers=auth_headers,
                    params={
                        "provider": orphan_history_query["provider"][0],
                        "dataset_key": orphan_history_query["dataset_key"][0],
                        "sync_scope": orphan_history_query["sync_scope"][0],
                        "page_size": _PAGE_SIZE,
                    },
                )

        assert pipeline_second_response.status_code == 200, (
            pipeline_second_response.text
        )
        pipeline_second = pipeline_second_response.json()
        second_items = pipeline_second["data"]["items"]
        assert orphan_pipeline_response.status_code == 200, (
            orphan_pipeline_response.text
        )
        orphan_pipeline = orphan_pipeline_response.json()
        orphan_pipeline_items = orphan_pipeline["data"]["items"]
        expected = _expected_order(seed.target_operations)
        expected_keys = [item.key for item in expected]
        first_keys = [(item["kind"], item["id"]) for item in first_items]
        second_keys = [(item["kind"], item["id"]) for item in second_items]
        detail_keys = [
            (item["kind"], item["id"]) for item in detail["recent_runs"]
        ]

        assert len(expected_keys) == 12
        assert first_keys == expected_keys[:_PAGE_SIZE]
        assert detail_keys == expected_keys[:_PAGE_SIZE]
        assert second_keys == expected_keys[_PAGE_SIZE:]
        assert set(first_keys).isdisjoint(second_keys)
        assert first_keys + second_keys == expected_keys
        assert len(set(first_keys + second_keys)) == len(expected_keys)
        assert pipeline_second["meta"]["page"]["next_cursor"] is None

        expected_by_key = {item.key: item for item in expected}
        for item in first_items + second_items:
            _assert_pipeline_projection(
                item, expected_by_key[(item["kind"], item["id"])]
            )
        for item in detail["recent_runs"]:
            _assert_dataset_projection(
                item, expected_by_key[(item["kind"], item["id"])]
            )
        assert orphan_detail["provider"] == seed.orphan_provider
        assert orphan_detail["dataset_key"] == seed.orphan_dataset_key
        assert orphan_detail["catalog_state"] == "orphan"
        assert orphan_detail["mutable"] is False
        orphan_rows = [
            item
            for item in grid["items"]
            if item["provider"] == seed.orphan_provider
            and item["dataset_key"] == seed.orphan_dataset_key
        ]
        assert len(orphan_rows) == 1
        orphan_grid_detail = urlsplit(orphan_rows[0]["detail_url"])
        assert orphan_grid_detail.path == "/v1/ops/datasets/detail"
        assert parse_qs(orphan_grid_detail.query, strict_parsing=True) == {
            "provider": [seed.orphan_provider],
            "dataset_key": [seed.orphan_dataset_key],
            "sync_scope": ["default"],
        }
        assert len(orphan_detail["recent_runs"]) == 1
        _assert_dataset_projection(
            orphan_detail["recent_runs"][0], seed.orphan_operation
        )
        assert len(orphan_pipeline_items) == 1
        _assert_pipeline_projection(
            orphan_pipeline_items[0], seed.orphan_operation
        )

        all_actual_keys = set(first_keys + second_keys)
        assert ("import_job", seed.update_job_id) not in all_actual_keys
        assert ("import_job", seed.decoy_root_id) not in all_actual_keys
        assert all(
            ("import_job", member_id) not in all_actual_keys
            for member_id in seed.decoy_member_ids
        )
        update_key = next(
            item.key for item in expected if item.kind == "update_request"
        )
        assert sum(key == update_key for key in first_keys + second_keys) == 1

        target_rows = [
            item
            for item in grid["items"]
            if item["provider"] == PROVIDER_NAME
            and item["dataset_key"] == DATASET_KEY_BULK
            and item["sync_scope"] == "default"
        ]
        assert len(target_rows) == 1
        target_detail_url = urlsplit(target_rows[0]["detail_url"])
        assert target_detail_url.path == "/v1/ops/datasets/detail"
        assert parse_qs(target_detail_url.query, strict_parsing=True) == {
            "provider": [PROVIDER_NAME],
            "dataset_key": [DATASET_KEY_BULK],
            "sync_scope": ["default"],
        }
        grid_latest = target_rows[0]["latest_execution"]
        assert grid_latest is not None
        _assert_dataset_projection(grid_latest, expected[0])

        assert grid["latest_execution_coverage"] == (
            "db_recorded_canonical_operations"
        )
        assert detail["provider"] == PROVIDER_NAME
        assert detail["dataset_key"] == DATASET_KEY_BULK
        assert detail["recent_runs_coverage"] == (
            "db_recorded_canonical_operations"
        )
        assert grid["schedule_source_status"] == "ok"
        assert grid["schedule_source_errors"] == []
        assert detail["schedule_source_status"] == "ok"
        assert detail["schedule_source_errors"] == []
        _assert_schedule(target_rows[0]["schedule"])
        _assert_schedule(detail["schedule"])
        assert len(schedule_requests) == 3

        # 인증 실패가 session을 열더라도 모든 의존성 호출은 독립 session이다.
        assert len(request_sessions) >= 6
        assert len({id(session) for session in request_sessions}) == len(
            request_sessions
        )
    finally:
        await _cleanup_committed_operations(migrated_engine)
