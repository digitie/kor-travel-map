"""정본 fresh430의 startup/private ACL/ORM 검증. 공유 fixture/SQL/권한을 바꾸지 않는다."""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.infra.db import assert_runtime_db_privilege_boundary, normalize_async_dsn
from tests.integration import test_alembic_metadata_consistency as official
from tests.integration.test_provider_field_scalar_projection import (
    scalar_container as scalar_container,
)
from tests.integration.test_provider_field_scalar_projection import scalar_engines as scalar_engines

pytestmark = [pytest.mark.integration, pytest.mark.timeout(40)]
_ROOT = Path(__file__).resolve().parents[2]


async def test_fresh_snapshot_startup_private_acl_and_inventory(scalar_engines):
    admin, runtime = scalar_engines
    await assert_runtime_db_privilege_boundary(runtime, expected_login="ktm_feature_service")
    async with admin.connect() as connection:
        assert (
            await connection.scalar(
                text("SELECT count(*) FROM feature.provider_field_active_policies")
            )
            == 0
        )
        assert (
            await connection.scalar(
                text(
                    "SELECT count(*) FROM pg_trigger WHERE tgname IN ('trg_00_strict_sh_data_prot"
                    "ocol','trg_00_strict_sh_data_target')"
                )
            )
            == 0
        )
        assert tuple(
            (
                await connection.execute(
                    text(
                        (
                            "SELECT max_bytes,max_rows FROM ops.provider_snapshot_quota_l"
                            "imits WHERE quot"
                            "a_key=0"
                        )
                    )
                )
            ).one()
        ) == (16777216, 256)
        for name in (
            "provider_snapshot_artifacts",
            "provider_snapshot_controls",
            "provider_snapshot_quota_limits",
            "provider_snapshot_quota_reservations",
        ):
            params = {"relation": "ops." + name}
            assert not await connection.scalar(
                text(
                    "SELECT has_table_privilege('ktm_feature_service',:relation,'SELECT,INSERT,UP"
                    "DATE,DELETE,TRUNCATE,REFERENCES,TRIGGER') OR has_any_column_privilege('ktm_f"
                    "eature_service',:relation,'SELECT,INSERT,UPDATE,REFERENCES')"
                ),
                params,
            )
        assert not await connection.scalar(
            text(
                "SELECT has_table_privilege('ktm_curation_command_owner','ops.provider_snapsh"
                "ot_artifacts','UPDATE')"
            )
        )
        assert await connection.scalar(
            text(
                "SELECT has_table_privilege('ktm_curation_command_owner','ops.provider_snapsh"
                "ot_artifacts','DELETE')"
            )
        )
        assert not await connection.scalar(
            text(
                "SELECT has_function_privilege('ktm_feature_runtime','feature._assert_strict_"
                "sh_data_guard_inventory(boolean)','EXECUTE')"
            )
        )
    async with AsyncSession(runtime) as session:
        assert (
            await session.scalar(
                text("SELECT feature._assert_strict_sh_data_guard_inventory(false)")
            )
            is True
        )
        with pytest.raises(DBAPIError) as caught:
            await session.scalar(text("SELECT feature._assert_strict_sh_data_guard_inventory()"))
        assert caught.value.orig.sqlstate == "23514"
        await session.rollback()
    # 두 mode 모두 읽기 전용이다. 실패 뒤 startup도 같은0 inventory에서 정상이다.
    await assert_runtime_db_privilege_boundary(runtime, expected_login="ktm_feature_service")


@pytest.mark.filterwarnings("ignore:Cannot correctly sort tables:sqlalchemy.exc.SAWarning")
@pytest.mark.filterwarnings("ignore:Computed default on:UserWarning")
async def test_reused_canonical_fresh_bootstrap_is_metadata_clean(scalar_engines, scalar_container):
    _, runtime = scalar_engines
    config = Config(str(_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", runtime.url.render_as_string(hide_password=False))
    # 같은 container/database는 정본 scalar fixture가300부터430까지 실제 올렸다.
    # 원 metadata 검사 함수/command.check/CHECK 대조를 완화 없이 호출한다.
    await official.test_fresh_300_upgrade_is_metadata_clean(
        (config, normalize_async_dsn(scalar_container.get_connection_url()))
    )
