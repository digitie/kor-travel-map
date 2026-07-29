"""KREX notice Dagster asset의 snapshot reconcile 순서 회귀 테스트."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import pytest
from dagster import build_asset_context
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

_KST = timezone(timedelta(hours=9))
_FETCHED_AT = datetime(2026, 7, 13, 12, 0, tzinfo=_KST)


class _Client:
    def __init__(self, *, reconcile_error: Exception | None = None) -> None:
        self.reconcile_error = reconcile_error
        self.events: list[str] = []
        self.success_calls: list[dict[str, Any]] = []

    @asynccontextmanager
    async def provider_run_lock(self, key: str) -> AsyncIterator[None]:
        self.events.append(f"lock:{key}")
        try:
            yield
        finally:
            self.events.append(f"unlock:{key}")

    async def get_sync_state(self, *, provider: str, dataset_key: str) -> None:
        assert provider == "python-krex-api"
        assert dataset_key == "krex_traffic_notices"

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

    async def record_sync_success(
        self,
        *,
        provider: str,
        dataset_key: str,
        cursor: dict[str, Any],
    ) -> None:
        self.events.append("sync_success")
        self.success_calls.append(
            {
                "provider": provider,
                "dataset_key": dataset_key,
                "cursor": cursor,
            }
        )

    async def record_address_validation_findings(self, findings: object) -> int:
        """T-VN-H30A: durable finding 기록 (테스트 double은 보관만 한다)."""
        self.recorded_findings = list(findings)  # type: ignore[arg-type]
        return len(self.recorded_findings)


class _WatermarkClient(_Client):
    def __init__(self, watermark: datetime) -> None:
        super().__init__()
        self.watermark = watermark

    async def get_sync_state(self, *, provider: str, dataset_key: str) -> Any:
        self.events.append("sync_watermark")
        assert provider == "python-krex-api"
        assert dataset_key == "krex_traffic_notices"
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
