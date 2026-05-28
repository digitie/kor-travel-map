"""``test_providers_kma_alerts`` — KMA 특보 → notice FeatureBundle (PR#46)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from krtour.map.dto import FeatureKind, SourceRole
from krtour.map.providers.kma import (
    KMA_ALERT_LEVEL_SEVERITY,
    KMA_WEATHER_ALERT_CATEGORY,
    KMA_WEATHER_ALERT_DATASET_KEY,
    KMA_WEATHER_ALERT_MARKER_ICON,
    weather_alerts_to_notice_bundles,
)

KST = timezone(timedelta(hours=9))
_NOW = datetime(2026, 5, 28, 6, 0, tzinfo=KST)


@dataclass(frozen=True)
class _Region:
    region_code: str
    region_name: str


@dataclass(frozen=True)
class _Alert:
    alert_id: str
    alert_type: str
    level: str | None
    title: str
    description: str | None
    issued_at: datetime
    effective_from: datetime | None
    effective_until: datetime | None
    source_agency: str | None
    regions: list[_Region]


_SEOUL = _Region(region_code="11B10101", region_name="서울특별시")
_GYEONGGI = _Region(region_code="11B20201", region_name="경기도")


_HEAVY_RAIN = _Alert(
    alert_id="ALERT-2026-05-28-001",
    alert_type="호우주의보",  # alias → 'heavy_rain_warning'
    level="주의보",  # KMA_ALERT_LEVEL_SEVERITY → 1
    title="수도권 호우주의보",
    description="2026-05-28 09:00부터 호우 예상.",
    issued_at=_NOW,
    effective_from=_NOW + timedelta(hours=3),
    effective_until=_NOW + timedelta(hours=12),
    source_agency="기상청",
    regions=[_SEOUL, _GYEONGGI],
)

_HEATWAVE = _Alert(
    alert_id="ALERT-2026-07-15-002",
    alert_type="폭염",
    level="경보",
    title="전국 폭염경보",
    description=None,
    issued_at=_NOW,
    effective_from=None,
    effective_until=None,
    source_agency="기상청",
    regions=[_SEOUL],
)


# ── happy path ────────────────────────────────────────────────────────


@pytest.mark.unit
def test_one_alert_two_regions_yields_two_bundles() -> None:
    bundles = weather_alerts_to_notice_bundles([_HEAVY_RAIN], fetched_at=_NOW)
    assert len(bundles) == 2
    keys = [b.source_record.source_entity_id for b in bundles]
    assert keys == [
        "ALERT-2026-05-28-001::11B10101",
        "ALERT-2026-05-28-001::11B20201",
    ]


@pytest.mark.unit
def test_alert_type_alias_normalized() -> None:
    """'호우주의보' → 'heavy_rain_warning' (NoticeDetail validator)."""
    bundles = weather_alerts_to_notice_bundles([_HEAVY_RAIN], fetched_at=_NOW)
    for bundle in bundles:
        detail = bundle.feature.detail
        assert detail is not None
        assert detail.notice_type == "heavy_rain_warning"  # type: ignore[union-attr]


@pytest.mark.unit
def test_alert_severity_from_level_map() -> None:
    bundles = weather_alerts_to_notice_bundles([_HEAVY_RAIN], fetched_at=_NOW)
    detail = bundles[0].feature.detail
    assert detail is not None
    assert detail.severity == KMA_ALERT_LEVEL_SEVERITY["주의보"]  # type: ignore[union-attr]
    assert detail.severity == 1  # type: ignore[union-attr]


@pytest.mark.unit
def test_alert_warning_level_severity_2() -> None:
    bundles = weather_alerts_to_notice_bundles([_HEATWAVE], fetched_at=_NOW)
    detail = bundles[0].feature.detail
    assert detail is not None
    assert detail.severity == 2  # type: ignore[union-attr]


@pytest.mark.unit
def test_alert_feature_kind_notice_and_category() -> None:
    bundles = weather_alerts_to_notice_bundles([_HEAVY_RAIN], fetched_at=_NOW)
    f = bundles[0].feature
    assert f.kind == FeatureKind.NOTICE
    assert f.category == KMA_WEATHER_ALERT_CATEGORY  # "99000000" placeholder
    assert f.marker_icon == KMA_WEATHER_ALERT_MARKER_ICON  # "danger"
    assert f.coord is None  # 특보는 region 단위 — 점 좌표 없음


@pytest.mark.unit
def test_alert_valid_start_uses_effective_from_when_present() -> None:
    bundles = weather_alerts_to_notice_bundles([_HEAVY_RAIN], fetched_at=_NOW)
    detail = bundles[0].feature.detail
    assert detail is not None
    assert detail.valid_start_time == _NOW + timedelta(hours=3)  # type: ignore[union-attr]
    assert detail.valid_end_time == _NOW + timedelta(hours=12)  # type: ignore[union-attr]


@pytest.mark.unit
def test_alert_valid_start_falls_back_to_issued_at() -> None:
    """effective_from=None이면 valid_start=issued_at."""
    bundles = weather_alerts_to_notice_bundles([_HEATWAVE], fetched_at=_NOW)
    detail = bundles[0].feature.detail
    assert detail is not None
    assert detail.valid_start_time == _NOW  # type: ignore[union-attr]
    assert detail.valid_end_time is None  # type: ignore[union-attr]


@pytest.mark.unit
def test_alert_payload_includes_region_domain_level() -> None:
    bundles = weather_alerts_to_notice_bundles([_HEAVY_RAIN], fetched_at=_NOW)
    detail = bundles[0].feature.detail
    assert detail is not None
    payload = detail.payload  # type: ignore[union-attr]
    assert payload["domain"] == "weather"
    assert payload["region_code"] == "11B10101"
    assert payload["region_name"] == "서울특별시"
    assert payload["level"] == "주의보"
    assert payload["kma_alert_id"] == "ALERT-2026-05-28-001"


@pytest.mark.unit
def test_alert_source_record_metadata() -> None:
    bundles = weather_alerts_to_notice_bundles([_HEAVY_RAIN], fetched_at=_NOW)
    src = bundles[0].source_record
    assert src.provider == "python-kma-api"
    assert src.dataset_key == KMA_WEATHER_ALERT_DATASET_KEY
    assert src.source_entity_type == "weather_alert"
    assert src.fetched_at == _NOW


@pytest.mark.unit
def test_alert_source_link_primary() -> None:
    bundles = weather_alerts_to_notice_bundles([_HEAVY_RAIN], fetched_at=_NOW)
    link = bundles[0].source_link
    assert link.source_role == SourceRole.PRIMARY
    assert link.confidence == 100
    assert link.is_primary_source is True


@pytest.mark.unit
def test_alert_two_regions_yield_distinct_feature_ids() -> None:
    """같은 alert이라도 region이 다르면 feature_id 다름."""
    bundles = weather_alerts_to_notice_bundles([_HEAVY_RAIN], fetched_at=_NOW)
    ids = {b.feature.feature_id for b in bundles}
    assert len(ids) == 2  # 2 region → 2 distinct feature_id


@pytest.mark.unit
def test_alert_determinism() -> None:
    """같은 input은 같은 feature_id / source_record_key."""
    a = weather_alerts_to_notice_bundles([_HEAVY_RAIN], fetched_at=_NOW)[0]
    b = weather_alerts_to_notice_bundles([_HEAVY_RAIN], fetched_at=_NOW)[0]
    assert a.feature.feature_id == b.feature.feature_id
    assert a.source_record.source_record_key == b.source_record.source_record_key


@pytest.mark.unit
def test_empty_iterable() -> None:
    assert weather_alerts_to_notice_bundles([], fetched_at=_NOW) == []


@pytest.mark.unit
def test_alert_no_regions_skipped() -> None:
    """regions가 빈 list면 결과도 빈 list."""
    bare = _Alert(
        alert_id="ALERT-EMPTY",
        alert_type="weather_alert",
        level=None,
        title="(no regions)",
        description=None,
        issued_at=_NOW,
        effective_from=None,
        effective_until=None,
        source_agency=None,
        regions=[],
    )
    assert weather_alerts_to_notice_bundles([bare], fetched_at=_NOW) == []
