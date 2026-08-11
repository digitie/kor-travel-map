"""T-VN-38B price fact/summary schema의 실제 migration 회귀 검증."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from kortravelmap.core.ids import make_payload_hash
from kortravelmap.dto import SourceRecord
from kortravelmap.dto.price import PriceValue
from kortravelmap.infra.price_repo import (
    build_price_card,
    load_price_values,
    materialize_current_price_summary,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession


pytestmark = pytest.mark.integration

_BASE = datetime(2026, 8, 8, 3, 0, tzinfo=UTC)
_PROVIDER = "tvn38-price-test"
_DATASET = "retail_prices"


async def _seed_response_record(
    session: AsyncSession, *, suffix: str, fetched_at: datetime
) -> tuple[int, SourceRecord]:
    if suffix == "a":
        dataset_id = await session.scalar(
            text(
                """
                INSERT INTO provider_sync.provider_datasets (
                    provider, dataset_key, display_name, source_kind
                ) VALUES (:provider, :dataset_key, 'T-VN-38 price test', 'manual')
                RETURNING provider_dataset_id
                """
            ),
            {"provider": _PROVIDER, "dataset_key": _DATASET},
        )
        assert dataset_id is not None
    else:
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
        source_entity_type="price_response",
        source_entity_id="response-20260808",
        raw_payload_hash=make_payload_hash({"response": suffix}),
        raw_data={"response": suffix},
        fetched_at=fetched_at,
        imported_at=fetched_at,
        source_record_key=f"tvn38-price-response-{suffix}",
    )
    return int(dataset_id), record


async def test_price_fact_is_immutable_and_current_rank_uses_known_at(
    migrated_session: AsyncSession,
) -> None:
    """같은 관측 correction은 새 response fact로 append하고 known_at으로 고른다."""

    dataset_id, first_response = await _seed_response_record(
        migrated_session, suffix="a", fetched_at=_BASE
    )
    _, correction_response = await _seed_response_record(
        migrated_session, suffix="b", fetched_at=_BASE + timedelta(minutes=5)
    )
    await migrated_session.execute(
        text(
            """
            INSERT INTO feature.features (feature_id, kind, name, category)
            VALUES ('tvn38-price-feature', 'price', 'T-VN-38 가격', '00000000')
            """
        )
    )
    value = PriceValue(
        feature_id="tvn38-price-feature",
        provider=_PROVIDER,
        price_domain="opinet_gas_station",
        product_key="gasoline",
        value_number=Decimal("1700"),
        unit="KRW/L",
        observed_at=_BASE - timedelta(hours=1),
    )
    assert await load_price_values(
        migrated_session,
        [value],
        provider_dataset_id=dataset_id,
        source_record=first_response,
    ) == 1
    assert await load_price_values(
        migrated_session,
        [value.model_copy(update={"value_number": Decimal("1720")})],
        provider_dataset_id=dataset_id,
        source_record=correction_response,
    ) == 1

    winner = (
        await migrated_session.execute(
            text(
                """
                SELECT fact.value_number, fact.known_at, summary.summary_run_id
                FROM feature.current_price_summary AS summary
                JOIN feature.feature_price_values AS fact
                  ON fact.price_value_key = summary.price_value_key
                WHERE summary.feature_id = 'tvn38-price-feature'
                """
            )
        )
    ).mappings().one()
    assert winner["value_number"] == Decimal("1720")
    assert winner["known_at"] == _BASE + timedelta(minutes=5)
    run_id = winner["summary_run_id"]

    with pytest.raises(DBAPIError, match="facts are immutable"):
        async with migrated_session.begin_nested():
            await migrated_session.execute(
                text(
                    """
                    UPDATE feature.feature_price_values
                    SET value_number = 99
                    WHERE feature_id = 'tvn38-price-feature'
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

    await migrated_session.execute(
        text("DELETE FROM feature.features WHERE feature_id = 'tvn38-price-feature'")
    )
    assert await migrated_session.scalar(
        text(
            """
            SELECT count(*) FROM feature.current_price_summary
            WHERE feature_id = 'tvn38-price-feature'
            """
        )
    ) == 0


async def test_price_current_reader_hides_inactive_dataset_before_reconcile(
    migrated_session: AsyncSession,
) -> None:
    """dataset deactivation과 delayed projection cleanup 사이에 current price를 노출하지 않는다."""

    dataset_id, response = await _seed_response_record(
        migrated_session, suffix="a", fetched_at=_BASE
    )
    await migrated_session.execute(
        text(
            """
            INSERT INTO feature.features (feature_id, kind, name, category)
            VALUES ('tvn38-price-inactive', 'price', 'T-VN-38 inactive price', '00000000')
            """
        )
    )
    assert await load_price_values(
        migrated_session,
        [
            PriceValue(
                feature_id="tvn38-price-inactive",
                provider=_PROVIDER,
                price_domain="opinet_gas_station",
                product_key="gasoline",
                value_number=Decimal("1700"),
                unit="KRW/L",
                observed_at=_BASE,
            )
        ],
        provider_dataset_id=dataset_id,
        source_record=response,
    ) == 1
    active = await build_price_card(
        migrated_session,
        feature_id="tvn38-price-inactive",
        stale_hide_days=None,
    )
    assert len(active.current) == 1

    await migrated_session.execute(
        text(
            """
            UPDATE provider_sync.provider_datasets
            SET is_active = false
            WHERE provider_dataset_id = :provider_dataset_id
            """
        ),
        {"provider_dataset_id": dataset_id},
    )
    inactive = await build_price_card(
        migrated_session,
        feature_id="tvn38-price-inactive",
        stale_hide_days=None,
    )
    assert inactive.current == []


async def test_price_global_projection_uses_transaction_advisory_lock(
    migrated_engine: AsyncEngine,
) -> None:
    """겹친 writer가 더 새 price summary pointer를 되돌리지 못하게 직렬화한다."""

    from sqlalchemy.ext.asyncio import AsyncSession

    from kortravelmap.infra.advisory_lock import advisory_lock_key

    holder = AsyncSession(migrated_engine, expire_on_commit=False)
    contender = AsyncSession(migrated_engine, expire_on_commit=False)
    try:
        await holder.begin()
        await holder.execute(
            text("SELECT pg_advisory_xact_lock(CAST(:lock_id AS bigint))"),
            {"lock_id": advisory_lock_key("projection:current-price-summary")},
        )
        task = asyncio.create_task(
            materialize_current_price_summary(contender, run_kind="reconcile")
        )
        await asyncio.sleep(0.05)
        assert not task.done()
        await holder.commit()
        result = await asyncio.wait_for(task, timeout=3)
        assert result.input_count == 0
    finally:
        if holder.in_transaction():
            await holder.rollback()
        if contender.in_transaction():
            await contender.rollback()
        await holder.close()
        await contender.close()
