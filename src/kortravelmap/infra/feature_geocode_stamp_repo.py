"""``feature_geocode_stamp_repo`` — 행별 지오코딩 스탬프 SQL과 outcome 판정 (ADR-109 결정 1·3, T-GR-01).

스탬프 표 ``feature.feature_geocode_stamps``(migration 407)는 "이 Feature의 geo 유도 값을 어느 geo
데이터 지문(``geo_data_token``)으로 해석했는가"를 ``features`` 밖에 둔다. 이 모듈은 그 표의 쓰기·
stale 판정과, 행 사실에서 ``reverse_outcome``을 정하는 순수 함수를 갖는다.

규칙(ADR-109):

- **NULL 토큰 스탬프는 만들지 않는다.** run의 현재 토큰(``DatasetRef``)이 없거나 ``data_token``이
  None이면 쓰지도 덮지도 않는다(:func:`upsert_stamps`가 0건을 돌려준다) — 그렇지 않으면 토큰 A로 찍힌
  스탬프가 NULL로 덮여 지문 복구 뒤 전량 재변환이 돈다.
- **스탬프 부재가 stale이다.** ``not_called`` 스탬프는 토큰 비교 대상이 아니다.
- 현재 토큰이 None이면 stale은 **0건**이다(fail-to-current — geo 장애가 전량 재변환으로 번지지 않는다).

raw SQL은 이 모듈의 상수다(ADR-004). commit은 호출자 책임이다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.types import Text

if TYPE_CHECKING:
    from collections.abc import Mapping

    from sqlalchemy.ext.asyncio import AsyncSession

    from kortravelmap.dto.geo_dataset import (
        DatasetRef,
        GeoApplied,
        GeoAttemptEvidence,
        ReverseOutcome,
    )

__all__ = [
    "GeocodeStamp",
    "decide_outcome",
    "get_stamp",
    "is_stale",
    "select_stale_feature_ids",
    "upsert_stamps",
]


@dataclass(frozen=True)
class GeocodeStamp:
    """스탬프 한 행."""

    feature_id: str
    geo_version_token: str
    geo_data_token: str
    reverse_outcome: ReverseOutcome


def decide_outcome(
    geo_applied: GeoApplied,
    *,
    has_coord: bool,
    provider_code_present: bool,
    legal_dong_code_present: bool,
    evidence: GeoAttemptEvidence | None = None,
) -> ReverseOutcome | None:
    """행 사실 → ``reverse_outcome``. None이면 **스탬프를 쓰지 않는다**.

    ``docs/etl/address-geocoding.md`` §2 판정 표 — **위에서 아래로 처음 맞는 것이 답이다**
    (평가 순서가 규칙이다):

    ① run이 geo 콜러블을 하나도 넘기지 않았다(price/notice) → None(스탬프 없음).
    ② 행 evidence가 있다(MOIS) → reverse 시도 ``called``; 아니고 geocode로 코드를 받았으면
       ``geocoded``; 그 외 ``not_called``.
    ③ reverse를 넘겼고 좌표가 있다 → ``called``(payload 코드를 썼어도 — geo가 명칭·우편번호 등을
       채운다; 빈 답이어도 시도했으면 ``called``).
    ④ geocode를 넘겼고 좌표가 없으며 법정동코드가 생겼고 provider 코드가 없다 → ``geocoded``.
    ⑤ 그 외 → ``not_called``(geo 유도 값 0개).

    ``provider_code_present``는 bundle source_record payload에 ``legal_dong_code``가 있는가,
    ``legal_dong_code_present``는 이 행이 결국 법정동코드를 갖게 됐는가다.
    """
    if not geo_applied.reverse and not geo_applied.geocode:
        return None
    if evidence is not None:
        if evidence.reverse_attempted:
            return "called"
        if evidence.geocode_attempted and evidence.geocode_obtained_code:
            return "geocoded"
        return "not_called"
    if geo_applied.reverse and has_coord:
        return "called"
    if (
        geo_applied.geocode
        and not has_coord
        and legal_dong_code_present
        and not provider_code_present
    ):
        return "geocoded"
    return "not_called"


_UPSERT_STAMPS_SQL: Final = text(
    """
INSERT INTO feature.feature_geocode_stamps AS stamp (
    feature_id, geo_version_token, geo_data_token, reverse_outcome, stamped_at
)
SELECT input.feature_id::uuid, :version_token, :data_token, input.reverse_outcome, now()
  FROM unnest(:feature_ids, :outcomes) AS input(feature_id, reverse_outcome)
ON CONFLICT (feature_id) DO UPDATE
   SET geo_version_token = EXCLUDED.geo_version_token,
       geo_data_token = EXCLUDED.geo_data_token,
       reverse_outcome = EXCLUDED.reverse_outcome,
       stamped_at = EXCLUDED.stamped_at
