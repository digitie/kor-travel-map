"""425의 실제 owned PG 계약. synthetic source이며 provider SDK 증거가 아니다."""

from __future__ import annotations

import asyncio
import hashlib
import json
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.core.ids import make_payload_hash, make_source_record_key
from kortravelmap.dto import SourceRecord
from kortravelmap.infra import feature_repo
from kortravelmap.infra.admin_feature_repo import author_admin_feature_field_overrides
from tests.integration.test_provider_field_scalar_projection import (
    scalar_container as scalar_container,
)
from tests.integration.test_provider_field_scalar_projection import (
    scalar_engines as scalar_engines,
)
from tests.integration.test_tvn36_override_lineage_spine import (
    _constraint_name,
    _open_domain_command,
)

pytestmark = pytest.mark.integration
_ROOT = Path(__file__).resolve().parents[2]
_EXPECTED_BODY = (
    (_ROOT / "alembic/versions/_425_provider_base_update_first.sql").read_text().split("$$")[1]
)
_LINE = "MULTILINESTRING((127 37.5,127.01 37.51))"
_AREA = "MULTIPOLYGON(((127 37.5,127.1 37.5,127.1 37.6,127 37.6,127 37.5)))"
_SHAPES = {
    "place": ("feature_places", "place_kind", "tourism", "place.biz_number", "123"),
    "event": ("feature_events", "event_kind", "festival", "event.venue_name", "광장"),
    "notice": ("feature_notices", "notice_type", "closure", "notice.source_agency", "기관"),
    "route": ("feature_routes", "route_type", "trail", "route.begin_name", "시점"),
    "area": ("feature_areas", "area_kind", "protected_area", "area.description", "설명"),
}


async def _gate(session):
    await session.execute(text("SET LOCAL statement_timeout='3s'"))
    await session.execute(text("SET LOCAL lock_timeout='1s'"))
    await feature_repo.lock_feature_curation_write(session)


async def _seed(engine, kind="place"):
    identity = uuid4().hex
    feature = str(uuid4())
    raw = {"fixture": identity, "kind": kind}
    payload_hash = make_payload_hash(raw)
    record = SourceRecord(
        provider="map425-synthetic",
        dataset_key=identity,
        source_entity_type=kind,
        source_entity_id=identity,
        raw_data=raw,
        raw_payload_hash=payload_hash,
        source_record_key=make_source_record_key(
            provider="map425-synthetic",
            dataset_key=identity,
            source_entity_type=kind,
            source_entity_id=identity,
            raw_payload_hash=payload_hash,
        ),
        fetched_at=datetime(2026, 10, 25, tzinfo=UTC),
    )
    entity = feature_repo._make_source_entity_key(record)
    table, column, value, _, _ = _SHAPES[kind]
    async with AsyncSession(engine) as session, session.begin():
        await _gate(session)
        dataset = await session.scalar(
            text("""INSERT INTO provider_sync.provider_datasets
            (provider,dataset_key,display_name,source_kind)
            VALUES('map425-synthetic',:identity,'425 synthetic','manual')
            RETURNING provider_dataset_id"""),
            {"identity": identity},
        )
        params = dict(
            feature=feature,
            dataset=dataset,
            entity=entity,
            record=record.source_record_key,
            hash=payload_hash,
            kind=kind,
            raw=json.dumps(raw),
            identity=identity,
        )
        for statement in [
            """INSERT INTO provider_sync.source_entities
                (source_entity_key,provider_dataset_id,source_entity_type,source_entity_id,
                 first_seen_at,last_seen_at)
                VALUES(:entity,:dataset,:kind,:identity,now(),now())""",
            """INSERT INTO provider_sync.source_records
                (source_record_key,source_entity_key,raw_data,raw_payload_hash,fetched_at)
                VALUES(:record,:entity,CAST(:raw AS jsonb),:hash,now())""",
            """INSERT INTO provider_sync.source_entity_heads
                (source_entity_key,current_source_record_key,observed_at)
                VALUES(:entity,:record,now())""",
            """INSERT INTO feature.features
                (feature_id,kind,name,category,lifecycle_state,publication_state,quality_state)
                VALUES(CAST(:feature AS uuid),:kind,'before','01010100',
                       'active','published','valid')""",
        ]:
            await session.execute(text(statement), params)
        # 관계/열은 위 고정 kind 표에서만 선택한다.
        if kind == "area":
            await session.execute(
                text("""INSERT INTO feature.feature_areas
                (feature_id,kind,area_kind,geom)
                VALUES(CAST(:feature AS uuid),'area','protected_area',
                       x_extension.st_geomfromtext(:wkt,4326))"""),
                {"feature": feature, "wkt": _AREA},
            )
        else:
            await session.execute(
                text(
                    f"INSERT INTO feature.{table}(feature_id,kind,{column}) "
                    "VALUES(CAST(:feature AS uuid),:kind,:value)"
                ),
                {"feature": feature, "kind": kind, "value": value},
            )
            if kind == "route":
                await session.execute(
                    text("""INSERT INTO feature.feature_route_geometries
                    (feature_id,kind,geom) VALUES(CAST(:feature AS uuid),'route',
                    x_extension.st_geomfromtext(:wkt,4326))"""),
                    {"feature": feature, "wkt": _LINE},
                )
        await session.execute(
            text("""INSERT INTO provider_sync.source_links
            (feature_id,source_entity_key,source_role,match_method,confidence)
            VALUES(CAST(:feature AS uuid),:entity,'primary','fixture',100)"""),
            params,
        )
    return params


