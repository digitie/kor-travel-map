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


async def test_explicit_null_is_rejected_without_advancing_head(scalar_engines):
    from sqlalchemy.exc import DBAPIError

    admin, runtime = scalar_engines
    feature, datasets, entities = await _seed(admin)
    await _activate(admin, feature)
    with pytest.raises(DBAPIError, match="typed registry"):
        await _refresh(runtime, feature, datasets[0], entities[0], {"core.name": None})
    async with AsyncSession(admin) as session:
        assert (
            await session.scalar(
                text("SELECT name FROM feature.features WHERE feature_id=CAST(:id AS uuid)"),
                {"id": feature},
            )
            == "winner-0"
        )
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


async def test_active_legacy_writer_cannot_replace_winner_with_lower_provider(scalar_engines):
    from sqlalchemy.exc import DBAPIError

    admin, runtime = scalar_engines
    feature, datasets, entities = await _seed(admin)
    await _activate(admin, feature)
    async with AsyncSession(runtime) as session, session.begin():
        await session.execute(text("SELECT ops.lock_scoped_feature_write_protocol(true)"))
        revision = await session.scalar(
            text("SELECT row_revision FROM feature.features WHERE feature_id=CAST(:id AS uuid)"),
            {"id": feature},
        )
        with pytest.raises(DBAPIError, match="current canonical source"):
            async with session.begin_nested():
                await session.execute(
                    text("""CALL feature.apply_provider_feature_field_patch(
                    CAST(:id AS uuid),:dataset,:entity,:record,:revision,
                    '{"core.name":"lower-legacy"}','{}',NULL,NULL,NULL)"""),
                    {
                        "id": feature,
                        "dataset": datasets[1],
                        "entity": entities[1],
                        "record": entities[1] + "-r1",
                        "revision": revision,
                    },
                )
    async with AsyncSession(admin) as session:
        assert (
            await session.scalar(
                text("SELECT name FROM feature.features WHERE feature_id=CAST(:id AS uuid)"),
                {"id": feature},
            )
            == "winner-0"
        )


async def test_cross_dataset_target_is_rejected_before_source_dml(scalar_engines):
    from sqlalchemy.exc import DBAPIError

    from kortravelmap.infra.provider_field_candidates import lock_provider_field_policy_epoch
    from kortravelmap.infra.scoped_feature_writes import (
        begin_scoped_feature_write,
        finish_scoped_feature_write,
        lock_scoped_feature_write_protocol,
    )

    admin, runtime = scalar_engines
    feature, datasets, entities = await _seed(admin)
    await _activate(admin, feature)
    attempt, owner, digest = await _plan(runtime, feature, datasets[0])
    async with AsyncSession(runtime) as session, session.begin():
        await lock_scoped_feature_write_protocol(session, exclusive=False)
        await lock_provider_field_policy_epoch(session)
        await begin_scoped_feature_write(
            session, attempt_id=attempt, owner=owner, manifest_digest=digest
        )
        with pytest.raises(DBAPIError, match="outside the applying dataset"):
            async with session.begin_nested():
                await session.execute(
                    text("""SELECT feature.assert_scoped_provider_scalar_target(
                    :attempt,CAST(:feature AS uuid),:dataset,:entity,1)"""),
                    {
                        "attempt": attempt,
                        "feature": feature,
                        "dataset": datasets[1],
                        "entity": entities[1],
                    },
                )
        await finish_scoped_feature_write(
            session, attempt_id=attempt, owner=owner, result_digest="b" * 64
        )


async def test_runtime_cannot_activate_or_call_private_projection(scalar_engines):
    from sqlalchemy.exc import DBAPIError

    admin, runtime = scalar_engines
    feature, _, _ = await _seed(admin)
    async with AsyncSession(runtime) as session, session.begin():
        for statement in [
            "CALL feature.activate_provider_field_policy(CAST(:id AS uuid),1,ARRAY['core.name'])",
            "SELECT feature._project_provider_field_candidates(CAST(:id AS uuid))",
            "SELECT feature._install_provider_field_projection_guards()",
        ]:
            with pytest.raises(DBAPIError, match="permission denied"):
                async with session.begin_nested():
                    await session.execute(text(statement), {"id": feature})


