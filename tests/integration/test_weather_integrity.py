"""T-VN-17 — feature_weather_values 무결성 제약 (alembic 0060).

semantic UNIQUE(NULLS NOT DISTINCT) + range/payload CHECK + source-record FK가
head schema에서 실제로 강제되는지, 그리고 writer(``weather_repo._INSERT_SQL``)의
ON CONFLICT 대상이 DB unique index와 정확히 일치하는지 검증한다(F-7 / ADR-072).

dedup keep-rule과 upgrade→downgrade→upgrade 왕복은
``test_weather_integrity_migration.py``(전용 stepping engine)에서 검증한다.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from kortravelmap.dto.weather import WeatherValue
from kortravelmap.infra import weather_repo

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_KST = timezone(timedelta(hours=9))
_T1 = datetime(2026, 7, 19, 9, 0, tzinfo=_KST)
_T2 = datetime(2026, 7, 19, 12, 0, tzinfo=_KST)

_IDENTITY = (
    "feature_id",
    "provider",
    "weather_domain",
    "forecast_style",
    "metric_key",
    "issued_at",
    "valid_at",
    "observed_at",
)


async def _ins_weather_feature(session: AsyncSession, fid: str) -> None:
    await session.execute(
        text(
            """
            INSERT INTO feature.features (
                feature_id, kind, name, category, status, updated_at
            )
            VALUES (:fid, 'weather', '날씨', '00000000', 'active', now())
            """
        ),
        {"fid": fid},
    )
    await session.flush()


async def _raw_weather_insert(session: AsyncSession, **overrides: object) -> None:
    params: dict[str, object] = {
        "weather_value_key": "wv_raw_1",
        "feature_id": "f_wi",
        "provider": "python-kma-api",
        "weather_domain": "kma_short_forecast",
        "forecast_style": "short",
        "metric_key": "TMP",
        "value_number": Decimal("20.0"),
        "value_text": None,
        "issued_at": _T1,
        "valid_at": _T1,
        "observed_at": None,
        "valid_from": None,
        "valid_until": None,
        "payload": "{}",
        "source_record_key": None,
    }
    params.update(overrides)
    await session.execute(
        text(
            """
            INSERT INTO feature.feature_weather_values (
                weather_value_key, feature_id, provider, weather_domain,
                forecast_style, metric_key, value_number, value_text,
                issued_at, valid_at, observed_at, valid_from, valid_until,
                payload, source_record_key
            ) VALUES (
                :weather_value_key, :feature_id, :provider, :weather_domain,
                :forecast_style, :metric_key, :value_number, :value_text,
                :issued_at, :valid_at, :observed_at, :valid_from, :valid_until,
                CAST(:payload AS jsonb), :source_record_key
            )
            """
        ),
        params,
    )


def _wv(**kw: object) -> WeatherValue:
    base: dict[str, object] = {
        "feature_id": "f_wi",
        "provider": "python-kma-api",
        "weather_domain": "kma_short_forecast",
        "forecast_style": "short",
        "timeline_bucket": "short",
        "metric_key": "TMP",
        "metric_name": "기온",
        "unit": "deg_c",
        "issued_at": _T1,
        "valid_at": _T1,
    }
    base.update(kw)
    return WeatherValue(**base)  # type: ignore[arg-type]


async def test_writer_conflict_target_matches_unique_index(
    migrated_session: AsyncSession,
) -> None:
    """writer ON CONFLICT 대상 == DB unique index 컬럼(순서까지) + NULLS NOT DISTINCT.

    단일 정본(``_WEATHER_IDENTITY_COLUMNS``)이 실제 index와 어긋나면 fast-fail.
    """
    expected_target = ", ".join(_IDENTITY)
    assert weather_repo._WEATHER_IDENTITY_COLUMNS == _IDENTITY
    assert expected_target == weather_repo._WEATHER_CONFLICT_TARGET

    rows = await migrated_session.execute(
        text(
            """
            SELECT a.attname
            FROM pg_index i
            JOIN pg_class c ON c.oid = i.indexrelid
            JOIN pg_attribute a
              ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
            WHERE c.relname = 'uq_weather_value_identity'
            ORDER BY array_position(i.indkey, a.attnum)
            """
        )
    )
    index_cols = tuple(r[0] for r in rows)
    assert index_cols == _IDENTITY

    meta = (
        await migrated_session.execute(
            text(
                """
                SELECT i.indisunique, i.indnullsnotdistinct
                FROM pg_index i
                JOIN pg_class c ON c.oid = i.indexrelid
                WHERE c.relname = 'uq_weather_value_identity'
                """
            )
        )
    ).one()
    assert meta[0] is True  # unique
    assert meta[1] is True  # NULLS NOT DISTINCT


@pytest.mark.parametrize(
    (
        "first_collected_at",
        "first_value",
        "second_collected_at",
        "second_value",
        "expected_collected_at",
        "expected_value",
        "expected_physical_update",
    ),
    [
        (_T1, "20.0", _T2, "25.0", _T2, "25.0", True),
        (_T2, "25.0", _T1, "20.0", _T2, "25.0", False),
    ],
    ids=("in-order-t1-to-t2", "late-backfill-t2-to-t1"),
)
async def test_semantic_upsert_keeps_latest_collected_at(
    migrated_session: AsyncSession,
    first_collected_at: datetime,
    first_value: str,
    second_collected_at: datetime,
    second_value: str,
    expected_collected_at: datetime,
    expected_value: str,
    expected_physical_update: bool,
) -> None:
    """정방향 수집은 갱신하고 늦은 provider backfill은 현재값을 되돌리지 않는다."""
    await _ins_weather_feature(migrated_session, "f_wi")
    first_source_key = f"SOURCE_{first_collected_at.hour}"
    first_source_name = f"원천 {first_collected_at.hour}시"
    second_source_key = f"SOURCE_{second_collected_at.hour}"
    second_source_name = f"원천 {second_collected_at.hour}시"
    assert (
        await weather_repo.load_weather_values(
            migrated_session,
            [
                _wv(
                    value_number=Decimal(first_value),
                    collected_at=first_collected_at,
                    source_metric_key=first_source_key,
                    source_metric_name=first_source_name,
                )
            ],
        )
        == 1
    )
    first_ctid = await migrated_session.scalar(
        text(
            "SELECT ctid::text FROM feature.feature_weather_values "
            "WHERE feature_id = 'f_wi'"
        )
    )
    assert (
        await weather_repo.load_weather_values(
            migrated_session,
            [
                _wv(
                    value_number=Decimal(second_value),
                    collected_at=second_collected_at,
                    source_metric_key=second_source_key,
                    source_metric_name=second_source_name,
                )
            ],
        )
        == 1
    )
    row = (
        await migrated_session.execute(
            text(
                "SELECT count(*) AS n, max(value_number) AS v, "
                "max(collected_at) AS collected_at, max(ctid::text) AS ctid, "
                "max(source_metric_key) AS source_metric_key, "
                "max(source_metric_name) AS source_metric_name "
                "FROM feature.feature_weather_values WHERE feature_id = 'f_wi'"
            )
        )
    ).one()
    assert row.n == 1
    assert row.v == Decimal(expected_value)
    assert row.collected_at == expected_collected_at
    assert row.source_metric_key == f"SOURCE_{expected_collected_at.hour}"
    assert row.source_metric_name == f"원천 {expected_collected_at.hour}시"
    assert (row.ctid != first_ctid) is expected_physical_update


async def test_semantic_upsert_tie_updates_changed_value_but_identical_replay_is_noop(
    migrated_session: AsyncSession,
) -> None:
    """동률은 뒤의 실제 변경이 이기고 완전히 같은 재적재는 heap을 갱신하지 않는다."""
    await _ins_weather_feature(migrated_session, "f_wi")
    original = _wv(
        value_number=Decimal("20.0"),
        collected_at=_T2,
        source_metric_key="TMP_OLD",
        source_metric_name="기온 구명칭",
    )
    correction = _wv(
        value_number=Decimal("20.0"),
        collected_at=_T2,
        source_metric_key="TMP_NEW",
        source_metric_name="기온 신명칭",
    )

    assert await weather_repo.load_weather_values(migrated_session, [original]) == 1
    original_ctid = await migrated_session.scalar(
        text(
            "SELECT ctid::text FROM feature.feature_weather_values "
            "WHERE feature_id = 'f_wi'"
        )
    )

    assert await weather_repo.load_weather_values(migrated_session, [correction]) == 1
    corrected = (
        await migrated_session.execute(
            text(
                "SELECT ctid::text AS ctid, value_number, collected_at, "
                "source_metric_key, source_metric_name "
                "FROM feature.feature_weather_values WHERE feature_id = 'f_wi'"
            )
        )
    ).one()
    assert corrected.ctid != original_ctid
    assert corrected.value_number == Decimal("20.0")
    assert corrected.collected_at == _T2
    assert corrected.source_metric_key == "TMP_NEW"
    assert corrected.source_metric_name == "기온 신명칭"

    assert await weather_repo.load_weather_values(migrated_session, [correction]) == 1
    replay_ctid = await migrated_session.scalar(
        text(
            "SELECT ctid::text FROM feature.feature_weather_values "
            "WHERE feature_id = 'f_wi'"
        )
    )
    assert replay_ctid == corrected.ctid


async def test_semantic_unique_rejects_duplicate_tuple_with_different_key(
    migrated_session: AsyncSession,
) -> None:
    """다른 weather_value_key라도 같은 semantic tuple이면 unique 위반 (tz-표기 구멍 봉인)."""
    await _ins_weather_feature(migrated_session, "f_wi")
    await _raw_weather_insert(migrated_session, weather_value_key="wv_a")
    await migrated_session.flush()
    with pytest.raises(IntegrityError):
        async with migrated_session.begin_nested():
            await _raw_weather_insert(migrated_session, weather_value_key="wv_b")


async def test_semantic_unique_nulls_not_distinct(
    migrated_session: AsyncSession,
) -> None:
    """시간축이 모두 NULL이어도 NULLS NOT DISTINCT로 같은 tuple은 중복 불가."""
    await _ins_weather_feature(migrated_session, "f_wi")
    await _raw_weather_insert(
        migrated_session,
        weather_value_key="wv_null_a",
        issued_at=None,
        valid_at=None,
        observed_at=None,
    )
    await migrated_session.flush()
    with pytest.raises(IntegrityError):
        async with migrated_session.begin_nested():
            await _raw_weather_insert(
                migrated_session,
                weather_value_key="wv_null_b",
                issued_at=None,
                valid_at=None,
                observed_at=None,
            )


async def test_reversed_range_rejected(migrated_session: AsyncSession) -> None:
    """valid_from > valid_until은 ck_weather_value_range로 거부된다."""
    await _ins_weather_feature(migrated_session, "f_wi")
    with pytest.raises(IntegrityError):
        async with migrated_session.begin_nested():
            await _raw_weather_insert(
                migrated_session,
                weather_value_key="wv_bad_range",
                valid_from=_T2,
                valid_until=_T1,
            )
    # 정상 순서는 통과.
    await _raw_weather_insert(
        migrated_session,
        weather_value_key="wv_ok_range",
        valid_from=_T1,
        valid_until=_T2,
    )
    await migrated_session.flush()


async def test_payload_non_object_rejected(migrated_session: AsyncSession) -> None:
    """payload가 object가 아니면 ck_weather_value_payload_object로 거부된다."""
    await _ins_weather_feature(migrated_session, "f_wi")
    with pytest.raises(IntegrityError):
        async with migrated_session.begin_nested():
            await _raw_weather_insert(
                migrated_session,
                weather_value_key="wv_bad_payload",
                payload="[1, 2, 3]",
            )


async def test_source_record_fk_rejects_orphan_and_sets_null_on_delete(
    migrated_session: AsyncSession,
) -> None:
    """source_record_key는 존재하는 source_record만 허용하고, 삭제 시 NULL로 떨어진다."""
    await _ins_weather_feature(migrated_session, "f_wi")

    # 없는 source_record_key → FK 위반.
    with pytest.raises(IntegrityError):
        async with migrated_session.begin_nested():
            await _raw_weather_insert(
                migrated_session,
                weather_value_key="wv_orphan",
                source_record_key="sr_missing",
            )

    # source_entity(FK 부모) → source_record를 만들고 참조 → 통과.
    await migrated_session.execute(
        text(
            """
            INSERT INTO provider_sync.source_entities (
                source_entity_key, provider_dataset_id, source_entity_type,
                source_entity_id, first_seen_at, last_seen_at
            )
            SELECT
                'se_ok', provider_dataset_id, 'weather',
                'grid-1', :ts, :ts
            FROM provider_sync.provider_datasets
            WHERE provider = 'python-kma-api' AND dataset_key = 'kma_short_forecast'
            """
        ),
        {"ts": _T1},
    )
    await migrated_session.execute(
        text(
            """
            INSERT INTO provider_sync.source_records (
                source_record_key, source_entity_key, raw_payload_hash, fetched_at
            ) VALUES (
                'sr_ok', 'se_ok', md5('hash-1'), :ts
            )
            """
        ),
        {"ts": _T1},
    )
    await _raw_weather_insert(
        migrated_session,
        weather_value_key="wv_linked",
        source_record_key="sr_ok",
    )
    await migrated_session.flush()

    # source_record 삭제 → ON DELETE SET NULL.
    await migrated_session.execute(
        text("DELETE FROM provider_sync.source_records WHERE source_record_key = 'sr_ok'")
    )
    await migrated_session.flush()
    linked = (
        await migrated_session.execute(
            text(
                "SELECT source_record_key FROM feature.feature_weather_values "
                "WHERE weather_value_key = 'wv_linked'"
            )
        )
    ).scalar_one()
    assert linked is None
