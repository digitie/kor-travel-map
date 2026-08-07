"""``/ops/datasets`` refresh-policy 실세션 transaction 회귀 (#678).

unit 테스트의 ``_FakeSession``은 SQLAlchemy autobegin("SELECT가 시작한
transaction 위에서 ``session.begin()`` 금지")을 흉내내지 못해, 존재 검증
SELECT를 begin 밖에서 수행하던 결함(모든 잔존 조합 PUT이 500
``InvalidRequestError``)을 잡지 못했다. 본 파일은 프로덕션 ``get_session``과
동일한 **fresh ``AsyncSession``**(transaction 미시작)으로 라우터 핸들러를 직접
호출해, canonical catalog mutation과 orphan mutation 금지가 같은 transaction
경계에서 성립함을 실 DB로 고정한다.

시드 데이터는 fresh 세션에서 보이도록 **commit**하므로, 테스트 전용 provider
이름을 쓰고 finally에서 반드시 정리한다(공유 migrated_engine 오염 방지).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.infra.provider_refresh_policy_repo import (
    get_provider_refresh_policy,
    upsert_provider_refresh_policy,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration


def _policy_app(engine: AsyncEngine) -> Any:
    from kortravelmap.api.app import create_app
    from kortravelmap.api.db import get_session
    from kortravelmap.api.settings import ApiSettings

    app = create_app(
        ApiSettings(
            _env_file=None,
            debug_routes_enabled=False,
            features_routes_enabled=False,
            admin_routes_enabled=False,
            ops_routes_enabled=True,
            api_call_log_enabled=False,
            prometheus_metrics_enabled=False,
            admin_proxy_secret=None,
        )
    )

    async def _session() -> AsyncIterator[AsyncSession]:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    app.dependency_overrides[get_session] = _session
    return app


async def _assert_request_waits_for_row_lock(
    task: asyncio.Task[Any],
    engine: AsyncEngine,
    *,
    holder_pid: int,
    statement_fragment: str,
) -> None:
    deadline = asyncio.get_running_loop().time() + 5.0
    while asyncio.get_running_loop().time() < deadline:
        if task.done():
            try:
                result = task.result()
            except BaseException as exc:  # noqa: BLE001 - 실패 증거에 원 예외 포함
                pytest.fail(
                    "waiter가 row lock 관측 전에 예외로 종료됨: "
                    f"{type(exc).__name__}: {exc}"
                )
            pytest.fail(
                "waiter가 row lock 관측 전에 응답함: "
                f"status={getattr(result, 'status_code', None)}, "
                f"body={getattr(result, 'text', result)!r}"
            )
        async with engine.connect() as connection:
            waiting = (
                await connection.execute(
                    text(
                        """
                        SELECT EXISTS (
                          SELECT 1
                          FROM pg_stat_activity
                          WHERE datname = current_database()
                            AND pid <> pg_backend_pid()
                            AND wait_event_type = 'Lock'
                            AND query LIKE :query_pattern
                            AND :holder_pid = ANY(pg_blocking_pids(pid))
                        )
                        """
                    ),
                    {
                        "holder_pid": holder_pid,
                        "query_pattern": f"%{statement_fragment}%",
                    },
                )
            ).scalar_one()
        if waiting:
            assert not task.done()
            return
        await asyncio.sleep(0.01)
    pytest.fail(
        "독립 ASGI request가 지정 holder의 PostgreSQL row lock에서 "
        f"5초 안에 대기하지 않음(holder_pid={holder_pid})"
    )


def _policy_body(
    *,
    expected_revision: str | None = None,
    targeted_policy: str = "allow_targeted",
    enabled: bool = False,
) -> Any:
    from kortravelmap.api.provider_refresh_schema import (
        ProviderRefreshPolicyUpsertRequest,
    )

    return ProviderRefreshPolicyUpsertRequest(
        expected_revision=expected_revision,
        source_kind="manual",
        targeted_policy=targeted_policy,
        max_concurrent=2,
        enabled=enabled,
        stale_after_minutes=90,
    )


async def _put_refresh_policy(
    engine: AsyncEngine,
    *,
    provider_dataset_id: int,
    expected_revision: str | None = None,
    targeted_policy: str = "allow_targeted",
    enabled: bool = False,
) -> Any:
    """프로덕션 ``get_session``과 동일한 fresh 세션으로 service를 호출한다."""
    from kortravelmap.api.ops_dataset_service import upsert_dataset_refresh_policy

    async with AsyncSession(engine, expire_on_commit=False) as session:
        return await upsert_dataset_refresh_policy(
            session,
            provider_dataset_id=provider_dataset_id,
            body=_policy_body(
                expected_revision=expected_revision,
                targeted_policy=targeted_policy,
                enabled=enabled,
            ),
        )


async def _dataset_id(engine: AsyncEngine, *, provider: str, dataset_key: str) -> int:
    """catalog 정본에서 canonical dataset id를 읽는다.

    T-VN-33 이후 dataset identity는 ``provider_dataset_id`` 하나다 —
    provider/dataset_key는 표시용 projection이라 API 경계에서도 id를 받는다.
    """
    async with AsyncSession(engine) as session:
        return int(
            (
                await session.execute(
                    text(
                        "SELECT provider_dataset_id"
                        " FROM provider_sync.provider_datasets"
                        " WHERE provider = :p AND dataset_key = :d"
                    ),
                    {"p": provider, "d": dataset_key},
                )
            ).scalar_one()
        )


async def _ghost_dataset_id(engine: AsyncEngine) -> int:
    """catalog에 **없는** dataset id — 어떤 seed와도 겹치지 않는다."""
    async with AsyncSession(engine) as session:
        return int(
            (
                await session.execute(
                    text(
                        "SELECT COALESCE(max(provider_dataset_id), 0) + 1000"
                        " FROM provider_sync.provider_datasets"
                    )
                )
            ).scalar_one()
        )


async def _cleanup(engine: AsyncEngine, provider_dataset_id: int) -> None:
    async with AsyncSession(engine) as session, session.begin():
        await session.execute(
            text(
                "DELETE FROM ops.provider_refresh_policies"
                " WHERE provider_dataset_id = :id"
            ),
            {"id": provider_dataset_id},
        )
        await session.execute(
            text(
                "DELETE FROM provider_sync.provider_sync_state"
                " WHERE provider_dataset_id = :id"
            ),
            {"id": provider_dataset_id},
        )


async def test_orphan_policy_and_state_rows_cannot_exist(
    migrated_engine: AsyncEngine,
) -> None:
    """catalog 밖 dataset을 가리키는 policy/state row는 **만들어지지 않는다**.

    예전에는 policy/state가 provider/dataset_key 사본을 들고 있어서 catalog에서
    사라진 조합의 row가 유령으로 남았고, service가 mutation 시점에 그것을 orphan
    409로 막았다. T-VN-33은 그 사본을 없애고 두 테이블 모두 canonical catalog를
    FK로 참조하게 했다 — 유령이 애초에 생기지 않으므로 mutation 시점 방어보다
    강한 보증이다. 이 FK가 빠지면 orphan은 조용히 되살아나고, 그것을 막던 코드는
    이미 없다.
    """
    ghost_id = await _ghost_dataset_id(migrated_engine)
    async with AsyncSession(migrated_engine) as session:
        with pytest.raises(IntegrityError) as policy_violation:
            async with session.begin():
                await session.execute(
                    text(
                        """
                        INSERT INTO ops.provider_refresh_policies (
                            provider_dataset_id, source_kind, targeted_policy,
                            max_concurrent, enabled
                        ) VALUES (:id, 'manual', 'allow_targeted', 1, true)
                        """
                    ),
                    {"id": ghost_id},
                )
    # FK 이전에 active-dataset write guard가 먼저 잡는다 — 둘 다 catalog 정본을
    # 참조하므로 어느 쪽이 먼저 울려도 유령 row는 남지 않는다.
    assert "provider dataset" in str(policy_violation.value)

    async with AsyncSession(migrated_engine) as session:
        with pytest.raises(IntegrityError) as state_violation:
            async with session.begin():
                await session.execute(
                    text(
                        """
                        INSERT INTO provider_sync.provider_sync_state (
                            provider_dataset_id, sync_scope, operation_key, status
                        ) VALUES (:id, 'dataset_wide', 'ghost_operation', 'active')
                        """
                    ),
                    {"id": ghost_id},
                )
    assert "inactive refresh operation" in str(state_violation.value)


async def test_put_unknown_dataset_id_404_creates_no_policy_row(
    migrated_engine: AsyncEngine,
) -> None:
    """catalog에 없는 dataset id는 404 + transaction 롤백(유령 policy row 없음)."""
    from kortravelmap.api.ops_dataset_service import DatasetNotFoundError

    ghost_id = await _ghost_dataset_id(migrated_engine)
    try:
        with pytest.raises(DatasetNotFoundError):
            await _put_refresh_policy(migrated_engine, provider_dataset_id=ghost_id)

        async with AsyncSession(migrated_engine) as verify:
            saved = await get_provider_refresh_policy(
                verify, provider_dataset_id=ghost_id
            )
        assert saved is None
    finally:
        await _cleanup(migrated_engine, ghost_id)


async def test_put_catalog_combo_succeeds_on_fresh_session(
    migrated_engine: AsyncEngine,
) -> None:
    """카탈로그 조합(정상 경로)도 fresh 세션에서 한 transaction으로 성립한다."""
    provider = "python-mois-api"
    dataset_key = "mois_license_features_bulk"
    dataset_id = await _dataset_id(
        migrated_engine, provider=provider, dataset_key=dataset_key
    )
    try:
        saved_response = await _put_refresh_policy(
            migrated_engine, provider_dataset_id=dataset_id
        )

        assert saved_response.provider == provider
        assert saved_response.enabled is False
        async with AsyncSession(migrated_engine) as verify:
            saved = await get_provider_refresh_policy(
                verify, provider_dataset_id=dataset_id
            )
        assert saved is not None
        assert saved.targeted_policy == "allow_targeted"
        assert saved.stale_after_minutes == 90
    finally:
        await _cleanup(migrated_engine, dataset_id)


async def test_same_revision_competition_is_cas_and_preserves_winner(
    migrated_engine: AsyncEngine,
) -> None:
    """같은 revision을 읽은 두 client 중 하나만 갱신하고 loser는 현재 row를 본다."""
    from kortravelmap.infra.provider_refresh_policy_repo import (
        ProviderRefreshPolicyRevisionConflict,
    )

    provider = "python-mois-api"
    dataset_key = "mois_license_features_bulk"
    dataset_id = await _dataset_id(
        migrated_engine, provider=provider, dataset_key=dataset_key
    )
    try:
        created = await _put_refresh_policy(
            migrated_engine,
            provider_dataset_id=dataset_id,
            expected_revision=None,
            targeted_policy="follow_system",
            enabled=True,
        )
        assert created.revision == 1

        async with (
            AsyncSession(migrated_engine) as client_a,
            AsyncSession(migrated_engine) as client_b,
        ):
            observed_a = await get_provider_refresh_policy(
                client_a, provider_dataset_id=dataset_id
            )
            observed_b = await get_provider_refresh_policy(
                client_b, provider_dataset_id=dataset_id
            )
        assert observed_a is not None
        assert observed_b is not None
        assert observed_a.revision == observed_b.revision == 1

        winner = await _put_refresh_policy(
            migrated_engine,
            provider_dataset_id=dataset_id,
            expected_revision="1",
            targeted_policy="disabled",
            enabled=False,
        )
        assert winner.revision == 2

        with pytest.raises(ProviderRefreshPolicyRevisionConflict) as excinfo:
            await _put_refresh_policy(
                migrated_engine,
                provider_dataset_id=dataset_id,
                expected_revision="1",
                targeted_policy="allow_targeted",
                enabled=True,
            )
        assert excinfo.value.current is not None
        assert excinfo.value.current.revision == 2
        assert excinfo.value.current.targeted_policy == "disabled"

        async with AsyncSession(migrated_engine) as verify:
            current = await get_provider_refresh_policy(
                verify, provider_dataset_id=dataset_id
            )
        assert current is not None
        assert current.revision == 2
        assert current.enabled is False
        assert current.targeted_policy == "disabled"
    finally:
        await _cleanup(migrated_engine, dataset_id)


async def test_create_update_kind_mismatch_and_rollback_do_not_advance_revision(
    migrated_engine: AsyncEngine,
) -> None:
    """create/update 종류 불일치와 caller rollback은 값·revision을 보존한다."""
    from kortravelmap.infra.provider_refresh_policy_repo import (
        ProviderRefreshPolicyRevisionConflict,
    )

    provider = "python-mois-api"
    dataset_key = "mois_license_features_bulk"
    dataset_id = await _dataset_id(
        migrated_engine, provider=provider, dataset_key=dataset_key
    )
    try:
        with pytest.raises(ProviderRefreshPolicyRevisionConflict) as missing:
            await _put_refresh_policy(
                migrated_engine,
                provider_dataset_id=dataset_id,
                expected_revision="1",
            )
        assert missing.value.current is None

        created = await _put_refresh_policy(
            migrated_engine,
            provider_dataset_id=dataset_id,
            expected_revision=None,
            targeted_policy="follow_system",
            enabled=True,
        )
        with pytest.raises(ProviderRefreshPolicyRevisionConflict) as existing:
            await _put_refresh_policy(
                migrated_engine,
                provider_dataset_id=dataset_id,
                expected_revision=None,
            )
        assert existing.value.current is not None
        assert existing.value.current.revision == created.revision == 1

        class IntentionalRollback(RuntimeError):
            pass

        async def update_then_rollback() -> None:
            async with AsyncSession(migrated_engine) as session, session.begin():
                changed = await upsert_provider_refresh_policy(
                    session,
                    provider_dataset_id=dataset_id,
                    source_kind="manual",
                    expected_revision=created.revision,
                    targeted_policy="disabled",
                    enabled=False,
                )
                assert changed.revision == 2
                raise IntentionalRollback

        with pytest.raises(IntentionalRollback):
            await update_then_rollback()

        async with AsyncSession(migrated_engine) as verify:
            current = await get_provider_refresh_policy(
                verify, provider_dataset_id=dataset_id
            )
        assert current is not None
        assert current.revision == 1
        assert current.targeted_policy == "follow_system"
        assert current.enabled is True
    finally:
        await _cleanup(migrated_engine, dataset_id)


async def test_real_row_lock_competition_returns_http_conflict_and_rollback_winner(
    migrated_engine: AsyncEngine,
) -> None:
    """실제 독립 transaction/ASGI 요청이 row lock 뒤 CAS 결과를 관측한다."""
    provider = "python-mois-api"
    dataset_key = "mois_license_features_bulk"
    dataset_id = await _dataset_id(
        migrated_engine, provider=provider, dataset_key=dataset_key
    )
    app = _policy_app(migrated_engine)
    pending: set[asyncio.Task[Any]] = set()
    try:
        await _cleanup(migrated_engine, dataset_id)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            # A의 미커밋 INSERT와 같은 create-only null을 보낸 B는 기다린 뒤
            # winner의 source_kind/revision을 typed 409로 받는다.
            async with AsyncSession(
                migrated_engine, expire_on_commit=False
            ) as client_a:
                transaction = await client_a.begin()
                holder_pid = (
                    await client_a.execute(text("SELECT pg_backend_pid()"))
                ).scalar_one()
                created = await upsert_provider_refresh_policy(
                    client_a,
                    provider_dataset_id=dataset_id,
                    source_kind="manual",
                    expected_revision=None,
                )
                assert created.revision == 1
                create_loser = asyncio.create_task(
                    client.put(
                        "/v1/ops/datasets/refresh-policy",
                        params={"provider_dataset_id": dataset_id},
                        json={
                            "expected_revision": None,
                            "source_kind": "openapi",
                        },
                    )
                )
                pending.add(create_loser)
                await _assert_request_waits_for_row_lock(
                    create_loser,
                    migrated_engine,
                    holder_pid=holder_pid,
                    statement_fragment="INSERT INTO ops.provider_refresh_policies",
                )
                await transaction.commit()
            create_conflict = await create_loser
            pending.discard(create_loser)
            assert create_conflict.status_code == 409
            create_problem = create_conflict.json()
            assert create_problem["code"] == (
                "PROVIDER_REFRESH_POLICY_REVISION_CONFLICT"
            )
            assert create_problem["details"]["expected_revision"] is None
            assert create_problem["details"]["current_revision"] == "1"
            assert create_problem["details"]["current_record"]["source_kind"] == (
                "manual"
            )

            # 두 client가 같은 revision 1을 갱신한다. A commit 뒤 B는 현재
            # revision 2를 포함한 typed 409를 받아 winner를 덮지 않는다.
            async with AsyncSession(
                migrated_engine, expire_on_commit=False
            ) as client_a:
                transaction = await client_a.begin()
                holder_pid = (
                    await client_a.execute(text("SELECT pg_backend_pid()"))
                ).scalar_one()
                winner = await upsert_provider_refresh_policy(
                    client_a,
                    provider_dataset_id=dataset_id,
                    source_kind="manual",
                    expected_revision=1,
                    targeted_policy="disabled",
                )
                assert winner.revision == 2
                stale_loser = asyncio.create_task(
                    client.put(
                        "/v1/ops/datasets/refresh-policy",
                        params={"provider_dataset_id": dataset_id},
                        json={
                            "expected_revision": "1",
                            "source_kind": "manual",
                            "targeted_policy": "allow_targeted",
                        },
                    )
                )
                pending.add(stale_loser)
                await _assert_request_waits_for_row_lock(
                    stale_loser,
                    migrated_engine,
                    holder_pid=holder_pid,
                    statement_fragment="UPDATE ops.provider_refresh_policies AS policy",
                )
                await transaction.commit()
            stale_conflict = await stale_loser
            pending.discard(stale_loser)
            assert stale_conflict.status_code == 409
            stale_problem = stale_conflict.json()
            assert stale_problem["code"] == (
                "PROVIDER_REFRESH_POLICY_REVISION_CONFLICT"
            )
            assert stale_problem["details"]["expected_revision"] == "1"
            assert stale_problem["details"]["current_revision"] == "2"
            assert stale_problem["details"]["current_record"][
                "targeted_policy"
            ] == "disabled"

            # A가 revision 2 갱신을 rollback하면 대기하던 B의 같은 CAS가
            # 성공하며 revision 3이 된다.
            async with AsyncSession(
                migrated_engine, expire_on_commit=False
            ) as client_a:
                transaction = await client_a.begin()
                holder_pid = (
                    await client_a.execute(text("SELECT pg_backend_pid()"))
                ).scalar_one()
                rolled_back = await upsert_provider_refresh_policy(
                    client_a,
                    provider_dataset_id=dataset_id,
                    source_kind="manual",
                    expected_revision=2,
                    targeted_policy="follow_system",
                )
                assert rolled_back.revision == 3
                rollback_winner = asyncio.create_task(
                    client.put(
                        "/v1/ops/datasets/refresh-policy",
                        params={"provider_dataset_id": dataset_id},
                        json={
                            "expected_revision": "2",
                            "source_kind": "manual",
                            "targeted_policy": "allow_targeted",
                        },
                    )
                )
                pending.add(rollback_winner)
                await _assert_request_waits_for_row_lock(
                    rollback_winner,
                    migrated_engine,
                    holder_pid=holder_pid,
                    statement_fragment="UPDATE ops.provider_refresh_policies AS policy",
                )
                await transaction.rollback()
            rollback_response = await rollback_winner
            pending.discard(rollback_winner)
            assert rollback_response.status_code == 200
            assert rollback_response.json()["data"]["revision"] == "3"
            assert rollback_response.json()["data"]["targeted_policy"] == (
                "allow_targeted"
            )

            immutable = await client.put(
                "/v1/ops/datasets/refresh-policy",
                params={"provider_dataset_id": dataset_id},
                json={
                    "expected_revision": "3",
                    "source_kind": "openapi",
                    "targeted_policy": "disabled",
                },
            )
            assert immutable.status_code == 409
            assert immutable.json()["code"] == (
                "PROVIDER_REFRESH_POLICY_SOURCE_KIND_IMMUTABLE"
            )
            assert immutable.json()["details"]["current_record"]["source_kind"] == (
                "manual"
            )
    finally:
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        await _cleanup(migrated_engine, dataset_id)


async def test_bigint_revision_round_trip_and_exhaustion_are_typed(
    migrated_engine: AsyncEngine,
) -> None:
    """2^53 초과 decimal string과 BIGINT 끝 경계를 HTTP에서 손실 없이 보존한다."""
    provider = "python-mois-api"
    dataset_key = "mois_license_features_bulk"
    dataset_id = await _dataset_id(
        migrated_engine, provider=provider, dataset_key=dataset_key
    )
    app = _policy_app(migrated_engine)
    try:
        await _cleanup(migrated_engine, dataset_id)
        await _put_refresh_policy(
            migrated_engine,
            provider_dataset_id=dataset_id,
            expected_revision=None,
            enabled=True,
        )
        async with AsyncSession(migrated_engine) as session, session.begin():
            await session.execute(
                text(
                    """
                    UPDATE ops.provider_refresh_policies
                    SET revision = 9007199254740993
                    WHERE provider_dataset_id = :provider_dataset_id
                    """
                ),
                {"provider_dataset_id": dataset_id},
            )

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            stale = await client.put(
                "/v1/ops/datasets/refresh-policy",
                params={"provider_dataset_id": dataset_id},
                json={
                    "expected_revision": "9007199254740992",
                    "source_kind": "manual",
                },
            )
            assert stale.status_code == 409
            assert stale.json()["details"]["expected_revision"] == (
                "9007199254740992"
            )
            assert stale.json()["details"]["current_revision"] == (
                "9007199254740993"
            )

            large_update = await client.put(
                "/v1/ops/datasets/refresh-policy",
                params={"provider_dataset_id": dataset_id},
                json={
                    "expected_revision": "9007199254740993",
                    "source_kind": "manual",
                },
            )
            assert large_update.status_code == 200
            assert large_update.json()["data"]["revision"] == (
                "9007199254740994"
            )

            async with AsyncSession(migrated_engine) as session, session.begin():
                await session.execute(
                    text(
                        """
                        UPDATE ops.provider_refresh_policies
                        SET revision = 9223372036854775806
                        WHERE provider_dataset_id = :provider_dataset_id
                        """
                    ),
                    {"provider_dataset_id": dataset_id},
                )

            to_max = await client.put(
                "/v1/ops/datasets/refresh-policy",
                params={"provider_dataset_id": dataset_id},
                json={
                    "expected_revision": "9223372036854775806",
                    "source_kind": "manual",
                },
            )
            assert to_max.status_code == 200
            assert to_max.json()["data"]["revision"] == "9223372036854775807"

            exhausted = await client.put(
                "/v1/ops/datasets/refresh-policy",
                params={"provider_dataset_id": dataset_id},
                json={
                    "expected_revision": "9223372036854775807",
                    "source_kind": "manual",
                },
            )
            assert exhausted.status_code == 409
            assert exhausted.json()["code"] == (
                "PROVIDER_REFRESH_POLICY_REVISION_EXHAUSTED"
            )
            assert exhausted.json()["details"]["current_revision"] == (
                "9223372036854775807"
            )
    finally:
        await _cleanup(migrated_engine, dataset_id)
