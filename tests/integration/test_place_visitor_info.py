"""place 방문 안내 jsonb 왕복·상세 백필 우선 점수(ADR-126).

- TourAPI 관광지를 상세 op 묶음과 함께 적재하면 ``feature_places.facility_info.visitor_info``와
  ``source_records.raw_data.tourapi_detail_ops``가 그대로 남고, current 원본 읽기가 묶음을 돌려준다
  (다음 run·replay가 이어 쓰는 경로).
- ``read_detail_priority_scores``는 검색 인지도를 점수로 돌려주고 0점 entity는 뺀다.

세션은 테스트마다 롤백된다(``migrated_session``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import text

from kortravelmap.dto import Address, Coordinate
from kortravelmap.infra import feature_identity
from kortravelmap.infra.feature_repo import load_bundles, resolve_active_provider_dataset_id
from kortravelmap.infra.source_replay_repo import (
    read_current_source_records,
    read_detail_priority_scores,
)
from kortravelmap.providers.visitkorea_attractions import (
    DATASET_KEY_VISITKOREA_ATTRACTIONS,
    TOURAPI_DETAIL_RAW_KEY,
    tourapi_attractions_to_bundles,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_FETCHED = datetime(2026, 11, 27, 3, 0, tzinfo=UTC)
_MODIFIED = datetime(2026, 3, 2, 1, 0, tzinfo=UTC)


@dataclass(frozen=True)
class _Item:
    content_id: str
    title: str
    content_type_id: str | None = "12"
    addr1: str | None = "부산광역시 중구 용두산길 37-30"
    addr2: str | None = None
    zipcode: str | None = None
    tel: str | None = None
    first_image: str | None = None
    first_image2: str | None = None
    map_x: float | None = 129.0324096
    map_y: float | None = 35.1011207
    lcls_systm1: str | None = "VE"
    lcls_systm2: str | None = "VE01"
    lcls_systm3: str | None = "VE010200"
    l_dong_regn_cd: str | None = "26"
    l_dong_signgu_cd: str | None = "110"
    created_time: datetime | None = None
    modified_time: datetime | None = _MODIFIED
    copyright_division_code: str | None = "Type1"
    overview: str | None = None
    homepage: str | None = None


async def _reverse(coord: Coordinate) -> Address:
    del coord
    return Address(bjd_code="2611010100", sigungu_code="26110", sido_code="26")


_OPS: dict[str, Any] = {
    "intro": {"modified_time": _MODIFIED.isoformat(), "data": {"usetime": "09:30~23:00"}},
    "images": {
        "modified_time": _MODIFIED.isoformat(),
        "data": [{"originimgurl": "http://tong.visitkorea.or.kr/a.jpg", "cpyrhtDivCd": "Type3"}],
    },
}


async def test_visitor_info_and_detail_ops_survive_the_jsonb_round_trip(
    migrated_session: AsyncSession,
) -> None:
    session = migrated_session
    bundles = await tourapi_attractions_to_bundles(
        [_Item("1277679", "부산타워"), _Item("128164", "광안대교")],
        fetched_at=_FETCHED,
        reverse_geocoder=_reverse,
        details={"1277679": _OPS},
    )
    await load_bundles(session, bundles)
    identity = await feature_identity.resolve_feature_identity(
        session, bundles[0].feature.feature_id
    )
    assert identity is not None
    stored = (
        await session.execute(
            text(
                "SELECT facility_info->'visitor_info' FROM feature.feature_places "
                "WHERE feature_id = CAST(:id AS uuid)"
            ),
            {"id": identity.feature_id},
        )
    ).scalar_one()
    assert stored["usage_hours"] == "09:30~23:00"
    assert stored["images"][0]["license"]["kogl_type"] == 3
    assert stored["images"][0]["license"]["derivatives_allowed"] is False

    dataset_id = await resolve_active_provider_dataset_id(
        session, provider="python-visitkorea-api", dataset_key=DATASET_KEY_VISITKOREA_ATTRACTIONS
    )
    current = await read_current_source_records(session, provider_dataset_id=dataset_id)
    by_id = {record.source_entity_id: record.raw_data for record in current}
    assert by_id["1277679"][TOURAPI_DETAIL_RAW_KEY] == _OPS
    assert TOURAPI_DETAIL_RAW_KEY not in by_id["128164"]

    # 검색 인지도가 있는 행만 점수를 받는다(0점은 생략).
    await session.execute(
        text(
            "INSERT INTO feature.feature_search_prominence (feature_id, prominence) "
            "VALUES (CAST(:id AS uuid), 4)"
        ),
        {"id": identity.feature_id},
    )
    scores = await read_detail_priority_scores(session, provider_dataset_id=dataset_id)
    assert scores == {"1277679": 4}
