"""``Feature`` DTO + Coordinate + detail discriminator (ADR-018/019)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from kortravelmap.core import kst_now
from kortravelmap.dto import (
    AreaDetail,
    Coordinate,
    EventDetail,
    Feature,
    FeatureKind,
    FeatureStatus,
    NoticeDetail,
    PlaceDetail,
    RouteDetail,
)

# ── Coordinate (Korea bounds) ────────────────────────────────────────────


@pytest.mark.unit
def test_coordinate_korea_valid() -> None:
    """한국 본토 좌표 OK (서울)."""
    c = Coordinate(lon=126.97, lat=37.57)
    assert float(c.lon) == 126.97
    assert float(c.lat) == 37.57


@pytest.mark.unit
def test_coordinate_jeju_valid() -> None:
    """제주 좌표도 한국 경계 안."""
    c = Coordinate(lon=126.5, lat=33.4)
    assert float(c.lat) == 33.4


@pytest.mark.unit
def test_coordinate_out_of_korea_raises() -> None:
    """경계 밖 좌표는 ValidationError."""
    with pytest.raises(Exception, match="한국 경계"):
        Coordinate(lon=200.0, lat=37.5)
    with pytest.raises(Exception, match="한국 경계"):
        Coordinate(lon=127.0, lat=50.0)


@pytest.mark.unit
def test_coordinate_frozen() -> None:
    """Coordinate는 frozen — mutation 차단."""
    c = Coordinate(lon=127.0, lat=37.5)
    with pytest.raises(ValidationError):  # frozen 위반은 Pydantic ValidationError
        c.lon = 130.0  # type: ignore[misc]


# ── Feature 기본 ──────────────────────────────────────────────────────────


def _make_place_feature(**overrides: object) -> Feature:
    """테스트용 minimal place Feature."""
    defaults: dict[str, object] = dict(
        feature_id="place:test001",
        kind=FeatureKind.PLACE,
        name="테스트 장소",
        coord=Coordinate(lon=126.97, lat=37.57),
        category="02020101",  # 한식
        marker_icon="restaurant",
        marker_color="P-03",
        detail=PlaceDetail(feature_id="place:test001", place_kind="restaurant"),
    )
    defaults.update(overrides)
    return Feature(**defaults)  # type: ignore[arg-type]


@pytest.mark.unit
def test_feature_basic_place() -> None:
    """기본 place Feature 생성."""
    feature = _make_place_feature()
    assert feature.feature_id == "place:test001"
    assert feature.kind == FeatureKind.PLACE
    assert feature.status == FeatureStatus.ACTIVE
    assert feature.created_at.tzinfo is not None  # KST aware


@pytest.mark.unit
def test_feature_coord_optional() -> None:
    """coord=None 허용 (예: 좌표 없는 축제)."""
    feature = _make_place_feature(coord=None)
    assert feature.coord is None
    assert feature.coord_precision_digits is None


@pytest.mark.unit
def test_feature_coord_precision_defaults_when_coord_present() -> None:
    """좌표가 있으면 원천 precision 기본값 6을 보존한다."""
    feature = _make_place_feature()
    assert feature.coord_precision_digits == 6


@pytest.mark.unit
def test_feature_coord_precision_rejects_without_coord() -> None:
    """좌표가 없으면 precision 신호도 없어야 한다."""
    with pytest.raises(ValidationError, match="coord_precision_digits"):
        _make_place_feature(coord=None, coord_precision_digits=6)


# ── ADR-018: detail discriminator ────────────────────────────────────────


@pytest.mark.unit
def test_feature_detail_kind_mismatch_raises() -> None:
    """ADR-018 — kind=place인데 EventDetail이 들어오면 ValidationError."""
    event_detail = EventDetail(feature_id="x", event_kind="festival")
    with pytest.raises(ValidationError, match="PlaceDetail만 허용"):
        _make_place_feature(detail=event_detail)


@pytest.mark.unit
def test_feature_detail_dict_rejected_with_complete_keys() -> None:
    """ADR-018 — 완전한 PlaceDetail 키를 가진 dict도 거부 (mode=before).

    review report P0-1: 이전 테스트는 ``feature_id`` 누락으로 우연히 실패했음.
    완전한 키 셋을 가진 dict가 ``Pydantic union`` coercion으로 ``PlaceDetail``로
    변환되는 path를 막아야 함.
    """
    complete_dict = {"feature_id": "place:1", "place_kind": "cafe"}
    with pytest.raises(ValidationError, match="dict 입력 금지"):
        _make_place_feature(detail=complete_dict)  # type: ignore[arg-type]


@pytest.mark.unit
def test_feature_detail_dict_rejected_partial() -> None:
    """ADR-018 — partial dict도 마찬가지로 거부."""
    with pytest.raises(ValidationError, match="dict 입력 금지"):
        _make_place_feature(detail={"place_kind": "cafe"})  # type: ignore[arg-type]


@pytest.mark.unit
def test_feature_detail_dict_rejected_empty() -> None:
    """ADR-018 — 빈 dict도 거부."""
    with pytest.raises(ValidationError, match="dict 입력 금지"):
        _make_place_feature(detail={})  # type: ignore[arg-type]


@pytest.mark.unit
def test_feature_weather_kind_detail_must_be_none() -> None:
    """kind=weather에 detail이 들어오면 ValidationError (별도 WeatherValue 테이블)."""
    place_detail = PlaceDetail(feature_id="w:1", place_kind="weather_station")
    with pytest.raises(ValidationError, match="detail을 가질 수 없"):
        Feature(
            feature_id="w:1",
            kind=FeatureKind.WEATHER,
            name="관측소",
            coord=Coordinate(lon=127.0, lat=37.5),
            category="01050100",
            marker_icon="natural",
            marker_color="P-08",
            detail=place_detail,  # weather는 detail=None 이어야
        )


@pytest.mark.unit
def test_feature_notice_detail_works() -> None:
    """kind=notice + NoticeDetail OK."""
    notice = NoticeDetail(
        feature_id="notice:fire001",
        notice_type="fire_alert",  # ADR-027
        severity=4,
        payload={"domain": "forest"},
    )
    f = Feature(
        feature_id="notice:fire001",
        kind=FeatureKind.NOTICE,
        name="설악산 산불경보",
        category="01020101",
        marker_icon="fire-station",
        marker_color="P-15",
        detail=notice,
    )
    assert f.detail is notice
    assert isinstance(f.detail, NoticeDetail)


@pytest.mark.unit
def test_feature_area_hazard_zone() -> None:
    """ADR-027 — area_kind='hazard_zone' Feature."""
    area = AreaDetail(
        feature_id="area:hazard001",
        area_kind="hazard_zone",
        payload={"domain": "forest", "hazard_type": "rockfall"},
    )
    f = Feature(
        feature_id="area:hazard001",
        kind=FeatureKind.AREA,
        name="설악산 낙석위험구역",
        category="00000000",  # area는 카테고리 트리 외
        marker_icon="barrier",
        marker_color="P-13",
        detail=area,
    )
    assert isinstance(f.detail, AreaDetail)
    assert f.detail.area_kind == "hazard_zone"


@pytest.mark.unit
def test_feature_route_normalization() -> None:
    """route_type alias 정규화 (한국어 입력 → canonical)."""
    route = RouteDetail(feature_id="route:1", route_type="등산로")
    assert route.route_type == "hiking_trail"


@pytest.mark.unit
def test_feature_route_facility_road_normalization() -> None:
    """ADR-028 amendment — KNPS 선형시설 route_type을 보존."""
    route = RouteDetail(feature_id="route:knps_linear", route_type="선형시설")
    assert route.route_type == "facility_road"


# ── ADR-019: KST aware datetime ──────────────────────────────────────────


@pytest.mark.unit
def test_feature_kst_aware_default() -> None:
    """default ``kst_now()``는 KST aware."""
    f = _make_place_feature()
    assert f.created_at.tzinfo is not None
    assert f.created_at.utcoffset().total_seconds() == 9 * 3600  # type: ignore[union-attr]


@pytest.mark.unit
def test_feature_naive_datetime_rejected() -> None:
    """ADR-019 — naive datetime 입력 ValidationError."""
    with pytest.raises(Exception, match="KST"):
        _make_place_feature(created_at=datetime(2026, 5, 25, 10, 0, 0))


@pytest.mark.unit
def test_feature_utc_aware_accepted() -> None:
    """UTC aware도 timezone aware라 허용. KST 강제는 아니고 aware만 강제."""
    utc_now = datetime.now(UTC)
    f = _make_place_feature(created_at=utc_now)
    assert f.created_at == utc_now


# ── category (review report P0-3) ────────────────────────────────────────


@pytest.mark.unit
def test_feature_category_8digit_accepted() -> None:
    """8자리 숫자 category는 허용."""
    f = _make_place_feature(category="02020101")
    assert f.category == "02020101"


@pytest.mark.unit
def test_feature_category_non_8digit_rejected() -> None:
    """8자리 아닌 category는 거부 (ADR-023 + review report P0-3)."""
    for bad in (
        "",  # 빈 문자열
        "1234567",  # 7자리
        "123456789",  # 9자리
        "0202010a",  # 영문 섞임
        "PLACE_RESTAURANT",  # ALL CAPS legacy
        "02-02-01-01",  # 구분자 포함
        "  02020101",  # 공백
    ):
        with pytest.raises(ValidationError, match="8자리"):
            _make_place_feature(category=bad)


# ── marker_color ─────────────────────────────────────────────────────────


@pytest.mark.unit
def test_feature_marker_color_valid() -> None:
    """P-01 ~ P-16 허용."""
    for n in range(1, 17):
        feature = _make_place_feature(marker_color=f"P-{n:02d}")
        assert feature.marker_color == f"P-{n:02d}"


@pytest.mark.unit
def test_feature_marker_color_invalid() -> None:
    """P-17 / P-00 / 다른 형식은 거부."""
    for bad in ("P-00", "P-17", "P-1", "P-001", "Q-01", "red", ""):
        with pytest.raises(ValidationError):
            _make_place_feature(marker_color=bad)


# ── kst_now sanity ───────────────────────────────────────────────────────


@pytest.mark.unit
def test_kst_now_returns_aware() -> None:
    """``kst_now()``는 항상 KST aware."""
    now = kst_now()
    assert now.tzinfo is not None
    # UTC offset = +09:00
    offset = now.utcoffset()
    assert offset is not None
    assert offset.total_seconds() == 9 * 3600
