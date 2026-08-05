"""비파생 UUIDv7 generator 전환 — 파생 CHECK 완화 + 선언적 사본 일치 (T-VN-32C, ADR-068).

Revision ID: 0083_nonderived_uuid_generator
Revises: 0082_legacy_write_fence
Create Date: 2026-08-05

32C 값 전환의 DB측 절반이다. 양 저장소 alias-map checksum 일치(2026-08-05 실측,
root ``8bd9534a…``·731,600행)로 rollout 게이트("checksum 일치 후 응답 전환")가
열렸고, 신규 행의 ``feature_uuid``를 legacy id 파생(uuid5)이 아니라 **비파생
UUIDv7**(app 정본 generator ``core.ids.make_feature_uuid``)로 만들기 위해 dual
기간 파생 강제를 해제한다.

무엇을 완화하나 (정확히 이 둘)
------------------------------

1. ``ck_features_feature_uuid_dual_derivation`` (0081) — features의
   ``feature_uuid = derive(feature_id)`` 강제. 비파생 신규 행이 위반한다.
2. ``ck_feature_aliases_uuid_dual_derivation`` (0081) — alias 행의 파생 강제.
   0080 AFTER 트리거가 features의 uuid를 alias 행에 그대로 복사하므로 features
   쪽만 떼면 alias INSERT에서 막힌다 — **세트로만** 뗀다.

무엇으로 대체하나 (선언적 사본 일치)
------------------------------------

파생 CHECK 2종은 부수적으로 "alias.feature_uuid == features.feature_uuid"의
사본 일치를 간접 보장했다(둘 다 같은 파생식). 해제 후 이 사본 일치가 트리거
+0082 fence의 **절차적** 보장으로 격하되면 ``session_replication_role=replica``
우회 창구가 넓어지므로, 선언적 대체를 넣는다:

- ``uq_features_identity_pair`` — ``UNIQUE (feature_id, feature_uuid)``
  (복합 FK의 참조 대상. ``uq_features_feature_uuid`` 단독 유니크는 유지).
- ``fk_feature_aliases_identity_pair`` — feature_aliases의
  ``(feature_id, feature_uuid) → features(feature_id, feature_uuid)``.
  alias 행의 uuid가 정본 행의 uuid와 **다를 수 없음**을 DB 선언으로 고정.
  기존 FK(``feature_id → features`` CASCADE)는 삭제 전파용으로 유지한다.

무엇을 유지하나
---------------

- 0082 fence 전부(identity UPDATE 거부·alias UPDATE/직접 DELETE/TRUNCATE 거부).
- ``ck_feature_aliases_legacy_identity``(alias = feature_id),
  alias_kind 닫힌 CHECK, canonical text CHECK, ``uq_features_feature_uuid``,
  NOT NULL.
- 0080 fill BEFORE 트리거 — 단 파생이 아니라 **같은 v7 레이아웃**의 SQL 함수
  (``feature.uuid_generate_v7()``)로 교체한다. raw SQL 경로(통합 테스트·수동
  INSERT)가 파생 uuid를 받으면 generator가 이원화되기 때문(app v7 ↔ SQL 파생).
  명시 값 존중 분기(NULL일 때만 채움)는 그대로다.
- 0080 AFTER alias 트리거 — 비파생 값도 ``NEW.feature_uuid`` 복사로
  INV-068-01(행 생성과 alias 원자성)을 계속 보장한다.
- ``feature.feature_uuid_from_legacy(text)`` SQL 함수 — 기존 731,600행의
  파생값 역사·downgrade 경로가 참조하므로 제거하지 않는다.

downgrade
---------

CHECK 2종을 ``NOT VALID``로 복원하고 fill 함수를 파생판으로 되돌린다.
**비파생 행이 이미 생성된 DB에서는 VALIDATE CONSTRAINT가 23514로 실패한다** —
기계적 전체 복원은 불가능하며, downgrade의 의미는 "신규 INSERT부터 파생 강제
재개(파생-only 모드 복귀)"다. 비파생 잔존 행의 처분은 운영 판단(수동)이다.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0083_nonderived_uuid_generator"
down_revision: str | Sequence[str] | None = "0082_legacy_write_fence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# RFC 9562 UUIDv7 — gen_random_uuid()(pgcrypto, 0079가 보장) 난수 위에
# 상위 48bit unix-ms 타임스탬프와 version/variant 비트를 오버레이한다.
# PG16에는 native uuidv7()가 없다. app 정본(core.ids.make_feature_uuid)과
# 같은 레이아웃 — 통합 테스트가 version/variant 비트 동일성을 대조한다.
_CREATE_UUID_V7_FUNCTION_SQL = """
CREATE FUNCTION feature.uuid_generate_v7()
RETURNS uuid
LANGUAGE sql
VOLATILE
SET search_path = pg_catalog
AS $$
SELECT encode(
    set_bit(
        set_bit(
            overlay(
                uuid_send(gen_random_uuid())
                PLACING substring(
                    int8send((extract(epoch FROM clock_timestamp()) * 1000)::bigint)
                    FROM 3 FOR 6
                )
                FROM 1 FOR 6
            ),
            52, 1
        ),
        53, 1
    ),
    'hex'
)::uuid
$$
"""

# 0080 원본과 동일 구조 — 파생 대신 v7. 명시 값 존중(NULL일 때만) 유지.
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

# downgrade 복원용 — 0080 원본 본문.
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
    # 1) 파생 CHECK 세트 해제 (docstring §완화 — 순서: alias → features).
    op.execute(
        "ALTER TABLE feature.feature_aliases "
        "DROP CONSTRAINT ck_feature_aliases_uuid_dual_derivation"
    )
    op.execute(
        "ALTER TABLE feature.features "
        "DROP CONSTRAINT ck_features_feature_uuid_dual_derivation"
    )
    # 2) 선언적 사본 일치 (docstring §대체).
    op.execute(
        "ALTER TABLE feature.features "
        "ADD CONSTRAINT uq_features_identity_pair UNIQUE (feature_id, feature_uuid)"
    )
    op.execute(
        """
        ALTER TABLE feature.feature_aliases
        ADD CONSTRAINT fk_feature_aliases_identity_pair
        FOREIGN KEY (feature_id, feature_uuid)
        REFERENCES feature.features (feature_id, feature_uuid)
        """
    )
    # 3) v7 generator + fill 트리거 함수 교체 (docstring §유지 — 이원화 차단).
    op.execute(_CREATE_UUID_V7_FUNCTION_SQL)
    op.execute(_REPLACE_FILL_FUNCTION_V7_SQL)


def downgrade() -> None:
    op.execute(_REPLACE_FILL_FUNCTION_DERIVED_SQL)
    op.execute("DROP FUNCTION feature.uuid_generate_v7()")
    op.execute(
        "ALTER TABLE feature.feature_aliases "
        "DROP CONSTRAINT fk_feature_aliases_identity_pair"
    )
    op.execute(
        "ALTER TABLE feature.features DROP CONSTRAINT uq_features_identity_pair"
    )
    # NOT VALID 복원 — 비파생 행 존재 시 VALIDATE는 불가(docstring §downgrade).
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
