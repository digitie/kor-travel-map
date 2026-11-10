"""migration 449 — 축제 원천을 TourAPI로 바꾼다(2026-11-10 소유자 결정).

**448까지 올린 빈 DB**(배포 경로: bootstrap → migrator → schema owner)에 seed 카탈로그의 실제
표준데이터 축제 dataset으로 축제 Feature를 심고, 옛 TourAPI 축제 보강 dataset으로 그 Feature에
enrichment link와 ``pending`` 검토 큐 행을 단 뒤 449을 올린다.

- 퇴역해야 하는 것: 표준데이터 축제 Feature — ``retired``·``suppressed``, ``system`` 상태 전이
  감사(``festival_source_moved_to_tourapi``) 한 줄, 재활성화를 막는 lifecycle override 한 줄.
- 닫혀야 하는 것: 옛 보강 dataset 원천의 ``pending`` 검토 큐 행 → ``ignored``.
- 꺼져야 하는 것: 두 옛 dataset의 operation(종류 불문)과 dataset 자체(``is_active = false``).
- 생겨야 하는 것: ``python-visitkorea-api``/``visitkorea_festivals`` 활성 dataset, refresh·preview
  operation, ``dataset_wide`` scope.
- 남아야 하는 것: 다른 원천의 행사(국가유산 행사)와 그 operation. source lineage 행(이력).

"검사는 한 번 빨갛게 만든다": 퇴역을 재는 탐침은 448에서 **active**·켜진 operation을 먼저 본다.
"""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, date, datetime
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
_BEFORE: Final = "448_mcst_theme_transition"
_AFTER: Final = "449_tourapi_festivals_primary"

_T0: Final = datetime(2026, 11, 10, 0, 0, tzinfo=UTC)

_STANDARD_FESTIVALS: Final = ("data.go.kr-standard", "datagokr_cultural_festivals")
_LEGACY_ENRICHMENT: Final = ("python-visitkorea-api", "visitkorea_festival_events")
_HERITAGE_EVENTS: Final = ("python-krheritage-api", "krheritage_event_list")
_FESTIVAL_JOB: Final = "feature_event_visitkorea_festivals_job"

