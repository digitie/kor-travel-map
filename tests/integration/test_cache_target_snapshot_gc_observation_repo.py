"""Cache-target snapshot GC referenced 추세 영속화 회귀."""

from __future__ import annotations

from uuid import uuid4

import pytest
from kortravelmap.dagster import maintenance as maintenance_mod
from sqlalchemy import CheckConstraint, text
from sqlalchemy.exc import IntegrityError

from kortravelmap.client import (
    AsyncKorTravelMapClient,
    CacheTargetSnapshotGcDrainResult,
)
from kortravelmap.infra.advisory_lock import try_advisory_lock
from kortravelmap.infra.cache_target_snapshot_gc_observation_repo import (
    record_cache_target_snapshot_gc_observation,
)
from kortravelmap.infra.models import (
    FeatureRow,
    PoiCacheTargetSnapshotGcObservationRow,
)

pytestmark = pytest.mark.integration


async def test_gc_observation_check_catalog_matches_orm_and_not_feature(
    migrated_session,
) -> None:
    prefix = "ck_cache_target_snapshot_gc_observations_"
    observation_checks = {
        str(constraint.name): str(constraint.sqltext)
        for constraint in PoiCacheTargetSnapshotGcObservationRow.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    }
    feature_check_names = {
        str(constraint.name)
        for constraint in FeatureRow.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    }
    rows = (
        await migrated_session.execute(
            text(
                "SELECT conname, pg_get_constraintdef(oid) AS definition "
                "FROM pg_constraint "
                "WHERE conrelid = "
                "'ops.poi_cache_target_snapshot_gc_observations'::regclass "
                "AND contype = 'c'"
            )
        )
    ).all()
    database_checks = {str(row.conname): str(row.definition) for row in rows}

    assert set(database_checks) == set(observation_checks)
    assert not any(name.startswith(prefix) for name in feature_check_names)
    for definitions in (database_checks, observation_checks):
        previous = definitions[f"{prefix}previous"].lower()
        growth = definitions[f"{prefix}growth_baseline"].lower()
        eligibility = definitions[f"{prefix}eligibility"].lower()
        assert "previous_observed_at is not null" in previous
        assert "previous_referenced_items is not null" in previous
        assert "previous_referenced_headers is not null" in previous
        assert "growth_baseline_observed_at is not null" in growth
        assert "growth_baseline_referenced_items is not null" in growth
        assert "growth_baseline_referenced_headers is not null" in growth
        assert "growth_baseline_eligible" in eligibility
        assert "growth_min_interval_seconds" in eligibility
        assert "previous_observed_at" in eligibility


