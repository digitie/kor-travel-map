"""``test_feature_repo_primary_source`` — ``get_primary_source_detail`` 결정성 검증.

issue #509 Problem B 회귀. 같은 안정 식별자에 inactive+deleted_at 구 feature와
active 신 feature가 둘 다 primary link로 남을 수 있다(re-key 정리 직전/직후, 혹은
0029 demote 누락 시). 구 ``_GET_PRIMARY_SOURCE_DETAIL_SQL``은 ``deleted_at`` 필터도
ORDER BY도 없는 ``LIMIT 1``이라 비활성 구 feature를 비결정적으로 반환할 수 있었다.

하든 후: ``f.deleted_at IS NULL`` + 결정적 ``ORDER BY (status='active') DESC,
imported_at DESC NULLS LAST, feature_id`` → 항상 active 신 feature 반환(반복 실행해도
동일).

Docker / testcontainers 미설치 환경에서는 conftest fixture가 ``pytest.skip``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from kortravelmap.infra.feature_repo import get_primary_source_detail

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
    status: str,
    deleted: bool,
) -> None:
    await session.execute(
        text(
            "INSERT INTO feature.features "
            "(feature_id, kind, name, category, status, deleted_at) "
            "VALUES (:fid, 'place', :name, :category, :status, "
            " CASE WHEN :deleted THEN now() ELSE NULL END)"
        ),
        {
            "fid": feature_id,
            "name": "월정리해수욕장",
            "category": category,
            "status": status,
            "deleted": deleted,
        },
    )


async def _insert_source_record(
    session: AsyncSession, *, key: str, payload_hash: str
) -> None:
    await session.execute(
        text(
            "INSERT INTO provider_sync.source_records "
            "(source_record_key, provider, dataset_key, source_entity_type, "
            " source_entity_id, raw_payload_hash, raw_data, fetched_at) "
            "VALUES (:key, :provider, :dataset_key, :entity_type, :entity_id, "
            " :payload_hash, :raw_data, now())"
        ),
        {
            "key": key,
            "provider": _PROVIDER,
            "dataset_key": _DATASET,
            "entity_type": _ENTITY_TYPE,
            "entity_id": _ENTITY_ID,
            "payload_hash": payload_hash,
            "raw_data": f'{{"key": "{key}"}}',
        },
    )


async def _link_primary(
    session: AsyncSession, *, feature_id: str, record_key: str
) -> None:
    await session.execute(
        text(
            "INSERT INTO provider_sync.source_links "
            "(feature_id, source_record_key, source_role, match_method, "
            " confidence, is_primary_source) "
            "VALUES (:fid, :key, 'primary', 'khoa_beach', 100, true)"
        ),
        {"fid": feature_id, "key": record_key},
    )


async def test_primary_source_detail_prefers_active_over_inactive(
    migrated_session: AsyncSession,
) -> None:
    """C: inactive-old + active-new 둘 다 primary link → 항상 active 반환(반복).

    구 feature는 ``deleted_at`` 가드로 제외되고, 동률 방어로 ORDER BY가 active를
    우선한다. 비결정성 제거를 보이기 위해 여러 번 실행해 동일 결과를 단언한다.
    """
    session = migrated_session

    # 구: inactive + deleted_at. (re-key cleanup 후 primary link가 아직 강등 안 된 상태)
    await _insert_source_record(session, key="sr_old", payload_hash="sha1:OLD")
    await _insert_feature(
        session,
        feature_id="f_old",
        category="01020300",
        status="inactive",
        deleted=True,
    )
    await _link_primary(session, feature_id="f_old", record_key="sr_old")

    # 신: active. 다른 raw_payload_hash → 다른 source_record_key(같은 안정 식별자).
    await _insert_source_record(session, key="sr_new", payload_hash="sha1:NEW")
    await _insert_feature(
        session,
        feature_id="f_new",
        category="01050100",
        status="active",
        deleted=False,
    )
    await _link_primary(session, feature_id="f_new", record_key="sr_new")
    await session.flush()

    # 반복 실행 — 항상 active 신 feature를 결정적으로 반환.
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
        assert detail["status"] == "active"
        assert detail["category"] == "01050100"


async def test_primary_source_detail_skips_soft_deleted_only(
    migrated_session: AsyncSession,
) -> None:
    """active 신 feature가 없고 inactive+deleted 구 feature만 남으면 None 반환
    (deleted_at 가드 — 비활성 구 feature를 detail로 노출하지 않는다)."""
    session = migrated_session

    await _insert_source_record(session, key="sr_only_old", payload_hash="sha1:OLD")
    await _insert_feature(
        session,
        feature_id="f_only_old",
        category="01020300",
        status="inactive",
        deleted=True,
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
