"""T-VN-H49 — manual Feature hard purge를 감사되는 운영 명령으로 연다.

Revision ID: 306_m02_manual_feature_purge
Revises: 305_m05_relitigation_fence

## 무엇이 막혀 있었나

`trg_features_manual_feature_hard_purge_fence`는 claim이 있으면 무조건 거부한다. claim은
append-only라 **항상** 있으므로 manual Feature는 영원히 지워지지 않는다. 그런데 그 제약의
이름은 `ck_manual_feature_purge_not_ready` — "not allowed"가 아니라 **"not ready"**다.
ADR-093도 "M02 purge 계약 **전**에는 닫는다"고 적었다. 즉 이것은 정책이 아니라 임시
마개였고, 그 마개의 술어가 하필 항상 참인 조건이었다.

그리고 스키마는 애초에 purge를 **전제로** 지어져 있다. claim과 origin 둘 다
`feature.features` FK를 **의도적으로 두지 않았고**, 그 이유를 각 모델 docstring이
"hard purge 뒤에도 남아야 하므로"라고 적는다.

## 왜 지금 열 수 있나

소유자가 건 순서는 "되돌릴 수 없는 삭제 경로를 restore proof보다 먼저 열 수 없다"였다.
M05-2 C·D단계가 증명한 것은 **복원 메커니즘**이다(복원본 카탈로그가 운영 DB와 바이트
단위로 같다). **복원할 대상이 있다는 것은 증명하지 못했다** — `map_application`은 어느
주기 백업에도 없고(T-VN-H43 보류) restore/swap은 300 baseline 정책으로 닫혀 있다.

그래서 이 설계는 DB 수준 restore에 기대지 않는다. **purge가 자기 복구점을 들고 다닌다** —
지우기 전에 cascade로 사라질 행을 전부 `feature.manual_feature_purge_records`에 담는다.
그러면 이 항목이 H43 보류에 묶이지 않는다(소유자 승인 2026-09-08).

## 담을 relation을 손으로 적지 않는다

`ON DELETE CASCADE`로 `feature.features`를 참조하는 자식은 지금 20개가 넘고, 새 자식이
생길 때마다 목록을 갱신해야 한다면 **갱신을 잊는 순간 purge가 조용히 데이터를 잃는다.**
그래서 프로시저가 `pg_constraint`에서 런타임에 유도한다(AGENTS.md DO NOT 15).

## 삭제를 막는 것과 되돌릴 수 없게 바꾸는 것을 **둘 다** 본다

`feature.features`를 참조하는 FK 34개의 삭제 동작은 넷으로 갈린다(실측):
CASCADE 25 · RESTRICT 5 · SET NULL 3 · **NO ACTION 1**.

- **막는 것**(probe): `RESTRICT`와 **`NO ACTION`**. 지연되지 않은 FK에서 NO ACTION은
  RESTRICT와 똑같이 거부한다 — `'r'`만 보면 그런 참조자가 probe를 통과한 뒤 DELETE에서
  raw 23503으로 죽는다. 그 하나가 `ops.feature_requests.resolved_feature_id`이고,
  **M04 승인으로 태어난 manual Feature 전부**에 달리므로 드문 경로가 아니다
  (2026-09-08 적대 리뷰 P1).
- **담는 것**(capture): `CASCADE`와 **`SET NULL`**. 전자는 행을 지우고 후자는 행을
  고치지만, 복구점의 관점에서는 둘 다 되돌릴 수 없는 변경이다.

`theme_feature_candidates`·`feature_reference_reconciliation_events`·
`manual_provider_dedup_cases`가 `ON DELETE RESTRICT`로 참조한다. 그 셋은 이 Feature의
identity를 **불변 증거로** 인용하므로 purge가 뚫으면 안 된다. 다만 raw 23503으로 죽으면
"왜 못 지우는지"를 말하지 못하므로, 프로시저가 먼저 조회해 **이름 붙은 거부**를 낸다.

## claim의 두 역할을 나눈다

claim은 지금 (i) "이 identity를 command X가 만들었다"는 증거이자 (ii) 살아 있는 유일성
예약이다. purge는 (ii)만 놓아야 한다 — (i)까지 지우면 append-only가 깨지고, (ii)를 쥔 채
purge하면 exact 예약이 **영구 tombstone**이 되어 같은 이름·좌표를 다시 만들 수 없다.

- `purged_by_command_id`/`purged_at` — purge 승인이자 기록. **fence가 이것을 본다.**
- `identity_released` — 예약 해제. purge의 **명시 파라미터**이지 자동이 아니다.
  `mistaken_creation`은 보통 놓고, `erasure_required`는 보통 쥔다(같은 것이 다시 만들어지면
  안 되므로). 두 동기가 정반대를 원하므로 운영자가 의도를 말해야 한다.

append-only 트리거는 이 셋의 **단조 전이 하나**만 허용하도록 완화한다 — 증거 필드는
여전히 불변이고, 전이는 command가 원인이라 감사된다. ADR-093 개정 한 문장이 함께 간다
(소유자 승인 2026-09-08).

## fence는 지속 상태의 순수 함수로 남는다

세션 GUC 같은 "승인된 경로" 표식을 새로 만들지 않는다. 규칙은 하나다 —
**claim이 purge 승인을 기록한 뒤에만 그 Feature를 지울 수 있다.** 프로시저가 claim을 먼저
갱신하고 그다음 DELETE하므로 fence는 상태만 보면 된다.

DDL은 문장 하나씩 실행한다(asyncpg prepared statement 제약).
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from alembic import op

# ruff: noqa: E501

revision: Final[str] = "306_m02_manual_feature_purge"
down_revision: Final[str] = "305_m05_relitigation_fence"
branch_labels: None = None
depends_on: None = None

_HERE: Final = Path(__file__).resolve().parent


def _sidecar(name: str) -> str:
    return (_HERE / name).read_text(encoding="utf-8")


#: **`ON CONFLICT ON CONSTRAINT`는 partial unique index를 가리킬 수 없다.** exact
#: 예약을 부분 인덱스로 좁히면 그 형태를 쓰는 생성 경로 셋이 전부 깨진다 — n150
#: 실측이 그것을 잡았다(`FeatureRequestError`로 새어 나왔다). index-inference 형태로
#: 바꾸되 본문은 baseline에서 기계 파생한다(302·303·305와 같은 규약).
_CONFLICT_TARGET_PROCEDURES: Final[tuple[str, ...]] = (
    "approve_feature_request_with_initial_state",
    "create_admin_manual_feature_with_initial_state",
    "create_manual_curation_item_with_feature_command",
)

#: 각 프로시저의 소유자. `CREATE OR REPLACE`는 소유자만 할 수 있다.
_CONFLICT_TARGET_OWNERS: Final[dict[str, str]] = {
    "approve_feature_request_with_initial_state": "ktm_feature_request_procedure_owner",
    "create_admin_manual_feature_with_initial_state": "ktm_manual_feature_procedure_owner",
    "create_manual_curation_item_with_feature_command": "ktm_curation_command_owner",
}


def _conflict_target_statements(suffix: str) -> tuple[str, ...]:
    statements: list[str] = []
    for name in _CONFLICT_TARGET_PROCEDURES:
        statements.append(f"SET ROLE {_CONFLICT_TARGET_OWNERS[name]}")
        statements.append(_sidecar(f"_306_{name}_{suffix}.sql"))
    statements.append("SET ROLE ktm_feature_schema_owner")
    return tuple(statements)


_CLAIM_PURGE_COLUMNS: Final[str] = (
    "ALTER TABLE feature.manual_feature_identity_claims"
    " ADD COLUMN purged_by_command_id bigint,"
    " ADD COLUMN purged_at timestamptz,"
    " ADD COLUMN identity_released boolean NOT NULL DEFAULT false"
)

_CLAIM_PURGE_COLUMNS_DROP: Final[str] = (
    "ALTER TABLE feature.manual_feature_identity_claims"
    " DROP COLUMN purged_by_command_id,"
    " DROP COLUMN purged_at,"
    " DROP COLUMN identity_released"
)

_CLAIM_PURGE_COMMAND_FK: Final[str] = (
    "ALTER TABLE feature.manual_feature_identity_claims"
    " ADD CONSTRAINT fk_manual_feature_identity_claims_purge_command"
    " FOREIGN KEY (purged_by_command_id) REFERENCES ops.domain_commands(command_id)"
    " ON DELETE RESTRICT"
)

#: 두 컬럼은 항상 함께 채워진다 — 하나만 있으면 "언제 승인됐나"를 말하지 못한다.
_CLAIM_PURGE_PAIR_CHECK: Final[str] = (
    "ALTER TABLE feature.manual_feature_identity_claims"
    " ADD CONSTRAINT ck_manual_feature_identity_claims_purge_pair"
    " CHECK ((purged_by_command_id IS NULL) = (purged_at IS NULL))"
)

#: 살아 있는 Feature의 identity를 놓을 수는 없다. 해제는 purge의 결과이지 그 자체가
#: 독립 동작이 아니다.
_CLAIM_RELEASE_CHECK: Final[str] = (
    "ALTER TABLE feature.manual_feature_identity_claims"
    " ADD CONSTRAINT ck_manual_feature_identity_claims_release_needs_purge"
    " CHECK (NOT identity_released OR purged_by_command_id IS NOT NULL)"
)

#: exact 예약을 **살아 있는 것만** 대상으로 좁힌다. 이것이 tombstone을 관리 가능하게
#: 만드는 한 줄이다 — 해제된 claim은 증거로 남되 재생성을 막지 않는다.
_EXACT_UNIQUE_DROP: Final[str] = (
    "ALTER TABLE feature.manual_feature_identity_claims"
    " DROP CONSTRAINT uq_manual_feature_identity_claims_exact"
)

_EXACT_UNIQUE_PARTIAL: Final[str] = (
    "CREATE UNIQUE INDEX uq_manual_feature_identity_claims_exact"
    " ON feature.manual_feature_identity_claims"
    " (feature_kind, name_key, lon_e6, lat_e6)"
    " WHERE NOT identity_released"
)

_EXACT_UNIQUE_PARTIAL_DROP: Final[str] = (
    "DROP INDEX feature.uq_manual_feature_identity_claims_exact"
)

_EXACT_UNIQUE_RESTORE: Final[str] = (
    "ALTER TABLE feature.manual_feature_identity_claims"
    " ADD CONSTRAINT uq_manual_feature_identity_claims_exact"
    " UNIQUE (feature_kind, name_key, lon_e6, lat_e6)"
)

#: cascade로 사라질 행을 통째로 담는다. `captured_rows`가 NULL이면 그것은 결손이 아니라
#: `erasure_required`의 **의도된 부재**이고, `captured_sha256`이 그 사실을 증언한다.
_PURGE_RECORDS_TABLE: Final[str] = """
CREATE TABLE feature.manual_feature_purge_records (
    purge_id uuid PRIMARY KEY DEFAULT x_extension.gen_random_uuid(),
    feature_uuid uuid NOT NULL,
    feature_id text NOT NULL,
    reason_code text NOT NULL,
    identity_released boolean NOT NULL,
    purged_by_command_id bigint NOT NULL,
    purged_by_actor text NOT NULL,
    captured_rows jsonb,
    captured_relation_count integer NOT NULL,
    captured_row_count integer NOT NULL,
    captured_sha256 text NOT NULL,
    purged_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT ck_manual_feature_purge_records_reason
        CHECK (reason_code IN ('mistaken_creation', 'erasure_required')),
    CONSTRAINT ck_manual_feature_purge_records_actor
        CHECK (btrim(purged_by_actor) <> '' AND char_length(purged_by_actor) <= 200),
    CONSTRAINT ck_manual_feature_purge_records_digest
        CHECK (captured_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_manual_feature_purge_records_payload
        CHECK (
            (reason_code = 'mistaken_creation'
             AND captured_rows IS NOT NULL
             AND jsonb_typeof(captured_rows) = 'object')
            OR (reason_code = 'erasure_required' AND captured_rows IS NULL)
        ),
    CONSTRAINT ck_manual_feature_purge_records_counts
        CHECK (captured_relation_count >= 0 AND captured_row_count >= 0),
    CONSTRAINT uq_manual_feature_purge_records_feature UNIQUE (feature_uuid),
    CONSTRAINT uq_manual_feature_purge_records_command UNIQUE (purged_by_command_id),
    CONSTRAINT fk_manual_feature_purge_records_command
        FOREIGN KEY (purged_by_command_id)
        REFERENCES ops.domain_commands(command_id) ON DELETE RESTRICT
)
"""

_PURGE_RECORDS_TABLE_DROP: Final[str] = "DROP TABLE feature.manual_feature_purge_records"

_PURGE_RECORDS_OWNER: Final[str] = (
    "ALTER TABLE feature.manual_feature_purge_records OWNER TO ktm_feature_schema_owner"
)

#: 복구점이 나중에 조용히 고쳐지면 복구점이 아니다.
_PURGE_RECORDS_APPEND_ONLY: Final[str] = (
    "CREATE TRIGGER trg_manual_feature_purge_records_append_only"
    " BEFORE DELETE OR UPDATE ON feature.manual_feature_purge_records"
    " FOR EACH ROW EXECUTE FUNCTION feature.reject_manual_feature_evidence_mutation()"
)

_PURGE_RECORDS_NO_TRUNCATE: Final[str] = (
    "CREATE TRIGGER trg_manual_feature_purge_records_no_truncate"
    " BEFORE TRUNCATE ON feature.manual_feature_purge_records"
    " FOR EACH STATEMENT EXECUTE FUNCTION"
    " feature.reject_manual_feature_evidence_mutation()"
)

#: 기존 함수는 claim/origin 두 이름만 알고 나머지는 origin 메시지로 떨어진다. 새 표에
#: 그대로 걸면 "Feature creation origins are append-only"라는 **틀린 진단**이 나온다.
#: 그리고 claim의 단조 전이 셋만 허용하도록 완화한다 — 증거 필드는 여전히 불변이다.
_EVIDENCE_GUARD_UPGRADED: Final[str] = """
CREATE OR REPLACE FUNCTION feature.reject_manual_feature_evidence_mutation() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog'
    AS $$
BEGIN
    IF TG_TABLE_NAME = 'manual_feature_purge_records' THEN
        RAISE EXCEPTION 'manual Feature purge records are append-only'
            USING ERRCODE = '42501',
                CONSTRAINT = 'ck_manual_feature_purge_records_append_only';
    END IF;
    IF TG_TABLE_NAME = 'manual_feature_identity_claims' THEN
        IF TG_OP = 'UPDATE'
           AND NEW.feature_id IS NOT DISTINCT FROM OLD.feature_id
           AND NEW.feature_kind IS NOT DISTINCT FROM OLD.feature_kind
           AND NEW.name_key IS NOT DISTINCT FROM OLD.name_key
           AND NEW.lon_e6 IS NOT DISTINCT FROM OLD.lon_e6
           AND NEW.lat_e6 IS NOT DISTINCT FROM OLD.lat_e6
           AND NEW.claimed_by_command_id IS NOT DISTINCT FROM OLD.claimed_by_command_id
           AND NEW.claim_basis IS NOT DISTINCT FROM OLD.claim_basis
           AND NEW.claimed_at IS NOT DISTINCT FROM OLD.claimed_at
           AND OLD.purged_by_command_id IS NULL
           AND NEW.purged_by_command_id IS NOT NULL
           AND NEW.purged_at IS NOT NULL
           AND (NEW.identity_released OR NOT OLD.identity_released)
        THEN
            RETURN NEW;
        END IF;
        RAISE EXCEPTION 'manual Feature identity claims are append-only'
            USING ERRCODE = '42501',
                CONSTRAINT = 'ck_manual_feature_identity_claims_append_only';
    END IF;
    RAISE EXCEPTION 'Feature creation origins are append-only'
        USING ERRCODE = '42501',
            CONSTRAINT = 'ck_feature_creation_origins_append_only';
END
$$
"""

_EVIDENCE_GUARD_ORIGINAL: Final[str] = """
CREATE OR REPLACE FUNCTION feature.reject_manual_feature_evidence_mutation() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog'
    AS $$
BEGIN
    IF TG_TABLE_NAME = 'manual_feature_identity_claims' THEN
        RAISE EXCEPTION 'manual Feature identity claims are append-only'
            USING ERRCODE = '42501',
                CONSTRAINT = 'ck_manual_feature_identity_claims_append_only';
    END IF;
    RAISE EXCEPTION 'Feature creation origins are append-only'
        USING ERRCODE = '42501',
            CONSTRAINT = 'ck_feature_creation_origins_append_only';
END
$$
"""

#: **fence는 지속 상태의 순수 함수로 남는다.** claim이 purge 승인을 기록했을 때만
#: 통과시킨다. 이름을 둘로 나눠 "아직 안 열렸다"와 "승인 없이 지우려 한다"를 구별한다 —
#: 전자는 이제 나올 수 없고, 후자가 진짜 거부다.
_PURGE_FENCE_UPGRADED: Final[str] = """
CREATE OR REPLACE FUNCTION feature.reject_manual_feature_hard_purge() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog'
    AS $$
DECLARE
    v_claim feature.manual_feature_identity_claims%ROWTYPE;
BEGIN
    SELECT * INTO v_claim
    FROM feature.manual_feature_identity_claims AS claim
    WHERE claim.feature_id = OLD.feature_uuid;
    IF NOT FOUND THEN
        RETURN OLD;
    END IF;
    IF v_claim.purged_by_command_id IS NULL THEN
        RAISE EXCEPTION 'manual Feature delete needs an authorised purge command'
            USING ERRCODE = '23514',
                CONSTRAINT = 'ck_manual_feature_purge_unauthorised';
    END IF;
    RETURN OLD;
END
$$
"""

_PURGE_FENCE_ORIGINAL: Final[str] = """
CREATE OR REPLACE FUNCTION feature.reject_manual_feature_hard_purge() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog'
    AS $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM feature.manual_feature_identity_claims AS claim
        WHERE claim.feature_id = OLD.feature_uuid
    ) THEN
        RAISE EXCEPTION 'manual Feature hard purge is not ready'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_manual_feature_purge_not_ready';
    END IF;
    RETURN OLD;
