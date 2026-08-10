"""T-VN-34C final typed assembly, receipt, and cutover contract proof."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Awaitable, Callable
from contextlib import suppress
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[2]
_CONTRACT = _ROOT / "contracts" / "vnext" / "tvn34c-post-cutover-invariants-v1.sql"
_LEGAL_TUPLES = (
    ("active", "draft", "valid"),
    ("active", "draft", "quarantined"),
    ("active", "published", "valid"),
    ("active", "published", "quarantined"),
    ("active", "suppressed", "valid"),
    ("active", "suppressed", "quarantined"),
    ("retired", "suppressed", "valid"),
    ("retired", "suppressed", "quarantined"),
)


def _contract_queries() -> list[str]:
    content = _CONTRACT.read_text(encoding="utf-8")
    parsed = re.findall(
        r"(?ms)^(SELECT .*?); -- expect: 0 -- phase: post-cutover$",
        content,
    )
    markers = re.findall(r"(?m); -- expect: 0 -- phase: post-cutover$", content)
    assert len(markers) == len(parsed)
    return parsed


def _feature_payload(feature_id: str, kind: str) -> str:
    return json.dumps(
        {
            "feature_id": feature_id,
            "kind": kind,
            "name": f"T-VN-34C {kind}",
            "category": "tvn34c-contract",
            "address": {},
            "urls": {},
            "raw_refs": [],
        }
    )


async def _create_as_runtime(
    session: AsyncSession,
    *,
    feature_id: str,
    kind: str,
    state: tuple[str, str, str] = ("active", "published", "valid"),
) -> None:
    await session.execute(text("SET ROLE ktm_feature_runtime"))
    try:
        await session.execute(
            text(
                """
                CALL feature.create_feature_with_initial_state(
                    CAST(:payload AS jsonb), :lifecycle_state, :publication_state,
                    :quality_state, CAST(:context AS jsonb), NULL, NULL, NULL, NULL
                )
                """
            ),
            {
                "payload": _feature_payload(feature_id, kind),
                "lifecycle_state": state[0],
                "publication_state": state[1],
                "quality_state": state[2],
                "context": json.dumps(
                    {
                        "transition_kind": "initial",
                        "reason_code": "tvn34c_fixture_initial",
                        "principal": "system:tvn34c-contract",
                    }
                ),
            },
        )
    finally:
        with suppress(DBAPIError):
            await session.execute(text("RESET ROLE"))


async def _materialize_provider_as_runtime(session: AsyncSession, feature_id: str) -> None:
    await session.execute(text("SET ROLE ktm_feature_runtime"))
    try:
        await session.execute(
            text("CALL feature.materialize_provider_feature_version(:feature_id)"),
            {"feature_id": feature_id},
        )
    finally:
        with suppress(DBAPIError):
            await session.execute(text("RESET ROLE"))


async def _require_tvn34c_provenance_bridge(
    session: AsyncSession,
) -> None:
    """T-VN-36D가 제거한 임시 provenance bridge의 head 오용을 막는다."""

    if await session.scalar(text("SELECT to_regclass('feature.feature_versions') IS NULL")):
        pytest.skip(
            "T-VN-36D final fence 이후에는 T-VN-34C provenance bridge가 없다; "
            "0096→0097 전용 gate가 이 contract를 보존한다."
        )


async def _require_tvn34c_provenance_bridge_engine(
    engine: AsyncEngine,
) -> None:
    async with engine.connect() as connection:
        if await connection.scalar(
            text("SELECT to_regclass('feature.feature_versions') IS NULL")
        ):
            pytest.skip(
                "T-VN-36D final fence 이후에는 T-VN-34C provenance bridge가 없다; "
                "0096→0097 전용 gate가 이 contract를 보존한다."
            )


async def test_tvn34c_contract_queries_hold_after_final_migration(
    migrated_session: AsyncSession,
) -> None:
    """전용 0096→C artifact의 모든 catalog/data assertion은 fresh head에서 0이다."""

    await _require_tvn34c_provenance_bridge(migrated_session)
    for query in _contract_queries():
        assert await migrated_session.scalar(text(query)) == 0, query


async def test_tvn34c_invariant_parser_runs_the_dedicated_0096_to_c_path(
    pg_container: object,
) -> None:
    """전용 disposable DB에서 0096 상태를 만든 뒤 C만 적용해 artifact를 실행한다."""

    import asyncpg
    from alembic.config import Config
    from sqlalchemy.engine import make_url

    from alembic import command
    from kortravelmap.infra.db import make_async_engine, normalize_async_dsn

    # 자기 DB를 따로 만들어 upgrade하는 테스트의 선행조건(배포와 같은 principal
    # graph + migrator 자격 DSN + schema-owner role flag)은 conftest의 private
    # 함수가 아니라 공유 모듈 ``_tvn34_migration_bootstrap``이 정본이다. 그 모듈이
    # 스스로 밝히듯 같은 코드를 두 벌 두면 갈리므로, 여기서도 손으로 재현하지 않고
    # 그 한 벌을 그대로 쓴다. ``bootstrapped_migrator_dsn``은 bootstrap + migrator
    # 자격 DSN 조립을, ``alembic_schema_owner_role``은 upgrade 동안의
    # ``SET ROLE ktm_feature_schema_owner`` 전환(ADR-090)을 각각 담당한다 —
    # 이 테스트가 직접 들고 있던 role-mode env 저장/복원과 의미가 같다.
    from tests.integration._tvn34_migration_bootstrap import (
        alembic_schema_owner_role,
        bootstrapped_migrator_dsn,
    )

    raw_dsn = pg_container.get_connection_url()  # type: ignore[attr-defined]
    async_dsn = normalize_async_dsn(raw_dsn)
    database_name = f"tvn34c_cutover_{uuid4().hex}"
    base_url = make_url(async_dsn)
    admin_connection = await asyncpg.connect(
        host=base_url.host,
        port=base_url.port or 5432,
        user=base_url.username,
        password=base_url.password,
        database="postgres",
    )
    temporary_engine: AsyncEngine | None = None
    try:
        await admin_connection.execute(f"CREATE DATABASE {database_name}")
        cutover_dsn = base_url.set(database=database_name).render_as_string(
            hide_password=False
        )
        temporary_engine = make_async_engine(cutover_dsn, pool_size=1)
        config = Config(str(_ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(_ROOT / "alembic"))
        config.set_main_option("sqlalchemy.url", await bootstrapped_migrator_dsn(cutover_dsn))
        # 0096 → 0097 두 단계 모두 migration이므로 schema-owner 전환은 그 둘을
        # 함께 감싼다. 사이의 catalog 확인은 migration이 아니라 관찰이라 flag와
        # 무관하다.
        with alembic_schema_owner_role():
            await asyncio.to_thread(command.upgrade, config, "0096_tvn34_public_projection")
            async with temporary_engine.connect() as connection:
                assert await connection.scalar(
                    text("SELECT to_regclass('feature.features_detailed') IS NOT NULL")
                ) is True
            await asyncio.to_thread(command.upgrade, config, "0097_tvn34c_final_cutover")
        async with temporary_engine.connect() as connection:
            for query in _contract_queries():
                assert await connection.scalar(text(query)) == 0, query
    finally:
        if temporary_engine is not None:
            await temporary_engine.dispose()
        await admin_connection.execute(f"DROP DATABASE IF EXISTS {database_name} WITH (FORCE)")
        await admin_connection.close()


async def test_tvn34c_direct_typed_assembly_covers_eight_tuples_and_subtypes(
    migrated_session: AsyncSession,
) -> None:
    """public/materializer는 private bridge 없이 모든 legal axis/subtype을 조립한다."""

    await _require_tvn34c_provenance_bridge(migrated_session)
    tuple_ids: list[str] = []
    for number, state in enumerate(_LEGAL_TUPLES, start=1):
        feature_id = f"tvn34c-tuple-{number}-{uuid4().hex}"
        tuple_ids.append(feature_id)
        await _create_as_runtime(
            migrated_session,
            feature_id=feature_id,
            kind="place",
            state=state,
        )

    observed_tuples = {
        tuple(row)
        for row in (
            await migrated_session.execute(
                text(
                    """
                    SELECT lifecycle_state, publication_state, quality_state
                    FROM feature.features
                    WHERE feature_id = ANY(CAST(:feature_ids AS text[]))
                    """
                ),
                {"feature_ids": tuple_ids},
            )
        ).all()
    }
    assert observed_tuples == set(_LEGAL_TUPLES)

    subtype_rows = (
        (
            "place",
            "INSERT INTO feature.feature_places (feature_id, feature_uuid, kind, place_kind) "
            "SELECT feature_id, feature_uuid, kind, 'cafe' FROM feature.features "
            "WHERE feature_id = :feature_id",
            "place_kind",
            "cafe",
        ),
        (
            "event",
            "INSERT INTO feature.feature_events (feature_id, feature_uuid, kind, event_kind) "
            "SELECT feature_id, feature_uuid, kind, 'festival' FROM feature.features "
            "WHERE feature_id = :feature_id",
            "event_kind",
            "festival",
        ),
        (
            "notice",
            "INSERT INTO feature.feature_notices (feature_id, feature_uuid, kind, notice_type) "
            "SELECT feature_id, feature_uuid, kind, 'alert' FROM feature.features "
            "WHERE feature_id = :feature_id",
            "notice_type",
            "alert",
        ),
        (
            "route",
            "INSERT INTO feature.feature_routes "
            "(feature_id, feature_uuid, kind, geom, route_type) "
            "SELECT feature_id, feature_uuid, kind, "
            "x_extension.ST_GeomFromText('MULTILINESTRING((127 37,127.1 37.1))', 4326), "
            "'walk' FROM feature.features WHERE feature_id = :feature_id",
            "route_type",
            "walk",
        ),
        (
            "area",
            "INSERT INTO feature.feature_areas "
            "(feature_id, feature_uuid, kind, geom, area_kind) "
            "SELECT feature_id, feature_uuid, kind, "
            "x_extension.ST_GeomFromText('POLYGON((127 37,127.1 37,127.1 37.1,127 37))', 4326), "
            "'district' FROM feature.features WHERE feature_id = :feature_id",
            "area_kind",
            "district",
        ),
    )
    feature_ids: list[str] = []
    expected_detail: dict[str, tuple[str, str]] = {}
    for kind, insert_sql, detail_key, detail_value in subtype_rows:
        feature_id = f"tvn34c-subtype-{kind}-{uuid4().hex}"
        feature_ids.append(feature_id)
        expected_detail[feature_id] = (detail_key, detail_value)
        await _create_as_runtime(migrated_session, feature_id=feature_id, kind=kind)
        await migrated_session.execute(text(insert_sql), {"feature_id": feature_id})
        await _materialize_provider_as_runtime(migrated_session, feature_id)

    public_rows = (
        await migrated_session.execute(
            text(
                """
                SELECT feature_id, kind, detail, geom
                FROM feature.public_features
                WHERE feature_id = ANY(CAST(:feature_ids AS text[]))
                ORDER BY feature_id
                """
            ),
            {"feature_ids": feature_ids},
        )
    ).mappings().all()
    assert len(public_rows) == len(subtype_rows)
    for row in public_rows:
        detail_key, detail_value = expected_detail[row["feature_id"]]
        assert row["detail"][detail_key] == detail_value
        if row["kind"] in {"route", "area"}:
            assert row["geom"] is not None
        else:
            assert row["geom"] is None

    snapshot_rows = (
        await migrated_session.execute(
            text(
                """
                SELECT payload
                FROM feature.feature_versions
                WHERE feature_id = ANY(CAST(:feature_ids AS text[])) AND version = 0
                """
            ),
            {"feature_ids": feature_ids},
        )
    ).scalars().all()
    assert len(snapshot_rows) == len(subtype_rows)
    for payload in snapshot_rows:
        assert {"lifecycle_state", "publication_state", "quality_state"} <= set(payload)
        assert {"data_origin", "data_version", "detail"} <= set(payload)
        assert not {
            "status",
            "deleted_at",
            "user_change_kind",
            "user_change_request_id",
        } & set(payload)


async def test_tvn34c_user_receipt_is_request_bound_immutable_and_concurrent(
    migrated_engine: AsyncEngine,
) -> None:
    """동시 같은 request materialization은 하나의 durable receipt만 남긴다."""

    await _require_tvn34c_provenance_bridge_engine(migrated_engine)
    feature_id = f"tvn34c-receipt-{uuid4().hex}"
    request_id = uuid4()
    async with AsyncSession(migrated_engine) as setup_session, setup_session.begin():
        await _create_as_runtime(setup_session, feature_id=feature_id, kind="place")
        await setup_session.execute(
            text(
                """
                INSERT INTO ops.feature_change_requests (
                    request_id, feature_id, action, state, review_mode,
                    base_row_revision, payload, reason, requested_by
                ) VALUES (
                    CAST(:request_id AS uuid), :feature_id, 'update', 'applied', 'immediate',
                    1, '{}'::jsonb, 'concurrent receipt fixture', 'admin:tvn34c-contract'
                )
                """
            ),
            {"request_id": str(request_id), "feature_id": feature_id},
        )

    async def materialize_once() -> tuple[str, int]:
        async with AsyncSession(migrated_engine) as session, session.begin():
            await session.execute(text("SET LOCAL ROLE ktm_feature_runtime"))
            row = (
                await session.execute(
                    text(
                        """
                        CALL feature.materialize_user_feature_change_provenance(
                            :feature_id, 'update', CAST(:request_id AS uuid),
                            'concurrent receipt fixture', 'admin:tvn34c-contract', 1, NULL, NULL
                        )
                        """
                    ),
                    {"feature_id": feature_id, "request_id": str(request_id)},
                )
            ).one()
            return row.o_feature_id, row.o_row_revision

    receipts = await asyncio.gather(materialize_once(), materialize_once())
    assert receipts == [(feature_id, 2), (feature_id, 2)]

    async with AsyncSession(migrated_engine) as verify_session:
        receipt = (
            await verify_session.execute(
                text(
                    """
                    SELECT feature_id, request_id::text, origin, change_kind,
                           payload ->> 'row_revision'
                    FROM feature.feature_versions
                    WHERE feature_id = :feature_id AND request_id = CAST(:request_id AS uuid)
                    """
                ),
                {"feature_id": feature_id, "request_id": str(request_id)},
            )
        ).one()
        assert tuple(receipt) == (feature_id, str(request_id), "user_request", "update", "2")
        with pytest.raises(DBAPIError) as mutate:
            async with verify_session.begin_nested():
                await verify_session.execute(
                    text(
                        "UPDATE feature.feature_versions SET created_by = 'forged' "
                        "WHERE feature_id = :feature_id AND request_id = CAST(:request_id AS uuid)"
                    ),
                    {"feature_id": feature_id, "request_id": str(request_id)},
                )
        assert getattr(mutate.value.orig, "sqlstate", None) == "42501"
        await verify_session.execute(text("SET LOCAL ROLE ktm_feature_runtime"))
        for statement in (
            "UPDATE ops.feature_change_requests SET state = 'rejected' "
            "WHERE request_id = CAST(:request_id AS uuid)",
            "DELETE FROM ops.feature_change_requests "
            "WHERE request_id = CAST(:request_id AS uuid)",
        ):
            with pytest.raises(DBAPIError) as request_mutation:
                async with verify_session.begin_nested():
                    await verify_session.execute(text(statement), {"request_id": str(request_id)})
            assert getattr(request_mutation.value.orig, "sqlstate", None) == "42501"


async def test_tvn34c_request_lock_serializes_first_receipt_against_request_mutation(
    migrated_engine: AsyncEngine,
) -> None:
    """first receipt는 locked applied request만 받아 immutable binding을 만든다."""

    await _require_tvn34c_provenance_bridge_engine(migrated_engine)
    feature_id = f"tvn34c-receipt-race-{uuid4().hex}"
    request_id = uuid4()
    async with AsyncSession(migrated_engine) as setup_session, setup_session.begin():
        await _create_as_runtime(setup_session, feature_id=feature_id, kind="place")
        await setup_session.execute(
            text(
                """
                INSERT INTO ops.feature_change_requests (
                    request_id, feature_id, action, state, review_mode,
                    base_row_revision, payload, reason, requested_by
                ) VALUES (
                    CAST(:request_id AS uuid), :feature_id, 'update', 'applied', 'immediate',
                    1, '{}'::jsonb, 'receipt race fixture', 'admin:tvn34c-contract'
                )
                """
            ),
            {"request_id": str(request_id), "feature_id": feature_id},
        )

    async with AsyncSession(migrated_engine) as mutator_session:
        await mutator_session.begin()
        await mutator_session.execute(
            text(
                "UPDATE ops.feature_change_requests SET state = 'rejected' "
                "WHERE request_id = CAST(:request_id AS uuid)"
            ),
            {"request_id": str(request_id)},
        )

        async def materialize() -> None:
            async with AsyncSession(migrated_engine) as session, session.begin():
                await session.execute(text("SET LOCAL ROLE ktm_feature_runtime"))
                await session.execute(
                    text(
                        """
                        CALL feature.materialize_user_feature_change_provenance(
                            :feature_id, 'update', CAST(:request_id AS uuid),
                            'receipt race fixture', 'admin:tvn34c-contract', 1, NULL, NULL
                        )
                        """
                    ),
                    {"feature_id": feature_id, "request_id": str(request_id)},
                )

        materialization = asyncio.create_task(materialize())
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(asyncio.shield(materialization), timeout=0.15)
        await mutator_session.commit()
        with pytest.raises(DBAPIError) as rejected:
            await materialization
        assert getattr(rejected.value.orig, "sqlstate", None) == "23514"

    async with AsyncSession(migrated_engine) as verify_session:
        receipt_count = await verify_session.scalar(
            text(
                """
                SELECT count(*) FROM feature.feature_versions
                WHERE feature_id = :feature_id
                  AND request_id = CAST(:request_id AS uuid)
                """
            ),
            {"feature_id": feature_id, "request_id": str(request_id)},
        )
    assert receipt_count == 0


async def test_tvn34c_admin_reactivation_derives_exact_current_source_evidence(
    migrated_session: AsyncSession,
) -> None:
    """관리자 재활성화는 링크·current head를 검증하고 DB 산출 causation만 감사한다."""

    suffix = uuid4().hex
    feature_id = f"tvn34c-reactivate-{suffix}"
    entity_key = f"tvn34c-entity-{suffix}"
    record_key = f"tvn34c-record-{suffix}"
    raw_payload_hash = suffix * 2
    dataset_id = int(
        (
            await migrated_session.execute(
                text(
                    """
                    INSERT INTO provider_sync.provider_datasets (
                        provider, dataset_key, display_name, source_kind
                    ) VALUES ('tvn34c', :dataset_key, 'T-VN-34C contract', 'manual')
                    RETURNING provider_dataset_id
                    """
                ),
                {"dataset_key": suffix},
            )
        ).scalar_one()
    )
    await migrated_session.execute(
        text(
            """
            INSERT INTO provider_sync.source_entities (
                source_entity_key, provider_dataset_id, source_entity_type, source_entity_id,
                first_seen_at, last_seen_at
            ) VALUES (:entity_key, :dataset_id, 'place', :source_entity_id, now(), now())
            """
        ),
        {"entity_key": entity_key, "dataset_id": dataset_id, "source_entity_id": suffix},
    )
    await migrated_session.execute(
        text(
            """
            INSERT INTO provider_sync.source_records (
                source_record_key, source_entity_key, raw_data, raw_payload_hash, fetched_at
            ) VALUES (:record_key, :entity_key, '{}'::jsonb, :raw_payload_hash, now())
            """
        ),
        {
            "record_key": record_key,
            "entity_key": entity_key,
            "raw_payload_hash": raw_payload_hash,
        },
    )
    await migrated_session.execute(
        text(
            """
            INSERT INTO provider_sync.source_entity_heads (
                source_entity_key, current_source_record_key, observed_at
            ) VALUES (:entity_key, :record_key, now())
            """
        ),
        {"entity_key": entity_key, "record_key": record_key},
    )
    await _create_as_runtime(
        migrated_session,
        feature_id=feature_id,
        kind="place",
        state=("retired", "suppressed", "valid"),
    )
    await migrated_session.execute(
        text(
            """
            INSERT INTO provider_sync.source_links (
                feature_id, source_entity_key, source_role, match_method, confidence
            ) VALUES (:feature_id, :entity_key, 'primary', 'fixture', 100)
            """
        ),
        {"feature_id": feature_id, "entity_key": entity_key},
    )

    await migrated_session.execute(text("SET ROLE ktm_feature_runtime"))
    try:
        with pytest.raises(DBAPIError) as mismatch:
            async with migrated_session.begin_nested():
                await migrated_session.execute(
                    text(
                        """
                        CALL feature.reactivate_admin_feature_state(
                            :feature_id, :dataset_id, :entity_key, 'wrong-record', 1,
                            'reactivate_after_evidence', 'admin:tvn34c-contract', NULL, NULL, NULL
                        )
                        """
                    ),
                    {"feature_id": feature_id, "dataset_id": dataset_id, "entity_key": entity_key},
                )
        assert getattr(mismatch.value.orig, "sqlstate", None) == "23514"

        result = (
            await migrated_session.execute(
                text(
                    """
                    CALL feature.reactivate_admin_feature_state(
                        :feature_id, :dataset_id, :entity_key, :record_key, 1,
                        'reactivate_after_evidence', 'admin:tvn34c-contract', NULL, NULL, NULL
                    )
                    """
                ),
                {
                    "feature_id": feature_id,
                    "dataset_id": dataset_id,
                    "entity_key": entity_key,
                    "record_key": record_key,
                },
            )
        ).one()
        assert result.o_feature_id == feature_id
        assert result.o_row_revision == 2
        assert result.o_transition_id is not None
    finally:
        with suppress(DBAPIError):
            await migrated_session.execute(text("RESET ROLE"))

    audit = (
        await migrated_session.execute(
            text(
                """
                SELECT principal, causation_ref, to_lifecycle_state, to_publication_state,
                       to_quality_state
                FROM feature.feature_state_transitions
                WHERE feature_id = :feature_id AND row_revision = 2
                """
            ),
            {"feature_id": feature_id},
        )
    ).one()
    assert audit.principal == "admin:tvn34c-contract"
    assert json.loads(audit.causation_ref) == {
        "provider_dataset_id": dataset_id,
        "source_entity_key": entity_key,
        "source_record_key": record_key,
        "raw_payload_hash": raw_payload_hash,
    }
    assert tuple(audit[2:]) == ("active", "suppressed", "valid")


async def test_tvn34c_provider_evidence_lock_rejects_head_advance_races(
    migrated_engine: AsyncEngine,
) -> None:
    """admin/provider lifecycle 모두 locked current head만 audit evidence로 쓴다."""

    suffix = uuid4().hex
    dataset_key = f"tvn34c-race-{suffix}"
    entity_key = f"tvn34c-race-entity-{suffix}"
    record_one = f"tvn34c-race-record-one-{suffix}"
    record_two = f"tvn34c-race-record-two-{suffix}"
    admin_feature_id = f"tvn34c-race-admin-{suffix}"
    provider_feature_id = f"tvn34c-race-provider-{suffix}"
    async with AsyncSession(migrated_engine) as setup_session, setup_session.begin():
        dataset_id = int(
            (
                await setup_session.execute(
                    text(
                        """
                        INSERT INTO provider_sync.provider_datasets (
                            provider, dataset_key, display_name, source_kind
                        ) VALUES ('tvn34c-race', :dataset_key, 'T-VN-34C race', 'manual')
                        RETURNING provider_dataset_id
                        """
                    ),
                    {"dataset_key": dataset_key},
                )
            ).scalar_one()
        )
        await setup_session.execute(
            text(
                """
                INSERT INTO provider_sync.source_entities (
                    source_entity_key, provider_dataset_id, source_entity_type, source_entity_id,
                    first_seen_at, last_seen_at
                ) VALUES (:entity_key, :dataset_id, 'place', :source_entity_id, now(), now())
                """
            ),
            {"entity_key": entity_key, "dataset_id": dataset_id, "source_entity_id": suffix},
        )
        for record_key, payload_hash in ((record_one, f"{suffix}a"), (record_two, f"{suffix}b")):
            await setup_session.execute(
                text(
                    """
                    INSERT INTO provider_sync.source_records (
                        source_record_key, source_entity_key, raw_data, raw_payload_hash, fetched_at
                    ) VALUES (:record_key, :entity_key, '{}'::jsonb, :payload_hash, now())
                    """
                ),
                {
                    "record_key": record_key,
                    "entity_key": entity_key,
                    "payload_hash": payload_hash,
                },
            )
        await setup_session.execute(
            text(
                """
                INSERT INTO provider_sync.source_entity_heads (
                    source_entity_key, current_source_record_key, observed_at
                ) VALUES (:entity_key, :record_key, now())
                """
            ),
            {"entity_key": entity_key, "record_key": record_one},
        )
        await _create_as_runtime(
            setup_session,
            feature_id=admin_feature_id,
            kind="place",
            state=("retired", "suppressed", "valid"),
        )
        await _create_as_runtime(setup_session, feature_id=provider_feature_id, kind="place")
        for feature_id in (admin_feature_id, provider_feature_id):
            await setup_session.execute(
                text(
                    """
                    INSERT INTO provider_sync.source_links (
                        feature_id, source_entity_key, source_role, match_method, confidence
                    ) VALUES (:feature_id, :entity_key, 'primary', 'fixture', 100)
                    """
                ),
                {"feature_id": feature_id, "entity_key": entity_key},
            )

    async def _advance_head_while(
        call: Callable[[], Awaitable[None]], *, link_feature_id: str
    ) -> DBAPIError:
        async with AsyncSession(migrated_engine) as head_session:
            await head_session.begin()
            await head_session.execute(
                text(
                    """
                    UPDATE provider_sync.source_entity_heads
                    SET current_source_record_key = :record_two, observed_at = now()
                    WHERE source_entity_key = :entity_key
                    """
                ),
                {"record_two": record_two, "entity_key": entity_key},
            )
            task = asyncio.create_task(call())
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(asyncio.shield(task), timeout=0.15)
            # A bundle advances the entity head and subsequently upserts the
            # source link.  The state command is deliberately waiting on the
            # head here, so this UPDATE must not wait on a link lock.  The
            # former link→head helper order formed a real 40P01 cycle.
            await head_session.execute(text("SET LOCAL lock_timeout = '300ms'"))
            await head_session.execute(
                text(
                    """
                    UPDATE provider_sync.source_links
                    SET confidence = confidence
                    WHERE feature_id = :feature_id
                      AND source_entity_key = :entity_key
                    """
                ),
                {"feature_id": link_feature_id, "entity_key": entity_key},
            )
            await head_session.commit()
            with pytest.raises(DBAPIError) as rejected:
                await task
            return rejected.value

    async def admin_reactivation() -> None:
        async with AsyncSession(migrated_engine) as session, session.begin():
            await session.execute(text("SET LOCAL ROLE ktm_feature_runtime"))
            await session.execute(
                text(
                    """
                    CALL feature.reactivate_admin_feature_state(
                        :feature_id, :dataset_id, :entity_key, :record_key, 1,
                        'current_source_required', 'admin:tvn34c-race', NULL, NULL, NULL
                    )
                    """
                ),
                {
                    "feature_id": admin_feature_id,
                    "dataset_id": dataset_id,
                    "entity_key": entity_key,
                    "record_key": record_one,
                },
            )

    admin_error = await _advance_head_while(
        admin_reactivation, link_feature_id=admin_feature_id
    )
    assert getattr(admin_error.orig, "sqlstate", None) == "23514"

    async with AsyncSession(migrated_engine) as reset_session, reset_session.begin():
        await reset_session.execute(
            text(
                """
                UPDATE provider_sync.source_entity_heads
                SET current_source_record_key = :record_one, observed_at = now()
                WHERE source_entity_key = :entity_key
                """
            ),
            {"record_one": record_one, "entity_key": entity_key},
        )

    async def provider_retirement() -> None:
        async with AsyncSession(migrated_engine) as session, session.begin():
            await session.execute(text("SET LOCAL ROLE ktm_feature_runtime"))
            await session.execute(
                text(
                    """
                    CALL feature.transition_feature_state(
                        :feature_id, 'retired', 'suppressed', 'valid', 1,
                        CAST(:context AS jsonb), NULL, NULL
                    )
                    """
                ),
                {
                    "feature_id": provider_feature_id,
                    "context": json.dumps(
                        {
                            "transition_kind": "provider_sync",
                            "reason_code": "provider_retire",
                            "provider_dataset_id": dataset_id,
                            "source_entity_key": entity_key,
                            "source_record_key": record_one,
                        }
                    ),
                },
            )

    provider_error = await _advance_head_while(
        provider_retirement, link_feature_id=provider_feature_id
    )
    assert getattr(provider_error.orig, "sqlstate", None) == "23514"

    async with AsyncSession(migrated_engine) as verify_session:
        states = (
            await verify_session.execute(
                text(
                    """
                    SELECT feature_id, lifecycle_state, row_revision
                    FROM feature.features
                    WHERE feature_id = ANY(CAST(:feature_ids AS text[]))
                    ORDER BY feature_id
                    """
                ),
                {"feature_ids": [admin_feature_id, provider_feature_id]},
            )
        ).all()
    assert {str(row.feature_id): (row.lifecycle_state, row.row_revision) for row in states} == {
        admin_feature_id: ("retired", 1),
        provider_feature_id: ("active", 1),
    }


@pytest.mark.parametrize(
    "transition_kind",
    ["admin", "user_request", "merge", "system", "quality_validation"],
)
async def test_tvn34c_generic_non_provider_retirement_writes_lifecycle_fence(
    migrated_session: AsyncSession,
    transition_kind: str,
) -> None:
    """Generic non-provider transitions cannot leave a retirement unfenced."""

    feature_id = f"tvn34c-retirement-fence-{transition_kind}"
    await _create_as_runtime(migrated_session, feature_id=feature_id, kind="place")
    await migrated_session.execute(text("SET ROLE ktm_feature_runtime"))
    try:
        await migrated_session.execute(
            text(
                """
                CALL feature.transition_feature_state(
                    :feature_id, 'retired', 'suppressed', 'valid', 1,
                    CAST(:context AS jsonb), NULL, NULL
                )
                """
            ),
            {
                "feature_id": feature_id,
                "context": json.dumps(
                    {
                        "transition_kind": transition_kind,
                        "reason_code": f"{transition_kind}_retire",
                        "principal": "runtime:tvn34c-fence",
                    }
                ),
            },
        )
    finally:
        with suppress(DBAPIError):
            await migrated_session.execute(text("RESET ROLE"))

    override = (
        await migrated_session.execute(
            text(
                """
                SELECT override_value, prevent_provider_reactivation
                FROM ops.feature_overrides
                WHERE feature_id = :feature_id
                  AND field_path = 'lifecycle_state'
                  AND status = 'active'
                """
            ),
            {"feature_id": feature_id},
        )
    ).one()
    assert tuple(override) == ("retired", True)