async def _revision(session, seed):
    return await session.scalar(
        text("SELECT row_revision FROM feature.features WHERE feature_id=CAST(:feature AS uuid)"),
        seed,
    )


async def _patch(session, seed, values, geometry=None, *, expected=None):
    revision = await _revision(session, seed) if expected is None else expected
    return (
        (
            await session.execute(
                text("""CALL feature.apply_provider_feature_field_patch(
        CAST(:feature AS uuid),:dataset,:entity,:record,:revision,
        CAST(:values AS jsonb),CAST(:geometry AS jsonb),NULL,NULL,NULL)"""),
                {
                    **seed,
                    "revision": revision,
                    "values": json.dumps(values),
                    "geometry": json.dumps(geometry or {}),
                },
            )
        )
        .mappings()
        .one()
    )


async def _base(engine, seed):
    async with AsyncSession(engine) as session:
        return {
            row["field_path"]: dict(row)
            for row in (
                await session.execute(
                    text("""
            SELECT field_path,provider_dataset_id,source_entity_key,source_record_key,
                source_raw_payload_hash,value_json,value_json IS NULL AS sql_null,
                value_json = 'null'::jsonb AS json_null,
                x_extension.st_astext(value_geometry) AS wkt,
                base_revision,observed_at,updated_at
            FROM feature.feature_base_field_values
            WHERE feature_id=CAST(:feature AS uuid) ORDER BY field_path"""),
                    seed,
                )
            ).mappings()
        }


async def _snapshot(engine, seed):
    async with AsyncSession(engine) as session:
        return (
            await session.execute(
                text("""SELECT to_jsonb(core),
            (SELECT jsonb_agg(to_jsonb(base) ORDER BY field_path)
             FROM feature.feature_base_field_values base WHERE base.feature_id=core.feature_id)
            FROM feature.features core WHERE core.feature_id=CAST(:feature AS uuid)"""),
                seed,
            )
        ).one()


@pytest.mark.parametrize("kind", list(_SHAPES))
async def test_missing_then_same_value_update_preserves_all_kind_lineage_and_clocks(
    scalar_engines, kind
):
    admin, runtime = scalar_engines
    seed = await _seed(admin, kind)
    field, value = _SHAPES[kind][3:]
    geometry = (
        {"route.geom": _LINE}
        if kind == "route"
        else ({"area.geom": _AREA} if kind == "area" else {"core.coord": "POINT(127 37.5)"})
    )
    values = {"core.name": "provider name", field: value}
    assert await _base(admin, seed) == {}
    async with AsyncSession(runtime) as session, session.begin():
        await _gate(session)
        out = await _patch(session, seed, values, geometry)
        assert out["o_applied_field_count"] == 3
    inserted = await _base(admin, seed)
    assert len(inserted) == 3
    for row in inserted.values():
        assert row["source_record_key"] == seed["record"]
        assert row["source_raw_payload_hash"] == seed["hash"]
        assert row["base_revision"] == out["o_row_revision"]
        assert row["observed_at"].tzinfo is not None
        # absent INSERT의 updated_at DEFAULT now()를 clock_timestamp()로 바꾸지 않는다.
        assert row["updated_at"] <= row["observed_at"]
    async with AsyncSession(runtime) as session, session.begin():
        await _gate(session)
        before_revision = await _revision(session, seed)
        again = await _patch(session, seed, values, geometry)
        assert again["o_row_revision"] == before_revision + 1
    updated = await _base(admin, seed)
    for path, row in updated.items():
        assert row["value_json"] == inserted[path]["value_json"]
        assert row["wkt"] == inserted[path]["wkt"]
        assert row["base_revision"] == again["o_row_revision"]
        assert row["observed_at"] > inserted[path]["observed_at"]
        assert row["updated_at"] >= row["observed_at"]
        assert row["source_entity_key"] == seed["entity"]


