"""검색 인지도(``feature.feature_search_prominence``) 산출 — 2026-11-11 검색 순위 점검 P6.

왜 필요한가. 검색 순위(``feature_repo`` ``search_rank``)의 모든 자리가 같으면 종전에는 trigram
유사도·``feature_id``가 순서를 정했다. 그래서 "신륵사"의 1위가 제천 신륵사(여주 신륵사와 같은
분류·같은 유사도)였고, "강화 펜션"은 짧은 이름의 MOIS 단독 펜션이 TourAPI·MCST가 소개하는 펜션
앞에 섰다. 인지도는 그 동점을 가르는 **순위 안의 마지막 자리**다(유사도보다 앞).

무엇을 세는가(장소 ``kind='place'``·좌표 있는 공개 행마다, 0~9).

- 언급 원천 수: 같은 이름(공백·대소문자·끝 괄호 무시)으로 ``_PROMINENCE_CLUSTER_RADIUS_M`` 안에
  있는 공개 place 무리(자기 포함)의 source link가 가리키는 **서로 다른 provider dataset** 수.
  같은 장소를 여러 원천이 따로 싣는 것 자체가 "알려진 곳"이라는 신호다. 상한
  ``_PROMINENCE_MENTION_CAP``.
- 국가유산·TourAPI: 그 무리의 원천에 ``python-krheritage-api``·``python-visitkorea-api``가 있으면
  ``_PROMINENCE_CURATED_BONUS``.
- 딸린 국가유산: ``_PROMINENCE_HERITAGE_RADIUS_M`` 안의 국가유산 행 가운데 이름 낱말 하나가 이
  행의 이름과 같은 것("신륵사(여주)" ↔ "여주 신륵사 조사당") 수, 상한 ``_PROMINENCE_HERITAGE_CAP``.
- MOIS 단독: 무리의 원천이 전부 ``python-mois-api``(인허가 대장)이면 0 — 영업 신고만 있는 행은
  소개된 적 없는 곳이다.

언제 도는가. 원천 적재가 끝나고 dedup 후보 갱신이 도는 maintenance job(``consistency_dedup_
refresh``, 매일)이 dedup 갱신 뒤에 부른다. 새로 적재된 행은 다음 갱신 전까지 표에 없고, 검색은
그 행을 ``SEARCH_PROMINENCE_DEFAULT``(1 — 원천 하나)로 본다. 값이 바뀐 행만 쓴다(첫 실행 뒤로는
쓰기가 적다). 표에만 쓰고 ``feature.features``는 건드리지 않는다(Feature 쓰기 문 밖 — 검색 전용
파생값).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "SEARCH_PROMINENCE_DEFAULT",
    "SEARCH_PROMINENCE_MAX",
    "SearchProminenceRefreshResult",
    "refresh_search_prominence",
]

#: 인지도의 범위 — 검색 순위의 한 자리(0~9)다.
SEARCH_PROMINENCE_MAX: Final[int] = 9
#: 표에 행이 없는(아직 갱신 전인) Feature의 인지도 — 원천 하나와 같다.
SEARCH_PROMINENCE_DEFAULT: Final[int] = 1

_PROMINENCE_CLUSTER_RADIUS_M: Final[int] = 300
_PROMINENCE_HERITAGE_RADIUS_M: Final[int] = 1_000
_PROMINENCE_MENTION_CAP: Final[int] = 4
_PROMINENCE_CURATED_BONUS: Final[int] = 2
_PROMINENCE_HERITAGE_CAP: Final[int] = 3
#: 소개·지정 원천(국가유산청·TourAPI).
_CURATED_PROVIDERS: Final[tuple[str, ...]] = ("python-krheritage-api", "python-visitkorea-api")
_HERITAGE_PROVIDER: Final[str] = "python-krheritage-api"
#: 인허가 대장(영업 신고) 원천.
_LICENSE_PROVIDER: Final[str] = "python-mois-api"
#: 이 refresh 한 번의 문장 시간 상한(prod 2026-11-11 실측은 ``docs`` 참조).
_REFRESH_STATEMENT_TIMEOUT: Final[str] = "15min"

if not (
    0 <= SEARCH_PROMINENCE_DEFAULT <= SEARCH_PROMINENCE_MAX
    and _PROMINENCE_MENTION_CAP + _PROMINENCE_CURATED_BONUS + _PROMINENCE_HERITAGE_CAP
    == SEARCH_PROMINENCE_MAX
):  # pragma: no cover — 상수 검사
    raise RuntimeError("search prominence parts must add up to SEARCH_PROMINENCE_MAX")

#: 검색 비교 키와 같은 공백 집합(``feature_repo.SEARCH_WHITESPACE_CODEPOINTS``). infra 안의
#: 순환 import를 피하려고 값만 가져오지 않고 같은 함수에서 SQL 조각을 받는다.


def _name_key_sql(expression: str) -> str:
    """이름 → 접기 키(공백·대소문자 무시, NFC, 끝 괄호 제거). ``feature_repo``의 접기 키와 같다."""
    from kortravelmap.infra.feature_repo import (
        _SEARCH_DEDUP_TRAILING_BRACKET,
        _search_compact_sql,
    )

    compact = _search_compact_sql(expression)
    return f"regexp_replace({compact}, '{_SEARCH_DEDUP_TRAILING_BRACKET}', '')"


def _quoted(values: tuple[str, ...]) -> str:
    for value in values:
        if "'" in value or "\\" in value or ":" in value:
            raise ValueError(f"provider name is not SQL-literal safe: {value!r}")
    return ", ".join(f"'{value}'" for value in values)


def _prominence_select_sql() -> str:
    """Feature마다 ``(feature_id, prominence, dataset_count, heritage_items)`` — 읽기 전용."""
    return f"""
