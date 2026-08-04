"""UUID identity shadow — schema·deterministic backfill (T-VN-32A, ADR-068).

``feature.features``에 ``feature_uuid`` shadow 컬럼과
``feature.feature_aliases`` legacy alias table을 **추가만** 한다. 현행 문자열
``f_*`` PK·FK·읽기 경로는 무변경이다 (consumer-rollout-v1.json T-VN-32 "32A:
읽기 경로 무변경"). 목표 계약은 ``contracts/vnext/target-schema-v1.sql``
§3(features UUID core)·§4(feature_aliases)이며, shadow 단계 이름은 freeze
목표형과 충돌하지 않게 대응물만 정합한다(예: UNIQUE는 목표 ``pk_features``
대신 ``uq_features_feature_uuid``).

freeze가 "미정(T-VN-32A 구현 소관)"으로 남긴 3건을 본 revision이 결정한다:

1. **backfill/shadow UUID generator** — ``uuid5(FEATURE_UUID_NAMESPACE,
   legacy_feature_id)``. namespace는
   ``uuid5(NAMESPACE_URL, 'kor-travel-map:feature-uuid:v1')``
   = ``75d60e13-2779-5b06-a920-6b1b892a7c84``
   (``core/ids.py FEATURE_UUID_NAMESPACE``와 동일 상수). 근거: 같은
   snapshot에서 재실행해도, KTM/PinVi 두 저장소가 독립 계산해도 같은 UUID
   (T-VN-32C alias-map DB-to-DB checksum 대조의 전제). 입력이 legacy id
   문자열 하나뿐이라 수정 가능한 속성(bjd/category)이 identity에 재유입되지
   않는다(ADR-068 결정 2). **DB server default는 두지 않는다** — 정본 신규
   행 generator(UUIDv7 채택 여부)는 freeze 주석대로 열린 결정이며 T-VN-32B
   소관이다. shadow 기간 신규 INSERT는 legacy id가 항상 존재하므로 같은
   파생 규칙을 트리거로 적용한다(아래 3).
2. **alias_kind 값 집합** — 닫힌 CHECK ``('legacy_feature_id')``. 32A가
   만드는 alias는 legacy id 1종뿐이고, 닫힌 domain이 writer의 임의 kind
   발명을 fail-close한다. 새 kind(예: merge-loser alias)가 정본 결정되면
   CHECK 확장 migration 한 줄로 추가한다.
3. **alias FK ON DELETE** — ``CASCADE``. alias·uuid는 legacy id에서 언제든
   재계산 가능한 **파생값**이고(손실 없음), feature 종속 행의 기존 정본
   패턴(freeze의 feature_state_transitions/source_links/weather·price FK)도
   일관되게 CASCADE다. ADR-068/075의 "alias 제거 금지"는 cutover-era의
   테이블/열 제거 DDL에 대한 규율이지, 물리 purge된 행의 참조 위생과는
   별개다(현행 코드에 feature 물리 DELETE 경로는 없음 — notice purge도
   soft-delete).

신규 INSERT 경로: ``feature.features``에 INSERT하는 경로는 repo 2곳
(provider upsert·admin add)에 더해 통합 테스트 37개 파일이 raw SQL로 직접
seed한다. NOT NULL을 걸려면 **모든** INSERT가 uuid를 채워야 하므로, 경로별
SQL 수정 대신 DB 트리거로 일괄 보장한다(가장 단순·안전 — 누락 경로가
생길 수 없음):

- ``trg_features_feature_uuid_fill`` (BEFORE INSERT): ``feature_uuid``가
  NULL이면 파생값으로 채운다. 호출자가 명시한 값(32B writer)은 존중한다.
- ``trg_features_legacy_alias`` (AFTER INSERT): 같은 transaction에서 legacy
  alias 행을 원자 생성한다(INV-068-01 post-backfill 유지). 재생성 시 같은
  파생값이므로 ``ON CONFLICT (alias) DO NOTHING``이 안전하다.

T-VN-32B 결정: 두 트리거는 writer 명시 생성이 착지한 뒤에도 raw SQL 경로의
안전망으로 **유지**한다(제거는 T-VN-32C write fence 시점 재평가). 파생 규칙
자체는 0080의 CHECK(``ck_features_feature_uuid_dual_derivation``)가 dual 기간
동안 DB 층에서 강제한다 — 트리거 fill 값·writer 명시 값 모두 그 CHECK를
통과해야 한다.

T-VN-32C 재평가 결론(0081): 두 트리거 **유지**. fill 트리거는 0080 CHECK가
요구하는 유일값만 쓸 수 있으므로 legacy-only write의 우회로가 아니라 강제
메커니즘의 일부이고, AFTER alias 트리거는 INV-068-01의 원자 보장이다. 32C
write fence는 0081이 alias map 불변(UPDATE 거부·직접 DELETE 거부)과 identity
불변(feature_id/feature_uuid UPDATE 거부)으로 착지했다. 트리거·CHECK 제거는
비파생 generator 채택(32C 잔여 — 양 저장소 checksum 일치 뒤)과 함께
재평가한다.

ADR-075 규율:

- 단일 transaction·``autocommit_block`` 미사용(0062와 같은 근거 — 실패 시
  전체 rollback으로 재시도 불능 상태를 남기지 않는다). 현재 행수(~1만)에서
  전량 backfill·SET NOT NULL·UNIQUE 직접 연결은 무해하다.
- MOIS bulk 재적재 후(수십만~100만 행) 재실행 시나리오: backfill UPDATE는
  ``WHERE feature_uuid IS NULL``이라 운영자가 migration 전에 같은 문장을
  LIMIT 배치로 선실행(pre-backfill)해도 결과가 같다(idempotent·결정적).
  그 규모에서는 UNIQUE를 ``CREATE UNIQUE INDEX CONCURRENTLY`` 후 연결하고
  NOT NULL은 ``CHECK ... NOT VALID`` → ``VALIDATE`` → ``SET NOT NULL``
  경로를 쓴다(ADR-075 결정 5).
- backfill UPDATE는 ``trg_features_row_revision``(0062)을 발화시켜 전 행의
  row_revision이 +1 된다 — 행이 실제로 바뀌므로 의미상 옳다(ETag 재검증
  1회 유발). ``trg_features_coord_precision``은 ``UPDATE OF coord``
  한정이라 발화하지 않는다.

downgrade: shadow 제거 — 트리거/함수/alias table/UNIQUE/컬럼 모두 파생
구조물이라 무손실이다. 재-upgrade하면 같은 값이 재계산된다(결정성).

Revision ID: 0079_feature_uuid_shadow
Revises: 0078_cache_target_gc_observe
Create Date: 2026-08-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision: str = "0079_feature_uuid_shadow"
down_revision: str | Sequence[str] | None = "0078_cache_target_gc_observe"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# core/ids.py FEATURE_UUID_NAMESPACE의 bytes hex — uuid5(NAMESPACE_URL,
# 'kor-travel-map:feature-uuid:v1'). 변경 금지(영구 약속): 바뀌면 backfill된
# 전 UUID가 갈라진다. 통합 테스트가 Python uuid5 고정 벡터와 대조한다.
_NAMESPACE_HEX = "75d60e1327795b06a9206b1b892a7c84"

# RFC 4122 uuid5의 수동 구성 — sha1(namespace_bytes || name_utf8)의 앞 16
# byte에 version(0x50)·variant(0x80) 비트를 심는다. ``uuid_generate_v5``는
# uuid-ossp 확장이 필요한데 x_extension에는 없고(pgcrypto/postgis/pg_trgm만,
# ADR-008), pgcrypto ``digest(..., 'sha1')``로 동일 결과를 만든다.
_CREATE_UUID_FUNCTION_SQL = f"""
CREATE FUNCTION feature.feature_uuid_from_legacy(legacy_feature_id text)
RETURNS uuid
LANGUAGE sql
IMMUTABLE STRICT PARALLEL SAFE
SET search_path = pg_catalog
AS $$
SELECT encode(
           set_byte(
               set_byte(
                   sha.digest16,
                   6,
                   (get_byte(sha.digest16, 6) & 15) | 80
               ),
               8,
               (get_byte(sha.digest16, 8) & 63) | 128
           ),
           'hex'
       )::uuid
