"""``feature_geocode_stamp_repo`` — 지오코딩 스탬프 SQL과 outcome 판정 (ADR-109, T-GR-01).

스탬프 표 ``feature.feature_geocode_stamps``(migration 407)는 "이 Feature의 geo 유도 값을 어느 geo
데이터 지문(``geo_data_token``)으로 해석했는가"를 ``features`` 밖에 둔다. 이 모듈은 그 표의 쓰기·
stale 판정과, 행 사실에서 ``reverse_outcome``을 정하는 순수 함수를 갖는다.

규칙(ADR-109):

- **NULL 토큰 스탬프는 만들지 않는다.** run의 현재 토큰(``DatasetRef``)이 없거나 ``data_token``이
  None이면 쓰지도 덮지도 않는다(:func:`upsert_stamps`가 0건을 돌려준다) — 그렇지 않으면
  토큰 A로 찍힌 스탬프가 NULL로 덮여 지문 복구 뒤 전량 재변환이 돈다.
- **스탬프 부재가 stale이다.** ``not_called`` 스탬프는 토큰 비교 대상이 아니다.
- 현재 토큰이 None이면 stale은 **0건**이다(fail-to-current — geo 장애가 전량 재변환으로
  번지지 않는다).

raw SQL은 이 모듈의 상수다(ADR-004). commit은 호출자 책임이다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.types import Text

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping

    from sqlalchemy.ext.asyncio import AsyncSession

    from kortravelmap.dto.geo_dataset import (
        DatasetRef,
        GeoApplied,
        GeoAttemptEvidence,
        ReverseOutcome,
    )

__all__ = [
    "GeoCoverage",
    "GeocodeStamp",
    "coverage",
    "decide_outcome",
    "get_stamp",
    "is_stale",
    "select_stale_feature_ids",
    "stale_among",
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
        if evidence.geocode_obtained_code:
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
SELECT feature.upsert_provider_geocode_stamps_ex(
    CAST(:feature_ids AS uuid[]), CAST(:outcomes AS text[]), :version_token, :data_token
)
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

#: 여러 Feature 중 stale인 것 — chunk 단위 적재가 행마다 묻지 않도록 한 번에 판정한다.
_STALE_AMONG_SQL: Final = text(
    f"""
SELECT target.feature_id::text AS feature_id
  FROM unnest(CAST(:feature_ids AS uuid[])) AS target(feature_id)
  LEFT JOIN feature.feature_geocode_stamps AS stamp
    ON stamp.feature_id = target.feature_id
 WHERE {_STALE_PREDICATE}
"""
).bindparams(bindparam("feature_ids", type_=ARRAY(Text)))

#: provider dataset에 **primary** source_link를 가진 활성 Feature 중 stale인 것.
#: 첫 페이지와 다음 페이지를 **다른 문장**으로 둔다 — ``(:after IS NULL OR id > :after)``
#: 한 문장은 재사용된 prepared statement의 generic plan에서 ``feature_id`` 범위 스캔을
#: 잃을 수 있다.
_SELECT_STALE_BASE: Final[str] = f"""
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
"""
_SELECT_STALE_FIRST_SQL: Final = text(
    _SELECT_STALE_BASE + " ORDER BY feature.feature_id\n LIMIT :limit\n"
)
_SELECT_STALE_AFTER_SQL: Final = text(
    _SELECT_STALE_BASE
    + "   AND feature.feature_id > CAST(:after AS uuid)\n"
    + " ORDER BY feature.feature_id\n LIMIT :limit\n"
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
    result = await session.execute(
        _UPSERT_STAMPS_SQL,
        {
            "feature_ids": feature_ids,
            "outcomes": [outcomes[feature_id] for feature_id in feature_ids],
            "version_token": current.version_token,
            "data_token": current.data_token,
        },
    )
    return int(result.scalar_one())


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


async def stale_among(
    session: AsyncSession,
    feature_ids: Collection[str],
    current_data_token: str | None,
) -> frozenset[str]:
    """``feature_ids`` 중 stale인 것 — :func:`is_stale`의 chunk 판(한 번의 왕복).

    현재 토큰이 None이면 빈 집합이다(fail-to-current).
    """
    if current_data_token is None or not feature_ids:
        return frozenset()
    rows = (
        (
            await session.execute(
                _STALE_AMONG_SQL,
                {"feature_ids": list(feature_ids), "current_data_token": current_data_token},
            )
        )
        .scalars()
        .all()
    )
    return frozenset(str(row) for row in rows)


async def select_stale_feature_ids(
    session: AsyncSession,
    current_data_token: str | None,
    *,
    provider_dataset_id: int,
    limit: int,
    after: str | None = None,
) -> list[str]:
    """provider dataset의 stale Feature id — ``feature_id`` 오름차순, ``limit`` 상한.

    현재 토큰이 None이면 빈 목록이다. 페이지는 keyset이다 — 앞 페이지의 마지막 id를 ``after``로
    넘기면 ``feature_id > after``부터 이어진다(OFFSET 없음).

    **호출자가 geo를 쓰는 dataset으로 한정한다.** 이 함수는 dataset이 geo 의존인지 보지 않는다 —
    price/notice처럼 geo를 쓰지 않는 dataset은 스탬프가 영영 없으므로 전 행이 "stale"로 나온다.
    한정의 정본은 T-GR-04의 ``GEO_DEPENDENT_OPERATION_KEYS``다.
    """
    if current_data_token is None:
        return []
    if limit <= 0:
        raise ValueError("limit must be positive")
    params: dict[str, object] = {
        "current_data_token": current_data_token,
        "provider_dataset_id": provider_dataset_id,
        "limit": limit,
    }
    if after is None:
        rows = await session.execute(_SELECT_STALE_FIRST_SQL, params)
    else:
        rows = await session.execute(_SELECT_STALE_AFTER_SQL, {**params, "after": after})
    return [str(feature_id) for feature_id in rows.scalars().all()]


@dataclass(frozen=True)
class GeoCoverage:
    """현재 토큰 기준 스탬프 커버리지(ADR-109 결정 5.6, T-GR-04).

    분모 ``total_provider_with_coord``는 **인자로 받은 dataset**에 primary source_link를 가진
    좌표 보유 활성 Feature다. 그 집합은 네 칸으로 나뉜다 — ``stamped_current``(현재 토큰,
    ``called|geocoded``) + ``stamped_other``(다른 토큰 ``called|geocoded`` = stale) +
    ``not_called``(토큰 비교 대상 아님, ``not_called_by_kind``의 합) + ``unstamped``(스탬프 없음 =
    stale). ``excluded_by_skip``은 skip된 dataset의 같은 계수, ``unstamped_non_provider``는 provider
    기원이 아닌(primary link 없음) 좌표 보유 활성 Feature 중 스탬프 없는 것이다 — 둘 다 표시만
    한다(완료 판정에 넣지 않는다).
    """

    total_provider_with_coord: int
    stamped_current: int
    stamped_other: int
    unstamped: int
    not_called_by_kind: dict[str, int]
    excluded_by_skip: int
    unstamped_non_provider: int

    @property
    def remaining(self) -> int:
        """다시 적재해야 할 행 — ``stamped_other + unstamped``(완료 판정의 잔여)."""
        return self.stamped_other + self.unstamped


_SCOPED_FEATURES_CTE: Final[str] = """
scoped AS (
    SELECT DISTINCT feature.feature_id, feature.kind
      FROM feature.features AS feature
      JOIN provider_sync.source_links AS link
        ON link.feature_id = feature.feature_id
       AND link.source_role = 'primary'
      JOIN provider_sync.source_entities AS entity
        ON entity.source_entity_key = link.source_entity_key
     WHERE feature.lifecycle_state = 'active'
       AND feature.coord IS NOT NULL
       AND entity.provider_dataset_id = ANY(CAST(:provider_dataset_ids AS bigint[]))
)
"""

_COVERAGE_BY_KIND_SQL: Final = text(
    "WITH"
    + _SCOPED_FEATURES_CTE
    + """
