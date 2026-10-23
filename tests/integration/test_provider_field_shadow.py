"""ADR115 shadow만 쓰며 R1 값 원문과 R2 검증 head를 분리한다."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.dto.provider_field_presence import ProviderFieldPresence
from kortravelmap.infra.provider_field_candidates import (
    arm_provider_field_shadow,
    capture_provider_field_candidates,
)
from tests.integration.test_tvn36_override_lineage_spine import _seed_feature_source

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration

_FIELDS = [
    {
        "field_path": "core.name",
        "provider_rank": 10,
        "omitted_policy": "carry_forward",
        "null_policy": "value",
    },
    {
        "field_path": "place.biz_number",
        "provider_rank": 10,
        "omitted_policy": "carry_forward",
        "null_policy": "remove",
    },
]


async def _seed(session: AsyncSession) -> tuple[str, int]:
    feature_id, dataset_id = await _seed_feature_source(session)
    await session.execute(
        text("""
        CALL feature.register_provider_field_shadow_policy(
            1,:dataset,'fixture-v1',CAST(:fields AS jsonb)
        )
    """),
        {"dataset": dataset_id, "fields": json.dumps(_FIELDS)},
    )
    return feature_id, dataset_id


async def _capture(
    session: AsyncSession,
    feature_id: str,
    dataset_id: int,
    record: str,
    values: dict[str, object],
    *,
    proven: bool = True,
):
    return await capture_provider_field_candidates(
        session,
        feature_id=feature_id,
        dataset_id=dataset_id,
        entity_key="tvn36-lineage-entity",
        record_key=record,
        values=json.dumps(values),
        geometry_wkt="{}",
        presence=ProviderFieldPresence(
            normalizer_revision="fixture-v1", supplied_fields=frozenset(values)
        )
        if proven
        else None,
    )


async def _next_head(session: AsyncSession) -> None:
    await session.execute(
        text("""
        INSERT INTO provider_sync.source_records(
            source_record_key,source_entity_key,raw_data,raw_payload_hash,fetched_at
        ) VALUES ('shadow-r2','tvn36-lineage-entity','{"name":"second"}',:hash,now());
    """),
        {"hash": "c" * 64},
    )
    await session.execute(
        text("""
        UPDATE provider_sync.source_entity_heads SET current_source_record_key='shadow-r2',
            observed_at=observed_at + interval '1 second'
        WHERE source_entity_key='tvn36-lineage-entity'
    """)
    )


async def test_explicit_omission_carries_original_value_to_new_validated_head(
    migrated_session: AsyncSession,
) -> None:
    session = migrated_session
    feature_id, dataset_id = await _seed(session)
    arm_provider_field_shadow(session, 1)
    first = await _capture(
        session,
        feature_id,
        dataset_id,
        "tvn36-lineage-record",
        {"core.name": "first", "place.biz_number": "123"},
    )
    assert first.field_count == 2
    assert first.unresolved_count == 0
    await _next_head(session)
    second = await _capture(session, feature_id, dataset_id, "shadow-r2", {"core.name": "second"})
    assert second.unresolved_count == 0
    rows = (
        (
            await session.execute(
                text("""
        SELECT field_path,value_json,value_source_record_key,validated_source_record_key,
               availability,reason FROM feature.provider_field_shadow_candidates
        WHERE feature_id=CAST(:feature AS uuid) ORDER BY field_path
    """),
                {"feature": feature_id},
            )
        )
        .mappings()
        .all()
    )
    assert rows[0]["value_source_record_key"] == "shadow-r2"
    assert rows[1]["value_json"] == "123"
    assert rows[1]["value_source_record_key"] == "tvn36-lineage-record"
    assert rows[1]["validated_source_record_key"] == "shadow-r2"
    assert rows[1]["reason"] == "omitted_carry"
    # shadow는 기존 effective name을 고치지 않는다.
    assert (
        await session.scalar(
            text("SELECT name FROM feature.features WHERE feature_id=CAST(:id AS uuid)"),
            {"id": feature_id},
        )
        == "tvn36-lineage-place"
    )


async def test_explicit_null_removes_candidate_but_not_native_effective(
    migrated_session: AsyncSession,
) -> None:
    session = migrated_session
    feature_id, dataset_id = await _seed(session)
    arm_provider_field_shadow(session, 1)
    await _capture(
        session,
        feature_id,
        dataset_id,
        "tvn36-lineage-record",
        {"core.name": "first", "place.biz_number": "123"},
    )
    await _next_head(session)
    await _capture(
        session,
        feature_id,
        dataset_id,
        "shadow-r2",
        {"core.name": "second", "place.biz_number": None},
    )
    row = (
        (
            await session.execute(
                text("""
        SELECT value_json,availability,reason,value_source_record_key
        FROM feature.provider_field_shadow_candidates WHERE field_path='place.biz_number'
    """)
            )
        )
        .mappings()
        .one()
    )
    assert dict(row) == {
        "value_json": None,
        "availability": "removed",
        "reason": "explicit_null",
        "value_source_record_key": "shadow-r2",
    }


async def test_missing_presence_is_unresolved_not_explicit_dto_null(
    migrated_session: AsyncSession,
) -> None:
    session = migrated_session
    feature_id, dataset_id = await _seed(session)
    arm_provider_field_shadow(session, 1)
    result = await _capture(
        session,
        feature_id,
        dataset_id,
        "tvn36-lineage-record",
        {"core.name": "first", "place.biz_number": None},
        proven=False,
    )
    assert result.field_count == result.unresolved_count == 2
    assert (
        await session.execute(
            text("SELECT DISTINCT reason FROM feature.provider_field_shadow_candidates")
        )
    ).scalars().all() == ["presence_unknown"]


async def test_runtime_can_only_use_typed_recorder_and_cannot_mutate_shadow_tables(
    migrated_session: AsyncSession,
) -> None:
    session = migrated_session
    feature_id, dataset_id = await _seed(session)
    arm_provider_field_shadow(session, 1)
    async with session.begin_nested():
        await session.execute(text("SET LOCAL ROLE ktm_feature_runtime"))
        result = await _capture(
            session,
            feature_id,
            dataset_id,
            "tvn36-lineage-record",
            {"core.name": "first", "place.biz_number": "123"},
        )
        assert result.unresolved_count == 0
        # 성공 savepoint는 SET LOCAL을 보존하므로 다음 정책 검사는 명시적으로 role을 복구한다.
    await session.execute(text("SET LOCAL ROLE ktm_feature_schema_owner"))
    for table in ("provider_field_shadow_candidates", "provider_field_shadow_policies"):
        with pytest.raises(DBAPIError, match="permission denied"):
            await _delete_as_runtime(session, table)


async def test_used_policy_cannot_be_changed_or_extended(
    migrated_session: AsyncSession,
) -> None:
    session = migrated_session
    feature_id, dataset_id = await _seed(session)
    arm_provider_field_shadow(session, 1)
    await _capture(
        session,
        feature_id,
        dataset_id,
        "tvn36-lineage-record",
        {"core.name": "first", "place.biz_number": "123"},
    )
    with pytest.raises(DBAPIError, match="immutable"):
        async with session.begin_nested():
            await session.execute(
                text(
                    "UPDATE feature.provider_field_shadow_policies "
                    "SET normalizer_revision='changed'"
                )
            )


async def test_old_source_record_is_not_accepted_as_current_head(
    migrated_session: AsyncSession,
) -> None:
    session = migrated_session
    feature_id, dataset_id = await _seed(session)
    arm_provider_field_shadow(session, 1)
    await _capture(
        session,
        feature_id,
        dataset_id,
        "tvn36-lineage-record",
        {"core.name": "first", "place.biz_number": "123"},
    )
    await _next_head(session)
    with pytest.raises(DBAPIError, match="current active source"):
        async with session.begin_nested():
            await _capture(
                session,
                feature_id,
                dataset_id,
                "tvn36-lineage-record",
                {"core.name": "forged", "place.biz_number": "999"},
            )
    assert (
        await session.scalar(
            text("""
        SELECT value_json FROM feature.provider_field_shadow_candidates WHERE field_path='core.name'
    """)
        )
        == "first"
    )


async def _delete_as_runtime(session: AsyncSession, table: str) -> None:
    async with session.begin_nested():
        await session.execute(text("SET LOCAL ROLE ktm_feature_runtime"))
        await session.execute(text(f"DELETE FROM feature.{table}"))


async def _register(
    session: AsyncSession, dataset_id: int, fields: object, *, revision: int = 1
) -> None:
    await session.execute(
        text("""CALL feature.register_provider_field_shadow_policy(
            :revision,:dataset,'fixture-v1',CAST(:fields AS jsonb))"""),
        {"revision": revision, "dataset": dataset_id, "fields": json.dumps(fields)},
    )


async def test_policy_fieldset_is_atomic_canonical_and_immutable_before_first_capture(
    migrated_session: AsyncSession,
) -> None:
    session = migrated_session
    _, dataset_id = await _seed(session)
    # 호출 순서만 다른 같은 fieldset은 새 행/버전 없이 동일하게 재사용된다.
    await _register(session, dataset_id, list(reversed(_FIELDS)))
    assert (
        await session.scalar(
            text(
                "SELECT count(*) FROM feature.provider_field_shadow_policies "
                "WHERE provider_dataset_id=:dataset"
            ),
            {"dataset": dataset_id},
        )
        == 1
    )
    for fields in (_FIELDS[:1], [*_FIELDS, {**_FIELDS[0], "provider_rank": 20}]):
        with pytest.raises(DBAPIError):
            async with session.begin_nested():
                await _register(session, dataset_id, fields)
    for statement in (
        "UPDATE feature.provider_field_shadow_policies SET fields='[]'::jsonb",
        "DELETE FROM feature.provider_field_shadow_policies",
    ):
        with pytest.raises(DBAPIError, match="immutable"):
            async with session.begin_nested():
                await session.execute(text(statement))
    assert (
        await session.scalar(
            text(
                "SELECT fields FROM feature.provider_field_shadow_policies "
                "WHERE provider_dataset_id=:dataset"
            ),
            {"dataset": dataset_id},
        )
        == _FIELDS
    )


@pytest.mark.parametrize(
    "fields",
    [
        [],
        [_FIELDS[0], _FIELDS[0]],
        [{**_FIELDS[0], "provider_rank": True}],
        [{**_FIELDS[0], "provider_rank": 1.5}],
        [{**_FIELDS[0], "provider_rank": 2147483648}],
        [{**_FIELDS[0], "null_policy": None}],
        [{**_FIELDS[0], "field_path": "core.not_registered"}],
        [{**_FIELDS[0], "unrecognized": "ignored"}],
    ],
)
async def test_invalid_policy_does_not_partially_register(
    migrated_session: AsyncSession, fields: object
) -> None:
    session = migrated_session
    _, dataset_id = await _seed_feature_source(session)
    with pytest.raises(DBAPIError):
        async with session.begin_nested():
            await _register(session, dataset_id, fields)
    assert (
        await session.scalar(
            text(
                "SELECT count(*) FROM feature.provider_field_shadow_policies "
                "WHERE provider_dataset_id=:dataset"
            ),
            {"dataset": dataset_id},
        )
        == 0
    )


async def test_runtime_cannot_register_policy_even_with_valid_input(
    migrated_session: AsyncSession,
) -> None:
    session = migrated_session
    _, dataset_id = await _seed(session)
    with pytest.raises(DBAPIError, match="permission denied"):
        await _register_as_runtime(session, dataset_id)


async def _register_as_runtime(session: AsyncSession, dataset_id: int) -> None:
    async with session.begin_nested():
        await session.execute(text("SET LOCAL ROLE ktm_feature_runtime"))
        await _register(session, dataset_id, _FIELDS, revision=2)


async def test_registration_global_first_and_repeatable_read_fail_closed(
    migrated_engine: AsyncEngine,
) -> None:
    # 실제 commit이 필요한 동시성 fixture. 고유 dataset/header만 만들고, 불변 정책을
    # 지우는 우회 DML은 쓰지 않는다. 이 소유 testcontainer DB 전체는 fixture가 회수한다.
    async with AsyncSession(migrated_engine) as setup, setup.begin():
        dataset_id = int(
            await setup.scalar(
                text("""
            INSERT INTO provider_sync.provider_datasets(
                provider,dataset_key,display_name,source_kind)
            VALUES ('shadow-fixture',:key,'shadow concurrency','manual')
            RETURNING provider_dataset_id
        """),
                {"key": uuid4().hex},
            )
        )
        await _register(setup, dataset_id, _FIELDS)

    # 등록의 첫 잠금이 global이어야 한다. waiter가 global을 기다리는 동안 정책 행을
    # 먼저 잠그면 holder의 FOR UPDATE와 교착한다. 실제 pg_stat_activity로 wait를 확인한다.
    async with AsyncSession(migrated_engine) as holder, holder.begin():
        await holder.execute(
            text("""
            SELECT pg_advisory_xact_lock(hashtextextended('feature-curation-write',0))
        """)
        )
        async with AsyncSession(migrated_engine) as waiter:
            await waiter.execute(text("SET LOCAL statement_timeout='5s'"))
            waiter_pid = await waiter.scalar(text("SELECT pg_backend_pid()"))
            task = asyncio.create_task(_register(waiter, dataset_id, _FIELDS))
            try:
                async with AsyncSession(migrated_engine) as probe:
                    async with asyncio.timeout(5):
                        while (
                            await probe.scalar(
                                text("""
                            SELECT wait_event_type FROM pg_stat_activity WHERE pid=:pid
                        """),
                                {"pid": waiter_pid},
                            )
                            != "Lock"
                        ):
                            await asyncio.sleep(0.01)
                            await probe.execute(text("SELECT pg_stat_clear_snapshot()"))
                await holder.execute(text("SET LOCAL lock_timeout='100ms'"))
                assert (
                    await holder.scalar(
                        text("""
                    SELECT policy_revision FROM feature.provider_field_shadow_policies
                    WHERE policy_revision=1 AND provider_dataset_id=:dataset FOR UPDATE
                """),
                        {"dataset": dataset_id},
                    )
                    == 1
                )
                await holder.commit()
                await task
            finally:
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                await waiter.rollback()

    # RR snapshot 이후 새 revision은 보이지 않아야 한다. 기존 revision fieldset은
    # 새 등록 뒤에도 동일하며, invisible revision을 재등록해서 승인하는 경로도 막힌다.
    async with migrated_engine.connect() as connection:
        await connection.execution_options(isolation_level="REPEATABLE READ")
        async with AsyncSession(bind=connection) as reader:
            first = await reader.scalar(
                text("""
                SELECT fields FROM feature.provider_field_shadow_policies
                WHERE provider_dataset_id=:dataset AND policy_revision=1
            """),
                {"dataset": dataset_id},
            )
            async with AsyncSession(migrated_engine) as writer, writer.begin():
                await _register(writer, dataset_id, _FIELDS[:1], revision=2)
            assert (
                await reader.scalar(
                    text("""
                SELECT fields FROM feature.provider_field_shadow_policies
                WHERE provider_dataset_id=:dataset AND policy_revision=1
            """),
                    {"dataset": dataset_id},
                )
                == first
                == _FIELDS
            )
            assert (
                await reader.scalar(
                    text("""
                SELECT fields FROM feature.provider_field_shadow_policies
                WHERE provider_dataset_id=:dataset AND policy_revision=2
            """),
                    {"dataset": dataset_id},
                )
                is None
            )
            with pytest.raises(DBAPIError) as conflict:
                async with reader.begin_nested():
                    await _register(reader, dataset_id, _FIELDS[:1], revision=2)
            assert getattr(conflict.value.orig, "sqlstate", None) == "40001"
            await reader.rollback()


@pytest.mark.parametrize("value", ["not-a-date", "2026-02-30", "tomorrow"])
async def test_invalid_calendar_date_is_not_an_approved_typed_candidate(
    migrated_session: AsyncSession, value: str
) -> None:
    session = migrated_session
    feature_id, dataset_id = await _seed_feature_source(session)
    await _register(session, dataset_id, [{**_FIELDS[0], "field_path": "place.license_date"}])
    arm_provider_field_shadow(session, 1)
    with pytest.raises(DBAPIError):
        async with session.begin_nested():
            await _capture(
                session,
                feature_id,
                dataset_id,
                "tvn36-lineage-record",
                {"place.license_date": value},
            )
    assert (
        await session.scalar(
            text("""
        SELECT count(*) FROM feature.provider_field_shadow_candidates
        WHERE provider_dataset_id=:dataset
    """),
            {"dataset": dataset_id},
        )
        == 0
    )
    accepted = await _capture(
        session,
        feature_id,
        dataset_id,
        "tvn36-lineage-record",
        {"place.license_date": "2026-10-24"},
    )
    assert accepted.unresolved_count == 0


@pytest.mark.parametrize(
    ("path", "invalid", "valid"),
    [
        ("notice.severity", 1.5, 2),
        ("notice.severity", 32768, 2),
        ("notice.valid_start_time", "2026-10-24T08:00:00", "2026-10-24T08:00:00+09:00"),
        ("notice.valid_start_time", "2026-02-30T08:00:00Z", "2026-10-24T08:00:00Z"),
    ],
)
async def test_scalar_target_cast_and_explicit_timezone_are_enforced(
    migrated_session: AsyncSession, path: str, invalid: object, valid: object
) -> None:
    session = migrated_session
    _, dataset_id = await _seed_feature_source(session)
    feature_id = str(uuid4())
    await session.execute(
        text("""
        INSERT INTO feature.features(feature_id,kind,name,category,
            lifecycle_state,publication_state,quality_state)
        VALUES(CAST(:id AS uuid),'notice','shadow notice','01010100','active','published','valid')
    """),
        {"id": feature_id},
    )
    await session.execute(
        text("""
        INSERT INTO feature.feature_notices(feature_id,kind,notice_type)
        VALUES(CAST(:id AS uuid),'notice','incident')
    """),
        {"id": feature_id},
    )
    await session.execute(
        text("""
        INSERT INTO provider_sync.source_links(feature_id,source_entity_key,
            source_role,match_method,confidence)
        VALUES(CAST(:id AS uuid),'tvn36-lineage-entity','primary','fixture',100)
    """),
        {"id": feature_id},
    )
    await _register(session, dataset_id, [{**_FIELDS[0], "field_path": path}])
    arm_provider_field_shadow(session, 1)
    with pytest.raises(DBAPIError):
        async with session.begin_nested():
            await _capture(session, feature_id, dataset_id, "tvn36-lineage-record", {path: invalid})
    accepted = await _capture(
        session, feature_id, dataset_id, "tvn36-lineage-record", {path: valid}
    )
    assert accepted.unresolved_count == 0