async def test_shared_source_entity_is_rejected_at_activation(scalar_engines):
    from sqlalchemy.exc import DBAPIError

    admin, _ = scalar_engines
    feature, _, entities = await _seed(admin)
    other = str(uuid4())
    async with AsyncSession(admin) as session, session.begin():
        await session.execute(text("SELECT ops.lock_scoped_feature_write_protocol(true)"))
        await session.execute(
            text("""INSERT INTO feature.features(
            feature_id,kind,name,category,lifecycle_state,publication_state,quality_state)
            VALUES(CAST(:id AS uuid),'place','other','01010100','active','published','valid')"""),
            {"id": other},
        )
        await session.execute(
            text("""INSERT INTO provider_sync.source_links(
            feature_id,source_entity_key,source_role,match_method,confidence)
            VALUES(CAST(:id AS uuid),:entity,'primary','fixture',100)"""),
            {"id": other, "entity": entities[0]},
        )
    with pytest.raises(DBAPIError, match="shared source entity"):
        await _activate(admin, feature)


async def test_geo_group_and_stamp_are_preserved_and_unsupported_writes_rejected(scalar_engines):
    from sqlalchemy.exc import DBAPIError

    admin, runtime = scalar_engines
    feature, datasets, entities = await _seed(admin)
    async with AsyncSession(admin) as session, session.begin():
        await session.execute(text("SELECT ops.lock_scoped_feature_write_protocol(true)"))
        await session.execute(
            text("""UPDATE feature.features
            SET coord=x_extension.st_setsrid(x_extension.st_makepoint(127,37),4326)
            WHERE feature_id=CAST(:id AS uuid)"""),
            {"id": feature},
        )
        assert (
            await session.scalar(
                text("""SELECT feature.upsert_provider_geocode_stamps_ex(
                ARRAY[CAST(:id AS uuid)],ARRAY['geocoded']::text[],:version,:data)"""),
                {"id": feature, "version": "dv1-" + "a" * 32, "data": "dd1-" + "b" * 32},
            )
            == 1
        )
    await _activate(admin, feature)
    query = text("""SELECT x_extension.st_asewkt(coord),coord_precision_digits,
        address,legal_dong_code,geo_version_token,geo_data_token,stamped_at
        FROM feature.features JOIN feature.feature_geocode_stamps USING(feature_id)
        WHERE feature_id=CAST(:id AS uuid)""")
    async with AsyncSession(admin) as session:
        before = tuple((await session.execute(query, {"id": feature})).one())
    await _refresh(runtime, feature, datasets[0], entities[0], {"core.name": "scalar refresh"})
    async with AsyncSession(admin) as session, session.begin():
        assert tuple((await session.execute(query, {"id": feature})).one()) == before
        await session.execute(text("SELECT ops.lock_scoped_feature_write_protocol(true)"))
        with pytest.raises(DBAPIError, match="unsupported"):
            async with session.begin_nested():
                await session.execute(
                    text("""UPDATE feature.feature_geocode_stamps
                    SET geo_data_token=:data WHERE feature_id=CAST(:id AS uuid)"""),
                    {"id": feature, "data": "dd1-" + "c" * 32},
                )
        with pytest.raises(DBAPIError, match="Geo lifecycle"):
            async with session.begin_nested():
                await session.execute(
                    text("""UPDATE feature.features
                    SET coord=x_extension.st_setsrid(x_extension.st_makepoint(128,38),4326)
                    WHERE feature_id=CAST(:id AS uuid)"""),
                    {"id": feature},
                )