SELECT scoped.kind,
       count(*) AS total,
       count(*) FILTER (
           WHERE stamp.reverse_outcome <> 'not_called'
             AND stamp.geo_data_token = CAST(:current_data_token AS text)
       ) AS stamped_current,
       count(*) FILTER (
           WHERE stamp.reverse_outcome <> 'not_called'
             AND stamp.geo_data_token IS DISTINCT FROM CAST(:current_data_token AS text)
       ) AS stamped_other,
       count(*) FILTER (WHERE stamp.feature_id IS NULL) AS unstamped,
       count(*) FILTER (WHERE stamp.reverse_outcome = 'not_called') AS not_called
  FROM scoped
  LEFT JOIN feature.feature_geocode_stamps AS stamp
    ON stamp.feature_id = scoped.feature_id
 GROUP BY scoped.kind
"""
)

_COUNT_SCOPED_SQL: Final = text("WITH" + _SCOPED_FEATURES_CTE + "SELECT count(*) FROM scoped")

_UNSTAMPED_NON_PROVIDER_SQL: Final = text(
    """
SELECT count(*)
  FROM feature.features AS feature
 WHERE feature.lifecycle_state = 'active'
   AND feature.coord IS NOT NULL
   AND NOT EXISTS (
        SELECT 1 FROM provider_sync.source_links AS link
         WHERE link.feature_id = feature.feature_id AND link.source_role = 'primary'
   )
   AND NOT EXISTS (
        SELECT 1 FROM feature.feature_geocode_stamps AS stamp
         WHERE stamp.feature_id = feature.feature_id
   )
"""
)


async def coverage(
    session: AsyncSession,
    current_data_token: str | None,
    *,
    provider_dataset_ids: Collection[int],
    skipped_provider_dataset_ids: Collection[int] = (),
) -> GeoCoverage:
    """``provider_dataset_ids``로 한정한 현재 토큰 커버리지(:class:`GeoCoverage`).

    현재 토큰이 None이면 ``called|geocoded`` 스탬프는 전부 ``stamped_other``다(비교할 현재가 없다).
    """
    ids = sorted({int(value) for value in provider_dataset_ids})
    rows = (
        (
            await session.execute(
                _COVERAGE_BY_KIND_SQL,
                {"provider_dataset_ids": ids, "current_data_token": current_data_token},
            )
        )
        .mappings()
        .all()
    )
    skipped = sorted({int(value) for value in skipped_provider_dataset_ids} - set(ids))
    excluded = (
        int(
            (
                await session.execute(_COUNT_SCOPED_SQL, {"provider_dataset_ids": skipped})
            ).scalar_one()
        )
        if skipped
        else 0
    )
    non_provider = int((await session.execute(_UNSTAMPED_NON_PROVIDER_SQL)).scalar_one())
    return GeoCoverage(
        total_provider_with_coord=sum(int(row["total"]) for row in rows),
        stamped_current=sum(int(row["stamped_current"]) for row in rows),
        stamped_other=sum(int(row["stamped_other"]) for row in rows),
        unstamped=sum(int(row["unstamped"]) for row in rows),
        not_called_by_kind={
            str(row["kind"]): int(row["not_called"]) for row in rows if int(row["not_called"])
        },
        excluded_by_skip=excluded,
        unstamped_non_provider=non_provider,
    )

