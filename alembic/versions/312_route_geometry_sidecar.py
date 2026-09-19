"""route geometry를 전용 PostGIS relation으로 옮긴다 (ADR-099 2단계).

Revision ID: 312_route_geometry_sidecar
Revises: 311_seal_member_digest

## 왜 옮기는가 — 크기 압박이 아니다

크기 천장은 311이 이미 닫았다. 그러므로 이 단계는 **자기 근거**로 선다.

    route 1건의 to_jsonb 평균   43 kB
      그중 geometry              98.5%
      geom 제외                   633 B

`to_jsonb(route)`를 쓰는 곳은 봉인 말고 둘 더 있다.

- `feature.current_theme_candidate_snapshot`이 그 detail을 후보의
  `match_evidence` jsonb로 **영구 저장**한다 — 후보 1건당 43 kB다.
- admin 큐레이션 후보 목록 API가 `feature_detail`로 그대로 내보낸다 — 목록
  엔드포인트라 **페이지당 N × 43 kB**다.

행을 좁히면 그 둘이 함께 줄어든다. 봉인은 311로 이미 안전하므로, 이 변경은
저장·전송 비용을 줄이는 것이 목적이다.

## ADR-086의 불변식을 어떻게 지키는가

`0087_route_area_subtypes`가 geometry를 subtype으로 옮긴 이유는 성능이 아니라
**"geometry가 필수인 kind와 없어야 하는 kind가 술어가 아니라 테이블 구조로
갈린다"**였다(ADR-086 결정 5). 보조 relation은 "geometry 없는 route"를 다시
표현 가능하게 만든다.

그래서 `feature_routes.feature_id`에 보조 relation을 가리키는 **DEFERRABLE
INITIALLY DEFERRED** FK를 건다. 한 트랜잭션 안에서는 삽입 순서가 자유롭고
COMMIT에서만 판정한다 — purge가 CASCADE로 두 표를 지울 때 중간 상태가 잠시
위반이 되므로 DEFERRABLE이어야 한다.

**이 불변식의 검사는 반드시 COMMIT으로 해야 한다.** 문장 직후에 assert하면
deferred 제약은 영원히 발화하지 않아 FK가 없어도 통과한다.

## FK는 feature.features를 직접 가리킨다

purge 증거 포획(`_309_purge_manual_feature.sql`)이
`confrelid = 'feature.features'::regclass` **한 단계만** 훑는다. `feature_routes`에
매달면 2단 CASCADE로 지워지되 `ops.manual_feature_purge_records`에 남지 않아
복구점이 조용히 불완전해진다.

## geom_digest는 생성 컬럼이다

geometry가 `to_jsonb(route)`에서 빠지면 봉인이 geometry 변경을 더는 못 본다.
그 자리를 고정폭 지문으로 메우되 **동기화할 코드를 만들지 않는다** —
`x_extension.digest`와 `x_extension.ST_AsEWKB`가 둘 다 IMMUTABLE임을 실측으로
확인했으므로(`pg_proc.provolatile = 'i'`) `GENERATED ALWAYS AS ... STORED`가
성립한다. DB가 유지하므로 트리거도, 이중 해시 식도, 프로시저를 우회한
`UPDATE ... SET geom` 경로의 누락도 없다.

봉인 함수는 그 컬럼을 LATERAL이 아니라 PK↔PK LEFT JOIN으로 읽어 route arm에
`geom_digest` 한 항으로 넣는다(`_312_current_provider_curation_input_set.sql`).

## 데이터를 이어 나르지 않는다

소유자 결정(2026-09-19): *"마이그레이션 하지말고 db재설계후 다시데이터 로드해.
지금데이터는 무의미함."*

그래서 이 revision에는 backfill도 무손실 증명도 없다. 그 둘은 "옮긴 것이 같은가"를
묻는 장치인데 여기서는 옮기지 않는다. 대신 `feature_routes`가 **비어 있기를
요구**한다 — 지우는 것은 DB를 다시 세우는 절차의 일이고, 이 revision의 일은 그
절차를 건너뛴 것을 알아차리는 것이다. 새 설치(300 → 312)는 0행이라 그대로 지나간다.

`feature_routes`만 지우면 `feature.features`의 route 행이 subtype 없이 남아 **다른
깨진 상태**가 되므로, 마이그레이션 안에서 지우지 않는다.

## area는 이번에 옮기지 않는다

`feature_areas`는 구조가 route와 완전히 대칭이지만 **prod 행 수가 0**이다
(2026-09-19 실측). 대칭성만을 근거로 범위를 두 배로 잡지 않는다.

**여는 기준을 수치로 박는다**: `feature_areas`의 `행 수 × to_jsonb 평균 바이트`가
100,000을 넘으면 같은 이전을 연다. 확인 질의는
`SELECT count(*), avg(length(to_jsonb(a)::text)) FROM feature.feature_areas a;`이고
`tests/lint/test_area_geometry_move_threshold.py`가 이 기준을 들고 있다.

## `RESET ROLE`을 하지 않는다
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

from alembic import op

#: **32자 이하여야 한다** — `public.alembic_version.version_num`이 `varchar(32)`다.
revision: Final[str] = "312_route_geometry_sidecar"
down_revision: Final[str] = "311_seal_member_digest"
branch_labels: None = None
depends_on: None = None

_HERE: Final[Path] = Path(__file__).parent


def _sidecar(name: str) -> tuple[str, ...]:
    """사이드카를 **문장 단위로** 쪼갠다(309·311과 같은 규약).

    asyncpg는 prepared statement 하나에 여러 명령을 넣지 못한다. 달러 인용 안의
    세미콜론은 세지 않고, 태그를 `$$`로 가정하지 않는다.
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


