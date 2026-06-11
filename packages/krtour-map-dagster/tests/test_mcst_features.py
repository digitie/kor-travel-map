"""MCST Dagster asset/fetcher 단위 테스트 (T-220b)."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
from dagster import build_asset_context
from krtour.map.dto import Address, Coordinate
from krtour.map.infra.feature_repo import FeatureLoadResult
from krtour.map.settings import KrtourMapSettings
from pydantic import SecretStr

from krtour.map_dagster.mcst_features import (
    group_records_by_slug,
    run_feature_place_mcst_culture,
    run_feature_place_mcst_libraries,
)
from krtour.map_dagster.provider_fetchers import (
    ProviderCredentialMissing,
    fetch_mcst_culture_records,
    fetch_mcst_libraries,
)

pytestmark = pytest.mark.filterwarnings(
    "ignore:Parameter `owners` of initializer `SensorDefinition.__init__`"
    ".*:dagster_shared.utils.warnings.BetaWarning"
)


@dataclass(frozen=True)
class _CultureItem:
    name: str | None = "테스트 장소"
    address: str | None = "서울특별시 종로구 세종대로 1"
    tel: str | None = None
    url: str | None = None
    longitude: float | None = 126.978
    latitude: float | None = 37.5665
    category: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


async def _fake_reverse(_coord: Coordinate) -> Address:
    return Address(bjd_code="1111010100", sido_name="서울특별시")


class _FakeBundleLoadClient:
    def __init__(self) -> None:
        self.loaded: list[Any] = []

    async def load_feature_bundles(self, bundles: Any) -> FeatureLoadResult:
        materialized = list(bundles)
        self.loaded.extend(materialized)
        return FeatureLoadResult(
            bundles_total=len(materialized), features_inserted=len(materialized)
        )


def _context(records: list[Any], *, resource_key: str) -> Any:
    return build_asset_context(
        resources={
            "krtour_map_client": _FakeBundleLoadClient(),
            "reverse_geocoder": _fake_reverse,
            "fetched_at": None,
            "strict_address": True,
            resource_key: records,
        }
    )


def test_group_records_by_slug_preserves_order() -> None:
    grouped = group_records_by_slug(
        [("a", 1), ("b", 2), ("a", 3)],
    )
    assert grouped == {"a": [1, 3], "b": [2]}


async def test_culture_asset_loads_per_slug_datasets() -> None:
    records = [
        ("independent_bookstores", _CultureItem(name="서점 1")),
        ("world_restaurants", _CultureItem(name="식당 1")),
        ("independent_bookstores", _CultureItem(name="서점 2")),
    ]

    result = await run_feature_place_mcst_culture(
        _context(records, resource_key="mcst_culture_records")
    )

    assert result.provider == "python-mcst-api"
    assert {r.dataset_key for r in result.results} == {
        "mcst_independent_bookstores",
        "mcst_world_restaurants",
    }
    by_key = {r.dataset_key: r for r in result.results}
    assert by_key["mcst_independent_bookstores"].load.bundles_total == 2
    assert by_key["mcst_world_restaurants"].load.bundles_total == 1
    assert result.bundles_total == 3
    assert result.as_metadata()["datasets_loaded"] == 2


async def test_culture_asset_rejects_unknown_slug() -> None:
    with pytest.raises(KeyError, match="nope"):
        await run_feature_place_mcst_culture(
            _context(
                [("nope", _CultureItem())], resource_key="mcst_culture_records"
            )
        )


async def test_libraries_asset_loads_rows() -> None:
    records = [
        (
            "public_libraries",
            {
                "도서관명": "종로도서관",
                "소재지도로명주소": "서울특별시 종로구 1",
                "위도": "37.57",
                "경도": "126.96",
            },
        ),
        # 이름 없는 row — 변환에서 제외(경고 로그).
        ("small_libraries", {"소재지": "어딘가"}),
    ]

    result = await run_feature_place_mcst_libraries(
        _context(records, resource_key="mcst_library_records")
    )

    by_key = {r.dataset_key: r for r in result.results}
    assert by_key["mcst_public_libraries"].load.bundles_total == 1
    assert by_key["mcst_small_libraries"].load.bundles_total == 0
    assert result.bundles_total == 1


# -- fetchers ---------------------------------------------------------------


class _FakeCultureClient:
    instances: list[_FakeCultureClient] = []

    def __init__(self, *, service_key: str) -> None:
        self.service_key = service_key
        self.closed = False
        self.calls: list[tuple[str, int | None]] = []
        _FakeCultureClient.instances.append(self)

    def iter_items(
        self, slug: str, *, num_of_rows: int, max_items: int | None = None
    ) -> Any:
        self.calls.append((slug, max_items))
        count = min(2, max_items if max_items is not None else 2)
        for index in range(count):
            yield SimpleNamespace(name=f"{slug}-{index}")

    def close(self) -> None:
        self.closed = True


class _FakeOdcloudClient:
    instances: list[_FakeOdcloudClient] = []

    def __init__(self, *, service_key: str) -> None:
        self.service_key = service_key
        self.closed = False
        self.calls: list[tuple[str, int]] = []
        _FakeOdcloudClient.instances.append(self)

    def request(self, slug: str, *, page_no: int, per_page: int) -> Any:
        self.calls.append((slug, page_no))
        items = [{"slug": slug, "row": page_no}] if page_no == 1 else []
        return SimpleNamespace(
            items=items, total_count=1, page_no=page_no, num_of_rows=per_page
        )

    def close(self) -> None:
        self.closed = True


def _install_fake_mcst(monkeypatch: pytest.MonkeyPatch) -> None:
    module = ModuleType("mcst")
    module.__dict__["CultureOpenApiClient"] = _FakeCultureClient
    module.__dict__["DataGoFileApiClient"] = _FakeOdcloudClient
    monkeypatch.setitem(sys.modules, "mcst", module)


def test_fetch_mcst_culture_records_streams_slug_tuples(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeCultureClient.instances = []
    _install_fake_mcst(monkeypatch)
    settings = KrtourMapSettings(
        data_go_kr_service_key=SecretStr("data-key"),
        mcst_max_items_per_dataset=1,
    )

    records = list(fetch_mcst_culture_records(settings))

    # 14 slug × max_items=1.
    assert len(records) == 14
    slugs = {slug for slug, _record in records}
    assert "independent_bookstores" in slugs
    assert "recommended_travel_destinations" in slugs
    [client] = _FakeCultureClient.instances
    assert client.closed is True
    assert all(max_items == 1 for _slug, max_items in client.calls)


def test_fetch_mcst_libraries_streams_both_slugs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeOdcloudClient.instances = []
    _install_fake_mcst(monkeypatch)
    settings = KrtourMapSettings(data_go_kr_service_key=SecretStr("data-key"))

    records = list(fetch_mcst_libraries(settings))

    assert {slug for slug, _row in records} == {
        "public_libraries",
        "small_libraries",
    }
    [client] = _FakeOdcloudClient.instances
    assert client.closed is True


@pytest.mark.parametrize(
    "fetch", [fetch_mcst_culture_records, fetch_mcst_libraries]
)
def test_fetch_mcst_requires_credential(fetch: Any) -> None:
    settings = KrtourMapSettings(data_go_kr_service_key=None)

    with pytest.raises(ProviderCredentialMissing, match="DATA_GO_KR_SERVICE_KEY"):
        next(iter(fetch(settings)))
