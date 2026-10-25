"""비활성429 설치를 owned PG에서만 명시 검증한다. 운영 activation 증거가 아니다."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.dto import Feature
from kortravelmap.infra import feature_repo, scoped_provider_batch
from kortravelmap.infra.feature_identity import resolve_feature_identity
from kortravelmap.infra.scoped_feature_writes import begin_scoped_feature_write
from kortravelmap.infra.scoped_provider_batch import ProviderScalarRefreshItem
from tests.integration.test_provider_base_update_first import _gate, _seed
from tests.integration.test_provider_field_scalar_projection import (
    scalar_container as scalar_container,
)
from tests.integration.test_provider_field_scalar_projection import scalar_engines as scalar_engines
from tests.integration.test_scoped_provider_batch import (
    _dataset_bundle,
    _entity,
    _plan,
    _seed_bundles,
    _snapshot,
)
from tests.integration.test_scoped_provider_batch import _seed as _batch_seed
from tests.integration.test_scoped_provider_geocode_stamps import _active_name_setup, _stamps
from tests.integration.test_tvn36_override_lineage_spine import _constraint_name

pytestmark = pytest.mark.integration


@pytest.fixture
async def strict_engines(scalar_engines):
    admin, runtime = scalar_engines
    async with AsyncSession(admin) as session, session.begin():
        await _gate(session)
        await session.execute(text("SET LOCAL ROLE ktm_feature_schema_owner"))
        await session.execute(text("SELECT feature._install_strict_sh_data_guards()"))
    return admin, runtime


def _error(error, constraint):
    assert error.value.orig.sqlstate == "23514"
    assert _constraint_name(error.value) == constraint


async def test_private_catalog_and_installer_repeat_leave_existing_guards(strict_engines):
    admin, runtime = strict_engines
    async with AsyncSession(admin) as session, session.begin():
        count = await session.scalar(
            text("""SELECT count(*) FROM pg_trigger
            WHERE NOT tgisinternal AND tgfoid IN (
            'feature._strict_sh_data_statement_guard()'::regprocedure,
            'feature._strict_sh_source_row_guard()'::regprocedure,
            'feature._strict_sh_feature_row_guard()'::regprocedure)""")
        )
        assert count == 33
        assert (
            await session.scalar(
                text("""SELECT bool_and(NOT has_function_privilege(
            'ktm_feature_runtime',p.oid,'EXECUTE')) FROM pg_proc p
            JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='feature'
            AND p.proname IN ('_strict_sh_data_context','_strict_sh_data_statement_guard',
            '_strict_sh_source_row_guard','_strict_sh_feature_row_guard',
            '_install_strict_sh_data_guards')""")
            )
            is True
        )
    async with AsyncSession(runtime) as session:
        with pytest.raises(DBAPIError) as error:
            async with session.begin():
                await session.execute(text("SELECT feature._install_strict_sh_data_guards()"))
        assert error.value.orig.sqlstate == "42501"


@pytest.mark.parametrize("shared", [False, True])
@pytest.mark.parametrize("target", ["feature", "record"])
async def test_prefix_rejects_before_epoch_and_feature_holder(strict_engines, shared, target):
    admin, runtime = strict_engines
    seed = await _seed(admin)
    async with AsyncSession(admin) as holder:
        await holder.begin()
        try:
            await holder.execute(
                text("SELECT 1 FROM feature.provider_field_policy_epoch FOR UPDATE")
            )
            await holder.execute(
                text(
                    "SELECT 1 FROM feature.features WHERE feature_id=CAST(:feature AS "
                    "uuid) FOR UPDATE"
                ),
                seed,
            )
            async with AsyncSession(runtime) as session:
                await session.begin()
                try:
                    await session.execute(text("SET LOCAL lock_timeout='50ms'"))
                    await session.execute(text("SET LOCAL statement_timeout='500ms'"))
                    if shared:
                        await session.execute(
                            text("SELECT ops.lock_scoped_feature_write_protocol(false)")
                        )
                    statement = (
                        "UPDATE feature.features SET name=name WHERE "
                        "feature_id=CAST(:feature AS uuid)"
                        if target == "feature"
                        else "UPDATE provider_sync.source_records SET fetched_at=fetched_at "
                        "WHERE false"
                    )
                    with pytest.raises(DBAPIError) as error:
                        await session.execute(text(statement), seed)
                    _error(
                        error,
                        "ck_strict_data_applying_context"
                        if shared
                        else "ck_strict_data_protocol_prefix",
                    )
                finally:
                    await session.rollback()

        finally:
            await holder.rollback()


@pytest.mark.parametrize(
    "relation",
    [
        "provider_sync.provider_datasets",
        "provider_sync.provider_dataset_operations",
        "provider_sync.provider_dataset_operation_scopes",
        "provider_sync.provider_feature_identities",
        "feature.manual_feature_identity_claims",
        "feature.feature_creation_origins",
        "feature.provider_field_shadow_policies",
        "feature.provider_field_active_policies",
        "feature.provider_field_policy_epoch",
        "ops.feature_override_field_paths",
        "provider_sync.source_links",
        "ops.feature_overrides",
        "feature.feature_events",
        "feature.feature_notices",
        "feature.feature_routes",
        "feature.feature_route_geometries",
        "feature.feature_areas",
    ],
)
async def test_ex_only_relations_reject_shared_before_any_row(strict_engines, relation):
    admin, _ = strict_engines
    # schema owner의 명시 관리 SQL 경계다. 일반 runtime의 raw catalog 권한을 늘리지 않는다.
    async with AsyncSession(admin) as session:
        await session.begin()
        try:
            await session.execute(text("SET LOCAL ROLE ktm_feature_schema_owner"))
            await session.execute(text("SELECT ops.lock_scoped_feature_write_protocol(false)"))
            with pytest.raises(DBAPIError) as error:
                await session.execute(text(f"DELETE FROM {relation} WHERE false"))
            _error(error, "ck_strict_data_protocol_prefix")
        finally:
            await session.rollback()


async def test_valid_apply_keeps_source_upsert_first_seen_and_denies_other_feature(strict_engines):
    admin, runtime = strict_engines
    outside = await _seed(admin)
    dataset, items = await _batch_seed(admin, runtime, count=1)
    plan, _ = await _plan(runtime, dataset, items)
    async with AsyncSession(runtime) as session:
        await session.begin()
        try:
            await begin_scoped_feature_write(
                session,
                attempt_id=plan["attempt_id"],
                owner=plan["owner"],
                manifest_digest=plan["manifest_digest"],
            )
            entity = await session.scalar(
                text(
                    "SELECT source_entity_key FROM provider_sync.source_links WHERE "
                    "feature_id=:feature"
                ),
                {"feature": items[0].feature_id},
            )
            before = await session.scalar(
                text(
                    "SELECT first_seen_at FROM provider_sync.source_entities WHERE "
                    "source_entity_key=:entity"
                ),
                {"entity": entity},
            )
            await session.execute(
                text("""INSERT INTO provider_sync.source_entities AS current
                (source_entity_key,provider_dataset_id,source_entity_type,
                 source_entity_id,first_seen_at,last_seen_at)
                SELECT source_entity_key,provider_dataset_id,source_entity_type,
                       source_entity_id,now(),now()
                FROM provider_sync.source_entities WHERE source_entity_key=:entity
                ON CONFLICT(source_entity_key) DO UPDATE
                  SET last_seen_at=greatest(current.last_seen_at,EXCLUDED.last_seen_at)"""),
                {"entity": entity},
            )
            assert (
                await session.scalar(
                    text(
                        "SELECT first_seen_at FROM provider_sync.source_entities WHERE "
                        "source_entity_key=:entity"
                    ),
                    {"entity": entity},
                )
                == before
            )
            # 기존 applying target의 두번째 검사는 이전 row_revision을 stale로 비교하지 않는다.
            for _ in range(2):
                result = await session.execute(
                    text("UPDATE feature.features SET name=name WHERE feature_id=:feature"),
                    {"feature": items[0].feature_id},
                )
                assert result.rowcount == 1
            with pytest.raises(DBAPIError) as error:
                async with session.begin_nested():
                    await session.execute(
                        text(
                            "UPDATE feature.features SET name='outside' WHERE "
                            "feature_id=CAST(:feature AS uuid)"
                        ),
                        outside,
                    )
            assert error.value.orig.sqlstate == "23514"
            with pytest.raises(DBAPIError) as error:
                async with session.begin_nested():
                    await session.execute(
                        text(
                            "DELETE FROM provider_sync.source_records WHERE "
                            "source_entity_key=:entity"
                        ),
                        {"entity": entity},
                    )
            _error(error, "ck_strict_data_source_target")
            with pytest.raises(DBAPIError) as error:
                async with session.begin_nested():
                    await session.execute(
                        text(
                            "UPDATE provider_sync.source_records SET "
                            "fetched_at=fetched_at+interval '1 second' WHERE "
                            "source_entity_key=:entity"
                        ),
                        {"entity": entity},
                    )
            _error(error, "ck_source_records_immutable")
        finally:
            # finish 없는 중간 상태의 증거이며 commit/collector 성공으로 세지 않는다.
            await session.rollback()


@pytest.mark.parametrize("drift", ["disabled", "partial"])
async def test_private_installer_rejects_drift_without_partial_repair(strict_engines, drift):
    admin, _ = strict_engines
    async with AsyncSession(admin) as session:
        await session.begin()
        try:
            await _gate(session)
            await session.execute(text("SET LOCAL ROLE ktm_feature_schema_owner"))
            statement = (
                "ALTER TABLE provider_sync.source_records DISABLE TRIGGER "
                "trg_00_strict_sh_data_protocol"
                if drift == "disabled"
                else "DROP TRIGGER trg_00_strict_sh_data_protocol ON provider_sync.source_records"
            )
            await session.execute(text(statement))
            with pytest.raises(DBAPIError) as error:
                async with session.begin_nested():
                    await session.execute(text("SELECT feature._install_strict_sh_data_guards()"))
            _error(error, "ck_strict_data_guard_inventory")
            if drift == "disabled":
                assert (
                    await session.scalar(
                        text(
                            "SELECT tgenabled::text FROM pg_trigger WHERE "
                            "tgrelid='provider_sync.source_records'::regclass AND "
                            "tgname='trg_00_strict_sh_data_protocol'"
                        )
                    )
                    == "D"
                )
            else:
                assert (
                    await session.scalar(
                        text(
                            "SELECT count(*) FROM pg_trigger WHERE "
                            "tgrelid='provider_sync.source_records'::regclass AND "
                            "tgname='trg_00_strict_sh_data_protocol'"
                        )
                    )
                    == 0
                )
        finally:
            await session.rollback()


@pytest.mark.parametrize("mutation", ["coord", "address", "payload", "lifecycle"])
async def test_inside_manifest_without_active_policy_rejects_non_scalar_mutation(
    strict_engines, mutation
):
    admin, runtime = strict_engines
    dataset_key, identity = "uncut-" + uuid4().hex, uuid4().hex
    bundle = _dataset_bundle(dataset_key, identity, "uncut-before", hours=-24)
    record = bundle.source_record
    async with AsyncSession(admin) as session, session.begin():
        await _gate(session)
        dataset = await session.scalar(
            text("""INSERT INTO provider_sync.provider_datasets
            (provider,dataset_key,display_name,source_kind)
            VALUES(:provider,:key,'uncut strict guard fixture','manual')
            RETURNING provider_dataset_id"""),
            {"provider": record.provider, "key": dataset_key},
        )
    # 실제 canonical legacy loader를 사용하되 policy 등록/cutover는 하지 않는다.
    async with AsyncSession(runtime) as session, session.begin():
        await feature_repo.load_bundles(session, [bundle])
        resolved = await resolve_feature_identity(session, bundle.feature.feature_id)
        assert resolved is not None
        feature = UUID(str(resolved.feature_id))
    async with AsyncSession(admin) as session:
        assert (
            await session.scalar(
                text(
                    """SELECT count(*) FROM feature.provider_field_active_policies
                    WHERE feature_id=:id"""
                ),
                {"id": feature},
            )
            == 0
        )
    async with AsyncSession(admin) as session:
        before = (
            await session.execute(
                text("""SELECT f.lifecycle_state,f.coord,f.address,p.payload
                FROM feature.features f JOIN feature.feature_places p USING(feature_id)
                WHERE f.feature_id=:feature"""),
                {"feature": feature},
            )
        ).one()
    plan, _ = await _plan(runtime, dataset, [ProviderScalarRefreshItem(feature, bundle)])
    statements = {
        "coord": """UPDATE feature.features SET
            coord=x_extension.st_geomfromtext('POINT(127 37)',4326),coord_precision_digits=6
            WHERE feature_id=:feature""",
        "address": """UPDATE feature.features SET address=CAST(:address AS jsonb)
            WHERE feature_id=:feature""",
        "payload": """UPDATE feature.feature_places SET payload=CAST(:payload AS jsonb)
            WHERE feature_id=:feature""",
        "lifecycle": """UPDATE feature.features SET lifecycle_state='retired'
            WHERE feature_id=:feature""",
    }
    # coord/address/payload는 일반 runtime의 정본 column 권한 경계다.
    # lifecycle은 직접 runtime grant가 없으므로 명시 관리 role의 SH 호출로 분리한다.
    async with AsyncSession(admin if mutation == "lifecycle" else runtime) as session:
        await session.begin()
        try:
            await begin_scoped_feature_write(
                session,
                attempt_id=plan["attempt_id"],
                owner=plan["owner"],
                manifest_digest=plan["manifest_digest"],
            )
            if mutation == "lifecycle":
                await session.execute(text("SET LOCAL ROLE ktm_feature_schema_owner"))
            with pytest.raises(DBAPIError) as error:
                await session.execute(
                    text(statements[mutation]),
                    {
                        "feature": feature,
                        "payload": '{"outside": "scalar"}',
                        "address": '{"road": "outside scalar"}',
                    },
                )
            _error(error, "ck_strict_data_feature_eligibility")
        finally:
            await session.rollback()
    async with AsyncSession(admin) as session:
        row = (
            await session.execute(
                text("""SELECT f.lifecycle_state,f.coord,f.address,p.payload
            FROM feature.features f JOIN feature.feature_places p USING(feature_id)
            WHERE f.feature_id=:feature"""),
                {"feature": feature},
            )
        ).one()
        assert row.lifecycle_state == "active"
        assert row.coord is None
        assert row.address == before.address
        assert tuple(row) == tuple(before)
        assert row.payload == bundle.feature.detail.payload


async def test_active_policy_does_not_make_retired_target_shared_eligible(strict_engines):
    admin, runtime = strict_engines
    dataset_key, identity = "retired-" + uuid4().hex, uuid4().hex
    old = _dataset_bundle(dataset_key, identity, "retired-before", hours=-24)
    retired = Feature.model_validate(
        old.feature.model_dump()
        | {
            "detail": old.feature.detail,
            "lifecycle_state": "retired",
            "publication_state": "suppressed",
        }
    )
    old = old.model_copy(update={"feature": retired})
    new = _dataset_bundle(dataset_key, identity, "retired-after", hours=0)
    new = new.model_copy(update={"feature": retired.model_copy(update={"name": "retired-after"})})
    dataset, items = await _seed_bundles(admin, runtime, [old], [new])
    feature = items[0].feature_id
    async with AsyncSession(admin) as session:
        row = (
            await session.execute(
                text("""SELECT f.lifecycle_state,active.feature_id FROM feature.features f
            JOIN feature.provider_field_active_policies active USING(feature_id)
            WHERE f.feature_id=:feature"""),
                {"feature": feature},
            )
        ).one()
        assert row.lifecycle_state == "retired"
        assert row.feature_id == feature
    plan, _ = await _plan(runtime, dataset, items)
    async with AsyncSession(runtime) as session:
        await session.begin()
        try:
            await begin_scoped_feature_write(
                session,
                attempt_id=plan["attempt_id"],
                owner=plan["owner"],
                manifest_digest=plan["manifest_digest"],
            )
            with pytest.raises(DBAPIError) as error:
                await session.execute(
                    text("UPDATE feature.features SET name=name WHERE feature_id=:feature"),
                    {"feature": feature},
                )
            _error(error, "ck_strict_data_feature_eligibility")
        finally:
            await session.rollback()


async def test_actual_shared_batch_finishes_and_commits_under_explicit_strict_guards(
    strict_engines,
):
    admin, runtime = strict_engines
    dataset, items = await _batch_seed(admin, runtime, count=2)
    plan, _ = await _plan(runtime, dataset, items)
    before = await _snapshot(admin, items)
    async with AsyncSession(runtime) as session, session.begin():
        receipt = await scoped_provider_batch.refresh_scoped_provider_scalars_batch(
            session, items, **plan
        )
        assert receipt["status"] == "completed"
        assert receipt["exclusive_protocol"] is False
        assert receipt["expected_members"] == 6
    # 별도 connection에서 commit 결과와 persisted attempt를 읽는다.
    after = await _snapshot(admin, items)
    assert after != before
    for item, state in zip(sorted(items, key=lambda item: item.feature_id), after, strict=True):
        assert state[0][0] == item.bundle.feature.name
        assert state[0][2] == item.bundle.source_record.source_record_key
    async with AsyncSession(admin) as session:
        state = (
            await session.execute(
                text("""SELECT status,exclusive_protocol,result_digest
            FROM ops.feature_write_attempts WHERE attempt_id=:attempt"""),
                {"attempt": plan["attempt_id"]},
            )
        ).one()
        assert state.status == "completed"
        assert state.exclusive_protocol is False
        assert state.result_digest == receipt["result_digest"]


@pytest.mark.parametrize(
    "target",
    [
        "source_entities",
        "source_entity_heads",
        "source_records",
        "features",
        "feature_places",
        "feature_base_field_values",
        "provider_field_shadow_candidates",
        "feature_geocode_stamps",
    ],
)
async def test_each_strict_target_rejects_other_feature_in_same_dataset(strict_engines, target):
    import json

    admin, runtime = strict_engines
    dataset, items = await _batch_seed(admin, runtime, count=2)
    selected, outside = items
    plan, _ = await _plan(runtime, dataset, [selected])
    record = outside.bundle.source_record
    params = {
        "feature": outside.feature_id,
        "entity": _entity(outside.bundle),
        "record": record.source_record_key,
        "hash": record.raw_payload_hash,
        "raw": json.dumps(record.raw_data),
        "fetched": record.fetched_at,
    }
    statements = {
        "source_entities": (
            "UPDATE provider_sync.source_entities SET last_seen_at=now() "
            "WHERE source_entity_key=:entity",
            """SELECT last_seen_at FROM provider_sync.source_entities
            WHERE source_entity_key=:entity""",
        ),
        "source_entity_heads": (
            "UPDATE provider_sync.source_entity_heads SET observed_at=now() "
            "WHERE source_entity_key=:entity",
            "SELECT current_source_record_key,observed_at FROM provider_sync.source_entity_heads "
            "WHERE source_entity_key=:entity",
        ),
        "source_records": (
            """INSERT INTO provider_sync.source_records
            (source_record_key,source_entity_key,raw_data,raw_payload_hash,fetched_at)
            VALUES(:record,:entity,CAST(:raw AS jsonb),:hash,:fetched)""",
            "SELECT source_record_key,raw_payload_hash FROM provider_sync.source_records "
            "WHERE source_entity_key=:entity ORDER BY source_record_key",
        ),
        "features": (
            "UPDATE feature.features SET name='forbidden outside target' WHERE feature_id=:feature",
            "SELECT name FROM feature.features WHERE feature_id=:feature",
        ),
        "feature_places": (
            "UPDATE feature.feature_places SET phones=ARRAY['02-000-9999']::text[] "
            "WHERE feature_id=:feature",
            "SELECT phones FROM feature.feature_places WHERE feature_id=:feature",
        ),
        "feature_base_field_values": (
            "UPDATE feature.feature_base_field_values SET value_json=value_json "
            "WHERE feature_id=:feature",
            "SELECT field_path,value_json FROM feature.feature_base_field_values "
            "WHERE feature_id=:feature ORDER BY field_path",
        ),
        "provider_field_shadow_candidates": (
            "UPDATE feature.provider_field_shadow_candidates SET validated_at=validated_at "
            "WHERE feature_id=:feature",
            "SELECT field_path,validated_at FROM feature.provider_field_shadow_candidates "
            "WHERE feature_id=:feature ORDER BY field_path",
        ),
        "feature_geocode_stamps": (
            """INSERT INTO feature.feature_geocode_stamps
            (feature_id,geo_version_token,geo_data_token,reverse_outcome)
            VALUES(:feature,:version,:data,'not_called')""",
            "SELECT geo_version_token,geo_data_token FROM feature.feature_geocode_stamps "
            "WHERE feature_id=:feature",
        ),
    }
    params.update(version="dv1-" + "1" * 32, data="dd1-" + "2" * 32)
    mutation, observer = statements[target]
    async with AsyncSession(admin) as session:
        before = (await session.execute(text(observer), params)).all()
        if target == "feature_geocode_stamps":
            assert before == []  # Geo 없는 정본 legacy seed이며 INSERT 시도를 실제 검사한다.
        else:
            assert before
    managed = target in {
        "feature_base_field_values",
        "provider_field_shadow_candidates",
        "feature_geocode_stamps",
    }
    # 이 세 표는 runtime raw grant가 없다. 소유자의 관리 SQL 경계로 분리한다.
    async with AsyncSession(admin if managed else runtime) as session:
        await session.begin()
        try:
            await begin_scoped_feature_write(
                session,
                attempt_id=plan["attempt_id"],
                owner=plan["owner"],
                manifest_digest=plan["manifest_digest"],
            )
            if managed:
                await session.execute(text("SET LOCAL ROLE ktm_feature_schema_owner"))
            assert (await session.scalar(text("SELECT current_user::text"))) == (
                "ktm_feature_schema_owner" if managed else "ktm_feature_service"
            )
            with pytest.raises(DBAPIError) as error:
                await session.execute(text(mutation), params)
            assert error.value.orig.sqlstate == "23514"  # 42501은 수용 증거가 아니다.
            if target.startswith("source_"):
                assert _constraint_name(error.value) == "ck_strict_data_source_target"
            elif target == "feature_geocode_stamps":
                assert _constraint_name(error.value) == "ck_strict_data_feature_target"
            else:
                assert "candidate Feature is outside the applying manifest" in str(error.value.orig)
        finally:
            await session.rollback()
    async with AsyncSession(admin) as session:
        assert (await session.execute(text(observer), params)).all() == before


async def test_installer_mid_ddl_collision_rolls_back_only_nested_new_triggers(strict_engines):
    admin, _ = strict_engines
    inventory_sql = text("""SELECT t.oid,t.tgrelid::regclass::text AS relation,t.tgname,
        pg_get_triggerdef(t.oid) AS definition,t.tgenabled::text AS enabled
        FROM pg_trigger t WHERE NOT t.tgisinternal AND t.tgfoid IN (
        'feature._strict_sh_data_statement_guard()'::regprocedure,
        'feature._strict_sh_source_row_guard()'::regprocedure,
        'feature._strict_sh_feature_row_guard()'::regprocedure)
        ORDER BY t.tgrelid::regclass::text,t.tgname""")
    async with AsyncSession(admin) as session:
        original = (await session.execute(inventory_sql)).all()
        assert len(original) == 33
    async with AsyncSession(admin) as session:
        await session.begin()
        try:
            await _gate(session)
            await session.execute(text("SET LOCAL ROLE ktm_feature_schema_owner"))
            # 모든 이름은 설치된 정본33개와 고정 catalog에서 읽으며 identifier quote한다.
            for trigger in original:
                schema, relation = trigger.relation.split(".")
                assert schema in {"feature", "provider_sync", "ops"}
                assert trigger.tgname in {
                    "trg_00_strict_sh_data_protocol",
                    "trg_00_strict_sh_data_target",
                }
                quoted = [part.replace('"', '""') for part in (schema, relation)]
                await session.execute(
                    text(f'DROP TRIGGER "{trigger.tgname}" ON "{quoted[0]}"."{quoted[1]}"')
                )
            assert (await session.execute(inventory_sql)).all() == []
            # features는 installer 정렬 배열의 열번째 table이다. 앞선 CREATE 뒤 충돌한다.
            await session.execute(
                text("""CREATE TRIGGER trg_00_strict_sh_data_protocol
                BEFORE UPDATE ON feature.features FOR EACH ROW
                EXECUTE FUNCTION pg_catalog.suppress_redundant_updates_trigger()""")
            )
            collision_sql = text("""SELECT oid,pg_get_triggerdef(oid),tgenabled::text
                FROM pg_trigger WHERE tgrelid='feature.features'::regclass
                AND tgname='trg_00_strict_sh_data_protocol'
                AND tgfoid='pg_catalog.suppress_redundant_updates_trigger()'::regprocedure""")
            collision = (await session.execute(collision_sql)).one()
            with pytest.raises(DBAPIError) as error:
                async with session.begin_nested():
                    await session.execute(text("SELECT feature._install_strict_sh_data_guards()"))
            assert error.value.orig.sqlstate == "42710"
            assert "trg_00_strict_sh_data_protocol" in str(error.value.orig)
            assert (await session.execute(inventory_sql)).all() == []
            assert (await session.execute(collision_sql)).one() == collision
        finally:
            await session.rollback()
    async with AsyncSession(admin) as session:
        restored = (await session.execute(inventory_sql)).all()
        assert restored == original  # outer rollback이 원래 OID/definition/enabled33개도 복구한다.


async def test_existing_geo_stamp_update_checks_exact_outside_manifest_target(strict_engines):
    admin, runtime = strict_engines
    # 기존 stamp 경계 helper는 정본 GeoLoadContext + 실제 EX full loader로 stamp를 쓴다.
    dataset, items, seeded_stamps = await _active_name_setup(admin, runtime, count=2)
    selected, outside = items
    feature = outside.feature_id
    assert len(seeded_stamps) == 2
    stamp = next(row for row in seeded_stamps if row["feature_id"] == str(feature))
    observer = text("""SELECT tableoid::oid AS relation_oid,feature_id,geo_version_token,
        geo_data_token,reverse_outcome,stamped_at FROM feature.feature_geocode_stamps
        WHERE feature_id=:feature""")
    async with AsyncSession(admin) as session:
        before = (await session.execute(observer, {"feature": feature})).one()
        assert before.relation_oid == await session.scalar(
            text("SELECT 'feature.feature_geocode_stamps'::regclass::oid")
        )
        assert before.geo_version_token == stamp["geo_version_token"]
        assert before.geo_data_token == stamp["geo_data_token"]
        assert before.reverse_outcome == stamp["reverse_outcome"]
        assert before.stamped_at == stamp["stamped_at"]
    plan, _ = await _plan(runtime, dataset, [selected])
    # runtime raw UPDATE 권한 부재를 guard 성공으로 세지 않고 실제 표 소유자 SQL을 쓴다.
    async with AsyncSession(admin) as session:
        await session.begin()
        try:
            begun = await begin_scoped_feature_write(
                session,
                attempt_id=plan["attempt_id"],
                owner=plan["owner"],
                manifest_digest=plan["manifest_digest"],
            )
            assert begun["status"] == "applying"
            assert begun["exclusive_protocol"] is False
            await session.execute(text("SET LOCAL ROLE ktm_feature_schema_owner"))
            assert (
                await session.scalar(text("SELECT current_user::text"))
                == "ktm_feature_schema_owner"
            )
            with pytest.raises(DBAPIError) as error:
                await session.execute(
                    text("""UPDATE feature.feature_geocode_stamps
                    SET stamped_at=stamped_at+interval '1 second' WHERE feature_id=:feature"""),
                    {"feature": feature},
                )
            assert error.value.orig.sqlstate == "23514"
            assert "candidate Feature is outside the applying manifest" in str(error.value.orig)
        finally:
            await session.rollback()
    async with AsyncSession(admin) as session:
        assert (await session.execute(observer, {"feature": feature})).one() == before
    assert await _stamps(admin, [str(item.feature_id) for item in items]) == seeded_stamps
