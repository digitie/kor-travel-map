"""``test_providers_krheritage`` — 국가유산청 place/area/event 변환 (ADR-034 8단계).

테스트 범위 (#380 — provider ``HeritageDetail`` 실모델 재정렬):
- ``key.ccba_kdcd`` → place/area kind 판정 (`classify_heritage_kind`) 분기.
- 유형 키워드(``name_ko``/``category``) → category 매핑.
- area는 GIS Polygon/MultiPolygon 경계가 있을 때만 생성. 경계 없는 사적/명승은
  좌표 기반 place.
- ``designated_at``(YYYYMMDD str) 방어적 파싱.
- 명칭 빈 row skip (#374 패턴), 소재지 ``location_text``→``region+sigungu`` fallback.
- event → EventDetail(heritage_event) + sn 빈 값 fallback 자연키 / skip.
- reverse_geocoder 주입 시 bjd_code 보강 + feature_id bucket + 좌표 dedup.
- 결정성 + FeatureBundle FK consistency + SourceRole.PRIMARY.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest

from kortravelmap.dto import Address, Coordinate, FeatureKind, SourceRole
from kortravelmap.providers.krheritage import (
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


@dataclass(frozen=True)
class _Key:
    """``KrHeritageItemKey`` Protocol 만족 (provider ``HeritageKey`` shape)."""

    ccba_kdcd: str
    ccba_asno: str
    ccba_ctcd: str

    @property
    def natural_key(self) -> str:
        return f"{self.ccba_kdcd}-{self.ccba_asno}-{self.ccba_ctcd}"


@dataclass(frozen=True)
class _Item:
    """``KrHeritageItem`` Protocol 만족 (provider ``HeritageDetail`` shape)."""

    key: _Key
    name_ko: str
    category: str | None = None
    region: str | None = None
    sigungu: str | None = None
    longitude: Decimal | float | None = None
    latitude: Decimal | float | None = None
    location_text: str | None = None
    designated_at: str | None = None
    manager: str | None = None
    image_url: str | None = None
    geom_wkt: str | None = None
    boundary_source: str | None = None


def _item(
    kdcd: str = "11",
    asno: str = "1",
    ctcd: str = "11",
    name_ko: str = "x",
    **kwargs: Any,
) -> _Item:
    return _Item(key=_Key(kdcd, asno, ctcd), name_ko=name_ko, **kwargs)


@dataclass(frozen=True)
class _Event:
    """``KrHeritageEvent`` Protocol 만족 (provider ``HeritageEvent`` shape)."""

    sn: str | None
    title: str | None
    starts_on: date | None = None
    ends_on: date | None = None
    place: str | None = None
    tel_name: str | None = None
    address: str | None = None
    longitude: Decimal | float | None = None
    latitude: Decimal | float | None = None
    main_image: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


# -- kind 판정 ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("kdcd", "expected"),
    [
        ("11", FeatureKind.PLACE),  # 국보
        ("12", FeatureKind.PLACE),  # 보물
        ("13", FeatureKind.PLACE),  # 사적 — 경계 없으면 point place
        ("16", FeatureKind.PLACE),  # 명승 — 경계 없으면 point place
        ("15", FeatureKind.PLACE),  # 천연기념물 — GIS 경계 미배선, place (#380)
        ("17", FeatureKind.PLACE),  # 등록문화유산
        ("31", FeatureKind.PLACE),  # 무형
    ],
)
def test_classify_heritage_kind(kdcd: str, expected: FeatureKind) -> None:
    assert classify_heritage_kind(_item(kdcd=kdcd)) is expected


@pytest.mark.parametrize(
    ("kdcd", "name_ko", "category", "expected"),
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
    kdcd: str, name_ko: str, category: str | None, expected: str
) -> None:
    assert (
        resolve_heritage_category(_item(kdcd=kdcd, name_ko=name_ko, category=category))
        == expected
    )


# -- place 변환 ---------------------------------------------------------------


async def test_place_bundle_mapping() -> None:
    item = _item(
        kdcd="11",
        asno="0001",
        ctcd="37",
        name_ko="석굴암 석굴",
        category="전통사찰",
        longitude=129.349,
        latitude=35.795,
        location_text="경상북도 경주시 진현동",
        designated_at="19621220",
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
    # 자연키 = provider key.natural_key (ccbaKdcd-ccbaAsno-ccbaCtcd).
    assert bundle.source_record.source_entity_id == "11-0001-37"
    assert bundle.source_record.dataset_key == DATASET_KEY_HERITAGE
    assert bundle.source_link.source_role is SourceRole.PRIMARY
    # designated_at(YYYYMMDD) → ISO 파싱, 유형 텍스트는 payload 보존.
    assert feat.detail.payload["designated_date"] == "1962-12-20"
    assert feat.detail.payload["heritage_type"] == "전통사찰"
    assert feat.detail.payload["manager"] == "불국사"
    # raw_data는 Protocol 필드에서 구성 (provider model에 raw 미보유).
    assert bundle.source_record.raw_data["name_ko"] == "석굴암 석굴"
    assert bundle.source_record.raw_data["designated_at"] == "19621220"
    assert bundle.source_record.raw_data["ccba_kdcd"] == "11"
    # FK consistency.
    assert bundle.source_link.feature_id == feat.feature_id
    assert feat.detail.feature_id == feat.feature_id
    # 좌표만 있고 reverse geocoder 없음 → bjd_code 없음, 'global' bucket.
    assert feat.feature_id.startswith("f_global_p_")


async def test_natural_monument_place_kind() -> None:
    item = _item(
        kdcd="15",
        asno="3",
        ctcd="11",
        name_ko="서울 재동 백송",
        category="천연기념물",
        longitude=126.98,
        latitude=37.57,
    )
    [bundle] = await heritage_items_to_bundles([item], fetched_at=_FETCHED)
    assert bundle.feature.kind is FeatureKind.PLACE
    assert bundle.feature.category == "01020400"
    assert bundle.feature.detail.place_kind == "natural_heritage"


async def test_empty_name_row_is_skipped() -> None:
    items = [
        _item(name_ko="  "),  # 정규화 후 빈 명칭 → skip
        _item(asno="2", name_ko="수원 화성", kdcd="13", category="사적"),
    ]
    bundles = await heritage_items_to_bundles(items, fetched_at=_FETCHED)
    assert len(bundles) == 1
    assert bundles[0].feature.name == "수원 화성"


@pytest.mark.parametrize(
    ("designated_at", "expected"),
    [
        ("19621220", "1962-12-20"),
        ("1962.12.20", "1962-12-20"),  # 구분자 변형 — 숫자만 추출
        ("19629999", None),  # 불량 월/일 → None
        ("1962", None),  # 8자리 미만 → None
        ("", None),
        (None, None),
    ],
)
async def test_designated_at_defensive_parsing(
    designated_at: str | None, expected: str | None
) -> None:
    item = _item(name_ko="유산", designated_at=designated_at)
    [bundle] = await heritage_items_to_bundles([item], fetched_at=_FETCHED)
    assert bundle.feature.detail.payload["designated_date"] == expected
    # 원천 문자열은 raw_data에 그대로 보존.
    assert bundle.source_record.raw_data["designated_at"] == designated_at


# -- area 변환 ---------------------------------------------------------------


async def test_historic_site_without_geometry_is_place() -> None:
    item = _item(
        kdcd="13",
        asno="0003",
        ctcd="31",
        name_ko="수원 화성",
        category="사적",
        longitude=127.01,
        latitude=37.28,
        manager="수원시",
    )
    [bundle] = await heritage_items_to_bundles([item], fetched_at=_FETCHED)
    feat = bundle.feature
    assert feat.kind is FeatureKind.PLACE
    assert feat.category == "01070300"
    # 좌표만 있는 사적/명승은 area가 아니라 place로 보존한다.
    assert feat.geom is None
    assert feat.coord is not None
    assert feat.detail.place_kind == "heritage_site"
    assert feat.detail.payload["manager"] == "수원시"


async def test_area_bundle_with_polygon_geometry() -> None:
    item = _item(
        kdcd="13",
        asno="0003",
        ctcd="31",
        name_ko="수원 화성",
        category="사적",
        longitude=127.01,
        latitude=37.28,
        manager="수원시",
        boundary_source="gis_spca",
        geom_wkt=(
            "POLYGON((127.00 37.27, 127.02 37.27, 127.02 37.29, "
            "127.00 37.29, 127.00 37.27))"
        ),
    )
    [bundle] = await heritage_items_to_bundles([item], fetched_at=_FETCHED)
    feat = bundle.feature
    assert feat.kind is FeatureKind.AREA
    assert feat.geom is not None
    assert feat.coord is not None
    assert feat.detail.area_kind == "heritage_area"
    assert feat.detail.boundary_source == "gis_spca"
    assert feat.detail.area_square_meters is not None
    assert float(feat.detail.area_square_meters) > 0
    assert feat.detail.administrative_office == "수원시"
    assert bundle.source_record.raw_data["geom_wkt"].startswith("POLYGON")


async def test_item_without_coord_has_none() -> None:
    [bundle] = await heritage_items_to_bundles(
        [_item(name_ko="좌표 없는 국보")], fetched_at=_FETCHED
    )
    assert bundle.feature.coord is None


# -- reverse geocoder 보강 ----------------------------------------------------


async def test_reverse_geocoder_fills_bjd_and_dedupes() -> None:
    calls: list[tuple[Decimal, Decimal]] = []

    async def _rg(coord: Coordinate) -> Address | None:
        calls.append((coord.lon, coord.lat))
        return Address(bjd_code="1111010100", sigungu_code="11110", sido_code="11")

    items = [
        _item(asno="1", name_ko="유산 A", longitude=126.98, latitude=37.57),
        _item(asno="2", name_ko="유산 B", longitude=126.98, latitude=37.57),
    ]
    bundles = await heritage_items_to_bundles(items, fetched_at=_FETCHED, reverse_geocoder=_rg)
    assert all(b.feature.address.bjd_code == "1111010100" for b in bundles)
    assert all(b.feature.feature_id.startswith("f_1111010100_p_") for b in bundles)
    # 같은 좌표 2건 → cached_reverse_geocoder가 1회만 호출.
    assert len(calls) == 1


async def test_location_text_fills_legal_without_geocoder() -> None:
    item = _item(name_ko="유산", location_text="서울특별시 종로구 세종로 1-1")
    [bundle] = await heritage_items_to_bundles([item], fetched_at=_FETCHED)
    assert bundle.feature.address.legal == "서울특별시 종로구 세종로 1-1"


async def test_region_sigungu_fallback_when_location_text_missing() -> None:
    item = _item(name_ko="유산", region="경상북도", sigungu="경주시")
    [bundle] = await heritage_items_to_bundles([item], fetched_at=_FETCHED)
    assert bundle.feature.address.legal == "경상북도 경주시"
    assert bundle.source_record.raw_address == "경상북도 경주시"


# -- event 변환 ---------------------------------------------------------------


async def test_event_bundle_mapping() -> None:
    event = _Event(
        sn="EVT-2026-001",
        title="종묘제례악 공연",
        starts_on=date(2026, 5, 1),
        ends_on=date(2026, 5, 3),
        place="종묘",
        tel_name="02-765-0195",
        address="서울특별시 종로구 종로 157",
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


async def test_event_empty_sn_derives_fallback_natural_key() -> None:
    event = _Event(
        sn="",
        title="무형유산 야간 공연",
        starts_on=date(2026, 7, 10),
        place="경복궁",
    )
    [bundle] = await heritage_events_to_bundles([event], fetched_at=_FETCHED)
    expected_key = "무형유산 야간 공연::2026-07-10::경복궁"
    assert bundle.source_record.source_entity_id == expected_key
    assert bundle.feature.detail.content_id == expected_key
    assert bundle.feature.name == "무형유산 야간 공연"


async def test_event_none_sn_falls_back_to_address_when_no_place() -> None:
    event = _Event(
        sn=None,
        title="행사",
        starts_on=None,
        place=None,
        address="서울특별시 종로구",
    )
    [bundle] = await heritage_events_to_bundles([event], fetched_at=_FETCHED)
    assert bundle.source_record.source_entity_id == "행사::::서울특별시 종로구"


async def test_event_fallback_key_is_deterministic() -> None:
    event = _Event(sn="", title="행사 A", starts_on=date(2026, 8, 1), place="종묘")
    a = (await heritage_events_to_bundles([event], fetched_at=_FETCHED))[0]
    b = (await heritage_events_to_bundles([event], fetched_at=_FETCHED))[0]
    assert a.feature.feature_id == b.feature.feature_id
    assert a.source_record.source_record_key == b.source_record.source_record_key


async def test_event_without_sn_and_title_is_skipped() -> None:
    events = [
        _Event(sn="", title=None, place="어딘가"),  # sn/title 모두 없음 → skip
        _Event(sn=None, title="  ", place="어딘가"),  # 정규화 후 빈 title → skip
        _Event(sn="EVT-1", title="살아남는 행사"),
    ]
    bundles = await heritage_events_to_bundles(events, fetched_at=_FETCHED)
    assert len(bundles) == 1
    assert bundles[0].feature.name == "살아남는 행사"


async def test_event_sn_without_title_uses_sn_as_name() -> None:
    event = _Event(sn="EVT-NO-TITLE", title=None)
    [bundle] = await heritage_events_to_bundles([event], fetched_at=_FETCHED)
    assert bundle.feature.name == "EVT-NO-TITLE"
    assert bundle.source_record.source_entity_id == "EVT-NO-TITLE"


async def test_deterministic_ids() -> None:
    item = _item(kdcd="13", name_ko="사적", longitude=127.0, latitude=37.5)
    a = (await heritage_items_to_bundles([item], fetched_at=_FETCHED))[0]
    b = (await heritage_items_to_bundles([item], fetched_at=_FETCHED))[0]
    assert a.feature.feature_id == b.feature.feature_id
    assert a.source_record.source_record_key == b.source_record.source_record_key


async def test_provider_name_constant() -> None:
    [bundle] = await heritage_items_to_bundles([_item(name_ko="x")], fetched_at=_FETCHED)
    assert bundle.source_record.provider == PROVIDER_NAME


# -- file_sources (미디어, docs/architecture/feature-files-rustfs.md §2.2) ------------------


async def test_heritage_image_url_becomes_file_source() -> None:
    item = _item(
        name_ko="통도사 대웅전",
        image_url="https://www.khs.go.kr/img/heritage/1234.jpg",
    )
    [bundle] = await heritage_items_to_bundles([item], fetched_at=_FETCHED)
    assert len(bundle.file_sources) == 1
    fs = bundle.file_sources[0]
    assert fs.source_url == "https://www.khs.go.kr/img/heritage/1234.jpg"
    assert fs.role == "primary"
    assert fs.file_type == "image"
    assert fs.feature_id == bundle.feature.feature_id  # FK 정합
    assert fs.source_record_key == bundle.source_record.source_record_key
    assert fs.provider == PROVIDER_NAME
    assert fs.alt_text == "통도사 대웅전"


async def test_heritage_no_image_url_empty_file_sources() -> None:
    [bundle] = await heritage_items_to_bundles(
        [_item(name_ko="이미지 없음")], fetched_at=_FETCHED
    )
    assert bundle.file_sources == []


async def test_event_main_image_becomes_file_source() -> None:
    event = _Event(
        sn="EVT-IMG-1",
        title="무형유산 공연",
        main_image="https://www.khs.go.kr/img/event/9.jpg",
    )
    [bundle] = await heritage_events_to_bundles([event], fetched_at=_FETCHED)
    assert len(bundle.file_sources) == 1
    assert bundle.file_sources[0].source_url == "https://www.khs.go.kr/img/event/9.jpg"
    assert bundle.file_sources[0].dataset_key == DATASET_KEY_EVENT
    assert bundle.file_sources[0].feature_id == bundle.feature.feature_id
