"""T-VN-33 feature-update canonical membership 경계 검증."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError

from kortravelmap.infra import feature_update_active_repo as active_repo
from kortravelmap.infra import feature_update_executor as executor
from kortravelmap.infra import feature_update_repo as repo
from kortravelmap.infra.feature_update_executor import (
    ProviderDatasetRefreshFailure,
    ProviderDatasetRefreshResult,
    ProviderDatasetRefreshScope,
    SkippedProviderDatasetRefresh,
    _require_runner_result_membership,
)
from kortravelmap.infra.jobs_repo import ImportJobDatasetTarget
from kortravelmap.infra.scope_repo import CacheTargetFeatureMatch, ScopeResolution


def _membership(
    *,
    provider_dataset_id: int = 17,
    sync_scope: str = "dataset_wide",
) -> repo.FeatureUpdateRequestDataset:
    return repo.FeatureUpdateRequestDataset(
        feature_update_request_dataset_id="90000000-0000-4000-8000-000000000017",
        provider_dataset_id=provider_dataset_id,
        sync_scope=sync_scope,
        provider="python-test-api",
        dataset_key="test-dataset",
        operation_key="refresh_test_dataset",
    )


def _row(*, membership: repo.FeatureUpdateRequestDataset | None) -> SimpleNamespace:
    now = datetime(2026, 8, 7, tzinfo=UTC)
    return SimpleNamespace(
        request_id="90000000-0000-4000-8000-000000000001",
        scope_type="provider_dataset",
        scope={
            "type": "provider_dataset",
            "provider_dataset_id": 17,
            "sync_scope": "dataset_wide",
            "operation_key": "refresh_test_dataset",
        },
        dataset_membership_mode="single",
        update_policy={},
        run_mode="queued",
        priority=50,
        status="queued",
        matched_scope={},
        job_id="90000000-0000-4000-8000-000000000002",
        dagster_run_id=None,
        cancellation_id=None,
        cancellation_requested_at=None,
        cancellation_requested_by=None,
        cancellation_reason=None,
        operator=None,
        reason=None,
        error_message=None,
        created_at=now,
        started_at=None,
        finished_at=None,
        generation=1,
        dispatch_requested_at=None,
        feature_update_request_dataset_id=(
            membership.feature_update_request_dataset_id if membership else None
        ),
        provider_dataset_id=membership.provider_dataset_id if membership else None,
        sync_scope=membership.sync_scope if membership else None,
        operation_key=membership.operation_key if membership else None,
        provider=membership.provider if membership else None,
        dataset_key=membership.dataset_key if membership else None,
    )


def _scope() -> ProviderDatasetRefreshScope:
    return ProviderDatasetRefreshScope(
        request_id="90000000-0000-4000-8000-000000000001",
        provider_dataset_id=17,
        sync_scope="dataset_wide",
        provider="python-test-api",
        dataset_key="test-dataset",
        scope_type="provider_dataset",
        request_scope={
            "type": "provider_dataset",
            "provider_dataset_id": 17,
            "sync_scope": "dataset_wide",
            "operation_key": "refresh_test_dataset",
        },
        update_policy={},
        feature_ids=(),
        feature_count=0,
        prevent_provider_reactivation=True,
        operation_key="refresh_test_dataset",
    )


def test_direct_scope_has_only_canonical_dataset_id() -> None:
    assert repo._canonicalize_request_scope(
        {
            "type": "provider_dataset",
            "provider_dataset_id": 17,
            "sync_scope": "dataset_wide",
            "operation_key": "refresh_test_dataset",
        }
    ) == {
        "type": "provider_dataset",
        "provider_dataset_id": 17,
        "sync_scope": "dataset_wide",
        "operation_key": "refresh_test_dataset",
    }

    with pytest.raises(ValueError, match="only permits"):
        repo._canonicalize_request_scope(
            {
                "type": "provider_dataset",
                "provider_dataset_id": 17,
                "sync_scope": "dataset_wide",
                "operation_key": "refresh_test_dataset",
                "provider": "python-test-api",
            }
        )


def test_direct_scope_must_match_its_single_membership() -> None:
    request = repo._rows_to_request([_row(membership=_membership())])
    assert repo.execution_scope_for_request(request) == {
        "type": "provider_dataset",
        "provider_dataset_id": 17,
        "sync_scope": "dataset_wide",
        "operation_key": "refresh_test_dataset",
    }

    wrong_scope = repo.FeatureUpdateRequest(
        **{
            **request.__dict__,
            "scope": {
                "type": "provider_dataset",
                "provider_dataset_id": 18,
                "sync_scope": "dataset_wide",
                "operation_key": "refresh_test_dataset",
            },
        }
    )
    with pytest.raises(RuntimeError, match="disagree"):
        repo.execution_scope_for_request(wrong_scope)


def test_persisted_request_requires_membership_and_exposes_canonical_identity() -> None:
    with pytest.raises(RuntimeError, match="requires dataset memberships"):
        repo._rows_to_request([_row(membership=None)])

    request = repo._rows_to_request([_row(membership=_membership())])
    assert request.dataset_membership_mode == "single"
    assert request.dataset_memberships == (_membership(),)
    assert not hasattr(request, "providers")
    assert not hasattr(request, "dataset_keys")
    assert not hasattr(request, "effective_sync_scope")


def test_duplicate_dataset_membership_is_rejected_before_any_writer_sql() -> None:
    target = ImportJobDatasetTarget(17, "dataset_wide", "refresh_test_dataset")
    with pytest.raises(ValueError, match="duplicate"):
        repo._normalized_dataset_memberships((target, target))


def test_request_insert_requires_job_membership_set_agreement() -> None:
    assert "ops.import_job_datasets" in repo._INSERT_REQUEST_SQL
    assert "ops.feature_update_request_datasets" in repo._INSERT_REQUEST_SQL
    assert "EXCEPT" in repo._INSERT_REQUEST_SQL
    assert "dataset_membership_mode" in repo._INSERT_REQUEST_SQL
    assert "providers" not in repo._INSERT_REQUEST_SQL
    assert "dataset_keys" not in repo._INSERT_REQUEST_SQL


def test_active_membership_overlap_uses_the_trigger_constraint_identity() -> None:
    class _DriverError(Exception):
        sqlstate = "23505"
        constraint_name = active_repo.ACTIVE_PROVIDER_DATASET_OVERLAP_CONSTRAINT

    conflict = IntegrityError("insert", {}, _DriverError())
    assert active_repo.is_active_provider_dataset_unique_violation(conflict)

    class _DifferentConstraintError(Exception):
        sqlstate = "23505"
        constraint_name = "uq_not_the_feature_update_membership"

    assert not active_repo.is_active_provider_dataset_unique_violation(
        IntegrityError("insert", {}, _DifferentConstraintError())
    )


def test_active_membership_lookup_rejects_inactive_or_disabled_target() -> None:
    class _Mappings:
        def all(self) -> list[object]:
            return []

    class _Result:
        def mappings(self) -> _Mappings:
            return _Mappings()

    class _Session:
        async def execute(self, *_args: object, **_kwargs: object) -> _Result:
            return _Result()

    async def _resolve() -> None:
        await repo._resolve_active_dataset_memberships(
            _Session(), (ImportJobDatasetTarget(17, "dataset_wide", "refresh_test_dataset"),)
        )

    with pytest.raises(ValueError, match="active dataset and enabled refresh scope"):
        asyncio.run(_resolve())


def test_runner_cannot_report_a_membership_outside_the_request_snapshot() -> None:
    scope = _scope()
    matching = ProviderDatasetRefreshResult(
        provider_dataset_id=17,
        sync_scope="dataset_wide",
        operation_key="refresh_test_dataset",
        provider="python-test-api",
        dataset_key="test-dataset",
    )
    assert _require_runner_result_membership(matching, scope) is matching

    with pytest.raises(RuntimeError, match="does not match"):
        _require_runner_result_membership(
            ProviderDatasetRefreshResult(
                provider_dataset_id=18,
                sync_scope="dataset_wide",
                operation_key="refresh_test_dataset",
                provider="python-other-api",
                dataset_key="other-dataset",
            ),
            scope,
        )


@pytest.mark.parametrize(
    ("sync_scope", "operation_key"),
    [
        ("target_grids", "refresh_test_dataset"),
        ("dataset_wide", "refresh_other_dataset"),
        ("target_grids", "refresh_other_dataset"),
    ],
)
def test_runner_result_membership_checks_every_triple_axis(
    sync_scope: str,
    operation_key: str,
) -> None:
    """``provider_dataset_id``만 맞으면 통과하는 대조가 아니어야 한다.

    같은 dataset이라도 scope/operation이 다르면 다른 실행 단위다. 위 테스트는
    dataset 축만 어긋뜨려 나머지 두 항을 지워도 통과했다.
    """
    with pytest.raises(RuntimeError, match="does not match"):
        _require_runner_result_membership(
            ProviderDatasetRefreshResult(
                provider_dataset_id=17,
                sync_scope=sync_scope,
                operation_key=operation_key,
                provider="python-test-api",
                dataset_key="test-dataset",
            ),
            _scope(),
        )


@pytest.mark.parametrize(
    ("sync_scope", "operation_key", "provider_dataset_id", "message"),
    [
        ("legacy_all", "refresh_test_dataset", 17, "unsupported sync_scope"),
        (" dataset_wide", "refresh_test_dataset", 17, "trimmed, non-empty"),
        ("external_system: pinvi", "refresh_test_dataset", 17, "exact non-empty"),
        ("dataset_wide", " refresh_test_dataset", 17, "trimmed non-empty"),
        ("dataset_wide", "", 17, "trimmed non-empty"),
        ("dataset_wide", "refresh_test_dataset", 0, "positive integer"),
        ("dataset_wide", "refresh_test_dataset", True, "positive integer"),
    ],
)
@pytest.mark.parametrize(
    "carrier",
    ["scope", "result", "failure", "skipped"],
)
def test_exact_refresh_membership_validator_guards_every_carrier(
    carrier: str,
    sync_scope: str,
    operation_key: str,
    provider_dataset_id: object,
    message: str,
) -> None:
    """네 운반체가 공유하는 유일한 검증기 — 본문을 비우면 전부 무르게 된다.

    ``ProviderDatasetRefreshScope``/``Result``/``Failure``/``SkippedProviderDatasetRefresh``는
    실행 identity를 request 이력·sync-state write까지 그대로 나른다.
    """
    def _build() -> object:
        if carrier == "scope":
            return ProviderDatasetRefreshScope(
                request_id="90000000-0000-4000-8000-000000000001",
                provider_dataset_id=provider_dataset_id,  # type: ignore[arg-type]
                sync_scope=sync_scope,
                provider="python-test-api",
                dataset_key="test-dataset",
                scope_type="provider_dataset",
                request_scope={},
                update_policy={},
                feature_ids=(),
                feature_count=0,
                prevent_provider_reactivation=True,
                operation_key=operation_key,
            )
        if carrier == "result":
            return ProviderDatasetRefreshResult(
                provider_dataset_id=provider_dataset_id,  # type: ignore[arg-type]
                sync_scope=sync_scope,
                operation_key=operation_key,
                provider="python-test-api",
                dataset_key="test-dataset",
            )
        if carrier == "failure":
            return ProviderDatasetRefreshFailure(
                provider_dataset_id=provider_dataset_id,  # type: ignore[arg-type]
                sync_scope=sync_scope,
                operation_key=operation_key,
                message="unit",
            )
        return SkippedProviderDatasetRefresh(
            provider_dataset_id=provider_dataset_id,  # type: ignore[arg-type]
            sync_scope=sync_scope,
            provider="python-test-api",
            dataset_key="test-dataset",
            reason="policy_disabled",
            feature_count=0,
            operation_key=operation_key,
        )

    with pytest.raises(ValueError, match=message):
        _build()


def test_direct_execution_scope_requires_exactly_one_membership() -> None:
    """direct request가 membership 2건이면 첫 건을 임의로 고르지 않고 죽는다."""
    request = repo._rows_to_request([_row(membership=_membership())])
    ambiguous = repo.FeatureUpdateRequest(
        **{
            **request.__dict__,
            "dataset_membership_mode": "multiple",
            "dataset_memberships": (
                _membership(),
                _membership(provider_dataset_id=18),
            ),
        }
    )

    with pytest.raises(RuntimeError, match="requires exactly one membership"):
        repo.execution_scope_for_request(ambiguous)

    empty = repo.FeatureUpdateRequest(
        **{**request.__dict__, "dataset_memberships": ()}
    )
    with pytest.raises(RuntimeError, match="requires exactly one membership"):
        repo.execution_scope_for_request(empty)


def _match(provider_dataset_id: int, feature_id: str) -> CacheTargetFeatureMatch:
    return CacheTargetFeatureMatch(
        target_id="target-1",
        feature_id=feature_id,
        provider_dataset_id=provider_dataset_id,
        provider="python-test-api",
        dataset_key="test-dataset",
        distance_m=1.0,
        relation="within_radius",
    )


def test_cache_target_matches_stay_inside_their_own_dataset() -> None:
    """POI cache target link 재작성 대상은 그 dataset의 match만 받아야 한다.

    필터가 사라지면 A dataset의 refresh scope가 B dataset의 target match까지
    target_ids/link 재작성 목록에 싣는다.
    """
    resolution = ScopeResolution(
        scope_type="cache_target_keys",
        features=(),
        cache_target_matches=(
            _match(17, "feature-own"),
            _match(18, "feature-foreign"),
            _match(None, "feature-unlinked"),  # type: ignore[arg-type]
        ),
    )

    own = executor._target_matches_for_provider(resolution, provider_dataset_id=17)

    assert [match.feature_id for match in own] == ["feature-own"]


def _stub_job(mode: str, member_ids: tuple[str, ...]) -> SimpleNamespace:
    return SimpleNamespace(
        dataset_membership_mode=mode,
        dataset_memberships=tuple(
            SimpleNamespace(import_job_dataset_id=member_id) for member_id in member_ids
        ),
    )


@pytest.mark.parametrize(
    ("job", "expected"),
    [
        (None, (None,)),
        (_stub_job("root", ()), (None,)),
        # docstring이 명시적으로 부정하는 fail-open: member가 비었는데 조용히
        # 건너뛰면 terminal event가 통째로 사라진다.
        (_stub_job("single", ()), (None,)),
        (_stub_job("multiple", ()), (None,)),
        (_stub_job("single", ("member-1",)), ("member-1",)),
        (_stub_job("multiple", ("member-1", "member-2")), ("member-1", "member-2")),
    ],
)
def test_terminal_event_member_ids_never_silently_skips(
    monkeypatch: pytest.MonkeyPatch,
    job: object,
    expected: tuple[str | None, ...],
) -> None:
    async def _fake_get_import_job(_session: object, _job_id: str) -> object:
        return job

    monkeypatch.setattr(executor, "get_import_job", _fake_get_import_job)

    assert (
        asyncio.run(executor._terminal_event_member_ids(object(), "job-1")) == expected
    )
