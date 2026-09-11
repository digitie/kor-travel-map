"""Tier-2 release harness의 실제 public cardinality fail-closed 통합 검증."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from scripts.perf_tier2_release_harness import (
    BenchmarkCardinalityError,
    _run,
    _select_public_batch_feature_ids,
)
from tests.integration._db_cleanup import truncate_committed_test_rows
from tests.integration._subtype_seed import seed_feature_subtypes_for_prefix
from tests.integration.perf_gate import seed_uuid_namespace, seeded_feature_id

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = [pytest.mark.integration, pytest.mark.perf_gate]

# harness가 쓰는 두 seed 라벨. T-VN-39 재키 뒤 ``feature.features.feature_id``는
# uuid라 라벨 문자열이 값 안에 남지 않는다 — ``perf_gate``가 라벨을 uuid 대역으로
# 접고 순번을 하위 자리에 담으므로, 이 파일이 기대값을 만들 때도 같은 generator를
# 쓴다. 그래야 "harness가 DB에서 실제 id를 뽑는다"는 이 파일의 축이 fixture 표기
# 규칙과 어긋나지 않는다.
_EXISTING_LABEL = "existing:f:"
_TIER2_LABEL = "tier2:f:"
_LEGACY_TIER1_LABEL = "perf:f:"

# T-VN-35(ADR-086): core에 ``detail``이 없다 — place 값은 subtype이 정본이므로
# seed도 core 다음에 ``feature_places``를 채운다.
#
# T-VN-34C(0097): 이 seed가 만들려는 것은 "공개 표면에 실리는 행"이다. 단일
# ``status='active'``가 뜻하던 그 한 가지를 3축이 그대로 이어받는다 —
# ``feature.public_features``의 WHERE가 곧 (lifecycle active, publication
# published, quality valid)이므로 세 값을 다 준 행만 public projection에 뜬다.
# 세 열의 DEFAULT가 우연히 같은 조합이지만 생략하지 않는다: 이 harness가 재는
# 것은 "기본값 행"이 아니라 "공개 행"의 cardinality이고, 아래 단언(220건 public,
# 200건 batch)이 성립하는 근거를 seed가 직접 밝혀야 하기 때문이다.
_CUSTOM_PUBLIC_FEATURES_SQL = """
INSERT INTO feature.features (
    feature_id, kind, name, category, coord,
    address, urls, raw_refs,
    lifecycle_state, publication_state, quality_state,
    legal_dong_code, sido_code, sigungu_code,
    created_at, updated_at
)
SELECT
    CAST(:uuid_namespace || lpad(to_hex(g), 12, '0') AS uuid),
    'place',
    '카페',
    '01070300',
    x_extension.ST_SetSRID(
        x_extension.ST_MakePoint(
            126.97 + ((g % 40)::float * 0.001),
            37.51 + ((g % 40)::float * 0.001)
        ),
        4326
    ),
    jsonb_build_object('road', '서울특별시 종로구 실측로 ' || g::text),
    '{}'::jsonb,
    '[]'::jsonb,
    'active',
    'published',
    'valid',
    '1111010100',
    '11',
    '11110',
    now() - (g::text || ' minutes')::interval,
    now() - (g::text || ' seconds')::interval
