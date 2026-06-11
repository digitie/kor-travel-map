"""``test_providers_standard_data`` — datagokr 전국문화축제표준데이터 변환 (PR#34, ADR-042).

본 PR 테스트 범위:
- 5건 fixture (좌표 있음 3 + 좌표 nullable 2, KST aware).
- ``cultural_festivals_to_bundles`` happy path.
- 좌표 없는 case는 ``Feature.coord=None`` + ``feature_id`` ``global`` fallback.
- ``starts_on > ends_on``은 ``EventDetail`` validator에서 reject.
- 결정성 — 같은 입력은 항상 같은 ``feature_id`` / ``source_record_key``.
- ``FeatureBundle`` FK consistency (model_validator 가동).
- ``ReverseGeocoder`` 적용 시 ``Address.bjd_code`` 채워짐.
"""

from __future__ import annotations

import asyncio
import dataclasses
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest

from krtour.map.dto import Address, Coordinate, FeatureBundle, FeatureKind, SourceRole
from krtour.map.providers.standard_data import (
    DATASET_KEY_CULTURAL_FESTIVALS,
    FESTIVAL_CATEGORY,
    FESTIVAL_MARKER_COLOR,
    FESTIVAL_MARKER_ICON,
)
from krtour.map.providers.standard_data import (
    cultural_festivals_to_bundles as _cultural_festivals_to_bundles_async,
)

KST = timezone(timedelta(hours=9))


def cultural_festivals_to_bundles(
    items: Iterable[Any], **kwargs: Any
) -> list[FeatureBundle]:
    """sync 테스트 ergonomics — 실제 async 변환을 asyncio.run으로 구동."""
    return asyncio.run(_cultural_festivals_to_bundles_async(items, **kwargs))


# -- 테스트 fixture (CulturalFestivalItem Protocol 만족 dataclass) ----------


@dataclass(frozen=True)
class _Fixture:
    """``CulturalFestivalItem`` Protocol 만족 + 테스트용 frozen dataclass.

    provider 실모델 ``PublicCulturalFestival`` 필드명 (ADR-044 재정렬, #374).
    """

    fstvl_nm: str | None
    opar: str | None
    fstvl_start_date: date | None
    fstvl_end_date: date | None
    fstvl_co: str | None
    mnnst_nm: str | None
    auspc_instt_nm: str | None
    suprt_instt_nm: str | None
    phone_number: str | None
    homepage_url: str | None
    relate_info: str | None
    rdnmadr: str | None
    lnmadr: str | None
    latitude: float | None
    longitude: float | None
    reference_date: date | None
    instt_code: str | None
    instt_nm: str | None


# 5건 — 좌표 있음 3 + 좌표 nullable 2 (SPRINT-2 §2.1 specification).
_F1 = _Fixture(
    fstvl_nm="서울 봄꽃 축제",
    opar="여의도공원",
    fstvl_start_date=date(2026, 4, 5),
    fstvl_end_date=date(2026, 4, 12),
    fstvl_co="봄꽃 만개에 맞춘 가족 단위 봄꽃 축제.",
    mnnst_nm="영등포구청",
    auspc_instt_nm=None,
    suprt_instt_nm=None,
    phone_number="02-2670-3114",
    homepage_url=None,
    relate_info=None,
    rdnmadr="서울특별시 영등포구 여의공원로 120",
    lnmadr="서울특별시 영등포구 여의도동 8",
    latitude=37.5263,
    longitude=126.9239,
    reference_date=date(2026, 3, 1),
    instt_code=None,
    instt_nm="서울특별시 영등포구",
)

