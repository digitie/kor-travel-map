"""435(ADR-117): 단건 writer는 P를 잡지 않는다 — regime·epoch 세계가 사라진 뒤의 반증.

434(#1426 DC-1)는 단건 writer 진입을 정책 epoch에 따라 P를 잡거나 잡지 않는 regime 진입으로 바꿨다.
435가 epoch 표·정책 활성화·regime 진입을 지웠으므로 남는 성질은 epoch=0 세계의 것 하나다.
적재가 P EX를 쥐어도 단건 writer는 P를 기다리지 않고 끝난다(ADR-117 §4-5).

434의 cutover·첫 활성화 drain·epoch>0 P EX·SH caller 승격 거부·barrier 사례는 그 객체가 없으므로
지웠다(#1426 머지 시점 `git show 7d10d559a:tests/integration/test_single_writer_regime_entry.py`).
"""

from __future__ import annotations

import json
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration._owned_pg import _seed
from tests.integration._owned_pg import (
    scalar_container as scalar_container,
)
from tests.integration._owned_pg import scalar_engines as scalar_engines
from tests.integration.test_state_lifecycle_protocol_entry import (
    owned_scalar_resource_bounds as owned_scalar_resource_bounds,
)

pytestmark = [pytest.mark.integration, pytest.mark.timeout(40)]
_TRANSITION = """CALL feature.transition_feature_state(
    :feature,'retired','suppressed','valid',:revision,CAST(:context AS jsonb),NULL,NULL)"""
_OWN_PROTOCOL_MODES = """SELECT mode FROM pg_locks WHERE pid=pg_backend_pid()
AND locktype='advisory' AND classid=1369104691::oid AND objid=115::oid AND objsubid=2
AND granted ORDER BY mode"""


async def _writer_target(admin) -> dict[str, object]:
    feature, _datasets, _entities = await _seed(admin)
    async with admin.connect() as connection:
        revision = await connection.scalar(
            text("SELECT row_revision FROM feature.features WHERE feature_id=:id"),
            {"id": UUID(feature)},
        )
    return dict(
        feature=UUID(feature),
        revision=int(revision),
        context=json.dumps(
            dict(transition_kind="system", reason_code="single-435", principal="admin:single-435")
        ),
    )


async def _lifecycle(admin, feature: UUID) -> str:
    async with admin.connect() as connection:
        return str(
            await connection.scalar(
                text("SELECT lifecycle_state FROM feature.features WHERE feature_id=:id"),
                {"id": feature},
            )
        )


async def test_regime_entry_and_epoch_world_are_gone(scalar_engines):
    admin, _runtime = scalar_engines
    async with admin.connect() as connection:
        row = (
            await connection.execute(
                text("""SELECT
                to_regprocedure('ops.lock_single_feature_writer_protocol()'),
                to_regclass('feature.provider_field_policy_epoch'),
                to_regclass('feature.provider_field_active_policies'),
                to_regprocedure('feature.activate_provider_field_policy(uuid,bigint,text[])')""")
            )
        ).one()
    assert tuple(row) == (None, None, None, None)


async def test_single_writer_finishes_while_a_load_holds_protocol_ex(scalar_engines):
    admin, runtime = scalar_engines
    target = await _writer_target(admin)
    async with AsyncSession(runtime) as holder, holder.begin():
        await holder.execute(text("SELECT ops.lock_scoped_feature_write_protocol(true)"))
        async with AsyncSession(runtime) as session, session.begin():
            # 종전(415)에는 이 짧은 상한에서 55P03이었다(관리 UI 503).
            await session.execute(text("SET LOCAL lock_timeout='300ms'"))
            await session.execute(text(_TRANSITION), target)
            assert (await session.scalars(text(_OWN_PROTOCOL_MODES))).all() == []
    assert await _lifecycle(admin, target["feature"]) == "retired"