FROM generate_series(1, :rows) AS g
"""


def _dsn(engine: AsyncEngine) -> str:
    return engine.url.render_as_string(hide_password=False)


async def _count_in_namespace(session: AsyncSession, label: str) -> int:
    """그 seed 라벨의 uuid 대역에 속한 ``feature.features`` 행 수."""

    return int(
        (
            await session.execute(
                text(
                    "SELECT count(*) FROM feature.features "
                    "WHERE CAST(feature_id AS text) LIKE :namespace || '%'"
                ),
                {"namespace": seed_uuid_namespace(label)},
            )
        ).scalar_one()
    )


async def _cleanup_committed_fixture(engine: AsyncEngine) -> None:
    async with AsyncSession(engine) as session, session.begin():
        await truncate_committed_test_rows(
            session,
            "TRUNCATE TABLE feature.features, "
            "provider_sync.source_entities, provider_sync.source_records "
            "RESTART IDENTITY CASCADE",
        )


async def _seed_custom_public_features(
    engine: AsyncEngine,
    *,
    rows: int,
) -> None:
    async with AsyncSession(engine) as session, session.begin():
        namespace = seed_uuid_namespace(_EXISTING_LABEL)
        await session.execute(
            text(_CUSTOM_PUBLIC_FEATURES_SQL),
            {"uuid_namespace": namespace, "rows": rows},
        )
        await seed_feature_subtypes_for_prefix(session, namespace)
        await session.execute(text("ANALYZE feature.features"))


def _assert_report_cardinality(report: dict[str, object]) -> None:
    viewports = report["viewports"]
    assert isinstance(viewports, list)
    assert len(viewports) == 5
    for viewport in viewports:
        assert isinstance(viewport, dict)
        assert viewport["matched_rows"] >= viewport["returned_rows"]
        assert viewport["returned_rows"] >= viewport["minimum_returned_rows"]
        assert viewport["response_bytes"] > 0
    batch = next(viewport for viewport in viewports if viewport["name"] == "200건 batch")
    assert batch["matched_rows"] == batch["returned_rows"] == 200


def _expected_seed_public_ids(label: str, rows: int) -> list[str]:
    """``perf_gate`` seed가 매 29번째 행을 공개 표면에서 빼는 규칙을 반영한다.

    legacy seed에서는 그 행이 ``status='inactive'``였고 0097 이후에는 lifecycle
    ``retired``(+ publication ``suppressed``)다. 이름이 무엇이든 여기서 필요한
    의미는 하나 — ``feature.public_features``에 뜨지 않는다는 것뿐이다.

    반환 순서는 selector의 ``ORDER BY feature_id``와 같다 — 한 라벨의 uuid 대역은
    상수이고 순번이 하위 자리라, uuid 정렬이 곧 순번 정렬이다.
    """

    return [
        seeded_feature_id(label, index)
        for index in range(1, rows + 1)
        if index % 29 != 0
    ]


async def test_seed_mode_resolves_database_ids_instead_of_legacy_fixed_batch(
    migrated_engine: AsyncEngine,
) -> None:
    await _cleanup_committed_fixture(migrated_engine)
    try:
        report = await _run(_dsn(migrated_engine), 220, 1, False)

        assert report["mode"] == "seeded"
        assert report["requested_seed_rows"] == 220
        expected_public_ids = _expected_seed_public_ids(_TIER2_LABEL, 220)
        assert report["public_feature_rows"] == len(expected_public_ids)
        assert report["batch_candidate_rows"] == len(expected_public_ids)
        _assert_report_cardinality(report)
        async with AsyncSession(migrated_engine) as session:
            selected = await _select_public_batch_feature_ids(session)
            # 라벨은 uuid 대역으로만 남는다 — 대역 prefix로 세어 "tier-1 고정
            # fixture(``perf:f:``) 행이 하나도 없다"를 종전과 같은 뜻으로 본다.
            legacy_count = await _count_in_namespace(session, _LEGACY_TIER1_LABEL)
            tier2_count = await _count_in_namespace(session, _TIER2_LABEL)
        assert legacy_count == 0
        assert tier2_count == 220
        assert selected == expected_public_ids[:200]
    finally:
        await _cleanup_committed_fixture(migrated_engine)


async def test_skip_seed_uses_real_public_rows_when_legacy_fixed_ids_are_absent(
    migrated_engine: AsyncEngine,
) -> None:
    await _cleanup_committed_fixture(migrated_engine)
    try:
        await _seed_custom_public_features(migrated_engine, rows=220)
        async with AsyncSession(migrated_engine) as session:
            selected = await _select_public_batch_feature_ids(session)

        report = await _run(_dsn(migrated_engine), 1_000_000, 1, True)

        assert report["mode"] == "existing"
        assert report["requested_seed_rows"] is None
        assert report["public_feature_rows"] == 220
        assert report["batch_candidate_rows"] == 220
        _assert_report_cardinality(report)
        assert selected == [
            seeded_feature_id(_EXISTING_LABEL, index) for index in range(1, 201)
        ]
        viewports = {
            viewport["name"]: viewport
            for viewport in report["viewports"]
            if isinstance(viewport, dict)
        }
        assert viewports["서울 밀집 in-bounds"]["matched_rows"] == 220
        assert viewports["서울 밀집 in-bounds"]["returned_rows"] == 200
        assert viewports["100km nearby"]["matched_rows"] == 220
        assert viewports["100km nearby"]["returned_rows"] == 51
        assert viewports["상용 검색어 search"]["matched_rows"] == 220
        assert viewports["상용 검색어 search"]["returned_rows"] == 51
    finally:
        await _cleanup_committed_fixture(migrated_engine)


async def test_batch_selector_excludes_notice_candidates(
    migrated_engine: AsyncEngine,
) -> None:
    await _cleanup_committed_fixture(migrated_engine)
    try:
        await _seed_custom_public_features(migrated_engine, rows=201)
        async with AsyncSession(migrated_engine) as session, session.begin():
            # T-VN-35(ADR-086): subtype 행이 있는 동안 core kind 변경은 배타 arc
            # FK가 막는다. kind 전환은 "옛 subtype 제거 → core kind → 새 subtype"
            # 순서로만 가능하다(그 순서 강제 자체가 이 재설계의 요점).
            flipped = seeded_feature_id(_EXISTING_LABEL, 1)
            await session.execute(
                text(
                    "DELETE FROM feature.feature_places "
                    "WHERE feature_id = CAST(:feature_id AS uuid)"
                ),
                {"feature_id": flipped},
            )
            await session.execute(
                text(
                    "UPDATE feature.features SET kind = 'notice', category = '99000000' "
                    "WHERE feature_id = CAST(:feature_id AS uuid)"
                ),
                {"feature_id": flipped},
            )
            # T-VN-39: subtype의 사본 컬럼 ``feature_uuid``는 309가 지웠다.
            # 심을 값은 core의 정본 키 하나뿐이다.
            await session.execute(
                text(
                    "INSERT INTO feature.feature_notices "
                    "(feature_id, kind, notice_type) "
                    "SELECT f.feature_id, f.kind, 'safety' "
                    "FROM feature.features AS f "
                    "WHERE f.feature_id = CAST(:feature_id AS uuid)"
                ),
                {"feature_id": flipped},
            )
        async with AsyncSession(migrated_engine) as session:
            selected = await _select_public_batch_feature_ids(session)

        assert flipped not in selected
        assert selected == [
            seeded_feature_id(_EXISTING_LABEL, index) for index in range(2, 202)
        ]
    finally:
        await _cleanup_committed_fixture(migrated_engine)


async def test_skip_seed_fails_closed_below_public_batch_cardinality(
    migrated_engine: AsyncEngine,
) -> None:
    await _cleanup_committed_fixture(migrated_engine)
    try:
        await _seed_custom_public_features(migrated_engine, rows=199)

        with pytest.raises(BenchmarkCardinalityError, match="199건만 존재함"):
            await _run(_dsn(migrated_engine), 1_000_000, 1, True)
    finally:
        await _cleanup_committed_fixture(migrated_engine)


async def test_skip_seed_fails_closed_when_representative_viewport_is_empty(
    migrated_engine: AsyncEngine,
) -> None:
    await _cleanup_committed_fixture(migrated_engine)
    try:
        await _seed_custom_public_features(migrated_engine, rows=220)
        async with AsyncSession(migrated_engine) as session, session.begin():
            await session.execute(
                text(
                    "UPDATE feature.features SET coord = "
                    "x_extension.ST_SetSRID(x_extension.ST_MakePoint(129.0, 35.0), 4326)"
                )
            )
            await session.execute(text("ANALYZE feature.features"))

        with pytest.raises(
            BenchmarkCardinalityError,
            match="서울 밀집 in-bounds: 최소 1행",
        ):
            await _run(_dsn(migrated_engine), 1_000_000, 1, True)
    finally:
        await _cleanup_committed_fixture(migrated_engine)
