"""causal seal의 fold를 per-row digest로 바꾼다 (ADR-099 1단계).

Revision ID: 311_seal_member_digest
Revises: 310_seoul_source_move

## 무엇이 막혀 있었나

`feature.current_provider_curation_input_set`이 causal seal을 만들 때 데이터셋
**전 행의 13항 배열을 하나의 `jsonb_agg` 배열**로 모은 뒤 그 text를 sha256했다.
크기가 O(행수 × 행당 payload)라 PostgreSQL의 jsonb 배열 상한
268,435,455 bytes에 걸린다.

2026-09-19 prod 실측:

    feature_route_krforest_mountain_trails_job
      4시간18분 지오코딩 완료 → 적재 → 봉인에서
      asyncpg.ProgramLimitExceededError:
        total size of jsonb array elements exceeds the maximum of 268435455 bytes

적재와 봉인이 **같은 트랜잭션**이고 봉인이 마지막이라 57,060행이 통째로
롤백된다. `provider_sync.source_entities`의 `mountain_trail_segment`가 0행인
이유가 이것이다 — 이 job은 **한 번도 성공한 적이 없다.** 재시도는 같은 자리에서
죽으며 매번 4시간을 다시 쓴다.

## 왜 geometry를 옮기는 것이 아니라 fold를 고치는가

geometry가 route payload의 98.5%인 것은 맞다(43 kB 중 633 B만 나머지). 그러나
같은 함수가 place에도 돈다.

    route 1건 평균     43 kB  ×  57,060 =  2.45 GB
    place 1건 평균      323 B  × 980,970 =   302 MB   ← geometry와 무관하게 초과

즉 geometry를 어디로 옮기든 **fold 자체가** 다음 큰 dataset(MOIS 인허가)에서
같은 벽에 닿는다. fold를 고치면 두 경우가 한 번에 닫힌다.

그리고 이 단계는 **표를 만들지 않고 행을 건드리지 않는다.** geometry를 별도
PostGIS 보조 relation으로 분리하는 소유자 지시는 312에서 이행한다 — 되돌리기
비싼 절반을 뒤에 두는 것이 옳은 순서다.

## 탐지 범위가 1비트도 줄지 않는다

사이드카의 `canonical_input` CTE는 `alembic/head-schema.sql`의 정의와 **41줄
바이트 단위로 동일**하다(조립 시 대조했다). 13항 배열의 정의도, `to_jsonb(route)`가
geometry를 담는 것도 그대로다. 바뀌는 것은 마지막 fold 하나다.

    종전: jsonb_agg(13항 배열 ORDER BY ...)::text → sha256
    변경: 행마다 digest(13항 배열::text) = 32 B
          → string_agg(bytea ORDER BY ...) → sha256

32바이트 고정폭이라 구분자 없이 이어 붙여도 경계가 모호해지지 않는다. 집계
결과는 57,060행이면 1.8 MB, MOIS 980,970행이면 31 MB다.

## 해시 **값**은 달라진다 — 그래서 세대를 기록한다

이 fold는 같은 입력에서 다른 값을 낸다. 두 비교 지점
(`feature.seal_provider_curation_snapshot_receipt`는 불일치 시 23514,
`feature.finalize_provider_curation_root`는 `stale_input`)은 **같은 run의
receipt만** 재대조하므로 게이팅은 깨지지 않는다. 2026-09-19 실측으로
진행 중(`queued`/`running`) curation root가 **0건**임을 확인하고 넣는다.

그러나 이미 저장된 receipt는 이 revision 이후 **영원히 재계산되지 않는다.**
세대를 적어 두지 않으면 "공식이 바뀌었다"와 "값이 변조됐다"가 구별되지 않는다.
그래서 두 receipt 표에 `input_set_formula`를 더한다 — 기존 행은 1,
이 revision 이후 발급분은 2다.

## 시그니처를 바꾸지 않는다

`CREATE OR REPLACE`가 되도록 인자와 `RETURNS TABLE`을 그대로 둔다. 바꾸면
DROP+CREATE가 되어 `ktm_curation_command_owner`에게 준 EXECUTE GRANT가 날아가고
`tests/integration/test_runtime_privileges_acl.py`가 빨개진다.

## `RESET ROLE`을 하지 않는다

이 저장소의 마이그레이션은 전부 `SET ROLE ktm_feature_schema_owner`를 켠 채로
끝난다. alembic이 본문 뒤 같은 트랜잭션에서 `UPDATE alembic_version`을 내는데
접속 로그인 롤에는 그 표의 UPDATE 권한이 없다
(`tests/lint/test_migrations_keep_the_schema_owner_role.py`).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

from alembic import op

#: **32자 이하여야 한다** — `public.alembic_version.version_num`이 `varchar(32)`다.
revision: Final[str] = "311_seal_member_digest"
down_revision: Final[str] = "310_seoul_source_move"
branch_labels: None = None
depends_on: None = None

_HERE: Final[Path] = Path(__file__).parent


def _sidecar(name: str) -> tuple[str, ...]:
    """사이드카를 **문장 단위로** 쪼갠다(309와 같은 규약).

    asyncpg는 prepared statement 하나에 여러 명령을 넣지 못한다. 달러 인용 안의
    세미콜론은 세지 않는다 — 놓치면 함수 본문이 중간에서 잘리고 그 실패는
    "문법 오류"로 나타나 원인을 가리키지 않는다. 태그를 `$$`로 가정하지 않는다.
    """

    body = (_HERE / name).read_text(encoding="utf-8")
    opener = re.compile(r"\$[A-Za-z_][A-Za-z_0-9]*\$|\$\$")
    statements: list[str] = []
    current: list[str] = []
    index = 0
    tag: str | None = None
    while index < len(body):
        if tag is None:
            match = opener.match(body, index)
            if match is not None:
                tag = match.group(0)
                current.append(tag)
                index = match.end()
                continue
            char = body[index]
            if char == ";":
                statement = "".join(current).strip()
                if statement:
                    statements.append(statement)
                current = []
                index += 1
                continue
            current.append(char)
            index += 1
            continue
        if body.startswith(tag, index):
            current.append(tag)
            index += len(tag)
            tag = None
            continue
        current.append(body[index])
        index += 1
    trailing = "".join(current).strip()
    if trailing:
        statements.append(trailing)
    return tuple(statements)


#: 봉인 함수 본문. 모듈 상수로 읽어 둔다 —
#: `tests/lint/test_migration_sidecars_are_wired_into_their_migration.py`가
#: import 시점의 `read_text`를 계측해 배선을 센다.
_SEAL_FUNCTION: Final[tuple[str, ...]] = _sidecar(
    "_311_current_provider_curation_input_set.sql"
)

#: 해시 공식 세대. 기존 행은 1(옛 fold), 이 revision 이후 발급분은 2다.
#:
#: **왜 컬럼인가.** 이 revision 이후 옛 receipt의 해시는 영원히 재계산되지
#: 않는다. 세대가 없으면 "공식이 바뀌었다"와 "값이 변조됐다"가 같은 관측으로
#: 보인다 — 감사에서 그 둘을 가를 수 없는 것이 위험이다.
#:
#: 열거를 `IN (1, 2)`로 **좁게** 둔다. 다음 공식이 생기면 그때 넓히는 것이 맞고,
#: 미리 열어 두면 아무도 확인하지 않은 값이 들어온다.
_FORMULA_COLUMN: Final[tuple[str, ...]] = tuple(
    statement
    for table in (
        "ops.curation_provider_snapshot_receipts",
        "ops.curation_source_observation_receipts",
    )
    for statement in (
        f"ALTER TABLE {table}"
        " ADD COLUMN input_set_formula smallint NOT NULL DEFAULT 1",
        f"ALTER TABLE {table}"
        " ALTER COLUMN input_set_formula SET DEFAULT 2",
        f"ALTER TABLE {table}"
        f" ADD CONSTRAINT ck_{table.split('.')[1]}_input_set_formula"
        " CHECK (input_set_formula IN (1, 2))",
    )
)

_FORMULA_COLUMN_DROP: Final[tuple[str, ...]] = tuple(
    statement
    for table in (
        "ops.curation_provider_snapshot_receipts",
        "ops.curation_source_observation_receipts",
    )
    for statement in (
        f"ALTER TABLE {table}"
        f" DROP CONSTRAINT ck_{table.split('.')[1]}_input_set_formula",
        f"ALTER TABLE {table} DROP COLUMN input_set_formula",
    )
)

#: receipt head CHECK 갱신. **graph의 모든 revision을 열거한다.**
#:
#: 현재 head만 넣으면 중간 revision으로 설치된 DB에서 `ADD CONSTRAINT` 자체가
#: 실패해 배포가 도중에 멈춘다
#: (`tests/lint/test_receipt_head_check_covers_the_graph_head.py`).
_RECEIPT_HEADS: Final[tuple[str, ...]] = (
    "300",
    "301_m03_import_children",
    "302_m03_child_issuance",
    "303_m05_payload_hash_domain",
    "304_m05_detector_manuals",
    "305_m05_relitigation_fence",
    "306_m02_manual_feature_purge",
    "307_m02_truncate_fence",
    "308_t39_provider_identities",
    "309_t39_feature_id_rekey",
    "310_seoul_source_move",
)


def _receipt_head_check(heads: tuple[str, ...]) -> str:
    listed = ", ".join(f"'{head}'" for head in heads)
    return (
        "ALTER TABLE ops.application_schema_operation_receipts"
        " DROP CONSTRAINT ck_application_schema_operation_receipts_head,"
        " ADD CONSTRAINT ck_application_schema_operation_receipts_head"
        f" CHECK (destination_head IN ({listed}))"
    )


#: 봉인 함수가 실제로 교체됐는지 스스로 증명한다.
#:
#: `CREATE OR REPLACE`는 본문이 틀려도 성공한다 — 그래서 "바뀌었는가"를 따로
#: 묻는다. 판정은 이름이 아니라 **본문**으로 한다: 새 fold에만 있는
#: `string_agg`이 정의에 있고 옛 fold의 `jsonb_agg(jsonb_build_array`가 **바깥
#: fold 자리에서** 사라졌는가. (`jsonb_agg`는 `override_lineage` LATERAL에도
#: 있으므로 그 이름만으로 판정하면 영원히 실패한다.)
_POSTCONDITION: Final[str] = """
DO $$
DECLARE
  v_body text;
