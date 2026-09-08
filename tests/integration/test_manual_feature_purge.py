"""manual Feature hard purge를 **실 DB로** 잰다 (migration 306).

각 테스트는 고칠 상태를 심고 그것이 잡히는지 본다. "정상 purge가 된다"만 재면 fence를
통째로 없애도 초록이다 — 이 세션에서 반복해 겪은 공허한 게이트다.
"""

from __future__ import annotations

from itertools import count
from typing import Final
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from kortravelmap.infra.manual_feature_purge_repo import (
    PURGE_OPERATION,
    ManualFeaturePurgeBlocked,
    ManualFeaturePurgeNotManual,
    ManualFeaturePurgeValidationError,
    purge_manual_feature,
)
from tests.integration.test_tvn_m05_manual_provider_dedup import (
    _open_command,
    _record_candidate,
    _runtime_engine,
    _seed_manual_provider_pair,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.usefixtures("tvn_m01_m05_role_graph"),
]

#: 좌표를 `index * 0.01`도씩 민다. 다른 모듈의 대역(0·10~13·20·30·40·50·60번대,
#: evidence_restore의 100번대)을 피하고, 상한 190 아래에 머문다 —
#: `_seed_manual_provider_pair`가 그 상한을 강제한다.
_PAIR_INDEX: Final = count(140)


async def _seed_manual(engine: AsyncEngine) -> dict[str, object]:
    return await _seed_manual_provider_pair(engine, index=next(_PAIR_INDEX))


async def _manual_uuid(engine: AsyncEngine, feature_id: str) -> str:
    async with engine.connect() as connection:
        return str(
            await connection.scalar(
                text("SELECT feature_uuid FROM feature.features WHERE feature_id = :fid"),
                {"fid": feature_id},
            )
        )


async def _purge_command(engine: AsyncEngine, actor: str) -> int:
    return await _open_command(engine, actor=actor, operation=PURGE_OPERATION)


async def _claim(engine: AsyncEngine, feature_uuid: str) -> dict[str, object]:
    async with engine.connect() as connection:
        return dict(
            (
                await connection.execute(
                    text(
                        "SELECT identity_released, purged_by_command_id, purged_at,"
                        " feature_kind, name_key, lon_e6, lat_e6"
                        " FROM feature.manual_feature_identity_claims"
                        " WHERE feature_id = CAST(:uuid AS uuid)"
                    ),
                    {"uuid": feature_uuid},
                )
            )
            .mappings()
            .one()
        )


async def _record(engine: AsyncEngine, feature_uuid: str) -> dict[str, object]:
    async with engine.connect() as connection:
        return dict(
            (
                await connection.execute(
                    text(
                        "SELECT * FROM feature.manual_feature_purge_records"
                        " WHERE feature_uuid = CAST(:uuid AS uuid)"
                    ),
                    {"uuid": feature_uuid},
                )
            )
            .mappings()
            .one()
        )


async def _feature_exists(engine: AsyncEngine, feature_id: str) -> bool:
    async with engine.connect() as connection:
        return bool(
            await connection.scalar(
                text("SELECT count(*) FROM feature.features WHERE feature_id = :fid"),
                {"fid": feature_id},
            )
        )


async def _reclaim_exact_identity(
    engine: AsyncEngine, claim: dict[str, object], *, actor: str
) -> None:
    """같은 exact identity로 새 claim을 예약한다.

    해제됐으면 성공하고 쥐고 있으면 23505다 — 두 테스트가 **같은 동작**을 반대 기대로
    부른다. 따로 쓰면 한쪽만 고쳐져 두 기대가 조용히 어긋난다.
    """

    async with engine.begin() as connection:
        command_id = await connection.scalar(
            text(
                "INSERT INTO ops.domain_commands (actor, operation, idempotency_key,"
                " request_fingerprint) VALUES (:actor,"
                " 'admin-ui-bff.manual-feature-create.v1',"
                " x_extension.gen_random_uuid(), repeat('f', 64))"
                " RETURNING command_id"
            ),
            {"actor": actor},
        )
        await connection.execute(
            text(
                "INSERT INTO feature.manual_feature_identity_claims ("
                " feature_id, feature_kind, name_key, lon_e6, lat_e6,"
                " claimed_by_command_id, claim_basis, claimed_at"
                ") VALUES (x_extension.gen_random_uuid(), :kind, :name_key,"
                " :lon_e6, :lat_e6, :command_id, 'manual_create', clock_timestamp())"
            ),
            {
                "kind": claim["feature_kind"],
                "name_key": claim["name_key"],
                "lon_e6": claim["lon_e6"],
                "lat_e6": claim["lat_e6"],
                "command_id": command_id,
            },
        )


