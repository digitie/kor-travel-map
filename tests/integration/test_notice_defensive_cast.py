"""T-VN-06 — 오염된 notice timestamp 방어적 cast 통합 테스트 (F-9, ADR-073 Wave 0).

``detail->>'valid_end_time'``은 free-form jsonb다. 오염된 **한 행**이 직접
``CAST(... AS timestamptz)``에서 예외를 던지면 ``_PUBLIC_ACTIVE_NOTICE_FILTER_SQL``
을 공유하는 모든 공개 read(bbox/search/nearby/in-area/cluster/counts/notice IDs,
그리고 notice detail/batch 가시성 판정)가 500이 됐다.

Wave 0 완화(스키마 변경 0, migration 0): ``pg_input_is_valid``(PG16+) 가드 +
fail-closed — 파싱 불가 row는 "notice 없음"으로 강등(제외 방향, 노출 아님).
JSON null/키 부재는 기존 의미(종료시각 없음 = 활성) 유지. typed notice
재설계와 오염 관측(카운터)은 T-VN-37 소유.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from kortravelmap.infra import feature_repo

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_KST = timezone(timedelta(hours=9))
_NOW = datetime(2026, 7, 19, 12, 0, tzinfo=_KST)

_BBOX = {"min_lon": 126.9, "min_lat": 37.5, "max_lon": 127.1, "max_lat": 37.7}

# 오염 변형: 빈 문자열 / garbage / 형태만 그럴듯한 달력 불가값 / 불가능한 timezone.
# (마지막 둘은 정규식 shape 가드가 놓치는 부류 — pg_input_is_valid가 필요한 이유.)
_CORRUPTED_END_TIMES: tuple[str, ...] = (
    "",
    "garbage",
    "2026-13-40 00:00:00",
    "2026-07-19T12:00:00+99:99",
)


async def _ins_notice(
    session: AsyncSession,
    *,
    feature_id: str,
    name: str,
    valid_end_time: str | None,
    end_time_key_present: bool = True,
    kind: str = "notice",
    lon: float = 126.978,
    lat: float = 37.5665,
) -> None:
    detail: dict[str, object] = {}
    if end_time_key_present:
        detail["valid_end_time"] = valid_end_time
    await session.execute(
        text(
            """
            INSERT INTO feature.features (
                feature_id, kind, name, category, coord, status, detail,
                sido_code, sigungu_code, updated_at
            )
            VALUES (
                :feature_id, :kind, :name, '99000000',
                x_extension.ST_SetSRID(
                    x_extension.ST_MakePoint(
                        CAST(:lon AS double precision),
                        CAST(:lat AS double precision)
                    ),
                    4326
                ),
                'active', CAST(:detail AS jsonb),
                '11', '11140', CAST(:updated_at AS timestamptz)
            )
            """
        ),
        {
            "feature_id": feature_id,
            "kind": kind,
            "name": name,
            "lon": lon,
            "lat": lat,
            "detail": json.dumps(detail),
            "updated_at": _NOW,
        },
    )
    await session.flush()


async def _seed_notice_matrix(session: AsyncSession) -> dict[str, str]:
    """place 대조군 1 + notice 7종(정상 3 + 오염 4)을 심는다. suffix→id 매핑 반환."""
    ids: dict[str, str] = {}
    rows: list[tuple[str, str | None, bool]] = [
        # (suffix, valid_end_time, end_time_key_present)
        ("future-end", "2999-01-01T00:00:00+09:00", True),
        ("past-end", "2000-01-01T00:00:00+09:00", True),
        ("null-end", None, True),
        ("no-end-key", None, False),
    ]
    rows += [
        (f"corrupt-{i}", corrupted, True)
        for i, corrupted in enumerate(_CORRUPTED_END_TIMES)
    ]
    for i, (suffix, end_time, key_present) in enumerate(rows):
        fid = f"ndc:{suffix}"
        await _ins_notice(
            session,
            feature_id=fid,
            name=f"방어캐스트공지 {suffix}",
            valid_end_time=end_time,
            end_time_key_present=key_present,
            lon=126.978 + i * 0.0001,
            lat=37.5665 + i * 0.0001,
        )
        ids[suffix] = fid
    # 대조군 place — 오염 notice가 있어도 place read는 계속 동작해야 한다.
    await _ins_notice(
        session,
        feature_id="ndc:place",
        # 이름은 notice 검색어와 트라이그램이 겹치지 않게 완전히 다르게 둔다.
        name="대조군일반장소",
        valid_end_time=None,
        end_time_key_present=False,
        kind="place",
        lon=126.99,
        lat=37.57,
    )
    ids["place"] = "ndc:place"
    return ids


# 정상 규칙(회귀): 미래 종료·종료 없음(null/키 부재)은 활성, 과거 종료는 숨김.
# 완화 규칙: 오염 4종은 전부 fail-closed 제외.
_EXPECTED_VISIBLE_NOTICES: frozenset[str] = frozenset(
    {"future-end", "null-end", "no-end-key"}
)


async def test_bbox_and_search_survive_corrupted_notice_timestamp(
    migrated_session: AsyncSession,
) -> None:
    """오염 row 1건이 있어도 bbox/search가 500 없이 동작하고 오염 notice만 빠진다."""
    ids = await _seed_notice_matrix(migrated_session)
    expected = {ids[s] for s in _EXPECTED_VISIBLE_NOTICES} | {ids["place"]}

    bbox_rows = await feature_repo.features_in_bbox(
        migrated_session, **_BBOX, price_stale_hide_days=None
    )
    assert {r["feature_id"] for r in bbox_rows} == expected

    bbox_geom_rows = await feature_repo.features_in_bbox(
        migrated_session, **_BBOX, include_geometry=True, price_stale_hide_days=None
    )
    assert {r["feature_id"] for r in bbox_geom_rows} == expected

    search = await feature_repo.search_features(migrated_session, q="방어캐스트공지")
    assert {item.feature_id for item in search.items} == {
        ids[s] for s in _EXPECTED_VISIBLE_NOTICES
    }


async def test_notice_ids_and_detail_visibility_fail_closed(
    migrated_session: AsyncSession,
) -> None:
    """notice IDs(=detail/batch 가시성 판정)가 오염 row를 '없음'으로 강등한다."""
    ids = await _seed_notice_matrix(migrated_session)
    notice_ids = [fid for suffix, fid in ids.items() if suffix != "place"]

    visible = await feature_repo.public_active_notice_feature_ids(
        migrated_session, notice_ids
    )
    assert visible == {ids[s] for s in _EXPECTED_VISIBLE_NOTICES}

    # detail/batch 라우터는 notice에 대해 위 판정을 그대로 소비한다
    # (features.py `_public_feature_row`) — 오염 notice 단건 조회는 500이 아니라
    # 404로 떨어진다. view 자체(row 존재)는 cast를 하지 않으므로 500 위험이 없다.
    for i in range(len(_CORRUPTED_END_TIMES)):
        corrupted_id = ids[f"corrupt-{i}"]
        assert (
            await feature_repo.public_active_notice_feature_ids(
                migrated_session, [corrupted_id]
            )
            == set()
        )
        row = await feature_repo.get_public_feature_row(migrated_session, corrupted_id)
        assert row is not None  # 예외 없이 조회되고, 가시성 판정만 제외한다.
