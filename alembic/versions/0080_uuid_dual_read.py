"""UUID dual read 지원 — 공개 view 노출 + dual 기간 파생 규칙 DB 강제 (T-VN-32B, ADR-068).

두 가지를 착지한다:

1. **공개 view의 feature_uuid 노출**. ``feature.public_features``(0062)는
   ``SELECT *``로 생성됐지만 view 컬럼 목록은 생성 시점에 고정되므로, 0079가
   추가한 ``feature_uuid`` shadow 컬럼이 공개 projection에 보이지 않는다.
   32B dual read(UUID 정본 읽기·additive 병행 노출)의 공개 read SQL이 base
   table 재조인 없이 ``feature_uuid``를 select할 수 있도록 view를 재생성한다.

   - ``CREATE OR REPLACE VIEW``는 기존 컬럼 목록 **끝에 추가**만 허용한다.
     ``feature_uuid``는 0079 ``ADD COLUMN``으로 table 컬럼 순서 마지막이고
     0062 이후 features에 추가된 컬럼은 이것뿐이므로, ``SELECT *`` 재고정은
     정확히 ``feature_uuid`` 1개를 끝에 덧붙인다.
   - 술어(``status='active' AND deleted_at IS NULL``)는 0062와 동일 — 공개
     여부 판정은 바꾸지 않는다(3축 정본 교체는 T-VN-34B 소관).

2. **dual 기간 파생 규칙의 DB 강제 (fail-close by construction)**. 32A freeze가
   "32B 소관"으로 남긴 정본 신규 행 generator를 32B는 **uuid5 파생 유지**로
   결정했다 — 결정론이 KTM/PinVi 양 저장소 독립 계산·checksum 대조(T-VN-32C)의
   전제라, legacy id가 존재하는 dual 기간에는 행마다 합법 UUID가 정확히 하나다.
   그 계약을 app 계층 검사에만 맡기지 않고 CHECK로 저장 경계에서 강제한다:

   - ``ck_features_feature_uuid_dual_derivation`` —
     ``feature_uuid = feature.feature_uuid_from_legacy(feature_id)``
   - ``ck_feature_aliases_uuid_dual_derivation`` — alias 행의 파생 사본도 동일
     규칙(32C DB-to-DB alias map 이관 무결성).

   기존 행은 전부 0079 결정적 backfill 산출이라 즉시 유효하다. 이 CHECK는
   **dual 기간 한정 fence**다 — legacy id가 소멸하는 cutover(T-VN-32C write
   fence/39)에서 비파생 generator(UUIDv7 등) 채택과 함께 제거한다(ADR-075의
   단계 fence 규율). 0079 트리거의 "명시 값 존중"은 유지되지만, dual 기간에
   파생값과 다른 명시 값은 이제 DB가 거부한다(의도된 강화 — 32A 시점의 열린
   계약을 32B가 닫았다. 32A 통합 테스트의 임의 명시 uuid 케이스는 fail-close
   계약으로 재정의됨).

   비용: pgcrypto SHA-1 1회/row write — 짧은 문자열 digest ~µs 수준, MOIS
   bulk(수십만 행) 재적재에도 초 단위 부가로 무해하다.

downgrade는 CHECK 2종을 떼고 view를 0080 이전 shape(``feature_uuid`` 제외)으로
재생성한다. 0079 downgrade(``DROP COLUMN``/``DROP FUNCTION``)가 view·CHECK
의존성 오류 없이 이어지도록, information_schema에서 현재 컬럼 목록을 읽어
``feature_uuid``만 제외한 명시 목록으로 만든다(컬럼 하드코딩 drift 회피).

Revision ID: 0080_uuid_dual_read
Revises: 0079_feature_uuid_shadow
Create Date: 2026-08-04
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0080_uuid_dual_read"
down_revision: str | Sequence[str] | None = "0079_feature_uuid_shadow"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1) 공개 view 컬럼 목록 재고정 — feature_uuid가 끝에 추가된다.
    op.execute(
        """
        CREATE OR REPLACE VIEW feature.public_features AS
        SELECT *
        FROM feature.features
        WHERE status = 'active'
          AND deleted_at IS NULL
        """
    )
    # 2) dual 기간 파생 규칙 fence — 기존 행은 0079 backfill 산출이라 즉시 유효.
    op.execute(
        """
        ALTER TABLE feature.features
        ADD CONSTRAINT ck_features_feature_uuid_dual_derivation
        CHECK (feature_uuid = feature.feature_uuid_from_legacy(feature_id))
        """
    )
    op.execute(
        """
        ALTER TABLE feature.feature_aliases
        ADD CONSTRAINT ck_feature_aliases_uuid_dual_derivation
        CHECK (feature_uuid = feature.feature_uuid_from_legacy(feature_id))
        """
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE feature.feature_aliases "
        "DROP CONSTRAINT ck_feature_aliases_uuid_dual_derivation"
    )
    op.execute(
        "ALTER TABLE feature.features "
        "DROP CONSTRAINT ck_features_feature_uuid_dual_derivation"
    )
    # CREATE OR REPLACE로는 컬럼을 제거할 수 없다 — DROP 후 feature_uuid를 제외한
    # 명시 컬럼 목록으로 재생성한다(0079 downgrade의 DROP COLUMN 선행 조건).
    op.execute("DROP VIEW feature.public_features")
    op.execute(
        """
        DO $$
        DECLARE
            cols text;
        BEGIN
            SELECT string_agg(quote_ident(column_name), ', ' ORDER BY ordinal_position)
            INTO cols
            FROM information_schema.columns
            WHERE table_schema = 'feature'
              AND table_name = 'features'
              AND column_name <> 'feature_uuid';
            EXECUTE format(
                'CREATE VIEW feature.public_features AS '
                'SELECT %s FROM feature.features '
                'WHERE status = ''active'' AND deleted_at IS NULL',
                cols
            );
        END
        $$
        """
    )
