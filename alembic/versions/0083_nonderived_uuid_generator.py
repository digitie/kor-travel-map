"""비파생 UUIDv7 generator 전환 — 파생 CHECK 완화 + 선언적 사본 일치 (T-VN-32C, ADR-068).

Revision ID: 0083_nonderived_uuid_generator
Revises: 0082_legacy_write_fence
Create Date: 2026-08-05

32C 값 전환의 DB측 절반이다. 양 저장소 alias-map checksum 일치(2026-08-05 실측,
root ``8bd9534a…``·731,600행)로 rollout 게이트("checksum 일치 후 응답 전환")가
열렸고, 신규 행의 ``feature_uuid``를 legacy id 파생(uuid5)이 아니라 **비파생
UUIDv7**(app 정본 generator ``core.ids.make_feature_uuid``)로 만들기 위해 dual
기간 파생 강제를 해제한다.

무엇을 완화하나 (정확히 이 둘 — 세트로만)
-----------------------------------------

1. ``ck_features_feature_uuid_dual_derivation`` (0081) — features의
   ``feature_uuid = derive(feature_id)`` 강제. 비파생 신규 행이 위반한다.
2. ``ck_feature_aliases_uuid_dual_derivation`` (0081) — alias 행의 파생 강제.
   0080 세대의 AFTER 트리거가 features의 uuid를 alias 행에 그대로 복사하므로
   features 쪽만 떼면 alias INSERT에서 막힌다.

무엇으로 대체하나 (선언적 사본 일치)
------------------------------------

파생 CHECK 2종은 부수적으로 "alias.feature_uuid == features.feature_uuid"의
사본 일치를 간접 보장했다(둘 다 같은 파생식 — 0080/0081/0082 체인으로 기존
731,600행 전 행에서 즉시 유효함이 증명된다: closed kind → ``alias=feature_id``
→ 양쪽 파생식 동일). 해제 후 이 사본 일치가 트리거+0082 fence의 **절차적**
보장으로 격하되면 ``session_replication_role=replica`` 우회 창구가 넓어지므로,
선언적 대체를 넣는다:

- ``uq_features_identity_pair`` — ``UNIQUE (feature_id, feature_uuid)``.
  유일성 자체는 PK+``uq_features_feature_uuid``로 이미 성립하는 **redundant**
  인덱스다(비용: 731,600행 실측 인덱스 ~60MB + features INSERT write
  amplification) — 존재 이유는 오로지 복합 FK의 참조 대상이다.
- ``fk_feature_aliases_identity_pair`` — feature_aliases의
  ``(feature_id, feature_uuid) → features(feature_id, feature_uuid)``,
  **ON DELETE CASCADE**. alias 행의 uuid가 정본 행의 uuid와 다를 수 없음을
  DB 선언으로 고정한다.

  CASCADE가 필수인 이유(적대 리뷰 1 H1 실측): 기존
  ``fk_feature_aliases_feature``(CASCADE)와 NO ACTION 복합 FK가 공존하면
  features DELETE 시 RI 트리거 발화 순서가 **트리거 이름 문자열 순서**
  (``RI_ConstraintTrigger_a_<oid>``)에 의존한다 — OID 자릿수가 다르면 역순이
  되어 NO ACTION이 아직 남은 alias를 보고 23503으로 죽는다. CI(빈 DB 연속
  적용)는 항상 정순이라 못 잡고 prod/pg_restore 재구축에서만 터진다. 양쪽
  모두 CASCADE면 순서 무관(실측 확인).

한계 기록 (적대 리뷰 1 H3 — 새로 열리는 결함 계열)
--------------------------------------------------

FK는 child DML에서만 검사한다. ``session_replication_role=replica``로 features
행을 지워 orphan alias를 만든 뒤 같은 feature_id를 재-INSERT하면, 0080 세대
alias 트리거의 ``ON CONFLICT (alias) DO NOTHING``이 stale alias 행을 덮지
않아 **사본 불일치가 조용히 잔존**한다. 파생 세계에서는 재-INSERT가 같은
파생값을 만들어 이 계열이 성립하지 않았다 — 비파생 세계의 순수 신규 리스크다.
보상 관측: ``feature_identity.count_features_missing_identity``의
``alias_pair_mismatch`` 축(이 PR에서 추가)이 이 계열을 센다. 배포 사전 점검
쿼리도 동일 축이다::

    SELECT count(*) FROM feature.feature_aliases a
    JOIN feature.features f USING (feature_id)
    WHERE a.feature_uuid IS DISTINCT FROM f.feature_uuid;  -- 0이어야 함

무엇을 유지하나
---------------

- 0082 fence 전부(identity UPDATE 거부·alias UPDATE/직접 DELETE/TRUNCATE 거부).
- ``ck_feature_aliases_legacy_identity``(alias=feature_id), alias_kind 닫힌
  CHECK, canonical CHECK, ``uq_features_feature_uuid``, NOT NULL.
- fill BEFORE 트리거 — 파생 대신 **같은 v7 레이아웃**의 SQL 함수
  (``feature.uuid_generate_v7()``)로 본문 교체. raw SQL 경로가 파생 uuid를
  받으면 generator가 이원화되기 때문(app v7 ↔ SQL 파생). 명시 값 존중
  분기(NULL일 때만 채움)는 그대로다 — 명시 "파생값" INSERT(재적재·downgrade
  경로)도 여전히 합법이다.
- AFTER alias 트리거 — 비파생 값도 ``NEW.feature_uuid`` 복사로 INV-068-01을
  계속 보장한다.
- ``feature.feature_uuid_from_legacy(text)`` SQL 함수 — 기존 731,600행의
  파생값 역사·downgrade 경로가 참조하므로 제거하지 않는다.

잠금·적용 비용 (적대 리뷰 1 M2 실측)
------------------------------------

731,600행 로컬 실측: UNIQUE 인덱스 빌드 ~0.6s(+60MB)·FK 검증 ~0.8s. plain
``ADD CONSTRAINT``는 features에 ACCESS EXCLUSIVE를 잡으므로, 본 migration은
0080 docstring의 규율대로 **CONCURRENTLY 인덱스 → USING INDEX 연결, FK는
NOT VALID → VALIDATE**로 분해해 서비스 중 잠금 창을 최소화한다(CONCURRENTLY는
트랜잭션 밖 실행이 필요해 autocommit block을 쓴다). 단 표준 배포 경로는
api-entrypoint가 서빙 **전에** migration을 완료하므로 실제 경합 상대는 병행
dagster write뿐이다 — 배포 runbook은 write path 정지를 선행한다.

배포·롤백 결합 (적대 리뷰 1 H2 / 리뷰 2 F8)
-------------------------------------------

- api-entrypoint는 기동 시 무조건 ``alembic upgrade head``를 실행한다 — **이
  코드가 담긴 API 이미지를 배포하는 순간 0083이 적용된다**(분리 불가).
  따라서 "PinVi 쌍 PR 배포 전 KTM API·dagster 이미지 배포 금지"가 실질
  게이트다.
- dagster-entrypoint에는 migration/EXPECTED_HEAD 게이트가 **없다** — dagster
  이미지를 API보다 먼저 재배포하면 코드(비파생 후보 바인드)와 DB(0082 파생
  CHECK)가 어긋나 신규 feature 생성이 전면 23514로 죽는다. 배포 순서는
  반드시 **api 먼저 → dagster**.
- 앱 이미지 단독 롤백 불가: v7 행이 1건이라도 생긴 뒤 구 이미지(파생 대조
  verify)로 되돌리면 그 행들의 upsert가 영구 fail-close된다. 롤백은 0083
  downgrade와 **동반**해야 한다.

downgrade
---------

CHECK 2종을 ``NOT VALID``로 복원하고 fill 함수를 파생판으로 되돌린다.
PostgreSQL은 ``NOT VALID`` CHECK도 **신규 INSERT·UPDATE에 강제**하므로,
downgrade 후 비파생 잔존 행은 무관한 컬럼 UPDATE조차 23514로 거부되는
사실상 read-only 행이 된다(전량 복원 VALIDATE도 그 행들 때문에 불가).
또한 downgrade는 앱 이미지 롤백을 **전제**한다 — 신 앱이 남아 있으면 v7
후보 INSERT가 복원된 CHECK에 걸려 신규 생성이 전면 중단된다. 비파생 잔존
행의 처분은 운영 판단(수동)이다.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0083_nonderived_uuid_generator"
down_revision: str | Sequence[str] | None = "0082_legacy_write_fence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# RFC 9562 UUIDv7 — x_extension.gen_random_uuid()(pgcrypto, 0001이 x_extension에
# 설치·ADR-008 격리) 난수 16바이트에 ① 상위 6바이트를 unix-ms 빅엔디안 하위
# 6바이트로 교체, ② byte 6 상위 nibble에 version 7, ③ byte 8 상위 2비트에
# variant 10을 **명시적으로 심는다**(0080의 set_byte 관용구와 동일 — 난수
# 소스의 기존 비트에 의존하지 않는다, 적대 리뷰 1 M5). app 정본
# (core.ids.make_feature_uuid)과 같은 레이아웃 — 통합 테스트가 version/variant
# 비트 동일성을 대조한다. PG16에는 native uuidv7()가 없다.
_CREATE_UUID_V7_FUNCTION_SQL = """
CREATE FUNCTION feature.uuid_generate_v7()
RETURNS uuid
LANGUAGE plpgsql
VOLATILE
SET search_path = pg_catalog
AS $$
DECLARE
    raw bytea;
