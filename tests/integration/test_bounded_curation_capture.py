"""제한 capture만 검증한다. synthetic 고유 PG이며 collector/RC 활성화 증거가 아니다."""

from __future__ import annotations

import json
from datetime import UTC, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.core.ids import make_payload_hash, make_source_record_key
from kortravelmap.infra import feature_repo
from kortravelmap.infra.admin_feature_repo import author_admin_feature_field_overrides
from tests.integration.test_provider_base_update_first import _gate, _patch, _seed
from tests.integration.test_provider_field_scalar_projection import (
    scalar_container as scalar_container,
)
from tests.integration.test_provider_field_scalar_projection import (
    scalar_engines as scalar_engines,
)
from tests.integration.test_tvn36_override_lineage_spine import _open_domain_command

pytestmark = pytest.mark.integration
_AGGREGATES = (
    "source_entity_count",
    "input_member_count",
    "last_source_modified_at",
    "source_input_set_hash",
)


async def _capture(session, dataset):
    await session.execute(text("SET LOCAL ROLE ktm_curation_command_owner"))
    return dict(
        (
            await session.execute(
                text(
                    "SELECT * FROM feature._bounded_provider_curation_input_set("
                    "CAST(:dataset AS bigint))"
                ),
                {"dataset": dataset},
            )
        )
        .mappings()
        .one()
    )


def _rejected(row, reason):
    assert row["capture_complete"] is False
    assert row["reason"] == reason
    assert all(row[key] is None for key in _AGGREGATES)


async def _set_place(admin, seed, *, payload=None, phones=None, business_hours=False):
    async with AsyncSession(admin) as session, session.begin():
        await _gate(session)
        if payload is not None:
            await session.execute(
                text("""UPDATE feature.feature_places
                SET payload=CAST(:payload AS jsonb),facility_info=CAST(:payload AS jsonb),
                    reviews_link=CAST(:payload AS jsonb)
                WHERE feature_id=CAST(:feature AS uuid)"""),
                {**seed, "payload": json.dumps(payload)},
            )
        if phones is not None:
            await session.execute(
                text("""UPDATE feature.feature_places SET phones=CAST(:phones AS text[])
                WHERE feature_id=CAST(:feature AS uuid)"""),
                {**seed, "phones": phones},
            )
        if business_hours:
            await session.execute(
                text("""UPDATE feature.feature_places SET business_hours='null'::jsonb
                WHERE feature_id=CAST(:feature AS uuid)"""),
                seed,
            )


@pytest.mark.parametrize("phones", [[], ["02-123-4567"], ["한글☎", 'quote"\\\n']])
@pytest.mark.parametrize("business_hours", [False, True], ids=["sql-null", "json-null"])
async def test_exact_old_four_aggregates_for_supported_place_shapes(
    scalar_engines, phones, business_hours
):
    admin, _ = scalar_engines
    seed = await _seed(admin)
    await _set_place(
        admin,
        seed,
        payload={"한글": '제주\n"\\', "nullable": None},
        phones=phones,
        business_hours=business_hours,
    )
    async with AsyncSession(admin) as session, session.begin():
        await _gate(session)
        expected = (
            (
                await session.execute(
                    text("SELECT * FROM feature.current_provider_curation_input_set(:dataset)"),
                    seed,
                )
            )
            .mappings()
            .one()
        )
        actual = await _capture(session, seed["dataset"])
        assert actual["capture_complete"] is True
        assert actual["reason"] is None
        assert tuple(actual[k] for k in _AGGREGATES) == tuple(expected[k] for k in _AGGREGATES)


@pytest.mark.parametrize("payload", [{"v": True}, {"v": []}, {"v": {}}, {"v": 1}])
async def test_unsupported_json_shape_does_not_become_a_partial_capture(scalar_engines, payload):
    admin, _ = scalar_engines
    seed = await _seed(admin)
    await _set_place(admin, seed, payload=payload)
    async with AsyncSession(admin) as session, session.begin():
        _rejected(await _capture(session, seed["dataset"]), "shape_unsupported")