WITH places AS MATERIALIZED (
    SELECT f.feature_id, f.coord_5179, {_name_key_sql("f.name")} AS name_key
    FROM feature.public_features AS f
    WHERE f.kind = 'place' AND f.coord_5179 IS NOT NULL
),
links AS MATERIALIZED (
    SELECT DISTINCT sl.feature_id, pd.provider, pd.provider || ':' || pd.dataset_key AS dataset
    FROM provider_sync.source_links AS sl
    JOIN provider_sync.source_entities AS se ON se.source_entity_key = sl.source_entity_key
    JOIN provider_sync.provider_datasets AS pd
      ON pd.provider_dataset_id = se.provider_dataset_id
    WHERE sl.feature_id IN (SELECT feature_id FROM places)
),
mentions AS (
    -- 같은 이름 무리(반경 안, 자기 포함)의 서로 다른 원천. 이름 같음으로 해시 결합한 뒤 거리를
    -- 본다.
    SELECT
        a.feature_id,
        count(DISTINCT l.dataset) AS dataset_count,
        bool_or(l.provider IN ({_quoted(_CURATED_PROVIDERS)})) AS curated,
        bool_and(l.provider = '{_LICENSE_PROVIDER}') AS license_only
    FROM places AS a
    JOIN places AS b
      ON b.name_key = a.name_key
     AND x_extension.ST_DWithin(a.coord_5179, b.coord_5179, {_PROMINENCE_CLUSTER_RADIUS_M})
    JOIN links AS l ON l.feature_id = b.feature_id
    WHERE a.name_key <> ''
    GROUP BY a.feature_id
),
heritage_tokens AS (
    SELECT DISTINCT h.feature_id, h.coord_5179, token
    FROM places AS h
    JOIN links AS l ON l.feature_id = h.feature_id AND l.provider = '{_HERITAGE_PROVIDER}'
    JOIN feature.features AS hf ON hf.feature_id = h.feature_id
    CROSS JOIN LATERAL regexp_split_to_table(
        lower(normalize(btrim(hf.name), NFC)), '[[:space:]]+'
    ) AS token
    WHERE char_length(token) >= 2
),
heritage AS (
    SELECT a.feature_id, count(DISTINCT t.feature_id) AS heritage_items
    FROM places AS a
    JOIN heritage_tokens AS t
      ON t.token = a.name_key
     AND x_extension.ST_DWithin(a.coord_5179, t.coord_5179, {_PROMINENCE_HERITAGE_RADIUS_M})
    WHERE char_length(a.name_key) >= 2
    GROUP BY a.feature_id
)
SELECT
    p.feature_id,
    CAST(
        CASE
          WHEN m.license_only IS TRUE THEN 0
          ELSE least(
            {SEARCH_PROMINENCE_MAX},
            least(coalesce(m.dataset_count, 1), {_PROMINENCE_MENTION_CAP})
            + CASE WHEN m.curated IS TRUE THEN {_PROMINENCE_CURATED_BONUS} ELSE 0 END
            + least(coalesce(h.heritage_items, 0), {_PROMINENCE_HERITAGE_CAP})
          )
        END AS smallint
    ) AS prominence,
    CAST(least(coalesce(m.dataset_count, 0), 32767) AS smallint) AS dataset_count,
    CAST(least(coalesce(h.heritage_items, 0), 32767) AS smallint) AS heritage_items
