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

from krtour.map.dto._enums import SourceRole

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_KST = timezone(timedelta(hours=9))
_FETCHED = datetime(2026, 5, 29, 12, 0, tzinfo=_KST)


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

    # enum의 모든 값으로 source_link INSERT — CHECK 위반 없어야 한다.
    # (feature_id, source_record_key)가 PK라 source_record를 role마다 새로 만든다.
    # uq_source_records(provider,dataset_key,entity_type,entity_id,payload_hash)
    # 충돌 회피 위해 entity_id/payload_hash를 i로 유일화.
    for i, role in enumerate(SourceRole):
        key = f"sr-check-k-{i}"
        await migrated_session.execute(
            text(
                "INSERT INTO provider_sync.source_records "
                "(source_record_key, provider, dataset_key, source_entity_type, "
                " source_entity_id, raw_payload_hash, fetched_at) "
                "VALUES (:k,'datagokr','ds','e',:eid,:h,:ts)"
            ),
            {"k": key, "eid": str(i), "h": f"h{i}", "ts": _FETCHED},
        )
        await migrated_session.flush()
        await migrated_session.execute(
            text(
                "INSERT INTO provider_sync.source_links "
                "(feature_id, source_record_key, source_role, match_method, "
                " confidence, is_primary_source) "
                "VALUES ('sr-check-f1', :k, :role, 'natural_key', 100, false)"
            ),
            {"k": key, "role": role.value},
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
