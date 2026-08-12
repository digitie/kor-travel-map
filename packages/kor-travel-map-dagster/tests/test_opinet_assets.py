"""OpiNet 가격 asset의 실패/성공 판정 회귀 테스트."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta, timezone
from decimal import Decimal
from types import MappingProxyType, SimpleNamespace
from typing import Any, Final, cast

import pytest
from dagster import build_asset_context
from kortravelmap.client import AsyncKorTravelMapClient, IntegrityFindingSyncResult
from kortravelmap.core.feature_operation import ProviderDatasetOperationMembership
from kortravelmap.dto import PriceValue
from kortravelmap.infra.feature_repo import FeatureLoadResult
from kortravelmap.infra.price_repo import PriceFeatureLoadResult
from kortravelmap.providers.opinet import (
    OPINET_PRICE_DATASET_KEY,
    OPINET_PROVIDER_NAME,
    OPINET_STATION_DATASET_KEY,
)

from kortravelmap.dagster import assets as assets_module
from kortravelmap.dagster.assets import (
    OPINET_PROVIDER_RUN_LOCK,
    run_feature_place_opinet_stations,
    run_feature_price_opinet_stations,
)
from kortravelmap.dagster.feature_operation_tracking import (
    FeatureOperationExecutionGuard,
)

_KST = timezone(timedelta(hours=9))
# ``build_asset_context()``로 직접 호출한 asset의 run id. guard는 자기가 지키는
# run과 같은 id를 들고 있어야 한다 — 다르면 ``run_id_mismatch``로 거부된다.
_RUN_ID: Final = "EPHEMERAL"
# asset 이름 ↔ operation key는 registry에서 1:1이다(`run_<asset>` ↔ `<asset>_job`).
_PLACE_OPERATION_KEY: Final = "feature_place_opinet_stations_job"
_PRICE_OPERATION_KEY: Final = "feature_price_opinet_stations_job"
# T-VN-33 이후 sync state row는 provider/dataset label이 아니라
# provider_dataset_id로 식별된다(ADR-088). 테스트 double은 dataset key 하나에
# 안정적인 surrogate id 하나를 대응시킨다.
_PROVIDER_DATASET_IDS: Final[dict[str, int]] = {
    OPINET_STATION_DATASET_KEY: 9101,
    OPINET_PRICE_DATASET_KEY: 9102,
}


@dataclass(frozen=True)
class _StationPriceDetail:
    """source record에도 그대로 보존 가능한 OpiNet 상세 응답 test double."""

    prices: tuple[object, ...] = ()


@dataclass(frozen=True)
class _FrozenPrice:
    trade_date: date
    trade_time: time
    raw: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))


@dataclass(frozen=True)
class _FrozenStationDetail:
    prices: tuple[_FrozenPrice, ...]
    raw: Mapping[str, Any]


def test_source_record_payload_preserves_frozen_opinet_detail_without_deepcopy() -> None:
    """실제 OpiNet detail의 ``MappingProxyType`` raw도 source receipt가 된다."""

    detail = _FrozenStationDetail(
        prices=(
            _FrozenPrice(
                trade_date=date(2026, 8, 12),
                trade_time=time(9, 30),
                raw=MappingProxyType({"PRODCD": "B027"}),
            ),
        ),
        raw=MappingProxyType({"UNI_ID": "A123", "nested": {"value": "kept"}}),
    )

    assert assets_module._response_payload_item(detail) == {
        "prices": [
            {
                "trade_date": "2026-08-12",
                "trade_time": "09:30:00",
                "raw": {"PRODCD": "B027"},
            }
        ],
        "raw": {"UNI_ID": "A123", "nested": {"value": "kept"}},
    }


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
        self.price_write_context: dict[str, Any] | None = None
        self.last_success_at = last_success_at
        self.sync_cursor = sync_cursor
        self.sync_state_reads: list[ProviderDatasetOperationMembership] = []
        self._memberships: dict[str, tuple[ProviderDatasetOperationMembership, ...]] = {}
        self._dataset_memberships: dict[
            tuple[str, str], ProviderDatasetOperationMembership
        ] = {}

    def guard_for(
        self, operation_key: str, dataset_key: str
    ) -> FeatureOperationExecutionGuard:
        """asset이 sync-state를 읽고 쓰려면 feature-operation guard가 있어야 한다.

        프로덕션에서는 ``run_tracked_feature_asset``이 실행 시작 시 넣는다. sync
        state 정체성이 ``provider_dataset_id + sync_scope + operation_key`` triple이
        된 뒤(ADR-088) provider/dataset label로는 어느 행인지 결정되지 않으므로,
        asset을 직접 호출하는 테스트도 실행 대상 operation을 똑같이 선언한다.
        """
        membership = ProviderDatasetOperationMembership(
            provider_dataset_id=_PROVIDER_DATASET_IDS[dataset_key],
            sync_scope="dataset_wide",
            operation_key=operation_key,
        )
        self._memberships[operation_key] = (membership,)
        self._dataset_memberships[(operation_key, dataset_key)] = membership
        return FeatureOperationExecutionGuard(
            client=cast("AsyncKorTravelMapClient", self),
            instance=None,
            operation_key=operation_key,
            memberships=(membership,),
            dagster_run_id=_RUN_ID,
            trigger_kind="schedule",
        )

    async def resolve_feature_operation_memberships(
        self, *, operation_key: str
    ) -> tuple[ProviderDatasetOperationMembership, ...]:
        return self._memberships[operation_key]

    async def resolve_feature_operation_dataset_membership(
        self, *, operation_key: str, provider: str, dataset_key: str
    ) -> ProviderDatasetOperationMembership:
        assert provider == OPINET_PROVIDER_NAME
        return self._dataset_memberships[(operation_key, dataset_key)]

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

    async def load_price_features(
        self, bundles: Any, values: Any, **kwargs: Any
    ) -> PriceFeatureLoadResult:
        materialized_bundles = list(bundles)
        self.loaded_price_values = list(values)
        self.price_write_context = kwargs
        self.events.append("load_price")
        return PriceFeatureLoadResult(
            features=FeatureLoadResult(bundles_total=len(materialized_bundles)),
            price_values=len(self.loaded_price_values),
        )

    async def record_sync_success(self, **_kwargs: Any) -> None:
        """legacy capability probe 전용.

        ``_record_feature_sync_success``는 지금도 이 이름의 존재로 "sync state를
        쓸 수 있는 client인가"를 판정한 뒤 실제 기록은
        ``record_sync_success_for_operation_membership``으로 한다. 이 double이
        이름을 지우면 asset이 조용히 기록을 건너뛰므로 남겨 둔다.
        """
        raise AssertionError(
            "T-VN-33 이후 asset은 membership 기반 기록만 해야 한다."
        )

    async def record_sync_success_for_operation_membership(
        self, **kwargs: Any
    ) -> None:
        self.events.append("sync_success")
        self.sync_success_calls.append(kwargs)

    async def get_sync_state_for_operation_membership(
        self, *, membership: ProviderDatasetOperationMembership
    ) -> Any:
        self.sync_state_reads.append(membership)
        if self.last_success_at is None:
            return None
        return SimpleNamespace(
            last_success_at=self.last_success_at,
            cursor=self.sync_cursor,
        )

    async def record_address_validation_findings(
        self, findings: Iterable[object], **kwargs: object
    ) -> IntegrityFindingSyncResult:
        """T-VN-H30A: durable finding 기록 (테스트 double은 보관만 한다)."""
        self.recorded_findings = list(findings)
        count = len(self.recorded_findings)
        return IntegrityFindingSyncResult(count, count, count)


async def test_price_asset_rejects_whole_run_zero_without_sync_success() -> None:
    client = _Client()
    context = build_asset_context(
        resources={
            "kor_travel_map_client": client,
            "reverse_geocoder": None,
            "fetched_at": datetime(2026, 7, 13, 18, 18, tzinfo=_KST),
            "strict_address": True,
            "feature_operation_guard": client.guard_for(
                _PRICE_OPERATION_KEY, OPINET_PRICE_DATASET_KEY
            ),
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
            "feature_operation_guard": client.guard_for(
                _PRICE_OPERATION_KEY, OPINET_PRICE_DATASET_KEY
            ),
            "opinet_station_price_details": [_StationPriceDetail()],
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
            "feature_operation_guard": client.guard_for(
                _PRICE_OPERATION_KEY, OPINET_PRICE_DATASET_KEY
            ),
            "opinet_station_price_details": [_StationPriceDetail()],
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
    # cursor는 label이 아니라 guard가 고정한 exact membership 행에 적힌다(ADR-088).
    assert client.sync_success_calls[0]["membership"] == ProviderDatasetOperationMembership(
        provider_dataset_id=_PROVIDER_DATASET_IDS[OPINET_PRICE_DATASET_KEY],
        sync_scope="dataset_wide",
        operation_key=_PRICE_OPERATION_KEY,
    )
    cursor = client.sync_success_calls[0]["cursor"]
    assert cursor["latest_observed_at"] == "2026-07-13T23:00:00+09:00"
    assert cursor["today_values_count"] == 2
    assert output_metadata["latest_observed_at"] == "2026-07-13T23:00:00+09:00"
    assert output_metadata["today_values_count"] == 2
    assert client.price_write_context is not None
    source_record = client.price_write_context["source_record"]
    # source record payload는 immutable hash 전에 canonical JSON 형태로 정규화된다.
    assert source_record.raw_data["records"] == [{"prices": []}]


async def test_place_asset_holds_same_provider_lock_through_sync_success() -> None:
    client = _Client()
    context = build_asset_context(
        resources={
            "kor_travel_map_client": client,
            "reverse_geocoder": None,
            "fetched_at": datetime(2026, 7, 13, 18, 18, tzinfo=_KST),
            "strict_address": True,
            "feature_operation_guard": client.guard_for(
                _PLACE_OPERATION_KEY, OPINET_STATION_DATASET_KEY
            ),
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
            "feature_operation_guard": client.guard_for(
                _PRICE_OPERATION_KEY, OPINET_PRICE_DATASET_KEY
            ),
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
    # coalescing 판단도 label이 아니라 exact membership 행을 읽고 내린다(ADR-088).
    assert client.sync_state_reads == [
        ProviderDatasetOperationMembership(
            provider_dataset_id=_PROVIDER_DATASET_IDS[OPINET_PRICE_DATASET_KEY],
            sync_scope="dataset_wide",
            operation_key=_PRICE_OPERATION_KEY,
        )
    ]


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
            "feature_operation_guard": client.guard_for(
                _PRICE_OPERATION_KEY, OPINET_PRICE_DATASET_KEY
            ),
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
            "feature_operation_guard": client.guard_for(
                _PRICE_OPERATION_KEY, OPINET_PRICE_DATASET_KEY
            ),
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
            "feature_operation_guard": client.guard_for(
                _PRICE_OPERATION_KEY, OPINET_PRICE_DATASET_KEY
            ),
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
            "feature_operation_guard": client.guard_for(
                _PLACE_OPERATION_KEY, OPINET_STATION_DATASET_KEY
            ),
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
