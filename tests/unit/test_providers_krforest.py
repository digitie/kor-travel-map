"""``test_providers_krforest`` — 산림청 휴양림/수목원 → FeatureBundle (T-RV-53a).

범위: ``recreation_forests_to_bundles`` / ``arboretums_to_bundles`` happy path,
좌표 nullable, 파생 자연키(institution_code 없음), place 카테고리/place_kind,
결정성, SourceLink PRIMARY, ReverseGeocoder bjd 보강.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from kortravelmap.dto import Address, Coordinate, FeatureBundle, FeatureKind, SourceRole
from kortravelmap.providers.krforest import (
    ARBORETUM_CATEGORY,
    DATASET_KEY_ARBORETUMS,
    DATASET_KEY_DULLE_TRAILS,
    DATASET_KEY_MOUNTAIN_TRAILS,
    DATASET_KEY_RECREATION_FORESTS,
    FOREST_ROUTE_CATEGORY,
    FOREST_ROUTE_MARKER_COLOR,
    KRFOREST_MARKER_COLOR,
    RECREATION_FOREST_CATEGORY,
)
from kortravelmap.providers.krforest import (
    arboretums_to_bundles as _arboretums_async,
)
from kortravelmap.providers.krforest import (
    forest_trails_to_bundles as _forest_trails_async,
)
from kortravelmap.providers.krforest import (
    recreation_forests_to_bundles as _recreation_forests_async,
)

KST = timezone(timedelta(hours=9))


def recreation_forests_to_bundles(items: Iterable[Any], **kwargs: Any) -> list[FeatureBundle]:
    return asyncio.run(_recreation_forests_async(items, **kwargs))


def arboretums_to_bundles(items: Iterable[Any], **kwargs: Any) -> list[FeatureBundle]:
    return asyncio.run(_arboretums_async(items, **kwargs))


def forest_trails_to_bundles(items: Iterable[Any], **kwargs: Any) -> list[FeatureBundle]:
    return asyncio.run(_forest_trails_async(items, **kwargs))


@dataclass(frozen=True)
class _Forest:
    """``RecreationForestItem`` Protocol 만족 fixture."""

    name: str | None
    sido_name: str | None
    forest_type: str | None
    address: str | None
    phone_number: str | None
    homepage_url: str | None
    latitude: float | None
    longitude: float | None
    institution_code: str | None
    raw: Any = field(default_factory=dict)


@dataclass(frozen=True)
class _Arb:
    """``ForestSpatialItem`` Protocol 만족 fixture."""

    name: str | None
    category: str | None
    address: str | None
    phone_number: str | None
    homepage_url: str | None
    latitude: float | None
    longitude: float | None
    region_code: str | None
    region_name: str | None
    raw: Any = field(default_factory=dict)


@dataclass(frozen=True)
class _Trail:
    """``ForestTrailItem`` Protocol 만족 fixture."""

    name: str | None
    source_id: str | None
    source_file: str | None
    layer_name: str | None
    geometry_type: str | None
    geometry: dict[str, Any] | None
    bbox: tuple[float, float, float, float] | None
    raw: Any = field(default_factory=dict)


_FOREST_1 = _Forest(
    name="유명산자연휴양림",
    sido_name="경기도",
    forest_type="국립",
    address="경기도 가평군 설악면 유명산길 79-53",
    phone_number="031-589-5487",
    homepage_url="https://www.foresttrip.go.kr",
    latitude=37.6042,
    longitude=127.4831,
    institution_code="KFS-0001",
)

_FOREST_NO_CODE = _Forest(
    name="대관령자연휴양림",
    sido_name="강원특별자치도",
    forest_type="국립",
    address="강원특별자치도 강릉시 성산면 대관령옛길 999",
    phone_number=None,
    homepage_url=None,
    latitude=None,
    longitude=None,
    institution_code=None,  # 파생키 name::sido
)

_ARB_1 = _Arb(
    name="국립세종수목원",
    category="국립수목원",
    address="세종특별자치시 수목원로 136",
    phone_number="044-251-0001",
    homepage_url="https://www.sjna.or.kr",
    latitude=36.4978,
    longitude=127.2895,
    region_code="36110",
    region_name="세종특별자치시",
)


_TRAIL_LINE = _Trail(
    name="북악산 부암동구간",
    source_id="mountain/111100101.zip/PMNTN.shp:PMNTN_SN:26719",
    source_file="mountain/111100101.zip/PMNTN.shp",
    layer_name="PMNTN",
    geometry_type="LineString",
    geometry={
        "type": "LineString",
        "coordinates": [[126.9700, 37.5900], [126.9800, 37.5950]],
    },
    bbox=(126.9700, 37.5900, 126.9800, 37.5950),
    raw={"MNTN_NM": "북악산", "PMNTN_NM": "부암동구간", "PMNTN_SN": "26719"},
)

_TRAIL_MULTI = _Trail(
    name="지리산둘레길 1구간",
    source_id="dulle/1.shp:Name:1",
    source_file="dulle/1.shp",
    layer_name="dulle",
    geometry_type="MultiLineString",
    geometry={
        "type": "MultiLineString",
        "coordinates": [
            [[127.7000, 35.3000], [127.7100, 35.3050]],
            [[127.7200, 35.3100], [127.7300, 35.3150]],
        ],
    },
    bbox=(127.7000, 35.3000, 127.7300, 35.3150),
    raw={"Name": "1", "ID": "DULE-1"},
)

_TRAIL_POINT = _Trail(
    name="산 정상 표지",
    source_id="point-1",
    source_file="point.shp",
    layer_name="point",
    geometry_type="Point",
    geometry={"type": "Point", "coordinates": [126.9750, 37.5920]},
    bbox=(126.9750, 37.5920, 126.9750, 37.5920),
)

_TRAIL_POLYGON = _Trail(
    name="산림 구역",
    source_id="polygon-1",
    source_file="polygon.shp",
    layer_name="polygon",
    geometry_type="Polygon",
    geometry={
        "type": "Polygon",
        "coordinates": [
            [
                [126.9700, 37.5900],
                [126.9800, 37.5900],
                [126.9800, 37.6000],
                [126.9700, 37.5900],
            ]
        ],
    },
    bbox=(126.9700, 37.5900, 126.9800, 37.6000),
)

_TRAIL_EMPTY = _Trail(
    name="빈 경로",
    source_id="empty-1",
    source_file="empty.shp",
    layer_name="empty",
    geometry_type="LineString",
    geometry={"type": "LineString", "coordinates": []},
    bbox=None,
)


def _now() -> datetime:
    return datetime(2026, 6, 7, 12, 0, 0, tzinfo=KST)


@pytest.mark.unit
def test_forest_trails_promote_only_lines_and_preserve_lineage() -> None:
    duplicate = replace(_TRAIL_LINE, name="중복 입력은 첫 행 승리")
    bundles = forest_trails_to_bundles(
        [_TRAIL_LINE, duplicate, _TRAIL_MULTI, _TRAIL_POINT, _TRAIL_POLYGON, _TRAIL_EMPTY],
        dataset_key=DATASET_KEY_MOUNTAIN_TRAILS,
        fetched_at=_now(),
    )

    assert len(bundles) == 2
    first, second = bundles
    assert first.feature.kind == FeatureKind.ROUTE
    assert first.feature.category == FOREST_ROUTE_CATEGORY
    assert first.feature.marker_color == FOREST_ROUTE_MARKER_COLOR
    assert first.feature.geom is not None
    assert first.feature.geom.startswith("LINESTRING")
    assert first.feature.name == "북악산 부암동구간"
    assert first.feature.detail is not None
    assert first.feature.detail.route_type == "hiking_trail"  # type: ignore[union-attr]
    assert first.source_record.source_entity_type == "mountain_trail_segment"
    assert first.source_record.raw_data["_kortravelmap_spatial"]["geometry_type"] == (
        "LineString"
    )
    assert second.feature.geom is not None
    assert second.feature.geom.startswith("MULTILINESTRING")
    assert second.feature.detail is not None
    assert second.feature.detail.route_type == "hiking_trail"  # type: ignore[union-attr]


@pytest.mark.unit
def test_forest_dulle_route_type_and_deterministic_fallback_key() -> None:
    no_source_id = replace(_TRAIL_MULTI, source_id=None)
    a = forest_trails_to_bundles(
        [no_source_id], dataset_key=DATASET_KEY_DULLE_TRAILS, fetched_at=_now()
    )[0]
    b = forest_trails_to_bundles(
        [no_source_id], dataset_key=DATASET_KEY_DULLE_TRAILS, fetched_at=_now()
    )[0]

    assert a.source_record.source_entity_type == "dulle_trail_segment"
    assert a.source_record.source_entity_id == b.source_record.source_entity_id
    assert a.feature.feature_id == b.feature.feature_id
    assert a.feature.detail is not None
    assert a.feature.detail.route_type == "trekking"  # type: ignore[union-attr]


@pytest.mark.unit
def test_forest_route_reverse_geocoder_and_dataset_guard() -> None:
    async def _fake_rg(coord: Coordinate) -> Address | None:
        return Address(bjd_code="1111010100", sigungu_code="11110", sido_code="11")

    bundle = forest_trails_to_bundles(
        [_TRAIL_LINE],
        dataset_key=DATASET_KEY_MOUNTAIN_TRAILS,
        fetched_at=_now(),
        reverse_geocoder=_fake_rg,
    )[0]
    assert bundle.feature.address.bjd_code == "1111010100"
    assert bundle.feature.feature_id.startswith("f_1111010100_r_")

    with pytest.raises(KeyError, match="route dataset_key"):
        forest_trails_to_bundles(
            [_TRAIL_LINE], dataset_key="krforest_unknown", fetched_at=_now()
        )


@pytest.mark.unit
def test_recreation_forest_bundle_per_item_and_order() -> None:
    bundles = recreation_forests_to_bundles([_FOREST_1, _FOREST_NO_CODE], fetched_at=_now())
    assert len(bundles) == 2
    assert bundles[0].source_record.source_entity_id == "KFS-0001"


@pytest.mark.unit
def test_recreation_forest_feature_fields() -> None:
    bundle = recreation_forests_to_bundles([_FOREST_1], fetched_at=_now())[0]
    feature = bundle.feature
    assert feature.kind == FeatureKind.PLACE
    assert feature.name == "유명산자연휴양림"
    assert feature.category == RECREATION_FOREST_CATEGORY  # 03030000
    assert feature.marker_color == KRFOREST_MARKER_COLOR
    assert feature.marker_icon  # 비어있지 않음(min_length=1)
    assert feature.coord is not None
    assert float(feature.coord.lat) == pytest.approx(37.6042)
    assert float(feature.coord.lon) == pytest.approx(127.4831)
    detail = feature.detail
    assert detail is not None
    assert detail.place_kind == "recreation_forest"  # type: ignore[union-attr]
    assert detail.phones == ["031-589-5487"]  # type: ignore[union-attr]
    assert (  # forest_type가 facility_info에 보존
        detail.facility_info["forest_type"] == "국립"  # type: ignore[union-attr]
    )
    assert feature.feature_id.startswith("f_global_p_")


@pytest.mark.unit
def test_recreation_forest_derived_key_when_no_institution_code() -> None:
    bundle = recreation_forests_to_bundles([_FOREST_NO_CODE], fetched_at=_now())[0]
    # institution_code 없음 → name::sido 파생키.
    assert bundle.source_record.source_entity_id == "대관령자연휴양림::강원특별자치도"
    assert bundle.feature.coord is None
    assert bundle.feature.feature_id.startswith("f_global_p_")


@pytest.mark.unit
def test_arboretum_feature_fields_and_category() -> None:
    bundle = arboretums_to_bundles([_ARB_1], fetched_at=_now())[0]
    feature = bundle.feature
    assert feature.kind == FeatureKind.PLACE
    assert feature.name == "국립세종수목원"
    assert feature.category == ARBORETUM_CATEGORY  # 01030000
    detail = feature.detail
    assert detail is not None
    assert detail.place_kind == "arboretum"  # type: ignore[union-attr]
    # 안정키 없음 → name::region_code 파생.
    assert bundle.source_record.source_entity_id == "국립세종수목원::36110"
    assert bundle.source_record.dataset_key == DATASET_KEY_ARBORETUMS


@pytest.mark.unit
def test_source_record_provider_and_dataset() -> None:
    source = recreation_forests_to_bundles([_FOREST_1], fetched_at=_now())[0].source_record
    assert source.provider == "python-krforest-api"
    assert source.dataset_key == DATASET_KEY_RECREATION_FORESTS
    assert source.source_entity_type == "recreation_forest"
    assert source.raw_data["institution_code"] == "KFS-0001"


@pytest.mark.unit
def test_source_link_primary() -> None:
    link = recreation_forests_to_bundles([_FOREST_1], fetched_at=_now())[0].source_link
    assert link.source_role == SourceRole.PRIMARY
    assert link.match_method == "natural_key"
    assert link.confidence == 100


@pytest.mark.unit
def test_bundle_fk_consistency_and_determinism() -> None:
    a = recreation_forests_to_bundles([_FOREST_1], fetched_at=_now())[0]
    b = recreation_forests_to_bundles([_FOREST_1], fetched_at=_now())[0]
    assert a.feature.feature_id == a.source_link.feature_id
    assert a.source_record.source_record_key == a.source_link.source_record_key
    assert a.feature.feature_id == b.feature.feature_id
    assert a.source_record.source_record_key == b.source_record.source_record_key


@pytest.mark.unit
def test_naive_fetched_at_rejected() -> None:
    with pytest.raises(ValueError, match="aware"):
        recreation_forests_to_bundles([_FOREST_1], fetched_at=datetime(2026, 6, 7, 12, 0, 0))


@pytest.mark.unit
def test_reverse_geocoder_fills_bjd_code() -> None:
    async def _fake_rg(coord: Coordinate) -> Address | None:
        return Address(bjd_code="4151025000", sigungu_code="41510", sido_code="41")

    bundle = recreation_forests_to_bundles(
        [_FOREST_1], fetched_at=_now(), reverse_geocoder=_fake_rg
    )[0]
    assert bundle.feature.address.bjd_code == "4151025000"
    assert bundle.feature.feature_id.startswith("f_4151025000_p_")


# -- T-VN-H30C: AdminEvidence 무장 -----------------------------------------
#
# krforest가 MOIS와 다른 지점: `_resolve_address`의 reverse 호출 조건에 payload 코드가
# **없다**. 따라서 obs(좌표 reverse)와 claim(payload region_code)이 동시에 성립해
# `grade == "dual"`이 실제로 나오고 staleness 축이 발화한다.
#
# prod 실측(2026-08-03): arboretum 205건 전량이 8자리 숫자 = `emd`.


def _rg(bjd: str | None):
    """지정한 bjd_code를 돌려주는 reverse geocoder."""

    async def _fake(coord: Coordinate) -> Address | None:
        if bjd is None:
            return None
        return Address(bjd_code=bjd, sigungu_code=bjd[:5], sido_code=bjd[:2])

    return _fake


@pytest.mark.unit
def test_arboretum_admin_evidence_is_dual_and_detects_staleness() -> None:
    """payload 코드와 reverse 결과가 어긋나면 dual + staleness warning이 나온다."""
    from kortravelmap.dagster.validation import validate_feature_bundle_address

    item = replace(_ARB_1, region_code="36110340")  # 8자리 = emd
    bundle = arboretums_to_bundles([item], fetched_at=_now(), reverse_geocoder=_rg("3611010900"))[0]

    evidence = bundle.admin_evidence
    assert evidence is not None
    assert evidence.grade == "dual", "krforest는 MOIS와 달리 dual이 성립해야 한다"
    assert evidence.claim_kind == "emd"
    assert evidence.claim_code == "36110340"
    assert evidence.obs_code == "3611010900"

    codes = validate_feature_bundle_address(bundle).issue_codes
    assert any(code.startswith("admin_code_stale_") for code in codes), (
        f"staleness warning이 나오지 않았다: {codes}"
    )


@pytest.mark.unit
def test_arboretum_admin_evidence_no_issue_when_codes_agree() -> None:
    """같은 행정구역이면 warning을 만들지 않는다 — 오탐 방지."""
    from kortravelmap.dagster.validation import validate_feature_bundle_address

    item = replace(_ARB_1, region_code="36110340")
    bundle = arboretums_to_bundles([item], fetched_at=_now(), reverse_geocoder=_rg("3611034000"))[0]

    assert bundle.admin_evidence is not None
    assert bundle.admin_evidence.grade == "dual"
    codes = validate_feature_bundle_address(bundle).issue_codes
    assert not [code for code in codes if code.startswith("admin_code_stale_")]


@pytest.mark.unit
@pytest.mark.parametrize(
    ("region_code", "expected_kind"),
    [
        ("4173025000", "bjd"),
        ("36110340", "emd"),
        ("36110", "sigungu"),
        ("36", "sido"),
    ],
)
def test_arboretum_claim_kind_dispatch_by_length(region_code: str, expected_kind: str) -> None:
    """길이 → claim_kind 디스패치. 어긋나면 DTO validator가 ValueError를 던진다."""
    item = replace(_ARB_1, region_code=region_code)
    bundle = arboretums_to_bundles([item], fetched_at=_now())[0]

    evidence = bundle.admin_evidence
    assert evidence is not None
    assert evidence.claim_code == region_code
    assert evidence.claim_kind == expected_kind


@pytest.mark.unit
@pytest.mark.parametrize(
    "region_code",
    [
        "4173025000.0",  # DBF 수치 필드가 float로 읽힌 경우
        "36-110",
        "세종",
        "",
        "   ",
        "1",  # 1자리
        "361",  # 3자리
        "3611",  # 4자리
        "361103",  # 6자리
        "3611034",  # 7자리
        "361103400",  # 9자리
        "36110340000",  # 11자리
    ],
)
def test_arboretum_rejects_unsupported_region_code_without_raising(
    region_code: str,
) -> None:
    """지원하지 않는 형태는 조용히 claim 없음으로 떨어진다 — asset이 죽으면 안 된다.

    원천 `python-krforest-api`는 region_code에 길이·숫자 검증을 전혀 하지 않는다
    (`parser.py`의 `str(value).strip()`). `AdminEvidence` validator는 그런 값에
    ValueError를 던지므로, provider에서 거르지 않으면 **적재 전체가 중단된다**.
    """
    item = replace(_ARB_1, region_code=region_code)
    bundle = arboretums_to_bundles([item], fetched_at=_now())[0]

    evidence = bundle.admin_evidence
    assert evidence is not None
    assert evidence.claim_code is None
    assert evidence.claim_kind is None


@pytest.mark.unit
def test_arboretum_obs_axis_is_reverse_only_not_address_resolver() -> None:
    """obs 축은 좌표 reverse 결과만이다 — 정지오코딩 결과가 섞이면 자기 비교가 된다.

    `address_resolver`는 provider **주소 문자열**을 정지오코딩한 것이라 claim_text와
    출처가 같다. 그걸 obs로 쓰면 "payload가 payload와 다른가"를 묻게 된다.
    """

    async def _no_reverse(coord: Coordinate) -> Address | None:
        return None

    async def _resolver(address: Address) -> Address | None:
        return Address(bjd_code="3611010900", sigungu_code="36110", sido_code="36")

    item = replace(_ARB_1, region_code="36110340")
    bundle = arboretums_to_bundles(
        [item],
        fetched_at=_now(),
        reverse_geocoder=_no_reverse,
        address_resolver=_resolver,
    )[0]

    # address 자체는 resolver 결과로 채워진다.
    assert bundle.feature.address.bjd_code == "3611010900"
    # 그러나 obs 축은 비어 있어야 한다.
    evidence = bundle.admin_evidence
    assert evidence is not None
    assert evidence.obs_code is None
    assert evidence.grade == "claim_only"


@pytest.mark.unit
def test_recreation_forest_never_has_claim_axis() -> None:
    """휴양림 payload에는 행정코드 필드가 없다 — 누가 나중에 발명하지 못하게 고정."""
    bundle = recreation_forests_to_bundles(
        [_FOREST_1], fetched_at=_now(), reverse_geocoder=_rg("4151025000")
    )[0]
    evidence = bundle.admin_evidence
    assert evidence is None or evidence.claim_code is None


@pytest.mark.unit
def test_arming_does_not_add_findings_for_records_without_claim() -> None:
    """무장 부수효과 중립성 — claim이 없는 레코드의 issue 집합이 늘지 않는다.

    MOIS 무장은 `reverse_geocode_not_attempted`를 새로 터뜨렸다. krforest는 prod asset이
    geocoder를 항상 주입하므로 그 위험이 없다는 것을 고정한다.
    """
    from kortravelmap.dagster.validation import validate_feature_bundle_address

    item = replace(_ARB_1, region_code=None)
    bundle = arboretums_to_bundles([item], fetched_at=_now(), reverse_geocoder=_rg("3611010900"))[0]

    codes = set(validate_feature_bundle_address(bundle).issue_codes)
    assert "reverse_geocode_not_attempted" not in codes
    assert not [code for code in codes if code.startswith("admin_code_stale_")]
    assert bundle.admin_evidence is not None
    assert bundle.admin_evidence.grade == "obs_only"
