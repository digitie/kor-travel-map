"""notice 계보 key 저장 계약 (T-VN-37, ADR-087).

이 파일이 있는 이유: 저장 경로가 **한 번도 실행되지 않은 채** 나간 적이 있다.
마이그레이션 backfill만 검증하고 writer를 돌려보지 않아서, 같은 bind 파라미터를
INSERT 값(varchar)과 CASE(text) 양쪽에 써서 생긴 ``AmbiguousParameterError``를
적대 리뷰가 잡을 때까지 몰랐다. 그 오류는 notice뿐 아니라 **모든 provider의 모든
source record 쓰기**를 죽인다.

그래서 여기서 고정하는 것은 세 가지다:

1. writer가 실제로 실행되고 notice scope에 값을 남긴다.
2. notice scope **밖**은 NULL이다(그러지 않으면 CASE의 ELSE가 73만 행에
   ``source_entity_id`` 사본을 남기고, backfill이 채운 집합과도 어긋난다).
3. 저장값이 read가 재계산하는 값과 **같다** — 세 벌(read/writer/migration)로
   흩어진 같은 CASE가 갈리면 공개 표면과 admin/reconcile이 다른 계보로 묶인다.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from kortravelmap.infra import feature_repo

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_KST = timezone(timedelta(hours=9))
_NOW = datetime(2026, 8, 6, 12, 0, tzinfo=_KST)


async def _insert_record(
    session: AsyncSession,
    *,
    key: str,
    provider: str,
    dataset_key: str,
    source_entity_type: str,
    raw_data: str,
) -> str | None:
    """프로덕션 writer SQL을 **그대로** 실행하고 저장된 계보 key를 돌려준다."""
    await session.execute(
        text(
            "INSERT INTO provider_sync.source_entities ("
            " source_entity_key, provider, dataset_key, source_entity_type,"
            " source_entity_id, first_seen_at, last_seen_at)"
            " VALUES (:k, :p, :d, :t, :i, :now, :now)"
            " ON CONFLICT (source_entity_key) DO NOTHING"
        ),
        {
            "k": f"se-{key}", "p": provider, "d": dataset_key,
            "t": source_entity_type, "i": f"ENT-{key}", "now": _NOW,
        },
    )
    await session.execute(
        text(feature_repo._UPSERT_SOURCE_RECORD_SQL),
        {
            "source_record_key": key,
            "source_entity_key": f"se-{key}",
            "provider": provider,
            "dataset_key": dataset_key,
            "source_entity_type": source_entity_type,
            "source_entity_id": f"ENT-{key}",
            "source_version": None,
            "raw_name": "n",
            "raw_address": None,
            "raw_longitude": None,
            "raw_latitude": None,
            "raw_data": raw_data,
            "raw_payload_hash": f"h-{key}",
            "fetched_at": _NOW,
            "imported_at": _NOW,
            "expires_at": None,
        },
    )
    return (
        await session.execute(
            text(
                "SELECT lineage_key FROM provider_sync.source_records"
                " WHERE source_record_key = :k"
            ),
            {"k": key},
        )
    ).scalar_one()


async def test_writer_stores_lineage_key_for_notice_scope(
    migrated_session: AsyncSession,
) -> None:
    """writer가 **실제로 실행되고** notice scope에 계보 key를 남긴다."""
    stored = await _insert_record(
        migrated_session,
        key="lin-krex",
        provider="python-krex-api",
        dataset_key="krex_traffic_notices",
        source_entity_type="traffic_notice",
        raw_data='{"occurred_date": "2026-08-01", "route_no": "1", "point_name": "p"}',
    )
    assert stored == "2026-08-01::1::p"


async def test_writer_leaves_non_notice_scope_null(
    migrated_session: AsyncSession,
) -> None:
    """notice scope 밖은 NULL — CASE의 ELSE가 전 record에 사본을 남기면 안 된다."""
    stored = await _insert_record(
        migrated_session,
        key="lin-mois",
        provider="python-mois-api",
        dataset_key="mois_licenses",
        source_entity_type="license_place",
        raw_data='{"a": 1}',
    )
    assert stored is None


async def test_stored_lineage_key_equals_read_time_recomputation(
    migrated_session: AsyncSession,
) -> None:
    """저장값 == read가 재계산하는 값.

    read/writer/migration에 같은 CASE가 세 벌 있다. 갈리면 공개 표면과
    admin/reconcile이 서로 다른 계보로 묶이고, 아무도 알아채지 못한다.
    """
    await _insert_record(
        migrated_session,
        key="lin-cmp",
        provider="python-krex-api",
        dataset_key="krex_traffic_notices",
        source_entity_type="traffic_notice",
        raw_data='{"occurred_date": "2026-08-02", "route_no": "9", "direction": "북"}',
    )
    recomputed_sql = feature_repo._notice_lineage_sql("sr")
    mismatched = (
        await migrated_session.execute(
            text(
                "SELECT count(*) FROM provider_sync.source_records AS sr"
                " WHERE sr.lineage_key IS NOT NULL"
                f"   AND sr.lineage_key IS DISTINCT FROM ({recomputed_sql})"
            )
        )
    ).scalar_one()
    assert mismatched == 0