_F2 = _Fixture(
    fstvl_nm="부산 바다 축제",
    opar="해운대 해수욕장",
    fstvl_start_date=date(2026, 8, 1),
    fstvl_end_date=date(2026, 8, 7),
    fstvl_co="해운대 메인 비치 여름 축제.",
    mnnst_nm="해운대구청",
    auspc_instt_nm=None,
    suprt_instt_nm=None,
    phone_number="051-749-4000",
    homepage_url=None,
    relate_info=None,
    rdnmadr="부산광역시 해운대구 해운대해변로 264",
    lnmadr="부산광역시 해운대구 우동 620",
    latitude=35.1587,
    longitude=129.1604,
    reference_date=date(2026, 6, 1),
    instt_code=None,
    instt_nm="부산광역시 해운대구",
)

_F3 = _Fixture(
    fstvl_nm="제주 유채꽃 축제",
    opar="가시리 마을",
    fstvl_start_date=date(2026, 4, 1),
    fstvl_end_date=date(2026, 4, 30),
    fstvl_co="제주 봄철 유채꽃 만개에 맞춘 한 달짜리 축제.",
    mnnst_nm="서귀포시청",
    auspc_instt_nm=None,
    suprt_instt_nm=None,
    phone_number="064-740-6000",
    homepage_url=None,
    relate_info=None,
    rdnmadr="제주특별자치도 서귀포시 표선면 가시로 565번길 41",
    lnmadr="제주특별자치도 서귀포시 표선면 가시리",
    latitude=33.3893,
    longitude=126.7831,
    reference_date=date(2026, 3, 1),
    instt_code=None,
    instt_nm="제주특별자치도 서귀포시",
)

# 좌표 nullable 2건.
_F4_NO_COORD = _Fixture(
    fstvl_nm="전남 청년 문화 축제",
    opar="광주광역시 광산구청 광장",  # 좌표는 표준데이터에 미기재
    fstvl_start_date=date(2026, 9, 18),
    fstvl_end_date=date(2026, 9, 19),
    fstvl_co="전남 권역 청년 문화 행사.",
    mnnst_nm="광산구청 문화체육과",
    auspc_instt_nm=None,
    suprt_instt_nm=None,
    phone_number="062-960-8800",
    homepage_url=None,
    relate_info=None,
    rdnmadr="광주광역시 광산구 광산로 29번길 15",
    lnmadr=None,
    latitude=None,
    longitude=None,
    reference_date=date(2026, 8, 15),
    instt_code=None,
    instt_nm="광주광역시 광산구",
)

_F5_NO_COORD_MINIMAL = _Fixture(
    fstvl_nm="강원 산촌 마을 축제",
    opar=None,  # 장소도 미상
    fstvl_start_date=None,
    fstvl_end_date=None,
    fstvl_co=None,
    mnnst_nm=None,
    auspc_instt_nm=None,
    suprt_instt_nm=None,
    phone_number=None,
    homepage_url=None,
    relate_info=None,
    rdnmadr=None,
    lnmadr=None,
    latitude=None,
    longitude=None,
    reference_date=None,
    instt_code=None,
    instt_nm=None,
)


_ALL_FIXTURES = [_F1, _F2, _F3, _F4_NO_COORD, _F5_NO_COORD_MINIMAL]


def _now() -> datetime:
    """ADR-019 — KST aware now()."""
    return datetime(2026, 5, 27, 23, 0, 0, tzinfo=KST)


# -- 테스트 본체 ----------------------------------------------------------


@pytest.mark.unit
def test_returns_bundle_per_item() -> None:
    """N items → N bundles, 순서 유지."""
    bundles = cultural_festivals_to_bundles(_ALL_FIXTURES, fetched_at=_now())
    assert len(bundles) == 5
    # 순서 유지 확인 — 자연키는 name::address 파생 (관리번호 컬럼 없음, #374).
    natural_keys = [b.source_record.source_entity_id for b in bundles]
    assert natural_keys == [
        f"{f.fstvl_nm}::{f.rdnmadr or f.lnmadr or ''}" for f in _ALL_FIXTURES
    ]