async def _purge_via_repo(
    engine: AsyncEngine,
    *,
    feature_uuid: str,
    reason_code: str,
    release_identity: bool,
    actor: str,
    command_id: int,
) -> object:
    async with (
        AsyncSession(engine, expire_on_commit=False) as session,
        session.begin(),
    ):
        await session.execute(text("SET TRANSACTION ISOLATION LEVEL READ COMMITTED"))
        return await purge_manual_feature(
            session,
            feature_uuid=feature_uuid,
            reason_code=reason_code,
            release_identity=release_identity,
            actor=actor,
            command_id=command_id,
        )


async def _direct_delete(engine: AsyncEngine, feature_id: str) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text("DELETE FROM feature.features WHERE feature_id = :fid"),
            {"fid": feature_id},
        )


async def _direct_claim_update(engine: AsyncEngine, feature_uuid: str, clause: str) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "UPDATE feature.manual_feature_identity_claims"
                f" SET {clause}"
                " WHERE feature_id = CAST(:uuid AS uuid)"
            ),
            {"uuid": feature_uuid},
        )


async def test_a_mistaken_creation_is_purged_and_its_rows_are_captured(
    migrated_engine: AsyncEngine,
) -> None:
    """지우기 전에 cascade로 사라질 행을 담는다 — 그것이 이 설계의 복구점이다.

    담을 relation을 손으로 적지 않으므로, 자식이 늘어도 목록 갱신을 잊어 데이터를 잃는
    일이 없다. 여기서는 **core + subtype이 최소한 담겼는지**로 그 유도가 살아 있음을 본다.
    """

    pair = await _seed_manual(migrated_engine)
    feature_id = str(pair["manual_feature_id"])
    feature_uuid = await _manual_uuid(migrated_engine, feature_id)
    command_id = await _purge_command(migrated_engine, str(pair["actor"]))

    async with (
        AsyncSession(migrated_engine, expire_on_commit=False) as session,
        session.begin(),
    ):
        await session.execute(text("SET TRANSACTION ISOLATION LEVEL READ COMMITTED"))
        outcome = await purge_manual_feature(
            session,
            feature_uuid=feature_uuid,
            reason_code="mistaken_creation",
            release_identity=True,
            actor=str(pair["actor"]),
            command_id=command_id,
        )

    assert outcome.outcome == "purged"
    assert not await _feature_exists(migrated_engine, feature_id)

    record = await _record(migrated_engine, feature_uuid)
    captured = record["captured_rows"]
    assert isinstance(captured, dict)
    assert "feature.features" in captured
    assert captured["feature.features"][0]["feature_id"] == feature_id
    # subtype 행도 담겨야 한다 — core만 담으면 복구가 반쪽이다.
    assert "feature.feature_places" in captured, sorted(captured)
    assert record["captured_row_count"] == outcome.captured_row_count
    assert record["captured_row_count"] >= 2
    assert record["reason_code"] == "mistaken_creation"
    assert record["identity_released"] is True


async def test_purging_releases_the_identity_so_the_same_place_can_be_remade(
    migrated_engine: AsyncEngine,
) -> None:
    """이 항목의 요지 — 해제가 없으면 exact 예약이 **영구 tombstone**이 된다.

    "잘못돼서 지웠으니 같은 자리에 제대로 다시 만들자"가 막히면, 복구 수단은 감사 없는
    DBA 수술뿐이다. 부분 유니크 인덱스가 그것을 막는다.
    """

    pair = await _seed_manual(migrated_engine)
    feature_uuid = await _manual_uuid(migrated_engine, str(pair["manual_feature_id"]))
    before = await _claim(migrated_engine, feature_uuid)
    command_id = await _purge_command(migrated_engine, str(pair["actor"]))

    async with (
        AsyncSession(migrated_engine, expire_on_commit=False) as session,
        session.begin(),
    ):
        await session.execute(text("SET TRANSACTION ISOLATION LEVEL READ COMMITTED"))
        await purge_manual_feature(
            session,
            feature_uuid=feature_uuid,
            reason_code="mistaken_creation",
            release_identity=True,
            actor=str(pair["actor"]),
            command_id=command_id,
        )

    released = await _claim(migrated_engine, feature_uuid)
    # 증거 필드는 그대로다 — append-only가 깨지지 않았다.
    assert released["name_key"] == before["name_key"]
    assert released["lon_e6"] == before["lon_e6"]
    assert released["identity_released"] is True

    # 같은 exact identity를 다시 예약할 수 있어야 한다.
    await _reclaim_exact_identity(migrated_engine, released, actor=str(pair["actor"]))