async def test_override_revoke_restores_latest_winner(scalar_engines):
    from kortravelmap.infra.admin_feature_repo import (
        author_admin_feature_field_overrides,
        revoke_admin_feature_field_overrides,
    )
    from tests.integration.test_tvn36_override_lineage_spine import _open_domain_command

    admin, runtime = scalar_engines
    feature, datasets, entities = await _seed(admin)
    await _activate(admin, feature)
    actor = "admin:scalar-fixture"
    async with AsyncSession(admin) as session, session.begin():
        await session.execute(text("SELECT ops.lock_scoped_feature_write_protocol(true)"))
        revision = await session.scalar(
            text("SELECT row_revision FROM feature.features WHERE feature_id=CAST(:id AS uuid)"),
            {"id": feature},
        )
        command = await _open_domain_command(
            session, actor=actor, operation="admin.feature.override.author"
        )
        await author_admin_feature_field_overrides(
            session,
            feature,
            expected_row_revision=revision,
            reason_code="operator_correction",
            operator=actor,
            command_id=command,
            values={"place.phones": ["099"]},
            geometry_wkt={},
        )
    await _refresh(
        runtime, feature, datasets[0], entities[0], {"core.name": "latest", "place.phones": ["011"]}
    )
    async with AsyncSession(admin) as session, session.begin():
        assert await session.scalar(
            text("SELECT phones FROM feature.feature_places WHERE feature_id=CAST(:id AS uuid)"),
            {"id": feature},
        ) == ["099"]
        assert await session.scalar(
            text(
                "SELECT value_json FROM feature.feature_base_field_values "
                "WHERE feature_id=CAST(:id AS uuid) AND field_path='place.phones'"
            ),
            {"id": feature},
        ) == ["011"]
        await session.execute(text("SELECT ops.lock_scoped_feature_write_protocol(true)"))
        revision = await session.scalar(
            text("SELECT row_revision FROM feature.features WHERE feature_id=CAST(:id AS uuid)"),
            {"id": feature},
        )
        command = await _open_domain_command(
            session, actor=actor, operation="admin.feature.override.revoke"
        )
        await revoke_admin_feature_field_overrides(
            session,
            feature,
            expected_row_revision=revision,
            reason_code="operator_correction",
            operator=actor,
            command_id=command,
            field_paths=("place.phones",),
        )
    async with AsyncSession(admin) as session:
        assert await session.scalar(
            text("SELECT phones FROM feature.feature_places WHERE feature_id=CAST(:id AS uuid)"),
            {"id": feature},
        ) == ["011"]


async def test_source_only_old_rr_cannot_advance_head_after_policy_cutover(scalar_engines):
    from sqlalchemy.exc import DBAPIError

    admin, _ = scalar_engines
    feature, datasets, entities = await _seed(admin)
    await _activate(admin, feature)
    other, _, _ = await _seed(admin)
    record = entities[0] + "-rr"
    # history 준비도 현재 prefix 규약을 따른다. RR 부정 TX에서는 head만 시험한다.
    async with AsyncSession(admin) as seed, seed.begin():
        await seed.execute(text("SELECT ops.lock_scoped_feature_write_protocol(true)"))
        await seed.execute(
            text("""INSERT INTO provider_sync.source_records(
            source_record_key,source_entity_key,raw_data,raw_payload_hash,fetched_at)
            VALUES(:record,:entity,'{}',:hash,clock_timestamp())"""),
            {"record": record, "entity": entities[0], "hash": "c" * 64},
        )
    async with admin.connect() as connection:
        await connection.execution_options(isolation_level="REPEATABLE READ")
        async with AsyncSession(bind=connection) as old:
            await old.execute(text("SELECT epoch FROM feature.provider_field_policy_epoch"))
            await _activate(admin, other)
            # 수동 old-RR 부정 fixture다. fresh first-party 진입 성공을 주장하지 않고
            # 현재 P 뒤에도 stale epoch의 원40001 보호가 남는지 확인한다.
            await old.execute(text("SELECT ops.lock_scoped_feature_write_protocol(true)"))
            with pytest.raises(DBAPIError) as failed:
                await old.execute(
                    text("""UPDATE provider_sync.source_entity_heads
                    SET current_source_record_key=:record,observed_at=clock_timestamp()
                    WHERE source_entity_key=:entity"""),
                    {"record": record, "entity": entities[0]},
                )
            assert getattr(failed.value.orig, "sqlstate", None) == "40001"
            await old.rollback()
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