@pytest.mark.parametrize("case", ["string", "key", "phone", "phone-count"])
async def test_known_shape_limits_are_enforced_before_final_capture(scalar_engines, case):
    admin, _ = scalar_engines
    seed = await _seed(admin)
    await _set_place(
        admin,
        seed,
        payload={"v": "x" * 257} if case == "string" else {"k" * 257: "v"} if case == "key" else {},
        phones=["x" * 257] if case == "phone" else ["x"] * 33 if case == "phone-count" else [],
    )
    async with AsyncSession(admin) as session, session.begin():
        _rejected(await _capture(session, seed["dataset"]), "shape_unsupported")


@pytest.mark.parametrize("hours", [{}, [], 0, "unknown"])
async def test_nonnull_business_hours_remain_unsupported(scalar_engines, hours):
    admin, _ = scalar_engines
    seed = await _seed(admin)
    async with AsyncSession(admin) as session, session.begin():
        await _gate(session)
        await session.execute(
            text("""UPDATE feature.feature_places SET business_hours=CAST(:hours AS jsonb)
            WHERE feature_id=CAST(:feature AS uuid)"""),
            {**seed, "hours": json.dumps(hours)},
        )
        _rejected(await _capture(session, seed["dataset"]), "shape_unsupported")


async def test_tiny_huge_exponent_is_rejected_without_calling_old_serializer(scalar_engines):
    admin, _ = scalar_engines
    seed = await _seed(admin)
    async with AsyncSession(admin) as session, session.begin():
        await _gate(session)
        await session.execute(
            text("""UPDATE feature.feature_places SET payload=CAST(:numeric_payload AS jsonb)
            WHERE feature_id=CAST(:feature AS uuid)"""),
            {**seed, "numeric_payload": '{"v":1e100000}'},
        )
        assert await session.scalar(
            text("""SELECT pg_column_size(payload)<8192
            AND pg_column_compression(payload) IS NULL FROM feature.feature_places
            WHERE feature_id=CAST(:feature AS uuid)"""),
            seed,
        )
        # 시험 TX 안에서만 기존 serializer를 trap으로 바꾸고 끝에 반드시 rollback한다.
        await session.execute(
            text("""CREATE OR REPLACE FUNCTION feature.current_provider_curation_input_set(
                p_provider_dataset_id bigint)
            RETURNS TABLE(source_entity_count bigint,input_member_count bigint,
                last_source_modified_at date,source_input_set_hash text)
            LANGUAGE plpgsql STABLE SECURITY DEFINER
            SET search_path TO pg_catalog,feature,provider_sync,ops,x_extension AS $$
            BEGIN RAISE EXCEPTION 'unexpected serializer call' USING ERRCODE='P0001'; END $$""")
        )
        _rejected(await _capture(session, seed["dataset"]), "shape_unsupported")
        await session.execute(text("RESET ROLE"))
        await session.execute(
            text(
                "UPDATE feature.feature_places SET payload='{}'::jsonb "
                "WHERE feature_id=CAST(:feature AS uuid)"
            ),
            seed,
        )
        # 정상 형태도 기존 함수를 재호출하지 않아 trap에 도달하지 않는다.
        positive = await _capture(session, seed["dataset"])
        assert positive["capture_complete"] is True
        await session.rollback()


async def test_compressed_payload_is_rejected_at_metadata_stage(scalar_engines):
    admin, _ = scalar_engines
    seed = await _seed(admin)
    await _set_place(admin, seed, payload={"v": "x" * 16000})
    async with AsyncSession(admin) as session, session.begin():
        assert await session.scalar(
            text("""SELECT pg_column_compression(payload) IS NOT NULL
            FROM feature.feature_places WHERE feature_id=CAST(:feature AS uuid)"""),
            seed,
        )
        _rejected(await _capture(session, seed["dataset"]), "storage_unsupported")


@pytest.mark.parametrize("missing", ["head", "link"])
async def test_missing_lineage_or_membership_returns_no_aggregates(scalar_engines, missing):
    admin, _ = scalar_engines
    seed = await _seed(admin)
    async with AsyncSession(admin) as session, session.begin():
        await _gate(session)
        table = (
            "provider_sync.source_entity_heads"
            if missing == "head"
            else "provider_sync.source_links"
        )
        await session.execute(text(f"DELETE FROM {table} WHERE source_entity_key=:entity"), seed)
        _rejected(
            await _capture(session, seed["dataset"]),
            "lineage_incomplete" if missing == "head" else "membership_unsupported",
        )
        # head 누락은 deferred 무결성 검사에 막히므로 관찰 뒤 시험 TX만 rollback한다.
        await session.rollback()