async def test_keeping_the_identity_still_blocks_recreation(
    migrated_engine: AsyncEngine,
) -> None:
    """`erasure_required`는 보통 예약을 **쥔다** — 같은 것이 다시 만들어지면 안 된다.

    두 동기가 정반대를 원하므로 해제는 자동이 아니라 명시 파라미터다. 이 축이 없으면
    해제를 항상 하도록 바꿔도 초록이다.
    """

    pair = await _seed_manual(migrated_engine)
    feature_uuid = await _manual_uuid(migrated_engine, str(pair["manual_feature_id"]))
    claim = await _claim(migrated_engine, feature_uuid)
    command_id = await _purge_command(migrated_engine, str(pair["actor"]))

    async with (
        AsyncSession(migrated_engine, expire_on_commit=False) as session,
        session.begin(),
    ):
        await session.execute(text("SET TRANSACTION ISOLATION LEVEL READ COMMITTED"))
        outcome = await purge_manual_feature(
            session,
            feature_uuid=feature_uuid,
            reason_code="erasure_required",
            release_identity=False,
            actor=str(pair["actor"]),
            command_id=command_id,
        )

    assert outcome.captured_row_count == 0
    record = await _record(migrated_engine, feature_uuid)
    # payload 부재는 결손이 아니라 의도다.
    assert record["captured_rows"] is None
    assert record["identity_released"] is False

    with pytest.raises(DBAPIError) as duplicate:
        await _reclaim_exact_identity(migrated_engine, claim, actor=str(pair["actor"]))
    assert getattr(duplicate.value.orig, "sqlstate", None) == "23505"


async def test_a_feature_bound_by_immutable_evidence_is_refused_by_name(
    migrated_engine: AsyncEngine,
) -> None:
    """RESTRICT가 막는 것은 **맞다** — 다만 raw 23503으로 죽으면 이유를 못 말한다.

    가장 현실적인 차단자를 쓴다: 이 manual Feature가 열린 dedup case에 걸려 있는 상태.
    `ops.manual_provider_dedup_cases`가 `ON DELETE RESTRICT`로 참조하므로 purge가 뚫으면
    M05 evidence가 dangling이 된다.

    프로시저의 사전 조회가 없으면 이 축은 raw 오류가 되고, 호출자는 그것을 500으로 본다.
    """

    pair = await _seed_manual(migrated_engine)
    feature_id = str(pair["manual_feature_id"])
    feature_uuid = await _manual_uuid(migrated_engine, feature_id)

    dagster = _runtime_engine(migrated_engine, login="ktm_feature_dagster_runtime")
    try:
        recorded = await _record_candidate(
            dagster,
            manual_feature_id=feature_id,
            provider_feature_id=str(pair["provider_feature_id"]),
        )
    finally:
        await dagster.dispose()
    assert recorded["o_outcome"] == "created"

    command_id = await _purge_command(migrated_engine, str(pair["actor"]))
    with pytest.raises(ManualFeaturePurgeBlocked) as blocked:
        await _purge_via_repo(
            migrated_engine,
            feature_uuid=feature_uuid,
            reason_code="mistaken_creation",
            release_identity=True,
            actor=str(pair["actor"]),
            command_id=command_id,
        )
    # 무엇이 막는지 말해야 한다 — "안 된다"만으로는 운영자가 다음 행동을 못 정한다.
    assert "manual_provider_dedup_cases" in str(blocked.value)
    assert await _feature_exists(migrated_engine, feature_id)


async def test_deleting_without_an_authorised_purge_is_still_refused(
    migrated_engine: AsyncEngine,
) -> None:
    """fence가 열린 것이 아니라 **조건부**가 된 것이다.

    프로시저 밖에서 직접 DELETE하면 여전히 막혀야 한다. 이 축이 없으면 fence를 통째로
    없애도 나머지 테스트가 전부 초록이다.
    """

    pair = await _seed_manual(migrated_engine)
    feature_id = str(pair["manual_feature_id"])

    with pytest.raises(DBAPIError) as refused:
        await _direct_delete(migrated_engine, feature_id)
    assert getattr(refused.value.orig, "sqlstate", None) == "23514"
    assert await _feature_exists(migrated_engine, feature_id)


