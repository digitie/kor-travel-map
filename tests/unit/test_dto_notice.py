"""``NoticeDetail`` + NOTICE_TYPES + ``normalize_notice_type`` (ADR-027)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from kortravelmap.dto import (
    NOTICE_TYPE_ACCESS_RESTRICTION,
    NOTICE_TYPE_FIRE_ALERT,
    NOTICE_TYPE_HEAVY_RAIN,
    NOTICE_TYPE_HEAVY_SNOW,
    NOTICE_TYPE_ROAD_CLOSURE,
    NOTICE_TYPE_WEATHER_ALERT,
    NOTICE_TYPES,
    NoticeDetail,
    normalize_notice_type,
)


@pytest.mark.unit
def test_notice_types_count() -> None:
    """ADR-027 적용 후 NOTICE_TYPES 14건."""
    assert len(NOTICE_TYPES) == 14
    assert NOTICE_TYPE_ACCESS_RESTRICTION in NOTICE_TYPES
    assert NOTICE_TYPE_FIRE_ALERT in NOTICE_TYPES


@pytest.mark.unit
def test_normalize_notice_type_canonical() -> None:
    """이미 canonical이면 그대로 반환."""
    assert normalize_notice_type("traffic") == "traffic"
    assert normalize_notice_type("access_restriction") == "access_restriction"
    assert normalize_notice_type("fire_alert") == "fire_alert"


@pytest.mark.unit
def test_normalize_notice_type_korean_aliases() -> None:
    """한국어 alias 정규화."""
    assert normalize_notice_type("호우경보") == NOTICE_TYPE_HEAVY_RAIN
    assert normalize_notice_type("호우주의보") == NOTICE_TYPE_HEAVY_RAIN
    assert normalize_notice_type("도로통제") == NOTICE_TYPE_ROAD_CLOSURE
    # ADR-027 generic aliases
    assert normalize_notice_type("입산통제") == NOTICE_TYPE_ACCESS_RESTRICTION
    assert normalize_notice_type("해수욕장폐장") == NOTICE_TYPE_ACCESS_RESTRICTION
    assert normalize_notice_type("산불경보") == NOTICE_TYPE_FIRE_ALERT
    assert normalize_notice_type("화재경보") == NOTICE_TYPE_FIRE_ALERT


@pytest.mark.unit
def test_normalize_notice_type_kma_weather_alerts() -> None:
    """KMA 기상특보 13종 — base type 매핑 (실데이터 라이브 검증으로 보강)."""
    # 전용 canonical 보유 종류
    assert normalize_notice_type("호우") == NOTICE_TYPE_HEAVY_RAIN
    assert normalize_notice_type("대설") == NOTICE_TYPE_HEAVY_SNOW
    assert normalize_notice_type("대설경보") == NOTICE_TYPE_HEAVY_SNOW
    # 전용 canonical 없는 종류 → generic weather_alert
    for kind in ("강풍", "풍랑", "태풍", "건조", "한파", "폭풍해일", "황사"):
        assert normalize_notice_type(kind) == NOTICE_TYPE_WEATHER_ALERT, kind
    assert normalize_notice_type("weather_alert") == NOTICE_TYPE_WEATHER_ALERT


@pytest.mark.unit
def test_normalize_notice_type_english_aliases() -> None:
    """영어 alias 정규화."""
    assert normalize_notice_type("heavy_rain") == NOTICE_TYPE_HEAVY_RAIN
    assert normalize_notice_type("forest_access") == NOTICE_TYPE_ACCESS_RESTRICTION
    assert normalize_notice_type("forest_fire") == NOTICE_TYPE_FIRE_ALERT


@pytest.mark.unit
def test_normalize_notice_type_unknown_raises() -> None:
    """모르는 값은 ValueError."""
    with pytest.raises(ValueError, match="unknown notice_type"):
        normalize_notice_type("unknown_xyz")


@pytest.mark.unit
def test_notice_detail_basic() -> None:
    """NoticeDetail 정상 생성."""
    detail = NoticeDetail(
        feature_id="notice:abc",
        notice_type="fire_alert",
        severity=3,
        payload={"domain": "forest"},
    )
    assert detail.notice_type == "fire_alert"
    assert detail.severity == 3
    assert detail.payload["domain"] == "forest"


@pytest.mark.unit
def test_notice_detail_normalizes_alias_input() -> None:
    """alias 입력은 자동 normalize."""
    detail = NoticeDetail(
        feature_id="notice:abc",
        notice_type="입산통제",
        payload={"domain": "forest"},
    )
    assert detail.notice_type == "access_restriction"


@pytest.mark.unit
def test_notice_detail_severity_bounds() -> None:
    """severity는 0~5."""
    with pytest.raises(ValidationError):
        NoticeDetail(feature_id="x", notice_type="safety", severity=10)
    with pytest.raises(ValidationError):
        NoticeDetail(feature_id="x", notice_type="safety", severity=-1)


@pytest.mark.unit
def test_notice_detail_unknown_type_raises() -> None:
    """모르는 notice_type은 ValueError (Pydantic ValidationError로 wrap)."""
    with pytest.raises(ValidationError):  # wrapping ValueError
        NoticeDetail(feature_id="x", notice_type="totally_unknown")


# ── ADR-019 datetime aware (review report P0-2) ─────────────────────────


@pytest.mark.unit
def test_notice_detail_naive_valid_start_time_rejected() -> None:
    """``valid_start_time``에 naive datetime은 ValidationError (ADR-019)."""
    from datetime import datetime

    with pytest.raises(ValidationError, match="timezone-aware"):
        NoticeDetail(
            feature_id="x",
            notice_type="safety",
            valid_start_time=datetime(2026, 1, 1),  # naive
        )


@pytest.mark.unit
def test_notice_detail_naive_valid_end_time_rejected() -> None:
    """``valid_end_time``에 naive datetime은 ValidationError (ADR-019)."""
    from datetime import datetime

    with pytest.raises(ValidationError, match="timezone-aware"):
        NoticeDetail(
            feature_id="x",
            notice_type="safety",
            valid_end_time=datetime(2026, 1, 1),  # naive
        )


@pytest.mark.unit
def test_notice_detail_aware_datetime_accepted() -> None:
    """KST/UTC aware datetime 모두 허용 (변환은 호출자 책임)."""
    from datetime import UTC, datetime
    from zoneinfo import ZoneInfo

    kst = ZoneInfo("Asia/Seoul")
    detail = NoticeDetail(
        feature_id="x",
        notice_type="safety",
        valid_start_time=datetime(2026, 1, 1, tzinfo=kst),
        valid_end_time=datetime(2026, 1, 2, tzinfo=UTC),
    )
    assert detail.valid_start_time is not None
    assert detail.valid_end_time is not None
