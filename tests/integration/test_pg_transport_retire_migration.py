"""migration 411 — PG transport 유가·돌발 적재 종료와 Feature 퇴역(ADR-114 결정 7, 1단계).

**410까지 올린 빈 DB**(배포 경로: bootstrap → migrator → schema owner)에 seed 카탈로그의 실제
transport dataset으로 Feature를 심고 411을 올린다.

- 퇴역해야 하는 것: 주유소 유가 price, 휴게소 유가 price, 고속도로 돌발 notice — ``retired``·
  ``suppressed``, ``system`` 상태 전이 감사 한 줄씩, 재활성화를 막는 lifecycle override 한 줄씩.
  그 dataset의 operation(종류 불문)은 꺼진다. dataset·source lineage·행은 남는다(이력).
- 남아야 하는 것: transport 주유소 place(장소 적재는 1단계 범위 밖 — 적재도 계속 돈다)와
  산림청 산사태 notice(다른 provider). 상태·``row_revision``이 그대로이고 operation도 켜져 있다.

"검사는 한 번 빨갛게 만든다": 퇴역을 재는 탐침은 410에서 **0이 아님**(active 대상 3)을 먼저 본다.
"""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4

import pytest
from alembic.config import Config

from alembic import command
from kortravelmap.infra.db import normalize_async_dsn
from tests.integration._application_300_bootstrap import (
    alembic_schema_owner_role,
    bootstrapped_application_300_migrator_dsn,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

pytestmark = pytest.mark.integration

_ROOT: Final = Path(__file__).resolve().parents[2]
_PROD_NOW: Final = "409_geo_release_item_reasons"
_BEFORE: Final = "410_provider_field_shadow"
_AFTER: Final = "411_retire_pg_transport_values"

_T0: Final = datetime(2026, 10, 24, 0, 0, tzinfo=UTC)

_FUEL_PRICES: Final = ("kor-travel-transport", "transport_fuel_prices")
_REST_AREA_PRICES: Final = ("kor-travel-transport", "transport_rest_area_fuel_prices")
_INCIDENTS: Final = ("kor-travel-transport", "transport_highway_incidents")
_FUEL_STATIONS: Final = ("kor-travel-transport", "transport_fuel_stations")
_LANDSLIDE: Final = ("python-krforest-api", "krforest_landslide_forecast_issues")

#: migration과 같은 정체성 규칙(provider + produces). 테스트가 이름 목록을 들지 않는다.
_TARGET_DATASETS_SQL: Final = """
SELECT dataset.provider_dataset_id
  FROM provider_sync.provider_datasets AS dataset
 WHERE dataset.provider = 'kor-travel-transport'
   AND ((dataset.capabilities -> 'produces') @> '["price"]'::jsonb
        OR (dataset.capabilities -> 'produces') @> '["notice"]'::jsonb)
"""


def _with_database(url: str, database: str) -> str:
    parts = urlsplit(url)
    return urlunsplit(parts._replace(path=f"/{database}"))


async def _connect(url: str) -> Any:
    import asyncpg

    parts = urlsplit(url)
    return await asyncpg.connect(
        user=parts.username,
        password=parts.password,
        host=parts.hostname,
        port=parts.port,
        database=(parts.path or "/postgres").lstrip("/"),
    )


async def _admin_execute(url: str, statement: str) -> None:
    connection = await _connect(url)
    try:
        await connection.execute(statement)
    finally:
        await connection.close()


async def _db_at(pg_container: object, *, stop_at_409: bool) -> AsyncIterator[tuple[Config, str]]:
    # 목표 revision은 모듈 상수 리터럴로만 넘긴다(`tests/unit/test_alembic_squash_boundary.py`).
    raw_dsn = pg_container.get_connection_url()  # type: ignore[attr-defined]
    database = f"transport_retire_{uuid4().hex}"
    await _admin_execute(raw_dsn, f'CREATE DATABASE "{database}"')
    superuser_dsn = _with_database(raw_dsn, database)
    config = Config(str(_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_ROOT / "alembic"))
    try:
        config.set_main_option(
            "sqlalchemy.url",
            await bootstrapped_application_300_migrator_dsn(normalize_async_dsn(superuser_dsn)),
        )
        with alembic_schema_owner_role():
            if stop_at_409:
                await asyncio.to_thread(command.upgrade, config, _PROD_NOW)
            else:
                await asyncio.to_thread(command.upgrade, config, _BEFORE)
        yield config, superuser_dsn
    finally:
        await _admin_execute(raw_dsn, f'DROP DATABASE "{database}" WITH (FORCE)')


@pytest.fixture
async def db_at_410(pg_container: object) -> AsyncIterator[tuple[Config, str]]:
    """fresh DB를 배포 경로로 **410까지만** 올린다(410 commit). (Config, superuser DSN)."""

    async for value in _db_at(pg_container, stop_at_409=False):
        yield value


@pytest.fixture
async def db_at_409(pg_container: object) -> AsyncIterator[tuple[Config, str]]:
    """prod와 같은 **409**에서 멈춘다 — 410·411을 한 트랜잭션으로 올리는 배포 경로를 잰다."""

    async for value in _db_at(pg_container, stop_at_409=True):
        yield value


async def _upgrade_to_411(config: Config) -> None:
    with alembic_schema_owner_role():
        await asyncio.to_thread(command.upgrade, config, _AFTER)


async def _version(connection: Any) -> str:
    return str(await connection.fetchval("SELECT version_num FROM public.alembic_version"))


async def _dataset_id(connection: Any, identity: tuple[str, str]) -> int:
    value = await connection.fetchval(
        "SELECT provider_dataset_id FROM provider_sync.provider_datasets "
        "WHERE provider = $1 AND dataset_key = $2",
        *identity,
    )
    assert value is not None, f"카탈로그에 {identity}가 없다 — 이 검사의 전제가 깨졌다"
    return int(value)


async def _seed_feature(
    connection: Any,
    *,
    dataset_id: int,
    kind: str,
    entity_type: str,
) -> tuple[UUID, str]:
    """entity·record·head·core(+notice subtype)·primary link 한 벌(superuser fixture seeding)."""

    feature_id = uuid4()
    entity_key = f"411-{kind}-{uuid4().hex[:8]}"
    record_key = f"{entity_key}-record"
    await connection.execute(
        """
        INSERT INTO provider_sync.source_entities (
            source_entity_key, source_entity_type, source_entity_id,
            first_seen_at, last_seen_at, provider_dataset_id
        ) VALUES ($1, $2, $1, $3, $3, $4)
        """,
        entity_key,
        entity_type,
        _T0,
        dataset_id,
    )
    await connection.execute(
        """
        INSERT INTO provider_sync.source_records (
            source_record_key, raw_data, raw_payload_hash, fetched_at, source_entity_key
        ) VALUES ($1, '{}'::jsonb, $2, $3, $4)
        """,
        record_key,
        hashlib.sha256(record_key.encode()).hexdigest(),
        _T0,
        entity_key,
    )
    await connection.execute(
        """
        INSERT INTO provider_sync.source_entity_heads (
            source_entity_key, current_source_record_key, observed_at
        ) VALUES ($1, $2, $3)
        """,
        entity_key,
        record_key,
        _T0,
    )
    await connection.execute(
        "INSERT INTO feature.features (feature_id, kind, name, category) "
        "VALUES ($1, $2, $3, '00000000')",
        feature_id,
        kind,
        f"411 {kind} {entity_key}",
    )
    if kind == "notice":
        await connection.execute(
            "INSERT INTO feature.feature_notices (feature_id, kind, notice_type, severity) "
            "VALUES ($1, 'notice', 'test', 2)",
            feature_id,
        )
    await connection.execute(
        """
        INSERT INTO provider_sync.source_links (
            feature_id, source_role, match_method, confidence, source_entity_key
        ) VALUES ($1, 'primary', 'provider_key', 100, $2)
        """,
        feature_id,
        entity_key,
    )
    return feature_id, entity_key


class _Seeded:
    def __init__(self) -> None:
        self.targets: list[UUID] = []
        self.kept: list[UUID] = []
        self.entities: list[str] = []


async def _seed_population(connection: Any) -> _Seeded:
    seeded = _Seeded()
    async with connection.transaction():
        for identity, kind, entity_type in (
            (_FUEL_PRICES, "price", "fuel_price"),
            (_REST_AREA_PRICES, "price", "rest_area_fuel_price"),
            (_INCIDENTS, "notice", "traffic_notice"),
        ):
            feature_id, entity = await _seed_feature(
                connection,
                dataset_id=await _dataset_id(connection, identity),
                kind=kind,
                entity_type=entity_type,
            )
            seeded.targets.append(feature_id)
            seeded.entities.append(entity)
        for identity, kind, entity_type in (
            (_FUEL_STATIONS, "place", "fuel_station"),
            (_LANDSLIDE, "notice", "landslide_forecast_issue"),
        ):
            feature_id, entity = await _seed_feature(
                connection,
                dataset_id=await _dataset_id(connection, identity),
                kind=kind,
                entity_type=entity_type,
            )
            seeded.kept.append(feature_id)
            seeded.entities.append(entity)
    return seeded


async def _states(connection: Any, feature_ids: list[UUID]) -> dict[UUID, tuple[str, str, int]]:
    rows = await connection.fetch(
        "SELECT feature_id, lifecycle_state, publication_state, row_revision "
        "FROM feature.features WHERE feature_id = ANY($1::uuid[])",
        feature_ids,
    )
    return {
        row["feature_id"]: (row["lifecycle_state"], row["publication_state"], row["row_revision"])
        for row in rows
    }


async def _enabled_target_operations(connection: Any) -> int:
    return int(
        await connection.fetchval(
            "SELECT count(*) FROM provider_sync.provider_dataset_operations "
            f"WHERE provider_dataset_id IN ({_TARGET_DATASETS_SQL}) AND is_enabled"
        )
    )


async def _other_dataset_seals(connection: Any) -> dict[int, tuple[int, int, str]]:
    """대상 밖 모든 dataset의 curation seal 입력(``current_provider_curation_input_set``)."""
    rows = await connection.fetch(
        f"""
        SELECT dataset.provider_dataset_id, input.source_entity_count, input.input_member_count,
               input.source_input_set_hash
          FROM provider_sync.provider_datasets AS dataset
         CROSS JOIN LATERAL feature.current_provider_curation_input_set(
               dataset.provider_dataset_id) AS input
         WHERE dataset.provider_dataset_id NOT IN ({_TARGET_DATASETS_SQL})
        """
    )
    return {
        int(row["provider_dataset_id"]): (
            int(row["source_entity_count"]),
            int(row["input_member_count"]),
            str(row["source_input_set_hash"]),
        )
        for row in rows
    }


async def _target_scope(connection: Any) -> Any:
    member = await connection.fetchrow(
        f"""
        SELECT scope.provider_dataset_id, scope.sync_scope, scope.operation_key
          FROM provider_sync.provider_dataset_operation_scopes AS scope
         WHERE scope.provider_dataset_id IN ({_TARGET_DATASETS_SQL})
         ORDER BY scope.provider_dataset_id, scope.operation_key, scope.sync_scope
         LIMIT 1
        """
    )
    assert member is not None, "대상 operation scope가 없다 — 전제가 깨졌다"
    return member


async def _insert_member_job(connection: Any, member: Any, kind: str) -> Any:
    job_id = await connection.fetchval(
        "INSERT INTO ops.import_jobs (kind, dataset_membership_mode) "
        "VALUES ($1, 'single') RETURNING job_id",
        kind,
    )
    await connection.execute(
        """
        INSERT INTO ops.import_job_datasets (
            job_id, provider_dataset_id, sync_scope, operation_key
        ) VALUES ($1, $2, $3, $4)
        """,
        job_id,
        member["provider_dataset_id"],
        member["sync_scope"],
        member["operation_key"],
    )
    return job_id


async def test_411_retires_transport_price_and_incident_features_and_keeps_everything_else(
    db_at_410: tuple[Config, str],
) -> None:
    config, superuser_dsn = db_at_410
    connection = await _connect(superuser_dsn)
    try:
        assert await _version(connection) == _BEFORE
        seeded = await _seed_population(connection)
        before = await _states(connection, seeded.targets + seeded.kept)
        # 410: 대상이 전부 active다(빨강) — 0이면 아래 단언이 항진명제다.
        assert all(before[f][0] == "active" for f in seeded.targets)
        assert await _enabled_target_operations(connection) > 0
        target_datasets = int(
            await connection.fetchval(f"SELECT count(*) FROM ({_TARGET_DATASETS_SQL}) AS t")
        )
        assert target_datasets == 3
        seals_before = await _other_dataset_seals(connection)
        assert len(seals_before) > 10
        kept_enabled_before = await connection.fetch(
            """
            SELECT operation.provider_dataset_id, operation.operation_key, operation.is_enabled
              FROM provider_sync.provider_dataset_operations AS operation
             WHERE operation.provider_dataset_id NOT IN ("""
            + _TARGET_DATASETS_SQL
            + """)
             ORDER BY 1, 2
            """
        )
    finally:
        await connection.close()

    await _upgrade_to_411(config)

    connection = await _connect(superuser_dsn)
    try:
        assert await _version(connection) == _AFTER
        after = await _states(connection, seeded.targets + seeded.kept)
        for feature_id in seeded.targets:
            assert after[feature_id][:2] == ("retired", "suppressed"), feature_id
            assert after[feature_id][2] > before[feature_id][2]
        for feature_id in seeded.kept:
            assert after[feature_id] == before[feature_id], feature_id

        transitions = await connection.fetch(
            """
            SELECT feature_id, transition_kind, reason_code, principal, causation_ref,
                   from_lifecycle_state, to_lifecycle_state, to_publication_state
              FROM feature.feature_state_transitions
             WHERE reason_code = 'adr114_transport_state_moved_to_valkey'
            """
        )
        assert {row["feature_id"] for row in transitions} == set(seeded.targets)
        assert all(row["transition_kind"] == "system" for row in transitions)
        assert all(
            (row["from_lifecycle_state"], row["to_lifecycle_state"], row["to_publication_state"])
            == ("active", "retired", "suppressed")
            for row in transitions
        )
        assert all(row["causation_ref"] == "ADR-114 decision 7 phase 1" for row in transitions)

        overrides = await connection.fetch(
            """
            SELECT feature_id, override_value, prevent_provider_reactivation
              FROM ops.feature_overrides
             WHERE field_path = 'lifecycle_state' AND status = 'active'
            """
        )
        assert {row["feature_id"] for row in overrides} == set(seeded.targets)
        assert all(row["prevent_provider_reactivation"] for row in overrides)

        # 이력은 남는다 — source lineage 행을 지우지 않는다.
        assert await connection.fetchval(
            "SELECT count(*) FROM provider_sync.source_entities "
            "WHERE source_entity_key = ANY($1::text[])",
            seeded.entities,
        ) == len(seeded.entities)
        assert await connection.fetchval(
            "SELECT count(*) FROM provider_sync.source_links WHERE feature_id = ANY($1::uuid[])",
            seeded.targets,
        ) == len(seeded.targets)

        # 대상 dataset: operation은 전부 꺼지고 행은 남는다. dataset은 활성으로 남는다(1단계).
        assert await _enabled_target_operations(connection) == 0
        assert await connection.fetchval(
            f"SELECT count(*) FROM ({_TARGET_DATASETS_SQL}) AS t"
        ) == target_datasets
        assert await connection.fetchval(
            "SELECT bool_and(is_active) FROM provider_sync.provider_datasets "
            f"WHERE provider_dataset_id IN ({_TARGET_DATASETS_SQL})"
        ) is True

        # 대상 밖 operation은 하나도 바뀌지 않았다(장소 적재·공항 C7 대상 포함).
        kept_enabled_after = await connection.fetch(
            """
            SELECT operation.provider_dataset_id, operation.operation_key, operation.is_enabled
              FROM provider_sync.provider_dataset_operations AS operation
             WHERE operation.provider_dataset_id NOT IN ("""
            + _TARGET_DATASETS_SQL
            + """)
             ORDER BY 1, 2
            """
        )
        assert [tuple(row) for row in kept_enabled_after] == [
            tuple(row) for row in kept_enabled_before
        ]
        assert await connection.fetchval(
            """
            SELECT operation.is_enabled
              FROM provider_sync.provider_dataset_operations AS operation
             WHERE operation.operation_key = 'feature_place_transport_airports_job'
            """
        ) is True

        # 대상 밖 dataset의 seal 입력은 하나도 바뀌지 않았다(대상 Feature에 그 link가 없다).
        assert await _other_dataset_seals(connection) == seals_before
        # 새 대상 member는 활성 가드가 거부한다(operation이 꺼졌다).
        import asyncpg

        member = await _target_scope(connection)
        with pytest.raises(asyncpg.CheckViolationError, match="inactive dataset member"):
            async with connection.transaction():
                await _insert_member_job(connection, member, "411-after-probe")
    finally:
        await connection.close()


async def test_411_refuses_when_a_job_is_queued_on_a_transport_price_operation(
    db_at_410: tuple[Config, str],
) -> None:
    """대상 operation을 member로 둔 queued job이 있으면 아무것도 바꾸지 않는다.

    operation을 끄면 그 job은 종결로 갈 수 없고, 퇴역이 그 root의 seal 입력을 바꿔
    ``stale_input``으로 실패시킨다(ADR-114 기각 대안의 첫 함정).
    """

    config, superuser_dsn = db_at_410
    connection = await _connect(superuser_dsn)
    try:
        seeded = await _seed_population(connection)
        member = await connection.fetchrow(
            f"""
            SELECT scope.provider_dataset_id, scope.sync_scope, scope.operation_key
              FROM provider_sync.provider_dataset_operation_scopes AS scope
              JOIN provider_sync.provider_dataset_operations AS operation
                ON operation.provider_dataset_id = scope.provider_dataset_id
               AND operation.operation_key = scope.operation_key
             WHERE scope.provider_dataset_id IN ({_TARGET_DATASETS_SQL})
               AND operation.is_enabled
             ORDER BY scope.provider_dataset_id, scope.operation_key, scope.sync_scope
             LIMIT 1
            """
        )
        assert member is not None, "켜진 대상 operation scope가 없다 — 전제가 깨졌다"
        async with connection.transaction():
            job_id = await connection.fetchval(
                "INSERT INTO ops.import_jobs (kind, dataset_membership_mode) "
                "VALUES ('411-in-flight-probe', 'single') RETURNING job_id"
            )
            await connection.execute(
                """
                INSERT INTO ops.import_job_datasets (
                    job_id, provider_dataset_id, sync_scope, operation_key
                ) VALUES ($1, $2, $3, $4)
                """,
                job_id,
                member["provider_dataset_id"],
                member["sync_scope"],
                member["operation_key"],
            )
        before = await _states(connection, seeded.targets)
        enabled_before = await _enabled_target_operations(connection)
    finally:
        await connection.close()

    with pytest.raises(Exception, match="queued/running job on a transport price/notice operation"):
        await _upgrade_to_411(config)

    connection = await _connect(superuser_dsn)
    try:
        assert await _version(connection) == _BEFORE
        assert await _states(connection, seeded.targets) == before
        assert await _enabled_target_operations(connection) == enabled_before
        assert await connection.fetchval(
            "SELECT status FROM ops.import_jobs WHERE job_id = $1", job_id
        ) == "queued"
    finally:
        await connection.close()


async def test_411_refuses_when_a_target_feature_has_a_link_from_another_dataset(
    db_at_410: tuple[Config, str],
) -> None:
    """대상 Feature가 대상 밖 dataset의 link(역할 무관 — 여기서는 enrichment)를 가지면 퇴역 안 함.

    퇴역은 그 dataset의 curation seal 입력을 바꾼다(link 역할 무관). 트랜잭션 전체가 되돌아가 410
    그대로여야 한다.
    """

    config, superuser_dsn = db_at_410
    connection = await _connect(superuser_dsn)
    try:
        seeded = await _seed_population(connection)
        landslide = await _dataset_id(connection, _LANDSLIDE)
        shared_entity = f"411-shared-{uuid4().hex[:8]}"
        async with connection.transaction():
            await connection.execute(
                """
                INSERT INTO provider_sync.source_entities (
                    source_entity_key, source_entity_type, source_entity_id,
                    first_seen_at, last_seen_at, provider_dataset_id
                ) VALUES ($1, 'landslide_forecast_issue', $1, $2, $2, $3)
                """,
                shared_entity,
                _T0,
                landslide,
            )
            await connection.execute(
                """
                INSERT INTO provider_sync.source_links (
                    feature_id, source_role, match_method, confidence, source_entity_key
                ) VALUES ($1, 'enrichment', 'provider_key', 80, $2)
                """,
                seeded.targets[2],
                shared_entity,
            )
        before = await _states(connection, seeded.targets)
    finally:
        await connection.close()

    with pytest.raises(Exception, match="source link outside the targets"):
        await _upgrade_to_411(config)

    connection = await _connect(superuser_dsn)
    try:
        assert await _version(connection) == _BEFORE
        assert await _states(connection, seeded.targets) == before
        assert await _enabled_target_operations(connection) > 0
    finally:
        await connection.close()


async def test_409_to_411_in_one_transaction_refuses_and_rolls_back_410_too(
    db_at_409: tuple[Config, str],
) -> None:
    """prod 경로(409)에서 410·411을 한 트랜잭션으로 올리면 411이 거부한다(퇴역할 Feature가 있을 때).

    한 트랜잭션이면 410의 FK 추가가 잡은 표 잠금을 퇴역 내내 쥔다. 거부되면 410도 함께 되돌아가
    409 그대로다. 그 뒤 410을 단독 commit하고 411을 올리면 통과한다(runbook A·B).
    """

    config, superuser_dsn = db_at_409
    connection = await _connect(superuser_dsn)
    try:
        assert await _version(connection) == _PROD_NOW
        seeded = await _seed_population(connection)
    finally:
        await connection.close()

    with pytest.raises(Exception, match="앞선 revision"):
        await _upgrade_to_411(config)

    connection = await _connect(superuser_dsn)
    try:
        assert await _version(connection) == _PROD_NOW
        assert await connection.fetchval(
            "SELECT to_regclass('feature.provider_field_shadow_candidates') IS NULL"
        ) is True
        assert all(
            state[0] == "active"
            for state in (await _states(connection, seeded.targets)).values()
        )
    finally:
        await connection.close()

    with alembic_schema_owner_role():
        await asyncio.to_thread(command.upgrade, config, _BEFORE)
    await _upgrade_to_411(config)

    connection = await _connect(superuser_dsn)
    try:
        assert await _version(connection) == _AFTER
        assert all(
            state[:2] == ("retired", "suppressed")
            for state in (await _states(connection, seeded.targets)).values()
        )
    finally:
        await connection.close()


async def test_411_refuses_when_a_target_feature_has_an_active_lifecycle_override(
    db_at_410: tuple[Config, str],
) -> None:
    """운영자 lifecycle override가 이미 있는 대상은 덮어쓰지 않는다 — 트랜잭션 전체가 되돌아간다."""

    config, superuser_dsn = db_at_410
    connection = await _connect(superuser_dsn)
    try:
        seeded = await _seed_population(connection)
        await connection.execute(
            """
            INSERT INTO ops.feature_overrides (
                feature_id, field_path, override_value, prevent_provider_reactivation, status
            ) VALUES ($1, 'lifecycle_state', '"active"'::jsonb, false, 'active')
            """,
            seeded.targets[0],
        )
        before = await _states(connection, seeded.targets)
    finally:
        await connection.close()

    with pytest.raises(Exception, match="active lifecycle override"):
        await _upgrade_to_411(config)

    connection = await _connect(superuser_dsn)
    try:
        assert await _version(connection) == _BEFORE
        assert await _states(connection, seeded.targets) == before
        assert await _enabled_target_operations(connection) > 0
    finally:
        await connection.close()


async def test_411_waits_on_an_uncommitted_target_membership_and_fails_closed(
    db_at_410: tuple[Config, str],
) -> None:
    """검사와 끄기 사이의 경주: commit되지 않은 대상 member가 있으면 411은 scope 행을 잠그지 못한다.

    member INSERT의 FK가 scope 행에 ``FOR KEY SHARE``를 쥐므로 411의 ``FOR UPDATE``는
    ``lock_timeout``(5초)으로 실패하고 아무것도 바꾸지 않는다. 잠금이 없다면 411은 그 job을
    보지 못한 채 operation을 끄고, job은 영영 종결로 가지 못한다.
    """

    config, superuser_dsn = db_at_410
    connection = await _connect(superuser_dsn)
    holder = await _connect(superuser_dsn)
    try:
        seeded = await _seed_population(connection)
        member = await _target_scope(connection)
        transaction = holder.transaction()
        await transaction.start()
        try:
            await _insert_member_job(holder, member, "411-race-probe")
            with pytest.raises(Exception, match="lock"):
                await _upgrade_to_411(config)
        finally:
            await transaction.rollback()
        assert await _version(connection) == _BEFORE
        assert all(
            state[0] == "active"
            for state in (await _states(connection, seeded.targets)).values()
        )
        assert await _enabled_target_operations(connection) > 0
    finally:
        await holder.close()
        await connection.close()