async def test_the_claim_evidence_fields_stay_immutable(
    migrated_engine: AsyncEngine,
) -> None:
    """완화는 **단조 전이 하나**만이다 — 증거 필드는 여전히 못 고친다.

    append-only 계약을 건드렸으므로 그 경계를 직접 잰다. 완화가 넓어지면 여기서 터진다.
    """

    pair = await _seed_manual(migrated_engine)
    feature_uuid = await _manual_uuid(migrated_engine, str(pair["manual_feature_id"]))

    with pytest.raises(DBAPIError) as mutated:
        await _direct_claim_update(
            migrated_engine, feature_uuid, "name_key = 'tampered'"
        )
    assert getattr(mutated.value.orig, "sqlstate", None) == "42501"

    # 승인 없는 해제도 막힌다 — 해제는 purge의 결과이지 독립 동작이 아니다.
    with pytest.raises(DBAPIError) as released:
        await _direct_claim_update(
            migrated_engine, feature_uuid, "identity_released = true"
        )
    assert getattr(released.value.orig, "sqlstate", None) == "42501"


async def test_the_sanctioned_transition_cannot_smuggle_other_fields(
    migrated_engine: AsyncEngine,
) -> None:
    """완화의 진짜 위험은 **다른 필드가 묻어 오는 것**이다.

    앞의 불변성 테스트는 이 축을 가려 준다 — 순수 tamper UPDATE는 `purged_by_command_id`를
    세우지 않으므로 완화 조건에 애초에 걸리지 않고, 그래서 `name_key` 검사를 빼도 여전히
    거부된다. 여기서는 **유효한 purge 전이와 함께** 증거 필드를 바꿔 본다.
    """

    pair = await _seed_manual(migrated_engine)
    feature_uuid = await _manual_uuid(migrated_engine, str(pair["manual_feature_id"]))
    command_id = await _purge_command(migrated_engine, str(pair["actor"]))

    with pytest.raises(DBAPIError) as smuggled:
        await _direct_claim_update(
            migrated_engine,
            feature_uuid,
            "purged_by_command_id = "
            + str(command_id)
            + ", purged_at = clock_timestamp(), name_key = 'tampered'",
        )
    assert getattr(smuggled.value.orig, "sqlstate", None) == "42501"


async def test_purge_is_idempotent_for_the_same_feature(
    migrated_engine: AsyncEngine,
) -> None:
    """두 번째 호출이 오류가 아니라 기존 영수증을 돌려준다."""

    pair = await _seed_manual(migrated_engine)
    feature_uuid = await _manual_uuid(migrated_engine, str(pair["manual_feature_id"]))

    async with (
        AsyncSession(migrated_engine, expire_on_commit=False) as session,
        session.begin(),
    ):
        await session.execute(text("SET TRANSACTION ISOLATION LEVEL READ COMMITTED"))
        first = await purge_manual_feature(
            session,
            feature_uuid=feature_uuid,
            reason_code="mistaken_creation",
            release_identity=True,
            actor=str(pair["actor"]),
            command_id=await _purge_command(migrated_engine, str(pair["actor"])),
        )

    async with (
        AsyncSession(migrated_engine, expire_on_commit=False) as session,
        session.begin(),
    ):
        await session.execute(text("SET TRANSACTION ISOLATION LEVEL READ COMMITTED"))
        second = await purge_manual_feature(
            session,
            feature_uuid=feature_uuid,
            reason_code="mistaken_creation",
            release_identity=True,
            actor=str(pair["actor"]),
            command_id=await _purge_command(migrated_engine, str(pair["actor"])),
        )

    assert second.already_purged
    assert second.purge_id == first.purge_id
    assert second.captured_row_count == first.captured_row_count


async def test_a_provider_feature_is_not_purgeable_by_this_command(
    migrated_engine: AsyncEngine,
) -> None:
    """이 명령은 manual origin 전용이다 — provider Feature에 쓰면 안 된다."""

    pair = await _seed_manual(migrated_engine)
    provider_uuid = await _manual_uuid(
        migrated_engine, str(pair["provider_feature_id"])
    )
    command_id = await _purge_command(migrated_engine, str(pair["actor"]))

    with pytest.raises(ManualFeaturePurgeNotManual):
        await _purge_via_repo(
            migrated_engine,
            feature_uuid=provider_uuid,
            reason_code="mistaken_creation",
            release_identity=True,
            actor=str(pair["actor"]),
            command_id=command_id,
        )


