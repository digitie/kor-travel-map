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