async def test_shared_feature_in_another_dataset_is_rejected(scalar_engines):
    admin, _ = scalar_engines
    seed, other = await _seed(admin), await _seed(admin)
    async with AsyncSession(admin) as session, session.begin():
        await _gate(session)
        await session.execute(
            text("""INSERT INTO provider_sync.source_links
            (feature_id,source_entity_key,source_role,match_method,confidence)
            VALUES(CAST(:feature AS uuid),:entity,'enrichment','fixture',100)"""),
            {"feature": seed["feature"], "entity": other["entity"]},
        )
        _rejected(await _capture(session, seed["dataset"]), "membership_unsupported")


@pytest.mark.parametrize("status", ["active", "inactive"])
async def test_any_operator_override_disqualifies_the_whole_scope(scalar_engines, status):
    admin, runtime = scalar_engines
    seed = await _seed(admin)
    async with AsyncSession(runtime) as session, session.begin():
        await _gate(session)
        await _patch(session, seed, {"core.name": "provider"})
        command = await _open_domain_command(
            session, actor="admin:428-test", operation="admin.feature.override.author"
        )
        await author_admin_feature_field_overrides(
            session,
            seed["feature"],
            expected_row_revision=2,
            reason_code="operator_correction",
            operator="admin:428-test",
            command_id=command,
            values={"core.name": "operator"},
            geometry_wkt={},
        )
    async with AsyncSession(admin) as session, session.begin():
        await _gate(session)
        if status == "inactive":
            await session.execute(
                text("""UPDATE ops.feature_overrides SET status='inactive'
                WHERE feature_id=CAST(:feature AS uuid)"""),
                seed,
            )
        _rejected(await _capture(session, seed["dataset"]), "membership_unsupported")


async def test_retired_place_and_other_kind_are_ineligible(scalar_engines):
    admin, runtime = scalar_engines
    seed = await _seed(admin)
    other = await _seed(admin, "event")
    async with AsyncSession(runtime) as session, session.begin():
        assert (
            await feature_repo.retire_features_by_source_entity_ids(
                session,
                provider="map425-synthetic",
                dataset_key=seed["identity"],
                source_entity_type="place",
                source_entity_ids={seed["identity"]},
            )
            == 1
        )
    async with AsyncSession(admin) as session, session.begin():
        _rejected(await _capture(session, seed["dataset"]), "membership_unsupported")
        _rejected(await _capture(session, other["dataset"]), "membership_unsupported")


async def test_runtime_login_cannot_call_private_capture(scalar_engines):
    admin, runtime = scalar_engines
    seed = await _seed(admin)
    async with AsyncSession(runtime) as session, session.begin():
        with pytest.raises(DBAPIError) as error:
            await session.execute(
                text("SELECT * FROM feature._bounded_provider_curation_input_set(:dataset)"), seed
            )
        assert error.value.orig.sqlstate == "42501"
        await session.rollback()


@pytest.mark.parametrize("dataset", [None, 0, -1, 9223372036854775807])
async def test_empty_or_invalid_dataset_has_no_success_aggregates(scalar_engines, dataset):
    admin, _ = scalar_engines
    async with AsyncSession(admin) as session, session.begin():
        _rejected(await _capture(session, dataset), "scope_unsupported")


@pytest.mark.parametrize(
    ("count", "reason"), [(2730, "lineage_incomplete"), (2731, "budget_exceeded")]
)
async def test_max_plus_one_count_precedes_payload_and_lineage(scalar_engines, count, reason):
    admin, _ = scalar_engines
    seed = await _seed(admin)
    async with AsyncSession(admin) as session, session.begin():
        await _gate(session)
        await session.execute(
            text("""INSERT INTO provider_sync.source_entities
            (source_entity_key,provider_dataset_id,source_entity_type,source_entity_id,
             first_seen_at,last_seen_at)
            SELECT 'se_'||md5(:identity||n::text)||md5(n::text||:identity),
                   :dataset,'place',:identity||n::text,now(),now()
            FROM generate_series(1,CAST(:extra AS integer)) AS g(n)"""),
            {**seed, "extra": count - 1},
        )
        _rejected(await _capture(session, seed["dataset"]), reason)
        await session.rollback()


