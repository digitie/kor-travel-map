"""``feature.feature_geocode_stamps``(migration 407)와 스탬프 repo (ADR-109 결정 1, T-GR-01).

고정하는 것:

- 두 토큰 열은 NOT NULL이고 형식 CHECK가 있다 — 어느 outcome이든 NULL·틀린 형식 스탬프는 DB가 거부한다.
- 현재 토큰이 없거나 ``data_token``이 None이면 :func:`upsert_stamps`는 아무것도 쓰지 않는다.
- stale 5분기(스탬프 없음·``not_called``·``geocoded`` 다른 토큰·``called`` 다른 토큰·같은 토큰)와
  "현재 토큰 None → stale 0건"이 :func:`is_stale`·:func:`select_stale_feature_ids`에서 같다.
- 런타임 role(``ktm_feature_service``)이 실제로 쓰고 읽을 수 있다(배포 조정기가 건 ACL).
- Feature 삭제가 스탬프를 따라 지운다(FK CASCADE).

세션은 테스트마다 롤백된다(``migrated_session``).
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from kortravelmap.dto.geo_dataset import DatasetRef
from kortravelmap.infra.feature_geocode_stamp_repo import (
    get_stamp,
    is_stale,
    select_stale_feature_ids,
    upsert_stamps,
)
from tests.integration.conftest import as_dagster_runtime

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

VERSION = "dv1-" + "a" * 32
CURRENT = "dd1-" + "1" * 32
OLD = "dd1-" + "0" * 32
CURRENT_REF = DatasetRef(version_token=VERSION, data_token=CURRENT)
OLD_REF = DatasetRef(version_token=VERSION, data_token=OLD)

_INSERT_FEATURE = text(
    """
    INSERT INTO feature.features (
        feature_id, kind, name, category, lifecycle_state,
        publication_state, quality_state
    ) VALUES (
        CAST(:feature_id AS uuid), 'place', :name, '99000000',
        :lifecycle_state, :publication_state, 'valid'
    )
    """
)

_DATASET_IDS = text(
    "SELECT provider_dataset_id FROM provider_sync.provider_datasets "
    "ORDER BY provider_dataset_id LIMIT 2"
)

_INSERT_ENTITY = text(
    """
    INSERT INTO provider_sync.source_entities (
        source_entity_key, provider_dataset_id, source_entity_type, source_entity_id,
        first_seen_at, last_seen_at
    ) VALUES (:key, :dataset_id, 'stamp_test', :key, now(), now())
    """
)

_INSERT_LINK = text(
    """
    INSERT INTO provider_sync.source_links (
        feature_id, source_entity_key, source_role, match_method, confidence
    ) VALUES (CAST(:feature_id AS uuid), :key, :role, 'natural_key', 100)
    """
)

_INSERT_RAW_STAMP = text(
    """
    INSERT INTO feature.feature_geocode_stamps (
        feature_id, geo_version_token, geo_data_token, reverse_outcome
    ) VALUES (CAST(:feature_id AS uuid), :version_token, :data_token, :outcome)
    """
)


async def _feature(
    session: AsyncSession,
    *,
    dataset_id: int | None = None,
    role: str = "primary",
    retired: bool = False,
) -> str:
    feature_id = str(uuid.uuid4())
    await session.execute(
        _INSERT_FEATURE,
        {
            "feature_id": feature_id,
            "name": f"stamp-{feature_id[:8]}",
            "lifecycle_state": "retired" if retired else "active",
            "publication_state": "suppressed" if retired else "published",
        },
    )
    if dataset_id is not None:
        key = f"stamp-test:{feature_id}"
        await session.execute(_INSERT_ENTITY, {"key": key, "dataset_id": dataset_id})
        await session.execute(
            _INSERT_LINK, {"feature_id": feature_id, "key": key, "role": role}
        )
    return feature_id


async def _dataset_ids(session: AsyncSession) -> tuple[int, int]:
    rows = (await session.execute(_DATASET_IDS)).scalars().all()
    assert len(rows) == 2, "provider dataset seed가 둘 이상 있어야 한다"
    return int(rows[0]), int(rows[1])


@pytest.mark.parametrize("outcome", ["called", "geocoded", "not_called"])
@pytest.mark.parametrize(
    ("version_token", "data_token"),
    [(None, CURRENT), (VERSION, None), ("dv1-short", CURRENT), (VERSION, "dd1-" + "Z" * 32)],
)
async def test_null_or_malformed_tokens_are_rejected_for_every_outcome(
    migrated_session: AsyncSession,
    outcome: str,
    version_token: str | None,
    data_token: str | None,
) -> None:
    feature_id = await _feature(migrated_session)
    with pytest.raises((IntegrityError, DBAPIError)):
        async with migrated_session.begin_nested():
            await migrated_session.execute(
                _INSERT_RAW_STAMP,
                {
                    "feature_id": feature_id,
                    "version_token": version_token,
                    "data_token": data_token,
                    "outcome": outcome,
                },
            )


async def test_unknown_outcome_is_rejected(migrated_session: AsyncSession) -> None:
    feature_id = await _feature(migrated_session)
    with pytest.raises((IntegrityError, DBAPIError)):
        async with migrated_session.begin_nested():
            await migrated_session.execute(
                _INSERT_RAW_STAMP,
                {
                    "feature_id": feature_id,
                    "version_token": VERSION,
                    "data_token": CURRENT,
                    "outcome": "unavailable",
                },
            )


@pytest.mark.parametrize(
    "current", [None, DatasetRef(version_token=VERSION, data_token=None)]
)
async def test_no_current_token_writes_nothing(
    migrated_session: AsyncSession, current: DatasetRef | None
) -> None:
    feature_id = await _feature(migrated_session)
    written = await upsert_stamps(migrated_session, current=current, outcomes={feature_id: "called"})
    assert written == 0
    assert await get_stamp(migrated_session, feature_id) is None


async def test_upsert_overwrites_the_previous_stamp(migrated_session: AsyncSession) -> None:
    feature_id = await _feature(migrated_session)
    assert await upsert_stamps(migrated_session, current=OLD_REF, outcomes={feature_id: "called"}) == 1
    assert await upsert_stamps(
        migrated_session, current=CURRENT_REF, outcomes={feature_id: "geocoded"}
    ) == 1
    stamp = await get_stamp(migrated_session, feature_id)
    assert stamp is not None
    assert (stamp.geo_data_token, stamp.reverse_outcome) == (CURRENT, "geocoded")


async def _five_branches(session: AsyncSession, dataset_id: int) -> dict[str, str]:
    """스탬프 없음·not_called(옛)·geocoded(옛)·called(옛)·called(현재) 다섯 Feature."""
    features = {
        name: await _feature(session, dataset_id=dataset_id)
        for name in ("unstamped", "not_called_old", "geocoded_old", "called_old", "called_current")
    }
    await upsert_stamps(
        session,
        current=OLD_REF,
        outcomes={
            features["not_called_old"]: "not_called",
            features["geocoded_old"]: "geocoded",
            features["called_old"]: "called",
        },
    )
    await upsert_stamps(
        session, current=CURRENT_REF, outcomes={features["called_current"]: "called"}
    )
    return features


_EXPECTED_STALE = {
    "unstamped": True,
    "not_called_old": False,
    "geocoded_old": True,
    "called_old": True,
    "called_current": False,
}


async def test_is_stale_five_branches(migrated_session: AsyncSession) -> None:
    dataset_id, _ = await _dataset_ids(migrated_session)
    features = await _five_branches(migrated_session, dataset_id)
    observed = {
        name: await is_stale(migrated_session, feature_id, CURRENT)
        for name, feature_id in features.items()
    }
    assert observed == _EXPECTED_STALE


async def test_select_stale_matches_is_stale_and_scopes_to_the_dataset(
    migrated_session: AsyncSession,
) -> None:
    dataset_id, other_dataset_id = await _dataset_ids(migrated_session)
    features = await _five_branches(migrated_session, dataset_id)
    # 같은 dataset이지만 제외돼야 하는 것: 퇴역 Feature, primary가 아닌 링크.
    retired = await _feature(migrated_session, dataset_id=dataset_id, retired=True)
    enrichment_only = await _feature(migrated_session, dataset_id=dataset_id, role="enrichment")
    # 다른 dataset의 stale Feature.
    other = await _feature(migrated_session, dataset_id=other_dataset_id)

    mine = {*features.values(), retired, enrichment_only, other}
    # 공유 DB라 이 dataset에 다른 모듈의 Feature가 있을 수 있다 — 이 검사가 만든 것만 본다.
    selected = mine & set(
        await select_stale_feature_ids(
            migrated_session, CURRENT, provider_dataset_id=dataset_id, limit=100_000
        )
    )
    expected = {features[name] for name, stale in _EXPECTED_STALE.items() if stale}
    assert selected == expected

    limited = await select_stale_feature_ids(
        migrated_session, CURRENT, provider_dataset_id=dataset_id, limit=1
    )
    assert len(limited) == 1


async def test_no_current_token_means_zero_stale(migrated_session: AsyncSession) -> None:
    dataset_id, _ = await _dataset_ids(migrated_session)
    features = await _five_branches(migrated_session, dataset_id)
    assert await select_stale_feature_ids(
        migrated_session, None, provider_dataset_id=dataset_id, limit=1000
    ) == []
    for feature_id in features.values():
        assert await is_stale(migrated_session, feature_id, None) is False


async def test_runtime_role_can_write_and_read_stamps(migrated_session: AsyncSession) -> None:
    dataset_id, _ = await _dataset_ids(migrated_session)
    feature_id = await _feature(migrated_session, dataset_id=dataset_id)
    async with as_dagster_runtime(migrated_session) as runtime:
        assert await upsert_stamps(runtime, current=OLD_REF, outcomes={feature_id: "called"}) == 1
        assert await upsert_stamps(
            runtime, current=CURRENT_REF, outcomes={feature_id: "called"}
        ) == 1
        assert await is_stale(runtime, feature_id, CURRENT) is False
        assert feature_id in await select_stale_feature_ids(
            runtime, OLD, provider_dataset_id=dataset_id, limit=100_000
        )


async def test_deleting_the_feature_deletes_its_stamp(migrated_session: AsyncSession) -> None:
    feature_id = await _feature(migrated_session)
    await upsert_stamps(migrated_session, current=CURRENT_REF, outcomes={feature_id: "called"})
    await migrated_session.execute(
        text("DELETE FROM feature.features WHERE feature_id = CAST(:id AS uuid)"),
        {"id": feature_id},
    )
    assert await get_stamp(migrated_session, feature_id) is None
