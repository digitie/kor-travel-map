"""장소 속성 필터·코드(ADR-121 §7) — 실 PostGIS에서 읽기 경로 전부.

속성은 source link에서 유도한다: Feature에 걸린 ``primary``/``enrichment`` link의 원천 entity
(dataset, entity 유형)이 ``feature.dataset_place_attributes``에서 코드에 묶이면 그 Feature가
그 속성을 가진다. 여기서는 master Feature 셋에 MCST 목록 entity를 ``enrichment``로 직접 걸고
(붙임 엔진은 ``test_theme_attach_load.py``가 본다) 다음을 확인한다.

- 검색(bbox·q)·in-bounds(item·cluster)·주변·목록이 **AND** 의미로 거른다.
- 응답 행의 ``attribute_codes``가 정렬된 공개 코드다.
- ``secondary`` 같은 다른 역할의 link·묶이지 않은 entity 유형은 속성을 만들지 않는다.
- 읽기는 API runtime role(``ktm_feature_service``)로 돈다 — 권한 회귀를 본다.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from kortravelmap.infra import admin_feature_repo, feature_repo, place_attribute_repo
from tests.integration._feature_ids import feature_uuid
from tests.integration.conftest import as_api_runtime

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_FETCHED = datetime(2026, 11, 10, 3, 0, tzinfo=UTC)
_SIGNING_KEY = b"place-attribute-filter-integration-cursor-key-0001"
_MCST = "python-mcst-api"
_BARRIER_FREE_DATASET = "mcst_barrier_free_places_csv"
_PET_DATASET = "mcst_pet_friendly_culture_facilities_csv"
#: 다른 모듈의 seed와 겹치지 않는 빈 좌표대(부산 앞바다 쪽).
_LON, _LAT = 129.3311, 35.0123
_BBOX = (_LON - 0.01, _LAT - 0.01, _LON + 0.01, _LAT + 0.01)

_BOTH = "pa:both"  # 무장애 + 반려동물
_BARRIER_ONLY = "pa:barrier-only"
_NONE = "pa:none"  # 속성 link 없음(secondary 역할 link만)


async def _dataset_id(session: AsyncSession, dataset_key: str, provider: str = _MCST) -> int:
    return int(
        (
            await session.execute(
                text(
                    """
                    INSERT INTO provider_sync.provider_datasets (
                        provider, dataset_key, display_name, source_kind,
                        is_active, capabilities
                    )
                    SELECT :provider, :dataset_key, :dataset_key, 'system', true,
                           jsonb_build_object('schema_version', 1,
                                              'produces', '[]'::jsonb,
                                              'extensions', '{}'::jsonb)
                    ON CONFLICT (provider, dataset_key) DO UPDATE
                        SET display_name = provider_datasets.display_name
                    RETURNING provider_dataset_id
                    """
                ),
                {"provider": provider, "dataset_key": dataset_key},
            )
        ).scalar_one()
    )


async def _map_dataset(session: AsyncSession, dataset_key: str, code: str) -> int:
    """migration 446 seed가 없는 환경(빈 catalog)에서도 (dataset, culture_place) → 코드를 건다."""
    dataset_id = await _dataset_id(session, dataset_key)
    await session.execute(
        text(
            """
            INSERT INTO feature.dataset_place_attributes (
                provider_dataset_id, source_entity_type, attribute_code
            )
            VALUES (:dataset_id, 'culture_place', :code)
            ON CONFLICT DO NOTHING
            """
        ),
        {"dataset_id": dataset_id, "code": code},
    )
    return dataset_id


async def _insert_place(
    session: AsyncSession, *, label: str, name: str, east_m: float
) -> str:
    feature_id = feature_uuid(label)
    await session.execute(
        text(
            """
            INSERT INTO feature.features (
                feature_id, kind, name, category, coord,
                lifecycle_state, publication_state, quality_state, updated_at,
                sido_code, sigungu_code, legal_dong_code
            )
            VALUES (
                :feature_id, 'place', :name, '01040100',
                x_extension.ST_SetSRID(
                    x_extension.ST_MakePoint(
                        CAST(:lon AS double precision), CAST(:lat AS double precision)
                    ),
                    4326
                ),
                'active', 'published', 'valid', :updated_at,
                '26', '26440', '2644010100'
            )
            """
        ),
        {
            "feature_id": feature_id,
            "name": name,
            "lon": _LON + east_m / 91_000.0,
            "lat": _LAT,
            "updated_at": _FETCHED,
        },
    )
    return feature_id


async def _link(
    session: AsyncSession,
    *,
    feature_id: str,
    dataset_id: int,
    entity_id: str,
    role: str,
    entity_type: str = "culture_place",
) -> None:
    entity_key = f"pa-entity:{dataset_id}:{entity_type}:{entity_id}"
    await session.execute(
        text(
            """
            INSERT INTO provider_sync.source_entities (
                source_entity_key, provider_dataset_id, source_entity_type,
                source_entity_id, first_seen_at, last_seen_at
            )
            VALUES (:entity_key, :dataset_id, :entity_type, :entity_id, :ts, :ts)
            """
        ),
        {
            "entity_key": entity_key,
            "dataset_id": dataset_id,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "ts": _FETCHED,
        },
    )
    await session.execute(
        text(
            """
            INSERT INTO provider_sync.source_links (
                feature_id, source_entity_key, source_role, match_method, confidence
            )
            VALUES (:feature_id, :entity_key, :role, 'natural_key', 90)
            """
        ),
        {"feature_id": feature_id, "entity_key": entity_key, "role": role},
    )


async def _seed(session: AsyncSession) -> dict[str, str]:
    barrier = await _map_dataset(session, _BARRIER_FREE_DATASET, "barrier_free")
    pet = await _map_dataset(session, _PET_DATASET, "pet_friendly")
    base = await _dataset_id(session, "datagokr_museums", provider="data.go.kr-standard")
    ids = {
        _BOTH: await _insert_place(session, label=_BOTH, name="속성필터테스트박물관 가", east_m=0),
        _BARRIER_ONLY: await _insert_place(
            session, label=_BARRIER_ONLY, name="속성필터테스트박물관 나", east_m=40
        ),
        _NONE: await _insert_place(session, label=_NONE, name="속성필터테스트박물관 다", east_m=80),
    }
    for label, feature_id in ids.items():
        # master의 primary link(비MCST) — 속성과 무관하다.
        await _link(
            session, feature_id=feature_id, dataset_id=base, entity_id=label,
            role="primary", entity_type="museum",
        )
    await _link(
        session, feature_id=ids[_BOTH], dataset_id=barrier, entity_id="bf-1", role="enrichment"
    )
    await _link(
        session, feature_id=ids[_BOTH], dataset_id=pet, entity_id="pet-1", role="enrichment"
    )
    await _link(
        session, feature_id=ids[_BARRIER_ONLY], dataset_id=barrier, entity_id="bf-2",
        role="enrichment",
    )
    # 속성을 만들지 않는 link — 다른 역할, 묶이지 않은 entity 유형.
    await _link(
        session, feature_id=ids[_NONE], dataset_id=pet, entity_id="pet-3", role="media"
    )
    await _link(
        session, feature_id=ids[_NONE], dataset_id=barrier, entity_id="bf-3",
        role="enrichment", entity_type="unmapped_type",
    )
    await session.flush()
    return ids


def _ours(ids: dict[str, str], found: list[str]) -> set[str]:
    reverse = {value: key for key, value in ids.items()}
    return {reverse[value] for value in found if value in reverse}


async def test_catalog_and_feature_attributes_follow_links(
    migrated_session: AsyncSession,
) -> None:
    session = migrated_session
    ids = await _seed(session)
    async with session.begin_nested(), as_api_runtime(session):
        catalog = await place_attribute_repo.list_place_attributes(session, public_only=True)
        both = await place_attribute_repo.list_feature_place_attributes(session, ids[_BOTH])
        none = await place_attribute_repo.list_feature_place_attributes(session, ids[_NONE])
    codes = [item.code for item in catalog]
    assert {"barrier_free", "pet_friendly"} <= set(codes)
    # catalog는 sort_order 순이다(반려동물 10 < 무장애 30).
    assert codes.index("pet_friendly") < codes.index("barrier_free")
    assert [item.code for item in both] == ["pet_friendly", "barrier_free"]
    assert none == ()
    digest = place_attribute_repo.place_attribute_codes_digest([item.code for item in both])
    assert digest is not None
    assert len(digest) == 16


async def test_bbox_and_cluster_filter_with_and_semantics(
    migrated_session: AsyncSession,
) -> None:
    session = migrated_session
    ids = await _seed(session)
    min_lon, min_lat, max_lon, max_lat = _BBOX
    bbox = {"min_lon": min_lon, "min_lat": min_lat, "max_lon": max_lon, "max_lat": max_lat}
    async with session.begin_nested(), as_api_runtime(session):
        unfiltered = await feature_repo.features_in_bbox(session, **bbox, limit=500)
        barrier = await feature_repo.features_in_bbox(
            session, **bbox, attributes=["barrier_free"], limit=500
        )
        both = await feature_repo.features_in_bbox(
            session, **bbox, attributes=["pet_friendly", "barrier_free"], limit=500
        )
        with_geometry = await feature_repo.features_in_bbox(
            session, **bbox, attributes=["barrier_free"], include_geometry=True, limit=500
        )
        clusters = await feature_repo.cluster_features_in_bbox(
            session, **bbox, cluster_unit="sigungu", attributes=["barrier_free"]
        )
        both_clusters = await feature_repo.cluster_features_in_bbox(
            session, **bbox, cluster_unit="sigungu",
            attributes=["barrier_free", "pet_friendly"],
        )
    assert _ours(ids, [str(row["feature_id"]) for row in unfiltered]) == {
        _BOTH, _BARRIER_ONLY, _NONE,
    }
    assert _ours(ids, [str(row["feature_id"]) for row in barrier]) == {_BOTH, _BARRIER_ONLY}
    assert _ours(ids, [str(row["feature_id"]) for row in both]) == {_BOTH}
    assert _ours(ids, [str(row["feature_id"]) for row in with_geometry]) == {
        _BOTH, _BARRIER_ONLY,
    }
    codes = {str(row["feature_id"]): list(row["attribute_codes"]) for row in unfiltered}
    assert codes[ids[_BOTH]] == ["barrier_free", "pet_friendly"]
    assert codes[ids[_BARRIER_ONLY]] == ["barrier_free"]
    assert codes[ids[_NONE]] == []
    by_key = {row["cluster_key"]: row["feature_count"] for row in clusters}
    assert by_key.get("26440", 0) >= 2
    both_by_key = {row["cluster_key"]: row["feature_count"] for row in both_clusters}
    assert both_by_key.get("26440", 0) == by_key["26440"] - 1


async def test_search_filters_with_and_semantics_and_codes(
    migrated_session: AsyncSession,
) -> None:
    session = migrated_session
    ids = await _seed(session)
    async with session.begin_nested(), as_api_runtime(session):
        bbox_page = await feature_repo.search_features(
            session, bbox=_BBOX, attributes=["barrier_free"], page_size=50,
            include_total=True, cursor_signing_key=_SIGNING_KEY,
        )
        q_page = await feature_repo.search_features(
            session, q="속성필터테스트박물관", attributes=["barrier_free", "pet_friendly"],
            page_size=50, include_total=True, cursor_signing_key=_SIGNING_KEY,
        )
        q_all = await feature_repo.search_features(
            session, q="속성필터테스트박물관", page_size=50, cursor_signing_key=_SIGNING_KEY,
        )
    assert _ours(ids, [item.feature_id for item in bbox_page.items]) == {_BOTH, _BARRIER_ONLY}
    assert bbox_page.total_count is not None
    assert bbox_page.total_count >= 2
    assert _ours(ids, [item.feature_id for item in q_page.items]) == {_BOTH}
    assert q_page.total_count == 1
    both_row = next(item for item in q_page.items if item.feature_id == ids[_BOTH])
    assert both_row.attribute_codes == ("barrier_free", "pet_friendly")
    assert _ours(ids, [item.feature_id for item in q_all.items]) == {
        _BOTH, _BARRIER_ONLY, _NONE,
    }


async def test_search_cursor_binds_the_attribute_filter(
    migrated_session: AsyncSession,
) -> None:
    """필터가 있는 cursor를 필터 없이 이어 쓰면 CURSOR_QUERY_MISMATCH다."""
    from kortravelmap.core.exceptions import FeatureSearchCursorQueryMismatchError

    session = migrated_session
    await _seed(session)
    async with session.begin_nested(), as_api_runtime(session):
        first = await feature_repo.search_features(
            session, bbox=_BBOX, attributes=["barrier_free"], page_size=1,
            cursor_signing_key=_SIGNING_KEY,
        )
        assert first.next_cursor is not None
        second = await feature_repo.search_features(
            session, bbox=_BBOX, attributes=["barrier_free"], page_size=1,
            cursor=first.next_cursor, cursor_signing_key=_SIGNING_KEY,
        )
        assert second.items
        with pytest.raises(FeatureSearchCursorQueryMismatchError):
            await feature_repo.search_features(
                session, bbox=_BBOX, page_size=1, cursor=first.next_cursor,
                cursor_signing_key=_SIGNING_KEY,
            )


async def test_nearby_filters_with_and_semantics_and_codes(
    migrated_session: AsyncSession,
) -> None:
    session = migrated_session
    ids = await _seed(session)
    async with session.begin_nested(), as_api_runtime(session):
        page = await feature_repo.features_nearby(
            session, lon=_LON, lat=_LAT, radius_m=500, attributes=["barrier_free"], limit=50
        )
        both = await feature_repo.features_nearby(
            session, lon=_LON, lat=_LAT, radius_m=500,
            attributes=["barrier_free", "pet_friendly"], limit=50,
        )
        by_name = await feature_repo.features_nearby(
            session, lon=_LON, lat=_LAT, radius_m=500, attributes=["pet_friendly"],
            sort="name", limit=50,
        )
    assert _ours(ids, [item.feature_id for item in page.items]) == {_BOTH, _BARRIER_ONLY}
    assert _ours(ids, [item.feature_id for item in both.items]) == {_BOTH}
    assert _ours(ids, [item.feature_id for item in by_name.items]) == {_BOTH}
    row = next(item for item in page.items if item.feature_id == ids[_BARRIER_ONLY])
    assert row.attribute_codes == ("barrier_free",)


async def test_admin_reads_apply_the_same_filter(
    migrated_session: AsyncSession,
) -> None:
    session = migrated_session
    ids = await _seed(session)
    min_lon, min_lat, max_lon, max_lat = _BBOX
    async with session.begin_nested(), as_api_runtime(session):
        items = await admin_feature_repo.admin_features_in_bbox(
            session, min_lon=min_lon, min_lat=min_lat, max_lon=max_lon, max_lat=max_lat,
            attributes=["barrier_free", "pet_friendly"],
        )
        listed = await admin_feature_repo.list_admin_features(
            session, q="속성필터테스트박물관", search_scope="feature",
            attributes=["barrier_free"], page_size=50,
        )
    assert _ours(ids, [str(row["feature_id"]) for row in items]) == {_BOTH}
    codes = {str(row["feature_id"]): list(row["attribute_codes"]) for row in items}
    assert codes[ids[_BOTH]] == ["barrier_free", "pet_friendly"]
    assert _ours(ids, [item.feature_id for item in listed.items]) == {_BOTH, _BARRIER_ONLY}
