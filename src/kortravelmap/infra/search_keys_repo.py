"""검색 비교 키(``feature.feature_search_keys``) 채우기 — 읽기 성능 계획 T-READ-06.

왜 필요한가. 검색 순위는 후보 행마다 보이는 이름을 정규화해 비교 키(NFC·공백 제거·소문자·끝 괄호
변형)와 실효 검색 그룹(이름 끝말 정규식)을 만든다. prod 2026-11-19 조용한 창 기준선에서 그 식이
지역 검색 본 질의 시간의 37~56%였다. 같은 키를 공개 Feature마다 미리 계산해 둔다.

무엇이 정본인가. 키를 만드는 식은 ``feature_repo``의 검색 질의가 키가 없을 때 쓰는 식과 같은
함수(``search_keys_select_sql``)에서 나온다. 행마다 ``keys_version``(그 SQL의 지문)·
``server_fingerprint``(PostgreSQL 판과 DB의 ctype·collation 판 — 유니코드 정규화·소문자 변환이
여기에 달려 있다)·키를 만든 ``name``·``category``를 함께 저장하고, 검색은 넷이 모두 지금과 같을
때만 저장 키를 쓴다. 서버를 올리면(판·locale) 모든 행이 맞지 않게 되어 식으로 계산되고 다음
갱신이 다시 쓴다. 그래서 이 표가 비었거나 묵어도 순위는 같다(느릴 뿐이다) — 이름이 바뀐 행은
다음 갱신 전까지 식으로 계산된다.

언제 도는가. maintenance job(``consistency_dedup_refresh``, 매일)이 dedup 갱신 뒤에 부른다.
키가 없거나 맞지 않는 공개 행만 계산해 쓰고(첫 실행 뒤로는 그날 새로 적재·변경된 행뿐이다), 공개가
아닌(사라진·비공개) 행의 키는 지운다. ``feature.features``는 읽기만 한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from sqlalchemy import text

from kortravelmap.infra.feature_repo import (
    SEARCH_KEYS_SERVER_FINGERPRINT_SQL,
    SEARCH_KEYS_VERSION,
    search_keys_select_sql,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "SearchKeysRefreshResult",
    "refresh_search_keys",
]

#: 이 refresh 한 번의 문장 시간 상한(첫 채우기는 공개 Feature 전부를 계산한다).
_REFRESH_STATEMENT_TIMEOUT: Final[str] = "15min"
_REFRESH_LOCK_KEY: Final[str] = "kortravelmap.search_keys_refresh"

_STALE_PUBLIC_FEATURES_SQL: Final[str] = f"""(
    SELECT f.feature_id, f.name, f.category
    FROM feature.public_features AS f
    WHERE NOT EXISTS (
        SELECT 1
        FROM feature.feature_search_keys AS k
        WHERE k.feature_id = f.feature_id
          AND k.keys_version = {SEARCH_KEYS_VERSION}
          AND k.server_fingerprint = {SEARCH_KEYS_SERVER_FINGERPRINT_SQL}
          AND k.name = f.name
          AND k.category = f.category
    )
)"""


def _refresh_sql() -> str:
    return f"""
WITH computed AS MATERIALIZED (
{search_keys_select_sql(_STALE_PUBLIC_FEATURES_SQL)}
),
upserted AS (
    INSERT INTO feature.feature_search_keys AS t (
        feature_id, keys_version, server_fingerprint, name, category,
        compact_name, compact_raw_name, compact_tail,
        compact_base_name, compact_paren_base_name, compact_bracket_name,
        search_group, computed_at
    )
    SELECT
        feature_id, {SEARCH_KEYS_VERSION}, {SEARCH_KEYS_SERVER_FINGERPRINT_SQL}, name, category,
        compact_name, compact_raw_name, compact_tail,
        compact_base_name, compact_paren_base_name, compact_bracket_name,
        search_group, now()
    FROM computed
    ON CONFLICT (feature_id) DO UPDATE
       SET keys_version = EXCLUDED.keys_version,
           server_fingerprint = EXCLUDED.server_fingerprint,
           name = EXCLUDED.name,
           category = EXCLUDED.category,
           compact_name = EXCLUDED.compact_name,
           compact_raw_name = EXCLUDED.compact_raw_name,
           compact_tail = EXCLUDED.compact_tail,
           compact_base_name = EXCLUDED.compact_base_name,
           compact_paren_base_name = EXCLUDED.compact_paren_base_name,
           compact_bracket_name = EXCLUDED.compact_bracket_name,
           search_group = EXCLUDED.search_group,
           computed_at = EXCLUDED.computed_at
    RETURNING 1
),
deleted AS (
    DELETE FROM feature.feature_search_keys AS t
    WHERE NOT EXISTS (
        SELECT 1 FROM feature.public_features AS f WHERE f.feature_id = t.feature_id
    )
    RETURNING 1
)
SELECT
    (SELECT count(*) FROM upserted) AS written,
    (SELECT count(*) FROM deleted) AS deleted
"""


@dataclass(frozen=True, slots=True)
class SearchKeysRefreshResult:
    """한 번의 갱신 결과 — 새로 계산해 쓴 행, 지운(공개가 아닌 Feature의) 행."""

    written: int
    deleted: int


async def refresh_search_keys(session: AsyncSession) -> SearchKeysRefreshResult:
    """키가 없거나 맞지 않는 공개 Feature의 검색 비교 키를 계산해 쓴다(호출자 transaction 안).

    ``feature.feature_search_keys``만 쓴다. ``statement_timeout``은 이 transaction에만
    ``_REFRESH_STATEMENT_TIMEOUT``으로 건다.
    """
    await session.execute(
        text("SELECT set_config('statement_timeout', :value, true)"),
        {"value": _REFRESH_STATEMENT_TIMEOUT},
    )
    # 수동 실행과 스케줄 실행이 겹치면 같은 키를 다른 순서로 upsert해 교착할 수 있다 — 직렬화한다.
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": _REFRESH_LOCK_KEY},
    )
    row = (await session.execute(text(_refresh_sql()))).one()
    return SearchKeysRefreshResult(written=int(row.written), deleted=int(row.deleted))