FROM (
    SELECT substring(
               x_extension.digest(
                   decode('{_NAMESPACE_HEX}', 'hex')
                       || convert_to(legacy_feature_id, 'UTF8'),
                   'sha1'
               )
               FROM 1 FOR 16
           ) AS digest16
) AS sha
$$
"""

_CREATE_FILL_TRIGGER_FUNCTION_SQL = """
CREATE FUNCTION feature.fill_features_feature_uuid()
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

_CREATE_ALIAS_TRIGGER_FUNCTION_SQL = """
CREATE FUNCTION feature.ensure_features_legacy_alias()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
BEGIN
    INSERT INTO feature.feature_aliases (alias, feature_id, feature_uuid, alias_kind)
    VALUES (NEW.feature_id, NEW.feature_id, NEW.feature_uuid, 'legacy_feature_id')
    ON CONFLICT (alias) DO NOTHING;
    RETURN NULL;
END;
$$
"""


def upgrade() -> None:
    # 1) 결정적 파생 함수 (backfill·트리거 공용).
    op.execute(_CREATE_UUID_FUNCTION_SQL)

    # 2) shadow 컬럼 — nullable로 추가 후 backfill, 그 다음 NOT NULL.
    op.add_column(
        "features",
        sa.Column("feature_uuid", UUID(as_uuid=False), nullable=True),
        schema="feature",
    )

    # 3) legacy alias table — 컬럼·제약 이름은 freeze §4 대응물과 정합.
    #    shadow 단계 실질 결합축은 legacy feature_id(text FK)이고 feature_uuid는
    #    32C 이관 때 재작성 없이 쓰는 파생 사본이다.
    op.create_table(
        "feature_aliases",
        sa.Column("alias", sa.Text(), nullable=False),
        sa.Column("feature_id", sa.Text(), nullable=False),
        sa.Column("feature_uuid", UUID(as_uuid=False), nullable=False),
        sa.Column("alias_kind", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("alias", name="pk_feature_aliases"),
        sa.ForeignKeyConstraint(
            ["feature_id"],
            ["feature.features.feature_id"],
            name="fk_feature_aliases_feature",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "alias <> '' AND alias = btrim(alias)",
            name="ck_feature_aliases_alias_canonical",
        ),
        sa.CheckConstraint(
            "alias_kind <> '' AND alias_kind = btrim(alias_kind)",
            name="ck_feature_aliases_kind_canonical",
        ),
        # 닫힌 값 집합 — 결정 2 (docstring). freeze의 canonical CHECK와 별도로
        # domain을 고정한다.
        sa.CheckConstraint(
            "alias_kind IN ('legacy_feature_id')",
            name="ck_feature_aliases_alias_kind",
        ),
        schema="feature",
    )
    op.create_index(
        "idx_feature_aliases_feature",
        "feature_aliases",
        ["feature_id"],
        schema="feature",
    )
    # 32B dual-read(UUID 정본 읽기 → alias 경계 해석)의 역방향 access path.
    op.create_index(
        "idx_feature_aliases_feature_uuid",
        "feature_aliases",
        ["feature_uuid"],
        schema="feature",
    )

    # 4) deterministic backfill — 같은 snapshot 재실행 시 같은 UUID.
    #    WHERE feature_uuid IS NULL이라 대량 행에서는 같은 문장을 LIMIT 배치로
    #    선실행할 수 있다(docstring ADR-075 절). row_revision +1 부수효과는
    #    docstring 참조.
    op.execute(
        """
        UPDATE feature.features
        SET feature_uuid = feature.feature_uuid_from_legacy(feature_id)
        WHERE feature_uuid IS NULL
        """
    )
    op.execute(
        """
        INSERT INTO feature.feature_aliases (alias, feature_id, feature_uuid, alias_kind)
        SELECT feature_id, feature_id, feature_uuid, 'legacy_feature_id'
        FROM feature.features
        ON CONFLICT (alias) DO NOTHING
        """
    )

    # 5) backfill 완료 후 불변식 연결 — NOT NULL + UNIQUE. 이름은 freeze 목표형
    #    (pk_features가 uuid로 넘어가는 것은 32C/39)과 충돌하지 않는 shadow명.
    op.alter_column(
        "features",
        "feature_uuid",
        nullable=False,
        schema="feature",
    )
    op.create_unique_constraint(
        "uq_features_feature_uuid",
        "features",
        ["feature_uuid"],
        schema="feature",
    )

    # 6) 신규 INSERT 경로 보장 트리거 — 모든 write 경로(repo 2곳 + 직접 SQL)에
    #    일괄 적용. 32B가 writer 원자 생성으로 대체하며 제거한다.
    op.execute(_CREATE_FILL_TRIGGER_FUNCTION_SQL)
    op.execute(
        "CREATE TRIGGER trg_features_feature_uuid_fill "
        "BEFORE INSERT ON feature.features "
        "FOR EACH ROW EXECUTE FUNCTION feature.fill_features_feature_uuid()"
    )
    op.execute(_CREATE_ALIAS_TRIGGER_FUNCTION_SQL)
    op.execute(
        "CREATE TRIGGER trg_features_legacy_alias "
        "AFTER INSERT ON feature.features "
        "FOR EACH ROW EXECUTE FUNCTION feature.ensure_features_legacy_alias()"
    )


def downgrade() -> None:
    # shadow 제거 — alias/uuid는 legacy id의 파생값이라 무손실이다. 재-upgrade
    # 시 같은 값이 재계산된다(결정성 보장).
    op.execute("DROP TRIGGER IF EXISTS trg_features_legacy_alias ON feature.features")
    op.execute("DROP FUNCTION IF EXISTS feature.ensure_features_legacy_alias()")
    op.execute("DROP TRIGGER IF EXISTS trg_features_feature_uuid_fill ON feature.features")
    op.execute("DROP FUNCTION IF EXISTS feature.fill_features_feature_uuid()")
    op.drop_table("feature_aliases", schema="feature")
    op.drop_constraint("uq_features_feature_uuid", "features", schema="feature", type_="unique")
    op.drop_column("features", "feature_uuid", schema="feature")
    op.execute("DROP FUNCTION IF EXISTS feature.feature_uuid_from_legacy(text)")
