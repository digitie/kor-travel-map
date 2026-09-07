"""T-VN-M05-3 — detector가 대상을 열거하고 후보를 발행하는 경로.

배포된 M05는 **쓰기 쪽만** 있었다. `record_manual_provider_dedup_candidate`는 이미
아는 쌍 하나를 기록하고, 그것이 detector executor가 EXECUTE할 수 있는 유일한
routine이었다. 쌍을 **찾는** 경로는 없었다 — manual origin을 증명하는 두 표가
`ktm_feature_dagster_runtime`에서 이름으로 REVOKE돼 있기 때문이다.

migration 304의 좁은 reader가 그 공백만 연다. 이 파일은 그 reader가
(a) 정말로 detector 전용인지, (b) 프로시저의 manual origin 판정과 **어긋나지
않는지**, (c) 쓰기를 할 수 없는지, 그리고 (d) 탐지기가 훑은 범위를 후보 유무와
무관하게 보고하는지를 잰다.
"""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from kortravelmap.infra.manual_provider_dedup_repo import (
    detect_manual_provider_candidates,
    manual_origin_features,
)

from .test_tvn_m05_manual_provider_dedup import (
    _runtime_engine,
    _seed_manual_provider_pair,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.usefixtures("tvn_m01_m05_role_graph"),
]

_LISTING = "feature.list_manual_provider_dedup_detector_manuals(text,integer)"


async def _listing_rows(
    engine: AsyncEngine, *, after: str | None = None, limit: int = 1000
) -> list[str]:
    async with engine.connect() as connection:
        result = await connection.execute(
            text(
                "SELECT feature_id FROM "
                "feature.list_manual_provider_dedup_detector_manuals("
                "CAST(:after AS text), CAST(:limit AS integer))"
            ),
            {"after": after, "limit": limit},
        )
        return [str(row.feature_id) for row in result]


