"""``test_feature_repo_primary_source`` — ``get_primary_source_detail`` 결정성 검증.

같은 안정 식별자에 retired 구 Feature와 public 신 Feature가 둘 다 primary link로
남을 수 있다. 이 reader는 ``feature.public_features`` 단일 projection을 조인하고
head/record 순서로 정렬하므로, 공개 가능한 최신 Feature만 결정적으로 반환한다.

Docker / testcontainers 미설치 환경에서는 conftest fixture가 ``pytest.skip``.
"""

from __future__ import annotations

from hashlib import md5
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from kortravelmap.infra.feature_repo import get_primary_source_detail
from tests.integration._subtype_seed import seed_feature_subtype

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


pytestmark = pytest.mark.integration

_PROVIDER = "python-khoa-api"
_DATASET = "khoa_beaches"
_ENTITY_TYPE = "beach"
_ENTITY_ID = "월정리::제주::구좌읍"


async def _insert_feature(
    session: AsyncSession,
    *,
    feature_id: str,
    category: str,
    lifecycle_state: str,
    publication_state: str = "published",
    quality_state: str = "valid",
) -> None:
    await session.execute(
        text(
            "INSERT INTO feature.features "
            "(feature_id, kind, name, category, lifecycle_state, "
            " publication_state, quality_state) "
            "VALUES (:fid, 'place', :name, :category, :lifecycle_state, "
            " :publication_state, :quality_state)"
        ),
        {
            "fid": feature_id,
            "name": "월정리해수욕장",
            "category": category,
            "lifecycle_state": lifecycle_state,
            "publication_state": publication_state,
            "quality_state": quality_state,
        },
    )
    await seed_feature_subtype(session, feature_id=feature_id, kind="place")


async def _insert_source_record(
    session: AsyncSession, *, key: str, payload_hash: str, observed_seconds: int = 0
) -> None:
    """entity + immutable record + 현재 record를 가리키는 head를 적재한다.

    T-VN-33: entity 소유는 ``provider_dataset_id``로, 현재 record 포인터는
    ``source_entity_heads``로 옮겼다. record는 payload 이력이라 갱신하지 않고
    새 row가 쌓이며, head만 앞으로 전진한다.
    """
    entity_key = "se_khoa_beach_woljeongri"
    await session.execute(
        text(
            "INSERT INTO provider_sync.source_entities "
            "(source_entity_key, provider_dataset_id, source_entity_type, "
            " source_entity_id, first_seen_at, last_seen_at) "
            "SELECT :entity_key, provider_dataset_id, :entity_type, "
            " :entity_id, now(), now() "
            "FROM provider_sync.provider_datasets "
            "WHERE provider = :provider AND dataset_key = :dataset_key "
            "ON CONFLICT (source_entity_key) DO UPDATE SET last_seen_at = now()"
        ),
        {
            "entity_key": entity_key,
            "provider": _PROVIDER,
            "dataset_key": _DATASET,
            "entity_type": _ENTITY_TYPE,
            "entity_id": _ENTITY_ID,
        },
    )
    await session.execute(
        text(
            "INSERT INTO provider_sync.source_records "
            "(source_record_key, source_entity_key, raw_payload_hash, raw_data, "
            " fetched_at, imported_at) "
            "VALUES (:key, :entity_key, :payload_hash, :raw_data, now(), now())"
        ),
        {
            "key": key,
            "entity_key": entity_key,
            "payload_hash": payload_hash,
            "raw_data": f'{{"key": "{key}"}}',
        },
    )
    await session.execute(
        text(
            "INSERT INTO provider_sync.source_entity_heads "
            "(source_entity_key, current_source_record_key, observed_at) "
            "VALUES (:entity_key, :key, now() + make_interval(secs => :secs)) "
            "ON CONFLICT (source_entity_key) DO UPDATE SET "
            " current_source_record_key = EXCLUDED.current_source_record_key, "
            " observed_at = EXCLUDED.observed_at"
        ),
        {"key": key, "entity_key": entity_key, "secs": observed_seconds},
    )


async def _link_primary(
    session: AsyncSession, *, feature_id: str, record_key: str
) -> None:
    await session.execute(
        text(
            "INSERT INTO provider_sync.source_links "
            "(feature_id, source_entity_key, source_role, match_method, confidence) "
            "SELECT :fid, source_entity_key, 'primary', 'khoa_beach', 100 "
            "FROM provider_sync.source_records WHERE source_record_key = :key"
        ),
        {"fid": feature_id, "key": record_key},
    )


async def test_primary_source_detail_returns_latest_public_feature(
    migrated_session: AsyncSession,
) -> None:
    """retired-old + active/public/new 둘 다 primary link면 새 행만 반환한다."""
    session = migrated_session

    # 구 행은 primary link가 남아 있어도 public projection 밖이다.
    await _insert_source_record(
        session, key="sr_old", payload_hash=md5(b"OLD").hexdigest()
    )
    await _insert_feature(
        session,
        feature_id="f_old",
        category="01020300",
        lifecycle_state="retired",
        publication_state="suppressed",
    )
    await _link_primary(session, feature_id="f_old", record_key="sr_old")

    # 신: active. 다른 raw_payload_hash → 다른 source_record_key(같은 안정 식별자).
    await _insert_source_record(
        session,
        key="sr_new",
        payload_hash=md5(b"NEW").hexdigest(),
        observed_seconds=1,
    )
    await _insert_feature(
        session,
        feature_id="f_new",
        category="01050100",
        lifecycle_state="active",
    )
    await _link_primary(session, feature_id="f_new", record_key="sr_new")
    await session.flush()

    # 반복 실행 — 항상 공개 가능 신 Feature를 결정적으로 반환.
    for _ in range(5):
        detail = await get_primary_source_detail(
            session,
            provider=_PROVIDER,
            dataset_key=_DATASET,
            source_entity_type=_ENTITY_TYPE,
            source_entity_id=_ENTITY_ID,
        )
        assert detail is not None
        assert detail["feature_id"] == "f_new"
        assert detail["lifecycle_state"] == "active"
        assert detail["publication_state"] == "published"
        assert detail["quality_state"] == "valid"
        assert detail["category"] == "01050100"


async def test_primary_source_detail_skips_nonpublic_feature_only(
    migrated_session: AsyncSession,
) -> None:
    """공개 가능 행이 없으면 retired source link를 detail로 노출하지 않는다."""
    session = migrated_session

    await _insert_source_record(
        session, key="sr_only_old", payload_hash=md5(b"OLD").hexdigest()
    )
    await _insert_feature(
        session,
        feature_id="f_only_old",
        category="01020300",
        lifecycle_state="retired",
        publication_state="suppressed",
    )
    await _link_primary(session, feature_id="f_only_old", record_key="sr_only_old")
    await session.flush()

    detail = await get_primary_source_detail(
        session,
        provider=_PROVIDER,
        dataset_key=_DATASET,
        source_entity_type=_ENTITY_TYPE,
        source_entity_id=_ENTITY_ID,
    )
    assert detail is None
