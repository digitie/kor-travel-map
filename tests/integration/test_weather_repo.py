"""weather_repo 적재/조회 + weather card 통합 테스트 (T-213e)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from kortravelmap.dto.weather import WeatherValue
from kortravelmap.infra import weather_repo

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


# ── #498/#499 tiered source merge + candidate-first nearest ────────────────

# 서울시청 근처. 경도 0.01° ≈ 0.9km, 위도 0.01° ≈ 1.1km (대략).
_BASE_LON = 126.9784
_BASE_LAT = 37.5665


async def _ins_feature_at(
    session: AsyncSession,
    fid: str,
    *,
    lon: float,
    lat: float,
    kind: str = "place",
) -> None:
    """좌표를 가진 feature 1건 삽입 (coord_5179 STORED generated 자동 계산)."""
    await session.execute(
        text(
            """
            INSERT INTO feature.features (
                feature_id, kind, name, category, coord, status, updated_at
            )
            VALUES (
                :fid, :kind, :fid, '06020000',
                x_extension.ST_SetSRID(
                    x_extension.ST_MakePoint(
                        CAST(:lon AS double precision),
                        CAST(:lat AS double precision)
                    ),
                    4326
                ),
                'active', now()
            )
            """
        ),
        {"fid": fid, "kind": kind, "lon": lon, "lat": lat},
    )
    await session.flush()


def _kma_short(
    fid: str, metric_key: str, **kw: object
) -> WeatherValue:
    base: dict[str, object] = {
        "feature_id": fid,
        "provider": "python-kma-api",
        "weather_domain": "kma_short_forecast",
        "forecast_style": "short",
        "timeline_bucket": "short",
        "metric_key": metric_key,
        "issued_at": _T1,
        "valid_at": _T2,
    }
    base.update(kw)
    return WeatherValue(**base)  # type: ignore[arg-type]


def _kma_mid(fid: str, metric_key: str, **kw: object) -> WeatherValue:
    base: dict[str, object] = {
        "feature_id": fid,
        "provider": "python-kma-api",
        "weather_domain": "kma_mid_forecast",
        "forecast_style": "mid",
        "timeline_bucket": "mid",
        "metric_key": metric_key,
        "issued_at": _T1,
        "valid_at": _T2,
    }
    base.update(kw)
    return WeatherValue(**base)  # type: ignore[arg-type]


def _krex_observed(fid: str, **kw: object) -> WeatherValue:
    base: dict[str, object] = {
        "feature_id": fid,
        "provider": "python-krex-api",
        "weather_domain": "rest_area_weather",
        "forecast_style": "observed",
        "timeline_bucket": "ultra_short",
        "metric_key": "T1H",
        "metric_name": "기온",
        "value_number": Decimal("18.0"),
        "unit": "deg_c",
        "observed_at": _T2,
    }
    base.update(kw)
    return WeatherValue(**base)  # type: ignore[arg-type]


async def test_weather_card_tiered_merge_observed_augments_kma_mid(
    migrated_session: AsyncSession,
) -> None:
    """#498: 농촌 feature에 KMA 중기 anchor(8km) + KREX 관측 T1H anchor(3km).

    관측이 더 가깝더라도, 카드는 KMA SKY/POP/TMN/TMX와 KREX 관측 T1H를 **둘 다**
    포함해야 한다(관측은 증강, KMA 단기/중기 기온을 그림자로 가리지 않음).
    """
    # 농촌 대상 feature — 자기 weather 없음.
    await _ins_feature_at(migrated_session, "rural", lon=_BASE_LON, lat=_BASE_LAT)

    # KREX 관측 anchor ≈ 3km 동쪽.
    await _ins_feature_at(
        migrated_session, "krex_obs", lon=_BASE_LON + 0.034, lat=_BASE_LAT
    )
    # KMA 중기/단기 anchor ≈ 8km 동쪽 (관측보다 멀다).
    await _ins_feature_at(
        migrated_session, "kma_anchor", lon=_BASE_LON + 0.090, lat=_BASE_LAT
    )

    await weather_repo.load_weather_values(
        migrated_session, [_krex_observed("krex_obs")]
    )
    await weather_repo.load_weather_values(
        migrated_session,
        [
            _kma_mid(
                "kma_anchor", "SKY", value_text="구름많음",
                metric_name="하늘상태", unit="code",
            ),
            _kma_mid(
                "kma_anchor", "POP", value_number=Decimal("30"),
                metric_name="강수확률", unit="%",
            ),
            _kma_mid(
                "kma_anchor", "TMN", value_number=Decimal("12.0"),
                metric_name="일 최저기온", unit="deg_c",
            ),
            _kma_mid(
                "kma_anchor", "TMX", value_number=Decimal("24.0"),
                metric_name="일 최고기온", unit="deg_c",
            ),
            _kma_short(
                "kma_anchor", "TMP", value_number=Decimal("21.0"),
                metric_name="기온", unit="deg_c",
            ),
        ],
    )

    card = await weather_repo.build_weather_card(
        migrated_session, feature_id="rural", freshness_seconds=10**9
    )
    by = {(m.forecast_style, m.metric_key): m for m in card.metrics}

    # KMA 중기 SKY/POP/TMN/TMX 전부 존재.
    assert by[("mid", "SKY")].value_text == "구름많음"
    assert by[("mid", "POP")].value_number == Decimal("30")
    assert by[("mid", "TMN")].value_number == Decimal("12.0")
    assert by[("mid", "TMX")].value_number == Decimal("24.0")
    # KMA 단기 기온도 존재.
    assert by[("short", "TMP")].value_number == Decimal("21.0")
    # KREX 관측 T1H가 별도 row로 증강 — 단기/중기 기온을 가리지 않음.
    assert ("observed", "T1H") in by
    assert by[("observed", "T1H")].value_number == Decimal("18.0")
    assert by[("observed", "T1H")].provider == "python-krex-api"
    # source trace.
    assert set(card.source_styles) == {"mid", "short", "observed"}


async def test_weather_card_krex_observed_only_in_radius(
    migrated_session: AsyncSession,
) -> None:
    """#498: KMA anchor가 반경 밖, KREX 관측만 반경 안 → 관측이 유일 기온 source."""
    await _ins_feature_at(migrated_session, "rural2", lon=_BASE_LON, lat=_BASE_LAT)
    # KREX 관측 ≈ 3km.
    await _ins_feature_at(
        migrated_session, "krex_only", lon=_BASE_LON + 0.034, lat=_BASE_LAT
    )
    await weather_repo.load_weather_values(
        migrated_session, [_krex_observed("krex_only")]
    )

    card = await weather_repo.build_weather_card(
        migrated_session, feature_id="rural2", freshness_seconds=10**9
    )
    by = {(m.forecast_style, m.metric_key): m for m in card.metrics}
    assert ("observed", "T1H") in by
    assert by[("observed", "T1H")].value_number == Decimal("18.0")
    # KMA 예보 기온은 없음.
    assert ("short", "TMP") not in by
    assert ("mid", "TMN") not in by