async def test_active_fieldset_change_is_rejected_atomically(scalar_engines):
    from sqlalchemy.exc import DBAPIError

    admin, _ = scalar_engines
    feature, datasets, entities = await _seed(admin)
    # 최초 활성화 전에 다른 완결 정책/후보도 준비한다. 새 revision 자체의 준비
    # 부족 때문이 아니라 이미 활성인 fieldset의 제거가 거부되어야 한다.
    async with AsyncSession(admin) as session, session.begin():
        await session.execute(text("SELECT ops.lock_scoped_feature_write_protocol(true)"))
        for index, dataset in enumerate(datasets):
            await session.execute(
                text("""CALL feature.register_provider_field_shadow_policy(
                    2,:dataset,'scalar-v1',CAST(:fields AS jsonb))"""),
                {
                    "dataset": dataset,
                    "fields": json.dumps(
                        [
                            {
                                "field_path": "core.name",
                                "provider_rank": 10 + index * 10,
                                "omitted_policy": "carry_forward",
                                "null_policy": "value",
                            }
                        ]
                    ),
                },
            )
            arm_provider_field_shadow(session, 2)
            await capture_provider_field_candidates(
                session,
                feature_id=feature,
                dataset_id=dataset,
                entity_key=entities[index],
                record_key=entities[index] + "-r1",
                values=json.dumps({"core.name": f"winner-{index}"}),
                geometry_wkt="{}",
                presence=ProviderFieldPresence(
                    normalizer_revision="scalar-v1",
                    supplied_fields={"core.name"},
                ),
            )
    await _activate(admin, feature)

    async def state():
        async with AsyncSession(admin) as session:
            return tuple(
                (
                    await session.execute(
                        text("""SELECT active.policy_revision,
                active.field_paths,epoch.epoch,feature.name,place.phones,
                (SELECT jsonb_agg(to_jsonb(base) ORDER BY base.field_path)
                  FROM feature.feature_base_field_values base
                  WHERE base.feature_id=active.feature_id)
                FROM feature.provider_field_active_policies active
                CROSS JOIN feature.provider_field_policy_epoch epoch
                JOIN feature.features feature ON feature.feature_id=active.feature_id
                JOIN feature.feature_places place ON place.feature_id=active.feature_id
                WHERE active.feature_id=CAST(:feature AS uuid)"""),
                        {"feature": feature},
                    )
                ).one()
            )

    before = await state()

    async def shrink():
        async with AsyncSession(admin) as session, session.begin():
            await session.execute(text("SET LOCAL statement_timeout='10s'"))
            await session.execute(
                text("""CALL feature.activate_provider_field_policy(
                CAST(:feature AS uuid),2,ARRAY['core.name'])"""),
                {"feature": feature},
            )

    with pytest.raises(DBAPIError, match="fieldset"):
        await shrink()
    assert await state() == before


async def test_foreign_unchanged_winner_preserves_base_revision_and_clock(scalar_engines):
    admin, runtime = scalar_engines
    feature, datasets, entities = await _seed(admin)
    await _activate(admin, feature)
    query = text("""SELECT to_jsonb(base) FROM feature.feature_base_field_values base
        WHERE feature_id=CAST(:feature AS uuid) ORDER BY field_path COLLATE "C"
        """)
    async with AsyncSession(admin) as observer:
        before = (await observer.execute(query, {"feature": feature})).scalars().all()
    await _refresh(runtime, feature, datasets[1], entities[1], {"core.name": "nonwinning-name"})
    async with AsyncSession(admin) as observer:
        after = (await observer.execute(query, {"feature": feature})).scalars().all()
    assert after == before
    assert {row["provider_dataset_id"] for row in after} == {datasets[0]}


async def test_foreign_changed_base_still_rejects_inside_manifest_feature(scalar_engines):
    from sqlalchemy.exc import DBAPIError

    from kortravelmap.infra.scoped_feature_writes import begin_scoped_feature_write

    admin, runtime = scalar_engines
    feature, datasets, _ = await _seed(admin)
    await _activate(admin, feature)
    attempt, owner, digest = await _plan(runtime, feature, datasets[1])
    query = text("""SELECT to_jsonb(base) FROM feature.feature_base_field_values base
        WHERE feature_id=CAST(:feature AS uuid) ORDER BY field_path COLLATE "C"
        """)
    async with AsyncSession(admin) as observer:
        before = (await observer.execute(query, {"feature": feature})).scalars().all()
    try:
        async with AsyncSession(admin) as session:
            await session.execute(text("SET LOCAL statement_timeout='8s'"))
            await begin_scoped_feature_write(
                session, attempt_id=attempt, owner=owner, manifest_digest=digest
            )
            # raw base UPDATE는 runtime grant가 없는 관리 SQL 경계다(기존 strict 시험과 동일).
            await session.execute(text("SET LOCAL ROLE ktm_feature_schema_owner"))
            assert await session.scalar(text("SELECT current_user::text")) == (
                "ktm_feature_schema_owner"
            )
            with pytest.raises(DBAPIError) as caught:
                await session.execute(
                    text("""UPDATE feature.feature_base_field_values
                    SET value_json=to_jsonb('forbidden'::text)
                    WHERE feature_id=CAST(:feature AS uuid) AND field_path='core.name'"""),
                    {"feature": feature},
                )
            assert caught.value.orig.sqlstate == "23514"
            assert "shared derived value is outside its own primary source target" in str(
                caught.value.orig
            )
            await session.rollback()
        async with AsyncSession(admin) as observer:
            after = (await observer.execute(query, {"feature": feature})).scalars().all()
        assert after == before
    finally:
        async with AsyncSession(runtime) as session, session.begin():
            await session.execute(text("SET LOCAL statement_timeout='8s'"))
            assert await session.scalar(
                text("SELECT ops.cancel_scoped_feature_write(:attempt,:owner)"),
                {"attempt": attempt, "owner": owner},
            )


