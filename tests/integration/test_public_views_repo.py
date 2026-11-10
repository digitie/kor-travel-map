"""``public_views_repo`` 공개 view SQL 통합 테스트 (T-222b)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pytest
from sqlalchemy import text

from kortravelmap.infra import feature_repo, public_views_repo
from kortravelmap.providers.khoa import beaches_to_bundles
from tests.integration._tourapi_festival import festival_bundles, festival_item

pytestmark = pytest.mark.integration

_KST = timezone(timedelta(hours=9))
_FETCHED = datetime(2026, 6, 12, 12, 0, tzinfo=_KST)


async def _canonical_uuid_for_alias(session: Any, legacy_feature_id: str) -> str:
    """provider가 계산한 legacy ``f_*``가 가리키는 정본 키(uuid의 text 표기).

    T-VN-39 재키(309) 뒤 ``feature.features.feature_id``는 uuid이고, 그 값은
    서버가 발급하는 비파생 UUIDv7이다(ADR-098) — provider 라이브러리가 유도한
    ``bundle.feature.feature_id``는 정본 키가 **아니다.** legacy 문자열에서
    정본 키로 가는 유일한 입구가 ``feature_aliases``이고, ADR-098 결정 6에 따라
    그 주소를 발급하는 것이 바로 이 두 테스트가 쓰는 provider 적재 경로다.

    응답의 ``feature_id``/``feature_uuid`` 슬롯은 이름도 값도 uuid의 text
    표기이므로(경계 규칙) 비교 대상을 여기서 같은 표기로 맞춘다.
    """
    return str(
        (
            await session.execute(
                text(
                    "SELECT CAST(a.feature_id AS text) "
                    "FROM feature.feature_aliases AS a "
                    "WHERE a.alias = :alias AND a.alias_kind = 'legacy_feature_id'"
                ),
                {"alias": legacy_feature_id},
            )
        ).scalar_one()
    )


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

    feature_uuid = await _canonical_uuid_for_alias(
        migrated_session, bundle.feature.feature_id
    )

    page = await public_views_repo.list_public_beaches(
        migrated_session,
        q="통합테스트",
        page_size=10,
    )
    ids = {row.feature_id for row in page.items}
    assert feature_uuid in ids
    row = next(item for item in page.items if item.feature_id == feature_uuid)
    assert row.feature_uuid == feature_uuid
    assert row.detail["place_kind"] == "beach"
    assert row.source_raw_data["image_url"] == "https://example.test/beach.jpg"
    assert "python-khoa-api" in row.source_providers


async def test_public_festivals_monthly_uses_date_overlap(migrated_session: Any) -> None:
    bundle = (
        await festival_bundles(
            [
                festival_item(
                    "FEST-PUBLIC-MONTHLY",
                    "통합테스트 봄꽃 축제",
                    starts_on=date(2026, 4, 25),
                    ends_on=date(2026, 5, 3),
                    overview="봄꽃 축제 상세",
                    homepage="https://example.test/festival",
                )
            ],
            fetched_at=_FETCHED,
        )
    )[0]
    await feature_repo.load_bundle(migrated_session, bundle)
    await migrated_session.flush()

    feature_uuid = await _canonical_uuid_for_alias(
        migrated_session, bundle.feature.feature_id
    )

    page = await public_views_repo.list_public_festivals_monthly(
        migrated_session,
        month_start=date(2026, 5, 1),
        month_end=date(2026, 5, 31),
        page_size=10,
        include_months=True,
    )
    ids = {row.feature_id for row in page.items}
    assert feature_uuid in ids
    row = next(item for item in page.items if item.feature_id == feature_uuid)
    assert row.feature_uuid == feature_uuid
    assert row.detail["starts_on"] == "2026-04-25"
    assert row.detail["ends_on"] == "2026-05-03"
    # 공개 축제 view의 ``festival_content``는 ``detail.payload.content``를 읽는다(TourAPI 상세).
    assert row.detail["payload"]["content"] == "봄꽃 축제 상세"
    assert row.source_raw_data["overview"] == "봄꽃 축제 상세"
    assert "python-visitkorea-api" in row.source_providers
    assert any(
        month.year == 2026 and month.month == 5 and month.count >= 1
        for month in page.months
    )
