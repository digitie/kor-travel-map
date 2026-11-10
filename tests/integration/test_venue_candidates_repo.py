"""장소 이름 후보 읽기(#1468 D) — 적재된 국가유산 장소를 행사 장소 이름으로 찾는다."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from kortravelmap.core.venue_match import match_venue
from kortravelmap.dto import Address, Coordinate
from kortravelmap.infra import feature_repo
from kortravelmap.infra.venue_candidates_repo import find_venue_candidates
from kortravelmap.providers.krheritage import DATASET_KEY_HERITAGE, heritage_items_to_bundles
from tests.integration.conftest import as_dagster_runtime

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration
_FETCHED = datetime(2026, 11, 10, tzinfo=UTC)


@dataclass(frozen=True)
class _Key:
    ccba_kdcd: str
    ccba_asno: str
    ccba_ctcd: str

    @property
    def natural_key(self) -> str:
        return f"{self.ccba_kdcd}-{self.ccba_asno}-{self.ccba_ctcd}"


@dataclass(frozen=True)
class _Item:
    key: _Key
    name_ko: str
    category: str | None = None
    region: str | None = "경상남도"
    sigungu: str | None = "진주시"
    longitude: Decimal | None = Decimal("128.0817")
    latitude: Decimal | None = Decimal("35.1887")
    location_text: str | None = "경상남도 진주시 남강로 626"
    designated_at: str | None = None
    owner: str | None = None
    image_url: str | None = None


async def _reverse(coord: Coordinate) -> Address:
    return Address(
        legal="경상남도 진주시 본성동 500-1",
        bjd_code="4817010100",
        sido_name="경상남도",
        sigungu_name="진주시",
        sigungu_code="48170",
        sido_code="48",
    )


async def test_heritage_place_is_found_by_event_venue_name(
    migrated_session: AsyncSession,
) -> None:
    [bundle] = await heritage_items_to_bundles(
        [_Item(key=_Key("13", "118", "38"), name_ko="진주 진주성")],
        fetched_at=_FETCHED,
        reverse_geocoder=_reverse,
    )
    async with as_dagster_runtime(migrated_session):
        await feature_repo.load_bundle(migrated_session, bundle)
        candidates = await find_venue_candidates(migrated_session, name="진주성")
        none = await find_venue_candidates(migrated_session, name="없는 장소 이름")
        short = await find_venue_candidates(migrated_session, name="성")

    [candidate] = [c for c in candidates if c.name == "진주 진주성"]
    assert candidate.dataset_key == DATASET_KEY_HERITAGE
    assert candidate.sido_name == "경상남도"
    assert candidate.sigungu_name == "진주시"
    assert none == []
    assert short == []
    match = match_venue(
        "진주성", "경상남도", "진주시", candidates, prefer_dataset_key=DATASET_KEY_HERITAGE
    )
    assert match is not None
    assert match.coord == candidate.coord
    assert match_venue("진주성", "경상북도", "경주시", candidates) is None
