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


async def test_seed_rule_apply_creates_candidate_and_detail_snapshot(
    migrated_session: AsyncSession,
) -> None:
    feature_id = await _load_seoul_bookstore(migrated_session)

    rules = await curated_repo.list_curated_source_rules(
        migrated_session,
        theme_slug="bookstores",
        provider="python-datagokr-api",
        dataset_key="datagokr_seoul_bookstores",
    )
    assert len(rules) == 1

    applied = await curated_repo.apply_curated_source_rule(
        migrated_session,
        rule_id=rules[0].rule_id,
    )
    assert applied.inserted_or_updated == 1

    candidates = await curated_repo.list_curated_features(
        migrated_session,
        theme_slug="bookstores",
        curation_status="candidate",
        page_size=10,
    )
    row = next(item for item in candidates.items if item.feature_id == feature_id)
    assert row.provider == "python-datagokr-api"
    assert row.dataset_key == "datagokr_seoul_bookstores"
    assert row.display_title == "python-datagokr-api"
    assert row.curation_relation == "bookstore_stop"
    assert row.reuse_policy == "allowed"

    selected = await curated_repo.set_curated_feature_status(
        migrated_session,
        curated_feature_id=row.curated_feature_id,
        curation_status="curated",
        actor="pytest",
    )
    assert selected is not None
    assert selected.content_version == row.content_version + 1

    public_page = await curated_repo.list_curated_features(
        migrated_session,
        theme_slug="bookstores",
    )
    assert [item.curated_feature_id for item in public_page.items] == [
        selected.curated_feature_id
    ]

    snapshot = await curated_repo.get_curated_feature_detail_snapshot(
        migrated_session,
        curated_feature_id=selected.curated_feature_id,
    )
    assert snapshot is not None
    assert snapshot.etag.startswith("sha256:")
    assert snapshot.theme["theme_slug"] == "bookstores"
    assert snapshot.content["title"] == "python-datagokr-api"
    assert snapshot.items[0].feature_snapshot["name"] == "통합테스트 헌책방"
    # T-VN-32C PR-2 (R6) — snapshot 빌더의 feature 참조는 UUID 정본이다.
    stored_uuid = (
        await migrated_session.execute(
            text(
                "SELECT CAST(feature_uuid AS text) FROM feature.features "
                "WHERE feature_id = :fid"
            ),
            {"fid": feature_id},
        )
    ).scalar_one()
    assert snapshot.items[0].feature_id == stored_uuid
    assert snapshot.items[0].feature_snapshot["feature_id"] == stored_uuid

    refreshed = await curated_repo.refresh_curated_source_metadata(
        migrated_session,
        provider="python-datagokr-api",
        dataset_key="datagokr_seoul_bookstores",
    )
    assert refreshed.sources_checked == 1
    assert refreshed.sources_with_records == 1
    assert refreshed.source_records_total >= 1

    materialized = await curated_repo.materialize_curated_feature_detail_snapshots(
        migrated_session,
        theme_slug="bookstores",
    )
    assert materialized.curated_features_total >= 1
    assert materialized.snapshots_materialized >= 1
    cached = (
        await migrated_session.execute(
            text(
                """
                SELECT content_version, etag, snapshot
                FROM feature.curated_feature_detail_snapshots
                WHERE curated_feature_id = CAST(:curated_feature_id AS uuid)
                """
            ),
            {"curated_feature_id": selected.curated_feature_id},
        )
    ).mappings().one()
    assert cached["content_version"] == selected.content_version
    assert cached["etag"] == snapshot.etag
    assert cached["snapshot"]["content"]["title"] == "python-datagokr-api"
    # T-VN-32C PR-2 (R6) — 물질화된 snapshot JSON의 items[].feature_id와
    # feature_snapshot.feature_id도 UUID 정본이다 (legacy 잔존 = 혼합 포맷 회귀).
    stored_items = cached["snapshot"]["items"]
    assert [item["feature_id"] for item in stored_items] == [stored_uuid]
    assert stored_items[0]["feature_snapshot"]["feature_id"] == stored_uuid


