"""MCST Dagster asset/fetcher 단위 테스트 (T-220 재배선, #395)."""

from __future__ import annotations

import sys
from types import ModuleType
from typing import Any

import pytest
from dagster import build_asset_context
from krtour.map.dto import Address, Coordinate
from krtour.map.infra.feature_repo import FeatureLoadResult
from krtour.map.providers.mcst import MCST_FILE_DATASETS
from krtour.map.settings import KrtourMapSettings

from krtour.map_dagster.mcst_features import (
    group_records_by_slug,
    run_feature_place_mcst_culture,
)
from krtour.map_dagster.provider_fetchers import fetch_mcst_culture_records

pytestmark = pytest.mark.filterwarnings(
    "ignore:Parameter `owners` of initializer `SensorDefinition.__init__`"
    ".*:dagster_shared.utils.warnings.BetaWarning"
)


def _common_row(name: str) -> dict[str, Any]:
    """공통 방언 A CSV row (실측 컬럼 모양)."""
    return {
        "TITLE": name,
        "ADDRESS": "서울특별시 종로구 세종대로 1",
        "COORDINATES": "N37.5665, E126.978",
        "RNUM": "1",
    }


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


def _context(records: list[Any]) -> Any:
    return build_asset_context(
        resources={
            "krtour_map_client": _FakeBundleLoadClient(),
            "reverse_geocoder": _fake_reverse,
            "fetched_at": None,
            "strict_address": True,
            "mcst_culture_records": records,
        }
    )


def test_group_records_by_slug_preserves_order() -> None:
    grouped = group_records_by_slug(
        [("a", 1), ("b", 2), ("a", 3)],
    )
    assert grouped == {"a": [1, 3], "b": [2]}


async def test_culture_asset_loads_per_slug_datasets() -> None:
    records = [
        ("independent_bookstores_csv", _common_row("서점 1")),
        ("world_restaurants_csv", _common_row("식당 1")),
        ("independent_bookstores_csv", _common_row("서점 2")),
    ]

    result = await run_feature_place_mcst_culture(_context(records))

    assert result.provider == "python-mcst-api"
    assert {r.dataset_key for r in result.results} == {
        "mcst_independent_bookstores_csv",
        "mcst_world_restaurants_csv",
    }
    by_key = {r.dataset_key: r for r in result.results}
    assert by_key["mcst_independent_bookstores_csv"].load.bundles_total == 2
    assert by_key["mcst_world_restaurants_csv"].load.bundles_total == 1
    assert result.bundles_total == 3
    assert result.as_metadata()["datasets_loaded"] == 2


async def test_culture_asset_rejects_unknown_slug() -> None:
    with pytest.raises(KeyError, match="nope"):
        await run_feature_place_mcst_culture(
            _context([("nope", _common_row("어딘가"))])
        )


async def test_culture_asset_rejects_excluded_slug() -> None:
    """제외 dataset(예: public_libraries)은 메타표에 없어 적재 시도 시 실패."""
    with pytest.raises(KeyError, match="public_libraries"):
        await run_feature_place_mcst_culture(
            _context([("public_libraries", {"도서관명": "더불어 숲"})])
        )


async def test_culture_asset_skips_unidentifiable_rows_with_warning() -> None:
    records = [
        ("golf_courses_status", {"이름": "라데나골프클럽", "소재지": "춘천시 1"}),
        # 이름 없는 row — 변환에서 제외(경고 로그).
        ("golf_courses_status", {"소재지": "어딘가"}),
    ]

    result = await run_feature_place_mcst_culture(_context(records))

    by_key = {r.dataset_key: r for r in result.results}
    assert by_key["mcst_golf_courses_status"].load.bundles_total == 1
    assert result.bundles_total == 1


# -- fetcher ------------------------------------------------------------------


class _FakeFileDataClient:
    instances: list[_FakeFileDataClient] = []
    rows_per_dataset: int = 2

    def __init__(self) -> None:
        self.closed = False
        self.calls: list[str] = []
        _FakeFileDataClient.instances.append(self)

    def iter_csv(self, slug: str) -> Any:
        self.calls.append(slug)
        for index in range(type(self).rows_per_dataset):
            yield {"TITLE": f"{slug}-{index}", "RNUM": str(index + 1)}

    def close(self) -> None:
        self.closed = True


def _install_fake_mcst(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeFileDataClient.instances = []
    module = ModuleType("mcst")
    module.__dict__["FileDataClient"] = _FakeFileDataClient
    monkeypatch.setitem(sys.modules, "mcst", module)


def test_fetch_mcst_culture_records_is_keyless_and_streams_slug_tuples(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_mcst(monkeypatch)
    # keyless(#395) — credential 없이도 fetch (knps/krheritage items 패턴).
    settings = KrtourMapSettings(
        data_go_kr_service_key=None,
        mcst_max_items_per_dataset=1,
    )

    records = list(fetch_mcst_culture_records(settings))

    # 등록 slug × max_items=1.
    assert len(records) == len(MCST_FILE_DATASETS)
    assert {slug for slug, _row in records} == set(MCST_FILE_DATASETS)
    [client] = _FakeFileDataClient.instances
    assert client.closed is True
    assert client.calls == list(MCST_FILE_DATASETS)


def test_fetch_mcst_culture_records_caps_rows_per_dataset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_mcst(monkeypatch)
    _FakeFileDataClient.rows_per_dataset = 5
    try:
        settings = KrtourMapSettings(mcst_max_items_per_dataset=3)

        records = list(fetch_mcst_culture_records(settings))

        per_slug: dict[str, int] = {}
        for slug, _row in records:
            per_slug[slug] = per_slug.get(slug, 0) + 1
        assert set(per_slug) == set(MCST_FILE_DATASETS)
        assert all(count == 3 for count in per_slug.values())
    finally:
        _FakeFileDataClient.rows_per_dataset = 2


def test_fetch_mcst_culture_records_closes_on_partial_consumption(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_mcst(monkeypatch)
    settings = KrtourMapSettings()

    gen = fetch_mcst_culture_records(settings)
    first = next(iter(gen))
    assert first is not None
    # 조기 종료 시에도 finally의 ``close()``가 실행되어 client가 닫혀야 한다.
    gen.close()

    [client] = _FakeFileDataClient.instances
    assert client.closed is True
