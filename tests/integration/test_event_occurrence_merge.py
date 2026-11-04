"""동명 행사 회차의 실제 runtime 병합 경계."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from sqlalchemy import text

from kortravelmap.infra.merge_repo import MergeConflictError, apply_feature_merge
from kortravelmap.infra.models import FeatureRow
from tests.integration._subtype_seed import seed_feature_subtype
from tests.integration.conftest import as_api_runtime

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration


async def _snapshot(session: AsyncSession, ids: list[str]) -> list[tuple[object, ...]]:
    rows = (await session.execute(text("""
        SELECT feature_id, lifecycle_state, publication_state, quality_state,
               row_revision,
               (SELECT count(*) FROM provider_sync.source_links s
                WHERE s.feature_id = f.feature_id) AS links,
               (SELECT count(*) FROM ops.feature_merge_history h
                WHERE h.master_feature_id = f.feature_id
                   OR h.loser_feature_id = f.feature_id) AS merges,
               (SELECT count(*) FROM feature.feature_state_transitions t
                WHERE t.feature_id = f.feature_id) AS transitions
        FROM feature.features f WHERE feature_id = ANY(CAST(:ids AS uuid[]))
        ORDER BY feature_id
    """), {"ids": ids})).all()
    return [tuple(row) for row in rows]


@pytest.mark.parametrize(
    ("start", "end", "venue", "allowed"),
    [
        ("2026-05-01", "2026-05-03", "종묘", True),
        ("2025-05-01", "2025-05-03", "종묘", False),
        ("2026-05-02", "2026-05-04", "종묘", False),
        ("2026-05-01", "2026-05-03", "다른 장소", False),
        (None, None, None, True),
    ],
)
async def test_direct_event_merge_checks_locked_subtype_as_runtime(
    migrated_session: AsyncSession,
    start: str | None, end: str | None, venue: str | None, allowed: bool,
) -> None:
    master, loser = str(uuid4()), str(uuid4())
    for feature_id, begins, ends, place in (
        (master, "2026-05-01", "2026-05-03", "종묘"), (loser, start, end, venue),
    ):
        migrated_session.add(FeatureRow(
            feature_id=feature_id, kind="event", name="우리들의 축제", category="01090000",
        ))
        await migrated_session.flush()
        await seed_feature_subtype(
            migrated_session, feature_id=feature_id, kind="event",
            detail={"starts_on": begins, "ends_on": ends, "venue_name": place},
        )
    before = await _snapshot(migrated_session, [master, loser])
    if allowed:
        async with migrated_session.begin_nested(), as_api_runtime(migrated_session):
            await apply_feature_merge(migrated_session, master_id=master, loser_id=loser)
        after = await _snapshot(migrated_session, [master, loser])
        assert before != after
        assert any(str(row[0]) == loser and row[1] == "retired" for row in after)
    else:
        with pytest.raises(MergeConflictError, match="회차"):
            async with migrated_session.begin_nested(), as_api_runtime(migrated_session):
                await apply_feature_merge(migrated_session, master_id=master, loser_id=loser)
        assert await _snapshot(migrated_session, [master, loser]) == before
