"""datasets와 pipeline REST의 canonical operation 교차 통합 회귀.

T-VN-33 cutover WIP 커밋(``2e76b80c``, 메시지 자체가 "do not merge")이 이 파일
992줄을 지우고 DB를 전혀 건드리지 않는 25줄만 남겼다. 그 25줄이 하던 일(함수 인자
이름 확인)은 ``tests/unit/test_ops_dataset_service_signature_contract.py``로 옮겼고,
여기서는 **실제 FastAPI app을 띄워 datasets/pipeline REST가 같은 canonical
operation을 같은 모양으로 투영하는지** 검증하던 통합 회귀를 되살린다.

identity가 pair(provider + dataset_key)에서 triple(provider_dataset_id +
sync_scope + operation_key)로 옮겨졌으므로(ADR-088) 다음이 달라졌다.

* 지어낸 자연키 ``ProviderDatasetOperationKey("provider", "dataset")``는 만들 수
  없다 — 실행 레코드가 ``provider_sync.provider_dataset_operation_scopes``를 FK로
  참조한다. membership은 시드에서 고른다(``tests/integration/_membership_seed.py``).
* REST가 dataset을 **id로** 지목한다. 예전의 cross-product decoy("provider는 같고
  dataset이 다른 member" ∧ "dataset은 같고 provider가 다른 member")는 triple 축에서
  다시 쓴다 — scope decoy(같은 dataset·같은 operation·**다른 sync_scope**)와
  dataset decoy(**다른 dataset**·다른 operation)다. filter가 conjunctive AND가
  아니면 둘 중 하나가 target 결과에 샌다.
* catalog 밖 dataset을 가리키는 state/policy row(옛 "orphan")는 이제 FK가 막는다 —
  ``test_ops_datasets_refresh_policy.py::test_orphan_policy_and_state_rows_cannot_exist``
  가 그 자리를 지킨다. 그래서 여기서는 orphan 200 경로를 되살리지 않고, 그 자리에
  **형제 sync_scope 상세**(같은 dataset·같은 operation·다른 scope)를 둔다.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

import httpx
import pytest
from kortravelmap.api import ops_dataset_schedule
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
    ProviderDatasetOperationMembership,
)
from kortravelmap.infra.feature_operation_repo import (
    ensure_dagster_feature_operation,
    finish_dagster_feature_membership,
)
from kortravelmap.infra.feature_update_repo import enqueue_feature_update_request
from kortravelmap.infra.jobs_repo import ImportJobDatasetTarget
from kortravelmap.infra.provider_refresh_policy_repo import (
    upsert_provider_refresh_policy,
)
from tests.integration._db_cleanup import truncate_committed_test_rows
from tests.integration._membership_seed import launch_tags, membership_for_dataset

pytestmark = pytest.mark.integration

_PAGE_SIZE = 10
_OPERATOR = "integration-test"
_PROXY_SECRET = "c3e-c-rest-proof-secret"

#: 대상 membership. ``kma_short_forecast``는 한 operation이 두 sync_scope를 갖는
#: 실측 시드라 scope decoy를 **지어내지 않고** 표현할 수 있다.
_TARGET_PROVIDER = "python-kma-api"
_TARGET_DATASET_KEY = "kma_short_forecast"
_TARGET_OPERATION = "feature_weather_kma_short_forecast_job"
_TARGET_SCOPE = "dataset_wide"
_SIBLING_SCOPE = "target_grids"

#: dataset decoy — 다른 dataset, 다른 operation.
_DECOY_DATASET_KEY = "kma_ultra_short_nowcast"
_DECOY_OPERATION = "feature_weather_kma_ultra_short_nowcast_job"

#: 정책 PUT 전용 dataset — 다른 단언과 겹치지 않게 따로 둔다.
_POLICY_PROVIDER = "python-khoa-api"
_POLICY_DATASET_KEY = "khoa_beaches"

_SCHEDULE_NAME = "feature_weather_kma_short_forecast_hourly_schedule"
_SCHEDULE_TICK = 2_000_000_000.0

_CLEANUP_SQL = """
TRUNCATE
    provider_sync.provider_sync_state,
    ops.provider_refresh_policies,
    ops.pipeline_cancellation_members,
    ops.pipeline_cancellation_runs,
    ops.feature_update_request_datasets,
    ops.feature_update_requests,
    ops.import_job_events,
    ops.import_job_datasets,
    ops.import_jobs,
    ops.pipeline_cancellations