async def test_a_command_opened_for_another_operation_is_refused(
    migrated_engine: AsyncEngine,
) -> None:
    """command가 이 명령의 것이 아니면 거부한다 — 감사 사슬이 끊기면 안 된다."""

    pair = await _seed_manual(migrated_engine)
    feature_uuid = await _manual_uuid(migrated_engine, str(pair["manual_feature_id"]))
    wrong_command = await _open_command(
        migrated_engine,
        actor=str(pair["actor"]),
        operation="admin.manual-provider-dedup-case.resolve.v1",
    )

    with pytest.raises(ManualFeaturePurgeValidationError):
        await _purge_via_repo(
            migrated_engine,
            feature_uuid=feature_uuid,
            reason_code="mistaken_creation",
            release_identity=True,
            actor=str(pair["actor"]),
            command_id=wrong_command,
        )
    assert await _feature_exists(migrated_engine, str(pair["manual_feature_id"]))


async def test_an_unknown_reason_code_never_reaches_the_database(
    migrated_engine: AsyncEngine,
) -> None:
    """호출부가 먼저 거른다 — DB까지 가서야 거부되면 진단이 한 겹 멀어진다."""

    async with AsyncSession(migrated_engine) as session:
        with pytest.raises(ManualFeaturePurgeValidationError) as refused:
            await purge_manual_feature(
                session,
                feature_uuid=str(uuid4()),
                reason_code="because_i_said_so",
                release_identity=True,
                actor="admin:test",
                command_id=1,
            )
    # **어느 층이 거부했는지**를 본다. DB까지 갔다면 오류가 프로시저의 문장이라
    # 파라미터 이름을 말하지 않는다 — 그러면 호출자가 무엇을 고쳐야 할지 한 겹 멀어진다.
    assert "reason_code" in str(refused.value)


async def test_a_request_approved_feature_is_refused_by_name_not_a_raw_fk_error(
    migrated_engine: AsyncEngine,
) -> None:
    """**적대 리뷰 P1.** `ops.feature_requests.resolved_feature_id`는 NO ACTION이다.

    지연되지 않은 FK에서 NO ACTION은 RESTRICT와 똑같이 삭제를 거부한다. probe가 `'r'`만
    보면 그런 참조자가 통과한 뒤 DELETE에서 raw 23503으로 죽고, "이름을 대는 거부"라는
    이 설계의 요지가 그 경로에서만 조용히 무효가 된다.

    그리고 이것은 드문 경로가 아니다 — `approve_feature_request_with_initial_state`가
    claim을 심고 **같은 트랜잭션에서** `resolved_feature_id`를 세우므로, M04 승인으로
    태어난 manual Feature **전부**에 달린다.
    """

    pair = await _seed_manual(migrated_engine)
    feature_id = str(pair["manual_feature_id"])
    feature_uuid = await _manual_uuid(migrated_engine, feature_id)

    async with migrated_engine.begin() as connection:
        command_id = await connection.scalar(
            text(
                "INSERT INTO ops.domain_commands ("
                " actor, operation, idempotency_key, request_fingerprint"
                ") VALUES ('service:feature-request',"
                " 'service.feature-request.submit.v1',"
                " x_extension.gen_random_uuid(), repeat('9', 64))"
                " RETURNING command_id"
            )
        )
        resolution_command = await connection.scalar(
            text(
                "INSERT INTO ops.domain_commands ("
                " actor, operation, idempotency_key, request_fingerprint"
                ") VALUES ('admin:purge-probe',"
                " 'admin.feature-request.resolve.v1',"
                " x_extension.gen_random_uuid(), repeat('a', 64))"
                " RETURNING command_id"
            )
        )
        await connection.execute(
            text(
                "INSERT INTO ops.feature_requests ("
                " request_id, submitted_by_principal, request_payload, status,"
                " submission_command_id, resolved_at, resolved_by_actor,"
                " resolution_command_id, resolved_feature_id"
                ") VALUES (x_extension.gen_random_uuid(), 'service:feature-request',"
                " jsonb_build_object('kind', 'place', 'name', 'purge probe'),"
                " 'approved', :submit, clock_timestamp(), 'admin:purge-probe',"
                " :resolve, CAST(:feature_uuid AS uuid))"
            ),
            {
                "submit": command_id,
                "resolve": resolution_command,
                "feature_uuid": feature_uuid,
            },
        )

    purge_command = await _purge_command(migrated_engine, str(pair["actor"]))
    with pytest.raises(ManualFeaturePurgeBlocked) as blocked:
        await _purge_via_repo(
            migrated_engine,
            feature_uuid=feature_uuid,
            reason_code="mistaken_creation",
            release_identity=True,
            actor=str(pair["actor"]),
            command_id=purge_command,
        )
    assert "feature_requests" in str(blocked.value)
    assert await _feature_exists(migrated_engine, feature_id)


