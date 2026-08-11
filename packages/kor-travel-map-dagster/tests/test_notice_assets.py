"""KREX notice Dagster asset의 snapshot reconcile 순서 회귀 테스트."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, cast

import pytest
from dagster import build_asset_context
from kortravelmap.client import IntegrityFindingSyncResult
from kortravelmap.core.feature_operation import ProviderDatasetOperationMembership
from kortravelmap.infra.feature_repo import (
    FeatureLoadResult,
    NoticeFeatureLoadResult,
    NoticeReconcileResult,
)

from kortravelmap.dagster import assets as assets_module
from kortravelmap.dagster.assets import (
    KREX_NOTICE_PROVIDER_RUN_LOCK,
    run_feature_notice_krex_traffic_notices,
)
from kortravelmap.dagster.feature_operation_tracking import (
    FeatureOperationExecutionGuard,
)

_KST = timezone(timedelta(hours=9))
_FETCHED_AT = datetime(2026, 7, 13, 12, 0, tzinfo=_KST)

# T-VN-33: sync state의 정체성은 (provider_dataset_id, sync_scope, operation_key)다
# (ADR-088). asset은 provider/dataset label에서 이 행을 역산하지 않고 feature
# operation guard가 고정한 membership만 쓴다 — asset 이름과 operation key는
# registry에서 1:1(`run_<asset>` ↔ `<asset>_job`)이다.
_OPERATION_KEY = "feature_notice_krex_traffic_notices_job"
_MEMBERSHIP = ProviderDatasetOperationMembership(
    provider_dataset_id=4101,
    sync_scope="dataset_wide",
    operation_key=_OPERATION_KEY,
)
# ``build_asset_context``로 직접 호출한 asset의 Dagster run id. guard는 실행 run과
# 다른 run에서 온 snapshot을 거부하므로(``require_feature_operation_guard`` →
# ``run_id_mismatch``) 테스트 guard도 이 run id를 써야 한다.
_DIRECT_INVOCATION_RUN_ID = "EPHEMERAL"


class _Client:
    def __init__(self, *, reconcile_error: Exception | None = None) -> None:
        self.reconcile_error = reconcile_error
        self.events: list[str] = []
        self.success_calls: list[dict[str, Any]] = []
        self.resolve_membership_calls: list[str] = []
        self.resolve_dataset_membership_calls: list[dict[str, Any]] = []
        self.state_calls: list[ProviderDatasetOperationMembership] = []

    @asynccontextmanager
    async def provider_run_lock(self, key: str) -> AsyncIterator[None]:
        self.events.append(f"lock:{key}")
        try:
            yield
        finally:
            self.events.append(f"unlock:{key}")

    async def resolve_feature_operation_memberships(
        self, *, operation_key: str
    ) -> tuple[ProviderDatasetOperationMembership, ...]:
        self.resolve_membership_calls.append(operation_key)
        return (_MEMBERSHIP,)

    async def resolve_feature_operation_dataset_membership(
        self, *, operation_key: str, provider: str, dataset_key: str
    ) -> ProviderDatasetOperationMembership:
        self.resolve_dataset_membership_calls.append(
            {
                "operation_key": operation_key,
                "provider": provider,
                "dataset_key": dataset_key,
            }
        )
        return _MEMBERSHIP

    async def get_sync_state_for_operation_membership(
        self, *, membership: ProviderDatasetOperationMembership
    ) -> Any | None:
        self.state_calls.append(membership)
        return None

    async def load_feature_bundles(self, bundles: Any) -> FeatureLoadResult:
        materialized = list(bundles)
        self.events.append("load")
        return FeatureLoadResult(bundles_total=len(materialized))

    async def load_authoritative_notice_snapshot(
        self,
        *,
        bundles: Any,
        provider: str,
        dataset_key: str,
        source_entity_type: str,
        active_lineage_keys: set[str],
        observed_at: datetime,
    ) -> NoticeFeatureLoadResult:
        materialized = list(bundles)
        self.events.append("atomic_notice")
        assert provider == "python-krex-api"
        assert dataset_key == "krex_traffic_notices"
        assert source_entity_type == "traffic_notice"
        assert active_lineage_keys == set()
        assert observed_at == _FETCHED_AT
        if self.reconcile_error is not None:
            raise self.reconcile_error
        return NoticeFeatureLoadResult(
            load=FeatureLoadResult(bundles_total=len(materialized)),
            reconcile=NoticeReconcileResult(closed=2),
        )

    async def record_sync_success(self, **kwargs: Any) -> None:
        """T-VN-33 이전의 provider/dataset label write 경로.

        ``_record_feature_sync_success``가 sync-state 기록 능력을 이 이름으로만
        판별하고(있으면 진행, 없으면 조용히 생략) 실제 write는 membership API로
        한다. 이 double에서 호출되면 label 경로로 되돌아간 회귀다.
        """
        raise AssertionError("label 기반 record_sync_success가 호출되면 안 된다")

    async def record_sync_success_for_operation_membership(
        self,
        *,
        membership: ProviderDatasetOperationMembership,
        cursor: dict[str, Any],
    ) -> None:
        self.events.append("sync_success")
        self.success_calls.append({"membership": membership, "cursor": cursor})

    async def record_address_validation_findings(
        self, findings: object, **kwargs: object
    ) -> IntegrityFindingSyncResult:
        """T-VN-H30A: durable finding 기록 (테스트 double은 보관만 한다)."""
        self.recorded_findings = list(findings)  # type: ignore[arg-type]
        count = len(self.recorded_findings)
        return IntegrityFindingSyncResult(count, count, count)


class _WatermarkClient(_Client):
    def __init__(self, watermark: datetime) -> None:
        super().__init__()
        self.watermark = watermark

    async def get_sync_state_for_operation_membership(
        self, *, membership: ProviderDatasetOperationMembership
    ) -> Any:
        self.events.append("sync_watermark")
        self.state_calls.append(membership)
        return SimpleNamespace(cursor={"snapshot_applied_at": self.watermark.isoformat()})

    async def get_notice_snapshot_watermark(
        self,
        *,
        provider: str,
        dataset_key: str,
        source_entity_type: str,
    ) -> datetime:
        self.events.append("scope_watermark")
        assert provider == "python-krex-api"
        assert dataset_key == "krex_traffic_notices"
        assert source_entity_type == "traffic_notice"
        return self.watermark


def _guard(client: _Client) -> FeatureOperationExecutionGuard:
    """프로덕션에서 ``run_tracked_feature_asset``이 주입하는 실행 guard."""
    return FeatureOperationExecutionGuard(
        client=cast(Any, client),
        instance=None,
        operation_key=_OPERATION_KEY,
        memberships=(_MEMBERSHIP,),
        dagster_run_id=_DIRECT_INVOCATION_RUN_ID,
        trigger_kind="schedule",
    )


def _context(
    client: _Client,
    *,
    reverse_geocoder: Any = None,
    notices: Any = (),
) -> Any:
    return build_asset_context(
        resources={
            "kor_travel_map_client": client,
            "reverse_geocoder": reverse_geocoder,
            "fetched_at": _FETCHED_AT,
            "strict_address": True,
            "krex_traffic_notices": notices,
            "feature_operation_guard": _guard(client),
        }
    )


async def test_empty_snapshot_reconciles_before_sync_success() -> None:
    client = _Client()

    result = await run_feature_notice_krex_traffic_notices(_context(client))

    assert result.load.bundles_total == 0
    assert client.events == [
        f"lock:{KREX_NOTICE_PROVIDER_RUN_LOCK}",
        "atomic_notice",
        "sync_success",
        f"unlock:{KREX_NOTICE_PROVIDER_RUN_LOCK}",
    ]
    [success] = client.success_calls
    assert success["cursor"]["notices_closed"] == 2


async def test_sync_state_is_read_and_written_on_the_guarded_membership() -> None:
    """T-VN-33: sync cursor read/write는 guard가 고정한 exact membership에만 간다."""
    client = _Client()

    await run_feature_notice_krex_traffic_notices(_context(client))

    assert client.resolve_membership_calls == [_OPERATION_KEY, _OPERATION_KEY]
    assert client.resolve_dataset_membership_calls == [
        {
            "operation_key": _OPERATION_KEY,
            "provider": "python-krex-api",
            "dataset_key": "krex_traffic_notices",
        }
    ] * 2
    assert client.state_calls == [_MEMBERSHIP]
    [success] = client.success_calls
    assert success["membership"] == _MEMBERSHIP


async def test_reconcile_failure_does_not_record_sync_success() -> None:
    client = _Client(reconcile_error=RuntimeError("reconcile failed"))

    with pytest.raises(RuntimeError, match="reconcile failed"):
        await run_feature_notice_krex_traffic_notices(_context(client))

    assert client.events == [
        f"lock:{KREX_NOTICE_PROVIDER_RUN_LOCK}",
        "atomic_notice",
        f"unlock:{KREX_NOTICE_PROVIDER_RUN_LOCK}",
    ]
    assert client.success_calls == []


async def test_older_snapshot_fails_before_destructive_load() -> None:
    client = _WatermarkClient(_FETCHED_AT + timedelta(minutes=10))

    with pytest.raises(RuntimeError, match="watermark보다 과거"):
        await run_feature_notice_krex_traffic_notices(_context(client))

    assert client.events == [
        f"lock:{KREX_NOTICE_PROVIDER_RUN_LOCK}",
        "scope_watermark",
        "sync_watermark",
        f"unlock:{KREX_NOTICE_PROVIDER_RUN_LOCK}",
    ]
    assert client.success_calls == []


async def test_same_snapshot_reaches_core_fingerprint_cas() -> None:
    client = _WatermarkClient(_FETCHED_AT)

    await run_feature_notice_krex_traffic_notices(_context(client))

    assert client.events == [
        f"lock:{KREX_NOTICE_PROVIDER_RUN_LOCK}",
        "scope_watermark",
        "sync_watermark",
        "atomic_notice",
        "sync_success",
        f"unlock:{KREX_NOTICE_PROVIDER_RUN_LOCK}",
    ]


async def test_newer_snapshot_records_applied_watermark() -> None:
    client = _WatermarkClient(_FETCHED_AT - timedelta(minutes=10))

    await run_feature_notice_krex_traffic_notices(_context(client))

    assert client.events == [
        f"lock:{KREX_NOTICE_PROVIDER_RUN_LOCK}",
        "scope_watermark",
        "sync_watermark",
        "atomic_notice",
        "sync_success",
        f"unlock:{KREX_NOTICE_PROVIDER_RUN_LOCK}",
    ]
    [success] = client.success_calls
    assert success["cursor"]["snapshot_applied_at"] == _FETCHED_AT.isoformat()


async def test_notice_critical_path_skips_reverse_geocoding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen_reverse_geocoders: list[Any] = []

    async def _convert(
        items: Any,
        *,
        fetched_at: datetime,
        reverse_geocoder: Any,
    ) -> list[Any]:
        assert list(items) == []
        assert fetched_at == _FETCHED_AT
        seen_reverse_geocoders.append(reverse_geocoder)
        return []

    monkeypatch.setattr(assets_module, "traffic_notices_to_bundles", _convert)
    client = _Client()

    await run_feature_notice_krex_traffic_notices(_context(client, reverse_geocoder=object()))

    assert seen_reverse_geocoders == [None]


async def test_incomplete_snapshot_fetch_does_not_reconcile() -> None:
    class _BrokenSnapshot:
        def __iter__(self) -> Any:
            yield object()
            raise RuntimeError("중복 사건 identity")

    client = _Client()

    with pytest.raises(RuntimeError, match="중복 사건 identity"):
        await run_feature_notice_krex_traffic_notices(_context(client, notices=_BrokenSnapshot()))

    assert client.events == [
        f"lock:{KREX_NOTICE_PROVIDER_RUN_LOCK}",
        f"unlock:{KREX_NOTICE_PROVIDER_RUN_LOCK}",
    ]
    assert client.success_calls == []
