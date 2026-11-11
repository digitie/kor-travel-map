"""KNPS 이름 정규화가 바뀐 뒤 같은 원천 행을 다시 적재하면 Feature 이름이 따라오는가.

python-knps-api a472a37(#17 후속)은 ``現노고단대피소``의 이름에서 ``現``을 걷고 원문은 ``raw``에
남긴다 — 원천 행(raw)은 **그대로**다. 원천 행만 해시하면 다음 적재가 그 행을 "바뀌지 않음"으로
보고 이름을 고치지 않는다(이 테스트가 처음 빨갛게 보인 것). Map 변환기가 고친 이름을 해시에
넣으므로(``providers.knps._point_raw_data``) 운영의 ``現노고단대피소``가 다음 적재에서 고쳐지는지를
실제 적재 경로로 고정한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import text

from kortravelmap.infra import feature_repo
from kortravelmap.providers.knps import knps_point_records_to_bundles

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_KST = timezone(timedelta(hours=9))


@dataclass(frozen=True)
class _Rec:
    source_id: str
    name: str | None
    longitude: Decimal | None
    latitude: Decimal | None
    raw: dict[str, Any]


async def _load(session: AsyncSession, name: str, fetched_at: datetime) -> str:
    raw = {"순번": "9421", "시설물": "現이름재적재대피소", "사무소": "지리산전남"}
    record = _Rec("shp:name-reload-9421", name, Decimal("127.5310"), Decimal("35.2950"), raw)
    [bundle] = await knps_point_records_to_bundles(
        [record], dataset_key="knps_shelters", fetched_at=fetched_at
    )
    await feature_repo.load_bundles(session, [bundle])
    await session.flush()
    return bundle.source_record.source_record_key


async def test_stripped_shelter_name_replaces_loaded_name_with_same_raw(
    migrated_session: AsyncSession,
) -> None:
    first_key = await _load(
        migrated_session, "現이름재적재대피소", datetime(2026, 11, 10, 9, 0, tzinfo=_KST)
    )
    second_key = await _load(
        migrated_session, "이름재적재대피소", datetime(2026, 11, 12, 9, 0, tzinfo=_KST)
    )
    # 원천 행은 같지만 고친 이름이 해시에 들어가(__map_display_name__) 새 source record가 된다 —
    # 그래야 적재가 "바뀌지 않음"으로 건너뛰지 않는다(이 덧붙임 전에는 이름이 現…로 남았다).
    assert first_key != second_key
    names = (
        await migrated_session.execute(
            text(
                """
                SELECT f.name FROM feature.features AS f
                JOIN provider_sync.source_links AS sl ON sl.feature_id = f.feature_id
                JOIN provider_sync.source_entities AS se
                  ON se.source_entity_key = sl.source_entity_key
                WHERE se.source_entity_id = 'shp:name-reload-9421'
                  AND sl.source_role = 'primary'
                """
            )
        )
    ).scalars().all()
    assert names == ["이름재적재대피소"]
