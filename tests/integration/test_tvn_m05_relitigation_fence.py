"""T-VN-M05-RELITIGATION — admin이 판정한 쌍이 다시 올라오지 않는다.

프로시저의 멱등성은 `evidence_fingerprint`가 같고 **미해결**일 때만 성립한다. 그래서
차단이 없으면 판정 직후 재실행이 그 쌍을 새 case로 다시 만들고, 주기 실행이 곧
admin 큐의 쳇바퀴가 된다.

**이 항목은 어느 방향으로도 틀릴 수 있다.** 너무 세게 막으면 증거가 실제로 바뀌었는데도
새 후보가 안 올라오는 영구 침묵이 되고, 너무 약하면 무관한 patch마다 재발행된다.
둘 다 조용히 실패하므로 R1(차단)과 R2(해제)를 **각각** 결박한다.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from kortravelmap.infra.manual_provider_dedup_repo import (
    DetectionOutcome,
    detect_manual_provider_candidates,
)

from .test_tvn_m05_manual_provider_dedup import (
    _open_command,
    _runtime_engine,
    _seed_manual_provider_pair,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.usefixtures("tvn_m01_m05_role_graph"),
]

_HOMEPAGE_PATCH = '{"homepage": "https://example.invalid"}'
_SUPERSEDED_CAUSATION = '{"scope": "fence-test"}'


async def _resolve_case(
    engine: AsyncEngine, *, case_id: str, decision: str = "kept"
) -> None:
    """admin 판정을 직접 심는다.

    `resolve_manual_provider_dedup_case`는 command·subscription 전제가 많아 이
    테스트의 축(재심 차단)과 무관한 설정을 잔뜩 요구한다. 차단이 읽는 것은
    `resolutions.decision`뿐이므로 그 행만 만들되, CHECK
    (`ck_manual_provider_dedup_resolutions_causation`)가 요구하는 모양은 지킨다.
    """

    command_id = await _open_command(
        engine,
        actor=f"admin:m05-fence-{uuid4().hex[:8]}",
        operation="admin.manual-provider-dedup.resolve-v1",
    )
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO ops.manual_provider_dedup_resolutions "
                "(case_id, decision, command_id, actor, reason) "
                "VALUES (CAST(:case_id AS uuid), :decision, :command_id, :actor, :reason)"
            ),
            {
                "case_id": case_id,
                "decision": decision,
                "command_id": command_id,
                "actor": "admin:m05-fence",
                "reason": "integration fence",
            },
        )


async def _detect_once(engine: AsyncEngine, *, run_id: str) -> DetectionOutcome:
    dagster = _runtime_engine(engine, login="ktm_feature_dagster_runtime")
    try:
        async with AsyncSession(dagster) as session:
            return await detect_manual_provider_candidates(session, run_id=run_id)
    finally:
        await dagster.dispose()


async def _case_id_for(
    engine: AsyncEngine, case_ids: tuple[str, ...], manual_feature_id: str
) -> str | None:
    if not case_ids:
        return None
    # T-VN-39 재키 뒤 `ops.manual_provider_dedup_cases.manual_feature_id`는 uuid다
    # — **정본 축**이고 legacy `f_*`가 들어오는 자리가 아니다. 맨 바인드로 두면
    # 드라이버의 타입 추론에 기대게 되므로 자리마다 명시 캐스트를 둔다(형제 파일
    # `test_tvn_m05_detector_manual_listing.py`와 같은 형태).
    async with engine.connect() as connection:
        row = (
            await connection.execute(
                text(
                    "SELECT case_id FROM ops.manual_provider_dedup_cases "
                    "WHERE case_id = ANY(CAST(:case_ids AS uuid[])) "
                    "  AND manual_feature_id = CAST(:manual_feature_id AS uuid)"
                ),
                {"case_ids": list(case_ids), "manual_feature_id": manual_feature_id},
            )
        ).first()
    # `case_id`는 uuid 컬럼이라 드라이버가 `uuid.UUID`를 준다. 호출부가 이 값을
    # `DetectionOutcome.suppressed_case_ids`(text 튜플)와 비교하므로 여기서 고정한다 —
    # 섞이면 `case_id in again.suppressed_case_ids`가 **항상 거짓**이라 공허해진다.
    return None if row is None else str(row.case_id)


async def _row_revision(engine: AsyncEngine, feature_id: str) -> int:
    """`feature.features.feature_id`는 재키 뒤 uuid다 — 넘기는 것도 정본 키다."""

    async with engine.connect() as connection:
        return int(
            await connection.scalar(
                text(
                    "SELECT row_revision FROM feature.features "
                    "WHERE feature_id = CAST(:feature_id AS uuid)"
                ),
                {"feature_id": feature_id},
            )
        )


async def _seed_and_decide(
    engine: AsyncEngine, *, index: int, decision: str = "kept"
) -> tuple[str, str]:
    """쌍 하나를 심고, 탐지해 나온 case를 admin 판정으로 닫는다."""

    pair = await _seed_manual_provider_pair(engine, index=index)
    # 이 파일이 `manual_id`를 쓰는 자리는 전부 정본 축이다 — case 조회의 uuid 컬럼과
    # `feature.features` 직접 UPDATE. 그래서 seed의 **정본 키**를 받는다. legacy `f_*`는
    # alias map에만 남고(ADR-098) 여기 어디에도 들어가지 않는다.
    manual_id = str(pair["manual_feature_id"])
    first = await _detect_once(engine, run_id=f"fence-seed-{uuid4().hex[:8]}")
    case_id = await _case_id_for(engine, first.created_case_ids, manual_id)
    assert case_id is not None, "탐지가 후보를 만들지 못하면 이 테스트는 아무것도 재지 않는다"
    await _resolve_case(engine, case_id=case_id, decision=decision)
    return manual_id, case_id


async def test_a_decided_pair_is_not_raised_again_on_the_same_evidence(
    migrated_engine: AsyncEngine,
) -> None:
    """R1 — 판정된 쌍은 같은 증거로 다시 올라오지 않는다."""

    manual_id, case_id = await _seed_and_decide(migrated_engine, index=70)

    again = await _detect_once(migrated_engine, run_id=f"fence-r1-{uuid4().hex[:8]}")
    assert await _case_id_for(migrated_engine, again.created_case_ids, manual_id) is None
    # **억눌렸다는 사실을 삼키지 않는다** — 세지 않으면 "후보가 없다"와 구별되지 않는다.
    assert case_id in again.suppressed_case_ids


async def test_a_decided_pair_returns_when_the_scoring_evidence_changes(
    migrated_engine: AsyncEngine,
) -> None:
    """R2 — 증거가 실제로 바뀌면 다시 올라온다.

    **R1의 반대 방향이다.** 한 방향만 재면 반대 방향 결함(영구 침묵)이 조용히 통과한다.
    """

    manual_id, _ = await _seed_and_decide(migrated_engine, index=71)

    # `name`은 scorer가 읽는 값이다 — 이것이 바뀌면 판정 근거가 달라진 것이다.
    async with migrated_engine.begin() as connection:
        await connection.execute(
            text(
                # `name`은 varchar, `feature_id`는 uuid다 — 한 문장에서 두 축이 만난다.
                # 바인드 이름을 나눠 두고 uuid 자리에만 캐스트를 붙인다.
                "UPDATE feature.features SET name = :name "
                "WHERE feature_id = CAST(:feature_id AS uuid)"
            ),
            {"name": "M05 수동 후보 71 개명", "feature_id": manual_id},
        )

    again = await _detect_once(migrated_engine, run_id=f"fence-r2-{uuid4().hex[:8]}")
    assert (
        await _case_id_for(migrated_engine, again.created_case_ids, manual_id) is not None
    )


async def test_an_unrelated_field_patch_does_not_reraise_a_decided_pair(
    migrated_engine: AsyncEngine,
) -> None:
    """R3 — score와 무관한 patch로 `row_revision`만 올라간 경우는 재발행하지 않는다.

    차단 키를 `evidence_fingerprint`로 잡으면 여기서 실패한다 — 그 지문은
    `row_revision`을 포함하므로 무관한 patch 하나에 달라진다.
    """

    manual_id, case_id = await _seed_and_decide(migrated_engine, index=72)

    before = await _row_revision(migrated_engine, manual_id)
    async with migrated_engine.begin() as connection:
        await connection.execute(
            text(
                "UPDATE feature.features "
                "SET urls = CAST(:urls AS jsonb), row_revision = row_revision + 1 "
                "WHERE feature_id = CAST(:feature_id AS uuid)"
            ),
            {"urls": _HOMEPAGE_PATCH, "feature_id": manual_id},
        )
    after = await _row_revision(migrated_engine, manual_id)
    # 전제가 실제로 성립했는지 먼저 확인한다 — revision이 안 올라갔으면 이 테스트는
    # 아무것도 재지 않는다.
    assert after > before

    again = await _detect_once(migrated_engine, run_id=f"fence-r3-{uuid4().hex[:8]}")
    assert await _case_id_for(migrated_engine, again.created_case_ids, manual_id) is None
    assert case_id in again.suppressed_case_ids


async def test_a_superseded_resolution_does_not_silence_the_detector(
    migrated_engine: AsyncEngine,
) -> None:
    """`superseded`는 admin 판정이 아니다.

    그것으로 차단하면 탐지기가 만든 resolution이 탐지기 자신을 영구히 침묵시킨다.
    """

    pair = await _seed_manual_provider_pair(migrated_engine, index=73)
    manual_id = str(pair["manual_feature_id"])
    first = await _detect_once(migrated_engine, run_id=f"fence-r4a-{uuid4().hex[:8]}")
    case_id = await _case_id_for(migrated_engine, first.created_case_ids, manual_id)
    assert case_id is not None

    async with migrated_engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO ops.manual_provider_dedup_resolutions "
                "(case_id, decision, superseded_by_case_id, detector_causation) "
                "VALUES (CAST(:case_id AS uuid), 'superseded', CAST(:case_id AS uuid), "
                "CAST(:causation AS jsonb))"
            ),
            {"case_id": case_id, "causation": _SUPERSEDED_CAUSATION},
        )

    again = await _detect_once(migrated_engine, run_id=f"fence-r4b-{uuid4().hex[:8]}")
    assert case_id not in again.suppressed_case_ids


async def test_the_detector_login_still_cannot_read_the_case_table(
    migrated_engine: AsyncEngine,
) -> None:
    """R4 — 차단이 detector 권한을 넓히지 않는다.

    차단은 프로시저 안에서 일어난다. detector에게 case 조회 권한을 주는 방식은
    채택하지 않았고, 그 사실을 여기서 잰다.
    """

    async with migrated_engine.connect() as connection:
        for relation in (
            "ops.manual_provider_dedup_cases",
            "ops.manual_provider_dedup_resolutions",
        ):
            assert (
                await connection.scalar(
                    text(
                        "SELECT has_table_privilege("
                        "'ktm_feature_dagster_runtime', :relation, 'SELECT')"
                    ),
                    {"relation": relation},
                )
                is False
            ), relation

async def test_a_new_provider_source_record_releases_the_fence(
    migrated_engine: AsyncEngine,
) -> None:
    """provider의 **현재 source 내용**이 바뀌면 차단이 풀린다.

    이 축이 없으면 provider가 데이터를 갱신해도 판정이 영구히 굳는다 — R2가 잡는
    "score-facing 값" 방향과 별개의 해제 경로다. 차단 지문에서 source 축을 빼는
    변이가 이 테스트로만 빨개진다.
    """

    manual_id, _ = await _seed_and_decide(migrated_engine, index=74)

    async with migrated_engine.begin() as connection:
        entity_key = str(
            await connection.scalar(
                text(
                    "SELECT link.source_entity_key FROM provider_sync.source_links AS link "
                    "JOIN feature.features AS f ON f.feature_id = link.feature_id "
                    "WHERE link.source_role = 'primary' "
                    "  AND f.feature_id <> CAST(:manual_feature_id AS uuid) "
                    "  AND f.name LIKE 'M05 Provider 후보 74%'"
                ),
                {"manual_feature_id": manual_id},
            )
        )
        fresh_record = f"{entity_key}_next"
        # 새 record를 만들고 head를 그쪽으로 옮긴다 — provider가 데이터를 갱신한 모양이다.
        await connection.execute(
            text(
                "INSERT INTO provider_sync.source_records "
                "(source_record_key, source_entity_key, raw_payload_hash, raw_data, "
                " fetched_at, imported_at) "
                "VALUES (:record_key, :entity_key, repeat('c', 64), CAST('{}' AS jsonb), "
                "        clock_timestamp(), clock_timestamp())"
            ),
            {"record_key": fresh_record, "entity_key": entity_key},
        )
        await connection.execute(
            text(
                "UPDATE provider_sync.source_entity_heads "
                "SET current_source_record_key = :record_key, observed_at = clock_timestamp() "
                "WHERE source_entity_key = :entity_key"
            ),
            {"record_key": fresh_record, "entity_key": entity_key},
        )

    again = await _detect_once(migrated_engine, run_id=f"fence-r5-{uuid4().hex[:8]}")
    assert (
        await _case_id_for(migrated_engine, again.created_case_ids, manual_id) is not None
    )