_RETIRED_DATASETS_SQL: Final = """
SELECT dataset.provider_dataset_id
  FROM provider_sync.provider_datasets AS dataset
 WHERE (dataset.provider, dataset.dataset_key) IN (
       ('data.go.kr-standard', 'datagokr_cultural_festivals'),
       ('python-visitkorea-api', 'visitkorea_festival_events'))
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
async def db_at_448(pg_container: object) -> AsyncIterator[tuple[Config, str]]:
    """fresh DB를 배포 경로로 **448까지만** 올린다. (Config, superuser DSN)."""

    # 목표 revision은 모듈 상수 리터럴로만 넘긴다(`tests/unit/test_alembic_squash_boundary.py`).
    raw_dsn = pg_container.get_connection_url()  # type: ignore[attr-defined]
    database = f"festival_source_{uuid4().hex}"
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


async def _upgrade_to_449(config: Config) -> None:
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


async def _seed_entity(connection: Any, *, dataset_id: int, entity_type: str) -> tuple[str, str]:
    """entity·record·head 한 벌. (source_entity_key, source_record_key)."""

    entity_key = f"449-{entity_type}-{uuid4().hex[:8]}"
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
    return entity_key, record_key


async def _seed_event(
    connection: Any, *, dataset_id: int, entity_type: str, event_kind: str
) -> tuple[UUID, str]:
    """event core + event subtype + primary link."""

    feature_id = uuid4()
    entity_key, _record_key = await _seed_entity(
        connection, dataset_id=dataset_id, entity_type=entity_type
    )
    await connection.execute(
        "INSERT INTO feature.features (feature_id, kind, name, category) "
        "VALUES ($1, 'event', $2, '01090000')",
        feature_id,
        f"449 {event_kind} {entity_key}",
    )
    await connection.execute(
        "INSERT INTO feature.feature_events (feature_id, kind, event_kind, starts_on, ends_on) "
        "VALUES ($1, 'event', $2, $3, $4)",
        feature_id,
        event_kind,
        date(2026, 4, 5),
        date(2026, 4, 12),
    )
    await connection.execute(
        """
        INSERT INTO provider_sync.source_links (
            feature_id, source_role, match_method, confidence, source_entity_key
        ) VALUES ($1, 'primary', 'natural_key', 100, $2)
        """,
        feature_id,
        entity_key,
    )
    return feature_id, entity_key


class _Seeded:
    def __init__(self) -> None:
        self.target: UUID | None = None
        self.kept: UUID | None = None
        self.review_id: UUID | None = None
        self.entities: list[str] = []


async def _seed_population(connection: Any) -> _Seeded:
    seeded = _Seeded()
    async with connection.transaction():
        target, target_entity = await _seed_event(
            connection,
            dataset_id=await _dataset_id(connection, _STANDARD_FESTIVALS),
            entity_type="cultural_festival",
            event_kind="festival",
        )
        kept, kept_entity = await _seed_event(
            connection,
            dataset_id=await _dataset_id(connection, _HERITAGE_EVENTS),
            entity_type="heritage_event",
            event_kind="heritage_event",
        )
        # 옛 TourAPI 보강: 같은 축제에 enrichment link 하나 + 판정 대기 검토 큐 행 하나.
        enrichment_entity, _ = await _seed_entity(
            connection,
            dataset_id=await _dataset_id(connection, _LEGACY_ENRICHMENT),
            entity_type="festival_enrichment",
        )
        await connection.execute(
            """
            INSERT INTO provider_sync.source_links (
                feature_id, source_role, match_method, confidence, source_entity_key
            ) VALUES ($1, 'enrichment', 'name_match', 95, $2)
            """,
            target,
            enrichment_entity,
        )
        review_entity, review_record = await _seed_entity(
            connection,
            dataset_id=await _dataset_id(connection, _LEGACY_ENRICHMENT),
            entity_type="festival_enrichment",
        )
        review_id = await connection.fetchval(
            """
            INSERT INTO ops.enrichment_review_queue (
                target_feature_id, source_name, target_name, name_score,
                source_entity_key, source_record_key
            ) VALUES ($1, '서울 봄꽃', '서울 봄꽃 축제', 80.00, $2, $3)
            RETURNING review_id
            """,
            target,
            review_entity,
            review_record,
        )
        seeded.target = target
        seeded.kept = kept
        seeded.review_id = review_id
        seeded.entities = [target_entity, kept_entity, enrichment_entity, review_entity]
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


async def _enabled_retired_operations(connection: Any) -> int:
    return int(
        await connection.fetchval(
            "SELECT count(*) FROM provider_sync.provider_dataset_operations "
            f"WHERE provider_dataset_id IN ({_RETIRED_DATASETS_SQL}) AND is_enabled"
        )
    )


async def _festival_dataset_count(connection: Any) -> int:
    return int(
        await connection.fetchval(
            "SELECT count(*) FROM provider_sync.provider_datasets "
            "WHERE provider = 'python-visitkorea-api' AND dataset_key = 'visitkorea_festivals'"
        )
    )


async def test_449_retires_standard_festivals_and_catalogs_the_tourapi_festival_load(
    db_at_448: tuple[Config, str],
) -> None:
    config, superuser_dsn = db_at_448
    connection = await _connect(superuser_dsn)
    try:
        assert await _version(connection) == _BEFORE
        seeded = await _seed_population(connection)
        assert seeded.target is not None
        assert seeded.kept is not None
        before = await _states(connection, [seeded.target, seeded.kept])
        # 448: 대상이 active이고 옛 operation이 켜져 있고 새 dataset은 없다(빨강).
        assert before[seeded.target][0] == "active"
        assert await _enabled_retired_operations(connection) > 0
        assert await _festival_dataset_count(connection) == 0
        assert await connection.fetchval(
            f"SELECT bool_and(is_active) FROM ({_RETIRED_DATASETS_SQL}) AS t "
            "JOIN provider_sync.provider_datasets AS d USING (provider_dataset_id)"
        ) is True
        heritage_ops_before = await connection.fetch(
            """
            SELECT operation.operation_key, operation.operation_kind, operation.is_enabled
              FROM provider_sync.provider_dataset_operations AS operation
              JOIN provider_sync.provider_datasets AS dataset USING (provider_dataset_id)
             WHERE dataset.provider = 'python-krheritage-api'
             ORDER BY 1, 2
            """
        )
    finally:
        await connection.close()

    await _upgrade_to_449(config)

    connection = await _connect(superuser_dsn)
    try:
        assert await _version(connection) == _AFTER
        after = await _states(connection, [seeded.target, seeded.kept])
        assert after[seeded.target][:2] == ("retired", "suppressed")
        assert after[seeded.target][2] > before[seeded.target][2]
        assert after[seeded.kept] == before[seeded.kept]

        transitions = await connection.fetch(
            """
            SELECT feature_id, transition_kind, from_lifecycle_state, to_lifecycle_state,
                   to_publication_state
              FROM feature.feature_state_transitions
             WHERE reason_code = 'festival_source_moved_to_tourapi'
            """
        )
        assert [row["feature_id"] for row in transitions] == [seeded.target]
        assert all(row["transition_kind"] == "system" for row in transitions)
        assert all(
            (row["from_lifecycle_state"], row["to_lifecycle_state"], row["to_publication_state"])
            == ("active", "retired", "suppressed")
            for row in transitions
        )
        overrides = await connection.fetch(
            """
            SELECT feature_id, prevent_provider_reactivation
              FROM ops.feature_overrides
             WHERE field_path = 'lifecycle_state' AND status = 'active'
            """
        )
        assert [row["feature_id"] for row in overrides] == [seeded.target]
        assert all(row["prevent_provider_reactivation"] for row in overrides)

        review = await connection.fetchrow(
            "SELECT status, decision_reason, reviewed_at FROM ops.enrichment_review_queue "
            "WHERE review_id = $1",
            seeded.review_id,
        )
        assert review["status"] == "ignored"
        assert review["decision_reason"] == "festival_source_moved_to_tourapi"
        assert review["reviewed_at"] is not None

        # 이력은 남는다 — source lineage·link 행을 지우지 않는다.
        assert await connection.fetchval(
            "SELECT count(*) FROM provider_sync.source_entities "
            "WHERE source_entity_key = ANY($1::text[])",
            seeded.entities,
        ) == len(seeded.entities)
        assert await connection.fetchval(
            "SELECT count(*) FROM provider_sync.source_links WHERE feature_id = $1",
            seeded.target,
        ) == 2

        # 옛 dataset 둘: operation 전부 꺼짐, dataset 비활성, 행은 남는다.
        assert await _enabled_retired_operations(connection) == 0
        assert await connection.fetchval(
            f"SELECT count(*) FROM ({_RETIRED_DATASETS_SQL}) AS t"
        ) == 2
        assert await connection.fetchval(
            "SELECT bool_or(is_active) FROM provider_sync.provider_datasets "
            f"WHERE provider_dataset_id IN ({_RETIRED_DATASETS_SQL})"
        ) is False

        # 새 TourAPI 축제 dataset: 활성 event dataset, refresh·preview 켜짐, dataset_wide scope.
        dataset = await connection.fetchrow(
            "SELECT provider_dataset_id, is_active, source_kind, capabilities -> 'produces' "
            "AS produces FROM provider_sync.provider_datasets "
            "WHERE provider = 'python-visitkorea-api' AND dataset_key = 'visitkorea_festivals'"
        )
        assert dataset is not None
        assert dataset["is_active"] is True
        assert dataset["source_kind"] == "openapi"
        assert '"event"' in str(dataset["produces"])
        operations = await connection.fetch(
            "SELECT operation_key, operation_kind, is_enabled "
            "FROM provider_sync.provider_dataset_operations "
            "WHERE provider_dataset_id = $1 ORDER BY 1",
            dataset["provider_dataset_id"],
        )
        assert [tuple(row) for row in operations] == [
            (_FESTIVAL_JOB, "refresh", True),
            (f"{_FESTIVAL_JOB}.preview", "preview", True),
        ]
        assert await connection.fetchval(
            "SELECT sync_scope FROM provider_sync.provider_dataset_operation_scopes "
            "WHERE provider_dataset_id = $1 AND operation_key = $2",
            dataset["provider_dataset_id"],
            _FESTIVAL_JOB,
        ) == "dataset_wide"

        # 다른 원천의 행사 적재는 그대로다.
        heritage_ops_after = await connection.fetch(
            """
            SELECT operation.operation_key, operation.operation_kind, operation.is_enabled
              FROM provider_sync.provider_dataset_operations AS operation
              JOIN provider_sync.provider_datasets AS dataset USING (provider_dataset_id)
             WHERE dataset.provider = 'python-krheritage-api'
             ORDER BY 1, 2
            """
        )
        assert [tuple(row) for row in heritage_ops_after] == [
            tuple(row) for row in heritage_ops_before
        ]
    finally:
        await connection.close()


async def test_449_refuses_when_a_target_feature_has_a_link_from_another_dataset(
    db_at_448: tuple[Config, str],
) -> None:
    """대상 축제에 옛 dataset 둘 밖의 link가 있으면 퇴역하지 않는다 — 그 dataset의 seal 입력이
    바뀌기 때문이다. 트랜잭션 전체가 되돌아가 448 그대로여야 한다(새 dataset도 생기지 않는다)."""

    config, superuser_dsn = db_at_448
    connection = await _connect(superuser_dsn)
    try:
        seeded = await _seed_population(connection)
        assert seeded.target is not None
        async with connection.transaction():
            shared_entity, _ = await _seed_entity(
                connection,
                dataset_id=await _dataset_id(connection, _HERITAGE_EVENTS),
                entity_type="heritage_event",
            )
            await connection.execute(
                """
                INSERT INTO provider_sync.source_links (
                    feature_id, source_role, match_method, confidence, source_entity_key
                ) VALUES ($1, 'enrichment', 'provider_key', 80, $2)
                """,
                seeded.target,
                shared_entity,
            )
        before = await _states(connection, [seeded.target])
    finally:
        await connection.close()

    with pytest.raises(Exception, match="source link outside the retired datasets"):
        await _upgrade_to_449(config)

    connection = await _connect(superuser_dsn)
    try:
        assert await _version(connection) == _BEFORE
        assert await _states(connection, [seeded.target]) == before
        assert await _enabled_retired_operations(connection) > 0
        assert await _festival_dataset_count(connection) == 0
        assert await connection.fetchval(
            "SELECT status FROM ops.enrichment_review_queue WHERE review_id = $1",
            seeded.review_id,
        ) == "pending"
    finally:
        await connection.close()


async def test_449_refuses_when_a_job_is_queued_on_a_retired_festival_operation(
    db_at_448: tuple[Config, str],
) -> None:
    """옛 축제 operation을 member로 둔 queued job이 있으면 아무것도 바꾸지 않는다(419와 같은 이유 —
    operation을 끄면 그 job은 종결로 갈 수 없다)."""

    config, superuser_dsn = db_at_448
    connection = await _connect(superuser_dsn)
    try:
        seeded = await _seed_population(connection)
        assert seeded.target is not None
        member = await connection.fetchrow(
            f"""
            SELECT scope.provider_dataset_id, scope.sync_scope, scope.operation_key
              FROM provider_sync.provider_dataset_operation_scopes AS scope
              JOIN provider_sync.provider_dataset_operations AS operation
                ON operation.provider_dataset_id = scope.provider_dataset_id
               AND operation.operation_key = scope.operation_key
             WHERE scope.provider_dataset_id IN ({_RETIRED_DATASETS_SQL})
               AND operation.is_enabled
             ORDER BY scope.provider_dataset_id, scope.operation_key, scope.sync_scope
             LIMIT 1
            """
        )
        assert member is not None, "켜진 옛 축제 operation scope가 없다 — 전제가 깨졌다"
        async with connection.transaction():
            job_id = await connection.fetchval(
                "INSERT INTO ops.import_jobs (kind, dataset_membership_mode) "
                "VALUES ('449-in-flight-probe', 'single') RETURNING job_id"
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
        before = await _states(connection, [seeded.target])
    finally:
        await connection.close()

    with pytest.raises(Exception, match="queued/running job on a retired festival operation"):
        await _upgrade_to_449(config)

    connection = await _connect(superuser_dsn)
    try:
        assert await _version(connection) == _BEFORE
        assert await _states(connection, [seeded.target]) == before
        assert await _festival_dataset_count(connection) == 0
        assert await connection.fetchval(
            "SELECT status FROM ops.import_jobs WHERE job_id = $1", job_id
        ) == "queued"
    finally:
        await connection.close()