async def test_weather_card_own_rows_no_fallback(
    migrated_session: AsyncSession,
) -> None:
    """#498 regression: 자기 기온 row가 있으면 nearest 폴백을 타지 않는다."""
    await _ins_feature_at(migrated_session, "own", lon=_BASE_LON, lat=_BASE_LAT)
    # 가까운 KREX 관측 anchor가 있어도, 자기 row가 기온을 채우면 병합하지 않아야 함.
    await _ins_feature_at(
        migrated_session, "neighbor_obs", lon=_BASE_LON + 0.01, lat=_BASE_LAT
    )
    await weather_repo.load_weather_values(
        migrated_session, [_krex_observed("neighbor_obs")]
    )
    await weather_repo.load_weather_values(
        migrated_session,
        [
            _kma_short(
                "own", "TMP", value_number=Decimal("22.0"),
                metric_name="기온", unit="deg_c",
            )
        ],
    )

    card = await weather_repo.build_weather_card(
        migrated_session, feature_id="own", freshness_seconds=10**9
    )
    keys = {(m.forecast_style, m.metric_key) for m in card.metrics}
    # 자기 단기 TMP만 — neighbor 관측 T1H는 병합되지 않음.
    assert keys == {("short", "TMP")}
    assert all(m.provider == "python-kma-api" for m in card.metrics)