@pytest.mark.unit
def test_row_without_festival_name_is_skipped() -> None:
    """축제명(fstvl_nm) 없는 row는 skip — bundle 미생성 (#374)."""
    nameless = _Fixture(
        fstvl_nm=None,
        opar=None,
        fstvl_start_date=None,
        fstvl_end_date=None,
        fstvl_co=None,
        mnnst_nm=None,
        auspc_instt_nm=None,
        suprt_instt_nm=None,
        phone_number=None,
        homepage_url=None,
        relate_info=None,
        rdnmadr=None,
        lnmadr=None,
        latitude=None,
        longitude=None,
        reference_date=None,
        instt_code=None,
        instt_nm=None,
    )
    blank_name = dataclasses.replace(nameless, fstvl_nm="   ")
    bundles = cultural_festivals_to_bundles(
        [nameless, _F1, blank_name], fetched_at=_now()
    )
    assert len(bundles) == 1
    assert bundles[0].feature.name == "서울 봄꽃 축제"


@pytest.mark.unit
def test_bundle_feature_fields_happy_path() -> None:
    """좌표 있는 happy path — Feature 필드 정합."""
    bundles = cultural_festivals_to_bundles([_F1], fetched_at=_now())
    bundle = bundles[0]
    feature = bundle.feature

    assert feature.kind == FeatureKind.EVENT
    assert feature.name == "서울 봄꽃 축제"
    assert feature.category == FESTIVAL_CATEGORY  # "01000000"
    assert feature.marker_icon == FESTIVAL_MARKER_ICON  # "star"
    assert feature.marker_color == FESTIVAL_MARKER_COLOR  # "P-11"
    assert feature.coord is not None
    assert float(feature.coord.lat) == pytest.approx(37.5263)
    assert float(feature.coord.lon) == pytest.approx(126.9239)
    assert feature.feature_id.startswith("f_global_e_")
    # bjd_code는 reverse_geocoder=None이므로 'global' fallback.


@pytest.mark.unit
def test_event_detail_dates_and_kind() -> None:
    """``EventDetail`` 필드 — event_kind='festival' + 날짜 매핑."""
    bundles = cultural_festivals_to_bundles([_F1], fetched_at=_now())
    detail = bundles[0].feature.detail
    # detail은 EventDetail 인스턴스.
    assert detail is not None
    # mypy narrowing은 unit test에서는 attribute로 직접 검사.
    assert detail.event_kind == "festival"  # type: ignore[union-attr]
    assert detail.starts_on == date(2026, 4, 5)  # type: ignore[union-attr]
    assert detail.ends_on == date(2026, 4, 12)  # type: ignore[union-attr]
    assert detail.venue_name == "여의도공원"  # type: ignore[union-attr]
    assert detail.tel == "02-2670-3114"  # type: ignore[union-attr]


@pytest.mark.unit
def test_no_coordinate_yields_none_coord() -> None:
    """좌표 nullable — Feature.coord=None + feature_id global fallback."""
    bundles = cultural_festivals_to_bundles(
        [_F4_NO_COORD, _F5_NO_COORD_MINIMAL], fetched_at=_now()
    )
    for bundle in bundles:
        assert bundle.feature.coord is None
        # bjd_code 없으면 feature_id는 global fallback (make_feature_id 룰).
        assert bundle.feature.feature_id.startswith("f_global_e_")


@pytest.mark.unit
def test_minimal_fixture_no_address_no_dates() -> None:
    """모든 nullable field가 None인 case — Feature는 여전히 valid."""
    bundles = cultural_festivals_to_bundles([_F5_NO_COORD_MINIMAL], fetched_at=_now())
    bundle = bundles[0]
    assert bundle.feature.name == "강원 산촌 마을 축제"
    detail = bundle.feature.detail
    assert detail is not None
    assert detail.starts_on is None  # type: ignore[union-attr]
    assert detail.ends_on is None  # type: ignore[union-attr]
    assert bundle.feature.address.road is None
    assert bundle.feature.address.legal is None
    assert bundle.feature.address.bjd_code is None


