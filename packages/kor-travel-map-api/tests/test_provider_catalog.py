"""``test_provider_catalog`` — 전 provider×dataset 카탈로그 정본 검증.

ETL preview(`/etl`)와 Providers(`/ops/providers`) 메뉴가 동일 카탈로그를
source로 쓰도록, 카탈로그가 fixture-backed 9종을 넘어 mois/knps/krheritage/mcst
등 시스템이 ETL 하는 모든 provider×dataset을 담는지 검증한다.
"""

from __future__ import annotations

import pytest

from kortravelmap.api.etl_fixtures import FIXTURE_REGISTRY
from kortravelmap.api.etl_live import LIVE_LOADER_REGISTRY
from kortravelmap.api.provider_catalog import (
    PROVIDER_DATASET_CATALOG,
    catalog_datasets,
    catalog_feature_load_entries,
    find_catalog_entry,
    list_catalog_providers,
)


@pytest.mark.unit
def test_catalog_includes_previously_missing_providers() -> None:
    """카탈로그는 fixture만으론 안 나오던 provider를 포함한다."""
    providers = set(list_catalog_providers())
    assert {
        "python-mois-api",
        "python-knps-api",
        "python-krheritage-api",
        "python-mcst-api",
    } <= providers


@pytest.mark.unit
def test_catalog_includes_specific_dataset_keys() -> None:
    """대표 dataset_key가 카탈로그에 들어있다 (drift-safe 상수 참조 검증)."""
    keys = {(e.provider, e.dataset_key) for e in PROVIDER_DATASET_CATALOG}
    assert ("python-mois-api", "mois_license_features_bulk") in keys
    assert ("python-knps-api", "knps_visitor_centers") in keys
    assert ("python-knps-api", "knps_trails") in keys
    assert ("python-knps-api", "knps_park_boundaries") in keys
    assert ("python-krheritage-api", "krheritage_heritage_features") in keys
    assert ("python-krheritage-api", "krheritage_event_list") in keys
    assert ("python-mcst-api", "mcst_world_restaurants_csv") in keys
    assert ("python-mcst-api", "mcst_golf_courses_status") in keys


@pytest.mark.unit
def test_catalog_covers_all_fixture_datasets() -> None:
    """모든 fixture-backed (provider, dataset)은 카탈로그에 존재해야 한다.

    누락되면 /etl preview가 카탈로그에서 그 dataset을 못 그린다 → drift 방지.
    """
    for entry in FIXTURE_REGISTRY:
        assert find_catalog_entry(entry.provider, entry.dataset) is not None, (
            f"fixture {entry.provider}/{entry.dataset}이 카탈로그에 없음"
        )


@pytest.mark.unit
def test_catalog_covers_all_live_loader_datasets() -> None:
    """모든 live loader (provider, dataset)도 카탈로그에 존재해야 한다."""
    for provider, dataset in LIVE_LOADER_REGISTRY:
        assert find_catalog_entry(provider, dataset) is not None, (
            f"live loader {provider}/{dataset}이 카탈로그에 없음"
        )


@pytest.mark.unit
def test_no_duplicate_catalog_entries() -> None:
    """(provider, dataset_key)는 카탈로그에서 유일해야 한다."""
    keys = [(e.provider, e.dataset_key) for e in PROVIDER_DATASET_CATALOG]
    assert len(keys) == len(set(keys))


@pytest.mark.unit
def test_preview_field_matches_registries() -> None:
    """preview 필드는 fixture/live registry 조회 결과와 정합한다."""
    fixture_keys = {(e.provider, e.dataset) for e in FIXTURE_REGISTRY}
    for entry in PROVIDER_DATASET_CATALOG:
        key = (entry.provider, entry.dataset_key)
        if key in fixture_keys:
            assert entry.preview == "fixture"
        elif key in LIVE_LOADER_REGISTRY:
            assert entry.preview == "live"
        else:
            assert entry.preview == "none"


@pytest.mark.unit
def test_feature_load_entries_are_subset() -> None:
    """catalog_feature_load_entries()는 is_feature_load=True 항목만, 정렬됨."""
    entries = catalog_feature_load_entries()
    assert all(e.is_feature_load for e in entries)
    # mois bulk는 feature load, opinet 가격(PriceValue)은 아님.
    fl_keys = {(e.provider, e.dataset_key) for e in entries}
    assert ("python-mois-api", "mois_license_features_bulk") in fl_keys
    assert ("python-opinet-api", "opinet_gas_station_prices") not in fl_keys
    # 정렬 보장.
    assert entries == sorted(entries, key=lambda e: (e.provider, e.dataset_key))


@pytest.mark.unit
def test_catalog_datasets_sorted_by_dataset_key() -> None:
    knps = catalog_datasets("python-knps-api")
    assert len(knps) == 10  # place 5 + geometry 5
    assert [e.dataset_key for e in knps] == sorted(e.dataset_key for e in knps)
    kinds = {e.dataset_key: e.feature_kind for e in knps}
    assert kinds["knps_visitor_centers"] == "place"
    assert kinds["knps_trails"] == "route"
    assert kinds["knps_park_boundaries"] == "area"


@pytest.mark.unit
def test_mcst_entries_reference_provider_dict() -> None:
    """MCST 13 slug 전체가 카탈로그에 (provider dict 참조, label 보존)."""
    mcst = catalog_datasets("python-mcst-api")
    assert len(mcst) == 13
    golf = find_catalog_entry("python-mcst-api", "mcst_golf_courses_status")
    assert golf is not None
    assert "골프장" in golf.label