BEGIN
  SELECT pg_get_functiondef(p.oid) INTO v_body
    FROM pg_proc AS p
    JOIN pg_namespace AS n ON n.oid = p.pronamespace
   WHERE n.nspname = 'feature'
     AND p.proname = 'current_provider_curation_input_set';
  IF v_body IS NULL THEN
    RAISE EXCEPTION '311: 봉인 함수를 찾지 못했다';
  END IF;
  IF position('string_agg' in v_body) = 0 THEN
    RAISE EXCEPTION '311: 새 fold(string_agg)가 정의에 없다 — 교체가 안 됐다';
  END IF;
  IF position('FROM canonical_input AS input' in v_body) = 0 THEN
    RAISE EXCEPTION '311: canonical_input CTE가 사라졌다';
  END IF;
END
$$
"""

_UPGRADE_STATEMENTS: Final[tuple[str, ...]] = (
    "SET ROLE ktm_feature_schema_owner",
    _receipt_head_check((*_RECEIPT_HEADS, revision)),
    *_FORMULA_COLUMN,
    *_SEAL_FUNCTION,
    _POSTCONDITION,
)

_DOWNGRADE_STATEMENTS: Final[tuple[str, ...]] = (
    "SET ROLE ktm_feature_schema_owner",
    _receipt_head_check(_RECEIPT_HEADS),
    *_FORMULA_COLUMN_DROP,
)


def upgrade() -> None:
    for statement in _UPGRADE_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    # **봉인 함수는 되돌리지 않는다.** 옛 fold로 돌아가면 등산로 적재가 다시
    # 불가능해지고, 그 사이 발급된 세대 2 receipt는 어차피 재계산되지 않는다.
    # 되돌리는 것은 세대 컬럼과 head CHECK뿐이다 — 함수 본문의 복원이 필요하면
    # forward revision으로 하는 것이 이 저장소의 방식이다.
    for statement in _DOWNGRADE_STATEMENTS:
        op.execute(statement)