BEGIN
    -- 난수 16바이트의 상위 6바이트를 unix-ms(빅엔디안 하위 6바이트)로 교체.
    raw := overlay(
        uuid_send(x_extension.gen_random_uuid())
        PLACING substring(
            int8send((extract(epoch FROM clock_timestamp()) * 1000)::bigint)
            FROM 3 FOR 6
        )
        FROM 1 FOR 6
    );
    -- version 7: byte 6 상위 nibble = 0111 (0x70).
    raw := set_byte(raw, 6, (get_byte(raw, 6) & 15) | 112);
    -- variant RFC: byte 8 상위 2비트 = 10.
    raw := set_byte(raw, 8, (get_byte(raw, 8) & 63) | 128);
    RETURN encode(raw, 'hex')::uuid;
END;
$$
"""

# 0080 세대 원본과 동일 구조 — 파생 대신 v7. 명시 값 존중(NULL일 때만) 유지.
_REPLACE_FILL_FUNCTION_V7_SQL = """
CREATE OR REPLACE FUNCTION feature.fill_features_feature_uuid()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
BEGIN
    IF NEW.feature_uuid IS NULL THEN
        NEW.feature_uuid := feature.uuid_generate_v7();
    END IF;
    RETURN NEW;
END;
$$
"""

# downgrade 복원용 — 0080 세대 원본 본문.
_REPLACE_FILL_FUNCTION_DERIVED_SQL = """
CREATE OR REPLACE FUNCTION feature.fill_features_feature_uuid()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
BEGIN
    IF NEW.feature_uuid IS NULL THEN
        NEW.feature_uuid := feature.feature_uuid_from_legacy(NEW.feature_id);
    END IF;
    RETURN NEW;
