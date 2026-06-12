"""``feature.curated_*`` repository 통합 테스트 (T-223c-1)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from krtour.map.dto import Address, Coordinate
from krtour.map.infra import curated_repo, feature_repo
from krtour.map.providers.datagokr_file_data import file_data_rows_to_bundles

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_KST = timezone(timedelta(hours=9))
_FETCHED = datetime(2026, 6, 12, 18, 0, tzinfo=_KST)


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


async def test_seed_rule_apply_creates_candidate_and_tripmate_snapshot(
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
    assert row.tripmate_relation == "bookstore_stop"
    assert row.tripmate_copy_policy == "copy_allowed"

    selected = await curated_repo.set_curated_feature_status(
        migrated_session,
        curated_feature_id=row.curated_feature_id,
        curation_status="curated",
        actor="pytest",
    )
    assert selected is not None
    assert selected.copy_version == row.copy_version + 1

    public_page = await curated_repo.list_curated_features(
        migrated_session,
        theme_slug="bookstores",
    )
    assert [item.curated_feature_id for item in public_page.items] == [
        selected.curated_feature_id
    ]

    snapshot = await curated_repo.get_curated_tripmate_copy_snapshot(
        migrated_session,
        curated_feature_id=selected.curated_feature_id,
    )
    assert snapshot is not None
    assert snapshot.etag.startswith("sha256:")
    assert snapshot.theme["theme_slug"] == "bookstores"
    assert snapshot.plan["title"] == "통합테스트 헌책방"
    assert snapshot.items[0].feature_snapshot["name"] == "통합테스트 헌책방"

    refreshed = await curated_repo.refresh_curated_source_metadata(
        migrated_session,
        provider="python-datagokr-api",
        dataset_key="datagokr_seoul_bookstores",
    )
    assert refreshed.sources_checked == 1
    assert refreshed.sources_with_records == 1
    assert refreshed.source_records_total >= 1

    materialized = await curated_repo.materialize_curated_tripmate_copy_snapshots(
        migrated_session,
        theme_slug="bookstores",
    )
    assert materialized.curated_features_total >= 1
    assert materialized.snapshots_materialized >= 1
    cached = (
        await migrated_session.execute(
            text(
                """
                SELECT copy_version, etag, snapshot
                FROM feature.curated_tripmate_copy_snapshots
                WHERE curated_feature_id = CAST(:curated_feature_id AS uuid)
                """
            ),
            {"curated_feature_id": selected.curated_feature_id},
        )
    ).mappings().one()
    assert cached["copy_version"] == selected.copy_version
    assert cached["etag"] == snapshot.etag
    assert cached["snapshot"]["plan"]["title"] == "통합테스트 헌책방"


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
        tripmate_relation="bookstore_stop",
        tripmate_copy_policy="copy_allowed",
        metadata={"manual": True},
    )
    assert created.selected_at is not None
    assert created.copy_version == 1

    patched = await curated_repo.update_curated_feature(
        migrated_session,
        curated_feature_id=created.curated_feature_id,
        updates={"display_summary": "수동 추천 책방"},
    )
    assert patched is not None
    assert patched.display_summary == "수동 추천 책방"
    assert patched.copy_version == 2

    archived = await curated_repo.archive_curated_feature(
        migrated_session,
        curated_feature_id=created.curated_feature_id,
        actor="pytest",
    )
    assert archived is not None
    assert archived.curation_status == "archived"
    assert archived.archived_at is not None


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