@pytest.mark.parametrize(
    ("values", "geometry", "expected", "sqlstate"),
    [
        ({"core.name": "x"}, {}, 99, "40001"),
        ({"core.not_registered": "x"}, {}, None, "23514"),
        ({"core.name": 12}, {}, None, "23514"),
        ({}, {"core.coord": "LINESTRING(127 37.5,127.1 37.6)"}, None, "23514"),
    ],
)
async def test_invalid_patch_rolls_back_full_business_state(
    scalar_engines, values, geometry, expected, sqlstate
):
    admin, runtime = scalar_engines
    seed = await _seed(admin)
    before = await _snapshot(admin, seed)

    async def attempt():
        async with AsyncSession(runtime) as session, session.begin():
            await _gate(session)
            await _patch(session, seed, values, geometry, expected=expected)

    with pytest.raises(DBAPIError) as caught:
        await attempt()
    assert getattr(caught.value.orig, "sqlstate", None) == sqlstate
    assert await _snapshot(admin, seed) == before


async def test_geometry_can_return_to_registry_allowed_null(scalar_engines):
    admin, runtime = scalar_engines
    seed = await _seed(admin)
    for geometry in [{"core.coord": "POINT(127 37.5)"}, {"core.coord": None}]:
        async with AsyncSession(runtime) as session, session.begin():
            await _gate(session)
            await _patch(session, seed, {}, geometry)
    row = (await _base(admin, seed))["core.coord"]
    assert row["value_json"] is None  # JSON null의 asyncpg 반환값
    assert row["sql_null"] is False
    assert row["json_null"] is True
    assert row["wkt"] is None
    assert row["updated_at"] >= row["observed_at"]


async def test_notice_first_probe_preserves_original_start(scalar_engines):
    admin, runtime = scalar_engines
    seed = await _seed(admin, "notice")
    first = "2026-10-24T00:00:00+00:00"
    for start in [first, "2026-10-25T00:00:00+00:00"]:
        async with AsyncSession(runtime) as session, session.begin():
            await _gate(session)
            await _patch(
                session,
                seed,
                {
                    "notice.valid_start_time": start,
                    "notice.payload": {"valid_start_origin": "first_probe"},
                },
            )
    assert (await _base(admin, seed))["notice.valid_start_time"]["value_json"] == first


async def test_operator_name_stays_effective_while_provider_base_changes(scalar_engines):
    admin, runtime = scalar_engines
    seed = await _seed(admin)
    async with AsyncSession(runtime) as session, session.begin():
        await _gate(session)
        await _patch(session, seed, {"core.name": "provider old"})
        command = await _open_domain_command(
            session, actor="admin:425-test", operation="admin.feature.override.author"
        )
        await author_admin_feature_field_overrides(
            session,
            seed["feature"],
            expected_row_revision=await _revision(session, seed),
            reason_code="operator_correction",
            operator="admin:425-test",
            command_id=command,
            values={"core.name": "operator name"},
            geometry_wkt={},
        )
    async with AsyncSession(runtime) as session, session.begin():
        await _gate(session)
        await _patch(session, seed, {"core.name": "provider new"})
        assert (
            await session.scalar(
                text("SELECT name FROM feature.features WHERE feature_id=CAST(:feature AS uuid)"),
                seed,
            )
            == "operator name"
        )
    assert (await _base(admin, seed))["core.name"]["value_json"] == "provider new"