async def test_extra_place_column_is_rejected_before_record_serialization(scalar_engines):
    admin, _ = scalar_engines
    seed = await _seed(admin)
    async with AsyncSession(admin) as session, session.begin():
        await session.execute(
            text("ALTER TABLE feature.feature_places ADD COLUMN bounded_capture_test_extra text")
        )
        _rejected(await _capture(session, seed["dataset"]), "storage_unsupported")
        await session.rollback()


async def _same_dataset_seeds(
    admin, count, *, extra_key_prefixes=None, controlled_import_clock=False
):
    """identity를 옮기지 않고 처음부터 한 DS에 별개 entity를 생성한다."""
    first = await _seed(admin)
    result = [first]
    async with AsyncSession(admin) as session, session.begin():
        await _gate(session)
        imported = None
        if controlled_import_clock:
            prior = await session.scalar(
                text(
                    "SELECT imported_at FROM provider_sync.source_records "
                    "WHERE source_record_key=:record"
                ),
                first,
            )
            # 첫 행보다 이틀 뒤 17:30 UTC를 고정하여 Seoul의 다음날 경계를 반드시 지난다.
            imported = prior.astimezone(UTC).replace(
                hour=17, minute=30, second=0, microsecond=0
            ) + timedelta(days=2)
        for index in range(count - 1):
            identity = uuid4().hex
            raw = {"fixture": identity, "kind": "place"}
            digest = make_payload_hash(raw)
            entity = feature_repo._make_source_entity_key(
                provider="map425-synthetic",
                dataset_key=first["identity"],
                source_entity_type="place",
                source_entity_id=identity,
            )
            if extra_key_prefixes is not None:
                # 기존 capture가 지원하는 짧은 legacy key의 collation 회귀 전용이다.
                entity = extra_key_prefixes[index] + identity
            record = make_source_record_key(
                provider="map425-synthetic",
                dataset_key=first["identity"],
                source_entity_type="place",
                source_entity_id=identity,
                raw_payload_hash=digest,
            )
            seed = {
                **first,
                "feature": str(uuid4()),
                "identity": identity,
                "entity": entity,
                "record": record,
                "hash": digest,
                "raw": json.dumps(raw),
                "imported": imported,
            }
            for statement in (
                """INSERT INTO provider_sync.source_entities
                (source_entity_key,provider_dataset_id,source_entity_type,source_entity_id,
                 first_seen_at,last_seen_at)
                VALUES(:entity,:dataset,'place',:identity,now(),now())""",
                """INSERT INTO provider_sync.source_records
                (source_record_key,source_entity_key,raw_data,raw_payload_hash,fetched_at,imported_at)
                VALUES(:record,:entity,CAST(:raw AS jsonb),:hash,now(),
                       COALESCE(CAST(:imported AS timestamptz),now()))""",
                """INSERT INTO provider_sync.source_entity_heads
                (source_entity_key,current_source_record_key,observed_at)
                VALUES(:entity,:record,now())""",
                """INSERT INTO feature.features
                (feature_id,kind,name,category,lifecycle_state,publication_state,quality_state)
                VALUES(CAST(:feature AS uuid),'place','before','01010100',
                       'active','published','valid')""",
                """INSERT INTO feature.feature_places(feature_id,kind,place_kind)
                VALUES(CAST(:feature AS uuid),'place','tourism')""",
                """INSERT INTO provider_sync.source_links
                (feature_id,source_entity_key,source_role,match_method,confidence)
                VALUES(CAST(:feature AS uuid),:entity,'primary','fixture',100)""",
            ):
                await session.execute(text(statement), seed)
            result.append(seed)
    return result


