"""Feature row revision의 최종 3축 state 경계 통합 회귀."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.infra.admin_feature_repo import get_feature_row_revision

pytestmark = [pytest.mark.integration]

_FID = "test-row-revision-1"


async def _seed_one_feature(session: AsyncSession) -> None:
    await session.execute(
        text(
            "INSERT INTO feature.features "
            "(feature_id, kind, name, category) "
            "VALUES (:fid, 'place', '광화문', '01070300')"
        ),
        {"fid": _FID},
    )


async def _is_publicly_visible(session: AsyncSession, feature_id: str) -> bool:
    """공개 정본 ``feature.public_features``에 이 feature가 실재하는가.

    3축 spine에서 "공개에 보인다"는 축 값 하나가 아니라 세 축의 교집합
    (active/published/valid)이라, 축 컬럼을 직접 단언하면 공개 규칙이 바뀔 때
    테스트가 조용히 낡는다. 공개 여부는 view 실재로만 묻는다 (ADR-067).
    """
    return bool(
        await session.scalar(
            text("SELECT EXISTS (SELECT 1 FROM feature.public_features WHERE feature_id = :fid)"),
            {"fid": feature_id},
        )
    )


async def test_row_revision_is_server_owned_for_normal_and_axis_updates(
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
    assert await _is_publicly_visible(migrated_session, _FID) is True

    # 축 전이와 함께 애플리케이션이 값을 직접 써도 서버가 OLD+1로 덮어쓴다
    # (우회 불가·server-owned).
    await migrated_session.execute(
        text(
            "UPDATE feature.features "
            "SET publication_state = 'suppressed', row_revision = 999 "
            "WHERE feature_id = :fid"
        ),
        {"fid": _FID},
    )
    assert await get_feature_row_revision(migrated_session, _FID) == 3
    assert await _is_publicly_visible(migrated_session, _FID) is False

    # 이 단계가 확인하려는 것은 "삭제조차 DELETE가 아니라 UPDATE라서 행이 남고
    # revision이 끊기지 않고 이어진다"이다. 0097이 legacy `deleted_at`/`status`를
    # 물리 삭제했으므로, 같은 사실을 3축 spine의 은퇴(retire) 전이로 옮긴다.
    # 0095 backfill이 정의한 등가는 `deleted_at IS NOT NULL` 또는
    # `status='deleted'` ≡ `lifecycle_state='retired'`이고, 0095의
    # `ck_features_state_tuple`(retired면 publication은 반드시 suppressed)이
    # 두 축이 함께 움직이도록 강제한다.
    await migrated_session.execute(
        text(
            "UPDATE feature.features "
            "SET lifecycle_state = 'retired', publication_state = 'suppressed' "
            "WHERE feature_id = :fid"
        ),
        {"fid": _FID},
    )
    # 행이 살아 있으므로 revision 조회가 값을 돌려주고, 그 값은 3에서 4로 이어진다.
    assert await get_feature_row_revision(migrated_session, _FID) == 4
    assert await _is_publicly_visible(migrated_session, _FID) is False


async def test_get_feature_row_revision_missing_returns_none(
    migrated_session: AsyncSession,
) -> None:
    assert await get_feature_row_revision(migrated_session, "no-such-feature") is None