#: 표 신설 + 이전 + 무손실 증명 + 제약 + 구 컬럼 제거.
_SIDECAR_TABLE: Final[tuple[str, ...]] = _sidecar("_312_feature_route_geometries.sql")

#: 봉인 함수 route arm에 `geom_digest`를 되넣는다.
_SEAL_FUNCTION: Final[tuple[str, ...]] = _sidecar(
    "_312_current_provider_curation_input_set.sql"
)

#: 공개 projection 뷰가 geometry를 보조 relation에서 읽게 한다. 출력 컬럼의
#: 이름·순서·타입이 그대로라 `CREATE OR REPLACE VIEW`가 성립한다.
_PUBLIC_VIEW: Final[tuple[str, ...]] = _sidecar("_312_public_features.sql")

#: `public_ready` 복제본을 유지하는 트리거.
#:
#: **자기 역할 창을 여는 사이드카다.** 이 함수의 소유자는
#: `ktm_feature_state_procedure_owner`이고 롤이 NOINHERIT이라 스키마 소유자 창에서
#: `CREATE OR REPLACE`하면 `must be owner of function`으로 죽는다(2026-09-19 n150
#: 첫 실행이 잡았다). 파일이 자기 창을 열고 **닫는다**.
_PUBLIC_READY_TRIGGERS: Final[tuple[str, ...]] = _sidecar(
    "_312_sync_subtype_public_ready.sql"
)

#: route geometry를 쓰는 프로시저 셋. plpgsql 본문은 `pg_depend`를 만들지 않아
#: `DROP COLUMN`이 막히지 않는다 — 고치지 않으면 **첫 route 적재**가 42703으로
#: 죽는다(2026-09-19 적대 리뷰가 blocker로 잡았다).
_ROUTE_GEOMETRY_ROUTINES: Final[tuple[str, ...]] = (
    *_sidecar("_312_apply_provider_feature_field_patch.sql"),
    *_sidecar("_312_author_feature_field_overrides.sql"),
    *_sidecar("_312_revoke_feature_field_overrides.sql"),
)

