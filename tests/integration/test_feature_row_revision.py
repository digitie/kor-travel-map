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

    # 이 단계가 확인하려는 것은 "삭제조차 DELETE가 아니라 UPDATE라서 행이 남고
    # revision이 끊기지 않고 이어진다"이다. 0097이 legacy `deleted_at`/`status`를
    # 물리 삭제했으므로, 같은 사실을 3축 spine의 은퇴(retire) 전이로 옮긴다.
    # 0095 backfill이 정의한 등가는 `deleted_at IS NOT NULL` 또는
    # `status='deleted'` ≡ `lifecycle_state='retired'`이고, 0095의
    # `ck_features_state_tuple`(retired면 publication은 반드시 suppressed)이
    # 두 축을 한 문장 안에서 함께 옮기도록 강제한다 — 은퇴는 두 번의 독립 write가
    # 아니라 한 번의 원자적 전이다.
    #
    # 은퇴 직전까지 이 행은 공개 정본에 떠 있다. 아래 전후 대조가 "행은 남는다"의
    # 실제 의미(base table에는 남고 공개 표면에서만 빠진다)를 축 값 문자열이 아니라
    # 관측 가능한 표면으로 못박는다.
    assert await _is_publicly_visible(migrated_session, _FID) is True

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