async def test_set_null_referrers_are_captured_before_they_are_nulled(
    migrated_engine: AsyncEngine,
) -> None:
    """**적대 리뷰 P1의 짝.** cascade는 행을 지우고 SET NULL은 행을 고친다.

    복구점의 관점에서는 둘 다 되돌릴 수 없는 변경이다. 담지 않으면 어느 행의 어느 컬럼이
    NULL이 됐는지 알 수 없다. `ops.data_integrity_violations`가 그런 참조자다.
    """

    pair = await _seed_manual(migrated_engine)
    feature_id = str(pair["manual_feature_id"])
    feature_uuid = await _manual_uuid(migrated_engine, feature_id)

    async with migrated_engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO ops.data_integrity_violations ("
                " feature_id, violation_type, severity, message"
                ") VALUES (:feature_id, 'purge-capture-probe', 'warning',"
                " 'purge capture probe')"
            ),
            {"feature_id": feature_id},
        )

    purge_command = await _purge_command(migrated_engine, str(pair["actor"]))
    await _purge_via_repo(
        migrated_engine,
        feature_uuid=feature_uuid,
        reason_code="mistaken_creation",
        release_identity=True,
        actor=str(pair["actor"]),
        command_id=purge_command,
    )

    record = await _record(migrated_engine, feature_uuid)
    captured = record["captured_rows"]
    assert isinstance(captured, dict)
    assert "ops.data_integrity_violations" in captured, sorted(captured)
    assert captured["ops.data_integrity_violations"][0]["feature_id"] == feature_id


async def test_a_released_identity_is_not_returned_as_the_exact_duplicate(
    migrated_engine: AsyncEngine,
) -> None:
    """**적대 리뷰 P1.** 306이 exact 키를 부분 유니크로 좁히면서 fallback이 남았다.

    306 이전에는 그 키가 전역 유일이라 fallback `SELECT ... INTO`가 한 행만 볼 수 있었다.
    이제는 **살아 있는 claim 중에서만** 유일하므로, purge-with-release 뒤 같은 자리에 다시
    만들면 두 행이 생긴다. `INTO`(STRICT 아님)는 그중 하나를 조용히 고르고, 물리적으로
    앞선 행은 **지워진 Feature의 것**이다.

    그러면 exact_conflict가 존재하지 않는 Feature의 UUID를 돌려준다 — 승인 경로에서는
    FK가 즉시 터지고, admin 경로에서는 UI가 없는 Feature를 가리키는 409를 받는다.
    """

    pair = await _seed_manual(migrated_engine)
    feature_uuid = await _manual_uuid(migrated_engine, str(pair["manual_feature_id"]))
    claim = await _claim(migrated_engine, feature_uuid)

    purge_command = await _purge_command(migrated_engine, str(pair["actor"]))
    await _purge_via_repo(
        migrated_engine,
        feature_uuid=feature_uuid,
        reason_code="mistaken_creation",
        release_identity=True,
        actor=str(pair["actor"]),
        command_id=purge_command,
    )
    # 같은 exact identity를 다시 예약한다 — 이제 두 행이 있다.
    await _reclaim_exact_identity(migrated_engine, claim, actor=str(pair["actor"]))

    # 프로시저의 fallback과 **같은 술어**로 조회한다. 해제된 것을 거르지 않으면 두 행이
    # 나오고, 그중 하나가 지워진 Feature의 UUID다.
    async with migrated_engine.connect() as connection:
        live = (
            await connection.execute(
                text(
                    "SELECT claim.feature_id"
                    " FROM feature.manual_feature_identity_claims AS claim"
                    " WHERE (claim.feature_kind, claim.name_key, claim.lon_e6,"
                    "        claim.lat_e6) = (:kind, :name_key, :lon_e6, :lat_e6)"
                    "   AND NOT claim.identity_released"
                ),
                {
                    "kind": claim["feature_kind"],
                    "name_key": claim["name_key"],
                    "lon_e6": claim["lon_e6"],
                    "lat_e6": claim["lat_e6"],
                },
            )
        ).scalars().all()
    assert len(live) == 1, live
    assert live[0] != feature_uuid

    # 술어가 없으면 둘이라는 것까지 못 박는다 — 이 사실이 곧 결함의 이유다.
    async with migrated_engine.connect() as connection:
        every = (
            await connection.execute(
                text(
                    "SELECT count(*)"
                    " FROM feature.manual_feature_identity_claims AS claim"
                    " WHERE (claim.feature_kind, claim.name_key, claim.lon_e6,"
                    "        claim.lat_e6) = (:kind, :name_key, :lon_e6, :lat_e6)"
                ),
                {
                    "kind": claim["feature_kind"],
                    "name_key": claim["name_key"],
                    "lon_e6": claim["lon_e6"],
                    "lat_e6": claim["lat_e6"],
                },
            )
        ).scalar_one()
    assert every == 2