async def test_short_rerun_does_not_absorb_spike_from_next_eligible_baseline(
    migrated_session,
) -> None:
    prefix = f"gc-short-{uuid4()}"
    first = await record_cache_target_snapshot_gc_observation(
        migrated_session,
        dagster_run_id=f"{prefix}-1",
        referenced_items=100,
        referenced_headers=2,
        retention_days=90,
        growth_min_interval_seconds=300,
    )
    await migrated_session.execute(
        text(
            "UPDATE ops.poi_cache_target_snapshot_gc_observations "
            "SET observed_at = transaction_timestamp() - interval '299 seconds' "
            "WHERE dagster_run_id = :run_id"
        ),
        {"run_id": first.dagster_run_id},
    )
    short = await record_cache_target_snapshot_gc_observation(
        migrated_session,
        dagster_run_id=f"{prefix}-2",
        referenced_items=200,
        referenced_headers=2,
        retention_days=90,
        growth_min_interval_seconds=300,
    )
    retry = await record_cache_target_snapshot_gc_observation(
        migrated_session,
        dagster_run_id=f"{prefix}-2",
        referenced_items=999_999,
        referenced_headers=999,
        retention_days=90,
        growth_min_interval_seconds=3_600,
    )
    assert short.growth_baseline_run_id == first.dagster_run_id
    assert short.growth_baseline_eligible is False
    assert retry == short

    await migrated_session.execute(
        text(
            "UPDATE ops.poi_cache_target_snapshot_gc_observations "
            "SET observed_at = transaction_timestamp() - interval '1 hour' "
            "WHERE dagster_run_id = :run_id"
        ),
        {"run_id": first.dagster_run_id},
    )
    await migrated_session.execute(
        text(
            "UPDATE ops.poi_cache_target_snapshot_gc_observations "
            "SET observed_at = transaction_timestamp() - interval '1 second' "
            "WHERE dagster_run_id = :run_id"
        ),
        {"run_id": short.dagster_run_id},
    )
    evaluable = await record_cache_target_snapshot_gc_observation(
        migrated_session,
        dagster_run_id=f"{prefix}-3",
        referenced_items=150,
        referenced_headers=2,
        retention_days=90,
        growth_min_interval_seconds=300,
    )

    assert evaluable.growth_baseline_run_id == first.dagster_run_id
    assert evaluable.growth_baseline_referenced_items == 100
    assert evaluable.growth_baseline_referenced_headers == 2
    assert evaluable.previous_observation_run_id == short.dagster_run_id
    assert evaluable.previous_referenced_items == 200
    assert evaluable.previous_referenced_headers == 2
    assert evaluable.growth_baseline_eligible is True
    assert (
        evaluable.observed_at - evaluable.growth_baseline_observed_at
    ).total_seconds() == 3_600
    metadata = maintenance_mod._cache_target_referenced_alert_metadata(
        CacheTargetSnapshotGcDrainResult(
            acquired=True,
            skipped=False,
            batches=1,
            deleted_items=0,
            deleted_headers=0,
            remaining_items=0,
            remaining_headers=0,
            observation_run_id=evaluable.dagster_run_id,
            observed_at=evaluable.observed_at,
            observation_referenced_items=evaluable.referenced_items,
            observation_referenced_headers=evaluable.referenced_headers,
            previous_observation_run_id=evaluable.previous_observation_run_id,
            previous_observed_at=evaluable.previous_observed_at,
            previous_referenced_items=evaluable.previous_referenced_items,
            previous_referenced_headers=evaluable.previous_referenced_headers,
            growth_baseline_observation_run_id=evaluable.growth_baseline_run_id,
            growth_baseline_observed_at=evaluable.growth_baseline_observed_at,
            growth_baseline_referenced_items=(
                evaluable.growth_baseline_referenced_items
            ),
            growth_baseline_referenced_headers=(
                evaluable.growth_baseline_referenced_headers
            ),
            observation_growth_baseline_eligible=(
                evaluable.growth_baseline_eligible
            ),
            observation_growth_min_interval_seconds=(
                evaluable.growth_min_interval_seconds
            ),
        ),
        item_ceiling=1_000,
        header_ceiling=10,
        item_growth_ceiling_per_hour=10,
        header_growth_ceiling_per_hour=10,
        growth_min_interval_seconds=300,
        observation_retention_days=90,
    )
    assert metadata["referenced_items_delta"] == -50
    assert metadata["referenced_items_growth_baseline_delta"] == 50
    assert metadata["referenced_items_growth_per_hour"] == 50
    assert metadata["referenced_item_inventory_loss_alert"] is True


