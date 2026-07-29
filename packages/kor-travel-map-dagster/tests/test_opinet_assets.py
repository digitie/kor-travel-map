"""OpiNet 가격 asset의 실패/성공 판정 회귀 테스트."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from dagster import build_asset_context
from kortravelmap.dto import PriceValue
from kortravelmap.infra.feature_repo import FeatureLoadResult
from kortravelmap.infra.price_repo import PriceFeatureLoadResult

from kortravelmap.dagster import assets as assets_module
from kortravelmap.dagster.assets import (
    OPINET_PROVIDER_RUN_LOCK,
    run_feature_place_opinet_stations,
    run_feature_price_opinet_stations,
)

_KST = timezone(timedelta(hours=9))


class _Client:
    def __init__(
        self,
        *,
        last_success_at: datetime | None = None,
        sync_cursor: dict[str, object] | None = None,
    ) -> None:
        self.events: list[str] = []
        self.sync_success_calls: list[dict[str, Any]] = []
        self.loaded_price_values: list[PriceValue] = []
        self.last_success_at = last_success_at
        self.sync_cursor = sync_cursor

    @asynccontextmanager
    async def provider_run_lock(self, key: str) -> AsyncIterator[None]:
        self.events.append(f"lock:{key}")
        try:
            yield
        finally:
            self.events.append(f"unlock:{key}")

    async def load_feature_bundles(self, bundles: Any) -> FeatureLoadResult:
        materialized = list(bundles)
        self.events.append("load")
        return FeatureLoadResult(bundles_total=len(materialized))

    async def load_price_features(self, bundles: Any, values: Any) -> PriceFeatureLoadResult:
        materialized_bundles = list(bundles)
        self.loaded_price_values = list(values)
        self.events.append("load_price")
        return PriceFeatureLoadResult(
            features=FeatureLoadResult(bundles_total=len(materialized_bundles)),
            price_values=len(self.loaded_price_values),
        )

    async def record_sync_success(self, **kwargs: Any) -> None:
        self.events.append("sync_success")
        self.sync_success_calls.append(kwargs)

    async def get_sync_state(self, **_kwargs: Any) -> Any:
        if self.last_success_at is None:
            return None
        return SimpleNamespace(
            last_success_at=self.last_success_at,
            cursor=self.sync_cursor,
        )

    async def record_address_validation_findings(
        self, findings: object, **kwargs: object
    ) -> int:
        """T-VN-H30A: durable finding 기록 (테스트 double은 보관만 한다)."""
        self.recorded_findings = list(findings)  # type: ignore[arg-type]
        return len(self.recorded_findings)


async def test_price_asset_rejects_whole_run_zero_without_sync_success() -> None:
    client = _Client()
    context = build_asset_context(
        resources={
            "kor_travel_map_client": client,
            "reverse_geocoder": None,
            "fetched_at": datetime(2026, 7, 13, 18, 18, tzinfo=_KST),
            "strict_address": True,
            "opinet_station_price_details": [],
        }
    )

    with pytest.raises(RuntimeError, match="전체 scope에서 0건"):
        await run_feature_price_opinet_stations(context)

    assert client.events == [
        f"lock:{OPINET_PROVIDER_RUN_LOCK}",
        f"unlock:{OPINET_PROVIDER_RUN_LOCK}",
    ]
    assert client.sync_success_calls == []


async def test_price_asset_rejects_nonempty_records_normalized_to_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _convert(*_args: Any, **_kwargs: Any) -> tuple[list[Any], list[Any], list[Any]]:
        return [object()], [object()], []

    monkeypatch.setattr(
        assets_module,
        "station_details_to_price_features_and_values",
        _convert,
    )
    client = _Client()
    context = build_asset_context(
        resources={
            "kor_travel_map_client": client,
            "reverse_geocoder": None,
            "fetched_at": datetime(2026, 7, 13, 18, 18, tzinfo=_KST),
            "strict_address": True,
            "opinet_station_price_details": [SimpleNamespace(prices=())],
        }
    )

    with pytest.raises(RuntimeError, match="PriceValue로 0건 변환"):
        await run_feature_price_opinet_stations(context)

    assert client.events == [
        f"lock:{OPINET_PROVIDER_RUN_LOCK}",
        f"unlock:{OPINET_PROVIDER_RUN_LOCK}",
    ]
    assert client.loaded_price_values == []
    assert client.sync_success_calls == []


async def test_price_asset_records_kst_observation_freshness_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetched_at = datetime(2026, 7, 13, 18, 18, tzinfo=_KST)
    observations = (
        datetime(2026, 7, 13, 1, 0, tzinfo=UTC),
        datetime(2026, 7, 13, 23, 0, tzinfo=_KST),
        datetime(2026, 7, 12, 23, 59, tzinfo=_KST),
    )
    values = [
        PriceValue(
            feature_id=f"price-{index}",
            provider="python-opinet-api",
            price_domain="opinet_gas_station",
            product_key="gasoline",
            value_number=Decimal("1700"),
            unit="KRW/L",
            observed_at=observed_at,
            collected_at=fetched_at,
        )
        for index, observed_at in enumerate(observations)
    ]

    async def _convert(
        *_args: Any, **_kwargs: Any
    ) -> tuple[list[Any], list[Any], list[PriceValue]]:
        return [object()], [object()], values

    output_metadata: dict[str, object] = {}
    monkeypatch.setattr(
        assets_module,
        "station_details_to_price_features_and_values",
        _convert,
    )
    monkeypatch.setattr(
        assets_module,
        "_add_output_metadata",
        lambda _context, metadata: output_metadata.update(metadata),
    )
    client = _Client()
    context = build_asset_context(
        resources={
            "kor_travel_map_client": client,
            "reverse_geocoder": None,
            "fetched_at": fetched_at,
            "strict_address": True,
            "opinet_station_price_details": [SimpleNamespace(prices=())],
        }
    )

    result = await run_feature_price_opinet_stations(context)

    assert result.price_values == 3
    assert client.events == [
        f"lock:{OPINET_PROVIDER_RUN_LOCK}",
        "load",
        "load_price",
        "sync_success",
        f"unlock:{OPINET_PROVIDER_RUN_LOCK}",
    ]
    cursor = client.sync_success_calls[0]["cursor"]
    assert cursor["latest_observed_at"] == "2026-07-13T23:00:00+09:00"
    assert cursor["today_values_count"] == 2
    assert output_metadata["latest_observed_at"] == "2026-07-13T23:00:00+09:00"
    assert output_metadata["today_values_count"] == 2


async def test_place_asset_holds_same_provider_lock_through_sync_success() -> None:
    client = _Client()
    context = build_asset_context(
        resources={
            "kor_travel_map_client": client,
            "reverse_geocoder": None,
            "fetched_at": datetime(2026, 7, 13, 18, 18, tzinfo=_KST),
            "strict_address": True,
            "opinet_stations": [],
        }
    )

    result = await run_feature_place_opinet_stations(context)

    assert result.load.bundles_total == 0
    assert client.events == [
        f"lock:{OPINET_PROVIDER_RUN_LOCK}",
        "load",
        "sync_success",
        f"unlock:{OPINET_PROVIDER_RUN_LOCK}",
    ]


class _NeverConsumed:
    def __iter__(self) -> Any:
        raise AssertionError("KST 당일 coalescing은 provider record를 소비하면 안 된다.")


async def test_price_asset_coalesces_same_kst_day_before_provider_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetched_at = datetime(2026, 7, 13, 18, 18, tzinfo=_KST)
    client = _Client(
        last_success_at=fetched_at - timedelta(hours=1),
        sync_cursor={
            "loaded_at": fetched_at.isoformat(),
            "today_values_count": 1,
            "price_values_upserted": 1,
            "latest_observed_at": fetched_at.isoformat(),
        },
    )
    output_metadata: dict[str, object] = {}
    monkeypatch.setattr(
        assets_module,
        "_add_output_metadata",
        lambda _context, metadata: output_metadata.update(metadata),
    )
    context = build_asset_context(
        resources={
            "kor_travel_map_client": client,
            "reverse_geocoder": None,
            "fetched_at": fetched_at,
            "strict_address": True,
            "opinet_station_price_details": _NeverConsumed(),
        }
    )

    result = await run_feature_price_opinet_stations(context)

    assert result.price_values == 0
    assert client.events == [
        f"lock:{OPINET_PROVIDER_RUN_LOCK}",
        f"unlock:{OPINET_PROVIDER_RUN_LOCK}",
    ]
    assert output_metadata["skipped"] is True
    assert output_metadata["skip_reason"] == "already_succeeded_today_kst"
    assert client.sync_success_calls == []


async def test_price_asset_does_not_coalesce_same_day_without_current_observation() -> None:
    fetched_at = datetime(2026, 7, 13, 18, 18, tzinfo=_KST)
    client = _Client(
        last_success_at=fetched_at - timedelta(hours=1),
        sync_cursor={
            "loaded_at": fetched_at.isoformat(),
            "today_values_count": 0,
            "price_values_upserted": 1,
            "latest_observed_at": (fetched_at - timedelta(days=1)).isoformat(),
        },
    )
    context = build_asset_context(
        resources={
            "kor_travel_map_client": client,
            "reverse_geocoder": None,
            "fetched_at": fetched_at,
            "strict_address": True,
            "opinet_station_price_details": [],
        }
    )

    with pytest.raises(RuntimeError, match="전체 scope에서 0건"):
        await run_feature_price_opinet_stations(context)

    assert client.events == [
        f"lock:{OPINET_PROVIDER_RUN_LOCK}",
        f"unlock:{OPINET_PROVIDER_RUN_LOCK}",
    ]


async def test_price_asset_does_not_coalesce_mixed_current_and_old_observations() -> None:
    fetched_at = datetime(2026, 7, 13, 18, 18, tzinfo=_KST)
    client = _Client(
        last_success_at=fetched_at - timedelta(hours=1),
        sync_cursor={
            "loaded_at": fetched_at.isoformat(),
            "today_values_count": 1,
            "price_values_upserted": 2,
            "latest_observed_at": fetched_at.isoformat(),
        },
    )
    context = build_asset_context(
        resources={
            "kor_travel_map_client": client,
            "reverse_geocoder": None,
            "fetched_at": fetched_at,
            "strict_address": True,
            "opinet_station_price_details": [],
        }
    )

    with pytest.raises(RuntimeError, match="전체 scope에서 0건"):
        await run_feature_price_opinet_stations(context)

    assert client.events == [
        f"lock:{OPINET_PROVIDER_RUN_LOCK}",
        f"unlock:{OPINET_PROVIDER_RUN_LOCK}",
    ]


async def test_price_asset_does_not_coalesce_run_that_crossed_kst_midnight() -> None:
    fetched_at = datetime(2026, 7, 14, 18, 18, tzinfo=_KST)
    previous_run_started = datetime(2026, 7, 13, 23, 59, tzinfo=_KST)
    client = _Client(
        last_success_at=datetime(2026, 7, 14, 0, 1, tzinfo=_KST),
        sync_cursor={
            "loaded_at": previous_run_started.isoformat(),
            "today_values_count": 1,
            "price_values_upserted": 1,
            "latest_observed_at": previous_run_started.isoformat(),
        },
    )
    context = build_asset_context(
        resources={
            "kor_travel_map_client": client,
            "reverse_geocoder": None,
            "fetched_at": fetched_at,
            "strict_address": True,
            "opinet_station_price_details": [],
        }
    )

    with pytest.raises(RuntimeError, match="전체 scope에서 0건"):
        await run_feature_price_opinet_stations(context)

    assert client.events == [
        f"lock:{OPINET_PROVIDER_RUN_LOCK}",
        f"unlock:{OPINET_PROVIDER_RUN_LOCK}",
    ]


async def test_place_asset_coalesces_same_kst_day_before_provider_fetch() -> None:
    fetched_at = datetime(2026, 7, 13, 18, 18, tzinfo=_KST)
    client = _Client(
        last_success_at=fetched_at - timedelta(hours=1),
        sync_cursor={"loaded_at": fetched_at.isoformat()},
    )
    context = build_asset_context(
        resources={
            "kor_travel_map_client": client,
            "reverse_geocoder": None,
            "fetched_at": fetched_at,
            "strict_address": True,
            "opinet_stations": _NeverConsumed(),
        }
    )

    result = await run_feature_place_opinet_stations(context)

    assert result.load.bundles_total == 0
    assert client.events == [
        f"lock:{OPINET_PROVIDER_RUN_LOCK}",
        "load",
        f"unlock:{OPINET_PROVIDER_RUN_LOCK}",
    ]
    assert client.sync_success_calls == []