@pytest.mark.unit
def test_source_record_provider_and_dataset() -> None:
    """SourceRecord — canonical provider name + dataset_key 정확."""
    bundles = cultural_festivals_to_bundles([_F2], fetched_at=_now())
    source = bundles[0].source_record
    assert source.provider == "data.go.kr-standard"  # ADR-024
    assert source.dataset_key == DATASET_KEY_CULTURAL_FESTIVALS
    assert source.source_entity_type == "cultural_festival"
    # 자연키는 name::address 파생 (관리번호 컬럼 없음, ADR-009 ``::``, #374).
    assert source.source_entity_id == (
        "부산 바다 축제::부산광역시 해운대구 해운대해변로 264"
    )
    assert source.raw_payload_hash != ""
    assert len(source.raw_payload_hash) == 32  # PAYLOAD_HASH_DEFAULT_LENGTH
    # raw_data canonical 직렬화 (sort_keys 가동, sets 등 거부) 정합 —
    # key는 provider 필드명 그대로 (ADR-044).
    assert source.raw_data["fstvl_nm"] == "부산 바다 축제"
    assert source.raw_data["latitude"] == "35.1587"
    assert source.raw_data["longitude"] == "129.1604"
    assert source.raw_data["instt_nm"] == "부산광역시 해운대구"


@pytest.mark.unit
def test_source_link_role_is_primary_and_confidence_100() -> None:
    """ADR-042 — datagokr는 1차 source. source_role=PRIMARY + confidence=100."""
    bundles = cultural_festivals_to_bundles([_F1], fetched_at=_now())
    link = bundles[0].source_link
    assert link.source_role == SourceRole.PRIMARY
    assert link.match_method == "natural_key"
    assert link.confidence == 100
    assert link.is_primary_source is True


@pytest.mark.unit
def test_bundle_fk_consistency() -> None:
    """``FeatureBundle.model_validator`` — feature_id / source_record_key 가
    bundle 안에서 닫혀 있는지 (PR#26 review P0-4 보강)."""
    bundles = cultural_festivals_to_bundles(_ALL_FIXTURES, fetched_at=_now())
    for bundle in bundles:
        assert bundle.feature.feature_id == bundle.source_link.feature_id
        assert (
            bundle.source_record.source_record_key
            == bundle.source_link.source_record_key
        )


@pytest.mark.unit
def test_determinism_same_input_same_ids() -> None:
    """같은 fixture 두 번 → 같은 feature_id / source_record_key (ADR-009)."""
    bundles_a = cultural_festivals_to_bundles([_F1], fetched_at=_now())
    bundles_b = cultural_festivals_to_bundles([_F1], fetched_at=_now())
    assert bundles_a[0].feature.feature_id == bundles_b[0].feature.feature_id
    assert (
        bundles_a[0].source_record.source_record_key
        == bundles_b[0].source_record.source_record_key
    )


@pytest.mark.unit
def test_payload_hash_differs_when_payload_changes() -> None:
    """payload 변경 시 ``raw_payload_hash`` + ``source_record_key`` 변경 (이력)."""
    bundles_a = cultural_festivals_to_bundles([_F1], fetched_at=_now())
    # 축제내용(fstvl_co) 변경한 새 fixture.
    f1_modified = dataclasses.replace(
        _F1, fstvl_co="새로 바뀐 설명 — payload hash 변동 시나리오."
    )
    bundles_b = cultural_festivals_to_bundles([f1_modified], fetched_at=_now())
    # source_record_key는 raw_payload_hash 포함 → 다름.
    assert (
        bundles_a[0].source_record.source_record_key
        != bundles_b[0].source_record.source_record_key
    )
    # feature_id는 natural_key + provider/dataset 기반 → 같음 (이력은
    # source_records로만, feature는 하나로 유지).
    assert (
        bundles_a[0].feature.feature_id == bundles_b[0].feature.feature_id
    )