def test_the_creation_procedures_filter_released_claims_in_their_fallback() -> None:
    """세 프로시저의 fallback이 전부 해제된 claim을 거르는지 **원문으로** 확인한다.

    위 테스트는 술어 자체를 재지만, 그 술어가 **프로시저 안에** 있는지는 재지 못한다.
    셋 중 하나만 빠져도 그 경로에서 결함이 그대로 남는다.
    """

    import pathlib

    versions = pathlib.Path(__file__).resolve().parents[2] / "alembic" / "versions"
    sidecars = sorted(versions.glob("_306_*_upgraded.sql"))
    assert len(sidecars) == 3, [p.name for p in sidecars]
    for sidecar in sidecars:
        body = sidecar.read_text(encoding="utf-8")
        assert "INTO o_existing_feature_uuid" in body, sidecar.name
        assert "AND NOT claim.identity_released" in body, sidecar.name


async def test_the_capture_set_equals_what_the_catalog_says_not_a_fixed_list(
    migrated_engine: AsyncEngine,
) -> None:
    """**적대 리뷰 P1.** 앞의 capture 테스트들은 "이것과 저것이 담겼다"만 잰다.

    그러면 `pg_constraint` 유도를 하드코딩된 이름 목록으로 바꿔도 초록이다 — 이 설계가
    내세운 요지("목록을 손으로 적지 않는다")가 정작 결박돼 있지 않았다.

    그래서 **동등성**을 잰다: 담긴 relation 집합이, 카탈로그가 말하는 "이 Feature를
    참조하고 행이 실제로 있는" 집합과 정확히 같아야 한다. 새 자식이 생기면 이 단언이
    저절로 넓어지고, 유도가 죽으면 저절로 좁아진다.
    """

    pair = await _seed_manual(migrated_engine)
    feature_id = str(pair["manual_feature_id"])
    feature_uuid = await _manual_uuid(migrated_engine, feature_id)

    # 담길 것을 카탈로그로 **독립 계산**한다 — 프로시저와 같은 코드를 부르지 않는다.
    async with migrated_engine.connect() as connection:
        expected = set(
            (
                await connection.execute(
                    text(
                        """
                        SELECT feature.qualified_relation_name(child.conrelid)
                        FROM pg_catalog.pg_constraint AS child
                        WHERE child.confrelid = 'feature.features'::regclass
                          AND child.contype = 'f'
                          AND child.confdeltype IN ('c', 'n')
                          AND feature.count_rows_dynamic(
                                format(
                                    'SELECT count(*) FROM %s AS c WHERE (%s) IN'
                                    ' (SELECT %s FROM feature.features'
                                    '  WHERE feature_uuid = %L)',
                                    feature.qualified_relation_name(child.conrelid),
                                    (SELECT string_agg(format('c.%I', a.attname), ', '
                                                       ORDER BY o.ordinality)
                                     FROM unnest(child.conkey) WITH ORDINALITY
                                          AS o(attnum, ordinality)
                                     JOIN pg_catalog.pg_attribute AS a
                                       ON a.attrelid = child.conrelid
                                      AND a.attnum = o.attnum),
                                    (SELECT string_agg(format('%I', a.attname), ', '
                                                       ORDER BY o.ordinality)
                                     FROM unnest(child.confkey) WITH ORDINALITY
                                          AS o(attnum, ordinality)
                                     JOIN pg_catalog.pg_attribute AS a
                                       ON a.attrelid = child.confrelid
                                      AND a.attnum = o.attnum),
                                    CAST(:feature_uuid AS uuid)
                                )
                              ) > 0
                        """
                    ),
                    {"feature_uuid": feature_uuid},
                )
            )
            .scalars()
            .all()
        )
    # 유도가 비면 이 단언 자체가 공허해진다.
    assert expected, "카탈로그가 자식을 하나도 못 찾았다 — 이 게이트가 죽었다"

    command_id = await _purge_command(migrated_engine, str(pair["actor"]))
    await _purge_via_repo(
        migrated_engine,
        feature_uuid=feature_uuid,
        reason_code="mistaken_creation",
        release_identity=True,
        actor=str(pair["actor"]),
        command_id=command_id,
    )

    captured = (await _record(migrated_engine, feature_uuid))["captured_rows"]
    assert isinstance(captured, dict)
    # core는 자식이 아니라 별도로 담긴다.
    assert set(captured) - {"feature.features"} == expected


