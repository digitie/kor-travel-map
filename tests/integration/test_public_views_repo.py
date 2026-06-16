"""``public_views_repo`` 공개 view SQL 통합 테스트 (T-222b)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pytest

from kortravelmap.infra import feature_repo, public_views_repo
from kortravelmap.providers.khoa import beaches_to_bundles
from kortravelmap.providers.standard_data import cultural_festivals_to_bundles

pytestmark = pytest.mark.integration

_KST = timezone(timedelta(hours=9))
_FETCHED = datetime(2026, 6, 12, 12, 0, tzinfo=_KST)


@dataclass(frozen=True)
class _Beach:
    name: str
    sido_name: str
    gugun_name: str | None
    latitude: float | None
    longitude: float | None
    beach_kind: str | None
    image_url: str | None
    raw: Any = None


@dataclass(frozen=True)
class _Festival:
    fstvl_nm: str | None
    opar: str | None = None
    fstvl_start_date: date | None = None
    fstvl_end_date: date | None = None
    fstvl_co: str | None = None
    mnnst_nm: str | None = None
    auspc_instt_nm: str | None = None
    suprt_instt_nm: str | None = None
    phone_number: str | None = None
    homepage_url: str | None = None
    relate_info: str | None = None
    rdnmadr: str | None = None
    lnmadr: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    reference_date: date | None = None
    instt_code: str | None = None
    instt_nm: str | None = None


async def test_public_beaches_use_place_kind_not_category(migrated_session: Any) -> None:
    """KHOA 해수욕장은 category 01050100(전용 해수욕장, DA-D-07)이어도 공개 view에 포함된다."""

    bundle = (
        await beaches_to_bundles(
            [
                _Beach(
                    name="통합테스트 해수욕장",
                    sido_name="부산광역시",
                    gugun_name="수영구",
                    latitude=35.155,
                    longitude=129.118,
                    beach_kind="일반",
                    image_url="https://example.test/beach.jpg",
                )
            ],
            fetched_at=_FETCHED,
        )
    )[0]
    assert bundle.feature.category == "01050100"
    assert bundle.feature.detail is not None
    assert bundle.feature.detail.place_kind == "beach"
    await feature_repo.load_bundle(migrated_session, bundle)
    await migrated_session.flush()

    page = await public_views_repo.list_public_beaches(
        migrated_session,
        q="통합테스트",
        page_size=10,
    )
    ids = {row.feature_id for row in page.items}
    assert bundle.feature.feature_id in ids
    row = next(item for item in page.items if item.feature_id == bundle.feature.feature_id)
    assert row.detail["place_kind"] == "beach"
    assert row.source_raw_data["image_url"] == "https://example.test/beach.jpg"
    assert "python-khoa-api" in row.source_providers


async def test_public_festivals_monthly_uses_date_overlap(migrated_session: Any) -> None:
    bundle = (
        await cultural_festivals_to_bundles(
            [
                _Festival(
                    fstvl_nm="통합테스트 봄꽃 축제",
                    opar="여의도공원",
                    fstvl_start_date=date(2026, 4, 25),
                    fstvl_end_date=date(2026, 5, 3),
                    fstvl_co="봄꽃 축제 상세",
                    mnnst_nm="영등포구청",
                    auspc_instt_nm="서울시",
                    suprt_instt_nm="후원기관",
                    phone_number="02-2670-3114",
                    homepage_url="https://example.test/festival",
                    rdnmadr="서울특별시 영등포구 여의공원로 120",
                    lnmadr="서울특별시 영등포구 여의도동 8",
                    latitude=37.5263,
                    longitude=126.9239,
                    reference_date=date(2026, 4, 1),
                    instt_nm="서울특별시 영등포구",
                )
            ],
            fetched_at=_FETCHED,
        )
    )[0]
    await feature_repo.load_bundle(migrated_session, bundle)
    await migrated_session.flush()

    page = await public_views_repo.list_public_festivals_monthly(
        migrated_session,
        month_start=date(2026, 5, 1),
        month_end=date(2026, 5, 31),
        page_size=10,
        include_months=True,
    )
    ids = {row.feature_id for row in page.items}
    assert bundle.feature.feature_id in ids
    row = next(item for item in page.items if item.feature_id == bundle.feature.feature_id)
    assert row.detail["starts_on"] == "2026-04-25"
    assert row.detail["ends_on"] == "2026-05-03"
    assert row.source_raw_data["fstvl_co"] == "봄꽃 축제 상세"
    assert any(
        month.year == 2026 and month.month == 5 and month.count >= 1
        for month in page.months
    )
