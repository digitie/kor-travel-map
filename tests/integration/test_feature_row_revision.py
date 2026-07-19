"""feature.features ``row_revision`` 트리거 + If-Match 낙관적 동시성 (T-VN-13).

migration 0062가 만든 server-owned monotonic revision과 그 위에서 correction
PATCH/DELETE/approve가 쓰는 ``_assert_feature_revision``/``get_feature_row_revision``
저수준 로직을 실제 PostGIS(testcontainers)에서 검증한다. seed는 1행이면 충분하다.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from kortravelmap.infra.admin_feature_repo import (
    FeatureChangeConflict,
    FeaturePreconditionFailed,
    _assert_feature_revision,
    apply_feature_change_request,
    get_feature_row_revision,
    submit_feature_change_request,
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

    # 없는 feature → 404로 사상할 not-found conflict. pending 요청으로 우회하지 않는다.
    with pytest.raises(FeatureChangeConflict, match="feature 없음"):
        await _assert_feature_revision(migrated_session, "no-such-feature", 1)


async def test_get_feature_row_revision_missing_returns_none(
    migrated_session: AsyncSession,
) -> None:
    assert await get_feature_row_revision(migrated_session, "no-such-feature") is None


async def test_pending_update_rejects_provider_write_after_submission(
    migrated_engine: AsyncEngine,
) -> None:
    """두 session 사이 provider write를 승인 시 저장된 base revision으로 감지한다."""
    feature_id = "test-row-revision-pending-update"
    request_id = ""
    try:
        async with (
            AsyncSession(migrated_engine, expire_on_commit=False) as submitter,
            submitter.begin(),
        ):
            await submitter.execute(
                text(
                    "INSERT INTO feature.features "
                    "(feature_id, kind, name, category) "
                    "VALUES (:fid, 'place', '제출 전', '01070300')"
                ),
                {"fid": feature_id},
            )
            request = await submit_feature_change_request(
                submitter,
                action="update",
                feature_id=feature_id,
                payload={"name": "승인 예정"},
                review_mode="require_review",
                reason="동시성 회귀",
                requested_by="tester",
                expected_row_revision=1,
            )
            request_id = request.request_id
            assert request.base_row_revision == 1

        async with (
            AsyncSession(migrated_engine) as provider,
            provider.begin(),
        ):
            await provider.execute(
                text(
                    "UPDATE feature.features SET name = 'provider 최신값' "
                    "WHERE feature_id = :fid"
                ),
                {"fid": feature_id},
            )

        async with (
            AsyncSession(migrated_engine) as reviewer,
            reviewer.begin(),
        ):
            with pytest.raises(FeaturePreconditionFailed) as excinfo:
                await apply_feature_change_request(
                    reviewer,
                    request_id,
                    operator="reviewer",
                )
            assert excinfo.value.expected == 1
            assert excinfo.value.current == 2

        async with AsyncSession(migrated_engine) as reader:
            row = (
                await reader.execute(
                    text(
                        "SELECT name, row_revision FROM feature.features "
                        "WHERE feature_id = :fid"
                    ),
                    {"fid": feature_id},
                )
            ).mappings().one()
            assert row == {"name": "provider 최신값", "row_revision": 2}
    finally:
        async with migrated_engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM ops.feature_change_requests WHERE feature_id = :fid"),
                {"fid": feature_id},
            )
            await connection.execute(
                text("DELETE FROM feature.features WHERE feature_id = :fid"),
                {"fid": feature_id},
            )


async def test_pending_add_does_not_overwrite_intermediate_insert(
    migrated_engine: AsyncEngine,
) -> None:
    feature_id = "test-row-revision-pending-add"
    try:
        async with (
            AsyncSession(migrated_engine, expire_on_commit=False) as submitter,
            submitter.begin(),
        ):
            request = await submit_feature_change_request(
                submitter,
                action="add",
                feature_id=feature_id,
                    payload={
                        "kind": "place",
                        "name": "승인 예정",
                        "category": "01070300",
                        "marker_icon": "marker",
                        "marker_color": "P-01",
                    },
                review_mode="require_review",
                reason="absence 회귀",
                requested_by="tester",
            )
            assert request.base_row_revision is None

        async with (
            AsyncSession(migrated_engine) as provider,
            provider.begin(),
        ):
            await provider.execute(
                text(
                    "INSERT INTO feature.features "
                    "(feature_id, kind, name, category) "
                    "VALUES (:fid, 'place', '중간 생성값', '01070300')"
                ),
                {"fid": feature_id},
            )

        async with (
            AsyncSession(migrated_engine) as reviewer,
            reviewer.begin(),
        ):
            with pytest.raises(FeatureChangeConflict):
                await apply_feature_change_request(
                    reviewer,
                    request.request_id,
                    operator="reviewer",
                )

        async with AsyncSession(migrated_engine) as reader:
            name = await reader.scalar(
                text("SELECT name FROM feature.features WHERE feature_id = :fid"),
                {"fid": feature_id},
            )
            assert name == "중간 생성값"
    finally:
        async with migrated_engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM ops.feature_change_requests WHERE feature_id = :fid"),
                {"fid": feature_id},
            )
            await connection.execute(
                text("DELETE FROM feature.features WHERE feature_id = :fid"),
                {"fid": feature_id},
            )