END
$$
"""

#: cascade 자식을 `pg_constraint`에서 유도해 담는다. 목록을 박으면 새 자식이 생길 때마다
#: purge가 조용히 데이터를 잃는다.
#:
#: FK 하나가 아니라 **relation 하나당 한 번** 담는다 — 같은 표를 두 FK가 참조하는 경우가
#: 있어(예: `(feature_id, kind)`와 `(feature_id, feature_uuid)`) FK마다 담으면 같은 행이
#: 두 번 들어간다.
_PURGE_PROCEDURE: Final[str] = """
CREATE PROCEDURE feature.purge_manual_feature(
    IN p_feature_uuid uuid,
    IN p_reason_code text,
    IN p_release_identity boolean,
    IN p_actor text,
    IN p_command_id bigint,
    OUT o_purge_id uuid,
    OUT o_outcome text,
    OUT o_captured_relation_count integer,
    OUT o_captured_row_count integer
)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'feature', 'ops', 'x_extension'
    AS $$
DECLARE
    v_claim feature.manual_feature_identity_claims%ROWTYPE;
    v_feature_id text;
    v_command ops.domain_commands%ROWTYPE;
    v_blockers text;
    v_relation text;
    v_predicate text;
    v_rows jsonb;
    v_captured jsonb := '{}'::jsonb;
    v_relation_count integer := 0;
    v_row_count integer := 0;
    v_existing feature.manual_feature_purge_records%ROWTYPE;
