"""통합 테스트 DB reset helper의 append-only trigger 복원 검증."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.infra.models import FeatureRow
from tests.integration._db_cleanup import truncate_committed_test_rows
from tests.integration._feature_ids import feature_uuid

pytestmark = pytest.mark.integration


async def _assert_history_truncate_is_rejected(session: AsyncSession) -> None:
    with pytest.raises(DBAPIError, match="curation import/link history is append-only"):
        async with session.begin_nested():
            await session.execute(
                text("TRUNCATE feature.curation_import_batches CASCADE")
            )


async def test_cleanup_reenables_append_only_trigger_after_success(
    migrated_session: AsyncSession,
) -> None:
    await truncate_committed_test_rows(
        migrated_session,
        "TRUNCATE feature.features RESTART IDENTITY CASCADE",
    )

    await _assert_history_truncate_is_rejected(migrated_session)


async def test_cleanup_rollback_reenables_append_only_trigger_after_failure(
    migrated_session: AsyncSession,
) -> None:
    with pytest.raises(DBAPIError):
        await truncate_committed_test_rows(
            migrated_session,
            "TRUNCATE feature.missing_cleanup_table",
        )

    await _assert_history_truncate_is_rejected(migrated_session)


_ANY_DATASET_SQL = "SELECT provider_dataset_id FROM provider_sync.provider_datasets LIMIT 1"

_CLAIM_SQL = (
    "INSERT INTO provider_sync.provider_feature_identities "
    "(provider_dataset_id, feature_kind, natural_key, feature_id, bound_by_operation) "
    "VALUES (:dataset_id, 'place', :natural_key, CAST(:feature_id AS uuid), 'test')"
)

_CLAIM_EXISTS_SQL = (
    "SELECT count(*) FROM provider_sync.provider_feature_identities "
    "WHERE natural_key = :natural_key"
)


async def test_cleanup_sweeps_provider_claims_whose_feature_is_gone(
    migrated_session: AsyncSession,
) -> None:
    """부모 없는 claim은 거두고, 부모가 살아 있는 claim은 그대로 둔다.

    `provider_sync.provider_feature_identities`에는 `feature.features`로 가는 FK가
    없다. 그래서 `TRUNCATE feature.features CASCADE`가 claim을 데려가지 않고,
    commit하는 테스트가 지나간 자리에 고아 claim이 남는다 — 그 상태를 다른 파일의
    identity 불변식이 대신 죽으며 알려 준다(2026-09-10 전량 런에서 실제로 그랬다).

    두 갈래를 한 자리에서 본다. 거두는 것만 보면 "전부 지운다"와 구분되지 않고,
    그러면 claim을 가진 채로 이어지는 테스트가 조용히 상태를 잃는다.
    """
    dataset_id = int(
        (await migrated_session.execute(text(_ANY_DATASET_SQL))).scalar_one()
    )
    orphan_uuid = feature_uuid("cleanup-orphan-claim")
    await migrated_session.execute(
        text(_CLAIM_SQL),
        {
            "dataset_id": dataset_id,
            "natural_key": "cleanup-orphan-claim",
            "feature_id": orphan_uuid,
        },
    )

    await truncate_committed_test_rows(
        migrated_session,
        "TRUNCATE feature.features RESTART IDENTITY CASCADE",
    )

    remaining = (
        await migrated_session.execute(
            text(_CLAIM_EXISTS_SQL), {"natural_key": "cleanup-orphan-claim"}
        )
    ).scalar_one()
    assert remaining == 0, "부모 없는 claim이 남았다 — 다른 파일의 불변식이 대신 죽는다"

    # 부모가 살아 있으면 건드리지 않는다.
    kept_uuid = feature_uuid("cleanup-kept-claim")
    migrated_session.add(
        FeatureRow(
            feature_id=kept_uuid,
            kind="place",
            name="정리 후에도 남는 feature",
            category="01070100",
        )
    )
    await migrated_session.flush()
    await migrated_session.execute(
        text(_CLAIM_SQL),
        {
            "dataset_id": dataset_id,
            "natural_key": "cleanup-kept-claim",
            "feature_id": kept_uuid,
        },
    )

    await truncate_committed_test_rows(
        migrated_session,
        "TRUNCATE ops.dedup_review_queue RESTART IDENTITY CASCADE",
    )

    kept = (
        await migrated_session.execute(
            text(_CLAIM_EXISTS_SQL), {"natural_key": "cleanup-kept-claim"}
        )
    ).scalar_one()
    assert kept == 1, "부모가 살아 있는 claim까지 거뒀다 — 그러면 상태가 조용히 사라진다"