@pytest.mark.unit
def test_invalid_date_order_rejected() -> None:
    """``EventDetail`` validator — ``ends_on < starts_on``은 ValidationError."""
    bad_fixture = dataclasses.replace(
        _F5_NO_COORD_MINIMAL,
        fstvl_nm="잘못된 날짜 축제",
        fstvl_start_date=date(2026, 5, 10),
        fstvl_end_date=date(2026, 5, 1),  # ends_on < starts_on
    )
    with pytest.raises(ValueError, match="ends_on .* must be >= starts_on"):
        cultural_festivals_to_bundles([bad_fixture], fetched_at=_now())


@pytest.mark.unit
def test_naive_fetched_at_rejected() -> None:
    """ADR-019 — naive datetime fetched_at은 SourceRecord validator에서 reject."""
    naive_now = datetime(2026, 5, 27, 23, 0, 0)  # tzinfo 없음
    with pytest.raises(ValueError, match="aware"):
        cultural_festivals_to_bundles([_F1], fetched_at=naive_now)


@pytest.mark.unit
def test_reverse_geocoder_fills_bjd_and_codes() -> None:
    """async ReverseGeocoder가 좌표→bjd_code 변환 시 Address.bjd_code 채워짐."""

    async def _fake_rg(coord: Coordinate) -> Address | None:
        # 영등포구 여의도동의 가짜 bjd_code.
        return Address(
            bjd_code="1156010100",
            sigungu_code="11560",
            sido_code="11",
            admin="서울특별시 영등포구 여의동",
        )

    bundles = cultural_festivals_to_bundles(
        [_F1], fetched_at=_now(), reverse_geocoder=_fake_rg
    )
    addr = bundles[0].feature.address
    assert addr.bjd_code == "1156010100"
    assert addr.sigungu_code == "11560"
    assert addr.sido_code == "11"
    assert addr.admin == "서울특별시 영등포구 여의동"
    # feature_id는 bjd_code 기반으로 변경.
    assert bundles[0].feature.feature_id.startswith("f_1156010100_e_")


@pytest.mark.unit
def test_reverse_geocoder_skipped_when_no_coord() -> None:
    """좌표 없으면 reverse_geocoder 호출 안 함 (불필요 await 회피)."""
    calls: list[tuple[Decimal, Decimal]] = []

    async def _recording_rg(coord: Coordinate) -> Address | None:
        calls.append((coord.lon, coord.lat))
        return None

    bundles = cultural_festivals_to_bundles(
        [_F4_NO_COORD], fetched_at=_now(), reverse_geocoder=_recording_rg
    )
    assert calls == []  # 좌표 없으니 호출 안 됨
    assert bundles[0].feature.coord is None
    assert bundles[0].feature.address.bjd_code is None


@pytest.mark.unit
def test_address_resolver_fills_bjd_when_coord_missing() -> None:
    """좌표/bjd가 없으면 주소 geocode resolver가 법정동코드를 보강한다."""
    calls: list[Address] = []

    async def _resolver(address: Address) -> Address | None:
        calls.append(address)
        return Address(
            road=address.road,
            legal=address.legal,
            bjd_code="2920010100",
            sigungu_code="29200",
            sido_code="29",
            admin="광주광역시 광산구 송정동",
        )

    bundles = cultural_festivals_to_bundles(
        [_F4_NO_COORD], fetched_at=_now(), address_resolver=_resolver
    )

    assert len(calls) == 1
    assert calls[0].road == "광주광역시 광산구 광산로 29번길 15"
    addr = bundles[0].feature.address
    assert addr.bjd_code == "2920010100"
    assert addr.sigungu_code == "29200"
    assert addr.sido_code == "29"
    assert addr.admin == "광주광역시 광산구 송정동"
    assert bundles[0].feature.feature_id.startswith("f_2920010100_e_")
