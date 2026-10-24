"""고유 owned PostGIS의 실제 full bootstrap에서 scalar cutover를 검증한다.

공유 migrated_engine을 활성화해서 다른 테스트의 legacy writer를 바꾸지 않는다.
운영/외부 DSN은 사용하지 않으며 이 파일의 container만 생성·회수한다.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from alembic.config import Config
from psycopg import sql
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.dto.provider_field_presence import ProviderFieldPresence
from kortravelmap.infra.db import make_async_engine, normalize_async_dsn
from kortravelmap.infra.provider_field_candidates import (
    arm_provider_field_shadow,
    capture_provider_field_candidates,
)
from tests.integration._application_300_bootstrap import (
    _TEST_RUNTIME_PASSWORD,
    upgrade_head_with_application_300_bootstrap,
)
from tests.integration._postgis_image import resolve_postgis_image

pytestmark = pytest.mark.integration
_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def scalar_container():
    from testcontainers.postgres import PostgresContainer

    if os.environ.get("DOCKER_HOST") and not os.environ["DOCKER_HOST"].startswith("unix://"):
        raise RuntimeError("scalar projection tests require the local owned Docker daemon")
    identity = uuid4().hex
    container = (
        PostgresContainer(
            resolve_postgis_image(),
            username="scalar_admin",
            password="scalar-" + identity,
            dbname="scalar_template",
        )
        .with_name("kt-map-scalar-" + identity)
        .with_kwargs(
            labels={"codex.scalar-projection": identity},
            mem_limit="1536m",
            memswap_limit="1536m",
            nano_cpus=2_000_000_000,
            pids_limit=256,
        )
    )
    wrapped = None
    try:
        container.start()
        wrapped = container.get_wrapped_container()
        wrapped.reload()
        assert wrapped.attrs["Config"]["Labels"]["codex.scalar-projection"] == identity
        admin = make_url(container.get_connection_url()).set(
            drivername="postgresql", database="postgres"
        )
        database = "scalar_" + identity
        with psycopg.connect(admin.render_as_string(False), autocommit=True) as connection:
            connection.execute(
                sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(database))
            )
        container.dbname = database
        yield container
    finally:
        if wrapped is None:
            try:
                wrapped = container.get_wrapped_container()
            except RuntimeError:
                wrapped = None
        if wrapped is not None:
            wrapped.reload()
            if wrapped.attrs["Config"]["Labels"].get("codex.scalar-projection") != identity:
                raise RuntimeError("refusing cleanup of an unowned scalar container")
            container.stop()


@pytest.fixture(scope="module")
async def scalar_engines(scalar_container):
    dsn = normalize_async_dsn(scalar_container.get_connection_url())
    config = Config(str(_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_ROOT / "alembic"))
    await upgrade_head_with_application_300_bootstrap(config, dsn)
    # 배포의 정본 post-migration ACL 단계. 임의 GRANT로 새 루틴 검사를 우회하지 않는다.
    from kortravelmap.infra.runtime_privileges import reconcile_runtime_privileges

    runtime_url = make_url(dsn).set(username="ktm_feature_service", password=_TEST_RUNTIME_PASSWORD)
    previous = os.environ.get("KOR_TRAVEL_MAP_PG_DSN")
    os.environ["KOR_TRAVEL_MAP_PG_DSN"] = runtime_url.render_as_string(False)
    try:
        await reconcile_runtime_privileges()
    finally:
        if previous is None:
            os.environ.pop("KOR_TRAVEL_MAP_PG_DSN", None)
        else:
            os.environ["KOR_TRAVEL_MAP_PG_DSN"] = previous
    admin = make_async_engine(dsn, pool_size=2)
    runtime = make_async_engine(runtime_url.render_as_string(False), pool_size=2)
    try:
        yield admin, runtime
    finally:
        await runtime.dispose()
        await admin.dispose()


async def _seed(engine, *, reverse: bool = False, unknown: bool = False):
    identity = uuid4().hex
    feature = str(uuid4())
    datasets = []
    entities = []
    async with AsyncSession(engine) as session, session.begin():
        await session.execute(text("SELECT ops.lock_scoped_feature_write_protocol(true)"))
        await session.execute(text("SET LOCAL statement_timeout='5s'"))
        await session.execute(
            text("""INSERT INTO feature.features(
            feature_id,kind,name,category,lifecycle_state,publication_state,quality_state)
            VALUES(CAST(:feature AS uuid),'place','before','01010100',
                'active','published','valid')"""),
            {"feature": feature},
        )
        await session.execute(
            text("""INSERT INTO feature.feature_places(feature_id,kind,place_kind)
            VALUES(CAST(:feature AS uuid),'place','tourism')"""),
            {"feature": feature},
        )
        for index in range(2):
            dataset = int(
                await session.scalar(
                    text("""INSERT INTO provider_sync.provider_datasets(
                provider,dataset_key,display_name,source_kind)
                VALUES(:provider,:key,'scalar fixture','manual') RETURNING provider_dataset_id"""),
                    {"provider": f"scalar-{index}", "key": identity},
                )
            )
            entity = f"scalar-{identity}-{index}"
            for statement in [
                """INSERT INTO provider_sync.source_entities(source_entity_key,provider_dataset_id,
                    source_entity_type,source_entity_id,first_seen_at,last_seen_at)
                    VALUES(:entity,:dataset,'place',:entity,now(),now())""",
                """INSERT INTO provider_sync.source_records(source_record_key,source_entity_key,
                    raw_data,raw_payload_hash,fetched_at)
                    VALUES(:record,:entity,'{}',:hash,now())""",
                """INSERT INTO provider_sync.source_entity_heads(
                    source_entity_key,current_source_record_key,
                    observed_at) VALUES(:entity,:record,now())""",
                """INSERT INTO provider_sync.source_links(feature_id,source_entity_key,source_role,
                    match_method,confidence) VALUES(
                    CAST(:feature AS uuid),:entity,'primary','fixture',100)""",
            ]:
                await session.execute(
                    text(statement),
                    {
                        "entity": entity,
                        "dataset": dataset,
                        "record": entity + "-r1",
                        "hash": str(index + 1) * 64,
                        "feature": feature,
                    },
                )
            fields = [
                {
                    "field_path": path,
                    "provider_rank": 10 + index * 10,
                    "omitted_policy": "carry_forward",
                    "null_policy": "value",
                }
                for path in ["core.name", "place.phones"]
            ]
            await session.execute(
                text("""CALL feature.register_provider_field_shadow_policy(
                1,:dataset,'scalar-v1',CAST(:fields AS jsonb))"""),
                {"dataset": dataset, "fields": json.dumps(fields)},
            )
            datasets.append(dataset)
            entities.append(entity)
        arm_provider_field_shadow(session, 1)
        for index in [1, 0] if reverse else [0, 1]:
            values = {"core.name": f"winner-{index}", "place.phones": [f"010-{index}"]}
            result = await capture_provider_field_candidates(
                session,
                feature_id=feature,
                dataset_id=datasets[index],
                entity_key=entities[index],
                record_key=entities[index] + "-r1",
                values=json.dumps(values),
                geometry_wkt="{}",
                presence=None
                if unknown and index == 1
                else ProviderFieldPresence(
                    normalizer_revision="scalar-v1", supplied_fields=set(values)
                ),
            )
            assert result is not None
    return feature, datasets, entities


async def _activate(engine, feature):
    async with AsyncSession(engine) as session, session.begin():
        await session.execute(text("SET LOCAL lock_timeout='2s'"))
        await session.execute(text("SET LOCAL statement_timeout='10s'"))
        await session.execute(
            text("""CALL feature.activate_provider_field_policy(
            CAST(:feature AS uuid),1,ARRAY['core.name','place.phones'])"""),
            {"feature": feature},
        )


async def test_off_has_no_scalar_triggers_or_active_policies(scalar_engines):
    admin, _ = scalar_engines
    async with AsyncSession(admin) as session:
        assert (
            await session.scalar(
                text("SELECT count(*) FROM pg_trigger WHERE tgname LIKE 'trg_scalar_%'")
            )
            == 0
        )
        assert (
            await session.scalar(
                text("SELECT count(*) FROM feature.provider_field_active_policies")
            )
            == 0
        )


@pytest.mark.parametrize("reverse", [False, True])
async def test_capture_order_does_not_change_explicit_rank_winner(scalar_engines, reverse):
    admin, _ = scalar_engines
    feature, datasets, _ = await _seed(admin, reverse=reverse)
    await _activate(admin, feature)
    async with AsyncSession(admin) as session:
        row = (
            await session.execute(
                text("""SELECT name,phones FROM feature.features
            JOIN feature.feature_places USING(feature_id) WHERE feature_id=CAST(:id AS uuid)"""),
                {"id": feature},
            )
        ).one()
        assert tuple(row) == ("winner-0", ["010-0"])
        assert (
            await session.execute(
                text("""SELECT DISTINCT provider_dataset_id
            FROM feature.feature_base_field_values WHERE feature_id=CAST(:id AS uuid)"""),
                {"id": feature},
            )
        ).scalars().all() == [datasets[0]]


async def test_unknown_source_cannot_activate_or_change_epoch(scalar_engines):
    from sqlalchemy.exc import DBAPIError

    admin, _ = scalar_engines
    feature, _, _ = await _seed(admin, unknown=True)
    async with AsyncSession(admin) as session:
        before = await session.scalar(text("SELECT epoch FROM feature.provider_field_policy_epoch"))
    with pytest.raises(DBAPIError, match="candidate is missing"):
        await _activate(admin, feature)
    async with AsyncSession(admin) as session:
        assert (
            await session.scalar(text("SELECT epoch FROM feature.provider_field_policy_epoch"))
            == before
        )
        assert (
            await session.scalar(
                text(
                    "SELECT count(*) FROM feature.provider_field_active_policies "
                    "WHERE feature_id=CAST(:id AS uuid)"
                ),
                {"id": feature},
            )
            == 0
        )
        assert (
            await session.scalar(
                text("SELECT name FROM feature.features WHERE feature_id=CAST(:id AS uuid)"),
                {"id": feature},
            )
            == "before"
        )


async def _plan(runtime, feature, dataset):
    from kortravelmap.infra.scoped_feature_writes import (
        ScopedWriteDependency,
        append_scoped_feature_write_manifest,
        claim_scoped_feature_write,
        seal_scoped_feature_write_manifest,
    )

    attempt, owner = uuid4(), uuid4()
    async with AsyncSession(runtime) as session, session.begin():
        assert tuple((await session.execute(text("SELECT session_user,current_user"))).one()) == (
            "ktm_feature_service",
            "ktm_feature_service",
        )
        revision = await session.scalar(
            text("SELECT row_revision FROM feature.features WHERE feature_id=CAST(:id AS uuid)"),
            {"id": feature},
        )
        heads = (
            await session.execute(
                text("""SELECT source_entity_key,current_source_record_key
            FROM provider_sync.source_links
            JOIN provider_sync.source_entity_heads USING(source_entity_key)
            WHERE feature_id=CAST(:id AS uuid) ORDER BY source_entity_key COLLATE "C"
            """),
                {"id": feature},
            )
        ).all()
        membership = await session.scalar(
            text("SELECT ops.scoped_feature_write_membership_digest(CAST(:id AS uuid))"),
            {"id": feature},
        )
        members = [
            ScopedWriteDependency(i, "source_head", entity, record)
            for i, (entity, record) in enumerate(heads)
        ]
        members.extend(
            [
                ScopedWriteDependency(len(members), "feature", feature, str(revision)),
                ScopedWriteDependency(len(members) + 1, "feature_membership", feature, membership),
            ]
        )
        await claim_scoped_feature_write(
            session,
            attempt_id=attempt,
            owner=owner,
            dataset_id=dataset,
            idempotency_key=uuid4().hex,
            regions=(),
            input_digest="a" * 64,
            expected_members=len(members),
        )
        await append_scoped_feature_write_manifest(
            session, attempt_id=attempt, owner=owner, members=members
        )
        digest = await seal_scoped_feature_write_manifest(session, attempt_id=attempt, owner=owner)
    return attempt, owner, digest


async def _refresh(runtime, feature, dataset, entity, values, *, project=True):
    import hashlib

    from kortravelmap.infra.provider_field_candidates import (
        lock_provider_field_policy_epoch,
        recompute_provider_field_candidates,
    )
    from kortravelmap.infra.scoped_feature_writes import (
        begin_scoped_feature_write,
        finish_scoped_feature_write,
        lock_scoped_feature_write_protocol,
    )

    attempt, owner, digest = await _plan(runtime, feature, dataset)
    record = entity + "-" + uuid4().hex[:8]
    payload = json.dumps(values, sort_keys=True)
    source_hash = hashlib.sha256(payload.encode()).hexdigest()
    async with AsyncSession(runtime) as session, session.begin():
        await session.execute(text("SET LOCAL statement_timeout='8s'"))
        await lock_scoped_feature_write_protocol(session, exclusive=False)
        await lock_provider_field_policy_epoch(session)
        await begin_scoped_feature_write(
            session, attempt_id=attempt, owner=owner, manifest_digest=digest
        )
        await session.execute(
            text("""SELECT feature.assert_scoped_provider_scalar_target(
            :attempt,CAST(:feature AS uuid),:dataset,:entity,1)"""),
            {"attempt": attempt, "feature": feature, "dataset": dataset, "entity": entity},
        )
        await session.execute(
            text("""INSERT INTO provider_sync.source_records(
            source_record_key,source_entity_key,raw_data,raw_payload_hash,fetched_at)
            VALUES(:record,:entity,CAST(:raw AS jsonb),:hash,clock_timestamp())"""),
            {"record": record, "entity": entity, "raw": payload, "hash": source_hash},
        )
        await session.execute(
            text("""UPDATE provider_sync.source_entity_heads
            SET current_source_record_key=:record,observed_at=clock_timestamp()
            WHERE source_entity_key=:entity"""),
            {"record": record, "entity": entity},
        )
        if project:
            arm_provider_field_shadow(session, 1)
            result = await capture_provider_field_candidates(
                session,
                feature_id=feature,
                dataset_id=dataset,
                entity_key=entity,
                record_key=record,
                values=payload,
                geometry_wkt="{}",
                presence=ProviderFieldPresence(
                    normalizer_revision="scalar-v1", supplied_fields=set(values)
                ),
                attempt_id=str(attempt),
            )
            assert result is not None
            assert result.unresolved_count == 0
            await recompute_provider_field_candidates(
                session, attempt_id=str(attempt), feature_id=feature, policy_revision=1
            )
        await finish_scoped_feature_write(
            session, attempt_id=attempt, owner=owner, result_digest="b" * 64
        )
    return record, source_hash


@pytest.mark.parametrize("order", [(0, 1), (1, 0)])
async def test_shared_refresh_order_preserves_r1_phone_and_r2_name(scalar_engines, order):
    admin, runtime = scalar_engines
    feature, datasets, entities = await _seed(admin)
    await _activate(admin, feature)
    records = {}
    for index in order:
        records[index] = await _refresh(
            runtime, feature, datasets[index], entities[index], {"core.name": f"new-{index}"}
        )
    async with AsyncSession(admin) as session:
        row = (
            await session.execute(
                text("""SELECT name,phones FROM feature.features
            JOIN feature.feature_places USING(feature_id) WHERE feature_id=CAST(:id AS uuid)"""),
                {"id": feature},
            )
        ).one()
        assert tuple(row) == ("new-0", ["010-0"])
        rows = (
            await session.execute(
                text("""SELECT field_path,source_record_key,
            source_raw_payload_hash,value_json FROM feature.feature_base_field_values
            WHERE feature_id=CAST(:id AS uuid) ORDER BY field_path"""),
                {"id": feature},
            )
        ).all()
        assert tuple(rows[0]) == ("core.name", records[0][0], records[0][1], "new-0")
        assert tuple(rows[1]) == ("place.phones", entities[0] + "-r1", "1" * 64, ["010-0"])
        validated = (
            await session.execute(
                text("""SELECT value_source_record_key,validated_source_record_key
            FROM feature.provider_field_shadow_candidates WHERE feature_id=CAST(:id AS uuid)
            AND field_path='place.phones' AND provider_dataset_id=:dataset"""),
                {"id": feature, "dataset": datasets[0]},
            )
        ).one()
        assert tuple(validated) == (entities[0] + "-r1", records[0][0])


async def test_head_only_commit_is_rejected_and_original_projection_survives(scalar_engines):
    from sqlalchemy.exc import DBAPIError

    admin, runtime = scalar_engines
    feature, datasets, entities = await _seed(admin)
    await _activate(admin, feature)
    with pytest.raises(DBAPIError, match="candidate is missing"):
        await _refresh(
            runtime, feature, datasets[0], entities[0], {"core.name": "unprojected"}, project=False
        )
    async with AsyncSession(admin) as session:
        assert (
            await session.scalar(
                text(
                    "SELECT current_source_record_key FROM provider_sync.source_entity_heads "
                    "WHERE source_entity_key=:entity"
                ),
                {"entity": entities[0]},
            )
            == entities[0] + "-r1"
        )
        assert (
            await session.scalar(
                text("SELECT name FROM feature.features WHERE feature_id=CAST(:id AS uuid)"),
                {"id": feature},
            )
            == "winner-0"
        )
