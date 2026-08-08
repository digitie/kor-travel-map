"""T-VN-38A weather fact/summary schema의 실제 migration 회귀 검증."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from kortravelmap.core.ids import make_payload_hash
from kortravelmap.dto import SourceRecord
from kortravelmap.dto.weather import WeatherValue
from kortravelmap.infra.feature_repo import upsert_source_record
from kortravelmap.infra.weather_repo import WeatherValueWriteContext, load_weather_values

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


pytestmark = pytest.mark.integration

_BASE = datetime(2026, 8, 8, 3, 0, tzinfo=UTC)
_PROVIDER = "tvn38-weather-test"
_DATASET = "forecast"


async def _seed_response_record(session: AsyncSession) -> tuple[int, SourceRecord]:
    await session.execute(
        text(
            """
            INSERT INTO provider_sync.provider_datasets (
                provider, dataset_key, display_name, source_kind
            ) VALUES (:provider, :dataset_key, 'T-VN-38 weather test', 'manual')
            RETURNING provider_dataset_id
            """
        ),
        {"provider": _PROVIDER, "dataset_key": _DATASET},
    )
    dataset_id = await session.scalar(
        text(
            """
            SELECT provider_dataset_id
            FROM provider_sync.provider_datasets
            WHERE provider = :provider AND dataset_key = :dataset_key
            """
        ),
        {"provider": _PROVIDER, "dataset_key": _DATASET},
    )
    assert dataset_id is not None

    record = SourceRecord(
        provider=_PROVIDER,
        dataset_key=_DATASET,
        source_entity_type="weather_response",
        source_entity_id="response-20260808T030000Z",
        raw_payload_hash=make_payload_hash({"response": "a"}),
        raw_data={"response": "a"},
        fetched_at=_BASE,
        imported_at=_BASE,
        source_record_key="tvn38-weather-response-a",
    )
    assert await upsert_source_record(session, record) is True
    return int(dataset_id), record


async def test_weather_fact_is_immutable_and_summary_requires_successful_receipt(
    migrated_session: AsyncSession,
) -> None:
    """source revision·dataset이 맞는 append fact만 current summary가 참조한다."""

    dataset_id, source_record = await _seed_response_record(migrated_session)
    await migrated_session.execute(
        text(
            """
            INSERT INTO feature.features (feature_id, kind, name, category)
            VALUES ('tvn38-weather-feature', 'weather', 'T-VN-38 날씨', '00000000')
            """
        )
    )
    source_entity_key = await migrated_session.scalar(
        text(
            """
            SELECT source_entity_key
            FROM provider_sync.source_records
            WHERE source_record_key = :source_record_key
            """
        ),
        {"source_record_key": source_record.source_record_key},
    )
    assert source_entity_key is not None

    run_id = await migrated_session.scalar(
        text(
            """
            INSERT INTO ops.current_summary_runs (
                projection_kind, run_kind, status, started_at
            ) VALUES ('weather', 'ingest', 'running', :started_at)
            RETURNING summary_run_id
            """
        ),
        {"started_at": _BASE},
    )
    assert run_id is not None
    await migrated_session.execute(
        text(
            """
            UPDATE ops.current_summary_runs
            SET status = 'succeeded', finished_at = :finished_at, input_count = 1,
                inserted_count = 1
            WHERE summary_run_id = :summary_run_id
            """
        ),
        {"finished_at": _BASE + timedelta(minutes=1), "summary_run_id": run_id},
    )

    context = WeatherValueWriteContext(
        provider_dataset_id=dataset_id,
        source_entity_key=str(source_entity_key),
        source_record_key=source_record.source_record_key,
        known_at=_BASE,
    )
    assert await load_weather_values(
        migrated_session,
        [
            WeatherValue(
                feature_id="tvn38-weather-feature",
                provider=_PROVIDER,
                weather_domain="kma_short_forecast",
                forecast_style="short",
                metric_key="TMP",
                valid_at=_BASE,
                value_number=Decimal("23.5"),
            )
        ],
        context=context,
    ) == 1
    await migrated_session.execute(
        text(
            """
            INSERT INTO feature.current_weather_summary (
                feature_id, provider_dataset_id, weather_domain, forecast_style,
                metric_key, weather_value_key, summary_run_id, selected_at, refresh_after
            ) VALUES (
                'tvn38-weather-feature', :dataset_id, 'kma_short_forecast', 'short', 'TMP',
                (SELECT weather_value_key FROM feature.feature_weather_values
                 WHERE feature_id = 'tvn38-weather-feature'),
                :summary_run_id, :selected_at, :refresh_after
            )
            """
        ),
        {
            "dataset_id": dataset_id,
            "summary_run_id": run_id,
            "selected_at": _BASE + timedelta(minutes=2),
            "refresh_after": _BASE + timedelta(minutes=3),
        },
    )

    with pytest.raises(DBAPIError, match="facts are immutable"):
        async with migrated_session.begin_nested():
            await migrated_session.execute(
                text(
                    """
                    UPDATE feature.feature_weather_values
                    SET value_number = 99
                    WHERE feature_id = 'tvn38-weather-feature'
                    """
                )
            )
    with pytest.raises(DBAPIError, match="terminal current summary receipt is immutable"):
        async with migrated_session.begin_nested():
            await migrated_session.execute(
                text(
                    """
                    UPDATE ops.current_summary_runs
                    SET detail = '{"late": true}'::jsonb
                    WHERE summary_run_id = :summary_run_id
                    """
                ),
                {"summary_run_id": run_id},
            )

    # parent cascade는 immutable fact/summary trigger에 막히지 않아야 한다.
    await migrated_session.execute(
        text("DELETE FROM feature.features WHERE feature_id = 'tvn38-weather-feature'")
    )
    assert await migrated_session.scalar(
        text(
            """
            SELECT count(*) FROM feature.current_weather_summary
            WHERE feature_id = 'tvn38-weather-feature'
            """
        )
    ) == 0