BEGIN
    IF p_feature_uuid IS NULL
       OR p_reason_code NOT IN ('mistaken_creation', 'erasure_required')
       OR p_release_identity IS NULL
       OR coalesce(btrim(p_actor), '') = ''
       OR p_command_id IS NULL THEN
        RAISE EXCEPTION 'manual Feature purge has invalid arguments'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_manual_feature_purge_command';
    END IF;

    SELECT * INTO v_command
    FROM ops.domain_commands AS command
    WHERE command.command_id = p_command_id
    FOR SHARE;
    IF NOT FOUND
       OR v_command.actor <> p_actor
       OR v_command.operation <> 'admin.manual-feature.purge.v1'
       OR EXISTS (
           SELECT 1 FROM ops.domain_command_results AS result
           WHERE result.command_id = p_command_id
       ) THEN
        RAISE EXCEPTION 'manual Feature purge command is not open'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_manual_feature_purge_command';
    END IF;

    SELECT * INTO v_claim
    FROM feature.manual_feature_identity_claims AS claim
    WHERE claim.feature_id = p_feature_uuid
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'purge target has no manual identity claim'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_manual_feature_purge_not_manual';
    END IF;

    IF v_claim.purged_by_command_id IS NOT NULL THEN
        SELECT * INTO v_existing
        FROM feature.manual_feature_purge_records AS record
        WHERE record.feature_uuid = p_feature_uuid;
        o_purge_id := v_existing.purge_id;
        o_outcome := 'already_purged';
        o_captured_relation_count := v_existing.captured_relation_count;
        o_captured_row_count := v_existing.captured_row_count;
        RETURN;
    END IF;

    SELECT feature.feature_id INTO v_feature_id
    FROM feature.features AS feature
    WHERE feature.feature_uuid = p_feature_uuid
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'purge target Feature does not exist'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_manual_feature_purge_not_manual';
    END IF;

    SELECT string_agg(blocked.relation_name || '=' || blocked.tally::text, ', '
                      ORDER BY blocked.relation_name)
    INTO v_blockers
    FROM (
        SELECT feature.qualified_relation_name(constraint_row.conrelid) AS relation_name,
               count(*) AS tally
        FROM pg_catalog.pg_constraint AS constraint_row
        CROSS JOIN LATERAL (
            SELECT format(
                'SELECT count(*) FROM %s AS child WHERE (%s) IN'
                ' (SELECT %s FROM feature.features WHERE feature_uuid = %L)',
                feature.qualified_relation_name(constraint_row.conrelid),
                (SELECT string_agg(format('child.%I', attribute.attname), ', '
                                   ORDER BY position.ordinality)
                 FROM unnest(constraint_row.conkey) WITH ORDINALITY AS position(attnum, ordinality)
                 JOIN pg_catalog.pg_attribute AS attribute
                   ON attribute.attrelid = constraint_row.conrelid
                  AND attribute.attnum = position.attnum),
                (SELECT string_agg(format('%I', attribute.attname), ', '
                                   ORDER BY position.ordinality)
                 FROM unnest(constraint_row.confkey) WITH ORDINALITY AS position(attnum, ordinality)
                 JOIN pg_catalog.pg_attribute AS attribute
                   ON attribute.attrelid = constraint_row.confrelid
                  AND attribute.attnum = position.attnum),
                p_feature_uuid
            ) AS statement
        ) AS built
        CROSS JOIN LATERAL feature.count_rows_dynamic(built.statement) AS counted(tally)
        WHERE constraint_row.confrelid = 'feature.features'::regclass
          AND constraint_row.contype = 'f'
          -- **`'a'`(NO ACTION)도 막는다.** 지연되지 않은 FK에서 NO ACTION은 RESTRICT와
          -- 똑같이 삭제를 거부한다. `'r'`만 보면 그런 참조자가 probe를 통과한 뒤
          -- DELETE에서 raw 23503으로 죽고, 그러면 "이름을 대는 거부"라는 이 설계의
          -- 요지가 그 경로에서만 조용히 무효가 된다.
          --
          -- 지금 그런 FK는 정확히 하나다 — `ops.feature_requests.resolved_feature_id`.
          -- 그리고 그것은 **M04 승인으로 태어난 manual Feature 전부**에 달린다
          -- (`approve_feature_request_with_initial_state`가 claim을 심고 같은
          -- 트랜잭션에서 `resolved_feature_id`를 세운다). 즉 드문 경로가 아니다.
          AND constraint_row.confdeltype IN ('r', 'a')
          AND counted.tally > 0
        GROUP BY constraint_row.conrelid
    ) AS blocked;

    IF v_blockers IS NOT NULL THEN
        RAISE EXCEPTION 'purge target is bound by immutable evidence: %', v_blockers
            USING ERRCODE = '23514',
                CONSTRAINT = 'ck_manual_feature_purge_evidence_bound';
    END IF;

    IF p_reason_code = 'mistaken_creation' THEN
        FOR v_relation, v_predicate IN
            SELECT feature.qualified_relation_name(constraint_row.conrelid),
                   string_agg(
                       format(
                           '(%s) IN (SELECT %s FROM feature.features WHERE feature_uuid = %L)',
                           (SELECT string_agg(format('child.%I', attribute.attname), ', '
                                              ORDER BY position.ordinality)
                            FROM unnest(constraint_row.conkey) WITH ORDINALITY AS position(attnum, ordinality)
                            JOIN pg_catalog.pg_attribute AS attribute
                              ON attribute.attrelid = constraint_row.conrelid
                             AND attribute.attnum = position.attnum),
                           (SELECT string_agg(format('%I', attribute.attname), ', '
                                              ORDER BY position.ordinality)
                            FROM unnest(constraint_row.confkey) WITH ORDINALITY AS position(attnum, ordinality)
                            JOIN pg_catalog.pg_attribute AS attribute
                              ON attribute.attrelid = constraint_row.confrelid
                             AND attribute.attnum = position.attnum),
                           p_feature_uuid
                       ),
                       ' OR '
                   )
            FROM pg_catalog.pg_constraint AS constraint_row
            WHERE constraint_row.confrelid = 'feature.features'::regclass
              AND constraint_row.contype = 'f'
              -- **`'n'`(SET NULL)도 담는다.** cascade는 행을 지우고 SET NULL은 행을
              -- 고치지만, 복구점의 관점에서는 둘 다 "이 삭제가 되돌릴 수 없게 바꾸는
              -- 것"이다. 담지 않으면 어느 행의 어느 컬럼이 NULL이 됐는지 알 수 없다.
              AND constraint_row.confdeltype IN ('c', 'n')
            GROUP BY constraint_row.conrelid
            ORDER BY feature.qualified_relation_name(constraint_row.conrelid)
        LOOP
            EXECUTE format(
                'SELECT coalesce(jsonb_agg(to_jsonb(child) ORDER BY to_jsonb(child)::text), ''[]''::jsonb)'
                ' FROM %s AS child WHERE %s',
                v_relation, v_predicate
            ) INTO v_rows;
            IF jsonb_array_length(v_rows) > 0 THEN
                v_captured := v_captured || jsonb_build_object(v_relation, v_rows);
                v_relation_count := v_relation_count + 1;
                v_row_count := v_row_count + jsonb_array_length(v_rows);
            END IF;
        END LOOP;
        v_captured := v_captured || jsonb_build_object(
            'feature.features',
            (SELECT jsonb_build_array(to_jsonb(feature))
             FROM feature.features AS feature
             WHERE feature.feature_uuid = p_feature_uuid)
        );
        v_relation_count := v_relation_count + 1;
        v_row_count := v_row_count + 1;
    END IF;

    UPDATE feature.manual_feature_identity_claims
    SET purged_by_command_id = p_command_id,
        purged_at = clock_timestamp(),
        identity_released = p_release_identity
    WHERE feature_id = p_feature_uuid;

    INSERT INTO feature.manual_feature_purge_records (
        feature_uuid, feature_id, reason_code, identity_released,
        purged_by_command_id, purged_by_actor, captured_rows,
        captured_relation_count, captured_row_count, captured_sha256
    ) VALUES (
        p_feature_uuid, v_feature_id, p_reason_code, p_release_identity,
        p_command_id, p_actor,
        CASE WHEN p_reason_code = 'mistaken_creation' THEN v_captured ELSE NULL END,
        v_relation_count, v_row_count,
        encode(
            x_extension.digest(
                convert_to(
                    CASE WHEN p_reason_code = 'mistaken_creation'
                         THEN v_captured::text
                         ELSE p_feature_uuid::text
                    END,
                    'UTF8'
                ),
                'sha256'
            ),
            'hex'
        )
    ) RETURNING purge_id INTO o_purge_id;

    DELETE FROM feature.features WHERE feature_uuid = p_feature_uuid;

    o_outcome := 'purged';
    o_captured_relation_count := v_relation_count;
    o_captured_row_count := v_row_count;
