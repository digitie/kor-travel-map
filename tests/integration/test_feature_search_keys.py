"""미리 계산한 검색 비교 키(T-READ-06, migration 455) 통합 시험.

- 검색 평가 묶음(``tests/integration/data/search_eval_queries.txt``)과 이 파일이 심은 이름의
  검색어에서 표가 빈 경로(종전 식)와 표 경로의 ``(feature_id, rank)`` 순서가 첫 3페이지까지
  같다. 표에 없는 행(새 Feature)·이름이 바뀐 행·지문이 다른 행이 섞여도 같다.
- refresh는 키가 없거나 맞지 않는 행만 쓰고(두 번째는 0), 공개가 아닌 Feature의 키를 지운다.
- 저장 키가 지금 행과 맞지 않으면 쓰지 않는다(일부러 틀린 키를 심어도 순위가 같다).

DB는 세션 내내 공유되므로 이름은 이 파일 고유("…키검")로 짓는다. 각 시험은 transaction 안에서 돌고
되돌린다(``migrated_session``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest
from sqlalchemy import text

from kortravelmap.infra import feature_repo
from kortravelmap.infra.search_keys_repo import refresh_search_keys
from tests.integration._subtype_seed import seed_feature_subtype

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_SEARCH_CURSOR_KEY = b"integration-feature-search-keys-cursor-key-00000001"
_EVAL_QUERIES = Path(__file__).resolve().parent / "data" / "search_eval_queries.txt"
_ANDONG = ("47170", "경상북도", "안동시")
_BUSAN = ("26350", "부산광역시", "해운대구")
_M = 0.000009  # 위도 1 m

#: (라벨, 이름, 분류, 지역, 경도, 위도) — 비교 키의 갈래(보이는 이름·tail·끝 라틴 괄호·끝 한글
#: 괄호·끝말 그룹·공백 변형·접기)를 모두 지나는 이름.
_SEEDS: tuple[tuple[str, str, str, tuple[str, str, str], float, float], ...] = (
    ("dosan", "도산키검서원", "01070100", _ANDONG, 128.8430, 36.7270),
    ("dosan_full", "안동 도산키검서원", "01000000", _ANDONG, 128.8440, 36.7280),
    ("dosan_parking", "도산키검서원", "06010000", _ANDONG, 128.8450, 36.7290),
    ("dosan_parking_named", "도산키검서원 주차장", "06010000", _ANDONG, 128.8460, 36.7300),
    ("hahoe", "하회키검(안동)", "01020100", _ANDONG, 128.5180, 36.5390),
    ("hahoe_dup", "하회키검", "01000000", _ANDONG, 128.5181, 36.5391),
    ("hahoe_lodging", "하회키검(민박)", "03050200", _ANDONG, 128.5200, 36.5400),
    ("jw", "JW 키검 호텔 (JW Kigeom Hotel)", "03010100", _BUSAN, 129.1600, 35.1600),
    ("cafe", "해운대 키검카페", "01000000", _BUSAN, 129.1610, 35.1610),
    ("cafe_space", "해운대　키검 카페", "02000000", _BUSAN, 129.1620, 35.1620),
    ("pension", "키검 펜션", "01000000", _BUSAN, 129.1630, 35.1630),
    ("station", "키검역", "06030300", _BUSAN, 129.1640, 35.1640),
)
_SEED_QUERIES: tuple[str, ...] = (
    "도산키검서원",
    "안동 도산키검서원",
    "도산키검서원 주차장",
    "하회키검",
    "안동 하회키검",
    "JW 키검 호텔",
    "JW Kigeom Hotel",
    "키검카페",
    "해운대 키검 카페",
    "키검 펜션",
    "키검역",
    "키검",
)


def _uuid(label: str) -> str:
    raw = bytearray(uuid5(NAMESPACE_URL, f"search-keys:{label}").bytes)
    raw[6] = (raw[6] & 0x0F) | 0x70
    raw[8] = (raw[8] & 0x3F) | 0x80
    return str(UUID(bytes=bytes(raw)))


def _eval_queries() -> list[str]:
    lines = _EVAL_QUERIES.read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.startswith("#")]


async def _seed(session: AsyncSession) -> dict[str, str]:
    ids: dict[str, str] = {}
    for label, name, category, region, lon, lat in _SEEDS:
        feature_id = _uuid(label)
        sigungu_code, sido_name, sigungu_name = region
        await session.execute(
            text(
                """
                INSERT INTO feature.features (
                    feature_id, kind, name, category, coord, address, sido_code, sigungu_code,
                    lifecycle_state, publication_state, quality_state
                )
                VALUES (
                    CAST(:feature_id AS uuid), 'place', :name, :category,
                    x_extension.ST_SetSRID(
                        x_extension.ST_MakePoint(
                            CAST(:lon AS double precision), CAST(:lat AS double precision)
                        ),
                        4326
                    ),
                    CAST(:address AS jsonb), :sido_code, :sigungu_code,
                    'active', 'published', 'valid'
                )
                """
            ),
            {
                "feature_id": feature_id,
                "name": name,
                "category": category,
                "lon": lon,
                "lat": lat,
                "address": json.dumps(
                    {"sido_name": sido_name, "sigungu_name": sigungu_name}, ensure_ascii=False
                ),
                "sido_code": sigungu_code[:2],
                "sigungu_code": sigungu_code,
            },
        )
        await seed_feature_subtype(session, feature_id=feature_id, kind="place")
        ids[label] = feature_id
    await session.flush()
    return ids


async def _orders(session: AsyncSession, queries: list[str]) -> dict[str, list[tuple[str, int]]]:
    """검색어마다 첫 3페이지(페이지당 3건)의 ``(feature_id, rank)`` — cursor도 지난다."""
    orders: dict[str, list[tuple[str, int]]] = {}
    for q in queries:
        rows: list[tuple[str, int]] = []
        cursor: str | None = None
        for _ in range(3):
            page = await feature_repo.search_features(
                session,
                q=q,
                page_size=3,
                cursor=cursor,
                cursor_signing_key=_SEARCH_CURSOR_KEY,
            )
            rows += [(item.feature_id, int(item.rank or 0)) for item in page.items]
            cursor = page.next_cursor
            if cursor is None:
                break
        orders[q] = rows
    return orders


async def _clear_keys(session: AsyncSession) -> None:
    await session.execute(text("DELETE FROM feature.feature_search_keys"))


async def test_table_path_keeps_the_order_of_the_expression_path(
    migrated_session: AsyncSession,
) -> None:
    await _seed(migrated_session)
    queries = _eval_queries() + list(_SEED_QUERIES)
    assert len(_eval_queries()) >= 40

    await _clear_keys(migrated_session)
    expression_path = await _orders(migrated_session, queries)
    # 심은 이름의 검색어는 실제로 행을 낸다 — 빈 결과끼리 같은 것은 증거가 아니다.
    assert all(expression_path[q] for q in _SEED_QUERIES), expression_path

    written = (await refresh_search_keys(migrated_session)).written
    assert written >= len(_SEEDS)
    assert await _orders(migrated_session, queries) == expression_path

    # 새 Feature(표에 없음)·이름이 바뀐 행(옛 이름의 키)·지문이 다른 행이 섞인다. 틀린 키 값은
    # 쓰이면 순위가 바뀌도록 일부러 엉뚱하게 둔다.
    seeded = [_uuid(label) for label, *_ in _SEEDS]
    await migrated_session.execute(
        text(
            "DELETE FROM feature.feature_search_keys"
            " WHERE feature_id = ANY(CAST(:ids AS uuid[]))"
        ),
        {"ids": seeded[0::4]},
    )
    await migrated_session.execute(
        text(
            "UPDATE feature.feature_search_keys"
            " SET name = name || '옛', compact_name = 'zzz', compact_tail = 'zzz',"
            " compact_paren_base_name = 'zzz', search_group = 9"
            " WHERE feature_id = ANY(CAST(:ids AS uuid[]))"
        ),
        {"ids": seeded[1::4]},
    )
    await migrated_session.execute(
        text(
            "UPDATE feature.feature_search_keys"
            " SET keys_version = keys_version + 1, compact_name = 'zzz', search_group = 9"
            " WHERE feature_id = ANY(CAST(:ids AS uuid[]))"
        ),
        {"ids": seeded[2::4]},
    )
    # 서버 지문이 다른 행(PostgreSQL 판·locale이 바뀐 뒤 남은 키).
    await migrated_session.execute(
        text(
            "UPDATE feature.feature_search_keys"
            " SET server_fingerprint = 'other-server', compact_name = 'zzz', search_group = 9"
            " WHERE feature_id = ANY(CAST(:ids AS uuid[]))"
        ),
        {"ids": seeded[3::4]},
    )
    assert await _orders(migrated_session, queries) == expression_path


async def test_search_reads_stored_keys_when_the_guard_matches(
    migrated_session: AsyncSession,
) -> None:
    """지문·이름·분류가 맞는 저장 키는 실제로 쓰인다 — 틀린 값을 심으면 순위가 바뀐다.

    위 동등 시험이 표를 전혀 읽지 않아도 초록이 되는 것을 막는다.
    """
    ids = await _seed(migrated_session)
    await refresh_search_keys(migrated_session)

    async def station_rank() -> int:
        page = await feature_repo.search_features(
            migrated_session, q="키검역", page_size=50, cursor_signing_key=_SEARCH_CURSOR_KEY
        )
        ranks = {item.feature_id: int(item.rank or 0) for item in page.items}
        return ranks[ids["station"]]

    honest = await station_rank()
    await migrated_session.execute(
        text(
            "UPDATE feature.feature_search_keys"
            " SET compact_name = 'zzz', compact_tail = 'zzz', search_group = 9"
            " WHERE feature_id = CAST(:id AS uuid)"
        ),
        {"id": ids["station"]},
    )
    assert await station_rank() != honest


async def test_refresh_writes_only_missing_or_stale_rows_and_drops_non_public(
    migrated_session: AsyncSession,
) -> None:
    ids = await _seed(migrated_session)
    await refresh_search_keys(migrated_session)
    again = await refresh_search_keys(migrated_session)
    assert again.written == 0, again
    assert again.deleted == 0, again

    # 이름이 바뀐 행은 다음 refresh가 새 이름으로 다시 쓴다.
    await migrated_session.execute(
        text(
            "UPDATE feature.features SET name = '도산키검서원 별관'"
            " WHERE feature_id = CAST(:id AS uuid)"
        ),
        {"id": ids["dosan"]},
    )
    # 공개 Feature가 아닌(사라진) 행의 키는 지운다.
    orphan = _uuid("orphan")
    await migrated_session.execute(
        text(
            "INSERT INTO feature.feature_search_keys"
            " (feature_id, keys_version, server_fingerprint, name, category, search_group)"
            " VALUES (CAST(:id AS uuid), :version, 'x', '사라진키검', '01000000', 0)"
        ),
        {"id": orphan, "version": feature_repo.SEARCH_KEYS_VERSION},
    )
    result = await refresh_search_keys(migrated_session)
    assert result.written == 1, result
    assert result.deleted == 1, result
    stored = (
        await migrated_session.execute(
            text(
                "SELECT feature_id::text AS id, keys_version, name, compact_name"
                " FROM feature.feature_search_keys WHERE feature_id = ANY(CAST(:ids AS uuid[]))"
            ),
            {"ids": [ids["dosan"], orphan]},
        )
    ).mappings().all()
    assert [dict(row) for row in stored] == [
        {
            "id": ids["dosan"],
            "keys_version": feature_repo.SEARCH_KEYS_VERSION,
            "name": "도산키검서원 별관",
            "compact_name": "도산키검서원별관",
        }
    ]


async def test_stored_keys_match_the_query_expressions(
    migrated_session: AsyncSession,
) -> None:
    """refresh가 쓴 키는 검색 질의가 식으로 계산하는 값과 같다(주차장 표시 이름 포함)."""
    ids = await _seed(migrated_session)
    await refresh_search_keys(migrated_session)
    stored = {
        row.feature_id: row
        for row in (
            await migrated_session.execute(
                text(
                    "SELECT feature_id::text AS feature_id, compact_name, compact_raw_name,"
                    " compact_tail, compact_base_name, compact_paren_base_name,"
                    " compact_bracket_name, search_group"
                    " FROM feature.feature_search_keys"
                    " WHERE feature_id = ANY(CAST(:ids AS uuid[]))"
                ),
                {"ids": list(ids.values())},
            )
        ).all()
    }
    assert set(stored) == set(ids.values())
    parking = stored[ids["dosan_parking"]]
    assert parking.compact_name == "도산키검서원주차장"
    assert parking.compact_raw_name == "도산키검서원"
    jw = stored[ids["jw"]]
    assert jw.compact_base_name == "jw키검호텔"
    assert jw.compact_bracket_name == "jwkigeomhotel"
    assert stored[ids["hahoe"]].compact_paren_base_name == "하회키검"
    assert stored[ids["cafe_space"]].compact_tail == "키검카페"
    # 관광으로 저장됐지만 이름 끝말이 숙박이면 숙박 그룹(1)이다.
    assert stored[ids["pension"]].search_group == 1
