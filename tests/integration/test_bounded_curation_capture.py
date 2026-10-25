"""제한 capture만 검증한다. synthetic 고유 PG이며 collector/RC 활성화 증거가 아니다."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

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
async def test_exact_old_four_aggregates_for_supported_place_shapes(scalar_engines, phones):
    admin, _ = scalar_engines
    seed = await _seed(admin)
    await _set_place(admin, seed, payload={"한글": '제주\n"\\', "nullable": None}, phones=phones)
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


@pytest.mark.parametrize("case", ["string", "key", "phone", "phone-count", "business-json-null"])
async def test_known_shape_limits_are_enforced_before_final_capture(scalar_engines, case):
    admin, _ = scalar_engines
    seed = await _seed(admin)
    await _set_place(
        admin,
        seed,
        payload={"v": "x" * 257} if case == "string" else {"k" * 257: "v"} if case == "key" else {},
        phones=["x" * 257] if case == "phone" else ["x"] * 33 if case == "phone-count" else [],
        business_hours=case == "business-json-null",
    )
    async with AsyncSession(admin) as session, session.begin():
        _rejected(await _capture(session, seed["dataset"]), "shape_unsupported")


async def test_tiny_huge_exponent_is_rejected_without_calling_old_serializer(scalar_engines):
    admin, _ = scalar_engines
    seed = await _seed(admin)
    async with AsyncSession(admin) as session, session.begin():
        await _gate(session)
        await session.execute(
            text("""UPDATE feature.feature_places SET payload='{"v":1e100000}'::jsonb
            WHERE feature_id=CAST(:feature AS uuid)"""),
            seed,
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
        with pytest.raises(DBAPIError) as error:
            await _capture(session, seed["dataset"])
        assert error.value.orig.sqlstate == "P0001"
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


@pytest.mark.parametrize("mode", ["binary", "encoded"])
async def test_whole_payload_budgets_reject_before_aggregate(scalar_engines, mode):
    import random

    admin, _ = scalar_engines
    seeds = [await _seed(admin) for _ in range(24 if mode == "binary" else 18)]
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
                text("""UPDATE provider_sync.source_entities
                SET provider_dataset_id=:target WHERE source_entity_key=:entity"""),
                {**seed, "target": seeds[0]["dataset"]},
            )
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