END
$$
"""

#: **`::regclass`를 쓰지 않는다.** 그것은 `search_path`에 상대적으로 렌더링돼
#: `feature.feature_places`가 `feature_places`로 나온다. 복구점의 키가 스키마 없이
#: 저장되면 나중에 어느 표였는지 확정할 수 없다 — 같은 이름의 표가 두 스키마에 있을 수
#: 있기 때문이다. 이 저장소는 같은 함정을 `pg_get_function_identity_arguments()`에서
#: 이미 한 번 겪었다.
_QUALIFIED_NAME_HELPER: Final[str] = """
CREATE FUNCTION feature.qualified_relation_name(p_relation oid)
RETURNS text
    LANGUAGE sql STABLE
    SET search_path TO 'pg_catalog'
    AS $$
    SELECT format('%I.%I', namespace.nspname, relation.relname)
    FROM pg_catalog.pg_class AS relation
    JOIN pg_catalog.pg_namespace AS namespace
      ON namespace.oid = relation.relnamespace
    WHERE relation.oid = p_relation
$$
"""

_QUALIFIED_NAME_HELPER_DROP: Final[str] = (
    "DROP FUNCTION feature.qualified_relation_name(oid)"
)

#: 동적 count를 함수로 뺀다 — `SELECT` 안에서 `EXECUTE`를 쓸 수 없기 때문이다.
_COUNT_HELPER: Final[str] = """
CREATE FUNCTION feature.count_rows_dynamic(p_statement text)
RETURNS bigint
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'feature', 'ops', 'provider_sync'
    AS $$
