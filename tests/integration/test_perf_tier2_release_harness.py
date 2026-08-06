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

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = [pytest.mark.integration, pytest.mark.perf_gate]

# T-VN-35(ADR-084): core에 ``detail``이 없다 — place 값은 subtype이 정본이므로
# seed도 core 다음에 ``feature_places``를 채운다.
_CUSTOM_PUBLIC_FEATURES_SQL = """
INSERT INTO feature.features (
    feature_id, kind, name, category, coord,
    address, urls, raw_refs,
    status, legal_dong_code, sido_code, sigungu_code,
    created_at, updated_at
)
SELECT
    :prefix || lpad(g::text, 6, '0'),
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
    '1111010100',
    '11',
    '11110',
    now() - (g::text || ' minutes')::interval,
    now() - (g::text || ' seconds')::interval
FROM generate_series(1, :rows) AS g
"""


def _dsn(engine: AsyncEngine) -> str:
    return engine.url.render_as_string(hide_password=False)


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
        await session.execute(
            text(_CUSTOM_PUBLIC_FEATURES_SQL),
            {"prefix": "existing:f:", "rows": rows},
        )
        await seed_feature_subtypes_for_prefix(session, "existing:f:")
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


def _expected_seed_public_ids(prefix: str, rows: int) -> list[str]:
    """``perf_gate`` seed의 매 29번째 inactive 규칙을 그대로 반영한다."""

    return [
        f"{prefix}{index:06d}" for index in range(1, rows + 1) if index % 29 != 0
    ]


async def test_seed_mode_resolves_database_ids_instead_of_legacy_fixed_batch(
    migrated_engine: AsyncEngine,
) -> None:
    await _cleanup_committed_fixture(migrated_engine)
    try:
        report = await _run(_dsn(migrated_engine), 220, 1, False)

        assert report["mode"] == "seeded"
        assert report["requested_seed_rows"] == 220
        expected_public_ids = _expected_seed_public_ids("tier2:f:", 220)
        assert report["public_feature_rows"] == len(expected_public_ids)
        assert report["batch_candidate_rows"] == len(expected_public_ids)
        _assert_report_cardinality(report)
        async with AsyncSession(migrated_engine) as session:
            selected = await _select_public_batch_feature_ids(session)
            legacy_count = int(
                (
                    await session.execute(
                        text(
                            "SELECT count(*) FROM feature.features "
                            "WHERE feature_id LIKE 'perf:f:%'"
                        )
                    )
                ).scalar_one()
            )
            tier2_count = int(
                (
                    await session.execute(
                        text(
                            "SELECT count(*) FROM feature.features "
                            "WHERE feature_id LIKE 'tier2:f:%'"
                        )
                    )
                ).scalar_one()
            )
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
        assert selected == [f"existing:f:{index:06d}" for index in range(1, 201)]
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
            # T-VN-35(ADR-084): subtype 행이 있는 동안 core kind 변경은 배타 arc
            # FK가 막는다. kind 전환은 "옛 subtype 제거 → core kind → 새 subtype"
            # 순서로만 가능하다(그 순서 강제 자체가 이 재설계의 요점).
            await session.execute(
                text(
                    "DELETE FROM feature.feature_places "
                    "WHERE feature_id = 'existing:f:000001'"
                )
            )
            await session.execute(
                text(
                    "UPDATE feature.features SET kind = 'notice', category = '99000000' "
                    "WHERE feature_id = 'existing:f:000001'"
                )
            )
            await session.execute(
                text(
                    "INSERT INTO feature.feature_notices "
                    "(feature_id, feature_uuid, kind, notice_type) "
                    "SELECT f.feature_id, f.feature_uuid, f.kind, 'safety' "
                    "FROM feature.features AS f "
                    "WHERE f.feature_id = 'existing:f:000001'"
                )
            )
        async with AsyncSession(migrated_engine) as session:
            selected = await _select_public_batch_feature_ids(session)

        assert "existing:f:000001" not in selected
        assert selected == [f"existing:f:{index:06d}" for index in range(2, 202)]
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