@pytest.mark.parametrize("mode", ["binary", "encoded"])
async def test_whole_payload_budgets_reject_before_aggregate(scalar_engines, mode):
    import random

    admin, _ = scalar_engines
    seeds = await _same_dataset_seeds(admin, 24 if mode == "binary" else 18)
    rng = random.Random(428)
    payload = {
        str(i): "".join(rng.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=240))
        if mode == "binary"
        else "\x01" * 240
        for i in range(16)
    }
    async with AsyncSession(admin) as session, session.begin():
        await _gate(session)
        # 시험 TX의 storage만 바꾸어 압축 거부와 전체 예산 거부를 분리한다.
        for column in ("facility_info", "reviews_link", "payload"):
            await session.execute(
                text(
                    f"ALTER TABLE feature.feature_places ALTER COLUMN {column} SET STORAGE EXTERNAL"
                )
            )
        for seed in seeds:
            await session.execute(
                text("""UPDATE feature.feature_places
                SET payload=CAST(:payload AS jsonb),facility_info=CAST(:payload AS jsonb),
                    reviews_link=CAST(:payload AS jsonb)
                WHERE feature_id=CAST(:feature AS uuid)"""),
                {**seed, "payload": json.dumps(payload)},
            )
        sizes = (
            await session.execute(
                text("""SELECT
            sum(pg_column_size(p.payload)+pg_column_size(p.facility_info)
                +pg_column_size(p.reviews_link)),
            sum(octet_length(to_jsonb(p)::text)),
            bool_and(pg_column_compression(p.payload) IS NULL
                AND pg_column_compression(p.facility_info) IS NULL
                AND pg_column_compression(p.reviews_link) IS NULL)
            FROM feature.feature_places p JOIN provider_sync.source_links l USING(feature_id)
            JOIN provider_sync.source_entities e USING(source_entity_key)
            WHERE e.provider_dataset_id=:dataset"""),
                seeds[0],
            )
        ).one()
        assert sizes[2] is True
        if mode == "binary":
            assert sizes[0] > 262144
        else:
            assert sizes[0] < 240000
            assert sizes[1] > 1048576
        _rejected(await _capture(session, seeds[0]["dataset"]), "budget_exceeded")
        await session.rollback()


async def test_canonical_body_and_private_acl_stay_exact(scalar_engines):
    from hashlib import sha256

    admin, _ = scalar_engines
    async with AsyncSession(admin) as session, session.begin():
        row = (
            await session.execute(
                text("""SELECT p.prosrc,p.prosecdef,p.provolatile::text,
            r.rolname,p.proconfig FROM pg_proc p JOIN pg_roles r ON r.oid=p.proowner
            WHERE p.oid='feature.current_provider_curation_input_set(bigint)'::regprocedure
            """)
            )
        ).one()
        assert sha256(row[0].encode()).hexdigest() == (
            "86bce78e9f40874f6a8312ff6e4e5f6aceaf836fa1cd07648637630083a2e5e0"
        )
        assert tuple(row[1:4]) == (True, "s", "ktm_feature_schema_owner")
        assert row[4] == ["search_path=pg_catalog, feature, provider_sync, ops, x_extension"]
        for role in (
            "ktm_feature_runtime",
            "ktm_feature_service",
            "ktm_curation_provider_executor",
        ):
            assert (
                await session.scalar(
                    text("""SELECT has_function_privilege(:role,
                'feature._bounded_provider_curation_input_set(bigint)','EXECUTE')"""),
                    {"role": role},
                )
                is False
            )
        assert (
            await session.scalar(
                text("""SELECT has_function_privilege(
            'ktm_curation_command_owner',
            'feature._bounded_provider_curation_input_set(bigint)','EXECUTE')""")
            )
            is True
        )


async def test_metadata_helper_dependency_is_available_to_capture_owner(scalar_engines):
    admin, _ = scalar_engines
    async with AsyncSession(admin) as session, session.begin():
        assert (
            await session.scalar(
                text("""SELECT has_function_privilege(
            'ktm_feature_schema_owner',
            'feature._heritage_evidence_metadata_bytes(bigint[],boolean[],integer[],boolean[])',
            'EXECUTE')""")
            )
            is True
        )


