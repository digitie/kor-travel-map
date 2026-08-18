"""``feature.curated_*`` repository 통합 테스트 (T-223c-1)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from kortravelmap.dto import Address, Coordinate
from kortravelmap.infra import curated_repo, feature_repo
from kortravelmap.providers.datagokr_file_data import file_data_rows_to_bundles
from kortravelmap.providers.kor_travel_concierge import (
    DATASET_KEY_YOUTUBE_PLACE_CANDIDATES,
    KOR_TRAVEL_CONCIERGE_PROVIDER_NAME,
    kor_travel_concierge_items_to_bundles,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_KST = timezone(timedelta(hours=9))
_FETCHED = datetime(2026, 6, 12, 18, 0, tzinfo=_KST)
_EXPANDED_THEME_SLUGS = {
    "seasonal-spring-blossom",
    "seasonal-summer-coast",
    "seasonal-autumn-foliage",
    "seasonal-winter-snow",
    "region-seoul-capital",
    "region-busan-coast",
    "region-jeju-island",
    "region-gangwon-nature",
    "region-jeolla-food",
    "region-gyeongju-history",
}


async def _reverse(_coord: Coordinate) -> Address:
    return Address(
        bjd_code="1114016200",
        sido_code="11",
        sigungu_code="11140",
        sido_name="서울특별시",
        sigungu_name="중구",
    )


async def _load_seoul_bookstore(session: AsyncSession) -> str:
    [bundle] = await file_data_rows_to_bundles(
        [
            {
                "책방명": "통합테스트 헌책방",
                "주소": "서울특별시 중구 청계천로 274",
                "전화번호": "02-2266-1234",
                "책방구분명": "헌책방",
                "홈페이지": "https://example.test/book",
                "위도": "37.568533",
                "경도": "127.007754",
            }
        ],
        dataset_key="datagokr_seoul_bookstores",
        fetched_at=_FETCHED,
        reverse_geocoder=_reverse,
    )
    await feature_repo.load_bundle(session, bundle)
    await session.flush()
    return bundle.feature.feature_id


async def _load_concierge_place(session: AsyncSession) -> str:
    [bundle] = await kor_travel_concierge_items_to_bundles(
        [
            {
                "export_id": "ytpc_curated_1",
                "candidate_id": "curated-1",
                "operation": "upsert",
                "place": {
                    "name": "월정리 해변",
                    "description": "제주 동쪽 해변",
                    "category_label": "해변",
                    "category_code_suggestion": "01050100",
                    "longitude": 126.7958,
                    "latitude": 33.5563,
                    "address": {
                        "official_address": "제주특별자치도 제주시 구좌읍 월정리",
                        "road_address": "제주특별자치도 제주시 구좌읍 해맞이해안로",
                        "legal_dong_code": None,
                        "sido_code": None,
                        "sigungu_code": None,
                    },
                },
                "youtube": {
                    "source_title": "제주 동쪽 영상 묶음",
                    "video_id": "video-curated-1",
                    "video_url": "https://www.youtube.com/watch?v=video-curated-1",
                    "video_title": "제주 동쪽 여행",
                    "channel_id": "channel-curated-1",
                    "channel_title": "제주 여행 채널",
                    "playlist_id": "playlist-curated-1",
                    "playlist_title": "제주 동쪽 코스",
                },
                "evidence": {"confidence_score": 0.91},
                "source_record": {
                    "provider": KOR_TRAVEL_CONCIERGE_PROVIDER_NAME,
                    "dataset_key": DATASET_KEY_YOUTUBE_PLACE_CANDIDATES,
                    "source_entity_type": "extracted_place_candidate",
                    "source_entity_id": "curated-1",
                    "raw_payload_hash": "sha256:curated-1",
                },
            }
        ],
        fetched_at=_FETCHED,
    )
    await feature_repo.load_bundle(session, bundle)
    await session.flush()
    return bundle.feature.feature_id


async def _curated_source_for_catalog_display(
    session: AsyncSession,
    *,
    provider: str,
    dataset_key: str,
) -> curated_repo.CuratedSource:
    """표기용 pair는 seed catalog projection을 고를 때만 사용한다."""
    sources = await curated_repo.list_curated_sources(session, limit=500)
    return next(
        source
        for source in sources
        if source.provider == provider and source.dataset_key == dataset_key
    )



async def _seed_legacy_curated_row(
    session: AsyncSession,
    *,
    theme_id: str,
    feature_id: str,
    source_id: str,
    curation_status: str = "curated",
    selected_by: str | None = "pytest",
    rank_score: float = 0.0,
    display_title: str | None = None,
) -> str:
    """legacy `curated_features` row를 **테스트 fixture로만** 심는다.

    T-VN-40A fence 뒤로 `curated_repo.create_curated_feature`는 static 층에서 막힌다.
    그런데 이 파일의 read 테스트(`list_curated_features` 계열)는 legacy row가 있어야
    돌고, soak 동안 legacy를 읽어 canonical과 대조하는 경로라 살아 있어야 한다.

    이 helper는 그 fence를 **우회하는 것이 아니다** — 우회하려면 앱 코드가 raw SQL로
    쓰면 되겠지만 그건 ACL 층(`runtime_privileges`)이 막는다. 여기서 되는 이유는
    `migrated_session`이 테스트 owner role이기 때문이고, 그것이 곧 "앱은 못 쓰고
    테스트만 심을 수 있다"는 fence의 의도다.

    ⚠️ 이 helper를 앱 코드나 스크립트로 옮기지 마라. 옮기는 순간 fence가 뚫린 것이다.
    """
    row = await session.execute(
        text(
            """
            INSERT INTO feature.curated_features (
                theme_id, feature_id, source_id, curation_status,
                selection_origin, selected_by, selected_at,
                rank_score, display_title, curation_relation, reuse_policy,
                metadata, updated_at
            ) VALUES (
                CAST(:theme_id AS uuid), :feature_id, CAST(:source_id AS uuid),
                :curation_status, 'admin', CAST(:selected_by AS text),
                CASE WHEN CAST(:selected_by AS text) IS NULL THEN NULL ELSE now() END,
                CAST(:rank_score AS numeric), CAST(:display_title AS text),
                'nearby_option', 'manual_review',
                '{}'::jsonb, now()
            )
            RETURNING curated_feature_id::text
            """
        ),
        {
            "theme_id": theme_id,
            "feature_id": feature_id,
            "source_id": source_id,
            "curation_status": curation_status,
            "selected_by": selected_by,
            "rank_score": rank_score,
            "display_title": display_title,
        },
    )
    return str(row.scalar_one())


async def test_seeded_theme_sets_include_seasonal_and_regional_expansion(
    migrated_session: AsyncSession,
) -> None:
    themes = await curated_repo.list_curated_themes(migrated_session, limit=50)
    by_slug = {theme.theme_slug: theme for theme in themes}

    assert len(themes) >= 18
    assert set(by_slug) >= _EXPANDED_THEME_SLUGS
    assert {by_slug[slug].theme_group for slug in _EXPANDED_THEME_SLUGS} == {
        "regional",
        "seasonal",
    }
    assert {by_slug[slug].visibility for slug in _EXPANDED_THEME_SLUGS} == {
        "public"
    }






async def test_curated_uuid_defaults_are_schema_qualified(
    migrated_session: AsyncSession,
) -> None:
    rows = (
        await migrated_session.execute(
            text(
                """
                SELECT
                    c.relname AS table_name,
                    a.attname AS column_name,
                    pg_get_expr(d.adbin, d.adrelid) AS default_expr
                FROM pg_attribute AS a
                JOIN pg_class AS c ON c.oid = a.attrelid
                JOIN pg_namespace AS n ON n.oid = c.relnamespace
                JOIN pg_attrdef AS d
                  ON d.adrelid = a.attrelid
                 AND d.adnum = a.attnum
                WHERE n.nspname = 'feature'
                  AND c.relname IN (
                    'curated_themes',
                    'curated_sources',
                    'curated_source_rules',
                    'curated_features'
                  )
                """
            )
        )
    ).mappings().all()
    defaults = {
        (str(row["table_name"]), str(row["column_name"])): str(row["default_expr"])
        for row in rows
        if str(row["column_name"]).endswith("_id")
    }

    assert defaults == {
        ("curated_themes", "theme_id"): "x_extension.gen_random_uuid()",
        ("curated_sources", "source_id"): "x_extension.gen_random_uuid()",
        ("curated_source_rules", "rule_id"): "x_extension.gen_random_uuid()",
        ("curated_features", "curated_feature_id"): "x_extension.gen_random_uuid()",
    }


async def test_manual_curated_feature_writes_are_fenced(
    migrated_session: AsyncSession,
) -> None:
    """T-VN-40A — legacy `curated_features` CRUD는 static fence에서 막힌다.

    원래 이 테스트는 legacy create/patch/archive가 **동작한다**를 검증했다. fence 후에는
    반대다. 세 write 함수 전부가 DB에 닿기 전에 `LegacyWriteFenceError`를 던져야 한다.
    """
    from kortravelmap.infra.legacy_write_fence import LegacyWriteFenceError

    feature_id = await _load_seoul_bookstore(migrated_session)
    themes = await curated_repo.list_curated_themes(migrated_session, limit=50)
    theme = next(item for item in themes if item.theme_group == "books")
    source = await _curated_source_for_catalog_display(
        migrated_session,
        provider="python-datagokr-api",
        dataset_key="datagokr_seoul_bookstores",
    )
    theme_id = theme.theme_id
    with pytest.raises(LegacyWriteFenceError):
        await curated_repo.create_curated_feature(
            migrated_session,
            theme_id=theme_id,
            feature_id=feature_id,
            source_id=source.source_id,
            curation_status="curated",
            selected_by="pytest",
        )
    with pytest.raises(LegacyWriteFenceError):
        await curated_repo.update_curated_feature(
            migrated_session,
            curated_feature_id="00000000-0000-0000-0000-000000000001",
            updates={"reuse_policy": "allowed"},
            actor="fence-test",
        )
    with pytest.raises(LegacyWriteFenceError):
        await curated_repo.set_curated_feature_status(
            migrated_session,
            curated_feature_id="00000000-0000-0000-0000-000000000001",
            curation_status="rejected",
            actor="fence-test",
        )
    with pytest.raises(LegacyWriteFenceError):
        await curated_repo.archive_curated_feature(
            migrated_session,
            curated_feature_id="00000000-0000-0000-0000-000000000001",
            actor="fence-test",
        )
    # static 층이 먼저 잡으므로 DB에 row가 생기지 않았어야 한다.
    count = (
        await migrated_session.execute(
            text("SELECT count(*) FROM feature.curated_features WHERE theme_id = CAST(:t AS uuid)"),
            {"t": theme_id},
        )
    ).scalar_one()
    assert count == 0

async def test_list_curated_features_distinct_by_feature_dedups_cross_theme(
    migrated_session: AsyncSession,
) -> None:
    """같은 물리 feature가 여러 테마로 큐레이션되면 기본 목록엔 테마 수만큼 행이 나오지만,
    distinct_by_feature=True(지도 경로)면 rank_score 최고 큐레이션 1건만 반환한다."""
    feature_id = await _load_seoul_bookstore(migrated_session)
    themes = await curated_repo.list_curated_themes(migrated_session, limit=50)
    theme_a = themes[0]
    theme_b = next(item for item in themes if item.theme_id != theme_a.theme_id)
    source = await _curated_source_for_catalog_display(
        migrated_session,
        provider="python-datagokr-api",
        dataset_key="datagokr_seoul_bookstores",
    )
    await _seed_legacy_curated_row(
        migrated_session,
        theme_id=theme_a.theme_id,
        feature_id=feature_id,
        source_id=source.source_id,
        rank_score=10.0,
    )
    best_id = await _seed_legacy_curated_row(
        migrated_session,
        theme_id=theme_b.theme_id,
        feature_id=feature_id,
        source_id=source.source_id,
        rank_score=90.0,
    )

    # 기본(per-curation): 같은 feature_id가 테마 수(2)만큼 반환된다 — 지도 중복의 근원.
    full = await curated_repo.list_curated_features(
        migrated_session, curation_status="curated", page_size=100
    )
    assert [item.feature_id for item in full.items].count(feature_id) == 2

    # distinct_by_feature: 물리 feature당 1행, rank_score 최고(best) 유지.
    deduped = await curated_repo.list_curated_features(
        migrated_session,
        curation_status="curated",
        page_size=100,
        distinct_by_feature=True,
    )
    kept = [item for item in deduped.items if item.feature_id == feature_id]
    assert len(kept) == 1
    assert kept[0].curated_feature_id == best_id
    dedup_feature_ids = [item.feature_id for item in deduped.items]
    assert len(dedup_feature_ids) == len(set(dedup_feature_ids))


async def test_list_curated_features_display_titles_multi_filter(
    migrated_session: AsyncSession,
) -> None:
    """display_titles(멀티) 필터는 지정한 제목 집합만 반환한다(큐레이션 관리 title 필터)."""
    feature_id = await _load_seoul_bookstore(migrated_session)
    themes = await curated_repo.list_curated_themes(migrated_session, limit=50)
    source = await _curated_source_for_catalog_display(
        migrated_session,
        provider="python-datagokr-api",
        dataset_key="datagokr_seoul_bookstores",
    )
    await _seed_legacy_curated_row(
        migrated_session,
        theme_id=themes[0].theme_id,
        feature_id=feature_id,
        source_id=source.source_id,
        display_title="가을 책방",
    )
    await _seed_legacy_curated_row(
        migrated_session,
        theme_id=themes[1].theme_id,
        feature_id=feature_id,
        source_id=source.source_id,
        display_title="겨울 책방",
    )

    only_fall = await curated_repo.list_curated_features(
        migrated_session, curation_status="curated", display_titles=["가을 책방"]
    )
    assert {item.display_title for item in only_fall.items} == {"가을 책방"}

    both = await curated_repo.list_curated_features(
        migrated_session,
        curation_status="curated",
        display_titles=["가을 책방", "겨울 책방"],
    )
    assert {item.display_title for item in both.items} == {"가을 책방", "겨울 책방"}


async def _load_concierge_place_channel(
    session: AsyncSession, *, candidate_id: str, channel_id: str, name: str
) -> str:
    """channel_id를 지정한 concierge youtube 후보 place를 적재하고 feature_id 반환."""
    [bundle] = await kor_travel_concierge_items_to_bundles(
        [
            {
                "export_id": f"ytpc_{candidate_id}",
                "candidate_id": candidate_id,
                "operation": "upsert",
                "place": {
                    "name": name,
                    "category_label": "해변",
                    "category_code_suggestion": "01050100",
                    "longitude": 126.79,
                    "latitude": 33.55,
                    "address": {
                        "official_address": "제주특별자치도 제주시 구좌읍",
                        "road_address": "제주특별자치도 제주시 구좌읍 해맞이해안로",
                        "legal_dong_code": None,
                        "sido_code": None,
                        "sigungu_code": None,
                    },
                },
                "youtube": {
                    "source_title": name,
                    "video_id": f"video-{candidate_id}",
                    "channel_id": channel_id,
                    "channel_title": f"채널 {channel_id}",
                },
                "evidence": {"confidence_score": 0.9},
                "source_record": {
                    "provider": KOR_TRAVEL_CONCIERGE_PROVIDER_NAME,
                    "dataset_key": DATASET_KEY_YOUTUBE_PLACE_CANDIDATES,
                    "source_entity_type": "extracted_place_candidate",
                    "source_entity_id": candidate_id,
                    "raw_payload_hash": f"sha256:{candidate_id}",
                },
            }
        ],
        fetched_at=_FETCHED,
    )
    await feature_repo.load_bundle(session, bundle)
    await session.flush()
    return bundle.feature.feature_id