async def test_equal_and_reversed_database_clock_rows_are_not_promoted(
    migrated_session,
) -> None:
    prefix = f"gc-clock-{uuid4()}"
    first = await record_cache_target_snapshot_gc_observation(
        migrated_session,
        dagster_run_id=f"{prefix}-1",
        referenced_items=10,
        referenced_headers=1,
        retention_days=90,
        growth_min_interval_seconds=300,
    )
    equal = await record_cache_target_snapshot_gc_observation(
        migrated_session,
        dagster_run_id=f"{prefix}-2",
        referenced_items=5,
        referenced_headers=2,
        retention_days=90,
        growth_min_interval_seconds=300,
    )
    assert equal.growth_baseline_run_id == first.dagster_run_id
    assert equal.previous_observation_run_id == first.dagster_run_id
    assert equal.previous_referenced_items == 10
    assert equal.observed_at == equal.growth_baseline_observed_at
    assert equal.growth_baseline_eligible is False

    await migrated_session.execute(
        text(
            "UPDATE ops.poi_cache_target_snapshot_gc_observations "
            "SET observed_at = transaction_timestamp() + interval '1 hour' "
            "WHERE dagster_run_id = :run_id"
        ),
        {"run_id": first.dagster_run_id},
    )
    reversed_clock = await record_cache_target_snapshot_gc_observation(
        migrated_session,
        dagster_run_id=f"{prefix}-3",
        referenced_items=4,
        referenced_headers=3,
        retention_days=90,
        growth_min_interval_seconds=300,
    )
    assert reversed_clock.growth_baseline_run_id == first.dagster_run_id
    assert reversed_clock.previous_observation_run_id == equal.dagster_run_id
    assert reversed_clock.previous_referenced_items == 5
    assert reversed_clock.observed_at < reversed_clock.growth_baseline_observed_at
    assert reversed_clock.growth_baseline_eligible is False

    await migrated_session.execute(
        text(
            "UPDATE ops.poi_cache_target_snapshot_gc_observations "
            "SET observed_at = transaction_timestamp() - interval '1 hour' "
            "WHERE dagster_run_id = :run_id"
        ),
        {"run_id": first.dagster_run_id},
    )
    await migrated_session.execute(
        text(
            "UPDATE ops.poi_cache_target_snapshot_gc_observations "
            "SET observed_at = transaction_timestamp() - interval '1 second' "
            "WHERE dagster_run_id = :run_id"
        ),
        {"run_id": reversed_clock.dagster_run_id},
    )
    recovered = await record_cache_target_snapshot_gc_observation(
        migrated_session,
        dagster_run_id=f"{prefix}-4",
        referenced_items=40,
        referenced_headers=4,
        retention_days=90,
        growth_min_interval_seconds=300,
    )
    assert recovered.growth_baseline_run_id == first.dagster_run_id
    assert recovered.growth_baseline_eligible is True


