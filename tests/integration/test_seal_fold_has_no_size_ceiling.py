"""causal seal의 fold가 **payload 크기와 무관**해야 한다 (ADR-099 1단계).

## 무엇이 막혀 있었나

종전 fold는 데이터셋 전 행의 13항 배열을 하나의 `jsonb_agg` 배열로 모은 뒤 그
text를 sha256했다. 크기가 O(행수 × 행당 payload)라 PostgreSQL의 jsonb 배열 상한
268,435,455 bytes에 걸린다. 2026-09-19 prod:

    feature_route_krforest_mountain_trails_job
      4시간18분 지오코딩 완료 → 적재 → 봉인에서
      ProgramLimitExceededError: total size of jsonb array elements ...
      → 적재와 봉인이 같은 트랜잭션이라 57,060행이 통째로 롤백

## 이 검사가 세는 것

"천장이 사라졌는가"를 직접 재려면 256 MB짜리 데이터가 필요하다. 대신 **천장이
생기는 원인**을 잰다 — 중간 집계물의 길이가 payload 크기에 따라 자라는가.

    옛 fold:  jsonb_agg(13항)::text        길이 ∝ 행수 × 행당 payload
    새 fold:  string_agg(digest(...), '')  길이 = 행수 × 32 B, payload와 무관

그래서 **행수는 같고 payload만 1,000배 다른 두 입력**을 주고, 새 fold의 중간
집계 길이가 **똑같은지**를 센다. 같다면 그 fold는 payload에 비례해 자랄 수 없고,
그것이 곧 천장 제거의 증명이다. 옛 fold를 같은 입력에 돌려 **실제로 자라는 것**도
함께 보여 이 검사가 항진명제가 아님을 그 자리에서 증명한다.

나머지 셋은 fold를 바꾸면서 잃기 쉬운 성질이다 — 탐지력, 순서 무관, 빈 집합.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

#: per-row digest의 폭. sha256이므로 32바이트이고, 고정폭이라 구분자 없이 이어
#: 붙여도 경계가 모호해지지 않는다.
_DIGEST_BYTES = 32

#: 새 fold의 중간 집계식. 마이그레이션 사이드카와 **같은 식**이어야 의미가 있다.
_NEW_FOLD_INTERMEDIATE = """
SELECT length(COALESCE(string_agg(
         x_extension.digest(convert_to(jsonb_build_array(sample.payload)::text, 'UTF8'),
                            'sha256'),
         ''::bytea ORDER BY sample.ordinal), ''::bytea)) AS intermediate_bytes
  FROM sample
"""

#: 옛 fold의 중간 집계식. 대조군이다.
_OLD_FOLD_INTERMEDIATE = """
SELECT length(COALESCE(jsonb_agg(jsonb_build_array(sample.payload)
                                 ORDER BY sample.ordinal), '[]'::jsonb)::text)
         AS intermediate_bytes
  FROM sample
