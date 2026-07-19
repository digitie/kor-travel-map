"""feature.features ``row_revision`` 트리거 + If-Match 낙관적 동시성 (T-VN-13).

migration 0062가 만든 server-owned monotonic revision과 그 위에서 correction
PATCH/DELETE/approve가 쓰는 ``_assert_feature_revision``/``get_feature_row_revision``
저수준 로직을 실제 PostGIS(testcontainers)에서 검증한다. seed는 1행이면 충분하다.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.infra.admin_feature_repo import (
    FeaturePreconditionFailed,
    _assert_feature_revision,
    get_feature_row_revision,
)

pytestmark = [pytest.mark.integration]

_FID = "test-row-revision-1"


async def _seed_one_feature(session: AsyncSession) -> None:
    await session.execute(
        text(
            "INSERT INTO feature.features (feature_id, kind, name, category) "
            "VALUES (:fid, 'place', '광화문', '01070300')"
        ),
        {"fid": _FID},
    )


async def test_row_revision_defaults_to_one_and_bumps_on_every_update(
    migrated_session: AsyncSession,
) -> None:
    await _seed_one_feature(migrated_session)
    assert await get_feature_row_revision(migrated_session, _FID) == 1

    # 어떤 UPDATE든 트리거가 revision을 +1 강제한다.
    await migrated_session.execute(
        text("UPDATE feature.features SET name = '수정' WHERE feature_id = :fid"),
        {"fid": _FID},
    )
    assert await get_feature_row_revision(migrated_session, _FID) == 2

    # 애플리케이션이 값을 직접 써도 서버가 OLD+1로 덮어쓴다 (우회 불가·server-owned).
    await migrated_session.execute(
        text(
            "UPDATE feature.features SET row_revision = 999 WHERE feature_id = :fid"
        ),
        {"fid": _FID},
    )
    assert await get_feature_row_revision(migrated_session, _FID) == 3

    # soft-delete도 UPDATE라 revision이 이어서 증가한다 (행은 남는다).
    await migrated_session.execute(
        text(
            "UPDATE feature.features "
            "SET deleted_at = now(), status = 'deleted' WHERE feature_id = :fid"
        ),
        {"fid": _FID},
    )
    assert await get_feature_row_revision(migrated_session, _FID) == 4


async def test_assert_feature_revision_if_match_semantics(
    migrated_session: AsyncSession,
) -> None:
    await _seed_one_feature(migrated_session)

    # 일치 → 통과 (예외 없음).
    await _assert_feature_revision(migrated_session, _FID, 1)

    # 불일치 → 412 신호(FeaturePreconditionFailed), current/expected 노출.
    with pytest.raises(FeaturePreconditionFailed) as excinfo:
        await _assert_feature_revision(migrated_session, _FID, 5)
    assert excinfo.value.current == 1
    assert excinfo.value.expected == 5
    assert excinfo.value.feature_id == _FID

    # 없는 feature → 통과(하위 not-found 경로가 404를 내도록 위임, 412 아님).
    await _assert_feature_revision(migrated_session, "no-such-feature", 1)


async def test_get_feature_row_revision_missing_returns_none(
    migrated_session: AsyncSession,
) -> None:
    assert await get_feature_row_revision(migrated_session, "no-such-feature") is None
