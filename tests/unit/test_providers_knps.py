"""``test_providers_knps`` — KNPS Point/place dataset 변환 (ADR-028/034 7단계).

본 PR 테스트 범위:
- 5건 Point/place dataset(visitor_centers/restrooms/campgrounds/shelters/
  cultural_resources) happy path + category/place_kind/maki 정합.
- cultural_resources subtype 분기 (사찰/유적/기타).
- 좌표 없는 record는 ``Feature.coord=None``.
- 결정성 — 같은 입력은 같은 ``feature_id`` / ``source_record_key``.
- ``FeatureBundle`` FK consistency + SourceRole.PRIMARY.
- 미지원 dataset_key는 ``KeyError`` (SHP/route/area는 후속 PR).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest

from krtour.map.dto import FeatureKind, SourceRole
from krtour.map.providers.knps import (
    KNPS_PLACE_DATASETS,
    KNPS_POINT_DATASET_KEYS,
    PROVIDER_NAME,
    knps_point_records_to_bundles,
    resolve_cultural_resource_category,
)

_KST = timezone(timedelta(hours=9))
_FETCHED = datetime(2026, 5, 29, 12, 0, tzinfo=_KST)


@dataclass(frozen=True)
class _Rec:
    """`KnpsPointRecord` Protocol 만족."""

    source_id: str
    name: str
    longitude: Decimal | None
    latitude: Decimal | None
    raw: dict[str, Any]


def _one(dataset_key: str, **over: Any):
    rec = _Rec(
        source_id=over.get("source_id", "KN-001"),
        name=over.get("name", "북한산 시설"),
        longitude=over.get("longitude", Decimal("126.9876")),
        latitude=over.get("latitude", Decimal("37.6584")),
        raw=over.get("raw", {"MNG_NO": "KN-001"}),
    )
    return knps_point_records_to_bundles(
        [rec], dataset_key=dataset_key, fetched_at=_FETCHED
    )[0]


def test_visitor_center_mapping() -> None:
    b = _one("knps_visitor_centers")
    assert b.feature.kind is FeatureKind.PLACE
    assert b.feature.category == "01060101"
    assert b.feature.detail.place_kind == "visitor_center"
    assert b.feature.marker_icon == "information"
    assert b.feature.coord is not None
    assert float(b.feature.coord.lon) == pytest.approx(126.9876)


def test_shelter_uses_adr027_category() -> None:
    b = _one("knps_shelters", name="대피소")
    assert b.feature.category == "03080100"  # LODGING_MOUNTAIN_SHELTER_KNPS
    assert b.feature.detail.place_kind == "mountain_shelter"
    assert b.feature.marker_icon == "shelter"


def test_restroom_and_campground_categories() -> None:
    assert _one("knps_restrooms").feature.category == "05060000"
    assert _one("knps_campgrounds").feature.category == "03060100"


@pytest.mark.parametrize(
    ("rtype", "category", "place_kind"),
    [
        ("사찰", "01070100", "temple"),
        ("유적", "01070300", "historic_site"),
        ("사적지", "01070300", "historic_site"),
        ("기념물", "01070300", "historic_site"),
        ("전망대", "01070000", "cultural_resource"),
        ("", "01070000", "cultural_resource"),
    ],
)
def test_cultural_resource_subtype_branching(
    rtype: str, category: str, place_kind: str
) -> None:
    cat, kind = resolve_cultural_resource_category({"RESOURCE_TYPE": rtype})
    assert (cat, kind) == (category, place_kind)


def test_cultural_resource_bundle_dynamic_category() -> None:
    b = _one(
        "knps_cultural_resources",
        name="화엄사",
        raw={"RESOURCE_TYPE": "사찰", "MNG_NO": "CR-1"},
    )
    assert b.feature.category == "01070100"
    assert b.feature.detail.place_kind == "temple"
    assert b.feature.marker_icon == "religious-buddhist"


def test_missing_coord_yields_none() -> None:
    b = _one("knps_restrooms", longitude=None, latitude=None)
    assert b.feature.coord is None
    assert b.source_record.raw_longitude is None


def test_out_of_korea_coord_is_dropped() -> None:
    # 한국 경계 밖 좌표는 Coordinate validator가 reject → coord=None.
    b = _one("knps_restrooms", longitude=Decimal("0.0"), latitude=Decimal("0.0"))
    assert b.feature.coord is None


def test_primary_source_and_provider_name() -> None:
    b = _one("knps_visitor_centers")
    assert b.source_link.source_role is SourceRole.PRIMARY
    assert b.source_link.is_primary_source is True
    assert b.source_link.confidence == 100
    assert b.source_record.provider == PROVIDER_NAME


def test_deterministic_ids() -> None:
    b1 = _one("knps_shelters")
    b2 = _one("knps_shelters")
    assert b1.feature.feature_id == b2.feature.feature_id
    assert b1.source_record.source_record_key == b2.source_record.source_record_key


def test_bundle_fk_consistency() -> None:
    # FeatureBundle model_validator: source_link FK가 feature/source_record와 일치.
    b = _one("knps_campgrounds")
    assert b.source_link.feature_id == b.feature.feature_id
    assert b.source_link.source_record_key == b.source_record.source_record_key


def test_unsupported_dataset_key_raises() -> None:
    with pytest.raises(KeyError, match="Point/place dataset 아님"):
        knps_point_records_to_bundles(
            [], dataset_key="knps_park_boundaries", fetched_at=_FETCHED
        )


def test_point_dataset_keys_match_registry() -> None:
    assert frozenset(KNPS_PLACE_DATASETS) == KNPS_POINT_DATASET_KEYS
    assert "knps_visitor_centers" in KNPS_POINT_DATASET_KEYS


def test_preserves_input_order() -> None:
    recs = [
        _Rec(f"K-{i}", f"시설{i}", Decimal("127.0"), Decimal("37.5"), {"i": i})
        for i in range(3)
    ]
    bundles = knps_point_records_to_bundles(
        recs, dataset_key="knps_restrooms", fetched_at=_FETCHED
    )
    assert [b.source_record.source_entity_id for b in bundles] == ["K-0", "K-1", "K-2"]