async def test_a_purged_identity_can_still_be_released_later(
    migrated_engine: AsyncEngine,
) -> None:
    """**적대 리뷰 P1.** `erasure_required`는 예약을 쥔 채 purge한다.

    그 뒤에 놓아야 할 수 있는데, 완화가 최초 승인 전이 하나만 허용하면 그 claim은
    **영원히** 해제할 수 없다 — 조문이 피하라는 영구 tombstone이 정확히 그 모양으로
    되살아난다. 두 번째 단조 전이를 허용하되 승인 필드는 여전히 못 바꾸게 한다.
    """

    pair = await _seed_manual(migrated_engine)
    feature_uuid = await _manual_uuid(migrated_engine, str(pair["manual_feature_id"]))
    claim = await _claim(migrated_engine, feature_uuid)

    await _purge_via_repo(
        migrated_engine,
        feature_uuid=feature_uuid,
        reason_code="erasure_required",
        release_identity=False,
        actor=str(pair["actor"]),
        command_id=await _purge_command(migrated_engine, str(pair["actor"])),
    )
    assert (await _claim(migrated_engine, feature_uuid))["identity_released"] is False

    # 뒤늦은 해제가 가능해야 한다.
    await _direct_claim_update(migrated_engine, feature_uuid, "identity_released = true")
    assert (await _claim(migrated_engine, feature_uuid))["identity_released"] is True
    await _reclaim_exact_identity(migrated_engine, claim, actor=str(pair["actor"]))

    # 그래도 **되돌리기**는 막힌다 — 단조롭다.
    with pytest.raises(DBAPIError) as reverted:
        await _direct_claim_update(
            migrated_engine, feature_uuid, "identity_released = false"
        )
    assert getattr(reverted.value.orig, "sqlstate", None) == "42501"

    # 승인 필드 재작성도 막힌다.
    with pytest.raises(DBAPIError) as rewritten:
        await _direct_claim_update(
            migrated_engine, feature_uuid, "purged_at = clock_timestamp()"
        )
    assert getattr(rewritten.value.orig, "sqlstate", None) == "42501"


async def test_a_late_release_cannot_smuggle_a_rewritten_approval(
    migrated_engine: AsyncEngine,
) -> None:
    """뒤늦은 해제에 **승인 필드 재작성이 묻어 오면** 안 된다.

    앞 테스트의 "승인 필드 재작성" 축은 이것을 가려 준다 — 순수 재작성은 해제 조건에
    애초에 걸리지 않아 다른 검사가 먼저 막는다. 여기서는 **유효한 해제와 함께** 바꾼다.
    변이 검증이 그 가림을 드러냈다(`late_release_too_wide`가 초록이었다).
    """

    pair = await _seed_manual(migrated_engine)
    feature_uuid = await _manual_uuid(migrated_engine, str(pair["manual_feature_id"]))
    await _purge_via_repo(
        migrated_engine,
        feature_uuid=feature_uuid,
        reason_code="erasure_required",
        release_identity=False,
        actor=str(pair["actor"]),
        command_id=await _purge_command(migrated_engine, str(pair["actor"])),
    )

    with pytest.raises(DBAPIError) as smuggled:
        await _direct_claim_update(
            migrated_engine,
            feature_uuid,
            "identity_released = true, purged_at = clock_timestamp()",
        )
    assert getattr(smuggled.value.orig, "sqlstate", None) == "42501"