async def test_removed_own_candidate_requires_fresh_ex_plan_for_foreign_winner(scalar_engines):
    from sqlalchemy.exc import DBAPIError

    from kortravelmap.infra.provider_field_candidates import (
        lock_provider_field_policy_epoch,
        recompute_provider_field_candidates,
    )
    from kortravelmap.infra.scoped_feature_writes import (
        ScopedWriteDependency,
        append_scoped_feature_write_manifest,
        begin_scoped_feature_write,
        claim_scoped_feature_write,
        finish_scoped_feature_write,
        lock_scoped_feature_write_protocol,
        seal_scoped_feature_write_manifest,
    )

    admin, runtime = scalar_engines
    feature, datasets, entities = await _seed(admin)
    async with AsyncSession(admin) as seed, seed.begin():
        await seed.execute(text("SELECT ops.lock_scoped_feature_write_protocol(true)"))
        for index, dataset in enumerate(datasets):
            fields = [
                dict(
                    field_path=path,
                    provider_rank=10 + 10 * index,
                    omitted_policy="remove" if path == "core.name" else "carry_forward",
                    null_policy="value",
                )
                for path in ("core.name", "place.phones")
            ]
            await seed.execute(
                text("""CALL feature.register_provider_field_shadow_policy(
                2,:dataset,'scalar-v1',CAST(:fields AS jsonb))"""),
                {"dataset": dataset, "fields": json.dumps(fields)},
            )
        arm_provider_field_shadow(seed, 2)
        for index, dataset in enumerate(datasets):
            values = {"core.name": f"winner-{index}", "place.phones": [f"010-{index}"]}
            captured = await capture_provider_field_candidates(
                seed,
                feature_id=feature,
                dataset_id=dataset,
                entity_key=entities[index],
                record_key=entities[index] + "-r1",
                values=json.dumps(values),
                geometry_wkt="{}",
                presence=ProviderFieldPresence(
                    normalizer_revision="scalar-v1", supplied_fields=set(values)
                ),
            )
            assert captured.unresolved_count == 0
        await seed.execute(
            text("""CALL feature.activate_provider_field_policy(
            CAST(:feature AS uuid),2,ARRAY['core.name','place.phones'])"""),
            {"feature": feature},
        )
        observed = await seed.scalar(text("SELECT clock_timestamp()+interval '1 hour'"))
    payload = json.dumps({"place.phones": ["011-own"]}, sort_keys=True)
    import hashlib

    source_hash = hashlib.sha256(payload.encode()).hexdigest()
    record = entities[0] + "-handoff"

    async def plan(exclusive):
        attempt, owner = uuid4(), uuid4()
        async with AsyncSession(runtime) as session, session.begin():
            revision = await session.scalar(
                text(
                    "SELECT row_revision FROM feature.features WHERE feature_id=CAST(:id AS uuid)"
                ),
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
                ScopedWriteDependency(i, "source_head", entity, key)
                for i, (entity, key) in enumerate(heads)
            ]
            members.extend(
                [
                    ScopedWriteDependency(len(members), "feature", feature, str(revision)),
                    ScopedWriteDependency(
                        len(members) + 1, "feature_membership", feature, membership
                    ),
                ]
            )
            await claim_scoped_feature_write(
                session,
                attempt_id=attempt,
                owner=owner,
                dataset_id=datasets[0],
                idempotency_key=uuid4().hex,
                regions=(),
                input_digest="a" * 64,
                expected_members=len(members),
                exclusive_protocol=exclusive,
            )
            await append_scoped_feature_write_manifest(
                session, attempt_id=attempt, owner=owner, members=members
            )
            digest = await seal_scoped_feature_write_manifest(
                session, attempt_id=attempt, owner=owner
            )
        return attempt, owner, digest

    async def apply(attempt, owner, digest, exclusive):
        async with AsyncSession(runtime) as session, session.begin():
            await session.execute(text("SET LOCAL statement_timeout='8s'"))
            await lock_scoped_feature_write_protocol(session, exclusive=exclusive)
            await lock_provider_field_policy_epoch(session)
            await begin_scoped_feature_write(
                session, attempt_id=attempt, owner=owner, manifest_digest=digest
            )
            await session.execute(
                text("""INSERT INTO provider_sync.source_records(
                source_record_key,source_entity_key,raw_data,raw_payload_hash,fetched_at)
                VALUES(:record,:entity,CAST(:raw AS jsonb),:hash,:observed)"""),
                {
                    "record": record,
                    "entity": entities[0],
                    "raw": payload,
                    "hash": source_hash,
                    "observed": observed,
                },
            )
            await session.execute(
                text("""UPDATE provider_sync.source_entity_heads SET
                current_source_record_key=:record,observed_at=:observed
                WHERE source_entity_key=:entity"""),
                {"record": record, "observed": observed, "entity": entities[0]},
            )
            arm_provider_field_shadow(session, 2)
            captured = await capture_provider_field_candidates(
                session,
                feature_id=feature,
                dataset_id=datasets[0],
                entity_key=entities[0],
                record_key=record,
                values=payload,
                geometry_wkt="{}",
                presence=ProviderFieldPresence(
                    normalizer_revision="scalar-v1", supplied_fields={"place.phones"}
                ),
                attempt_id=str(attempt),
            )
            assert captured.unresolved_count == 0
            await recompute_provider_field_candidates(
                session, attempt_id=str(attempt), feature_id=feature, policy_revision=2
            )
            await finish_scoped_feature_write(
                session, attempt_id=attempt, owner=owner, result_digest="b" * 64
            )

    sh_attempt, sh_owner, sh_digest = await plan(False)
    try:
        with pytest.raises(DBAPIError) as caught:
            await apply(sh_attempt, sh_owner, sh_digest, False)
        assert caught.value.orig.sqlstate == "23514"
        assert "shared derived value is outside its own primary source target" in str(
            caught.value.orig
        )
        async with AsyncSession(admin) as observer:
            assert (
                await observer.scalar(
                    text("SELECT name FROM feature.features WHERE feature_id=CAST(:id AS uuid)"),
                    {"id": feature},
                )
                == "winner-0"
            )
            assert (
                await observer.scalar(
                    text(
                        "SELECT count(*) FROM provider_sync.source_records "
                        "WHERE source_record_key=:record"
                    ),
                    {"record": record},
                )
                == 0
            )
    finally:
        async with AsyncSession(runtime) as session, session.begin():
            await session.execute(text("SET LOCAL statement_timeout='8s'"))
            assert await session.scalar(
                text("SELECT ops.cancel_scoped_feature_write(:attempt,:owner)"),
                {"attempt": sh_attempt, "owner": sh_owner},
            )
    ex_attempt, ex_owner, ex_digest = await plan(True)
    assert ex_attempt != sh_attempt
    await apply(ex_attempt, ex_owner, ex_digest, True)
    async with AsyncSession(admin) as observer:
        winner = (
            await observer.execute(
                text("""SELECT feature.name,base.provider_dataset_id,
                base.source_entity_key,base.source_record_key
            FROM feature.features feature
            JOIN feature.feature_base_field_values base USING(feature_id)
            WHERE feature.feature_id=CAST(:id AS uuid) AND base.field_path='core.name'"""),
                {"id": feature},
            )
        ).one()
        assert tuple(winner) == ("winner-1", datasets[1], entities[1], entities[1] + "-r1")
        own = (
            await observer.execute(
                text("""SELECT availability,reason,validated_source_record_key
            FROM feature.provider_field_shadow_candidates
            WHERE feature_id=CAST(:id AS uuid) AND provider_dataset_id=:dataset
              AND field_path='core.name' AND policy_revision=2"""),
                {"id": feature, "dataset": datasets[0]},
            )
        ).one()
        assert tuple(own) == ("removed", "omitted_remove", record)
        stored = (
            await observer.execute(
                text(
                    "SELECT raw_data,raw_payload_hash,fetched_at FROM provider_sync.source_records "
                    "WHERE source_record_key=:record"
                ),
                {"record": record},
            )
        ).one()
        assert tuple(stored) == (json.loads(payload), source_hash, observed)
        assert await observer.scalar(
            text("SELECT phones FROM feature.feature_places WHERE feature_id=CAST(:id AS uuid)"),
            {"id": feature},
        ) == ["011-own"]
        statuses = dict(
            (
                await observer.execute(
                    text(
                        "SELECT attempt_id,status FROM ops.feature_write_attempts "
                        "WHERE attempt_id=ANY(CAST(:attempts AS uuid[]))"
                    ),
                    {"attempts": [sh_attempt, ex_attempt]},
                )
            ).all()
        )
        assert statuses == {sh_attempt: "cancelled", ex_attempt: "completed"}
