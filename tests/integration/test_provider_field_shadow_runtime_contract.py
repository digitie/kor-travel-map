"""410의 실제 runtime 권한과 사전검사 실패 시 자원 회수를 검증한다."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from kortravelmap.infra.db import RuntimeDbPrivilegeBoundaryError
from tests.integration import test_tvn34_runtime_privilege_preflight as runtime_fixture

pytestmark = pytest.mark.integration


async def test_shadow_recorder_is_allowed_but_policy_and_direct_dml_are_denied(
    migrated_engine: AsyncEngine,
) -> None:
    await runtime_fixture._provision_runtime_logins(migrated_engine)
    for login in runtime_fixture._RUNTIME_LOGINS:
        # 이 helper는 실제 LOGIN의 전체 exact-signature preflight도 실행한다.
        runtime_engine = await runtime_fixture._engine_for_runtime(migrated_engine, login=login)
        try:
            async with runtime_engine.connect() as connection:
                privileges = (
                    await connection.execute(
                        text(
                            """
                            SELECT
                                has_function_privilege(
                                    session_user,
                                    'feature.record_provider_field_candidates('
                                    'uuid,bigint,text,text,bigint,text,boolean,jsonb,jsonb)'
                                    ::regprocedure, 'EXECUTE'
                                ) AS recorder,
                                has_function_privilege(
                                    session_user,
                                    'feature.register_provider_field_shadow_policy('
                                    'bigint,bigint,text,jsonb)'::regprocedure, 'EXECUTE'
                                ) AS policy,
                                EXISTS (
                                    SELECT 1
                                    FROM unnest(ARRAY[
                                        'feature.provider_field_shadow_policies',
                                        'feature.provider_field_shadow_candidates'
                                    ]) AS target(relation_name)
                                    CROSS JOIN unnest(ARRAY[
                                        'INSERT','UPDATE','DELETE','TRUNCATE'
                                    ]) AS operation(privilege_name)
                                    WHERE has_table_privilege(
                                        session_user, relation_name, privilege_name
                                    )
                                ) AS direct_dml
                            """
                        )
                    )
                ).mappings().one()
                assert dict(privileges) == {
                    "recorder": True, "policy": False, "direct_dml": False
                }
        finally:
            await runtime_engine.dispose()


async def test_runtime_engine_is_disposed_when_preflight_fails(
    migrated_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = AsyncMock(spec=AsyncEngine)
    preflight = AsyncMock(side_effect=RuntimeDbPrivilegeBoundaryError("fixture denial"))
    monkeypatch.setattr(runtime_fixture, "make_async_engine", lambda *args, **kwargs: engine)
    monkeypatch.setattr(runtime_fixture, "assert_runtime_db_privilege_boundary", preflight)
    with pytest.raises(RuntimeDbPrivilegeBoundaryError, match="fixture denial"):
        await runtime_fixture._engine_for_runtime(migrated_engine, login="ktm_feature_service")
    engine.dispose.assert_awaited_once()
    preflight.assert_awaited_once_with(engine, expected_login="ktm_feature_service")
