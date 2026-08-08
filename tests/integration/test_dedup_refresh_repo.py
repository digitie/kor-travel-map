"""``infra.dedup_refresh_repo`` DB 기준 dedup refresh 입력 조회 테스트."""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import md5
from typing import TYPE_CHECKING

import pytest
from geoalchemy2 import WKTElement
from sqlalchemy import text

from kortravelmap.infra.dedup_refresh_repo import (
    DedupRefreshScope,
    list_dedup_refresh_features,
)
from kortravelmap.infra.models import (
    FeatureRow,
    SourceEntityHeadRow,
    SourceEntityRow,
    SourceLinkRow,
    SourceRecordRow,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_PROVIDER = "python-dedup-refresh-api"
_DATASET = "dedup_refresh_features"
_CAT = "01070100"
_T1 = datetime(2026, 6, 5, 9, 0, tzinfo=UTC)
_T2 = datetime(2026, 6, 5, 10, 0, tzinfo=UTC)


async def test_list_dedup_refresh_features_exposes_master_signals_and_keyset(
    migrated_session: AsyncSession,
) -> None:
    await _seed_feature(
        migrated_session,
        feature_id="dedup-refresh-a",
        updated_at=_T1,
        coord_precision_digits=5,
    )
    await _seed_feature(
        migrated_session,
        feature_id="dedup-refresh-b",
        updated_at=_T2,
        coord_precision_digits=7,
    )
    await _seed_feature(
        migrated_session,
        feature_id="dedup-refresh-c",
        updated_at=_T2,
        coord_precision_digits=6,
    )

    first_page = await list_dedup_refresh_features(
        migrated_session,
        DedupRefreshScope(provider=_PROVIDER, dataset_key=_DATASET, limit=2),
    )

    assert [item.feature_id for item in first_page] == [
        "dedup-refresh-c",
        "dedup-refresh-b",
    ]
    assert [item.coord_precision_digits for item in first_page] == [6, 7]
    assert first_page[0].updated_at == _T2
    assert first_page[0].as_master_candidate().feature_id == "dedup-refresh-c"
    assert first_page[0].as_master_candidate().has_coord is True

    last = first_page[-1]
    second_page = await list_dedup_refresh_features(
        migrated_session,
        DedupRefreshScope(
            provider=_PROVIDER,
            dataset_key=_DATASET,
            limit=2,
            cursor_updated_at=last.updated_at,
            cursor_feature_id=last.feature_id,
        ),
    )

    assert [item.feature_id for item in second_page] == ["dedup-refresh-a"]
    assert second_page[0].coord_precision_digits == 5


async def test_list_dedup_refresh_features_rejects_partial_cursor(
    migrated_session: AsyncSession,
) -> None:
    with pytest.raises(ValueError, match="cursor_updated_at"):
        await list_dedup_refresh_features(
            migrated_session,
            DedupRefreshScope(
                provider=_PROVIDER,
                dataset_key=_DATASET,
                limit=10,
                cursor_updated_at=_T1,
            ),
        )


async def _dataset_id(session: AsyncSession) -> int:
    """fixture 전용 catalog 행을 만들고 canonical id를 돌려준다 (T-VN-33).

    dedup refresh scope는 여전히 provider/dataset_key 표시 자연키를 받지만,
    source entity의 identity는 ``provider_dataset_id`` 하나다.
    """

    return int(
        (
            await session.execute(
                text(
                    """
                    INSERT INTO provider_sync.provider_datasets (
                        provider, dataset_key, display_name, source_kind,
                        is_active, capabilities
                    )
                    SELECT :provider, :dataset_key, :provider, 'system', true,
                           jsonb_build_object('schema_version', 1,
                                              'produces', '[]'::jsonb,
                                              'extensions', '{}'::jsonb)
                    ON CONFLICT (provider, dataset_key) DO UPDATE
                        SET display_name = EXCLUDED.display_name
                    RETURNING provider_dataset_id
                    """
                ),
                {"provider": _PROVIDER, "dataset_key": _DATASET},
            )
        ).scalar_one()
    )


async def _seed_feature(
    session: AsyncSession,
    *,
    feature_id: str,
    updated_at: datetime,
    coord_precision_digits: int,
) -> None:
    dataset_id = await _dataset_id(session)
    session.add(
        FeatureRow(
            feature_id=feature_id,
            kind="place",
            name=f"중복 후보 {feature_id}",
            category=_CAT,
            coord=WKTElement("POINT(129.3320 35.7900)", srid=4326),
            coord_precision_digits=coord_precision_digits,
            status="active",
            created_at=_T1,
            updated_at=updated_at,
        )
    )
    session.add(
        SourceEntityRow(
            source_entity_key=f"se-{feature_id}",
            provider_dataset_id=dataset_id,
            source_entity_type="place",
            source_entity_id=feature_id,
            first_seen_at=updated_at,
            last_seen_at=updated_at,
        )
    )
    await session.flush()
    session.add(
        SourceRecordRow(
            source_record_key=f"sr-{feature_id}",
            source_entity_key=f"se-{feature_id}",
            # ck_source_records_payload_hash_canonical = ^[0-9a-f]{1,64}$
            raw_payload_hash=md5(feature_id.encode()).hexdigest(),
            raw_data={"feature_id": feature_id},
            fetched_at=updated_at,
            imported_at=updated_at,
        )
    )
    await session.flush()
    session.add(
        SourceEntityHeadRow(
            source_entity_key=f"se-{feature_id}",
            current_source_record_key=f"sr-{feature_id}",
            observed_at=updated_at,
        )
    )
    await session.flush()
    session.add(
        SourceLinkRow(
            feature_id=feature_id,
            source_entity_key=f"se-{feature_id}",
            source_role="primary",
            match_method="natural_key",
            confidence=100,
            created_at=updated_at,
        )
    )
    await session.flush()
