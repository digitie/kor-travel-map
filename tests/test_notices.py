from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from krtour_map.db import (
    feature_notice_details,
    features,
    initialize_feature_db,
)
from krtour_map.enums import FeatureKind
from krtour_map.models import NOTICE_TYPE_HEAVY_RAIN, NOTICE_TYPE_TRAFFIC_ACCIDENT
from krtour_map.notices import (
    KMA_WEATHER_ALERT_NOTICE_DATASET_KEY,
    KREX_TRAFFIC_NOTICE_DATASET_KEY,
    collect_kma_weather_alert_notice_features,
    collect_krex_traffic_notice_features,
    load_notice_result,
)


@dataclass(frozen=True)
class FakeNotice:
    notice_id: str
    title: str
    message: str
    lat: float
    lon: float
    source_agency: str
    valid_start_time: datetime
    severity: int | None = None


def test_collect_traffic_and_weather_notices_with_notice_type() -> None:
    traffic = collect_krex_traffic_notice_features(
        [
            FakeNotice(
                notice_id="T-1",
                title="영동선 강릉방향 사고 처리",
                message="1차로 사고 처리 중",
                lat=37.543,
                lon=128.442,
                source_agency="한국도로공사",
                valid_start_time=datetime(2026, 5, 20, 9, 0, tzinfo=ZoneInfo("Asia/Seoul")),
                severity=4,
            )
        ]
    )
    weather = collect_kma_weather_alert_notice_features(
        [
            FakeNotice(
                notice_id="W-1",
                title="서울 호우주의보",
                message="서울 전역 호우주의보 발효",
                lat=37.5665,
                lon=126.9780,
                source_agency="기상청",
                valid_start_time=datetime(2026, 5, 20, 10, 0, tzinfo=ZoneInfo("Asia/Seoul")),
            )
        ]
    )

    assert traffic.dataset_key == KREX_TRAFFIC_NOTICE_DATASET_KEY
    assert traffic.features[0].kind == FeatureKind.NOTICE
    assert traffic.notice_details[0].notice_type == NOTICE_TYPE_TRAFFIC_ACCIDENT
    assert traffic.notice_details[0].severity == 4
    assert traffic.features[0].marker_icon == "car"
    assert weather.dataset_key == KMA_WEATHER_ALERT_NOTICE_DATASET_KEY
    assert weather.notice_details[0].notice_type == NOTICE_TYPE_HEAVY_RAIN
    assert weather.features[0].marker_icon == "water"


def test_load_notice_result_upserts_updates_without_duplication() -> None:
    context = initialize_feature_db("sqlite+pysqlite:///:memory:")
    try:
        with context.session_factory() as session:
            first = collect_krex_traffic_notice_features(
                [
                    FakeNotice(
                        notice_id="T-1",
                        title="영동선 강릉방향 사고 처리",
                        message="1차로 사고 처리 중",
                        lat=37.543,
                        lon=128.442,
                        source_agency="한국도로공사",
                        valid_start_time=datetime(
                            2026,
                            5,
                            20,
                            9,
                            0,
                            tzinfo=ZoneInfo("Asia/Seoul"),
                        ),
                    )
                ]
            )
            load_notice_result(session, first)
            updated = collect_krex_traffic_notice_features(
                [
                    FakeNotice(
                        notice_id="T-1",
                        title="영동선 강릉방향 사고 처리 완료",
                        message="사고 처리 완료, 정체 해소 중",
                        lat=37.543,
                        lon=128.442,
                        source_agency="한국도로공사",
                        valid_start_time=datetime(
                            2026,
                            5,
                            20,
                            9,
                            10,
                            tzinfo=ZoneInfo("Asia/Seoul"),
                        ),
                    )
                ]
            )
            load_notice_result(session, updated)
            session.commit()

            feature_count = session.scalar(select(func.count()).select_from(features))
            notice_count = session.scalar(
                select(func.count()).select_from(feature_notice_details)
            )
            row = session.execute(select(features.c.name)).scalar_one()

        assert feature_count == 1
        assert notice_count == 1
        assert row == "영동선 강릉방향 사고 처리 완료"
    finally:
        context.dispose()
