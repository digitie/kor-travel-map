"""T-VN-34A runtime LOGIN principal의 actual-catalog privilege proof."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from kortravelmap.infra import feature_repo
from kortravelmap.infra.db import (
    RuntimeDbPrivilegeBoundaryError,
    assert_runtime_db_privilege_boundary,
    make_async_engine,
)
from kortravelmap.providers.standard_data import cultural_festivals_to_bundles

pytestmark = pytest.mark.integration

# Shared migrations recreate the disposable runtime LOGIN roles with this
# T-VN-40 password.  Keep the preflight fixture aligned so a preceding
# privilege test cannot invalidate later command-login connections.
_PASSWORD = "tvn40-test-only-runtime-password"
_RUNTIME_LOGINS = (
    "ktm_feature_api_runtime",
    "ktm_feature_dagster_runtime",
)


async def _require_tvn34_provenance_bridge(engine: AsyncEngine) -> None:
    """T-VN-36D 이후에는 T-VN-34의 materializer DML contract를 실행하지 않는다."""

    async with engine.connect() as connection:
        if await connection.scalar(
            text("SELECT to_regclass('feature.feature_versions') IS NULL")
        ):
            pytest.skip(
                "T-VN-36D final fence 이후에는 T-VN-34 provenance materializer가 없다; "
                "T-VN-36 runtime gate가 final procedure-only DML을 검증한다."
            )


async def _runtime_provider_bundle(suffix: str):
    """실 provider 변환 결과를 runtime ``load_bundle`` 검증에 사용한다."""

    item = SimpleNamespace(
        fstvl_nm="runtime bundle 축제",
        opar="runtime fixture venue",
        fstvl_start_date=date(2026, 8, 1),
        fstvl_end_date=date(2026, 8, 2),
        fstvl_co="runtime LOGIN provider load bundle proof",
        mnnst_nm="runtime fixture organizer",
        auspc_instt_nm=None,
        suprt_instt_nm=None,
        phone_number="02-0000-0000",
        homepage_url=None,
        relate_info=None,
        rdnmadr=f"서울특별시 runtime구 runtime로 {suffix}",
        lnmadr="서울특별시 runtime동",
        latitude=37.5,
        longitude=127.0,
        reference_date=date(2026, 8, 1),
        instt_code=None,
        instt_nm="runtime fixture authority",
    )
    return (
        await cultural_festivals_to_bundles(
            [item],  # type: ignore[list-item]
            fetched_at=datetime(2026, 8, 9, tzinfo=UTC),
        )
    )[0]


async def _provision_runtime_logins(engine: AsyncEngine) -> None:
    """bootstrap가 만드는 LOGIN identity를 disposable test DB에서 재현한다."""

    async with engine.begin() as connection:
        for login in _RUNTIME_LOGINS:
            await connection.execute(
                text(
                    "DO $runtime_login$ "
                    "BEGIN "
                    "IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles "
                    f"WHERE rolname = '{login}') THEN "
                    f"CREATE ROLE {login} LOGIN NOINHERIT NOSUPERUSER "
                    f"NOCREATEDB NOCREATEROLE NOBYPASSRLS NOREPLICATION "
                    f"PASSWORD '{_PASSWORD}'; "
                    "END IF; "
                    "END "
                    "$runtime_login$"
                )
            )
            await connection.execute(
                text(
                    f"ALTER ROLE {login} LOGIN NOINHERIT NOSUPERUSER "
                    f"NOCREATEDB NOCREATEROLE NOBYPASSRLS NOREPLICATION "
                    f"PASSWORD '{_PASSWORD}'"
                )
            )
            await connection.execute(
                text(
                    f"GRANT ktm_feature_runtime TO {login} "
                    "WITH ADMIN FALSE, INHERIT TRUE, SET FALSE"
                )
            )


def _runtime_dsn(engine: AsyncEngine, *, login: str) -> str:
    url = engine.url.set(username=login, password=_PASSWORD)
    return url.render_as_string(hide_password=False)


async def _engine_for_runtime(engine: AsyncEngine, *, login: str) -> AsyncEngine:
    runtime_engine = make_async_engine(_runtime_dsn(engine, login=login), pool_size=1)
    await assert_runtime_db_privilege_boundary(runtime_engine, expected_login=login)
    return runtime_engine


async def test_tvn34_api_and_dagster_runtime_logins_pass_actual_catalog_preflight(
    migrated_engine: AsyncEngine,
) -> None:
    """두 runtime LOGIN은 session_user=current_user와 procedure-only 권한을 만족한다."""

    await _provision_runtime_logins(migrated_engine)
    engines: list[AsyncEngine] = []
    try:
        for login in _RUNTIME_LOGINS:
            runtime_engine = await _engine_for_runtime(migrated_engine, login=login)
            engines.append(runtime_engine)
            async with runtime_engine.connect() as connection:
                identity = (
                    await connection.execute(text("SELECT session_user::text, current_user::text"))
                ).one()
                assert identity == (login, login)
                # membership is inherited for normal grants, never a role that
                # the runtime connection can assume.  This is the practical
                # session_user=current_user proof, rather than a config claim.
                assert (
                    await connection.execute(
                        text(
                            "SELECT "
                            "pg_has_role(session_user, 'ktm_feature_runtime', 'SET'), "
                            "pg_has_role(session_user, 'ktm_feature_schema_owner', 'SET')"
                        )
                    )
                ).one() == (False, False)
                assert (
                    await connection.scalar(
                        text(
                            "SELECT has_function_privilege("
                            "session_user, "
                            "'feature.create_feature_with_initial_state("
                            "jsonb,text,text,text,jsonb)'::regprocedure, "
                            "'EXECUTE')"
                        )
                    )
                ) is (login == "ktm_feature_dagster_runtime")
                assert (
                    await connection.scalar(
                        text(
                            "SELECT has_function_privilege("
                            "session_user, "
                            "'feature.create_admin_manual_feature_with_initial_state("
                            "jsonb,bigint)'::regprocedure, "
                            "'EXECUTE')"
                        )
                    )
                ) is (login == "ktm_feature_api_runtime")
                assert (
                    await connection.scalar(
                        text(
                            "SELECT has_function_privilege("
                            "session_user, "
                            "'feature.apply_provider_feature_field_patch("
                            "text,bigint,text,text,bigint,jsonb,jsonb)'::regprocedure, "
                            "'EXECUTE')"
                        )
                    )
                ) is True
                assert (
                    await connection.scalar(
                        text(
                            "SELECT has_function_privilege("
                            "session_user, "
                            "'feature.author_feature_field_overrides("
                            "text,bigint,text,text,bigint,jsonb,jsonb)'::regprocedure, "
                            "'EXECUTE')"
                        )
                    )
                ) is True
                assert (
                    await connection.scalar(
                        text(
                            "SELECT has_function_privilege("
                            "session_user, "
                            "'feature.revoke_feature_field_overrides("
                            "text,bigint,text,text,bigint,text[])'::regprocedure, "
                            "'EXECUTE')"
                        )
                    )
                ) is True
                assert await connection.scalar(
                    text("SELECT count(*) FROM feature.public_features")
                ) is not None
                assert await connection.scalar(
                    text("SELECT to_regclass('feature.features_detailed') IS NULL")
                ) is True
                assert (
                    await connection.scalar(
                        text(
                            "SELECT has_function_privilege("
                            "session_user, "
                            "'feature.transition_admin_feature_state("
                            "text,text,text,text,bigint,text,text,text)'::regprocedure, "
                            "'EXECUTE')"
                        )
                    )
                ) is True
                assert (
                    await connection.scalar(
                        text(
                            "SELECT has_function_privilege("
                            "session_user, "
                            "'feature.author_lifecycle_override("
                            "text,text,text,boolean,text,text,bigint)'::regprocedure, "
                            "'EXECUTE')"
                        )
                    )
                ) is True
                assert (
                    await connection.scalar(
                        text(
                            "SELECT has_function_privilege("
                            "session_user, "
                            "'feature.revoke_lifecycle_override("
                            "text,text,bigint)'::regprocedure, "
                            "'EXECUTE')"
                        )
                    )
                ) is True
                assert (
                    await connection.scalar(
                        text(
                            "SELECT has_function_privilege("
                            "session_user, "
                            "'feature.reactivate_admin_feature_state("
                            "text,bigint,text,text,bigint,text,text)'::regprocedure, "
                            "'EXECUTE')"
                        )
                    )
                ) is True
                assert (
                    await connection.scalar(
                        text(
                            "SELECT has_function_privilege("
                            "session_user, "
                            "'feature.write_feature_state_transition()'::regprocedure, "
                            "'EXECUTE')"
                        )
                    )
                ) is False
                assert (
                    await connection.scalar(
                        text(
                            "SELECT has_table_privilege("
                            "session_user, 'feature.feature_state_transitions', 'INSERT')"
                        )
                    )
                ) is False
                assert (
                    await connection.scalar(
                        text(
                            "SELECT has_function_privilege("
                            "session_user, "
                            "'feature.transition_feature_state("
                            "text,text,text,text,bigint,jsonb)'::regprocedure, "
                            "'EXECUTE')"
                        )
                    )
                ) is True
    finally:
        for runtime_engine in engines:
            await runtime_engine.dispose()


async def test_tvn34_runtime_preflight_rejects_single_audit_or_read_view_leak(
    migrated_engine: AsyncEngine,
) -> None:
    """audit·필수 read view ACL 하나라도 빠지면 fail-closed다."""

    await _provision_runtime_logins(migrated_engine)
    api_engine = await _engine_for_runtime(
        migrated_engine,
        login="ktm_feature_api_runtime",
    )
    dagster_engine = await _engine_for_runtime(
        migrated_engine,
        login="ktm_feature_dagster_runtime",
    )
    try:
        async with migrated_engine.begin() as connection:
            await connection.execute(
                text("GRANT INSERT ON feature.feature_state_transitions TO ktm_feature_api_runtime")
            )
        with pytest.raises(RuntimeDbPrivilegeBoundaryError, match="transition"):
            await assert_runtime_db_privilege_boundary(
                api_engine,
                expected_login="ktm_feature_api_runtime",
            )

        async with migrated_engine.begin() as connection:
            await connection.execute(
                text(
                    "GRANT EXECUTE ON FUNCTION feature.write_feature_state_transition() "
                    "TO ktm_feature_dagster_runtime"
                )
            )
        with pytest.raises(RuntimeDbPrivilegeBoundaryError, match="audit writer"):
            await assert_runtime_db_privilege_boundary(
                dagster_engine,
                expected_login="ktm_feature_dagster_runtime",
            )

        async with migrated_engine.begin() as connection:
            await connection.execute(
                text("REVOKE SELECT ON feature.public_features FROM ktm_feature_runtime")
            )
        with pytest.raises(RuntimeDbPrivilegeBoundaryError, match="public_features"):
            await assert_runtime_db_privilege_boundary(
                api_engine,
                expected_login="ktm_feature_api_runtime",
            )
    finally:
        async with migrated_engine.begin() as connection:
            await connection.execute(
                text(
                    "REVOKE INSERT ON feature.feature_state_transitions "
                    "FROM ktm_feature_api_runtime"
                )
            )
            await connection.execute(
                text(
                    "REVOKE EXECUTE ON FUNCTION feature.write_feature_state_transition() "
                    "FROM ktm_feature_dagster_runtime"
                )
            )
            await connection.execute(
                text("GRANT SELECT ON feature.public_features TO ktm_feature_runtime")
            )
        await api_engine.dispose()
        await dagster_engine.dispose()


async def test_tvn40_runtime_preflight_rejects_cross_executor_and_missing_grants(
    migrated_engine: AsyncEngine,
) -> None:
    """T-VN-40 application routine 집합은 API/Dagster별 exact equality다."""

    await _provision_runtime_logins(migrated_engine)
    api_engine = await _engine_for_runtime(
        migrated_engine,
        login="ktm_feature_api_runtime",
    )
    dagster_engine = await _engine_for_runtime(
        migrated_engine,
        login="ktm_feature_dagster_runtime",
    )
    try:
        async with migrated_engine.begin() as connection:
            await connection.execute(
                text(
                    "GRANT EXECUTE ON PROCEDURE "
                    "feature.finalize_provider_curation_root(uuid) "
                    "TO ktm_feature_api_runtime"
                )
            )
            await connection.execute(
                text(
                    "GRANT EXECUTE ON PROCEDURE "
                    "feature.reject_theme_feature_candidate("
                    "uuid,bigint,bigint,text,text) "
                    "TO ktm_feature_dagster_runtime"
                )
            )
            await connection.execute(
                text(
                    "CREATE PROCEDURE ops.review_rogue_procedure() "
                    "LANGUAGE SQL SECURITY DEFINER AS 'SELECT 1'"
                )
            )
            await connection.execute(
                text(
                    "CREATE FUNCTION ops.review_rogue_function() RETURNS integer "
                    "LANGUAGE SQL SECURITY DEFINER AS 'SELECT 1'"
                )
            )
            await connection.execute(
                text(
                    "REVOKE ALL ON PROCEDURE ops.review_rogue_procedure() FROM PUBLIC"
                )
            )
            await connection.execute(
                text(
                    "GRANT EXECUTE ON PROCEDURE ops.review_rogue_procedure() "
                    "TO ktm_feature_dagster_runtime"
                )
            )
            await connection.execute(
                text(
                    "REVOKE ALL ON FUNCTION ops.review_rogue_function() FROM PUBLIC"
                )
            )
            await connection.execute(
                text(
                    "GRANT EXECUTE ON FUNCTION ops.review_rogue_function() "
                    "TO ktm_feature_api_runtime"
                )
            )

        with pytest.raises(RuntimeDbPrivilegeBoundaryError, match="unexpected"):
            await assert_runtime_db_privilege_boundary(
                api_engine,
                expected_login="ktm_feature_api_runtime",
            )
        with pytest.raises(RuntimeDbPrivilegeBoundaryError, match="unexpected"):
            await assert_runtime_db_privilege_boundary(
                dagster_engine,
                expected_login="ktm_feature_dagster_runtime",
            )

        async with migrated_engine.begin() as connection:
            await connection.execute(
                text(
                    "REVOKE EXECUTE ON PROCEDURE "
                    "feature.finalize_provider_curation_root(uuid) "
                    "FROM ktm_feature_api_runtime"
                )
            )
            await connection.execute(
                text(
                    "REVOKE EXECUTE ON PROCEDURE "
                    "feature.reject_theme_feature_candidate("
                    "uuid,bigint,bigint,text,text) "
                    "FROM ktm_feature_dagster_runtime"
                )
            )
            await connection.execute(
                text("DROP PROCEDURE ops.review_rogue_procedure()")
            )
            await connection.execute(
                text("DROP FUNCTION ops.review_rogue_function()")
            )
            await connection.execute(
                text(
                    "REVOKE EXECUTE ON PROCEDURE "
                    "ops.ensure_provider_feature_operation_command("
                    "text,text,text,jsonb,timestamptz,timestamptz,text) "
                    "FROM ktm_curation_provider_executor"
                )
            )
            await connection.execute(
                text(
                    "REVOKE EXECUTE ON FUNCTION "
                    "ops.fill_provider_cancellation_starts_command("
                    "uuid,text,timestamptz) FROM ktm_feature_api_runtime"
                )
            )

        with pytest.raises(RuntimeDbPrivilegeBoundaryError, match="missing expected"):
            await assert_runtime_db_privilege_boundary(
                api_engine,
                expected_login="ktm_feature_api_runtime",
            )
        with pytest.raises(RuntimeDbPrivilegeBoundaryError, match="missing expected"):
            await assert_runtime_db_privilege_boundary(
                dagster_engine,
                expected_login="ktm_feature_dagster_runtime",
            )
    finally:
        async with migrated_engine.begin() as connection:
            await connection.execute(
                text("DROP PROCEDURE IF EXISTS ops.review_rogue_procedure()")
            )
            await connection.execute(
                text("DROP FUNCTION IF EXISTS ops.review_rogue_function()")
            )
            await connection.execute(
                text(
                    "REVOKE EXECUTE ON PROCEDURE "
                    "feature.finalize_provider_curation_root(uuid) "
                    "FROM ktm_feature_api_runtime"
                )
            )
            await connection.execute(
                text(
                    "REVOKE EXECUTE ON PROCEDURE "
                    "feature.reject_theme_feature_candidate("
                    "uuid,bigint,bigint,text,text) "
                    "FROM ktm_feature_dagster_runtime"
                )
            )
            await connection.execute(
                text(
                    "GRANT EXECUTE ON PROCEDURE "
                    "ops.ensure_provider_feature_operation_command("
                    "text,text,text,jsonb,timestamptz,timestamptz,text) "
                    "TO ktm_curation_provider_executor"
                )
            )
            await connection.execute(
                text(
                    "GRANT EXECUTE ON FUNCTION "
                    "ops.fill_provider_cancellation_starts_command("
                    "uuid,text,timestamptz) TO ktm_feature_api_runtime"
                )
            )
        await api_engine.dispose()
        await dagster_engine.dispose()


async def test_tvn34_runtime_logins_run_provider_and_admin_dml_but_raw_state_writes_fail(
    migrated_engine: AsyncEngine,
) -> None:
    """실 LOGIN으로 source lineage/admin provenance 성공과 raw state 차단을 함께 증명한다."""

    await _require_tvn34_provenance_bridge(migrated_engine)
    await _provision_runtime_logins(migrated_engine)
    runtime_engines: list[AsyncEngine] = []
    try:
        for login in _RUNTIME_LOGINS:
            runtime_engine = await _engine_for_runtime(migrated_engine, login=login)
            runtime_engines.append(runtime_engine)
            suffix = uuid4().hex
            provider_bundle = await _runtime_provider_bundle(suffix)
            async with (
                AsyncSession(runtime_engine, expire_on_commit=False) as session,
                session.begin(),
            ):
                provider_result = await feature_repo.load_bundle(session, provider_bundle)
            assert provider_result.features_inserted == 1
            assert provider_result.source_records_inserted == 1
            assert provider_result.source_links_inserted == 1

            feature_id = f"tvn34-runtime-{suffix}"
            entity_key = f"source-entity-{suffix}"
            record_key = f"source-record-{suffix}"
            async with runtime_engine.begin() as connection:
                dataset_id = int(
                    (
                        await connection.execute(
                            text(
                                """
                                INSERT INTO provider_sync.provider_datasets (
                                    provider, dataset_key, display_name, source_kind
                                ) VALUES (
                                    :provider, :dataset_key, :display_name, 'internal'
                                )
                                RETURNING provider_dataset_id
                                """
                            ),
                            {
                                "provider": f"runtime-{login}",
                                "dataset_key": f"dml-{suffix}",
                                "display_name": "runtime DML boundary fixture",
                            },
                        )
                    ).scalar_one()
                )
                await connection.execute(
                    text(
                        """
                        INSERT INTO provider_sync.source_entities (
                            source_entity_key, provider_dataset_id,
                            source_entity_type, source_entity_id, first_seen_at, last_seen_at
                        ) VALUES (
                            :entity_key, :dataset_id, 'runtime_fixture', :entity_id,
                            clock_timestamp(), clock_timestamp()
                        )
                        """
                    ),
                    {
                        "entity_key": entity_key,
                        "dataset_id": dataset_id,
                        "entity_id": suffix,
                    },
                )
                await connection.execute(
                    text(
                        """
                        INSERT INTO provider_sync.source_records (
                            source_record_key, source_entity_key, raw_data, raw_payload_hash,
                            fetched_at, imported_at
                        ) VALUES (
                            :record_key, :entity_key, '{}'::jsonb, :payload_hash,
                            clock_timestamp(), clock_timestamp()
                        )
                        """
                    ),
                    {
                        "record_key": record_key,
                        "entity_key": entity_key,
                        "payload_hash": suffix,
                    },
                )
                await connection.execute(
                    text(
                        """
                        INSERT INTO provider_sync.source_entity_heads (
                            source_entity_key, current_source_record_key, observed_at
                        ) VALUES (:entity_key, :record_key, clock_timestamp())
                        """
                    ),
                    {"entity_key": entity_key, "record_key": record_key},
                )
                await connection.execute(
                    text(
                        """
                        CALL feature.create_feature_with_initial_state(
                            CAST(:payload AS jsonb), 'active', 'draft', 'valid',
                            CAST(:context AS jsonb), NULL, NULL, NULL, NULL
                        )
                        """
                    ),
                    {
                        "payload": json.dumps(
                            {
                                "feature_id": feature_id,
                                "kind": "place",
                                "name": "runtime privilege fixture",
                                "category": "tvn34-runtime",
                                "address": {},
                                "urls": {},
                                "raw_refs": [],
                            }
                        ),
                        "context": json.dumps(
                            {
                                "transition_kind": "initial",
                                "reason_code": "runtime_dml_fixture",
                                "principal": login,
                            }
                        ),
                    },
                )
                await connection.execute(
                    text(
                        """
                        INSERT INTO provider_sync.source_links (
                            feature_id, source_entity_key, source_role, match_method,
                            confidence, created_at
                        ) VALUES (
                            :feature_id, :entity_key, 'primary', 'natural_key', 100,
                            clock_timestamp()
                        )
                        """
                    ),
                    {"feature_id": feature_id, "entity_key": entity_key},
                )
                await connection.execute(
                    text(
                        "CALL feature.materialize_provider_feature_version(:feature_id)"
                    ),
                    {"feature_id": feature_id},
                )
                provider_patch = (
                    await connection.execute(
                        text(
                            """
                            CALL feature.apply_provider_feature_field_patch(
                                :feature_id, :dataset_id, :entity_key, :record_key, 1,
                                CAST(:values AS jsonb), '{}'::jsonb,
                                NULL, NULL, NULL
                            )
                            """
                        ),
                        {
                            "feature_id": feature_id,
                            "dataset_id": dataset_id,
                            "entity_key": entity_key,
                            "record_key": record_key,
                            "values": json.dumps({"core.name": "runtime patched name"}),
                        },
                    )
                ).mappings().one()
                assert dict(provider_patch) == {
                    "o_feature_id": feature_id,
                    "o_row_revision": 2,
                    "o_applied_field_count": 1,
                }
                request_id = str(uuid4())
                await connection.execute(
                    text(
                        """
                        INSERT INTO ops.feature_change_requests (
                            request_id, feature_id, action, state, review_mode,
                            base_row_revision, payload, reason, requested_by
                        ) VALUES (
                            CAST(:request_id AS uuid), :feature_id, 'update', 'applied',
                            'immediate', 2, '{}'::jsonb, 'runtime admin DML', :requested_by
                        )
                        """
                    ),
                    {
                        "request_id": request_id,
                        "feature_id": feature_id,
                        "requested_by": login,
                    },
                )
                await connection.execute(
                    text(
                        """
                        CALL feature.materialize_user_feature_change_provenance(
                            :feature_id, 'update', CAST(:request_id AS uuid),
                            'runtime admin DML', :operator, 2, NULL, NULL
                        )
                        """
                    ),
                    {
                        "feature_id": feature_id,
                        "request_id": request_id,
                        "operator": login,
                    },
                )
                await connection.execute(
                    text(
                        """
                        CALL feature.transition_feature_state(
                            :feature_id, 'retired', 'suppressed', 'valid', 3,
                            jsonb_build_object(
                                'transition_kind', 'admin',
                                'reason_code', 'runtime_lifecycle_override_fixture',
                                'principal', CAST(:principal AS text)
                            ),
                            NULL, NULL
                        )
                        """
                    ),
                    {"feature_id": feature_id, "principal": login},
                )
                version_count = int(
                    (
                        await connection.execute(
                            text(
                                "SELECT count(*) FROM feature.feature_versions "
                                "WHERE feature_id = :feature_id"
                            ),
                            {"feature_id": feature_id},
                        )
                    ).scalar_one()
                )
                assert version_count >= 1
                await connection.execute(
                    text(
                        """
                        CALL feature.author_lifecycle_override(
                            :feature_id, 'active', 'retired', true,
                            'runtime lifecycle override', :principal, 4, NULL
                        )
                        """
                    ),
                    {"feature_id": feature_id, "principal": login},
                )
                await connection.execute(
                    text(
                        """
                        CALL feature.revoke_lifecycle_override(
                            :feature_id, :principal, 4, NULL
                        )
                        """
                    ),
                    {"feature_id": feature_id, "principal": login},
                )

            for forbidden_sql in (
                "UPDATE feature.features SET lifecycle_state = 'retired' "
                "WHERE feature_id = :feature_id",
                "UPDATE feature.features SET data_origin = 'provider' "
                "WHERE feature_id = :feature_id",
                "INSERT INTO feature.feature_versions ("
                "feature_id, version, origin, change_kind, payload"
                ") VALUES (:feature_id, 999, 'user_request', 'update', '{}'::jsonb)",
                "INSERT INTO feature.feature_aliases ("
                "alias, feature_id, feature_uuid, alias_kind"
                ") SELECT 'runtime-alias-' || :feature_id, feature_id, feature_uuid, "
                "'legacy_feature_id' FROM feature.features WHERE feature_id = :feature_id",
                "INSERT INTO feature.feature_state_transitions (feature_id) VALUES (:feature_id)",
                "UPDATE ops.feature_overrides SET status = status WHERE FALSE",
                "DELETE FROM ops.feature_overrides WHERE FALSE",
                "DELETE FROM feature.feature_routes WHERE FALSE",
                "UPDATE feature.feature_routes SET feature_id = feature_id WHERE FALSE",
            ):
                with pytest.raises(DBAPIError) as rejected:
                    async with runtime_engine.begin() as connection:
                        await connection.execute(text(forbidden_sql), {"feature_id": feature_id})
                assert getattr(rejected.value.orig, "sqlstate", None) == "42501"

            # Geometry refinement is a normal subtype writer operation, but
            # the identity and DB-owned cache columns above are not writable.
            async with runtime_engine.begin() as connection:
                await connection.execute(
                    text("UPDATE feature.feature_routes SET geom = geom WHERE FALSE")
                )
    finally:
        for runtime_engine in runtime_engines:
            await runtime_engine.dispose()