async def test_config_change_cannot_promote_row_behind_previous_clock(
    migrated_session,
) -> None:
    prefix = f"gc-config-clock-{uuid4()}"
    baseline = await record_cache_target_snapshot_gc_observation(
        migrated_session,
        dagster_run_id=f"{prefix}-baseline",
        referenced_items=100,
        referenced_headers=1,
        retention_days=90,
        growth_min_interval_seconds=2_000,
    )
    await migrated_session.execute(
        text(
            "UPDATE ops.poi_cache_target_snapshot_gc_observations "
            "SET observed_at = transaction_timestamp() - interval '1000 seconds' "
            "WHERE dagster_run_id = :run_id"
        ),
        {"run_id": baseline.dagster_run_id},
    )
    previous = await record_cache_target_snapshot_gc_observation(
        migrated_session,
        dagster_run_id=f"{prefix}-previous",
        referenced_items=200,
        referenced_headers=2,
        retention_days=90,
        growth_min_interval_seconds=2_000,
    )
    assert previous.growth_baseline_eligible is False
    await migrated_session.execute(
        text(
            "UPDATE ops.poi_cache_target_snapshot_gc_observations "
            "SET observed_at = transaction_timestamp() + interval '100 seconds' "
            "WHERE dagster_run_id = :run_id"
        ),
        {"run_id": previous.dagster_run_id},
    )
    current = await record_cache_target_snapshot_gc_observation(
        migrated_session,
        dagster_run_id=f"{prefix}-current",
        referenced_items=250,
        referenced_headers=3,
        retention_days=90,
        growth_min_interval_seconds=300,
    )

    assert current.growth_baseline_run_id == baseline.dagster_run_id
    assert current.previous_observation_run_id == previous.dagster_run_id
    assert current.growth_baseline_eligible is False
    assert current.observed_at > current.growth_baseline_observed_at
    assert current.observed_at < current.previous_observed_at

    metadata = maintenance_mod._cache_target_referenced_alert_metadata(
        CacheTargetSnapshotGcDrainResult(
            acquired=True,
            skipped=False,
            batches=1,
            deleted_items=0,
            deleted_headers=0,
            remaining_items=0,
            remaining_headers=0,
            observation_run_id=current.dagster_run_id,
            observed_at=current.observed_at,
            observation_referenced_items=current.referenced_items,
            observation_referenced_headers=current.referenced_headers,
            previous_observation_run_id=current.previous_observation_run_id,
            previous_observed_at=current.previous_observed_at,
            previous_referenced_items=current.previous_referenced_items,
            previous_referenced_headers=current.previous_referenced_headers,
            growth_baseline_observation_run_id=current.growth_baseline_run_id,
            growth_baseline_observed_at=current.growth_baseline_observed_at,
            growth_baseline_referenced_items=(
                current.growth_baseline_referenced_items
            ),
            growth_baseline_referenced_headers=(
                current.growth_baseline_referenced_headers
            ),
            observation_growth_baseline_eligible=(
                current.growth_baseline_eligible
            ),
            observation_growth_min_interval_seconds=(
                current.growth_min_interval_seconds
            ),
        ),
        item_ceiling=1_000,
        header_ceiling=10,
        item_growth_ceiling_per_hour=1,
        header_growth_ceiling_per_hour=1,
        growth_min_interval_seconds=300,
        observation_retention_days=90,
    )
    assert metadata["referenced_growth_rate_observed"] is False
    assert metadata["referenced_items_growth_per_hour"] == "not_observed"
    assert metadata["referenced_growth_baseline_elapsed_seconds"] == 1_000.0
    assert metadata["referenced_observation_elapsed_seconds"] == -100.0
    assert metadata["referenced_observation_status"] == (
        "non_forward_database_clock"
    )
    assert metadata["referenced_growth_unobserved_reason"] == (
        "non_forward_database_clock"
    )


async def test_client_real_gc_lock_skip_then_observation_retry_is_exact(
    migrated_engine,
) -> None:
    run_id = f"gc-client-{uuid4()}"
    client = AsyncKorTravelMapClient(migrated_engine)
    try:
        async with migrated_engine.connect() as owner, try_advisory_lock(
            owner, "cache-target-snapshot-gc"
        ) as acquired:
            assert acquired
            await owner.commit()
            skipped = await client.drain_expired_cache_target_snapshots(
                max_batches=1,
                observation_run_id=run_id,
                observation_growth_min_interval_seconds=300,
            )
            assert skipped.skipped is True
            assert skipped.observation_run_id is None

        first = await client.drain_expired_cache_target_snapshots(
            max_batches=1,
            observation_run_id=run_id,
            observation_growth_min_interval_seconds=300,
        )
        retry = await client.drain_expired_cache_target_snapshots(
            max_batches=1,
            observation_run_id=run_id,
            observation_growth_min_interval_seconds=3_600,
        )
        assert first.acquired is True
        assert retry.observation_run_id == first.observation_run_id == run_id
        assert retry.observed_at == first.observed_at
        assert retry.observation_referenced_items == first.observation_referenced_items
        assert retry.observation_referenced_headers == first.observation_referenced_headers
        assert retry.previous_observation_run_id == first.previous_observation_run_id
        assert retry.previous_observed_at == first.previous_observed_at
        assert retry.previous_referenced_items == first.previous_referenced_items
        assert retry.previous_referenced_headers == first.previous_referenced_headers
        assert (
            retry.growth_baseline_observation_run_id
            == first.growth_baseline_observation_run_id
        )
        assert retry.growth_baseline_observed_at == first.growth_baseline_observed_at
        assert (
            retry.growth_baseline_referenced_items
            == first.growth_baseline_referenced_items
        )
        assert (
            retry.growth_baseline_referenced_headers
            == first.growth_baseline_referenced_headers
        )
        assert (
            retry.observation_growth_baseline_eligible
            == first.observation_growth_baseline_eligible
        )
        assert retry.observation_growth_min_interval_seconds == 300
        async with migrated_engine.connect() as connection:
            count = await connection.scalar(
                text(
                    "SELECT count(*) FROM "
                    "ops.poi_cache_target_snapshot_gc_observations "
                    "WHERE dagster_run_id = :run_id"
                ),
                {"run_id": run_id},
            )
        assert count == 1
    finally:
        async with migrated_engine.begin() as connection:
            await connection.execute(
                text(
                    "DELETE FROM ops.poi_cache_target_snapshot_gc_observations "
                    "WHERE dagster_run_id = :run_id"
                ),
                {"run_id": run_id},
            )