#: 새 표가 자기 자리를 갖췄는지 스스로 증명한다.
_POSTCONDITION: Final[str] = """
DO $post$
DECLARE
    v_missing text;
    v_still_there bigint;
BEGIN
    SELECT string_agg(expected, ', ') INTO v_missing
      FROM (VALUES
              ('pk_feature_route_geometries'),
              ('fk_feature_route_geometries_feature_kind'),
              ('ck_feature_route_geometries_kind')
           ) AS wanted(expected)
     WHERE NOT EXISTS (
       SELECT 1 FROM pg_constraint AS c
        WHERE c.conname = wanted.expected
          AND c.conrelid = 'feature.feature_route_geometries'::regclass);
    IF v_missing IS NOT NULL THEN
        RAISE EXCEPTION '312: 보조 relation 제약이 없다: %', v_missing;
    END IF;

    IF NOT EXISTS (
      SELECT 1 FROM pg_constraint
       WHERE conname = 'fk_feature_routes_geometry'
         AND condeferrable AND condeferred) THEN
        RAISE EXCEPTION
            '312: 존재 불변식 FK가 없거나 DEFERRABLE INITIALLY DEFERRED가 아니다';
    END IF;

    SELECT count(*) INTO v_still_there
      FROM pg_attribute
     WHERE attrelid = 'feature.feature_routes'::regclass
       AND attname = 'geom' AND attnum > 0 AND NOT attisdropped;
    IF v_still_there > 0 THEN
        RAISE EXCEPTION '312: feature_routes.geom이 아직 남아 있다';
    END IF;

    IF NOT EXISTS (
      SELECT 1 FROM pg_attribute
       WHERE attrelid = 'feature.feature_route_geometries'::regclass
         AND attname = 'geom_digest' AND attgenerated = 's') THEN
        RAISE EXCEPTION
            '312: geom_digest가 STORED 생성 컬럼이 아니다 — 동기화 부담이 생긴다';
    END IF;
END
$post$
"""

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
    "311_seal_member_digest",
)


def _receipt_head_check(heads: tuple[str, ...]) -> str:
    listed = ", ".join(f"'{head}'" for head in heads)
    return (
        "ALTER TABLE ops.application_schema_operation_receipts"
        " DROP CONSTRAINT ck_application_schema_operation_receipts_head,"
        " ADD CONSTRAINT ck_application_schema_operation_receipts_head"
        f" CHECK (destination_head IN ({listed}))"
    )


_UPGRADE_STATEMENTS: Final[tuple[str, ...]] = (
    "SET ROLE ktm_feature_schema_owner",
    _receipt_head_check((*_RECEIPT_HEADS, revision)),
    *_SIDECAR_TABLE,
    *_SEAL_FUNCTION,
    *_PUBLIC_VIEW,
    # **뷰 교체 뒤에 드롭한다.** `feature.public_features`가 이 컬럼을 참조하므로
    # 순서를 어기면 `DependentObjectsStillExistError`로 멎는다. 무손실 증명은
    # 표 사이드카 안에서 **드롭 전에** 이미 끝났다.
    "ALTER TABLE feature.feature_routes DROP COLUMN geom",
    *_PUBLIC_READY_TRIGGERS,
    *_ROUTE_GEOMETRY_ROUTINES,
    _POSTCONDITION,
)


def upgrade() -> None:
    for statement in _UPGRADE_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    # **되돌리면 geometry가 다시 route 행으로 들어온다.** 무손실을 같은 술어로
    # 한 번 더 증명한다 — 되돌리는 방향에도 바이트 동일성이 요구된다.
    raise RuntimeError(
        "312_route_geometry_sidecar는 forward-only다. geometry를 되돌리려면 "
        "역이전을 증명하는 새 revision을 쓸 것 — 이 저장소의 배포는 이미지 롤백 "
        "창을 갖지 않는다(production entrypoint는 마이그레이션을 돌리지 않고 "
        "final permit이 head를 정확 일치로 본다)."
    )