DECLARE
    v_tally bigint;
BEGIN
    EXECUTE p_statement INTO v_tally;
    RETURN coalesce(v_tally, 0);
END
$$
"""

_COUNT_HELPER_DROP: Final[str] = "DROP FUNCTION feature.count_rows_dynamic(text)"

_PURGE_PROCEDURE_DROP: Final[str] = (
    "DROP PROCEDURE feature.purge_manual_feature(uuid, text, boolean, text, bigint)"
)

#: 런타임 로그인에는 주지 않는다. purge는 전용 운영 경로다.
_PURGE_HELPER_REVOKE: Final[str] = (
    "REVOKE ALL ON FUNCTION feature.count_rows_dynamic(text) FROM PUBLIC"
)

_PURGE_PROCEDURE_REVOKE: Final[str] = (
    "REVOKE ALL ON PROCEDURE"
    " feature.purge_manual_feature(uuid, text, boolean, text, bigint) FROM PUBLIC"
)

_RECEIPT_HEAD_WIDEN: Final[str] = (
    "ALTER TABLE ops.application_schema_operation_receipts"
    " DROP CONSTRAINT ck_application_schema_operation_receipts_head,"
    " ADD CONSTRAINT ck_application_schema_operation_receipts_head"
    " CHECK (destination_head IN ('300', '301_m03_import_children',"
    " '302_m03_child_issuance', '303_m05_payload_hash_domain',"
    " '304_m05_detector_manuals', '305_m05_relitigation_fence',"
    " '306_m02_manual_feature_purge'))"
)

_RECEIPT_HEAD_NARROW: Final[str] = (
    "ALTER TABLE ops.application_schema_operation_receipts"
    " DROP CONSTRAINT ck_application_schema_operation_receipts_head,"
    " ADD CONSTRAINT ck_application_schema_operation_receipts_head"
    " CHECK (destination_head IN ('300', '301_m03_import_children',"
    " '302_m03_child_issuance', '303_m05_payload_hash_domain',"
    " '304_m05_detector_manuals', '305_m05_relitigation_fence'))"
)


_UPGRADE_STATEMENTS: Final[tuple[str, ...]] = (
    _CLAIM_PURGE_COLUMNS,
    _CLAIM_PURGE_COMMAND_FK,
    _CLAIM_PURGE_PAIR_CHECK,
    _CLAIM_RELEASE_CHECK,
    _EXACT_UNIQUE_DROP,
    _EXACT_UNIQUE_PARTIAL,
    *_conflict_target_statements("upgraded"),
    _PURGE_RECORDS_TABLE,
    _PURGE_RECORDS_OWNER,
    _PURGE_RECORDS_APPEND_ONLY,
    _PURGE_RECORDS_NO_TRUNCATE,
    # append-only guard의 소유자는 audit writer다.
    "SET ROLE ktm_feature_audit_writer",
    _EVIDENCE_GUARD_UPGRADED,
    "SET ROLE ktm_feature_schema_owner",
    # fence의 소유자는 manual feature procedure owner다 — claim만 읽는다.
    "SET ROLE ktm_manual_feature_procedure_owner",
    _PURGE_FENCE_UPGRADED,
    "SET ROLE ktm_feature_schema_owner",
    # **purge 프로시저의 definer는 schema owner다.** 이 명령은 본질적으로
    # `feature.features`의 cascade 자식 **전부**를 읽고 지운다. 그러니 definer는 그
    # graph의 소유자여야 한다. 좁은 owner에게 그만큼을 GRANT로 주면 목록이 드리프트하고
    # (자식이 늘 때마다 갱신을 잊는다) 결국 같은 권한을 더 나쁜 방식으로 주게 된다.
    #
    # 대신 **도달 가능성**으로 좁힌다 — EXECUTE를 PUBLIC에서 회수하고 아무에게도 주지
    # 않는다. 즉 owner/superuser 외에는 부를 수 없고, 운영자에게 열려면 명시 GRANT가
    # 하나 더 있어야 한다.
    _QUALIFIED_NAME_HELPER,
    _COUNT_HELPER,
    _PURGE_PROCEDURE,
    _PURGE_HELPER_REVOKE,
    _PURGE_PROCEDURE_REVOKE,
    _RECEIPT_HEAD_WIDEN,
)

_DOWNGRADE_STATEMENTS: Final[tuple[str, ...]] = (
    _RECEIPT_HEAD_NARROW,
    _PURGE_PROCEDURE_DROP,
    _COUNT_HELPER_DROP,
    _QUALIFIED_NAME_HELPER_DROP,
    "SET ROLE ktm_manual_feature_procedure_owner",
    _PURGE_FENCE_ORIGINAL,
    "SET ROLE ktm_feature_audit_writer",
    _EVIDENCE_GUARD_ORIGINAL,
    "SET ROLE ktm_feature_schema_owner",
    _PURGE_RECORDS_TABLE_DROP,
    # 제약을 **먼저** 되돌린다 — 원래 본문이 그 이름을 가리키기 때문이다.
    _EXACT_UNIQUE_PARTIAL_DROP,
    _EXACT_UNIQUE_RESTORE,
    *_conflict_target_statements("original"),
    _CLAIM_PURGE_COLUMNS_DROP,
)


def upgrade() -> None:
    for statement in _UPGRADE_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    for statement in _DOWNGRADE_STATEMENTS:
        op.execute(statement)
