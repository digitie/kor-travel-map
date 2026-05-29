"""``test_providers_krheritage`` — 국가유산청 place/area/event 변환 (ADR-034 8단계).

테스트 범위:
- ccba_kdcd → place/area kind 판정 (`classify_heritage_kind`) 분기.
- 유형 키워드 → category 매핑 (사찰/궁궐/한옥/사적/천연기념물).
- area + geom_wkt → Feature.geom + centroid 좌표 + area_kind.
- event → EventDetail(heritage_event) + content_id=sn.
- reverse_geocoder 주입 시 bjd_code 보강 + feature_id bucket + 좌표 dedup.
- 결정성 + FeatureBundle FK consistency + SourceRole.PRIMARY.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest

from krtour.map.dto import Address, Coordinate, FeatureKind, SourceRole
from krtour.map.providers.krheritage import (
    DATASET_KEY_EVENT,
    DATASET_KEY_HERITAGE,
    HERITAGE_MARKER_COLOR,
    PROVIDER_NAME,
    classify_heritage_kind,
    heritage_events_to_bundles,
    heritage_items_to_bundles,
    resolve_heritage_category,
)

_KST = timezone(timedelta(hours=9))
_FETCHED = datetime(2026, 5, 29, 12, 0, tzinfo=_KST)

# 서울 경계 안 폴리곤 (area geometry 테스트용).
_POLYGON_WKT = "POLYGON((127.0 37.5, 127.1 37.5, 127.1 37.6, 127.0 37.6, 127.0 37.5))"


@dataclass(frozen=True)
class _Item:
    """``KrHeritageItem`` Protocol 만족."""

    ccba_kdcd: str
    ccba_asno: str
    ccba_ctcd: str
    name: str
    heritage_type: str | None = None
    longitude: Decimal | float | None = None
    latitude: Decimal | float | None = None
    location_text: str | None = None
    designated_date: date | None = None
    manager: str | None = None
    geom_wkt: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class _Event:
    """``KrHeritageEvent`` Protocol 만족."""

    sn: str
    title: str
    start_date: date | None = None
    end_date: date | None = None
    venue_name: str | None = None
    tel: str | None = None
    location_text: str | None = None
    longitude: Decimal | float | None = None
    latitude: Decimal | float | None = None
    raw: dict[str, Any] = field(default_factory=dict)


# -- kind 판정 ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("kdcd", "geom", "expected"),
    [
        ("11", None, FeatureKind.PLACE),  # 국보
        ("12", None, FeatureKind.PLACE),  # 보물
        ("13", None, FeatureKind.AREA),  # 사적
        ("16", None, FeatureKind.AREA),  # 명승
        ("15", None, FeatureKind.PLACE),  # 천연기념물, 경계 없음
        ("15", _POLYGON_WKT, FeatureKind.AREA),  # 천연기념물, 경계 있음
        ("17", None, FeatureKind.PLACE),  # 등록문화유산
        ("31", None, FeatureKind.PLACE),  # 무형
    ],
)
def test_classify_heritage_kind(kdcd: str, geom: str | None, expected: FeatureKind) -> None:
    item = _Item(ccba_kdcd=kdcd, ccba_asno="1", ccba_ctcd="11", name="x", geom_wkt=geom)
    assert classify_heritage_kind(item) is expected


@pytest.mark.parametrize(
    ("kdcd", "name", "htype", "expected"),
    [
        ("11", "통도사 대웅전", "전통사찰", "01070100"),
        ("12", "경복궁 근정전", "궁궐", "01070200"),
        ("18", "안동 하회 한옥마을", "민속마을", "01070400"),
        ("13", "수원 화성", "사적", "01070300"),
        ("16", "명주 청학동", "명승", "01070300"),
        ("15", "천연기념물 동백나무", "천연기념물", "01020400"),
        ("17", "기타 등록유산", None, "01070000"),
    ],
)
def test_resolve_heritage_category(
    kdcd: str, name: str, htype: str | None, expected: str
) -> None:
    item = _Item(ccba_kdcd=kdcd, ccba_asno="1", ccba_ctcd="11", name=name, heritage_type=htype)
    assert resolve_heritage_category(item) == expected


# -- place 변환 ---------------------------------------------------------------


async def test_place_bundle_mapping() -> None:
    item = _Item(
        ccba_kdcd="11",
        ccba_asno="0001",
        ccba_ctcd="37",
        name="석굴암 석굴",
        heritage_type="전통사찰",
        longitude=Decimal("129.349"),
        latitude=Decimal("35.795"),
        location_text="경상북도 경주시 진현동",
        designated_date=date(1962, 12, 20),
        manager="불국사",
    )
    [bundle] = await heritage_items_to_bundles([item], fetched_at=_FETCHED)
    feat = bundle.feature
    assert feat.kind is FeatureKind.PLACE
    assert feat.category == "01070100"
    assert feat.marker_icon == "religious-buddhist"
    assert feat.marker_color == HERITAGE_MARKER_COLOR
    assert feat.detail.place_kind == "heritage_site"
    assert feat.coord is not None
    # 자연키 = ccbaKdcd-ccbaAsno-ccbaCtcd.
    assert bundle.source_record.source_entity_id == "11-0001-37"
    assert bundle.source_record.dataset_key == DATASET_KEY_HERITAGE
    assert bundle.source_link.source_role is SourceRole.PRIMARY
    # FK consistency.
    assert bundle.source_link.feature_id == feat.feature_id
    assert feat.detail.feature_id == feat.feature_id
    # 좌표만 있고 reverse geocoder 없음 → bjd_code 없음, 'global' bucket.
    assert feat.feature_id.startswith("f_global_p_")


async def test_natural_monument_place_kind() -> None:
    item = _Item(
        ccba_kdcd="15",
        ccba_asno="3",
        ccba_ctcd="11",
        name="서울 재동 백송",
        heritage_type="천연기념물",
        longitude=Decimal("126.98"),
        latitude=Decimal("37.57"),
    )
    [bundle] = await heritage_items_to_bundles([item], fetched_at=_FETCHED)
    assert bundle.feature.kind is FeatureKind.PLACE
    assert bundle.feature.category == "01020400"
    assert bundle.feature.detail.place_kind == "natural_heritage"


# -- area 변환 (geometry) -----------------------------------------------------


async def test_area_bundle_with_geometry() -> None:
    item = _Item(
        ccba_kdcd="13",
        ccba_asno="0003",
        ccba_ctcd="31",
        name="수원 화성",
        heritage_type="사적",
        geom_wkt=_POLYGON_WKT,
        manager="수원시",
    )
    [bundle] = await heritage_items_to_bundles([item], fetched_at=_FETCHED)
    feat = bundle.feature
    assert feat.kind is FeatureKind.AREA
    assert feat.category == "01070300"
    assert feat.geom is not None  # 정규화된 WKT
    assert feat.coord is not None  # centroid
    # centroid는 폴리곤 중심 근처 (127.05, 37.55).
    assert float(feat.coord.lon) == pytest.approx(127.05, abs=0.01)
    assert feat.detail.area_kind == "heritage_area"
    assert feat.detail.boundary_source == "gis"
    # geometry 면적 보강 (측지, m²) — 0.1°×0.1° 폴리곤은 ~1e8 m² 규모.
    assert feat.detail.area_square_meters is not None
    assert float(feat.detail.area_square_meters) > 5e7


async def test_area_invalid_geometry_falls_back_to_coord() -> None:
    item = _Item(
        ccba_kdcd="13",
        ccba_asno="9",
        ccba_ctcd="11",
        name="사적 좌표만",
        geom_wkt="POLYGON((bad wkt))",
        longitude=Decimal("127.0"),
        latitude=Decimal("37.5"),
    )
    [bundle] = await heritage_items_to_bundles([item], fetched_at=_FETCHED)
    feat = bundle.feature
    assert feat.kind is FeatureKind.AREA
    assert feat.geom is None  # 불량 geometry → 좌표만
    assert feat.coord is not None
    assert feat.detail.boundary_source is None


async def test_item_without_coord_has_none() -> None:
    item = _Item(ccba_kdcd="11", ccba_asno="1", ccba_ctcd="11", name="좌표 없는 국보")
    [bundle] = await heritage_items_to_bundles([item], fetched_at=_FETCHED)
    assert bundle.feature.coord is None


# -- reverse geocoder 보강 ----------------------------------------------------


async def test_reverse_geocoder_fills_bjd_and_dedupes() -> None:
    calls: list[tuple[Decimal, Decimal]] = []

    async def _rg(coord: Coordinate) -> Address | None:
        calls.append((coord.lon, coord.lat))
        return Address(bjd_code="1111010100", sigungu_code="11110", sido_code="11")

    items = [
        _Item("11", "1", "11", "유산 A", longitude=Decimal("126.98"), latitude=Decimal("37.57")),
        _Item("11", "2", "11", "유산 B", longitude=Decimal("126.98"), latitude=Decimal("37.57")),
    ]
    bundles = await heritage_items_to_bundles(items, fetched_at=_FETCHED, reverse_geocoder=_rg)
    assert all(b.feature.address.bjd_code == "1111010100" for b in bundles)
    assert all(b.feature.feature_id.startswith("f_1111010100_p_") for b in bundles)
    # 같은 좌표 2건 → cached_reverse_geocoder가 1회만 호출.
    assert len(calls) == 1


async def test_location_text_fills_legal_without_geocoder() -> None:
    item = _Item(
        ccba_kdcd="11",
        ccba_asno="1",
        ccba_ctcd="11",
        name="유산",
        location_text="서울특별시 종로구 세종로 1-1",
    )
    [bundle] = await heritage_items_to_bundles([item], fetched_at=_FETCHED)
    assert bundle.feature.address.legal == "서울특별시 종로구 세종로 1-1"


# -- event 변환 ---------------------------------------------------------------


async def test_event_bundle_mapping() -> None:
    event = _Event(
        sn="EVT-2026-001",
        title="종묘제례악 공연",
        start_date=date(2026, 5, 1),
        end_date=date(2026, 5, 3),
        venue_name="종묘",
        tel="02-765-0195",
        location_text="서울특별시 종로구 종로 157",
        longitude=Decimal("126.994"),
        latitude=Decimal("37.574"),
    )
    [bundle] = await heritage_events_to_bundles([event], fetched_at=_FETCHED)
    feat = bundle.feature
    assert feat.kind is FeatureKind.EVENT
    assert feat.category == "01070000"
    assert feat.detail.event_kind == "heritage_event"
    assert feat.detail.starts_on == date(2026, 5, 1)
    assert feat.detail.ends_on == date(2026, 5, 3)
    assert feat.detail.venue_name == "종묘"
    assert feat.detail.content_id == "EVT-2026-001"
    assert bundle.source_record.dataset_key == DATASET_KEY_EVENT
    assert bundle.source_record.source_entity_id == "EVT-2026-001"
    assert feat.feature_id.startswith("f_global_e_")


async def test_deterministic_ids() -> None:
    item = _Item("13", "1", "11", "사적", geom_wkt=_POLYGON_WKT)
    a = (await heritage_items_to_bundles([item], fetched_at=_FETCHED))[0]
    b = (await heritage_items_to_bundles([item], fetched_at=_FETCHED))[0]
    assert a.feature.feature_id == b.feature.feature_id
    assert a.source_record.source_record_key == b.source_record.source_record_key


async def test_provider_name_constant() -> None:
    item = _Item("11", "1", "11", "x")
    [bundle] = await heritage_items_to_bundles([item], fetched_at=_FETCHED)
    assert bundle.source_record.provider == PROVIDER_NAME