FROM places AS p
LEFT JOIN mentions AS m ON m.feature_id = p.feature_id
LEFT JOIN heritage AS h ON h.feature_id = p.feature_id
"""


def _refresh_sql() -> str:
    return f"""
WITH computed AS MATERIALIZED (
{_prominence_select_sql()}
),
upserted AS (
    INSERT INTO feature.feature_search_prominence AS t (
        feature_id, prominence, dataset_count, heritage_items, computed_at
    )
    SELECT feature_id, prominence, dataset_count, heritage_items, now()
    FROM computed
    ON CONFLICT (feature_id) DO UPDATE
       SET prominence = EXCLUDED.prominence,
           dataset_count = EXCLUDED.dataset_count,
           heritage_items = EXCLUDED.heritage_items,
           computed_at = EXCLUDED.computed_at
     WHERE (t.prominence, t.dataset_count, t.heritage_items)
           IS DISTINCT FROM
           (EXCLUDED.prominence, EXCLUDED.dataset_count, EXCLUDED.heritage_items)
    RETURNING 1
),
deleted AS (
    DELETE FROM feature.feature_search_prominence AS t
    WHERE NOT EXISTS (SELECT 1 FROM computed AS c WHERE c.feature_id = t.feature_id)
    RETURNING 1
)
SELECT
    (SELECT count(*) FROM computed) AS computed,
    (SELECT count(*) FROM upserted) AS changed,
    (SELECT count(*) FROM deleted) AS deleted
"""


@dataclass(frozen=True, slots=True)
class SearchProminenceRefreshResult:
    """한 번의 갱신 결과 — 계산한 행, 바뀐(새로 쓴) 행, 지운(공개 place가 아닌) 행."""

    computed: int
    changed: int
    deleted: int


async def refresh_search_prominence(session: AsyncSession) -> SearchProminenceRefreshResult:
    """공개 place 전부의 검색 인지도를 다시 계산해 바뀐 행만 쓴다(호출자 transaction 안).

    ``feature.feature_search_prominence``만 쓴다. ``statement_timeout``은 이 transaction에만
    ``_REFRESH_STATEMENT_TIMEOUT``으로 건다.
    """
    await session.execute(
        text("SELECT set_config('statement_timeout', :value, true)"),
        {"value": _REFRESH_STATEMENT_TIMEOUT},
    )
    row = (await session.execute(text(_refresh_sql()))).one()
    return SearchProminenceRefreshResult(
        computed=int(row.computed), changed=int(row.changed), deleted=int(row.deleted)
    )
