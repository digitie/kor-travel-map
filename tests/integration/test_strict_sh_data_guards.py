"""비활성429 설치를 owned PG에서만 명시 검증한다. 운영 activation 증거가 아니다."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.dto import Feature
from kortravelmap.infra import feature_repo
from kortravelmap.infra.feature_identity import resolve_feature_identity
from kortravelmap.infra.scoped_feature_writes import begin_scoped_feature_write
from kortravelmap.infra.scoped_provider_batch import ProviderScalarRefreshItem
from tests.integration.test_provider_base_update_first import _gate, _seed
from tests.integration.test_provider_field_scalar_projection import (
    scalar_container as scalar_container,
)
from tests.integration.test_provider_field_scalar_projection import scalar_engines as scalar_engines
from tests.integration.test_scoped_provider_batch import _dataset_bundle, _plan, _seed_bundles
from tests.integration.test_scoped_provider_batch import _seed as _batch_seed
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
                            "SELECT tgenabled FROM pg_trigger WHERE "
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
    plan, _ = await _plan(runtime, dataset, [ProviderScalarRefreshItem(feature, bundle)])
    statements = {
        "coord": """UPDATE feature.features SET
            coord=x_extension.st_geomfromtext('POINT(127 37)',4326),coord_precision_digits=6
            WHERE feature_id=:feature""",
        "address": "UPDATE feature.features SET address='outside scalar' WHERE feature_id=:feature",
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
                    {"feature": feature, "payload": '{"outside": "scalar"}'},
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
        assert row.address is None
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