END;
$$
"""


def upgrade() -> None:
    # 1) 파생 CHECK 세트 해제 (docstring §완화 — 단일 트랜잭션이라 순서 무관,
    #    세트로만 뗀다는 요구가 실질).
    op.execute(
        "ALTER TABLE feature.feature_aliases "
        "DROP CONSTRAINT ck_feature_aliases_uuid_dual_derivation"
    )
    op.execute(
        "ALTER TABLE feature.features "
        "DROP CONSTRAINT ck_features_feature_uuid_dual_derivation"
    )
    # 2) v7 generator + fill 트리거 함수 교체 (docstring §유지 — 이원화 차단).
    op.execute(_CREATE_UUID_V7_FUNCTION_SQL)
    op.execute(_REPLACE_FILL_FUNCTION_V7_SQL)
    # 3) 선언적 사본 일치 — 잠금 최소화 분해 (docstring §잠금·적용 비용):
    #    CONCURRENTLY는 트랜잭션 밖 실행이 필요하다.
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE UNIQUE INDEX CONCURRENTLY uq_features_identity_pair "
            "ON feature.features (feature_id, feature_uuid)"
        )
    op.execute(
        "ALTER TABLE feature.features "
        "ADD CONSTRAINT uq_features_identity_pair "
        "UNIQUE USING INDEX uq_features_identity_pair"
    )
    op.execute(
        """
        ALTER TABLE feature.feature_aliases
        ADD CONSTRAINT fk_feature_aliases_identity_pair
        FOREIGN KEY (feature_id, feature_uuid)
        REFERENCES feature.features (feature_id, feature_uuid)
        ON DELETE CASCADE
        NOT VALID
        """
    )
    op.execute(
        "ALTER TABLE feature.feature_aliases "
        "VALIDATE CONSTRAINT fk_feature_aliases_identity_pair"
    )


def downgrade() -> None:
    op.execute(_REPLACE_FILL_FUNCTION_DERIVED_SQL)
    op.execute("DROP FUNCTION IF EXISTS feature.uuid_generate_v7()")
    op.execute(
        "ALTER TABLE feature.feature_aliases "
        "DROP CONSTRAINT fk_feature_aliases_identity_pair"
    )
    op.execute(
        "ALTER TABLE feature.features DROP CONSTRAINT uq_features_identity_pair"
    )
    # NOT VALID 복원 — 비파생 잔존 행 존재 시 VALIDATE 불가 + 해당 행은 신규
    # INSERT/UPDATE에서도 강제되어 사실상 read-only (docstring §downgrade).
    op.execute(
        """
        ALTER TABLE feature.features
        ADD CONSTRAINT ck_features_feature_uuid_dual_derivation
        CHECK (feature_uuid = feature.feature_uuid_from_legacy(feature_id))
        NOT VALID
        """
    )
    op.execute(
        """
        ALTER TABLE feature.feature_aliases
        ADD CONSTRAINT ck_feature_aliases_uuid_dual_derivation
        CHECK (feature_uuid = feature.feature_uuid_from_legacy(alias))
        NOT VALID
        """
    )