@pytest.mark.parametrize("timezone", ["UTC", "Asia/Seoul", "Pacific/Honolulu"])
async def test_multiple_rows_fold_matches_canonical_order_and_import_date(scalar_engines, timezone):
    admin, _ = scalar_engines
    seeds = await _same_dataset_seeds(
        admin, 3, extra_key_prefixes=("Zebra한글", "alpha한글"), controlled_import_clock=True
    )
    # 각각 다른 Unicode/escape 값을 주고 실제 hash·집계 네 값을 정본과 비교한다.
    for seed, value in zip(reversed(seeds), ["가나다", "Zebra", "alpha\n\t"], strict=True):
        await _set_place(admin, seed, payload={"v": value}, phones=[value])
    async with AsyncSession(admin) as session, session.begin():
        await session.execute(
            text("SELECT set_config('TimeZone',:timezone,true)"), {"timezone": timezone}
        )
        await _gate(session)
        expected = (
            (
                await session.execute(
                    text("SELECT * FROM feature.current_provider_curation_input_set(:dataset)"),
                    seeds[0],
                )
            )
            .mappings()
            .one()
        )
        actual = await _capture(session, seeds[0]["dataset"])
        assert actual["capture_complete"] is True
        assert tuple(actual[k] for k in _AGGREGATES) == tuple(expected[k] for k in _AGGREGATES)
        assert actual["source_entity_count"] == actual["input_member_count"] == 3
        assert (
            actual["last_source_modified_at"]
            == seeds[1]["imported"].astimezone(ZoneInfo(timezone)).date()
        )


async def test_non_default_entity_key_collation_is_known_rejection(scalar_engines):
    admin, _ = scalar_engines
    seed = await _seed(admin)
    async with AsyncSession(admin) as session, session.begin():
        await _gate(session)
        await session.execute(
            text(
                "ALTER TABLE provider_sync.source_entities "
                'ALTER COLUMN source_entity_key TYPE text COLLATE "C"'
            )
        )
        _rejected(await _capture(session, seed["dataset"]), "storage_unsupported")
        await session.rollback()


async def test_record_lookup_uses_bounded_index_with_unrelated_history(scalar_engines):
    admin, _ = scalar_engines
    seed, other = await _seed(admin), await _seed(admin)
    async with AsyncSession(admin) as session, session.begin():
        await _gate(session)
        await session.execute(
            text("""INSERT INTO provider_sync.source_records
            (source_record_key,source_entity_key,raw_data,raw_payload_hash,fetched_at)
            SELECT 'sr_'||substr(md5(:identity||n::text),1,20),:entity,jsonb_build_object('n',n),
                substr(encode(sha256(convert_to('{"n":'||n::text||'}','UTF8')),'hex'),1,32),now()
            FROM generate_series(1,5000) AS g(n)"""),
            other,
        )
        await session.execute(
            text("""INSERT INTO provider_sync.source_records
            (source_record_key,source_entity_key,raw_data,raw_payload_hash,fetched_at)
            VALUES(:long_key,:entity,'{}'::jsonb,:hash,now())"""),
            {**other, "long_key": "x" * 16000, "hash": make_payload_hash({})},
        )
        compressed = (
            await session.execute(
                text("""SELECT
            pg_column_compression(source_record_key) IS NOT NULL,
            octet_length(source_record_key),pg_column_size(source_record_key)
            FROM provider_sync.source_records WHERE source_record_key=:long_key"""),
                {"long_key": "x" * 16000},
            )
        ).one()
        assert compressed[0] is True
        assert compressed[1] == 16000
        assert compressed[2] < 1000
        plan = await session.scalar(
            text("""EXPLAIN (FORMAT JSON,COSTS OFF)
            SELECT pg_column_size(t.raw_data)
            FROM ONLY provider_sync.source_records t
            WHERE (CASE WHEN pg_catalog.octet_length(t.source_record_key::text)<=256
                THEN t.source_record_key::text ELSE NULL::text END)=:record"""),
            seed,
        )
        assert "ix_source_records_bounded_evidence_key" in json.dumps(plan)
        assert "Index Cond" in json.dumps(plan)
        actual = await _capture(session, seed["dataset"])
        assert actual["capture_complete"] is True
        assert actual["source_entity_count"] == actual["input_member_count"] == 1
        await session.rollback()
