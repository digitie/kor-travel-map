"""기존 내부 catalog SD의 RC는 current backend P EX+L에서만 진입한다."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.test_provider_field_scalar_projection import (
    scalar_container as scalar_container,
)
from tests.integration.test_provider_field_scalar_projection import (
    scalar_engines as scalar_engines,
)
from tests.integration.test_state_lifecycle_protocol_entry import (
    owned_scalar_resource_bounds as owned_scalar_resource_bounds,
)

pytestmark = [pytest.mark.integration, pytest.mark.timeout(35)]
_LINEAGE = 6832465333779826081
_CALLS = {
    "observation": "CALL feature.refresh_curated_source_observation(NULL,NULL,NULL,NULL,NULL,NULL)",
    "generation": "CALL feature.materialize_theme_candidate_generation("
    "NULL,'provider_full_snapshot',NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL)",
}


@pytest.mark.parametrize("kind", tuple(_CALLS))
@pytest.mark.parametrize("mode", ["none", "shared", "protocol_only", "lineage_only", "other_pid"])
async def test_rc_catalog_rejects_missing_exact_current_backend_prefix(scalar_engines, kind, mode):
    admin, _ = scalar_engines
    async with AsyncSession(admin) as holder, holder.begin():
        if mode == "other_pid":
            await holder.execute(text("SELECT ops.lock_provider_feature_tracking_protocol(true)"))
        holder_pid = await holder.scalar(text("SELECT pg_backend_pid()"))
        async with AsyncSession(admin) as session:
            await session.begin()
            try:
                await session.execute(text("SET LOCAL statement_timeout='3s'"))
                await session.execute(text("SET LOCAL lock_timeout='900ms'"))
                assert await session.scalar(
                    text("SELECT current_setting('transaction_isolation')")
                ) == ("read committed")
                if mode == "shared":
                    await session.execute(
                        text("SELECT ops.lock_scoped_feature_write_protocol(false)")
                    )
                elif mode == "protocol_only":
                    await session.execute(
                        text("SELECT ops.lock_scoped_feature_write_protocol(true)")
                    )
                elif mode == "lineage_only":
                    await session.execute(
                        text("SELECT pg_advisory_xact_lock(:key)"), {"key": _LINEAGE}
                    )
                assert await session.scalar(text("SELECT pg_backend_pid()")) != holder_pid
                # runtime에는 이 private SD의 EXECUTE가 없다. 명시 관리 owner probe다.
                await session.execute(text("SET LOCAL ROLE ktm_curation_command_owner"))
                with pytest.raises(DBAPIError) as caught:
                    await session.execute(text(_CALLS[kind]))
                assert caught.value.orig.sqlstate == "25001"
                assert "requires SERIALIZABLE transaction" in str(caught.value.orig)
            finally:
                await session.rollback()


async def test_rc_rule_reconcile_stays_ser_only_even_with_full_finalizer_prefix(scalar_engines):
    admin, _ = scalar_engines
    async with AsyncSession(admin) as session:
        await session.begin()
        try:
            await session.execute(text("SELECT ops.lock_provider_feature_tracking_protocol(true)"))
            await session.execute(text("SET LOCAL ROLE ktm_curation_command_owner"))
            with pytest.raises(DBAPIError) as caught:
                await session.execute(
                    text(
                        _CALLS["generation"].replace("'provider_full_snapshot'", "'rule_reconcile'")
                    )
                )
            assert caught.value.orig.sqlstate == "25001"
            assert "candidate generation requires SERIALIZABLE transaction" in str(
                caught.value.orig
            )
        finally:
            await session.rollback()
