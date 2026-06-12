"""``test_phone_enrichment`` — Place 전화번호 보강 (Sprint 4b, ADR-006/016).

전화번호 없는 MOIS place 후보 발굴(`find_place_phone_candidates`) + 외부 lookup
전화번호 보강(`apply_place_phone_enrichment` — detail.phones 갱신 + enrichment
source_link)을 실 PostGIS에서 검증한다.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.enrichment import (
    apply_place_phone_enrichment,
    find_place_phone_candidates,
)
from kortravelmap.infra.feature_repo import get_feature_row
from kortravelmap.infra.models import FeatureRow, SourceLinkRow, SourceRecordRow
from kortravelmap.providers.mois import DATASET_KEY_BULK, PROVIDER_NAME

if TYPE_CHECKING:
    pass

pytestmark = pytest.mark.integration

_FETCHED = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
_ENTITY = "license_place"


async def _seed_place(
    session: AsyncSession, feature_id: str, entity_id: str, phones: list[str]
) -> None:
    """MOIS bulk place feature 1건 + primary source_link 적재 (phones 지정)."""
    session.add(
        FeatureRow(
            feature_id=feature_id,
            kind="place",
            name="한식당 가나다",
            category="02010100",
            detail={"place_kind": "restaurant", "phones": phones},
        )
    )
    session.add(
        SourceRecordRow(
            source_record_key=f"sr-{feature_id}",
            provider=PROVIDER_NAME,
            dataset_key=DATASET_KEY_BULK,
            source_entity_type=_ENTITY,
            source_entity_id=entity_id,
            raw_payload_hash="h",
            raw_data={},
            fetched_at=_FETCHED,
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
        )
    )
    await session.flush()


async def _enrichment_link_count(session: AsyncSession, feature_id: str) -> int:
    return int(
        (
            await session.execute(
                text(
                    "SELECT count(*) FROM provider_sync.source_links "
                    "WHERE feature_id = :f AND source_role = 'enrichment'"
                ),
                {"f": feature_id},
            )
        ).scalar_one()
    )


async def test_candidates_only_without_phone(
    migrated_session: AsyncSession,
) -> None:
    await _seed_place(migrated_session, "p-nophone", "general_restaurants::a", [])
    await _seed_place(
        migrated_session, "p-hasphone", "general_restaurants::b", ["02-1-2"]
    )
    cands = await find_place_phone_candidates(migrated_session, limit=50)
    ids = {c.feature_id for c in cands}
    assert "p-nophone" in ids
    assert "p-hasphone" not in ids
    cand = next(c for c in cands if c.feature_id == "p-nophone")
    assert cand.source_entity_id == "general_restaurants::a"


async def test_apply_enrichment_updates_phone_and_link(
    migrated_session: AsyncSession,
) -> None:
    await _seed_place(migrated_session, "p1", "general_restaurants::c1", [])
    result = await apply_place_phone_enrichment(
        migrated_session,
        feature_id="p1",
        phone="0212345678",
        enrichment_provider="kakao-local-api",
        source_entity_id="general_restaurants::c1",
        fetched_at=_FETCHED,
    )
    await migrated_session.flush()
    assert result.applied is True
    assert result.phone == "02-1234-5678"  # 정규화됨

    row = await get_feature_row(migrated_session, "p1")
    assert row is not None
    assert row["detail"]["phones"] == ["02-1234-5678"]
    # enrichment source_link 1건 생성.
    assert await _enrichment_link_count(migrated_session, "p1") == 1


async def test_apply_enrichment_duplicate_skips(
    migrated_session: AsyncSession,
) -> None:
    await _seed_place(
        migrated_session, "p2", "general_restaurants::c2", ["02-1234-5678"]
    )
    result = await apply_place_phone_enrichment(
        migrated_session,
        feature_id="p2",
        phone="02-1234-5678",
        enrichment_provider="kakao-local-api",
        source_entity_id="general_restaurants::c2",
        fetched_at=_FETCHED,
    )
    assert result.applied is False
    assert result.reason == "duplicate"
    assert await _enrichment_link_count(migrated_session, "p2") == 0


async def test_apply_enrichment_invalid_phone(
    migrated_session: AsyncSession,
) -> None:
    await _seed_place(migrated_session, "p3", "general_restaurants::c3", [])
    result = await apply_place_phone_enrichment(
        migrated_session,
        feature_id="p3",
        phone="not-a-phone",
        enrichment_provider="kakao-local-api",
        source_entity_id="general_restaurants::c3",
        fetched_at=_FETCHED,
    )
    assert result.applied is False
    assert result.reason == "invalid_phone"


async def test_apply_enrichment_feature_not_found(
    migrated_session: AsyncSession,
) -> None:
    result = await apply_place_phone_enrichment(
        migrated_session,
        feature_id="missing",
        phone="0212345678",
        enrichment_provider="kakao-local-api",
        source_entity_id="x::y",
        fetched_at=_FETCHED,
    )
    assert result.applied is False
    assert result.reason == "feature_not_found"


async def test_apply_enrichment_max_phones(
    migrated_session: AsyncSession,
) -> None:
    await _seed_place(
        migrated_session,
        "p4",
        "general_restaurants::c4",
        ["02-1-1", "02-2-2", "02-3-3"],
    )
    result = await apply_place_phone_enrichment(
        migrated_session,
        feature_id="p4",
        phone="0212345678",
        enrichment_provider="kakao-local-api",
        source_entity_id="general_restaurants::c4",
        fetched_at=_FETCHED,
    )
    assert result.applied is False
    assert result.reason == "max_phones"