async def test_the_listing_and_the_procedure_agree_on_manual_origin(
    migrated_engine: AsyncEngine,
) -> None:
    """목록과 프로시저는 **같은 manual origin 판정**을 써야 한다.

    이 둘은 같은 진실을 두 곳에 적은 것이다(목록의 WHERE와 프로시저의
    `ck_m05_candidate_manual_origin`). 어긋나면 탐지기가 조용히 비거나 23514
    폭풍이 난다. 그래서 값이 아니라 **집합의 일치**를 잰다 — 목록이 돌려준
    Feature는 프로시저가 반드시 받고, 목록이 뺀 Feature는 프로시저가 반드시
    그 CONSTRAINT로 거부해야 한다.
    """

    pair = await _seed_manual_provider_pair(migrated_engine, index=10)
    dagster = _runtime_engine(migrated_engine, login="ktm_feature_dagster_runtime")
    try:
        listed = await _listing_rows(dagster)
        assert pair["manual_feature_id"] in listed
        # provider Feature는 manual origin이 아니므로 목록에 없어야 한다.
        assert pair["provider_feature_id"] not in listed

        # 목록이 뺀 쪽을 manual 자리에 넣으면 프로시저가 그 CONSTRAINT로 거부한다.
        async with dagster.connect() as connection:
            await connection.execute(
                text("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
            )
            with pytest.raises(DBAPIError) as rejected:
                await connection.execute(
                    text(
                        "CALL feature.record_manual_provider_dedup_candidate("
                        "CAST(:manual AS text), CAST(:provider AS text), "
                        "CAST(:scores AS jsonb), CAST(:causation AS jsonb), "
                        "NULL::uuid, NULL::text)"
                    ),
                    {
                        # 일부러 뒤집는다 — provider를 manual 자리에.
                        "manual": pair["provider_feature_id"],
                        "provider": pair["manual_feature_id"],
                        "scores": json.dumps(
                            {
                                "name_score": 0.9,
                                "spatial_score": 0.9,
                                "category_score": 0.9,
                                "total_score": 0.9,
                                "distance_meters": 1.0,
                                "scorer_input_sha256": "b" * 64,
                            }
                        ),
                        "causation": json.dumps({"scope": "binder"}),
                    },
                )
            await connection.rollback()
        assert (
            getattr(rejected.value.orig, "constraint_name", None)
            == "ck_m05_candidate_manual_origin"
        )
    finally:
        await dagster.dispose()


async def test_the_listing_body_guard_is_not_masked_by_the_acl(
    migrated_engine: AsyncEngine,
) -> None:
    """ACL과 본문 검사가 **둘 다** 막아야 한다.

    EXECUTE가 없는 principal로만 재면 본문의 `session_user` 검사를 지워도 초록이다
    (ACL이 먼저 막으므로). 그래서 **EXECUTE를 가진** principal(함수 owner)로도
    재서 본문 검사가 살아 있는지 확인한다 — 두 실패의 SQLSTATE는 같은 42501이지만
    본문 검사만 CONSTRAINT 이름을 남긴다.
    """

    await _seed_manual_provider_pair(migrated_engine, index=11)

    # (a) EXECUTE 없음 — ACL이 막는다.
    api = _runtime_engine(migrated_engine, login="ktm_feature_api_runtime")
    try:
        with pytest.raises(DBAPIError) as by_acl:
            await _listing_rows(api)
        assert getattr(by_acl.value.orig, "sqlstate", None) == "42501"
        assert getattr(by_acl.value.orig, "constraint_name", None) is None
    finally:
        await api.dispose()

    # (b) EXECUTE 있음(owner) — 본문 검사가 막는다.
    async with migrated_engine.connect() as connection:
        assert (
            await connection.scalar(
                text(
                    "SELECT has_function_privilege("
                    "'ktm_manual_provider_dedup_procedure_owner', "
                    f"'{_LISTING}'::regprocedure, 'EXECUTE')"
                )
            )
            is True
        )
        with pytest.raises(DBAPIError) as by_body:
            await connection.execute(
                text(
                    "SET LOCAL ROLE ktm_manual_provider_dedup_procedure_owner; "
                    "SELECT feature_id FROM "
                    "feature.list_manual_provider_dedup_detector_manuals(NULL, 10)"
                )
            )
        await connection.rollback()
    assert getattr(by_body.value.orig, "sqlstate", None) == "42501"
    assert (
        getattr(by_body.value.orig, "constraint_name", None)
        == "ck_m05_detector_manuals_executor"
    )


async def test_the_listing_cannot_write_because_the_engine_forbids_it(
    migrated_engine: AsyncEngine,
) -> None:
    """읽기 전용은 약속이 아니라 엔진이 강제한다.

    `STABLE`이면 SPI가 read-only로 돌아 SECURITY DEFINER owner 권한으로도
    INSERT/UPDATE/DELETE/CALL을 할 수 없다. `VOLATILE`로 바꾸면 이 단언이 깨진다.
    """

    async with migrated_engine.connect() as connection:
        volatility = await connection.scalar(
            text(
                "SELECT provolatile FROM pg_catalog.pg_proc "
                f"WHERE oid = '{_LISTING}'::regprocedure"
            )
        )
        owner = await connection.scalar(
            text(
                "SELECT pg_get_userbyid(proowner) FROM pg_catalog.pg_proc "
                f"WHERE oid = '{_LISTING}'::regprocedure"
            )
        )
        secdef = await connection.scalar(
            text(
                "SELECT prosecdef FROM pg_catalog.pg_proc "
                f"WHERE oid = '{_LISTING}'::regprocedure"
            )
        )
    assert volatility == "s"
    assert owner == "ktm_manual_provider_dedup_procedure_owner"
    assert secdef is True


async def test_the_detector_login_still_cannot_read_the_origin_tables(
    migrated_engine: AsyncEngine,
) -> None:
    """경계는 함수 하나만큼만 움직였다 — 표 자체는 여전히 안 보인다."""

    async with migrated_engine.connect() as connection:
        for relation in (
            "feature.feature_creation_origins",
            "feature.manual_feature_identity_claims",
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


async def test_the_detector_records_a_candidate_and_reports_the_scope_it_scanned(
    migrated_engine: AsyncEngine,
) -> None:
    """탐지기가 후보를 남기고, 그 case가 **어떤 범위를 본 결과인지**를 싣는다."""

    pair = await _seed_manual_provider_pair(migrated_engine, index=12)
    dagster = _runtime_engine(migrated_engine, login="ktm_feature_dagster_runtime")
    run_id = f"itest-{uuid4().hex[:12]}"
    try:
        async with AsyncSession(dagster) as session, session.begin():
            outcome = await detect_manual_provider_candidates(session, run_id=run_id)

        assert outcome.manual_input_count >= 1
        assert outcome.scored_pair_count >= 1
        assert len(outcome.created_case_ids) == 1
        assert outcome.complete_set is True

        async with migrated_engine.connect() as connection:
            row = (
                await connection.execute(
                    text(
                        "SELECT manual_feature_id, provider_feature_id, scorer_id, "
                        "detector_causation, total_score "
                        "FROM ops.manual_provider_dedup_cases WHERE case_id = :case_id"
                    ),
                    {"case_id": outcome.created_case_ids[0]},
                )
            ).one()
        assert row.manual_feature_id == pair["manual_feature_id"]
        assert row.provider_feature_id == pair["provider_feature_id"]
        assert row.scorer_id == "manual-provider-v1"
        assert float(row.total_score) >= 0.65

        causation = row.detector_causation
        assert causation["run_id"] == run_id
        # 이 셋이 없으면 "후보가 없다"와 "다 보지 않았다"가 같아 보인다.
        assert causation["block"]["complete_set"] is True
        assert causation["block"]["radius_meters"] > 0
        assert causation["detector_input_count"]["provider_in_block"] >= 1
    finally:
        await dagster.dispose()


async def test_the_detector_reports_its_scope_even_when_nothing_survives(
    migrated_engine: AsyncEngine,
) -> None:
    """후보가 0건이어도 훑은 범위는 보고한다.

    이 단언이 없으면 "후보가 없다"와 "manual 질의가 조용히 비었다"가 증거상
    구별되지 않는다 — 이 저장소가 반복해 겪은 실패 양상이다. 임계값을 1.01로
    올려 어떤 쌍도 통과하지 못하게 만든 뒤, 그래도 집계가 남는지 본다.
    """

    await _seed_manual_provider_pair(migrated_engine, index=13)
    dagster = _runtime_engine(migrated_engine, login="ktm_feature_dagster_runtime")
    try:
        async with AsyncSession(dagster) as session, session.begin():
            # 반경을 1m로 좁히면 이웃이 사라진다 — 후보 0건, 그러나 manual은 훑었다.
            outcome = await detect_manual_provider_candidates(
                session, run_id=f"empty-{uuid4().hex[:8]}", radius_meters=1.0
            )
        assert outcome.created_case_ids == ()
        assert outcome.idempotent_case_ids == ()
        assert outcome.manual_input_count >= 1
        assert outcome.scored_pair_count == 0
    finally:
        await dagster.dispose()


async def test_the_manual_cursor_advances_past_a_page_with_no_neighbour(
    migrated_engine: AsyncEngine,
) -> None:
    """cursor는 **쌍이 아니라 manual**로 전진한다.

    reader가 쌍을 돌려주면 이웃 없는 manual에서 페이지가 비고, cursor가 없어
    그 뒤 manual이 영원히 스캔에서 빠진다(적대 리뷰가 잡은 결함). 페이지 크기를
    1로 놓고 여러 manual을 심어, 마지막 manual까지 실제로 도달하는지 잰다.
    """

    pairs = [
        await _seed_manual_provider_pair(migrated_engine, index=i) for i in range(3)
    ]
    wanted = {str(pair["manual_feature_id"]) for pair in pairs}
    dagster = _runtime_engine(migrated_engine, login="ktm_feature_dagster_runtime")
    try:
        seen: list[str] = []
        after: str | None = None
        for _ in range(50):
            page = await manual_origin_features(
                AsyncSession(dagster), after=after, limit=1
            )
            if not page:
                break
            seen.append(page[0].feature_id)
            after = page[0].feature_id
        assert wanted <= set(seen)
        assert len(seen) == len(set(seen))
    finally:
        await dagster.dispose()