async def test_concierge_seed_rule_creates_curated_with_source_title(
    migrated_session: AsyncSession,
) -> None:
    feature_id = await _load_concierge_place(migrated_session)

    [rule] = await curated_repo.list_curated_source_rules(
        migrated_session,
        theme_slug="media-places",
        provider=KOR_TRAVEL_CONCIERGE_PROVIDER_NAME,
        dataset_key=DATASET_KEY_YOUTUBE_PLACE_CANDIDATES,
    )
    assert rule.default_action == "curated"

    applied = await curated_repo.apply_curated_source_rule(
        migrated_session,
        rule_id=rule.rule_id,
    )
    assert applied.inserted_or_updated == 1

    page = await curated_repo.list_curated_features(
        migrated_session,
        theme_slug="media-places",
        provider=KOR_TRAVEL_CONCIERGE_PROVIDER_NAME,
        dataset_key=DATASET_KEY_YOUTUBE_PLACE_CANDIDATES,
    )
    row = next(item for item in page.items if item.feature_id == feature_id)
    assert row.curation_status == "curated"
    assert row.display_title == "제주 동쪽 영상 묶음"
    assert row.selected_at is not None

    snapshot = await curated_repo.get_curated_feature_detail_snapshot(
        migrated_session,
        curated_feature_id=row.curated_feature_id,
    )
    assert snapshot is not None
    assert snapshot.content["title"] == "제주 동쪽 영상 묶음"
    assert snapshot.items[0].feature_snapshot["name"] == "월정리 해변"


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


async def test_manual_create_patch_and_archive_curated_feature(
    migrated_session: AsyncSession,
) -> None:
    feature_id = await _load_seoul_bookstore(migrated_session)
    themes = await curated_repo.list_curated_themes(
        migrated_session,
        limit=50,
    )
    theme = next(item for item in themes if item.theme_group == "books")
    target_theme = next(item for item in themes if item.theme_id != theme.theme_id)
    [source] = await curated_repo.list_curated_sources(
        migrated_session,
        provider="python-datagokr-api",
        dataset_key="datagokr_seoul_bookstores",
        limit=1,
    )

    created = await curated_repo.create_curated_feature(
        migrated_session,
        theme_id=theme.theme_id,
        feature_id=feature_id,
        source_id=source.source_id,
        curation_status="curated",
        selected_by="pytest",
        curation_relation="bookstore_stop",
        reuse_policy="allowed",
        metadata={"manual": True},
    )
    assert created.selected_at is not None
    assert created.content_version == 1

    patched = await curated_repo.update_curated_feature(
        migrated_session,
        curated_feature_id=created.curated_feature_id,
        updates={
            "theme_id": target_theme.theme_id,
            "display_title": "관리자 지정 묶음 제목",
            "display_summary": "수동 추천 책방",
        },
    )
    assert patched is not None
    assert patched.theme_id == target_theme.theme_id
    assert patched.display_title == "관리자 지정 묶음 제목"
    assert patched.display_summary == "수동 추천 책방"
    assert patched.content_version == 2

    archived = await curated_repo.update_curated_feature(
        migrated_session,
        curated_feature_id=created.curated_feature_id,
        updates={"curation_status": "archived"},
        actor="pytest",
    )
    assert archived is not None
    assert archived.curation_status == "archived"
    assert archived.archived_at is not None

    retained_tombstone = await curated_repo.update_curated_feature(
        migrated_session,
        curated_feature_id=created.curated_feature_id,
        updates={"curation_status": "curated"},
        actor="pytest",
    )
    assert retained_tombstone is not None
    assert retained_tombstone.curation_status == "archived"
    assert retained_tombstone.archived_at is not None

    created_archived = await curated_repo.create_curated_feature(
        migrated_session,
        theme_id=theme.theme_id,
        feature_id=feature_id,
        source_id=source.source_id,
        curation_status="archived",
        actor="pytest",
    )
    assert created_archived.curation_status == "archived"
    assert created_archived.archived_at is not None


