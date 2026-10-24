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
_BEFORE: Final = "410_provider_field_shadow"
_AFTER: Final = "411_retire_pg_transport_prices_incidents"

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


@pytest.fixture
async def db_at_410(pg_container: object) -> AsyncIterator[tuple[Config, str]]:
    """fresh DB를 배포 경로로 **410까지만** 올린다. (411을 올릴 Config, superuser DSN)."""

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
            await asyncio.to_thread(command.upgrade, config, _BEFORE)
        yield config, superuser_dsn
    finally:
        await _admin_execute(raw_dsn, f'DROP DATABASE "{database}" WITH (FORCE)')


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


async def test_411_refuses_when_a_target_feature_has_another_primary_source(
    db_at_410: tuple[Config, str],
) -> None:
    """대상 Feature가 대상 밖 dataset에도 primary 출처를 가지면 퇴역하지 않는다.

    퇴역하면 남는 출처의 Feature가 함께 사라진다. 트랜잭션 전체가 되돌아가 410 그대로여야 한다.
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
                ) VALUES ($1, 'primary', 'provider_key', 100, $2)
                """,
                seeded.targets[2],
                shared_entity,
            )
        before = await _states(connection, seeded.targets)
    finally:
        await connection.close()

    with pytest.raises(Exception, match="primary source outside the targets"):
        await _upgrade_to_411(config)

    connection = await _connect(superuser_dsn)
    try:
        assert await _version(connection) == _BEFORE
        assert await _states(connection, seeded.targets) == before
        assert await _enabled_target_operations(connection) > 0
    finally:
        await connection.close()
