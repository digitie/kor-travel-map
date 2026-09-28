"""collation에 민감한 text 정렬을 byte 순서로 고정했는지 — 공용 glibc instance 대비 (ADR-103).

n150 prod의 Map DB는 Manager 공용 instance(glibc, default collation ``en_US.utf8``)로
옮긴다. alpine(musl) lane에서는 default collation이 byte 순서와 사실상 같아
``COLLATE "C"``를 빼는 변이가 테스트를 전부 통과한 채 살아남는다
(``test_alias_map_collation_glibc`` 모듈과 같은 이유). 본 모듈은 **lane의 이미지**
(``KTM_TEST_POSTGIS_IMAGE``)를 별도 cluster로 띄워 최소 격리 표면을 만들고, en_US와
C에서 갈리는 key(``'a-b'``·``'ab'``·``'B'``·``'a'``)를 고친 함수마다 흘려:

① 결과 순서·digest·잠금 순서가 UTF-8 byte 순서(= Python ``sorted()``)임을 단언하고
   (``COLLATE "C"`` 제거 변이는 glibc에서 en_US 순서로 갈라져 여기서 죽는다),
② ``ORDER BY``(default)와 ``ORDER BY … COLLATE "C"``가 실제로 **다름**을 단언한다
   (collation 감지 가드). 같으면 이 환경은 판별력이 없다 — alpine lane에서는 사유를
   적고 skip하지만, lane이 공용 glibc digest면 skip하지 않고 **실패**한다. 판별력 없는
   초록이 glibc lane을 조용히 무력화하지 못하게 한다.

잠금 순서는 직접 볼 수 없으므로 효과로 잰다. advisory lock은 같은 이름의 함수를
``search_path`` 앞 schema에 두어 호출 순서를 기록하고(``pg_catalog``를 path에 명시하면
그 앞 schema가 먼저 해석된다), ``INSERT … SELECT … ORDER BY … FOR KEY SHARE``의
row lock은 행을 끌어올 때 잡히고 곧바로 INSERT되므로 BEFORE INSERT 트리거가 기록한
삽입 순서가 곧 잠금 순서다.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import TYPE_CHECKING, Any, Final
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.infra.cache_target_event_repo import (
    capture_cache_target_refresh_members,
    capture_cache_target_refresh_members_by_keys,
)
from kortravelmap.infra.curation_repo import _lock_collection_keys
from kortravelmap.infra.db import make_async_engine, normalize_async_dsn
from kortravelmap.infra.evidence_export import canonical_jsonl, export_evidence
from kortravelmap.infra.evidence_restore import invalidate_leases, rebuild_acked_through
from tests.integration._postgis_image import SHARED_GLIBC_POSTGIS_IMAGE
from tests.integration.conftest import postgis_image

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

    from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration

#: en_US.utf8(glibc)와 C에서 순서가 갈리는 최소 세트. en_US는 구두점을 1차 비교에서
#: 무시하고 대소문자를 뒤 단계로 미룬다 — `'a' < 'ab' < 'a-b' < 'B'`. byte 순서는
#: `'B' < 'a' < 'a-b' < 'ab'`다.
_SEED_KEYS: Final[tuple[str, ...]] = ("a-b", "ab", "B", "a")


def _byte_sorted(values: Any) -> list[Any]:
    """Python의 codepoint 정렬 — UTF-8 byte 순서와 같다."""

    return sorted(values, key=lambda value: str(value).encode("utf-8"))


_BYTE_ORDER: Final[list[str]] = _byte_sorted(_SEED_KEYS)

_EVENT_ID: Final[str] = str(uuid.uuid5(uuid.NAMESPACE_URL, "ktm-collation-probe-event"))

#: evidence export가 도는 열 relation의 최소 모양. 순서와 무관한 relation은 비워 둔다
#: — exporter는 열 개를 모두 읽으므로 존재만 하면 된다.
_SURFACE_DDL: Final[tuple[str, ...]] = (
    "CREATE SCHEMA feature",
    "CREATE SCHEMA ops",
    "CREATE SCHEMA collation_probe",
    "CREATE TABLE feature.manual_feature_identity_claims (feature_id uuid PRIMARY KEY)",
    "CREATE TABLE feature.feature_creation_origins (feature_id uuid PRIMARY KEY)",
    "CREATE TABLE ops.domain_commands (command_id bigint PRIMARY KEY)",
    "CREATE TABLE ops.domain_command_results (command_id bigint PRIMARY KEY)",
    "CREATE TABLE ops.feature_requests (request_id uuid PRIMARY KEY)",
    "CREATE TABLE ops.manual_provider_dedup_cases (case_id uuid PRIMARY KEY)",
    "CREATE TABLE ops.manual_provider_dedup_resolutions (resolution_id uuid PRIMARY KEY)",
    "CREATE TABLE ops.feature_reference_reconciliation_events ("
    " event_id uuid PRIMARY KEY, event_sequence bigint NOT NULL UNIQUE)",
    "CREATE TABLE ops.feature_reference_reconciliation_acks ("
    " event_id uuid NOT NULL, principal_id text NOT NULL,"
    " PRIMARY KEY (event_id, principal_id))",
    "CREATE TABLE ops.feature_reference_reconciliation_subscriptions ("
    " principal_id text PRIMARY KEY, initial_event_sequence bigint NOT NULL)",
    "CREATE TABLE ops.feature_reference_reconciliation_leases ("
    " principal_id text PRIMARY KEY, worker_id text, lease_epoch bigint NOT NULL,"
    " lease_expires_at timestamptz, acked_through_sequence bigint NOT NULL,"
    " updated_at timestamptz NOT NULL DEFAULT now())",
    "CREATE TABLE ops.poi_cache_target_streams ("
    " external_system text PRIMARY KEY, restore_epoch bigint NOT NULL)",
    "CREATE TABLE ops.poi_cache_targets ("
    " target_id uuid PRIMARY KEY, external_system text NOT NULL, target_key text NOT NULL,"
    " deleted_at timestamptz, update_enabled boolean NOT NULL,"
    " refresh_policy text NOT NULL)",
    "CREATE TABLE ops.poi_cache_target_source_heads ("
    " external_system text NOT NULL, target_key text NOT NULL, target_id uuid,"
    " state text NOT NULL, restore_epoch bigint NOT NULL,"
    " source_generation bigint NOT NULL, source_payload_fingerprint text NOT NULL,"
    " PRIMARY KEY (external_system, target_key))",
    "CREATE TABLE ops.poi_cache_target_source_events ("
    " external_system text NOT NULL, target_key text NOT NULL,"
    " restore_epoch bigint NOT NULL, source_generation bigint NOT NULL,"
    " source_payload_fingerprint text NOT NULL,"
    " PRIMARY KEY (external_system, target_key, restore_epoch, source_generation))",
    "CREATE TABLE ops.poi_cache_target_refresh_members ("
    " request_id uuid NOT NULL, target_id uuid NOT NULL, external_system text NOT NULL,"
    " target_key text NOT NULL, restore_epoch bigint NOT NULL,"
    " source_generation bigint NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),"
    " PRIMARY KEY (request_id, target_id))",
    # 잠금 순서 기록기 — 모듈 docstring 참조.
    "CREATE TABLE collation_probe.advisory_lock_log ("
    " position bigserial PRIMARY KEY, lock_key bigint NOT NULL)",
    "CREATE FUNCTION collation_probe.pg_advisory_xact_lock(bigint) RETURNS void"
    " LANGUAGE plpgsql VOLATILE AS $$ BEGIN"
    " INSERT INTO collation_probe.advisory_lock_log (lock_key) VALUES ($1);"
    " END $$",
    "CREATE TABLE collation_probe.member_insert_log ("
    " position bigserial PRIMARY KEY, external_system text NOT NULL,"
    " target_key text NOT NULL)",
    "CREATE FUNCTION collation_probe.log_member_insert() RETURNS trigger"
    " LANGUAGE plpgsql AS $$ BEGIN"
    " INSERT INTO collation_probe.member_insert_log (external_system, target_key)"
    " VALUES (NEW.external_system, NEW.target_key);"
    " RETURN NEW; END $$",
    "CREATE TRIGGER log_member_insert BEFORE INSERT"
    " ON ops.poi_cache_target_refresh_members"
    " FOR EACH ROW EXECUTE FUNCTION collation_probe.log_member_insert()",
)


def _target_id(external_system: str, target_key: str) -> str:
    name = f"ktm-collation-probe:{external_system}:{target_key}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, name))


def _fingerprint(external_system: str, target_key: str) -> str:
    return hashlib.sha256(f"{external_system}\x00{target_key}".encode()).hexdigest()


async def _seed(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        for statement in _SURFACE_DDL:
            await connection.execute(text(statement))
        await connection.execute(
            text(
                "INSERT INTO ops.feature_reference_reconciliation_events"
                " (event_id, event_sequence) VALUES (CAST(:event_id AS uuid), 1)"
            ),
            {"event_id": _EVENT_ID},
        )
        for principal_id in _SEED_KEYS:
            params = {"principal_id": principal_id, "event_id": _EVENT_ID}
            await connection.execute(
                text(
                    "INSERT INTO ops.feature_reference_reconciliation_subscriptions"
                    " (principal_id, initial_event_sequence) VALUES (:principal_id, 0)"
                ),
                params,
            )
            await connection.execute(
                text(
                    "INSERT INTO ops.feature_reference_reconciliation_acks"
                    " (event_id, principal_id)"
                    " VALUES (CAST(:event_id AS uuid), :principal_id)"
                ),
                params,
            )
            await connection.execute(
                text(
                    "INSERT INTO ops.feature_reference_reconciliation_leases"
                    " (principal_id, worker_id, lease_epoch, acked_through_sequence)"
                    " VALUES (:principal_id, 'worker-' || :principal_id, 1, 1)"
                ),
                params,
            )
        # cache target: system·key가 모두 판별 세트인 4×4 격자다. 그래야 두 정렬 축이
        # 둘 다 collation을 탄다.
        for external_system in _SEED_KEYS:
            await connection.execute(
                text(
                    "INSERT INTO ops.poi_cache_target_streams (external_system, restore_epoch)"
                    " VALUES (:external_system, 1)"
                ),
                {"external_system": external_system},
            )
            for target_key in _SEED_KEYS:
                params = {
                    "target_id": _target_id(external_system, target_key),
                    "external_system": external_system,
                    "target_key": target_key,
                    "fingerprint": _fingerprint(external_system, target_key),
                }
                await connection.execute(
                    text(
                        "INSERT INTO ops.poi_cache_targets (target_id, external_system,"
                        " target_key, update_enabled, refresh_policy) VALUES"
                        " (CAST(:target_id AS uuid), :external_system, :target_key,"
                        " true, 'normal')"
                    ),
                    params,
                )
                await connection.execute(
                    text(
                        "INSERT INTO ops.poi_cache_target_source_heads (external_system,"
                        " target_key, target_id, state, restore_epoch, source_generation,"
                        " source_payload_fingerprint) VALUES (:external_system, :target_key,"
                        " CAST(:target_id AS uuid), 'active', 1, 1, :fingerprint)"
                    ),
                    params,
                )
                await connection.execute(
                    text(
                        "INSERT INTO ops.poi_cache_target_source_events (external_system,"
                        " target_key, restore_epoch, source_generation,"
                        " source_payload_fingerprint) VALUES (:external_system, :target_key,"
                        " 1, 1, :fingerprint)"
                    ),
                    params,
                )


def _requires_discrimination() -> bool:
    """lane이 공용 glibc digest면 판별력 없음은 skip이 아니라 실패다."""

    return postgis_image() == SHARED_GLIBC_POSTGIS_IMAGE


@pytest.fixture(scope="module")
def lane_pg_container() -> Iterator[Any]:
    """lane 이미지의 별도 cluster — conftest 공유 cluster의 상태와 섞지 않는다."""

    image = postgis_image()
    try:
        from testcontainers.postgres import PostgresContainer
    except ImportError:
        pytest.skip("testcontainers not installed")
    try:
        container = PostgresContainer(image)
    except Exception as exc:  # pragma: no cover — Docker 없음
        pytest.skip(f"PostgresContainer init failed (Docker?): {exc}")
    with container:
        yield container


@pytest.fixture(scope="module")
async def collation_engine(lane_pg_container: Any) -> AsyncIterator[AsyncEngine]:
    admin_dsn = normalize_async_dsn(lane_pg_container.get_connection_url())
    database = f"collation_orderings_{uuid4().hex}"
    dsn = make_url(admin_dsn).set(database=database).render_as_string(hide_password=False)
    admin_engine = make_async_engine(admin_dsn)
    async with admin_engine.connect() as connection:
        autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
        # prod의 Map DB처럼 template0에서 만든다 — cluster default locale을 그대로 받는다.
        await autocommit.execute(text(f'CREATE DATABASE "{database}" TEMPLATE template0'))
    await admin_engine.dispose()

    engine = make_async_engine(dsn)
    try:
        await _seed(engine)
        yield engine
    finally:
        await engine.dispose()


async def _assert_collation_discriminates(engine: AsyncEngine) -> None:
    """default collation 순서가 byte 순서와 같으면 판별력이 없다.

    alpine lane에서는 사유를 적고 skip한다. 공용 glibc lane에서는 실패한다 — 그
    lane의 존재 이유가 바로 이 판별이다.
    """

    values = ", ".join(f"('{key}')" for key in _SEED_KEYS)
    async with engine.connect() as connection:
        default_order = list(
            (
                await connection.execute(
                    text(f"SELECT key FROM (VALUES {values}) AS probe(key) ORDER BY key")
                )
            ).scalars()
        )
        c_order = list(
            (
                await connection.execute(
                    text(
                        f"SELECT key FROM (VALUES {values}) AS probe(key)"
                        ' ORDER BY key COLLATE "C"'
                    )
                )
            ).scalars()
        )
        collation = await connection.scalar(
            text("SELECT datcollate FROM pg_database WHERE datname = current_database()")
        )
    assert c_order == _BYTE_ORDER
    if default_order == c_order:
        message = (
            f"DB default collation({collation}) 순서가 byte 순서와 같다 — COLLATE \"C\""
            f" 제거 변이를 잡을 수 없다. 이미지 {postgis_image()}"
        )
        if _requires_discrimination():
            pytest.fail(f"공용 glibc lane인데 판별력이 없다: {message}", pytrace=False)
        pytest.skip(f"glibc 판별 환경이 아니므로 skip: {message}")


async def test_default_and_c_collation_orders_actually_differ(
    collation_engine: AsyncEngine,
) -> None:
    """② collation 감지 가드 — glibc lane에서 두 순서는 반드시 갈라져야 한다."""

    await _assert_collation_discriminates(collation_engine)


async def test_evidence_export_orders_principals_by_bytes(
    collation_engine: AsyncEngine,
) -> None:
    """evidence SHA-256은 행 순서에 매인다 — ACK·subscription은 byte 순서여야 한다."""

    await _assert_collation_discriminates(collation_engine)
    async with collation_engine.connect() as connection:
        exported = await export_evidence(connection)
        for relation in (
            "feature_reference_reconciliation_acks",
            "feature_reference_reconciliation_subscriptions",
        ):
            payload, digest = exported[relation]
            principals = [
                json.loads(line)["principal_id"] for line in payload.decode().splitlines()
            ]
            assert principals == _BYTE_ORDER, relation
            # digest는 byte 순서로 한 행씩 뽑아 이어 붙인 것과 같아야 한다.
            expected_rows = [
                str(
                    await connection.scalar(
                        text(
                            f"SELECT to_jsonb(row_value)::text FROM ops.{relation}"
                            " AS row_value WHERE row_value.principal_id = :principal_id"
                        ),
                        {"principal_id": principal_id},
                    )
                )
                for principal_id in _BYTE_ORDER
            ]
            expected = canonical_jsonl(expected_rows)
            assert payload == expected, relation
            assert digest.sha256 == hashlib.sha256(expected).hexdigest(), relation
        await connection.rollback()


async def test_evidence_restore_rebuilds_and_locks_leases_in_byte_order(
    collation_engine: AsyncEngine,
) -> None:
    """cursor 재구축 receipt와 lease ``FOR UPDATE`` 순서가 byte 순서다."""

    await _assert_collation_discriminates(collation_engine)
    async with collation_engine.connect() as connection:
        rebuilt, failures = await rebuild_acked_through(connection, apply=False)
        assert failures == []
        assert [cursor.principal_id for cursor in rebuilt] == _BYTE_ORDER
        # apply=True는 `_LOCK_LEASES_SQL`(… FOR UPDATE)로 읽는다 — 잠금 순서가 곧 반환 순서다.
        invalidated = await invalidate_leases(connection, apply=True)
        assert [lease.principal_id for lease in invalidated] == _BYTE_ORDER
        await connection.rollback()


async def test_curation_collection_locks_follow_python_sorted_order(
    collation_engine: AsyncEngine,
) -> None:
    """collection advisory lock은 caller의 ``sorted()``와 같은 순서로 잡혀야 한다."""

    await _assert_collation_discriminates(collation_engine)
    async with AsyncSession(collation_engine) as session, session.begin():
        expected_keys = [
            await session.scalar(
                text(
                    "SELECT pg_catalog.hashtextextended("
                    "'kortravelmap:curation-collection:' || :collection_key, 0)"
                ),
                {"collection_key": collection_key},
            )
            for collection_key in _BYTE_ORDER
        ]
        await session.execute(text("SET LOCAL search_path = collation_probe, pg_catalog"))
        await _lock_collection_keys(session, list(_SEED_KEYS))
        recorded = list(
            (
                await session.execute(
                    text(
                        "SELECT lock_key FROM collation_probe.advisory_lock_log"
                        " ORDER BY position"
                    )
                )
            ).scalars()
        )
        # 기록기가 실제로 불렸는지(빈 목록이면 진짜 lock 함수가 불린 것이다)와 순서를 함께 본다.
        assert recorded == expected_keys
        await session.rollback()


async def _captured_order(session: AsyncSession) -> list[tuple[str, str]]:
    rows = await session.execute(
        text(
            "SELECT external_system, target_key FROM collation_probe.member_insert_log"
            " ORDER BY position"
        )
    )
    return [(str(row[0]), str(row[1])) for row in rows]


async def test_cache_target_capture_by_ids_locks_and_returns_heads_in_byte_order(
    collation_engine: AsyncEngine,
) -> None:
    """``_CAPTURE_REFRESH_MEMBERS_SQL``의 ``FOR KEY SHARE OF head`` 잠금 순서와
    ``_SELECT_REFRESH_MEMBERS_SQL``의 member 반환 순서 — 두 text 축 모두 byte 순서."""

    await _assert_collation_discriminates(collation_engine)
    expected = [
        (external_system, target_key)
        for external_system in _BYTE_ORDER
        for target_key in _BYTE_ORDER
    ]
    async with AsyncSession(collation_engine) as session, session.begin():
        members = await capture_cache_target_refresh_members(
            session,
            request_id=str(uuid4()),
            target_ids=[
                _target_id(external_system, target_key)
                for external_system in _SEED_KEYS
                for target_key in _SEED_KEYS
            ],
        )
        assert await _captured_order(session) == expected
        assert [(member.external_system, member.target_key) for member in members] == expected
        await session.rollback()


async def test_cache_target_capture_by_keys_locks_and_returns_heads_in_byte_order(
    collation_engine: AsyncEngine,
) -> None:
    """``_CAPTURE_REFRESH_MEMBERS_BY_KEYS_SQL``의 잠금 순서와 member 반환 순서."""

    await _assert_collation_discriminates(collation_engine)
    external_system = _SEED_KEYS[0]
    expected = [(external_system, target_key) for target_key in _BYTE_ORDER]
    async with AsyncSession(collation_engine) as session, session.begin():
        members = await capture_cache_target_refresh_members_by_keys(
            session,
            request_id=str(uuid4()),
            external_system=external_system,
            target_keys=list(_SEED_KEYS),
        )
        assert await _captured_order(session) == expected
        assert [(member.external_system, member.target_key) for member in members] == expected
        await session.rollback()
