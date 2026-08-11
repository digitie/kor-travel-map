"""``test_providers_kma_alerts`` — KMA 특보 → notice FeatureBundle (PR#46)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from kortravelmap.dto import FeatureKind, SourceRole
from kortravelmap.providers.kma import (
    KMA_ALERT_LEVEL_SEVERITY,
    KMA_WEATHER_ALERT_CATEGORY,
    KMA_WEATHER_ALERT_DATASET_KEY,
    KMA_WEATHER_ALERT_MARKER_ICON,
    is_kma_alert_lift_title,
    kma_alert_natural_key,
    kma_alert_phenomena_in_title,
    kma_alert_phenomenon,
    weather_alert_lift_closures,
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
    # 사건 단위 자연키(#632) — region × 현상 토큰. 발표 시각/번호는 키에 없다.
    assert keys == [
        "11B10101::호우",
        "11B20201::호우",
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
    # T-219c — region명이 유일한 위치 단서: Dagster 주소 검증이 원 payload를 읽는다.
    assert src.raw_data["region_name"] == "서울특별시"


@pytest.mark.unit
def test_alert_source_link_primary() -> None:
    bundles = weather_alerts_to_notice_bundles([_HEAVY_RAIN], fetched_at=_NOW)
    link = bundles[0].source_link
    assert link.source_role == SourceRole.PRIMARY
    assert link.confidence == 100


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


# ── 사건 단위 identity + 해제 라이프사이클 (#632) ─────────────────────────


def _announce(
    alert_id: str,
    title: str,
    issued_at: datetime,
    *,
    level: str | None = "주의보",
    regions: list[_Region] | None = None,
) -> _Alert:
    # 실제 dagster 경로처럼 alert_type은 title에서 뽑은 현상 토큰(정규화 가능 값).
    return _Alert(
        alert_id=alert_id,
        alert_type=kma_alert_phenomenon(title),
        level=level,
        title=title,
        description=None,
        issued_at=issued_at,
        effective_from=None,
        effective_until=None,
        source_agency="기상청",
        regions=regions if regions is not None else [_SEOUL],
    )


@pytest.mark.unit
def test_reannouncement_keeps_same_feature_id() -> None:
    """같은 특보의 재발표(tm_fc/seq 변경)는 같은 feature로 upsert된다."""
    first = _announce("108:202607030600:20", "폭염주의보 발표", _NOW)
    again = _announce("108:202607031200:23", "폭염주의보 발표", _NOW + timedelta(hours=6))
    a = weather_alerts_to_notice_bundles([first], fetched_at=_NOW)[0]
    b = weather_alerts_to_notice_bundles([again], fetched_at=_NOW)[0]
    assert a.feature.feature_id == b.feature.feature_id
    assert a.source_record.source_entity_id == b.source_record.source_entity_id
    # 발표 원문은 payload_hash가 달라 source_record 이력으로는 구분된다.
    assert a.source_record.source_record_key != b.source_record.source_record_key


@pytest.mark.unit
def test_level_escalation_keeps_same_feature_id() -> None:
    """주의보 → 경보 승격도 같은 사건 — 같은 feature로 upsert."""
    watch = _announce("108:202607030600:20", "폭염주의보 발표", _NOW, level="주의보")
    warning = _announce(
        "108:202607031200:23",
        "폭염경보 발표",
        _NOW + timedelta(hours=6),
        level="경보",
    )
    a = weather_alerts_to_notice_bundles([watch], fetched_at=_NOW)[0]
    b = weather_alerts_to_notice_bundles([warning], fetched_at=_NOW)[0]
    assert a.feature.feature_id == b.feature.feature_id


@pytest.mark.unit
def test_distinct_phenomena_stay_distinct_features() -> None:
    """풍랑/강풍은 notice_type이 둘 다 generic weather_alert지만 별개 사건이다."""
    wind = _announce("108:202607030600:20", "강풍주의보 발표", _NOW)
    waves = _announce("108:202607030600:21", "풍랑주의보 발표", _NOW)
    a = weather_alerts_to_notice_bundles([wind], fetched_at=_NOW)[0]
    b = weather_alerts_to_notice_bundles([waves], fetched_at=_NOW)[0]
    assert a.feature.feature_id != b.feature.feature_id


@pytest.mark.unit
def test_lift_title_creates_no_bundle() -> None:
    """해제 공고는 feature를 만들지 않는다."""
    lift = _announce("108:202607031800:25", "폭염주의보 해제", _NOW)
    assert weather_alerts_to_notice_bundles([lift], fetched_at=_NOW) == []


@pytest.mark.unit
def test_lift_closure_targets_announced_feature() -> None:
    """해제 closure의 feature_id는 발표 bundle의 feature_id와 일치한다."""
    announced = weather_alerts_to_notice_bundles(
        [_announce("108:202607030600:20", "폭염주의보 발표", _NOW)],
        fetched_at=_NOW,
    )[0]
    lifted_at = _NOW + timedelta(hours=12)
    closures = weather_alert_lift_closures(
        [_announce("108:202607031800:25", "폭염주의보 해제", lifted_at)]
    )
    assert len(closures) == 1
    assert closures[0].feature_id == announced.feature.feature_id
    assert closures[0].closed_at == lifted_at
    assert closures[0].phenomenon == "폭염"


@pytest.mark.unit
def test_combined_lift_title_closes_each_phenomenon() -> None:
    """결합 해제문은 현상 토큰마다 closure 1건씩 fan-out."""
    lifted_at = _NOW + timedelta(hours=12)
    closures = weather_alert_lift_closures(
        [_announce("108:202607031800:26", "풍랑주의보·호우주의보 해제", lifted_at)]
    )
    phenomena = {c.phenomenon for c in closures}
    assert phenomena == {"풍랑", "호우"}
    ids = {c.feature_id for c in closures}
    assert len(ids) == 2


@pytest.mark.unit
def test_lift_closures_dedupe_latest_per_region_phenomenon() -> None:
    """같은 region×현상의 해제가 여러 건이면 최신 issued_at 1건만 남는다."""
    older = _announce("108:202607031200:24", "폭염주의보 해제", _NOW)
    newer = _announce("108:202607031800:26", "폭염주의보 해제", _NOW + timedelta(hours=6))
    closures = weather_alert_lift_closures([older, newer])
    assert len(closures) == 1
    assert closures[0].closed_at == _NOW + timedelta(hours=6)


@pytest.mark.unit
def test_batch_dedupe_keeps_latest_announcement() -> None:
    """3일 window 재조회로 같은 사건 발표가 여러 건이면 최신 1건만 남는다."""
    first = _announce("108:202607030600:20", "폭염주의보 발표", _NOW, level="주의보")
    newer = _announce(
        "108:202607031200:23",
        "폭염경보 발표",
        _NOW + timedelta(hours=6),
        level="경보",
    )
    bundles = weather_alerts_to_notice_bundles([first, newer], fetched_at=_NOW)
    assert len(bundles) == 1
    detail = bundles[0].feature.detail
    assert detail is not None
    assert detail.severity == 2  # type: ignore[union-attr] — 경보(최신)가 남는다.


@pytest.mark.unit
def test_phenomenon_helpers() -> None:
    assert kma_alert_phenomenon("수도권 호우주의보") == "호우"
    assert kma_alert_phenomenon("특이사항 없음") == "weather_alert"
    # 토큰 tuple 순서(폭풍해일→호우→…)로 스캔 — title 등장 순서가 아니다.
    assert kma_alert_phenomena_in_title("풍랑주의보·호우주의보 해제") == ["호우", "풍랑"]
    assert kma_alert_phenomena_in_title("특이사항 없음") == ["weather_alert"]
    assert is_kma_alert_lift_title("폭염주의보 해제") is True
    assert is_kma_alert_lift_title("폭염주의보 발표") is False
    assert kma_alert_natural_key("stn:108", "폭염") == "stn:108::폭염"
