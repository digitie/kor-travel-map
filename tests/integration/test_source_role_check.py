"""``test_source_role_check`` — DB CHECK가 모든 ``SourceRole`` enum 값을 허용.

회귀 차단: ``source_links.ck_source_links_role`` CHECK와 DTO ``SourceRole`` enum이
어긋나면(마이그레이션 0002 → 0004로 정정한 버그) 적재 시 CHECK 위반이 난다.
본 테스트는 enum의 8개 값이 전부 INSERT 가능함을 실 DB로 보장한다.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from kortravelmap.dto._enums import SourceRole

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_KST = timezone(timedelta(hours=9))
_FETCHED = datetime(2026, 5, 29, 12, 0, tzinfo=_KST)

_PROVIDER = "test-provider-source-role"
_DATASET = "source_role_check"


async def _dataset_id(session: AsyncSession) -> int:
    """fixture 전용 catalog 행을 만들고 canonical id를 돌려준다 (T-VN-33)."""

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


async def test_all_source_role_values_pass_db_check(
    migrated_session: AsyncSession,
) -> None:
    # feature 1건 (FK 충족)
    await migrated_session.execute(
        text(
            "INSERT INTO feature.features (feature_id, kind, name, category, "
            "marker_icon, marker_color) "
            "VALUES ('sr-check-f1','place','장소','01010100','star','P-01')"
        )
    )
    await migrated_session.flush()

    dataset_id = await _dataset_id(migrated_session)

    # enum의 모든 값으로 source_link INSERT — CHECK 위반 없어야 한다.
    # (feature_id, source_entity_key)가 PK라 source entity를 role마다 새로 만든다.
    # T-VN-33 이후 entity 자연키는 (provider_dataset_id, type, id)라 entity_id를
    # i로 유일화하고, 현재 record 포인터는 source_entity_heads가 소유한다.
    for i, role in enumerate(SourceRole):
        key = f"sr-check-k-{i}"
        entity_key = f"se-check-k-{i}"
        await migrated_session.execute(
            text(
                "INSERT INTO provider_sync.source_entities "
                "(source_entity_key, provider_dataset_id, source_entity_type, "
                " source_entity_id, first_seen_at, last_seen_at) "
                "VALUES (:sek,:pdid,'e',:eid,:ts,:ts)"
            ),
            {"sek": entity_key, "pdid": dataset_id, "eid": str(i), "ts": _FETCHED},
        )
        await migrated_session.execute(
            text(
                "INSERT INTO provider_sync.source_records "
                "(source_record_key, source_entity_key, raw_data, "
                " raw_payload_hash, fetched_at) "
                "VALUES (:k,:sek,'{}'::jsonb,:h,:ts)"
            ),
            {
                "k": key,
                "sek": entity_key,
                # ck_source_records_payload_hash_canonical = ^[0-9a-f]{1,64}$
                "h": f"{i:032x}",
                "ts": _FETCHED,
            },
        )
        await migrated_session.execute(
            text(
                "INSERT INTO provider_sync.source_entity_heads "
                "(source_entity_key, current_source_record_key, observed_at) "
                "VALUES (:sek,:k,:ts)"
            ),
            {"sek": entity_key, "k": key, "ts": _FETCHED},
        )
        await migrated_session.execute(
            text(
                "INSERT INTO provider_sync.source_links "
                "(feature_id, source_entity_key, source_role, match_method, "
                " confidence) "
                "VALUES ('sr-check-f1', :sek, :role, 'natural_key', 100)"
            ),
            {"sek": entity_key, "role": role.value},
        )
        await migrated_session.flush()

    count = (
        await migrated_session.execute(
            text(
                "SELECT count(*) FROM provider_sync.source_links "
                "WHERE feature_id = 'sr-check-f1'"
            )
        )
    ).scalar_one()
    assert count == len(list(SourceRole))
