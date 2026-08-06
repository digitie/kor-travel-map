"""notice 계보 key 저장 계약 (T-VN-37, ADR-087).

이 파일이 있는 이유: 저장 경로가 **한 번도 실행되지 않은 채** 나간 적이 있다.
마이그레이션 backfill만 검증하고 writer를 돌려보지 않아서, 같은 bind 파라미터를
INSERT 값(varchar)과 CASE(text) 양쪽에 써서 생긴 ``AmbiguousParameterError``를
적대 리뷰가 잡을 때까지 몰랐다. 그 오류는 notice뿐 아니라 **모든 provider의 모든
source record 쓰기**를 죽인다.

계보 key의 정본은 이제 **DB**에 있다(0088):
``provider_sync.source_record_lineage_key`` 함수를 BEFORE INSERT/UPDATE 트리거가
호출해 컬럼을 채우고, 애플리케이션은 그 컬럼을 읽기만 한다. 고정하는 것:

1. writer SQL이 ``lineage_key``를 **주지 않아도** 트리거가 채운다(NOT NULL).
2. KREX/KMA 전용 계보 규칙과 그 밖의 fallback이 각각 맞는 값을 만든다.
3. DB 정본 == 애플리케이션이 H35 고정 세대 replay에 쓰는 재계산 식. 갈리면
   리허설이 재생하는 표면이 현행 표면과 다른 계보로 묶인다. 값이 *틀린* 경우는
   NULL과 달리 fallback으로 막을 수 없다(값은 write-once다).
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
) -> str:
    """프로덕션 writer SQL을 **그대로** 실행하고 트리거가 넣은 계보 key를 읽는다."""
    await session.execute(
        text(
            "INSERT INTO provider_sync.source_entities ("
            " source_entity_key, provider, dataset_key, source_entity_type,"
            " source_entity_id, first_seen_at, last_seen_at)"
            " VALUES (:k, :p, :d, :t, :i, :now, :now)"
            " ON CONFLICT (source_entity_key) DO NOTHING"
        ),
        {
            "k": f"se-{key}",
            "p": provider,
            "d": dataset_key,
            "t": source_entity_type,
            "i": f"ENT-{key}",
            "now": _NOW,
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


@pytest.mark.parametrize(
    ("label", "provider", "dataset_key", "source_entity_type", "raw_data", "expected"),
    [
        (
            "krex",
            "python-krex-api",
            "krex_traffic_notices",
            "traffic_notice",
            '{"occurred_date": "2026-08-01", "route_no": "1", "point_name": "p"}',
            "2026-08-01::1::p",
        ),
        (
            # 대소문자·공백 정규화가 계보를 가른다 — 같은 사건이 두 계보가 되면
            # 밀려난 공지가 되살아난다.
            "krex-normalized",
            "python-krex-api",
            "krex_traffic_notices",
            "traffic_notice",
            '{"occurred_date": " 2026-08-01 ", "route_no": "AB", "point_name": "Foo Bar"}',
            "2026-08-01::ab::foo bar",
        ),
        (
            "kma-phenomenon",
            "python-kma-api",
            "kma_weather_alerts",
            "weather_alert",
            '{"region_code": "L1010000", "phenomenon": "호우"}',
            "L1010000::호우",
        ),
        (
            # phenomenon이 없으면 alert_type으로 물러난다. 이 분기는 prod 데이터에
            # KMA 특보가 아직 0행이라 실데이터로는 한 번도 실행된 적이 없다.
            "kma-alert-type-fallback",
            "python-kma-api",
            "kma_weather_alerts",
            "weather_alert",
            '{"region_code": "L1010000", "alert_type": "강풍"}',
            "L1010000::강풍",
        ),
        (
            # notice scope 밖도 NULL이 아니다 — ELSE 분기가 source_entity_id다.
            # NULL을 허용하면 read가 재계산 fallback을 껴야 하고 인덱스가 죽는다.
            "non-notice",
            "python-mois-api",
            "mois_licenses",
            "license_place",
            '{"a": 1}',
            "ENT-lin-non-notice",
        ),
        (
            # 계보 구성요소가 전부 비면 entity id로 물러난다.
            "krex-empty",
            "python-krex-api",
            "krex_traffic_notices",
            "traffic_notice",
            '{"occurred_date": "  ", "route_no": ""}',
            "ENT-lin-krex-empty",
        ),
    ],
)
async def test_writer_stores_lineage_key(
    migrated_session: AsyncSession,
    label: str,
    provider: str,
    dataset_key: str,
    source_entity_type: str,
    raw_data: str,
    expected: str,
) -> None:
    """writer가 실제로 실행되고, 트리거가 모든 scope에 맞는 계보 key를 남긴다."""
    stored = await _insert_record(
        migrated_session,
        key=f"lin-{label}",
        provider=provider,
        dataset_key=dataset_key,
        source_entity_type=source_entity_type,
        raw_data=raw_data,
    )
    assert stored == expected


async def test_writer_does_not_supply_lineage_key(
    migrated_session: AsyncSession,
) -> None:
    """writer SQL은 ``lineage_key``를 쓰지 않는다 — 파생의 정본은 DB다.

    애플리케이션이 값을 넣기 시작하면 DB 함수와 갈릴 수 있고, 그 불일치는 어떤
    제약도 잡아주지 못한다.
    """
    assert "lineage_key" not in feature_repo._UPSERT_SOURCE_RECORD_SQL


async def test_lineage_key_column_is_not_null(
    migrated_session: AsyncSession,
) -> None:
    """NOT NULL이 살아 있어야 read가 컬럼 등식 하나만 쓰고 인덱스가 쓰인다."""
    nullable = (
        await migrated_session.execute(
            text(
                "SELECT is_nullable FROM information_schema.columns"
                " WHERE table_schema = 'provider_sync'"
                "   AND table_name = 'source_records'"
                "   AND column_name = 'lineage_key'"
            )
        )
    ).scalar_one()
    assert nullable == "NO"


async def test_trigger_recomputes_lineage_key_when_payload_changes(
    migrated_session: AsyncSession,
) -> None:
    """``raw_data``가 바뀌면 계보도 따라간다 — 값이 낡은 채 남지 않는다."""
    await _insert_record(
        migrated_session,
        key="lin-repay",
        provider="python-krex-api",
        dataset_key="krex_traffic_notices",
        source_entity_type="traffic_notice",
        raw_data='{"occurred_date": "2026-08-03", "route_no": "7"}',
    )
    await migrated_session.execute(
        text(
            "UPDATE provider_sync.source_records"
            " SET raw_data = CAST(:d AS jsonb) WHERE source_record_key = :k"
        ),
        {"d": '{"occurred_date": "2026-08-04", "route_no": "8"}', "k": "lin-repay"},
    )
    updated = (
        await migrated_session.execute(
            text(
                "SELECT lineage_key FROM provider_sync.source_records"
                " WHERE source_record_key = :k"
            ),
            {"k": "lin-repay"},
        )
    ).scalar_one()
    assert updated == "2026-08-04::8"


async def test_direct_write_to_lineage_key_is_corrected(
    migrated_session: AsyncSession,
) -> None:
    """파생 컬럼을 **직접** 써도 트리거가 되돌린다.

    트리거의 ``UPDATE OF`` 목록에 ``lineage_key`` 자신이 없으면 이 문장이 트리거를
    타지 않아 거짓 값이 그대로 남고, 밀려난 공지가 공개 표면에 되살아난다.
    NOT NULL은 "비어 있지 않다"만 보장하지 "맞다"를 보장하지 않는다.
    """
    await _insert_record(
        migrated_session,
        key="lin-tamper",
        provider="python-krex-api",
        dataset_key="krex_traffic_notices",
        source_entity_type="traffic_notice",
        raw_data='{"occurred_date": "2026-08-05", "route_no": "3"}',
    )
    await migrated_session.execute(
        text(
            "UPDATE provider_sync.source_records SET lineage_key = 'TAMPERED'"
            " WHERE source_record_key = :k"
        ),
        {"k": "lin-tamper"},
    )
    stored = (
        await migrated_session.execute(
            text(
                "SELECT lineage_key FROM provider_sync.source_records"
                " WHERE source_record_key = :k"
            ),
            {"k": "lin-tamper"},
        )
    ).scalar_one()
    assert stored == "2026-08-05::3"


async def test_hot_upsert_path_does_not_fire_the_trigger(
    migrated_session: AsyncSession,
) -> None:
    """재관측(``last_seen_at``만 갱신)은 트리거를 타지 않고 값도 그대로다.

    타면 provider 폴링마다 전 record가 재계산된다.
    """
    await _insert_record(
        migrated_session,
        key="lin-hot",
        provider="python-krex-api",
        dataset_key="krex_traffic_notices",
        source_entity_type="traffic_notice",
        raw_data='{"occurred_date": "2026-08-06", "route_no": "4"}',
    )
    before = (
        await migrated_session.execute(
            text(
                "SELECT xmin::text, lineage_key FROM provider_sync.source_records"
                " WHERE source_record_key = :k"
            ),
            {"k": "lin-hot"},
        )
    ).one()
    await migrated_session.execute(
        text(
            "UPDATE provider_sync.source_records"
            " SET last_seen_at = last_seen_at + interval '1 second'"
            " WHERE source_record_key = :k"
        ),
        {"k": "lin-hot"},
    )
    after = (
        await migrated_session.execute(
            text(
                "SELECT lineage_key FROM provider_sync.source_records"
                " WHERE source_record_key = :k"
            ),
            {"k": "lin-hot"},
        )
    ).scalar_one()
    assert after == before.lineage_key == "2026-08-06::4"

    trigger_columns = (
        await migrated_session.execute(
            text(
                "SELECT count(*) FROM information_schema.triggered_update_columns"
                " WHERE trigger_schema = 'provider_sync'"
                "   AND trigger_name = 'trg_source_record_lineage_key'"
                "   AND event_object_column = 'last_seen_at'"
            )
        )
    ).scalar_one()
    assert trigger_columns == 0


async def test_db_lineage_function_matches_frozen_replay_expression(
    migrated_session: AsyncSession,
) -> None:
    """DB 정본 == H35 고정 세대 replay가 쓰는 재계산 식 (전 행 대조).

    replay는 컬럼이 없던 0079 세대를 재생하므로 애플리케이션 식을 쓴다. 두 벌이
    갈리면 리허설이 재생하는 표면이 현행 표면과 다른 계보로 묶인다.
    """
    for label, provider, dataset_key, entity_type, raw in (
        ("k", "python-krex-api", "krex_traffic_notices", "traffic_notice",
         '{"occurred_date": "2026-08-02", "route_no": "9", "direction": "북"}'),
        ("w", "python-kma-api", "kma_weather_alerts", "weather_alert",
         '{"region_code": "L1010000", "alert_type": "강풍"}'),
        ("o", "python-mois-api", "mois_licenses", "license_place", "{}"),
    ):
        await _insert_record(
            migrated_session,
            key=f"lin-fn-{label}",
            provider=provider,
            dataset_key=dataset_key,
            source_entity_type=entity_type,
            raw_data=raw,
        )
    recomputed_sql = feature_repo._notice_lineage_sql("sr")
    total, mismatched = (
        await migrated_session.execute(
            text(
                "SELECT count(*), count(*) FILTER (WHERE"
                "   provider_sync.source_record_lineage_key(sr)"
                f"     IS DISTINCT FROM ({recomputed_sql})"
                "   OR sr.lineage_key"
                "     IS DISTINCT FROM provider_sync.source_record_lineage_key(sr))"
                " FROM provider_sync.source_records AS sr"
            )
        )
    ).one()
    assert total > 0, "대조할 record가 없으면 이 테스트는 공허하다"
    assert mismatched == 0