RESTART IDENTITY CASCADE
"""


@dataclass(frozen=True)
class _ExpectedOperation:
    """두 REST 표면이 같은 canonical root를 어떻게 투영해야 하는지."""

    kind: str
    id: str
    status: str
    created_at: datetime
    started_at: datetime | None
    dagster_run_id: str | None
    dagster_run_status: str | None
    trigger_kind: str
    #: pipeline root record의 ``operation_key`` — root 자신의 실행 operation.
    operation_key: str | None
    #: 두 표면이 **똑같이** 실어야 하는 membership 목록(정렬 포함).
    members: tuple[dict[str, Any], ...]
    #: dataset 표면이 "무엇에 대한 레코드인지" 말하는 축(membership).
    view_sync_scope: str
    view_operation_key: str
    view_operation_member_id: str
    view_status: str
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
    projected_operation_key: str | None

    @property
    def key(self) -> tuple[str, str]:
        return self.kind, self.id


@dataclass(frozen=True)
class _SeedState:
    target_dataset_id: int
    target_operations: tuple[_ExpectedOperation, ...]
    sibling_operations: tuple[_ExpectedOperation, ...]
    update_job_id: str
    scope_decoy_root_id: str
    scope_decoy_member_ids: tuple[str, ...]
    dataset_decoy_root_id: str
    dataset_decoy_member_ids: tuple[str, ...]
    dataset_decoy_dataset_id: int
    #: target과 dataset·scope가 **같고 operation만 다른** decoy. 이 축이 없으면
    #: row-selection에서 operation_key를 무시해도 테스트가 통과한다(실증됨).
    operation_decoy_root_id: str
    operation_decoy_member_ids: tuple[str, ...]
    operation_decoy_operation_key: str
    policy_dataset_id: int


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


def _member_projection(
    membership: ProviderDatasetOperationMembership,
    *,
    provider: str,
    dataset_key: str,
    operation_member_id: str,
    status: str,
) -> dict[str, Any]:
    return {
        "provider_dataset_id": membership.provider_dataset_id,
        "provider": provider,
        "dataset_key": dataset_key,
        "sync_scope": membership.sync_scope,
        "operation_key": membership.operation_key,
        "operation_member_id": operation_member_id,
        "status": status,
    }


def _assert_common_projection(
    item: dict[str, Any],
    expected: _ExpectedOperation,
) -> None:
    """datasets REST와 pipeline REST가 **똑같이** 투영해야 하는 축."""

    assert (item["kind"], item["id"]) == expected.key
    assert item["detail_url"] == (
        f"/v1/ops/pipeline/executions/{expected.kind}/{expected.id}"
    )
    assert item["status"] == expected.status
    # membership 목록은 두 표면이 공유한다 — 한쪽만 접거나 늘리면 여기서 갈린다.
    assert item["provider_datasets"] == list(expected.members)
    assert item["dagster_run_id"] == expected.dagster_run_id
    assert item["dagster_run_status"] == expected.dagster_run_status
    assert item["trigger_kind"] == expected.trigger_kind
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
    assert projected["dagster_run_status"] == expected.projected_dagster_run_status
    assert projected["trigger_kind"] == expected.projected_trigger_kind
    # 예전 ``operation_registry_version``의 자리다 — registry 문자열이 아니라 DB
    # operation_key가 실린다.
    assert projected["operation_key"] == expected.projected_operation_key
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
    # dataset 표면의 레코드는 "어느 membership을 본 것인지"를 스스로 말해야 한다.
    assert item["sync_scope"] == expected.view_sync_scope
    assert item["operation_key"] == expected.view_operation_key
    assert item["operation_member_id"] == expected.view_operation_member_id
    assert item["pair_status"] == expected.view_status


def _assert_pipeline_projection(
    item: dict[str, Any],
    expected: _ExpectedOperation,
) -> None:
    _assert_common_projection(item, expected)
    assert item["operation_key"] == expected.operation_key
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
    memberships: tuple[ProviderDatasetOperationMembership, ...],
    view_membership: ProviderDatasetOperationMembership,
    dataset_keys: dict[int, tuple[str, str]],
    run_id: str,
    engine_created_at: datetime,
    view_status: str = "running",
    expect_outcome: str = "applied",
    finished_memberships: tuple[ProviderDatasetOperationMembership, ...] = (),
) -> _ExpectedOperation:
    """mutation 자체의 불변식을 박고 REST 기대값으로 옮긴다.

    ``view_status``는 **membership의 상태**이고 root 상태와 같을 필요가 없다.
    둘이 항상 같은 시드만 쓰면 ``pair_status`` 단언이 공허해진다 — 서버가 membership
    상태 대신 root 상태를 실어도 통과한다(적대 검증이 mutation으로 실증했고, main
    원본에도 있던 구멍이다). 그래서 mixed run의 sibling member를 완료시켜 축을 가른다.
    """

    operation = mutation.operation
    assert mutation.outcome == expect_outcome
    assert mutation.block_reason is None
    assert operation.dagster_run_id == run_id
    # member 하나가 끝나도 root는 running이다 — terminal 전이는 Dagster handoff만 한다.
    assert operation.status == "running"
    assert operation.dagster_run_status == "STARTED"
    assert operation.current_stage == "loading"
    assert operation.created_at == engine_created_at
    assert operation.started_at == engine_created_at
    assert operation.finished_at is None
    assert operation.trigger_kind == "manual"
    assert operation.operation_key == _TARGET_OPERATION
    assert len(operation.members) == len(memberships)
    members_by_membership = {
        member.membership: member for member in operation.members
    }
    assert set(members_by_membership) == set(memberships)
    done_memberships = {
        member.membership for member in operation.members if member.status == "done"
    }
    assert done_memberships == set(finished_memberships)
    # root progress는 완료한 member 비율이다. 이 값이 0으로 고정된 시드만 쓰면
    # 진행률 전파가 검증되지 않는다.
    expected_progress = round(100 * len(done_memberships) / len(memberships))
    assert operation.progress == expected_progress
    for member in operation.members:
        is_done = member.membership in done_memberships
        assert member.status == ("done" if is_done else "running")
        assert member.progress == (100 if is_done else 0)
        assert member.current_stage == ("completed" if is_done else "loading")
        assert member.started_at == engine_created_at
        assert (member.finished_at is not None) is is_done

    projection = tuple(
        _member_projection(
            membership,
            provider=dataset_keys[membership.provider_dataset_id][0],
            dataset_key=dataset_keys[membership.provider_dataset_id][1],
            operation_member_id=members_by_membership[
                membership
            ].import_job_dataset_id,
            status="done" if membership in done_memberships else "running",
        )
        # REST는 ``(provider_dataset_id, sync_scope, operation_key)`` 순으로 낸다.
        for membership in sorted(memberships)
    )
    return _ExpectedOperation(
        kind="import_job",
        id=operation.root_job_id,
        status="running",
        created_at=engine_created_at,
        started_at=engine_created_at,
        dagster_run_id=run_id,
        dagster_run_status="STARTED",
        trigger_kind="manual",
        operation_key=_TARGET_OPERATION,
        members=projection,
        view_sync_scope=view_membership.sync_scope,
        view_operation_key=view_membership.operation_key,
        view_operation_member_id=members_by_membership[
            view_membership
        ].import_job_dataset_id,
        view_status=view_status,
        progress=expected_progress,
        current_stage="loading",
        scope_type=None,
        priority=None,
        run_mode=None,
        operator=None,
        requested_job_id=None,
        linked_job_count=1 + len(memberships),
        projected_id=operation.root_job_id,
        projected_kind="provider_feature_load_run",
        projected_status="running",
        projected_progress=expected_progress,
        projected_stage="loading",
        projected_created_at=engine_created_at,
        projected_started_at=engine_created_at,
        projected_dagster_run_id=run_id,
        projected_dagster_run_status="STARTED",
        projected_trigger_kind="manual",
        projected_operation_key=_TARGET_OPERATION,
    )


async def _dataset_identity(session: AsyncSession) -> dict[int, tuple[str, str]]:
    rows = (
        await session.execute(
            text(
                "SELECT provider_dataset_id, provider, dataset_key"
                " FROM provider_sync.provider_datasets"
            )
        )
    ).all()
    return {
        int(row.provider_dataset_id): (str(row.provider), str(row.dataset_key))
        for row in rows
    }


async def _seed_committed_operations(engine: AsyncEngine) -> _SeedState:
    token = uuid4().hex
    target_operations: list[_ExpectedOperation] = []
    sibling_operations: list[_ExpectedOperation] = []

    async with (
        AsyncSession(engine, expire_on_commit=False) as session,
        session.begin(),
    ):
        dataset_keys = await _dataset_identity(session)
        target = await membership_for_dataset(
            session,
            provider=_TARGET_PROVIDER,
            dataset_key=_TARGET_DATASET_KEY,
            operation_key=_TARGET_OPERATION,
            sync_scope=_TARGET_SCOPE,
        )
        sibling = await membership_for_dataset(
            session,
            provider=_TARGET_PROVIDER,
            dataset_key=_TARGET_DATASET_KEY,
            operation_key=_TARGET_OPERATION,
            sync_scope=_SIBLING_SCOPE,
        )
        dataset_decoy = await membership_for_dataset(
            session,
            provider=_TARGET_PROVIDER,
            dataset_key=_DECOY_DATASET_KEY,
            operation_key=_DECOY_OPERATION,
            sync_scope=_TARGET_SCOPE,
        )
        # scope decoy는 target과 dataset·operation이 같고 scope만 다르다. dataset
        # decoy는 dataset이 다르다. 둘 다 target filter에 새면 conjunctive AND가
        # 깨진 것이다.
        assert sibling.provider_dataset_id == target.provider_dataset_id
        assert sibling.operation_key == target.operation_key
        assert sibling.sync_scope != target.sync_scope
        assert dataset_decoy.provider_dataset_id != target.provider_dataset_id

        # 시드에는 한 (dataset, scope)에 refresh operation이 둘인 조합이 없다
        # (실측: MULTI_OP_PER_SCOPE_COUNT=0). 그래서 operation_key만 다른 decoy는
        # 직접 등록해야 한다 — 스키마가 허용하는 상태이고(scope PK가 triple),
        # 이 축을 안 덮으면 row-selection이 operation_key를 통째로 무시해도
        # 테스트가 초록이다(적대 검증이 mutation으로 실증했다).
        operation_decoy_key = f"{_TARGET_OPERATION}.decoy_{token[:8]}"
        await session.execute(
            text(
                """
                INSERT INTO provider_sync.provider_dataset_operations (
                    provider_dataset_id, operation_key, operation_kind, is_enabled
                ) VALUES (:dataset_id, :operation_key, 'refresh', true)
                """
            ),
            {
                "dataset_id": target.provider_dataset_id,
                "operation_key": operation_decoy_key,
            },
        )
        await session.execute(
            text(
                """
                INSERT INTO provider_sync.provider_dataset_operation_scopes (
                    provider_dataset_id, sync_scope, operation_key, operation_kind
                ) VALUES (:dataset_id, :sync_scope, :operation_key, 'refresh')
                """
            ),
            {
                "dataset_id": target.provider_dataset_id,
                "sync_scope": target.sync_scope,
                "operation_key": operation_decoy_key,
            },
        )
        operation_decoy = ProviderDatasetOperationMembership(
            provider_dataset_id=target.provider_dataset_id,
            sync_scope=target.sync_scope,
            operation_key=operation_decoy_key,
        )
        assert operation_decoy.provider_dataset_id == target.provider_dataset_id
        assert operation_decoy.sync_scope == target.sync_scope
        assert operation_decoy.operation_key != target.operation_key

        policy_dataset_id = next(
            dataset_id
            for dataset_id, identity in dataset_keys.items()
            if identity == (_POLICY_PROVIDER, _POLICY_DATASET_KEY)
        )
        # 서버가 소유하는 provenance 필드. 아래 PUT은 이 값을 건드리지 않아야 한다.
        await upsert_provider_refresh_policy(
            session,
            provider_dataset_id=policy_dataset_id,
            source_kind="manual",
            expected_revision=None,
            rate_limit_source={"proof": "server-provider-contract"},
        )

        update_request = await enqueue_feature_update_request(
            session,
            scope={
                "type": "provider_dataset",
                "provider_dataset_id": target.provider_dataset_id,
                "sync_scope": target.sync_scope,
                "operation_key": target.operation_key,
            },
            dataset_memberships=(
                ImportJobDatasetTarget(
                    provider_dataset_id=target.provider_dataset_id,
                    sync_scope=target.sync_scope,
                    operation_key=target.operation_key,
                ),
            ),
            operator=_OPERATOR,
            reason="canonical REST projection proof",
        )
        assert len(update_request.dataset_memberships) == 1
        update_member = update_request.dataset_memberships[0]
        assert update_member.feature_update_request_dataset_id is not None
        target_operations.append(
            _ExpectedOperation(
                kind="update_request",
                id=update_request.request_id,
                status="queued",
                created_at=update_request.created_at,
                started_at=None,
                dagster_run_id=None,
                dagster_run_status=None,
                trigger_kind="update_request",
                # root 자신은 실행 operation이 없다(``feature_update_request`` job).
                # membership이 operation을 들고 있고, 그것은 dataset 표면의
                # ``operation_key``로만 나온다 — 예전 ``registry_version=None``과
                # 같은 자리다.
                operation_key=None,
                members=(
                    _member_projection(
                        target,
                        provider=_TARGET_PROVIDER,
                        dataset_key=_TARGET_DATASET_KEY,
                        operation_member_id=(
                            update_member.feature_update_request_dataset_id
                        ),
                        status="queued",
                    ),
                ),
                view_sync_scope=target.sync_scope,
                view_operation_key=target.operation_key,
                view_operation_member_id=(
                    update_member.feature_update_request_dataset_id
                ),
                view_status="queued",
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
                projected_operation_key=None,
            )
        )

        # 같은 created_at 동률을 포함해 detail 고정 10개보다 많은 11개 root를 만든다.
        offsets_us = (4, 4, 3, 3, 2, 1, -1, -1, -2, -3, -4)
        #: target과 sibling scope를 **한 run에** 묶는 index. 같은 operation_key라
        #: 표현 가능하고, dataset 표면이 요청한 membership 하나만 레코드로 내는지
        #: (형제 scope를 섞지 않는지) 여기서 갈린다.
        #:
        #: offset이 **음수인** index를 고른다. 시드는 한 트랜잭션에서 돌고
        #: `finish_dagster_feature_membership`은 `finished_at = now()`(트랜잭션 시작
        #: 시각)를 쓴다. 양수 offset이면 engine `started_at`이 `now()`보다 뒤라
        #: `ck_import_jobs_feature_engine_timeline`의 `started_at <= finished_at`이
        #: 깨진다 — 아래에서 member 하나를 완료시켜 pair_status 축을 가르려면
        #: 이 조건이 필요하다.
        mixed_index = 6
        assert offsets_us[mixed_index] < 0
        for index, offset_us in enumerate(offsets_us):
            created_at = update_request.created_at + timedelta(microseconds=offset_us)
            run_id = f"c3e-c-rest-proof-{token}-{index}"
            memberships = (
                (target, sibling) if index == mixed_index else (target,)
            )
            mutation = await ensure_dagster_feature_operation(
                session,
                dagster_run_id=run_id,
                trigger_kind="manual",
                selected_memberships=memberships,
                operation_key=_TARGET_OPERATION,
                engine_created_at=created_at,
                engine_started_at=created_at,
                observed_status="STARTED",
            )
            if index == mixed_index:
                # sibling member만 완료시켜 **member 상태 != root 상태**를 만든다.
                # 이게 없으면 `pair_status` 단언이 공허하다 — 서버가 membership
                # 상태 대신 root 상태를 실어도 통과한다(적대 검증이 실증했다).
                # root는 running으로 남는다(terminal 전이는 Dagster handoff만 한다).
                mutation = await finish_dagster_feature_membership(
                    session,
                    dagster_run_id=run_id,
                    membership=sibling,
                )
                assert mutation.operation.status == "running"
            finished_memberships = (sibling,) if index == mixed_index else ()
            target_operations.append(
                _feature_expectation(
                    mutation,
                    memberships=memberships,
                    view_membership=target,
                    dataset_keys=dataset_keys,
                    run_id=run_id,
                    engine_created_at=created_at,
                    finished_memberships=finished_memberships,
                )
            )
            if index == mixed_index:
                sibling_operations.append(
                    _feature_expectation(
                        mutation,
                        memberships=memberships,
                        view_membership=sibling,
                        dataset_keys=dataset_keys,
                        run_id=run_id,
                        engine_created_at=created_at,
                        view_status="done",
                        finished_memberships=finished_memberships,
                    )
                )

        scope_decoy_created_at = update_request.created_at + timedelta(microseconds=20)
        scope_decoy_run_id = f"c3e-c-rest-proof-{token}-scope-decoy"
        scope_decoy = await ensure_dagster_feature_operation(
            session,
            dagster_run_id=scope_decoy_run_id,
            trigger_kind="manual",
            selected_memberships=(sibling,),
            operation_key=_TARGET_OPERATION,
            engine_created_at=scope_decoy_created_at,
            engine_started_at=scope_decoy_created_at,
            observed_status="STARTED",
        )
        sibling_operations.append(
            _feature_expectation(
                scope_decoy,
                memberships=(sibling,),
                view_membership=sibling,
                dataset_keys=dataset_keys,
                run_id=scope_decoy_run_id,
                engine_created_at=scope_decoy_created_at,
            )
        )

        dataset_decoy_created_at = update_request.created_at + timedelta(
            microseconds=30
        )
        dataset_decoy_mutation = await ensure_dagster_feature_operation(
            session,
            dagster_run_id=f"c3e-c-rest-proof-{token}-dataset-decoy",
            trigger_kind="manual",
            selected_memberships=(dataset_decoy,),
            operation_key=_DECOY_OPERATION,
            engine_created_at=dataset_decoy_created_at,
            engine_started_at=dataset_decoy_created_at,
            observed_status="STARTED",
        )
        operation_decoy_created_at = update_request.created_at + timedelta(
            microseconds=40
        )
        operation_decoy_mutation = await ensure_dagster_feature_operation(
            session,
            dagster_run_id=f"c3e-c-rest-proof-{token}-operation-decoy",
            trigger_kind="manual",
            selected_memberships=(operation_decoy,),
            operation_key=operation_decoy_key,
            engine_created_at=operation_decoy_created_at,
            engine_started_at=operation_decoy_created_at,
            observed_status="STARTED",
        )
        await session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))

        root_ids = {item.id for item in target_operations}
        member_ids = {item.view_operation_member_id for item in target_operations}
        scope_decoy_member_ids = tuple(
            member.import_job_dataset_id for member in scope_decoy.operation.members
        )
        dataset_decoy_member_ids = tuple(
            member.import_job_dataset_id
            for member in dataset_decoy_mutation.operation.members
        )
        operation_decoy_member_ids = tuple(
            member.import_job_dataset_id
            for member in operation_decoy_mutation.operation.members
        )
        assert len(root_ids) == 12
        assert len(member_ids) == 12
        assert root_ids.isdisjoint(member_ids)
        canonical_ids = root_ids | member_ids
        assert len(canonical_ids) == 24
        assert scope_decoy.operation.root_job_id not in canonical_ids
        assert dataset_decoy_mutation.operation.root_job_id not in canonical_ids
        assert operation_decoy_mutation.operation.root_job_id not in canonical_ids
        assert set(operation_decoy_member_ids).isdisjoint(canonical_ids)
        assert len(scope_decoy_member_ids) == 1
        assert len(dataset_decoy_member_ids) == 1
        assert set(scope_decoy_member_ids).isdisjoint(canonical_ids)
        assert set(dataset_decoy_member_ids).isdisjoint(canonical_ids)
        assert update_request.request_id != update_request.job_id
        return _SeedState(
            target_dataset_id=target.provider_dataset_id,
            target_operations=tuple(target_operations),
            sibling_operations=tuple(sibling_operations),
            update_job_id=update_request.job_id,
            scope_decoy_root_id=scope_decoy.operation.root_job_id,
            scope_decoy_member_ids=scope_decoy_member_ids,
            dataset_decoy_root_id=dataset_decoy_mutation.operation.root_job_id,
            dataset_decoy_member_ids=dataset_decoy_member_ids,
            dataset_decoy_dataset_id=dataset_decoy.provider_dataset_id,
            operation_decoy_root_id=operation_decoy_mutation.operation.root_job_id,
            operation_decoy_member_ids=operation_decoy_member_ids,
            operation_decoy_operation_key=operation_decoy_key,
            policy_dataset_id=policy_dataset_id,
        )


async def _cleanup_committed_operations(engine: AsyncEngine) -> None:
    """append-only 행은 저장소 integration 관례의 TRUNCATE로 별도 commit 정리한다."""
    async with AsyncSession(engine) as session, session.begin():
        await truncate_committed_test_rows(session, _CLEANUP_SQL)
        # 시드가 등록한 형제 operation은 카탈로그 행이라 TRUNCATE 대상이 아니다.
        # 남겨 두면 다음 테스트의 카탈로그 전제가 조용히 달라진다.
        # **실행 행을 지운 뒤**에 지운다 — `fk_import_job_datasets_exact_operation_scope`가
        # scope 행을 참조하므로 순서를 바꾸면 FK 위반으로 정리가 실패한다.
        await session.execute(
            text(
                "DELETE FROM provider_sync.provider_dataset_operation_scopes "
                "WHERE operation_key LIKE '%.decoy@_%' ESCAPE '@'"
            )
        )
        await session.execute(
            text(
                "DELETE FROM provider_sync.provider_dataset_operations "
                "WHERE operation_key LIKE '%.decoy@_%' ESCAPE '@'"
            )
        )
        await session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


def _schedule_payload() -> dict[str, Any]:
    # launch 쪽 tag 생산자와 read 쪽 tag 소비자가 같은 key를 쓰는지 먼저 박는다 —
    # 두 상수가 갈리면 schedule은 조용히 "not_scheduled"가 된다.
    schedule_tags = {
        **launch_tags(operation_key=_TARGET_OPERATION, trigger_kind="schedule"),
        "kor_travel_map.timezone": "Asia/Seoul",
    }
    assert ops_dataset_schedule.OPERATION_KEY_TAG in schedule_tags
    assert schedule_tags[ops_dataset_schedule.OPERATION_KEY_TAG] == _TARGET_OPERATION
    return {
        "data": {
            "repositoriesOrError": {
                "__typename": "RepositoryConnection",
                "nodes": [
                    {
                        "schedules": [
                            {
                                "name": _SCHEDULE_NAME,
                                "pipelineName": _TARGET_OPERATION,
                                "tags": [
                                    {"key": key, "value": value}
                                    for key, value in sorted(schedule_tags.items())
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
    assert summary["basis"] == "dagster_operation_key_tag"
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
        async with AsyncSession(migrated_engine, expire_on_commit=False) as session:
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
        target_filter = {
            "provider_dataset_id": seed.target_dataset_id,
            "sync_scope": _TARGET_SCOPE,
            "operation_key": _TARGET_OPERATION,
        }

        from kortravelmap.api.routers import ops_datasets as datasets_router

        preview_calls: list[tuple[str, str, int]] = []

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
                variant="id-routing-proof",
                description="id로 지목한 dataset이 catalog identity로 실행되는 증거",
                items=({"provider": provider, "dataset_key": dataset_key},),
                total_items=1,
                max_items=max_items,
            )

        monkeypatch.setattr(
            datasets_router,
            "run_dataset_fixture_preview",
            _preview_fixture,
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
                    f"/v1/ops/datasets/{seed.target_dataset_id}",
                    headers=auth_headers,
                    params={
                        "sync_scope": _TARGET_SCOPE,
                        "operation_key": _TARGET_OPERATION,
                    },
                )
                pipeline_first_response = await client.get(
                    "/v1/ops/pipeline/executions",
                    headers=auth_headers,
                    params={**target_filter, "page_size": _PAGE_SIZE},
                )
                # pair를 경로/질의로 받던 예전 표면은 남아 있지 않다.
                legacy_detail_response = await client.get(
                    "/v1/ops/datasets/detail",
                    headers=auth_headers,
                    params={
                        "provider": _TARGET_PROVIDER,
                        "dataset_key": _TARGET_DATASET_KEY,
                        "sync_scope": _TARGET_SCOPE,
                    },
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
                    f"/v1/ops/datasets/{seed.target_dataset_id}/preview",
                    headers=auth_headers,
                    params={
                        "sync_scope": _TARGET_SCOPE,
                        "operation_key": _TARGET_OPERATION,
                    },
                    json={"source": "fixture", "max_items": 1},
                )
                policy_response = await client.put(
                    "/v1/ops/datasets/refresh-policy",
                    headers=auth_headers,
                    params={"provider_dataset_id": seed.policy_dataset_id},
                    json={
                        "expected_revision": "1",
                        "source_kind": "manual",
                        "targeted_policy": "allow_targeted",
                        "stale_after_minutes": 137,
                        "max_concurrent": 3,
                        "config_source": "c3e-c-integration",
                        "enabled": False,
                    },
                )

                assert denied_response.status_code == 401
                assert denied_response.json()["code"] == "OPS_TOKEN_REQUIRED"
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
                    "sync_scope": [_TARGET_SCOPE],
                    "operation_key": [_TARGET_OPERATION],
                }
                # id로 지목한 dataset이 **catalog의 exact identity**로 실행됐다.
                assert preview_calls == [
                    (_TARGET_PROVIDER, _TARGET_DATASET_KEY, 1)
                ]
                preview_data = preview_response.json()["data"]
                assert preview_data["provider_dataset_id"] == seed.target_dataset_id
                assert preview_data["sync_scope"] == _TARGET_SCOPE
                assert preview_data["operation_key"] == _TARGET_OPERATION
                assert preview_data["provider"] == _TARGET_PROVIDER
                assert preview_data["dataset_key"] == _TARGET_DATASET_KEY
                assert preview_data["items"] == [
                    {
                        "provider": _TARGET_PROVIDER,
                        "dataset_key": _TARGET_DATASET_KEY,
                    }
                ]

                policy_request_query = parse_qs(
                    policy_response.request.url.query.decode(),
                    strict_parsing=True,
                )
                assert policy_request_query == {
                    "provider_dataset_id": [str(seed.policy_dataset_id)]
                }
                policy_data = policy_response.json()["data"]
                assert policy_data["provider_dataset_id"] == seed.policy_dataset_id
                assert policy_data["provider"] == _POLICY_PROVIDER
                assert policy_data["dataset_key"] == _POLICY_DATASET_KEY
                assert policy_data["source_kind"] == "manual"
                assert policy_data["targeted_policy"] == "allow_targeted"
                assert policy_data["stale_after_minutes"] == 137
                assert policy_data["max_concurrent"] == 3
                assert policy_data["rate_limit_source"] == {
                    "proof": "server-provider-contract"
                }
                assert policy_data["config_source"] == "c3e-c-integration"
                assert policy_data["enabled"] is False
                assert policy_data["revision"] == "2"

                async with AsyncSession(migrated_engine) as verify_session:
                    saved_policy = (
                        (
                            await verify_session.execute(
                                text(
                                    """
                                    SELECT provider_dataset_id, source_kind,
                                           targeted_policy, stale_after_minutes,
                                           max_concurrent, rate_limit_source,
                                           config_source, enabled, revision
                                    FROM ops.provider_refresh_policies
                                    WHERE provider_dataset_id = :provider_dataset_id
                                    """
                                ),
                                {"provider_dataset_id": seed.policy_dataset_id},
                            )
                        )
                        .mappings()
                        .one()
                    )
                assert dict(saved_policy) == {
                    "provider_dataset_id": seed.policy_dataset_id,
                    "source_kind": "manual",
                    "targeted_policy": "allow_targeted",
                    "stale_after_minutes": 137,
                    "max_concurrent": 3,
                    "rate_limit_source": {"proof": "server-provider-contract"},
                    "config_source": "c3e-c-integration",
                    "enabled": False,
                    "revision": 2,
                }

                grid = grid_response.json()["data"]
                detail = detail_response.json()["data"]
                pipeline_first = pipeline_first_response.json()
                first_items = pipeline_first["data"]["items"]
                detail_cursor = detail["run_history"]["next_cursor"]
                first_cursor = pipeline_first["meta"]["page"]["next_cursor"]
                assert detail_cursor is not None
                assert first_cursor == detail_cursor

                history = urlsplit(detail["run_history"]["canonical_url"])
                history_query = parse_qs(history.query, strict_parsing=True)
                assert history.scheme == ""
                assert history.netloc == ""
                assert history.fragment == ""
                assert history.path == "/v1/ops/pipeline/executions"
                assert history_query == {
                    "provider_dataset_id": [str(seed.target_dataset_id)],
                    "sync_scope": [_TARGET_SCOPE],
                    "operation_key": [_TARGET_OPERATION],
                }
                pipeline_second_response = await client.get(
                    history.path,
                    headers=auth_headers,
                    params={
                        "provider_dataset_id": history_query["provider_dataset_id"][0],
                        "sync_scope": history_query["sync_scope"][0],
                        "operation_key": history_query["operation_key"][0],
                        "page_size": _PAGE_SIZE,
                        "cursor": detail_cursor,
                    },
                )

                sibling_detail_response = await client.get(
                    f"/v1/ops/datasets/{seed.target_dataset_id}",
                    headers=auth_headers,
                    params={
                        "sync_scope": _SIBLING_SCOPE,
                        "operation_key": _TARGET_OPERATION,
                    },
                )
                assert sibling_detail_response.status_code == 200, (
                    sibling_detail_response.text
                )
                sibling_detail = sibling_detail_response.json()["data"]
                sibling_history = urlsplit(
                    sibling_detail["run_history"]["canonical_url"]
                )
                sibling_history_query = parse_qs(
                    sibling_history.query, strict_parsing=True
                )
                assert sibling_history.path == "/v1/ops/pipeline/executions"
                assert sibling_history_query == {
                    "provider_dataset_id": [str(seed.target_dataset_id)],
                    "sync_scope": [_SIBLING_SCOPE],
                    "operation_key": [_TARGET_OPERATION],
                }
                sibling_pipeline_response = await client.get(
                    sibling_history.path,
                    headers=auth_headers,
                    params={
                        "provider_dataset_id": (
                            sibling_history_query["provider_dataset_id"][0]
                        ),
                        "sync_scope": sibling_history_query["sync_scope"][0],
                        "operation_key": sibling_history_query["operation_key"][0],
                        "page_size": _PAGE_SIZE,
                    },
                )

        assert pipeline_second_response.status_code == 200, (
            pipeline_second_response.text
        )
        pipeline_second = pipeline_second_response.json()
        second_items = pipeline_second["data"]["items"]
        assert sibling_pipeline_response.status_code == 200, (
            sibling_pipeline_response.text
        )
        sibling_pipeline_items = sibling_pipeline_response.json()["data"]["items"]

        expected = _expected_order(seed.target_operations)
        expected_keys = [item.key for item in expected]
        first_keys = [(item["kind"], item["id"]) for item in first_items]
        second_keys = [(item["kind"], item["id"]) for item in second_items]
        detail_keys = [
            (item["kind"], item["id"]) for item in detail["run_history"]["items"]
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
        for item in detail["run_history"]["items"]:
            _assert_dataset_projection(
                item, expected_by_key[(item["kind"], item["id"])]
            )

        # 형제 scope 뷰: 같은 dataset·같은 operation이지만 **다른 scope**의 실행만
        # 보인다. target-only root는 여기 없고, scope decoy는 여기에만 있다.
        sibling_expected = _expected_order(seed.sibling_operations)
        sibling_expected_keys = [item.key for item in sibling_expected]
        sibling_detail_keys = [
            (item["kind"], item["id"])
            for item in sibling_detail["run_history"]["items"]
        ]
        sibling_pipeline_keys = [
            (item["kind"], item["id"]) for item in sibling_pipeline_items
        ]
        assert len(sibling_expected_keys) == 2
        assert sibling_detail_keys == sibling_expected_keys
        assert sibling_pipeline_keys == sibling_expected_keys
        sibling_by_key = {item.key: item for item in sibling_expected}
        for item in sibling_detail["run_history"]["items"]:
            _assert_dataset_projection(item, sibling_by_key[(item["kind"], item["id"])])
        for item in sibling_pipeline_items:
            _assert_pipeline_projection(
                item, sibling_by_key[(item["kind"], item["id"])]
            )

        # 두 scope 뷰가 공유하는 root는 mixed run 하나뿐이고, dataset 표면은 그
        # root에 대해 **요청한 membership 한 줄만** 낸다(형제 member는 섞이지 않는다).
        shared_keys = set(sibling_expected_keys) & set(expected_keys)
        assert len(shared_keys) == 1
        shared_key = next(iter(shared_keys))
        shared_target_record = next(
            item
            for item in detail["run_history"]["items"]
            if (item["kind"], item["id"]) == shared_key
        )
        shared_sibling_record = next(
            item
            for item in sibling_detail["run_history"]["items"]
            if (item["kind"], item["id"]) == shared_key
        )
        assert len(shared_target_record["provider_datasets"]) == 2
        assert (
            shared_target_record["provider_datasets"]
            == shared_sibling_record["provider_datasets"]
        )
        assert shared_target_record["sync_scope"] == _TARGET_SCOPE
        assert shared_sibling_record["sync_scope"] == _SIBLING_SCOPE
        assert (
            shared_target_record["operation_member_id"]
            != shared_sibling_record["operation_member_id"]
        )
        assert (
            sum(
                (item["kind"], item["id"]) == shared_key
                for item in detail["run_history"]["items"]
            )
            == 1
        )

        # decoy와 update job은 target filter 결과에 없다.
        all_actual_keys = set(first_keys + second_keys)
        assert ("import_job", seed.update_job_id) not in all_actual_keys
        assert ("import_job", seed.scope_decoy_root_id) not in all_actual_keys
        assert ("import_job", seed.dataset_decoy_root_id) not in all_actual_keys
        # operation만 다른 decoy도 새면 안 된다. 이 줄이 없으면 row-selection이
        # operation_key를 무시해도(예: 필터 param을 None으로) 통과한다.
        assert ("import_job", seed.operation_decoy_root_id) not in all_actual_keys
        assert all(
            ("import_job", member_id) not in all_actual_keys
            for member_id in (
                *seed.scope_decoy_member_ids,
                *seed.dataset_decoy_member_ids,
                *seed.operation_decoy_member_ids,
            )
        )
        update_key = next(
            item.key for item in expected if item.kind == "update_request"
        )
        assert sum(key == update_key for key in first_keys + second_keys) == 1

        # 그리드: 행 identity는 triple이다. 같은 dataset의 두 scope는 서로 다른
        # 행이며 서로 다른 상세 링크를 갖는다(접히면 형제가 사라진다).
        dataset_rows = [
            item
            for item in grid["items"]
            if item["provider_dataset_id"] == seed.target_dataset_id
        ]
        # 같은 scope에 형제 operation이 둘이면 **두 행**이다(접히면 형제가 사라진다).
        # decoy 등록 덕에 이 dataset은 (scope, operation) 조합이 셋이다.
        assert [
            (row["sync_scope"], row["operation_key"]) for row in dataset_rows
        ] == [
            (_TARGET_SCOPE, _TARGET_OPERATION),
            (_TARGET_SCOPE, seed.operation_decoy_operation_key),
            (_SIBLING_SCOPE, _TARGET_OPERATION),
        ]
        # 상세 링크도 membership마다 달라야 한다 — 같으면 어느 행을 눌러도 같은
        # 화면이 열린다.
        assert len({row["detail_url"] for row in dataset_rows}) == 3
        target_rows = [
            row
            for row in dataset_rows
            if row["sync_scope"] == _TARGET_SCOPE
            and row["operation_key"] == _TARGET_OPERATION
        ]
        assert len(target_rows) == 1
        target_row = target_rows[0]
        assert target_row["provider"] == _TARGET_PROVIDER
        assert target_row["dataset_key"] == _TARGET_DATASET_KEY
        assert target_row["catalog_state"] == "canonical"
        assert target_row["mutable"] is True
        target_detail_url = urlsplit(target_row["detail_url"])
        assert target_detail_url.path == (
            f"/v1/ops/datasets/{seed.target_dataset_id}"
        )
        assert parse_qs(target_detail_url.query, strict_parsing=True) == {
            "sync_scope": [_TARGET_SCOPE],
            "operation_key": [_TARGET_OPERATION],
        }
        assert target_row["latest_execution"] is None
        grid_active = target_row["active_execution"]
        assert grid_active is not None
        _assert_dataset_projection(grid_active, expected[0])

        assert grid["execution_coverage"] == "db_recorded_canonical_operations"
        assert detail["provider_dataset_id"] == seed.target_dataset_id
        assert detail["provider"] == _TARGET_PROVIDER
        assert detail["dataset_key"] == _TARGET_DATASET_KEY
        assert detail["catalog_state"] == "canonical"
        assert detail["mutable"] is True
        assert detail["execution_coverage"] == "db_recorded_canonical_operations"
        assert detail["latest_execution"] is None
        assert detail["active_execution"] is not None
        _assert_dataset_projection(detail["active_execution"], expected[0])
        assert sibling_detail["active_execution"] is not None
        _assert_dataset_projection(
            sibling_detail["active_execution"], sibling_expected[0]
        )

        # schedule은 operation_key tag로만 붙는다 — dataset을 가로질러 번지지 않는다.
        assert grid["schedule_source_status"] == "ok"
        assert grid["schedule_source_errors"] == []
        assert detail["schedule_source_status"] == "ok"
        assert detail["schedule_source_errors"] == []
        # schedule은 **operation_key**에 붙는다. 같은 dataset·같은 scope라도
        # operation이 다르면 붙지 않는다 — decoy 행이 그것을 증명한다.
        for row in dataset_rows:
            if row["operation_key"] == _TARGET_OPERATION:
                _assert_schedule(row["schedule"])
            else:
                assert row["operation_key"] == seed.operation_decoy_operation_key
                assert row["schedule"]["basis"] == "not_scheduled"
                assert row["schedule"]["schedule_names"] == []
        _assert_schedule(detail["schedule"])
        _assert_schedule(sibling_detail["schedule"])
        decoy_rows = [
            item
            for item in grid["items"]
            if item["provider_dataset_id"] == seed.dataset_decoy_dataset_id
        ]
        assert decoy_rows
        assert {row["schedule"]["basis"] for row in decoy_rows} == {"not_scheduled"}
        assert {row["schedule"]["status"] for row in decoy_rows} == {None}
        # schedule 조회는 **요청당 한 번**이다(행마다가 아니라). schedule을 쓰는
        # REST 호출은 grid/detail/sibling detail 세 번뿐이다.
        assert len(schedule_requests) == 3

        # 인증 실패가 session을 열더라도 모든 의존성 호출은 독립 session이다.
        assert len(request_sessions) >= 6
        assert len({id(session) for session in request_sessions}) == len(
            request_sessions
        )
    finally:
        await _cleanup_committed_operations(migrated_engine)
