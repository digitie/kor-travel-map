"""``source_replay_repo`` — 저장된 원본(raw)을 다시 읽는 replay 읽기 (ADR-109 결정 7, T-GR-08).

geo만 바뀐 릴리스에서 쿼터 민감 dataset을 provider HTTP로 다시 받지 않고, entity head의 current
``source_records.raw_data``를 읽어 같은 record 모델·같은 변환기로 다시 적재한다. 이 모듈은 그
읽기만 갖는다 — record 모델 복원과 적재는 호출자(Dagster records resource·asset)다.

읽는 집합은 **primary link의 Feature가 ``active``인 entity**뿐이다. ``feature_repo``의
unchanged CTE(``_UNCHANGED_ACTIVE_ENTITIES_CTE``)와 같은 술어다. provider에서 사라져 retired된
entity를 읽으면 적재가 그 Feature를 되살린다 — 그래서 읽지 않는다.

keyset은 ``source_entity_key`` 오름차순이다(``provider_dataset_id`` 안). raw SQL은 이 모듈의
상수다(ADR-004). 읽기 전용이다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Final

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "CurrentSourceRecord",
    "count_active_source_entities",
    "read_current_source_records",
]


@dataclass(frozen=True, slots=True)
class CurrentSourceRecord:
    """entity head가 가리키는 current 원본 한 건.

    ``fetched_at``은 그 payload를 처음 받은 시각(``source_records``, 불변)이고 ``observed_at``은
    head의 마지막 관측 시각이다. replay 적재는 둘을 그대로 되돌려 써서 head를 전진시키지 않는다
    — replay는 provider를 관측하지 않았다.
    """

    source_entity_key: str
    source_entity_type: str
    source_entity_id: str
    raw_data: dict[str, Any]
    raw_payload_hash: str
    fetched_at: datetime
    observed_at: datetime


#: primary Feature가 ``active``인 entity — 읽기 SQL과 같은 술어(head 조인만 뺐다).
_ACTIVE_PRIMARY_EXISTS: Final = """
      EXISTS (
          SELECT 1
          FROM provider_sync.source_links AS link
          JOIN feature.features AS feature
            ON feature.feature_id = link.feature_id
          WHERE link.source_entity_key = entity.source_entity_key
            AND link.source_role = 'primary'
            AND feature.lifecycle_state = 'active'
      )
"""

_COUNT_ACTIVE_SOURCE_ENTITIES_SQL: Final = text(
    """
    SELECT count(*)
    FROM provider_sync.source_entities AS entity
    WHERE entity.provider_dataset_id = :provider_dataset_id
      AND"""
    + _ACTIVE_PRIMARY_EXISTS
)

_CURRENT_SOURCE_RECORDS_SQL: Final = text(
    """
    SELECT
        entity.source_entity_key,
        entity.source_entity_type,
        entity.source_entity_id,
        record.raw_data,
        record.raw_payload_hash,
        record.fetched_at,
        head.observed_at
    FROM provider_sync.source_entities AS entity
    JOIN provider_sync.source_entity_heads AS head
      ON head.source_entity_key = entity.source_entity_key
    JOIN provider_sync.source_records AS record
      ON record.source_record_key = head.current_source_record_key
    WHERE entity.provider_dataset_id = :provider_dataset_id
      AND entity.source_entity_key > :after_source_entity_key
      AND"""
    + _ACTIVE_PRIMARY_EXISTS
    + """
    ORDER BY entity.source_entity_key
    LIMIT :limit
    """
)


def _raw_mapping(value: object) -> dict[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        raise TypeError(f"source_records.raw_data가 object가 아니다: {type(value).__name__}")
    return value


async def read_current_source_records(
    session: AsyncSession,
    *,
    provider_dataset_id: int,
    after_source_entity_key: str = "",
    limit: int = 1000,
) -> list[CurrentSourceRecord]:
    """``provider_dataset_id``의 current 원본을 ``source_entity_key`` 다음부터 ``limit``건 읽는다.

    빈 목록이면 끝이다. 다음 페이지는 마지막 행의 ``source_entity_key``를
    ``after_source_entity_key``로 넘긴다.
    """
    if limit <= 0:
        raise ValueError("limit must be positive")
    rows = (
        await session.execute(
            _CURRENT_SOURCE_RECORDS_SQL,
            {
                "provider_dataset_id": provider_dataset_id,
                "after_source_entity_key": after_source_entity_key,
                "limit": limit,
            },
        )
    ).mappings().all()
    return [
        CurrentSourceRecord(
            source_entity_key=str(row["source_entity_key"]),
            source_entity_type=str(row["source_entity_type"]),
            source_entity_id=str(row["source_entity_id"]),
            raw_data=_raw_mapping(row["raw_data"]),
            raw_payload_hash=str(row["raw_payload_hash"]),
            fetched_at=row["fetched_at"],
            observed_at=row["observed_at"],
        )
        for row in rows
    ]


async def count_active_source_entities(
    session: AsyncSession, *, provider_dataset_id: int
) -> int:
    """primary Feature가 ``active``인 entity 수 — replay가 읽어야 할 건수(head 유무와 무관).

    replay 읽기가 이보다 적으면(head·record 누락, 읽기 도중 변경) 부분 replay다 — 호출자가
    실패시킨다.
    """
    return int(
        (
            await session.execute(
                _COUNT_ACTIVE_SOURCE_ENTITIES_SQL, {"provider_dataset_id": provider_dataset_id}
            )
        ).scalar_one()
    )