"""
).bindparams(
    bindparam("feature_ids", type_=ARRAY(Text)),
    bindparam("outcomes", type_=ARRAY(Text)),
)

_GET_STAMP_SQL: Final = text(
    """
SELECT feature_id::text AS feature_id, geo_version_token, geo_data_token, reverse_outcome
  FROM feature.feature_geocode_stamps
 WHERE feature_id = CAST(:feature_id AS uuid)
"""
)

#: stale 술어 — 스탬프 없음, 또는 ``not_called``가 아니면서 토큰이 현재와 다르다.
_STALE_PREDICATE: Final[str] = (
    "(stamp.feature_id IS NULL OR (stamp.reverse_outcome <> 'not_called' "
    "AND stamp.geo_data_token IS DISTINCT FROM :current_data_token))"
)

_IS_STALE_SQL: Final = text(
    f"""
SELECT {_STALE_PREDICATE} AS stale
  FROM (SELECT CAST(:feature_id AS uuid) AS feature_id) AS target
  LEFT JOIN feature.feature_geocode_stamps AS stamp
    ON stamp.feature_id = target.feature_id
"""
)

#: provider dataset에 **primary** source_link를 가진 활성 Feature 중 stale인 것.
_SELECT_STALE_SQL: Final = text(
    f"""
SELECT feature.feature_id::text AS feature_id
  FROM feature.features AS feature
  LEFT JOIN feature.feature_geocode_stamps AS stamp
    ON stamp.feature_id = feature.feature_id
 WHERE feature.lifecycle_state = 'active'
   AND EXISTS (
        SELECT 1
          FROM provider_sync.source_links AS link
          JOIN provider_sync.source_entities AS entity
            ON entity.source_entity_key = link.source_entity_key
         WHERE link.feature_id = feature.feature_id
           AND link.source_role = 'primary'
           AND entity.provider_dataset_id = :provider_dataset_id
   )
   AND {_STALE_PREDICATE}
 ORDER BY feature.feature_id
 LIMIT :limit
"""
)


async def upsert_stamps(
    session: AsyncSession,
    *,
    current: DatasetRef | None,
    outcomes: Mapping[str, ReverseOutcome],
) -> int:
    """run의 현재 토큰으로 스탬프를 쓴다(있으면 덮는다). 쓴 행 수를 돌려준다.

    ``current``가 None이거나 ``current.data_token``이 None이면 **아무것도 쓰지 않는다**(0) —
    NULL 토큰 스탬프는 없다(ADR-109 결정 1·2). ``outcomes``는 ``feature_id → reverse_outcome``이고,
    :func:`decide_outcome`이 None을 낸 행은 호출자가 빼고 넘긴다.
    """
    if current is None or current.data_token is None or not outcomes:
        return 0
    feature_ids = list(outcomes)
    await session.execute(
        _UPSERT_STAMPS_SQL,
        {
            "feature_ids": feature_ids,
            "outcomes": [outcomes[feature_id] for feature_id in feature_ids],
            "version_token": current.version_token,
            "data_token": current.data_token,
        },
    )
    return len(feature_ids)


async def get_stamp(session: AsyncSession, feature_id: str) -> GeocodeStamp | None:
    """스탬프 한 행(없으면 None)."""
    row = (await session.execute(_GET_STAMP_SQL, {"feature_id": feature_id})).mappings().first()
    if row is None:
        return None
    return GeocodeStamp(
        feature_id=str(row["feature_id"]),
        geo_version_token=str(row["geo_version_token"]),
        geo_data_token=str(row["geo_data_token"]),
        reverse_outcome=row["reverse_outcome"],
    )


async def is_stale(
    session: AsyncSession,
    feature_id: str,
    current_data_token: str | None,
) -> bool:
    """이 Feature의 스탬프가 현재 토큰 기준으로 낡았는가.

    현재 토큰이 None이면 언제나 False다(fail-to-current). 스탬프가 없으면 True,
    ``not_called``면 False, 그 외에는 ``geo_data_token``이 현재와 다를 때 True.
    """
    if current_data_token is None:
        return False
    value = (
        await session.execute(
            _IS_STALE_SQL,
            {"feature_id": feature_id, "current_data_token": current_data_token},
        )
    ).scalar_one()
    return bool(value)


async def select_stale_feature_ids(
    session: AsyncSession,
    current_data_token: str | None,
    *,
    provider_dataset_id: int,
    limit: int,
) -> list[str]:
    """provider dataset의 stale Feature id(정렬, ``limit`` 상한). 현재 토큰이 None이면 빈 목록."""
    if current_data_token is None:
        return []
    if limit <= 0:
        raise ValueError("limit must be positive")
    rows = await session.execute(
        _SELECT_STALE_SQL,
        {
            "current_data_token": current_data_token,
            "provider_dataset_id": provider_dataset_id,
            "limit": limit,
        },
    )
    return [str(feature_id) for feature_id in rows.scalars().all()]

