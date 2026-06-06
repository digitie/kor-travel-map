"""weather_repo 적재/조회 + weather card 통합 테스트 (T-213e)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from krtour.map.dto.weather import WeatherValue
from krtour.map.infra import weather_repo

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_KST = timezone(timedelta(hours=9))
_T1 = datetime(2026, 6, 6, 9, 0, tzinfo=_KST)
_T2 = datetime(2026, 6, 6, 12, 0, tzinfo=_KST)


async def _ins_weather_feature(session: AsyncSession, fid: str) -> None:
    await session.execute(
        text(
            """
            INSERT INTO feature.features (
                feature_id, kind, name, category, status, updated_at
            )
            VALUES (:fid, 'weather', '날씨', '00000000', 'active', now())
            """
        ),
        {"fid": fid},
    )
    await session.flush()


def _wv(metric_key: str, **kw: object) -> WeatherValue:
    base: dict[str, object] = {
        "feature_id": "f_w",
        "provider": "python-kma-api",
        "weather_domain": "kma_short_forecast",
        "forecast_style": "short",
        "timeline_bucket": "short",
        "metric_key": metric_key,
    }
    base.update(kw)
    return WeatherValue(**base)  # type: ignore[arg-type]


async def test_weather_load_card_asof_freshness(migrated_session: AsyncSession) -> None:
    await _ins_weather_feature(migrated_session, "f_w")
    values = [
        _wv("TMP", metric_name="기온", value_number=Decimal("20.0"), unit="deg_c",
            issued_at=_T1, valid_at=_T1),
        # 같은 (short, TMP) 더 최신 valid_at → card 최신값.
        _wv("TMP", metric_name="기온", value_number=Decimal("25.0"), unit="deg_c",
            issued_at=_T1, valid_at=_T2),
        _wv("FIRE_RISK", weather_domain="kma_weather_alert", forecast_style="advisory",
            timeline_bucket=None, value_text="주의보", severity="주의보",
            issued_at=_T2, valid_at=_T2),
    ]
    assert await weather_repo.load_weather_values(migrated_session, values) == 3

    card = await weather_repo.build_weather_card(
        migrated_session, feature_id="f_w", freshness_seconds=10**9
    )
    by = {(m.forecast_style, m.metric_key): m for m in card.metrics}
    assert by[("short", "TMP")].value_number == Decimal("25.0")  # 최신
    assert by[("advisory", "FIRE_RISK")].value_text == "주의보"
    assert set(card.source_styles) == {"short", "advisory"}
    assert card.is_stale is False  # freshness 무한대

    # 멱등 재적재 — 중복 없음.
    assert await weather_repo.load_weather_values(migrated_session, values) == 3
    card2 = await weather_repo.build_weather_card(
        migrated_session, feature_id="f_w", freshness_seconds=10**9
    )
    assert len({(m.forecast_style, m.metric_key) for m in card2.metrics}) == 2

    # asof: 10:00 이하만 → short TMP=20.0(T1), advisory(T2) 제외.
    asof = datetime(2026, 6, 6, 10, 0, tzinfo=_KST)
    card3 = await weather_repo.build_weather_card(
        migrated_session, feature_id="f_w", asof=asof, freshness_seconds=10**9
    )
    by3 = {(m.forecast_style, m.metric_key): m for m in card3.metrics}
    assert by3[("short", "TMP")].value_number == Decimal("20.0")
    assert ("advisory", "FIRE_RISK") not in by3

    # freshness: 작은 threshold + 과거 데이터 → stale.
    card4 = await weather_repo.build_weather_card(
        migrated_session, feature_id="f_w", freshness_seconds=1
    )
    assert card4.is_stale is True


async def test_weather_card_empty(migrated_session: AsyncSession) -> None:
    card = await weather_repo.build_weather_card(
        migrated_session, feature_id="f_none"
    )
    assert card.metrics == []
    assert card.source_styles == []
    assert card.latest_at is None
    assert card.is_stale is True