async def test_gc_observation_prunes_expired_history(migrated_session) -> None:
    prefix = f"gc-prune-{uuid4()}"
    first = await record_cache_target_snapshot_gc_observation(
        migrated_session,
        dagster_run_id=f"{prefix}-1",
        referenced_items=1,
        referenced_headers=1,
        retention_days=90,
        growth_min_interval_seconds=300,
    )
    await migrated_session.execute(
        text(
            "UPDATE ops.poi_cache_target_snapshot_gc_observations "
            "SET observed_at = transaction_timestamp() - interval '91 days' "
            "WHERE dagster_run_id = :run_id"
        ),
        {"run_id": first.dagster_run_id},
    )
    ancient_retry = await record_cache_target_snapshot_gc_observation(
        migrated_session,
        dagster_run_id=first.dagster_run_id,
        referenced_items=999,
        referenced_headers=999,
        retention_days=90,
        growth_min_interval_seconds=3_600,
    )
    assert ancient_retry.referenced_items == 1
    assert ancient_retry.referenced_headers == 1
    assert ancient_retry.growth_min_interval_seconds == 300

    second = await record_cache_target_snapshot_gc_observation(
        migrated_session,
        dagster_run_id=f"{prefix}-2",
        referenced_items=2,
        referenced_headers=2,
        retention_days=90,
        growth_min_interval_seconds=300,
    )
    assert second.growth_baseline_run_id is None
    remaining = await migrated_session.scalar(
        text(
            "SELECT count(*) FROM ops.poi_cache_target_snapshot_gc_observations "
            "WHERE dagster_run_id LIKE :prefix"
        ),
        {"prefix": f"{prefix}%"},
    )
    assert remaining == 1


async def test_gc_observation_table_rejects_invalid_raw_counts(
    migrated_session,
) -> None:
    with pytest.raises(
        IntegrityError,
        match="ck_cache_target_snapshot_gc_observations_counts",
    ):
        async with migrated_session.begin_nested():
            await migrated_session.execute(
                text(
                    "INSERT INTO ops.poi_cache_target_snapshot_gc_observations "
                    "(dagster_run_id, referenced_items, referenced_headers, "
                    "growth_baseline_eligible, growth_min_interval_seconds) "
                    "VALUES ('invalid-count-run', -1, 0, true, 300)"
                )
            )


