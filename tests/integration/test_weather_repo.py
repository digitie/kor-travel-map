"""weather_repo 적재/조회 + weather card 통합 테스트 (T-213e)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import event, text

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
        _wv(
            "TMP",
            metric_name="기온",
            value_number=Decimal("20.0"),
            unit="deg_c",
            issued_at=_T1,
            valid_at=_T1,
        ),
        # 같은 (short, TMP) 더 최신 valid_at → card 최신값.
        _wv(
            "TMP",
            metric_name="기온",
            value_number=Decimal("25.0"),
            unit="deg_c",
            issued_at=_T1,
            valid_at=_T2,
        ),
        _wv(
            "FIRE_RISK",
            weather_domain="kma_weather_alert",
            forecast_style="advisory",
            timeline_bucket=None,
            value_text="주의보",
            severity="주의보",
            issued_at=_T2,
            valid_at=_T2,
        ),
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
    card = await weather_repo.build_weather_card(migrated_session, feature_id="f_none")
    assert card.metrics == []
    assert card.source_styles == []
    assert card.latest_at is None
    assert card.is_stale is True


async def test_weather_batch_is_one_snapshot_and_separates_parent_states(
    migrated_session: AsyncSession,
) -> None:
    target_at = _T2
    earlier_target_at = _T2 - timedelta(hours=1)
    known_at = _T2 + timedelta(hours=1)
    await _ins_feature_at(
        migrated_session,
        "batch_weather",
        lon=_BASE_LON,
        lat=_BASE_LAT,
        kind="weather",
    )
    await _ins_feature_at(
        migrated_session,
        "batch_weather_peer",
        lon=_BASE_LON + 0.001,
        lat=_BASE_LAT,
    )
    await _ins_weather_feature(migrated_session, "batch_no_data")
    await _ins_weather_feature(migrated_session, "batch_retired")
    await migrated_session.execute(
        text(
            """
            UPDATE feature.features
            SET status = 'deleted', deleted_at = :deleted_at
            WHERE feature_id = 'batch_retired'
            """
        ),
        {"deleted_at": known_at},
    )
    await weather_repo.load_weather_values(
        migrated_session,
        [
            _kma_short(
                "batch_weather",
                "TMP",
                issued_at=_T1,
                valid_at=_T1,
                collected_at=_T1 + timedelta(minutes=20),
                value_number=Decimal("20.0"),
                unit="deg_c",
            ),
            _kma_short(
                "batch_weather",
                "TMP",
                issued_at=_T2,
                valid_at=_T2 + timedelta(days=1),
                collected_at=_T2 + timedelta(minutes=20),
                value_number=Decimal("23.0"),
                unit="deg_c",
            ),
            # known_at 뒤 수집된 미래 row는 snapshot에 보이지 않는다.
            _kma_short(
                "batch_weather",
                "TMP",
                issued_at=_T2,
                valid_at=_T2 + timedelta(days=2),
                collected_at=known_at + timedelta(seconds=1),
                value_number=Decimal("99.0"),
                unit="deg_c",
            ),
            # 발행시각이 없는 forecast는 known-at 계약을 만족하지 않는다.
            _kma_short(
                "batch_weather",
                "POP",
                issued_at=None,
                valid_at=_T2 + timedelta(hours=6),
                collected_at=_T1,
                value_number=Decimal("88.0"),
                unit="%",
            ),
            # 구간형 weather는 valid_from을 effective_at으로 보존한다.
            _wv(
                "RANGE_CURRENT",
                feature_id="batch_weather",
                weather_domain="kma_weather_alert",
                forecast_style="advisory",
                timeline_bucket=None,
                issued_at=None,
                valid_from=_T2 - timedelta(minutes=30),
                valid_until=_T2 + timedelta(minutes=30),
                collected_at=_T1,
                value_text="현재 구간",
            ),
            _wv(
                "RANGE_EXPIRED",
                feature_id="batch_weather",
                weather_domain="kma_weather_alert",
                forecast_style="advisory",
                timeline_bucket=None,
                issued_at=None,
                valid_from=_T1 - timedelta(hours=2),
                valid_until=_T1 - timedelta(hours=1),
                collected_at=_T1 - timedelta(hours=3),
                value_text="종료 구간",
            ),
            _wv(
                "RANGE_TIMELINE",
                feature_id="batch_weather",
                weather_domain="kma_weather_alert",
                forecast_style="advisory",
                timeline_bucket=None,
                issued_at=None,
                valid_from=_T2 + timedelta(hours=12),
                valid_until=_T2 + timedelta(hours=18),
                collected_at=_T1,
                value_text="예정 구간",
            ),
        ],
    )
    await migrated_session.flush()
    series_count = (
        await migrated_session.execute(
            text(
                """
                SELECT count(*)
                FROM feature.weather_metric_series
                WHERE feature_id = 'batch_weather'
                """
            )
        )
    ).scalar_one()
    assert series_count == 5

    connection = await migrated_session.connection()
    statement_count = 0

    def _count_statement(
        *_args: object,
    ) -> None:
        nonlocal statement_count
        statement_count += 1

    event.listen(connection.sync_connection, "before_cursor_execute", _count_statement)
    try:
        snapshots = await weather_repo.get_weather_batch_snapshots(
            migrated_session,
            targets=(
                weather_repo.WeatherBatchTarget(
                    target_at=earlier_target_at,
                    feature_ids=("batch_weather",),
                ),
                weather_repo.WeatherBatchTarget(
                    target_at=target_at,
                    feature_ids=(
                        "batch_weather",
                        "batch_weather_peer",
                        "batch_no_data",
                        "batch_retired",
                    ),
                ),
            ),
            known_at=known_at,
            freshness_seconds=10**9,
        )
    finally:
        event.remove(
            connection.sync_connection,
            "before_cursor_execute",
            _count_statement,
        )

    assert statement_count == 1
    assert [snapshot.target_at for snapshot in snapshots] == [
        earlier_target_at,
        target_at,
    ]
    earlier_item = snapshots[0].items[0]
    earlier_card = snapshots[0].cards[0]
    assert earlier_item.feature_id == "batch_weather"
    assert earlier_item.card_key == earlier_card.card_key
    assert "RANGE_CURRENT" not in {metric.metric_key for metric in earlier_card.current}
    assert "RANGE_CURRENT" in {metric.metric_key for metric in earlier_card.timeline}
    items = snapshots[1].items
    assert [item.state for item in items] == ["found", "found", "no_data", "retired"]
    assert items[0].card_key == items[1].card_key
    assert len(snapshots[1].cards) == 1
    card = snapshots[1].cards[0]
    assert card.card_key == items[0].card_key
    current_by_key = {metric.metric_key: metric for metric in card.current}
    timeline_by_key = {metric.metric_key: metric for metric in card.timeline}
    assert current_by_key["TMP"].value_number == Decimal("20.0")
    assert current_by_key["RANGE_CURRENT"].effective_at == _T2 - timedelta(minutes=30)
    assert "RANGE_EXPIRED" not in current_by_key
    assert timeline_by_key["TMP"].value_number == Decimal("23.0")
    assert "POP" not in timeline_by_key
    assert timeline_by_key["RANGE_TIMELINE"].effective_at == _T2 + timedelta(hours=12)
    assert timeline_by_key["RANGE_TIMELINE"].valid_until == _T2 + timedelta(hours=18)
    assert card.latest_at == _T2 - timedelta(minutes=30)
    assert items[2].card_key is None
    assert items[3].card_key is None


async def test_weather_batch_metric_budget_fails_without_partial_snapshot(
    migrated_session: AsyncSession,
) -> None:
    await _ins_feature_at(
        migrated_session,
        "batch_budget",
        lon=_BASE_LON,
        lat=_BASE_LAT,
        kind="weather",
    )
    await weather_repo.load_weather_values(
        migrated_session,
        [
            _kma_short(
                "batch_budget",
                "TMP",
                issued_at=_T1,
                valid_at=_T1,
                collected_at=_T1,
                value_number=Decimal("20.0"),
                unit="deg_c",
            ),
            _kma_short(
                "batch_budget",
                "POP",
                issued_at=_T1,
                valid_at=_T2,
                collected_at=_T1,
                value_number=Decimal("40.0"),
                unit="%",
            ),
        ],
    )
    await migrated_session.flush()

    with pytest.raises(
        weather_repo.WeatherBatchMetricLimitExceededError,
        match="metric rows 2 exceed limit 1",
    ):
        await weather_repo.get_weather_batch_snapshots(
            migrated_session,
            targets=(
                weather_repo.WeatherBatchTarget(
                    target_at=_T2,
                    feature_ids=("batch_budget",),
                ),
            ),
            known_at=_T2,
            metric_row_limit=1,
        )


async def test_weather_batch_payload_budget_fails_without_partial_snapshot(
    migrated_session: AsyncSession,
) -> None:
    await _ins_feature_at(
        migrated_session,
        "batch_payload_budget",
        lon=_BASE_LON,
        lat=_BASE_LAT,
        kind="weather",
    )
    await weather_repo.load_weather_values(
        migrated_session,
        [
            _wv(
                "LONG_TEXT",
                feature_id="batch_payload_budget",
                weather_domain="kma_weather_alert",
                forecast_style="advisory",
                timeline_bucket=None,
                issued_at=_T1,
                valid_at=_T2,
                collected_at=_T1,
                value_text="ok",
            )
        ],
    )
    await migrated_session.flush()

    short_snapshot = await weather_repo.get_weather_batch_snapshots(
        migrated_session,
        targets=(
            weather_repo.WeatherBatchTarget(
                target_at=_T2,
                feature_ids=("batch_payload_budget",),
            ),
        ),
        known_at=_T2,
        response_byte_limit=6000,
    )
    assert short_snapshot[0].items[0].state == "found"

    await weather_repo.load_weather_values(
        migrated_session,
        [
            _wv(
                "LONG_TEXT",
                feature_id="batch_payload_budget",
                weather_domain="kma_weather_alert",
                forecast_style="advisory",
                timeline_bucket=None,
                issued_at=_T1,
                valid_at=_T2,
                collected_at=_T1 + timedelta(seconds=1),
                value_text="x" * 5000,
            )
        ],
    )
    await migrated_session.flush()

    with pytest.raises(
        weather_repo.WeatherBatchPayloadLimitExceededError,
        match=r"response bytes \d+ exceed limit 6000",
    ):
        await weather_repo.get_weather_batch_snapshots(
            migrated_session,
            targets=(
                weather_repo.WeatherBatchTarget(
                    target_at=_T2,
                    feature_ids=("batch_payload_budget",),
                ),
            ),
            known_at=_T2,
            response_byte_limit=6000,
        )


async def test_weather_batch_series_work_budget_stops_before_fact_projection(
    migrated_session: AsyncSession,
) -> None:
    await _ins_feature_at(
        migrated_session,
        "batch_series_budget",
        lon=_BASE_LON,
        lat=_BASE_LAT,
        kind="weather",
    )
    await weather_repo.load_weather_values(
        migrated_session,
        [
            _kma_short(
                "batch_series_budget",
                metric_key,
                issued_at=_T1,
                valid_at=_T2 + timedelta(hours=hour),
                collected_at=_T1,
                value_number=Decimal("20.0"),
                unit="deg_c",
            )
            for metric_key in ("TMP", "POP")
            for hour in range(25)
        ],
    )
    await migrated_session.flush()

    with pytest.raises(
        weather_repo.WeatherBatchWorkLimitExceededError,
        match="series work 2 exceeds limit 1",
    ):
        await weather_repo.get_weather_batch_snapshots(
            migrated_session,
            targets=(
                weather_repo.WeatherBatchTarget(
                    target_at=_T2,
                    feature_ids=("batch_series_budget",),
                ),
            ),
            known_at=_T2,
            series_work_limit=1,
        )

    plan = (
        await migrated_session.execute(
            text(
                "EXPLAIN (ANALYZE, FORMAT JSON, COSTS OFF, TIMING OFF) "
                + weather_repo._WEATHER_BATCH_SQL  # noqa: SLF001
            ),
            {
                "feature_ids": ["batch_series_budget"],
                "target_ats": [_T2],
                "known_at": _T2,
                "radius_m": 50_000.0,
                "timeline_days": 1,
                "metric_row_limit": weather_repo.WEATHER_BATCH_MAX_METRIC_ROWS,
                "response_byte_limit": weather_repo.WEATHER_BATCH_MAX_RESPONSE_BYTES,
                "series_work_limit": 1,
            },
        )
    ).scalar_one()[0]["Plan"]
    fact_rows_read = sum(
        float(node.get("Actual Rows", 0)) * float(node.get("Actual Loops", 0))
        for node in _walk_plan(plan)
        if node.get("Relation Name") == "feature_weather_values"
    )
    assert fact_rows_read < 25, (
        "series-work gate must stop the 50-row timeline projection; "
        f"fact rows read={fact_rows_read:g}"
    )


async def test_weather_batch_future_own_series_does_not_change_past_anchor(
    migrated_session: AsyncSession,
) -> None:
    target_at = _T2
    known_at = _T2 + timedelta(hours=1)
    await _ins_feature_at(
        migrated_session,
        "batch_bitemporal_parent",
        lon=_BASE_LON,
        lat=_BASE_LAT,
    )
    await _ins_feature_at(
        migrated_session,
        "batch_bitemporal_anchor",
        lon=_BASE_LON + 0.001,
        lat=_BASE_LAT,
        kind="weather",
    )
    await weather_repo.load_weather_values(
        migrated_session,
        [
            _kma_short(
                "batch_bitemporal_anchor",
                "TMP",
                issued_at=_T1,
                valid_at=target_at,
                collected_at=_T1,
                value_number=Decimal("18.0"),
                unit="deg_c",
            )
        ],
    )
    await migrated_session.flush()

    async def _temperature() -> Decimal | None:
        snapshots = await weather_repo.get_weather_batch_snapshots(
            migrated_session,
            targets=(
                weather_repo.WeatherBatchTarget(
                    target_at=target_at,
                    feature_ids=("batch_bitemporal_parent",),
                ),
            ),
            known_at=known_at,
            series_work_limit=1,
        )
        assert snapshots[0].items[0].state == "found"
        return snapshots[0].cards[0].current[0].value_number

    assert await _temperature() == Decimal("18.0000")

    # Catalog는 monotonic이라 이 미래 own series identity 자체는 즉시 등록된다.
    # 그러나 fact가 known_at 뒤라 같은 과거 snapshot의 source 선택을 바꾸면 안 된다.
    await weather_repo.load_weather_values(
        migrated_session,
        [
            _kma_short(
                "batch_bitemporal_parent",
                "TMP",
                issued_at=_T1,
                valid_at=target_at,
                collected_at=known_at + timedelta(hours=1),
                value_number=Decimal("99.0"),
                unit="deg_c",
            )
        ],
    )
    await migrated_session.flush()
    assert await _temperature() == Decimal("18.0000")


async def test_weather_timeline_preserves_forecast_issue_history(
    migrated_session: AsyncSession,
) -> None:
    await _ins_feature_at(
        migrated_session,
        "kma_anchor",
        lon=_BASE_LON,
        lat=_BASE_LAT,
        kind="weather",
    )
    previous_issue = _T1 - timedelta(hours=3)
    await weather_repo.load_weather_values(
        migrated_session,
        [
            _kma_short(
                "kma_anchor",
                "TMP",
                issued_at=previous_issue,
                valid_at=_T2,
                value_number=Decimal("22.0"),
                unit="deg_c",
            ),
            _kma_short(
                "kma_anchor",
                "TMP",
                issued_at=_T1,
                valid_at=_T2,
                value_number=Decimal("24.0"),
                unit="deg_c",
            ),
        ],
    )

    anchor = await weather_repo.nearest_weather_feature_for_coordinate(
        migrated_session,
        lon=_BASE_LON + 0.001,
        lat=_BASE_LAT,
    )
    assert anchor is not None
    assert anchor.feature_id == "kma_anchor"

    rows = await weather_repo.list_weather_values(
        migrated_session,
        feature_id=anchor.feature_id,
        metric_keys=["TMP"],
        valid_from=_T2,
        valid_to=_T2,
        history_from=previous_issue - timedelta(days=1),
    )
    by_issue = {row.issued_at: row for row in rows}
    assert by_issue[previous_issue].value_number == Decimal("22.0000")
    assert by_issue[_T1].value_number == Decimal("24.0000")


async def test_kma_weather_alert_history_reads_source_records(
    migrated_session: AsyncSession,
) -> None:
    raw_data = {
        "alert_id": "A-1",
        "alert_type": "heavy_rain_warning",
        "phenomenon": "호우",
        "level": "주의보",
        "title": "호우주의보",
        "description": "강한 비",
        "issued_at": _T1.isoformat(),
        "effective_from": _T1.isoformat(),
        "effective_until": None,
        "source_agency": "기상청",
        "region_code": "11B10101",
        "region_name": "서울특별시",
    }
    await migrated_session.execute(
        text(
            """
            INSERT INTO feature.features (
                feature_id, kind, name, category, status, detail, updated_at
            )
            VALUES (
                'f_notice_weather', 'notice', '호우주의보', '99000000',
                'active', '{}'::jsonb, now()
            )
            """
        )
    )
    await migrated_session.execute(
        text(
            """
            INSERT INTO provider_sync.source_entities (
                source_entity_key, provider, dataset_key, source_entity_type,
                source_entity_id, first_seen_at, last_seen_at
            )
            VALUES (
                'se_kma_alert_1', 'python-kma-api', 'kma_weather_alerts',
                'weather_alert', '11B10101::호우', :fetched_at, :fetched_at
            )
            """
        ),
        {"fetched_at": _T1},
    )
    await migrated_session.execute(
        text(
            """
            INSERT INTO provider_sync.source_records (
                source_record_key, source_entity_key,
                provider, dataset_key, source_entity_type,
                source_entity_id, raw_name, raw_address, raw_data,
                raw_payload_hash, fetched_at
            )
            VALUES (
                'sr_kma_alert_1', 'se_kma_alert_1',
                'python-kma-api', 'kma_weather_alerts',
                'weather_alert', '11B10101::호우', '호우주의보', '서울특별시',
                CAST(:raw_data AS jsonb), 'hash-alert-1', :fetched_at
            )
            """
        ),
        {"raw_data": json.dumps(raw_data), "fetched_at": _T1},
    )
    await migrated_session.execute(
        text(
            """
            UPDATE provider_sync.source_entities
            SET current_source_record_key = 'sr_kma_alert_1'
            WHERE source_entity_key = 'se_kma_alert_1'
            """
        )
    )
    await migrated_session.execute(
        text(
            """
            INSERT INTO provider_sync.source_links (
                feature_id, source_entity_key, source_role, match_method,
                confidence, is_primary_source
            )
            VALUES (
                'f_notice_weather', 'se_kma_alert_1', 'primary',
                'natural_key', 100, true
            )
            """
        )
    )

    rows = await weather_repo.list_kma_weather_alert_history(
        migrated_session,
        region_code="11B10101",
        phenomenon="호우",
        history_from=_T1 - timedelta(days=1),
    )

    assert len(rows) == 1
    row = rows[0]
    assert row.source_record_key == "sr_kma_alert_1"
    assert row.feature_id == "f_notice_weather"
    assert row.region_name == "서울특별시"
    assert row.issued_at == _T1
    assert row.payload["alert_id"] == "A-1"


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


def _kma_short(fid: str, metric_key: str, **kw: object) -> WeatherValue:
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
        migrated_session,
        "krex_obs",
        lon=_BASE_LON + 0.034,
        lat=_BASE_LAT,
        kind="weather",
    )
    # KMA 중기/단기 anchor ≈ 8km 동쪽 (관측보다 멀다).
    await _ins_feature_at(
        migrated_session,
        "kma_anchor",
        lon=_BASE_LON + 0.090,
        lat=_BASE_LAT,
        kind="weather",
    )

    await weather_repo.load_weather_values(migrated_session, [_krex_observed("krex_obs")])
    await weather_repo.load_weather_values(
        migrated_session,
        [
            _kma_mid(
                "kma_anchor",
                "SKY",
                value_text="구름많음",
                metric_name="하늘상태",
                unit="code",
            ),
            _kma_mid(
                "kma_anchor",
                "POP",
                value_number=Decimal("30"),
                metric_name="강수확률",
                unit="%",
            ),
            _kma_mid(
                "kma_anchor",
                "TMN",
                value_number=Decimal("12.0"),
                metric_name="일 최저기온",
                unit="deg_c",
            ),
            _kma_mid(
                "kma_anchor",
                "TMX",
                value_number=Decimal("24.0"),
                metric_name="일 최고기온",
                unit="deg_c",
            ),
            _kma_short(
                "kma_anchor",
                "TMP",
                value_number=Decimal("21.0"),
                metric_name="기온",
                unit="deg_c",
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
        migrated_session,
        "krex_only",
        lon=_BASE_LON + 0.034,
        lat=_BASE_LAT,
        kind="weather",
    )
    await weather_repo.load_weather_values(migrated_session, [_krex_observed("krex_only")])

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
        migrated_session,
        "neighbor_obs",
        lon=_BASE_LON + 0.01,
        lat=_BASE_LAT,
        kind="weather",
    )
    await weather_repo.load_weather_values(migrated_session, [_krex_observed("neighbor_obs")])
    await weather_repo.load_weather_values(
        migrated_session,
        [
            _kma_short(
                "own",
                "TMP",
                value_number=Decimal("22.0"),
                metric_name="기온",
                unit="deg_c",
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
        migrated_session,
        "far_kma",
        lon=_BASE_LON + 1.0,
        lat=_BASE_LAT,
        kind="weather",
    )
    await weather_repo.load_weather_values(
        migrated_session,
        [
            _kma_short(
                "far_kma",
                "TMP",
                value_number=Decimal("20.0"),
                metric_name="기온",
                unit="deg_c",
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
                CASE WHEN g % 7 = 1 THEN 'weather' ELSE 'place' END,
                'seed ' || g::text, '06020000',
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
    await _ins_feature_at(migrated_session, "explain_target", lon=126.95, lat=37.55)
    await migrated_session.flush()
    await migrated_session.execute(text("ANALYZE feature.features"))
    await migrated_session.execute(text("ANALYZE feature.feature_weather_values"))
    await migrated_session.execute(text("ANALYZE feature.weather_metric_series"))

    batch_params = {
        "feature_ids": ["explain_target"],
        "target_ats": [datetime.now(_KST)],
        "known_at": datetime.now(_KST),
        "radius_m": 50_000.0,
        "timeline_days": 1,
        "metric_row_limit": weather_repo.WEATHER_BATCH_MAX_METRIC_ROWS,
        "response_byte_limit": weather_repo.WEATHER_BATCH_MAX_RESPONSE_BYTES,
        "series_work_limit": weather_repo.WEATHER_BATCH_MAX_SOURCE_SERIES_WORK,
    }
    default_batch_plan = (
        await migrated_session.execute(
            text(
                "EXPLAIN (FORMAT JSON, COSTS OFF) " + weather_repo._WEATHER_BATCH_SQL  # noqa: SLF001
            ),
            batch_params,
        )
    ).scalar_one()[0]["Plan"]
    catalog_seq_scans = [
        node
        for node in _walk_plan(default_batch_plan)
        if node.get("Node Type") == "Seq Scan"
        and node.get("Relation Name") == "weather_metric_series"
    ]
    assert not catalog_seq_scans, (
        "weather batch must index-probe only request/spatial candidate series: "
        f"{catalog_seq_scans}"
    )

    await migrated_session.execute(text("SET LOCAL enable_seqscan = off"))
    plan = (
        await migrated_session.execute(
            text(
                "EXPLAIN (FORMAT JSON, COSTS OFF) " + weather_repo._NEAREST_KMA_FORECAST_SQL  # noqa: SLF001
            ),
            {"feature_id": "explain_target", "radius_m": 50_000.0},
        )
    ).scalar_one()[0]["Plan"]
    nodes = _walk_plan(plan)

    index_names = {str(n["Index Name"]) for n in nodes if n.get("Index Name") is not None}
    assert "idx_features_public_weather_coord_5179_gist" in index_names, (
        f"expected weather-only coord_5179 GiST KNN, used={sorted(index_names)}"
    )
    weather_seq_scans = [
        n
        for n in nodes
        if n.get("Node Type") == "Seq Scan" and n.get("Relation Name") == "feature_weather_values"
    ]
    assert not weather_seq_scans, (
        f"feature_weather_values must not be full-scanned: {weather_seq_scans}"
    )

    batch_plan = (
        await migrated_session.execute(
            text(
                "EXPLAIN (FORMAT JSON, COSTS OFF) " + weather_repo._WEATHER_BATCH_SQL  # noqa: SLF001
            ),
            batch_params,
        )
    ).scalar_one()[0]["Plan"]
    batch_nodes = _walk_plan(batch_plan)
    batch_indexes = {
        str(node["Index Name"]) for node in batch_nodes if node.get("Index Name") is not None
    }
    assert "idx_weather_values_feature_effective" in batch_indexes
    assert not [
        node
        for node in batch_nodes
        if node.get("Node Type") == "Seq Scan"
        and node.get("Relation Name") == "feature_weather_values"
    ]
