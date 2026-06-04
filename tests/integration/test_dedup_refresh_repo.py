"""``infra.dedup_refresh_repo`` DB 기준 dedup refresh 입력 조회 테스트."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from geoalchemy2 import WKTElement

from krtour.map.infra.dedup_refresh_repo import (
    DedupRefreshScope,
    list_dedup_refresh_features,
)
from krtour.map.infra.models import FeatureRow, SourceLinkRow, SourceRecordRow

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


async def _seed_feature(
    session: AsyncSession,
    *,
    feature_id: str,
    updated_at: datetime,
    coord_precision_digits: int,
) -> None:
    session.add(
        FeatureRow(
            feature_id=feature_id,
            kind="place",
            name=f"중복 후보 {feature_id}",
            category=_CAT,
            coord=WKTElement("POINT(129.3320 35.7900)", srid=4326),
            coord_precision_digits=coord_precision_digits,
            detail={"summary": "dedup refresh"},
            status="active",
            created_at=_T1,
            updated_at=updated_at,
        )
    )
    session.add(
        SourceRecordRow(
            source_record_key=f"sr-{feature_id}",
            provider=_PROVIDER,
            dataset_key=_DATASET,
            source_entity_type="place",
            source_entity_id=feature_id,
            raw_name=feature_id,
            raw_address="경상북도 경주시 불국로 385",
            raw_payload_hash=f"hash-{feature_id}",
            raw_data={"feature_id": feature_id},
            fetched_at=updated_at,
            imported_at=updated_at,
        )
    )
    await session.flush()
    session.add(
        SourceLinkRow(
            feature_id=feature_id,
            source_record_key=f"sr-{feature_id}",
            source_role="primary",
            match_method="natural_key",
            confidence=100,
            is_primary_source=True,
            created_at=updated_at,
        )
    )
    await session.flush()