async def test_list_curated_features_distinct_by_feature_dedups_cross_theme(
    migrated_session: AsyncSession,
) -> None:
    """같은 물리 feature가 여러 테마로 큐레이션되면 기본 목록엔 테마 수만큼 행이 나오지만,
    distinct_by_feature=True(지도 경로)면 rank_score 최고 큐레이션 1건만 반환한다."""
    feature_id = await _load_seoul_bookstore(migrated_session)
    themes = await curated_repo.list_curated_themes(migrated_session, limit=50)
    theme_a = themes[0]
    theme_b = next(item for item in themes if item.theme_id != theme_a.theme_id)
    [source] = await curated_repo.list_curated_sources(
        migrated_session,
        provider="python-datagokr-api",
        dataset_key="datagokr_seoul_bookstores",
        limit=1,
    )
    await curated_repo.create_curated_feature(
        migrated_session,
        theme_id=theme_a.theme_id,
        feature_id=feature_id,
        source_id=source.source_id,
        curation_status="curated",
        selected_by="pytest",
        rank_score=10.0,
    )
    best = await curated_repo.create_curated_feature(
        migrated_session,
        theme_id=theme_b.theme_id,
        feature_id=feature_id,
        source_id=source.source_id,
        curation_status="curated",
        selected_by="pytest",
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
    assert kept[0].curated_feature_id == best.curated_feature_id
    dedup_feature_ids = [item.feature_id for item in deduped.items]
    assert len(dedup_feature_ids) == len(set(dedup_feature_ids))


async def test_list_curated_features_display_titles_multi_filter(
    migrated_session: AsyncSession,
) -> None:
    """display_titles(멀티) 필터는 지정한 제목 집합만 반환한다(큐레이션 관리 title 필터)."""
    feature_id = await _load_seoul_bookstore(migrated_session)
    themes = await curated_repo.list_curated_themes(migrated_session, limit=50)
    [source] = await curated_repo.list_curated_sources(
        migrated_session,
        provider="python-datagokr-api",
        dataset_key="datagokr_seoul_bookstores",
        limit=1,
    )
    await curated_repo.create_curated_feature(
        migrated_session,
        theme_id=themes[0].theme_id,
        feature_id=feature_id,
        source_id=source.source_id,
        curation_status="curated",
        display_title="가을 책방",
        selected_by="pytest",
    )
    await curated_repo.create_curated_feature(
        migrated_session,
        theme_id=themes[1].theme_id,
        feature_id=feature_id,
        source_id=source.source_id,
        curation_status="curated",
        display_title="겨울 책방",
        selected_by="pytest",
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


async def test_apply_rule_detail_selector_partitions_by_youtube_channel(
    migrated_session: AsyncSession,
) -> None:
    """detail_selector로 단일 concierge source를 youtube channel_id별로 분할한다.

    channel-A 후보만 detail_selector에 맞아 후보화되고 channel-B는 제외된다 —
    concierge 그룹핑을 테마 멤버십으로 만드는 apply 술어 검증(#15 근간).
    """
    fid_a = await _load_concierge_place_channel(
        migrated_session, candidate_id="sel-a", channel_id="channel-A", name="A 해변"
    )
    fid_b = await _load_concierge_place_channel(
        migrated_session, candidate_id="sel-b", channel_id="channel-B", name="B 해변"
    )
    [source] = await curated_repo.list_curated_sources(
        migrated_session,
        provider="kor-travel-concierge-youtube",
        dataset_key="youtube_place_candidates",
        limit=1,
    )
    theme = (await curated_repo.list_curated_themes(migrated_session, limit=50))[0]
    rule = await curated_repo.create_curated_source_rule(
        migrated_session,
        theme_id=theme.theme_id,
        source_id=source.source_id,
        dataset_key="youtube_place_candidates",
        place_kind="youtube_place_candidate",
        detail_selector={
            "path": ["payload", "kor_travel_concierge", "youtube", "channel_id"],
            "value": "channel-A",
        },
        default_action="curated",
    )
    assert rule.detail_selector == {
        "path": ["payload", "kor_travel_concierge", "youtube", "channel_id"],
        "value": "channel-A",
    }

    await curated_repo.apply_curated_source_rule(migrated_session, rule_id=rule.rule_id)
    curated = await curated_repo.list_curated_features(
        migrated_session, theme_id=theme.theme_id, curation_status="curated"
    )
    curated_fids = {item.feature_id for item in curated.items}
    assert fid_a in curated_fids
    assert fid_b not in curated_fids


async def test_sync_concierge_themes_creates_themes_and_candidates(
    migrated_session: AsyncSession,
) -> None:
    """concierge youtube channel 그룹핑 → public 테마 + detail_selector rule +
    후보 feature 자동 채움. 멱등(재실행 시 rule 추가 생성 없음). #15 근간."""
    fid_a1 = await _load_concierge_place_channel(
        migrated_session, candidate_id="syn-a1", channel_id="chan-A", name="A1"
    )
    fid_a2 = await _load_concierge_place_channel(
        migrated_session, candidate_id="syn-a2", channel_id="chan-A", name="A2"
    )
    fid_b1 = await _load_concierge_place_channel(
        migrated_session, candidate_id="syn-b1", channel_id="chan-B", name="B1"
    )

    result = await curated_repo.sync_concierge_themes(migrated_session, min_features=1)
    assert result.groupings >= 2
    assert result.rules_created >= 2

    themes = await curated_repo.list_curated_themes(migrated_session, limit=200)
    slugs = {theme.theme_slug for theme in themes}
    assert "concierge-yt-chan-A" in slugs
    assert "concierge-yt-chan-B" in slugs
    theme_a = next(t for t in themes if t.theme_slug == "concierge-yt-chan-A")
    assert theme_a.theme_group == "media"
    assert theme_a.visibility == "public"

    curated_a = await curated_repo.list_curated_features(
        migrated_session, theme_id=theme_a.theme_id, curation_status="curated"
    )
    a_fids = {item.feature_id for item in curated_a.items}
    assert fid_a1 in a_fids
    assert fid_a2 in a_fids
    assert fid_b1 not in a_fids

    # 멱등: 재실행 시 rule 추가 생성 없음.
    again = await curated_repo.sync_concierge_themes(migrated_session, min_features=1)
    assert again.rules_created == 0


async def test_rejected_curated_feature_is_not_revived_by_rule_apply(
    migrated_session: AsyncSession,
) -> None:
    feature_id = await _load_seoul_bookstore(migrated_session)
    [rule] = await curated_repo.list_curated_source_rules(
        migrated_session,
        theme_slug="bookstores",
        provider="python-datagokr-api",
        dataset_key="datagokr_seoul_bookstores",
    )
    await curated_repo.apply_curated_source_rule(migrated_session, rule_id=rule.rule_id)
    [candidate] = (
        await curated_repo.list_curated_features(
            migrated_session,
            theme_slug="bookstores",
            curation_status="candidate",
        )
    ).items
    assert candidate.feature_id == feature_id

    manually_classified = await curated_repo.update_curated_feature(
        migrated_session,
        curated_feature_id=candidate.curated_feature_id,
        updates={
            "curation_relation": "bookstore_stop",
            "reuse_policy": "blocked",
        },
    )
    assert manually_classified is not None
    await curated_repo.apply_curated_source_rule(
        migrated_session,
        rule_id=rule.rule_id,
    )
    after_provider_refresh = await curated_repo.get_curated_feature(
        migrated_session,
        curated_feature_id=candidate.curated_feature_id,
        include_archived=True,
    )
    assert after_provider_refresh is not None
    assert after_provider_refresh.curation_relation == "bookstore_stop"
    assert after_provider_refresh.reuse_policy == "blocked"

    rejected = await curated_repo.set_curated_feature_status(
        migrated_session,
        curated_feature_id=candidate.curated_feature_id,
        curation_status="rejected",
        actor="pytest",
        reason="테스트 제외",
    )
    assert rejected is not None
    applied = await curated_repo.apply_curated_source_rule(
        migrated_session,
        rule_id=rule.rule_id,
    )

    assert applied.inserted_or_updated == 0
    rejected_page = await curated_repo.list_curated_features(
        migrated_session,
        theme_slug="bookstores",
        curation_status="rejected",
    )
    assert [item.curated_feature_id for item in rejected_page.items] == [
        rejected.curated_feature_id
    ]


async def test_curated_status_sweep_archives_inactive_feature(
    migrated_session: AsyncSession,
) -> None:
    feature_id = await _load_seoul_bookstore(migrated_session)
    [theme] = await curated_repo.list_curated_themes(
        migrated_session,
        theme_group="books",
        limit=1,
    )
    [source] = await curated_repo.list_curated_sources(
        migrated_session,
        provider="python-datagokr-api",
        dataset_key="datagokr_seoul_bookstores",
        limit=1,
    )
    created = await curated_repo.create_curated_feature(
        migrated_session,
        theme_id=theme.theme_id,
        feature_id=feature_id,
        source_id=source.source_id,
        curation_status="curated",
        selected_by="pytest",
    )

    await migrated_session.execute(
        text("UPDATE feature.features SET status = 'inactive' WHERE feature_id = :id"),
        {"id": feature_id},
    )
    swept = await curated_repo.sweep_curated_feature_status(migrated_session)
    archived = await curated_repo.get_curated_feature(
        migrated_session,
        curated_feature_id=created.curated_feature_id,
        include_archived=True,
    )

    assert swept.archived == 1
    assert archived is not None
    assert archived.curation_status == "archived"
    assert archived.archived_at is not None