@pytest.mark.parametrize(
    "columns_and_values",
    [
        (
            "growth_baseline_run_id, growth_baseline_observed_at, "
            "growth_baseline_referenced_items, "
            "growth_baseline_referenced_headers",
            "'baseline', transaction_timestamp(), NULL, 1",
        ),
        (
            "growth_baseline_run_id, growth_baseline_observed_at, "
            "growth_baseline_referenced_items, "
            "growth_baseline_referenced_headers",
            "'baseline', transaction_timestamp(), 1, NULL",
        ),
        (
            "previous_observation_run_id, previous_observed_at, "
            "previous_referenced_items, previous_referenced_headers",
            "'previous', transaction_timestamp(), NULL, 1",
        ),
    ],
)
async def test_gc_observation_table_rejects_partial_raw_baseline_shapes(
    migrated_session,
    columns_and_values: tuple[str, str],
) -> None:
    columns, values = columns_and_values
    run_id = f"partial-{uuid4()}"
    with pytest.raises(IntegrityError):
        async with migrated_session.begin_nested():
            await migrated_session.execute(
                text(
                    "INSERT INTO ops.poi_cache_target_snapshot_gc_observations "
                    f"(dagster_run_id, referenced_items, referenced_headers, {columns}, "
                    "growth_baseline_eligible, growth_min_interval_seconds) "
                    f"VALUES (:run_id, 1, 1, {values}, false, 300)"
                ),
                {"run_id": run_id},
            )


async def test_gc_observation_table_rejects_raw_ineligible_interval_as_eligible(
    migrated_session,
) -> None:
    prefix = f"raw-eligibility-{uuid4()}"
    await migrated_session.execute(
        text(
            "INSERT INTO ops.poi_cache_target_snapshot_gc_observations "
            "(dagster_run_id, observed_at, referenced_items, referenced_headers, "
            "growth_baseline_eligible, growth_min_interval_seconds) "
            "VALUES (:run_id, transaction_timestamp(), 1, 1, true, 300)"
        ),
        {"run_id": f"{prefix}-baseline"},
    )
    with pytest.raises(
        IntegrityError,
        match="ck_cache_target_snapshot_gc_observations_eligibility",
    ):
        async with migrated_session.begin_nested():
            await migrated_session.execute(
                text(
                    "INSERT INTO ops.poi_cache_target_snapshot_gc_observations "
                    "(dagster_run_id, observed_at, referenced_items, "
                    "referenced_headers, previous_observation_run_id, "
                    "previous_observed_at, previous_referenced_items, "
                    "previous_referenced_headers, growth_baseline_run_id, "
                    "growth_baseline_observed_at, "
                    "growth_baseline_referenced_items, "
                    "growth_baseline_referenced_headers, "
                    "growth_baseline_eligible, growth_min_interval_seconds) "
                    "VALUES (:run_id, transaction_timestamp() + interval '60 seconds', "
                    "2, 2, :baseline_run_id, transaction_timestamp(), 1, 1, "
                    ":baseline_run_id, transaction_timestamp(), 1, 1, true, 300)"
                ),
                {
                    "run_id": f"{prefix}-invalid",
                    "baseline_run_id": f"{prefix}-baseline",
                },
            )
    with pytest.raises(
        IntegrityError,
        match="ck_cache_target_snapshot_gc_observations_eligibility",
    ):
        async with migrated_session.begin_nested():
            await migrated_session.execute(
                text(
                    "INSERT INTO ops.poi_cache_target_snapshot_gc_observations "
                    "(dagster_run_id, observed_at, referenced_items, "
                    "referenced_headers, previous_observation_run_id, "
                    "previous_observed_at, previous_referenced_items, "
                    "previous_referenced_headers, growth_baseline_run_id, "
                    "growth_baseline_observed_at, "
                    "growth_baseline_referenced_items, "
                    "growth_baseline_referenced_headers, "
                    "growth_baseline_eligible, growth_min_interval_seconds) "
                    "VALUES (:run_id, transaction_timestamp(), 3, 3, "
                    ":previous_run_id, "
                    "transaction_timestamp() + interval '100 seconds', 2, 2, "
                    ":baseline_run_id, "
                    "transaction_timestamp() - interval '1000 seconds', 1, 1, "
                    "true, 300)"
                ),
                {
                    "run_id": f"{prefix}-reverse-invalid",
                    "previous_run_id": f"{prefix}-previous",
                    "baseline_run_id": f"{prefix}-baseline-copy",
                },
            )
