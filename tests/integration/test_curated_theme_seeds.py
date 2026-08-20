"""seed된 theme 집합 — 40C 이후에도 catalog는 그대로다.

T-VN-40C가 `tests/integration/test_curated_repo.py`를 지우면서 legacy overlay 검사와
함께 사라질 뻔한 theme seed 계약만 옮겼다.
"""

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