async def test_owner_insert_first_blocks_feature_then_updates_after_commit(
    scalar_engines, record_property
):
    admin, runtime = scalar_engines
    seed = await _seed(admin)
    ready = asyncio.get_running_loop().create_future()

    async def writer():
        async with AsyncSession(runtime) as session, session.begin():
            await _gate(session)
            pid = await session.scalar(text("SELECT pg_backend_pid()"))
            ready.set_result(pid)
            return await _patch(session, seed, {"core.name": "provider after owner"})

    async with AsyncSession(admin) as owner:
        await owner.begin()
        await owner.execute(text("SET LOCAL statement_timeout='3s'"))
        owner_pid = await owner.scalar(text("SELECT pg_backend_pid()"))
        await owner.execute(
            text("""INSERT INTO feature.feature_base_field_values
            (feature_id,field_path,provider_dataset_id,source_entity_key,source_record_key,
             source_raw_payload_hash,value_json,base_revision,observed_at)
            VALUES(CAST(:feature AS uuid),'core.name',:dataset,:entity,:record,:hash,
                   '"owner initial"'::jsonb,1,clock_timestamp())"""),
            seed,
        )
        task = asyncio.create_task(writer())
        try:
            waiter = await asyncio.wait_for(ready, 1)
            async with asyncio.timeout(1), AsyncSession(admin) as observer:
                while True:
                    blockers = await observer.scalar(
                        text("SELECT pg_blocking_pids(:pid)"), {"pid": waiter}
                    )
                    if owner_pid in blockers:
                        break
                    await asyncio.sleep(0.005)
            record_property("owner_blocker_pid", owner_pid)
            record_property("provider_waiter_pid", waiter)
            assert owner_pid != waiter
            await owner.commit()
            out = await asyncio.wait_for(task, 3)
            assert out["o_row_revision"] == 2
        finally:
            await owner.rollback()
            if not task.done():
                task.cancel()
            with suppress(asyncio.CancelledError):
                await task
    assert (await _base(admin, seed))["core.name"]["value_json"] == "provider after owner"


async def test_actual_catalog_body_owner_acl_and_service_identity(scalar_engines):
    admin, runtime = scalar_engines
    expected = _EXPECTED_BODY
    async with AsyncSession(admin) as session:
        row = (
            await session.execute(
                text("""SELECT p.prosrc,p.prokind::text,p.prosecdef,
            p.provolatile::text,p.proconfig,r.rolname,
            ARRAY(SELECT role.rolname FROM aclexplode(p.proacl) acl
                  LEFT JOIN pg_roles role ON role.oid=acl.grantee ORDER BY role.rolname)
            FROM pg_proc p JOIN pg_roles r ON r.oid=p.proowner
            WHERE p.oid=to_regprocedure(
              'feature.apply_provider_feature_field_patch(uuid,bigint,text,text,bigint,jsonb,jsonb)'
            )""")
            )
        ).one()
        assert row[0] == expected
        assert (
            hashlib.sha256(row[0].encode()).hexdigest()
            == hashlib.sha256(expected.encode()).hexdigest()
        )
        assert tuple(row[1:6]) == (
            "p",
            True,
            "v",
            ["search_path=pg_catalog"],
            "ktm_feature_state_procedure_owner",
        )
        assert row[6] == ["ktm_feature_runtime", "ktm_feature_state_procedure_owner"]
    async with AsyncSession(runtime) as session:
        assert tuple((await session.execute(text("SELECT session_user,current_user"))).one()) == (
            "ktm_feature_service",
            "ktm_feature_service",
        )


async def test_invalid_source_precedes_invalid_field_and_rolls_back(scalar_engines):
    admin, runtime = scalar_engines
    seed = await _seed(admin)
    before = await _snapshot(admin, seed)
    bad = {**seed, "record": "sr_" + "f" * 20}

    async def attempt():
        async with AsyncSession(runtime) as session, session.begin():
            await _gate(session)
            await _patch(session, bad, {"core.not_registered": "invalid"})

    with pytest.raises(DBAPIError) as caught:
        await attempt()
    assert getattr(caught.value.orig, "sqlstate", None) == "23514"
    assert _constraint_name(caught.value) == "ck_feature_provider_source_provenance"
    assert await _snapshot(admin, seed) == before