async def test_weather_card_far_anchor_outside_radius_no_merge(
    migrated_session: AsyncSession,
) -> None:
    """#499 behavioral parity: 반경(50km) 밖 anchor는 병합되지 않는다."""
    await _ins_feature_at(migrated_session, "isolated", lon=_BASE_LON, lat=_BASE_LAT)
    # ≈ 90km 동쪽 (반경 50km 밖).
    await _ins_feature_at(
        migrated_session, "far_kma", lon=_BASE_LON + 1.0, lat=_BASE_LAT
    )
    await weather_repo.load_weather_values(
        migrated_session,
        [
            _kma_short(
                "far_kma", "TMP", value_number=Decimal("20.0"),
                metric_name="기온", unit="deg_c",
            )
        ],
    )
    card = await weather_repo.build_weather_card(
        migrated_session, feature_id="isolated", freshness_seconds=10**9
    )
    assert card.metrics == []


def _walk_plan(plan: dict[str, object]) -> list[dict[str, object]]:
    nodes = [plan]
    for child in plan.get("Plans", []):  # type: ignore[union-attr]
        nodes.extend(_walk_plan(child))  # type: ignore[arg-type]
    return nodes


async def test_nearest_temp_uses_coord_gist_and_no_weather_full_scan(
    migrated_session: AsyncSession,
) -> None:
    """#499: nearest-anchor 쿼리가 features GiST KNN을 쓰고 weather를 full-scan 안함.

    과거 구현은 ``SELECT DISTINCT feature_id FROM feature_weather_values`` CTE로
    weather 테이블 전체를 먼저 스캔했다. 재작성 후에는 features의 coord_5179 GiST
    인덱스가 후보를 먼저 좁히고, weather는 EXISTS 상관 서브쿼리로 인덱스 접근해야
    한다 — feature_weather_values에 Seq Scan이 없어야 한다.
    """
    # GiST KNN을 planner가 고르도록 충분한 feature를 seed.
    await migrated_session.execute(
        text(
            """
            INSERT INTO feature.features (
                feature_id, kind, name, category, coord, status, updated_at
            )
            SELECT
                'wseed:' || lpad(g::text, 6, '0'),
                'place', 'seed ' || g::text, '06020000',
                x_extension.ST_SetSRID(
                    x_extension.ST_MakePoint(
                        126.90 + ((g % 200)::float * 0.002),
                        37.50 + ((g % 200)::float * 0.0015)
                    ),
                    4326
                ),
                'active', now()
            FROM generate_series(1, 3000) AS g
            """
        )
    )
    # 일부에만 기온 weather 적재.
    await migrated_session.execute(
        text(
            """
            INSERT INTO feature.feature_weather_values (
                weather_value_key, feature_id, provider, weather_domain,
                forecast_style, metric_key, value_number, unit,
                valid_at, collected_at, updated_at
            )
            SELECT
                'wv:' || lpad(g::text, 6, '0'),
                'wseed:' || lpad(g::text, 6, '0'),
                'python-kma-api', 'kma_short_forecast', 'short', 'TMP',
                20.0, 'deg_c', now(), now(), now()
            FROM generate_series(1, 3000, 7) AS g
            """
        )
    )
    await _ins_feature_at(
        migrated_session, "explain_target", lon=126.95, lat=37.55
    )
    await migrated_session.flush()
    await migrated_session.execute(text("ANALYZE feature.features"))
    await migrated_session.execute(
        text("ANALYZE feature.feature_weather_values")
    )

    await migrated_session.execute(text("SET LOCAL enable_seqscan = off"))
    plan = (
        await migrated_session.execute(
            text(
                "EXPLAIN (FORMAT JSON, COSTS OFF) "
                + weather_repo._NEAREST_KMA_FORECAST_SQL  # noqa: SLF001
            ),
            {"feature_id": "explain_target", "radius_m": 50_000.0},
        )
    ).scalar_one()[0]["Plan"]
    nodes = _walk_plan(plan)

    index_names = {
        str(n["Index Name"]) for n in nodes if n.get("Index Name") is not None
    }
    assert "idx_features_coord_5179_gist" in index_names, (
        f"expected features coord_5179 GiST KNN, used={sorted(index_names)}"
    )
    weather_seq_scans = [
        n
        for n in nodes
        if n.get("Node Type") == "Seq Scan"
        and n.get("Relation Name") == "feature_weather_values"
    ]
    assert not weather_seq_scans, (
        f"feature_weather_values must not be full-scanned: {weather_seq_scans}"
    )
