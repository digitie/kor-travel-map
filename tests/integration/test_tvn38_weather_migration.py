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
from kortravelmap.infra.provider_refresh_policy_repo import (
    upsert_provider_refresh_policy,
)
from kortravelmap.infra.weather_repo import (
    build_weather_card,
    load_weather_values,
    materialize_current_weather_summary,
)

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
    await upsert_provider_refresh_policy(
        session,
        provider_dataset_id=int(dataset_id),
        source_kind="manual",
        expected_revision=None,
        stale_after_minutes=120,
    )

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
        provider_dataset_id=dataset_id,
        source_record=source_record,
        selected_at=_BASE + timedelta(minutes=2),
    ) == 1
    run_id = await migrated_session.scalar(
        text(
            """
            SELECT summary_run_id
            FROM feature.current_weather_summary
            WHERE feature_id = 'tvn38-weather-feature'
            """
        )
    )
    assert run_id is not None

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


async def test_weather_summary_uses_business_time_and_expires_stale_rows(
    migrated_session: AsyncSession,
) -> None:
    """정정 revision은 known_at 순위로 이기며 stale summary는 남기지 않는다."""

    dataset_id, first_response = await _seed_response_record(migrated_session)
    await migrated_session.execute(
        text(
            """
            INSERT INTO feature.features (feature_id, kind, name, category)
            VALUES ('tvn38-summary-feature', 'weather', 'T-VN-38 summary', '00000000')
            """
        )
    )
    first_value = WeatherValue(
        feature_id="tvn38-summary-feature",
        provider=_PROVIDER,
        weather_domain="kma_short_forecast",
        forecast_style="short",
        metric_key="TMP",
        valid_at=_BASE,
        value_number=Decimal("20.0"),
    )
    assert await load_weather_values(
        migrated_session,
        [first_value],
        provider_dataset_id=dataset_id,
        source_record=first_response,
        selected_at=_BASE,
    ) == 1

    second_response = SourceRecord(
        provider=_PROVIDER,
        dataset_key=_DATASET,
        source_entity_type="weather_response",
        source_entity_id="response-20260808T030000Z",
        raw_payload_hash=make_payload_hash({"response": "b"}),
        raw_data={"response": "b"},
        fetched_at=_BASE + timedelta(minutes=5),
        imported_at=_BASE + timedelta(minutes=5),
        source_record_key="tvn38-weather-response-b",
    )
    correction = first_value.model_copy(update={"value_number": Decimal("21.0")})
    assert await load_weather_values(
        migrated_session,
        [correction],
        provider_dataset_id=dataset_id,
        source_record=second_response,
        selected_at=_BASE + timedelta(minutes=10),
    ) == 1

    result = await materialize_current_weather_summary(
        migrated_session,
        selected_at=_BASE + timedelta(minutes=10),
        run_kind="ingest",
    )
    assert result.input_count == 2
    assert result.updated_count == 1
    assert await migrated_session.scalar(
        text(
            """
            SELECT fact.value_number
            FROM feature.current_weather_summary AS summary
            JOIN feature.feature_weather_values AS fact
              ON fact.weather_value_key = summary.weather_value_key
            WHERE summary.feature_id = 'tvn38-summary-feature'
            """
        )
    ) == Decimal("21.0000")
    assert await migrated_session.scalar(
        text(
            """
            SELECT refresh_after
            FROM feature.current_weather_summary
            WHERE feature_id = 'tvn38-summary-feature'
            """
        )
    ) == _BASE + timedelta(minutes=125)
    card = await build_weather_card(
        migrated_session,
        feature_id="tvn38-summary-feature",
    )
    assert card.metrics[0].value_number == Decimal("21.0000")
    assert card.metrics[0].provider_dataset_id == dataset_id
    assert card.metrics[0].dataset_key == _DATASET

    expired = await materialize_current_weather_summary(
        migrated_session,
        selected_at=_BASE + timedelta(hours=3),
    )
    assert expired.input_count == 0
    assert expired.deleted_count == 1
    assert await migrated_session.scalar(
        text(
            """
            SELECT count(*)
            FROM feature.current_weather_summary
            WHERE feature_id = 'tvn38-summary-feature'
            """
        )
    ) == 0