"""

_SAMPLE_CTE = """
WITH sample AS (
  SELECT g AS ordinal, repeat('x', :width) AS payload
    FROM generate_series(1, :rows) AS g
)
"""


async def _intermediate_bytes(
    session: AsyncSession, expression: str, *, rows: int, width: int
) -> int:
    result = await session.execute(
        text(_SAMPLE_CTE + expression), {"rows": rows, "width": width}
    )
    return int(result.scalar_one())


async def test_new_fold_does_not_grow_with_payload_size(
    migrated_session: AsyncSession,
) -> None:
    """**핵심.** 행수가 같으면 payload가 1,000배여도 중간 집계 길이가 같다."""

    rows = 64
    small = await _intermediate_bytes(migrated_session, _NEW_FOLD_INTERMEDIATE, rows=rows, width=8)
    large = await _intermediate_bytes(
        migrated_session, _NEW_FOLD_INTERMEDIATE, rows=rows, width=8_000
    )

    assert small == large, (
        "새 fold의 중간 집계가 payload 크기에 따라 자란다 — 천장이 그대로 있다는 뜻이다. "
        f"payload 8B일 때 {small}, 8,000B일 때 {large}."
    )
    assert small == rows * _DIGEST_BYTES, (
        f"중간 집계 길이가 행수×{_DIGEST_BYTES}B가 아니다({small}) — per-row digest가 "
        "고정폭이 아니거나 구분자가 끼어들었다."
    )


async def test_the_old_fold_really_did_grow(migrated_session: AsyncSession) -> None:
    """**항진명제 방지.** 대조군이 실제로 자라야 위 검사가 무언가를 말한다."""

    rows = 64
    small = await _intermediate_bytes(migrated_session, _OLD_FOLD_INTERMEDIATE, rows=rows, width=8)
    large = await _intermediate_bytes(
        migrated_session, _OLD_FOLD_INTERMEDIATE, rows=rows, width=8_000
    )

    assert large > small * 100, (
        "옛 fold가 payload에 비례해 자라지 않는다 — 이 검사의 전제가 틀렸다는 뜻이므로 "
        f"위 검사도 다시 봐야 한다. 8B일 때 {small}, 8,000B일 때 {large}."
    )


async def test_the_seal_still_sees_a_single_changed_byte(
    migrated_session: AsyncSession,
) -> None:
    """fold를 접어도 **탐지력이 줄면 안 된다** — 한 행의 한 바이트가 해시를 바꾼다."""

    fold = """
    SELECT encode(x_extension.digest(
             COALESCE(string_agg(
               x_extension.digest(convert_to(jsonb_build_array(sample.payload)::text, 'UTF8'),
                                  'sha256'),
               ''::bytea ORDER BY sample.ordinal), ''::bytea),
             'sha256'), 'hex')
      FROM sample
    """
    base = await migrated_session.execute(
        text(
            """
            WITH sample AS (
              SELECT g AS ordinal, 'row-' || g::text AS payload
                FROM generate_series(1, 32) AS g
            )
            """
            + fold
        )
    )
    changed = await migrated_session.execute(
        text(
            """
            WITH sample AS (
              SELECT g AS ordinal,
                     CASE WHEN g = 17 THEN 'row-17!' ELSE 'row-' || g::text END AS payload
                FROM generate_series(1, 32) AS g
            )
            """
            + fold
        )
    )
    base_hash = base.scalar_one()
    changed_hash = changed.scalar_one()

    assert base_hash != changed_hash, (
        "32행 중 한 행의 한 글자를 바꿨는데 해시가 같다 — fold가 입력을 잃고 있다."
    )
    assert len(base_hash) == 64, f"해시가 64자 hex가 아니다: {base_hash!r}"


async def test_the_live_seal_function_uses_the_folded_form(
    migrated_session: AsyncSession,
) -> None:
    """마이그레이션이 **실제 DB의 함수**를 교체했는지 본다.

    `CREATE OR REPLACE`는 본문이 틀려도 성공하므로, 파일이 아니라 카탈로그에 든
    정의를 읽는다. 그리고 시그니처가 유지돼 GRANT가 살아 있는지도 함께 센다 —
    시그니처를 바꾸면 DROP+CREATE가 되어 `ktm_curation_command_owner`의 EXECUTE가
    조용히 사라진다.
    """

    row = (
        await migrated_session.execute(
            text(
                """
                SELECT pg_get_functiondef(p.oid) AS definition,
                       has_function_privilege('ktm_curation_command_owner', p.oid, 'EXECUTE')
                         AS command_owner_may_execute
                  FROM pg_proc AS p
                  JOIN pg_namespace AS n ON n.oid = p.pronamespace
                 WHERE n.nspname = 'feature'
                   AND p.proname = 'current_provider_curation_input_set'
                """
            )
        )
    ).mappings().one()

    definition = str(row["definition"])
    assert "string_agg" in definition, (
        "live 봉인 함수에 새 fold(string_agg)가 없다 — 마이그레이션이 교체하지 못했다."
    )
    assert "FROM canonical_input AS input" in definition, (
        "canonical_input CTE가 사라졌다 — member 정의가 바뀌면 탐지 범위가 달라진다."
    )
    assert row["command_owner_may_execute"], (
        "`ktm_curation_command_owner`가 봉인 함수를 실행하지 못한다 — 시그니처가 바뀌어 "
        "DROP+CREATE가 되면서 EXECUTE GRANT가 날아갔다."
    )


async def test_receipts_record_which_formula_produced_the_hash(
    migrated_session: AsyncSession,
) -> None:
    """세대가 없으면 "공식이 바뀌었다"와 "값이 변조됐다"가 구별되지 않는다."""

    rows = (
        await migrated_session.execute(
            text(
                """
                SELECT c.relname AS table_name,
                       a.attnotnull AS not_null,
                       pg_get_expr(d.adbin, d.adrelid) AS default_expr
                  FROM pg_attribute AS a
                  JOIN pg_class AS c ON c.oid = a.attrelid
                  JOIN pg_namespace AS n ON n.oid = c.relnamespace
                  LEFT JOIN pg_attrdef AS d
                         ON d.adrelid = a.attrelid AND d.adnum = a.attnum
                 WHERE n.nspname = 'ops'
                   AND c.relname IN ('curation_provider_snapshot_receipts',
                                     'curation_source_observation_receipts')
                   AND a.attname = 'input_set_formula'
                 ORDER BY c.relname
                """
            )
        )
    ).mappings().all()

    found = {str(row["table_name"]) for row in rows}
    assert found == {
        "curation_provider_snapshot_receipts",
        "curation_source_observation_receipts",
    }, f"세대 컬럼이 두 receipt 표 모두에 있어야 한다 — 찾은 것: {sorted(found)}"
    for row in rows:
        assert row["not_null"], f"{row['table_name']}.input_set_formula가 NULL을 받는다"
        assert "2" in str(row["default_expr"]), (
            f"{row['table_name']}의 기본값이 새 공식 세대(2)가 아니다: "
            f"{row['default_expr']!r} — 이 revision 이후 발급분이 옛 세대로 기록된다."
        )
