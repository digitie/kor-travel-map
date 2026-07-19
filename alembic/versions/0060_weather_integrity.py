"""feature_weather_values 무결성 제약 — semantic UNIQUE + range/payload CHECK + source FK.

Revision ID: 0060_weather_integrity
Revises: 0059_public_features_view
Create Date: 2026-07-19

배경 (F-7 weather/price 비대칭, ADR-072 / ADR-075 D-12-1)
--------------------------------------------------------
``feature_price_values``(0034)는 semantic tuple UNIQUE·source-record FK·값 CHECK를
가지지만 ``feature_weather_values``(0017)에는 없다. PK ``weather_value_key``는
identity tuple의 SHA1 해시라 **의미적 UNIQUE가 아니다**: 같은 순간(timestamptz는
instant를 저장)을 서로 다른 tz 표기(예: ``+09:00`` vs ``Z``)로 적재하면
``issued_at.isoformat()`` 입력이 달라 다른 key를 받아 두 행이 공존한다. 이 revision은
price의 무결성 패턴을 미러링해 weather에 다음을 도입한다.

semantic UNIQUE tuple (WeatherValue.identity() / make_weather_value_key 와 동일 축):
  (feature_id, provider, weather_domain, forecast_style, metric_key,
   issued_at, valid_at, observed_at)
  - feature_id/provider/weather_domain/forecast_style/metric_key: 어떤
    feature·제공기관·도메인·예보종류·지표인지 (non-null 축).
  - issued_at/valid_at/observed_at: 발표·유효·관측 시각 (nullable 시간축). 셋 다
    nullable이라 ``NULLS NOT DISTINCT``(PG15+)로 "둘 다 NULL이면 같은 행"으로 묶어
    중복을 막는다. timeline_bucket은 ADR-010 분류 결과(재계산 가능)라 제외한다.

DDL 유형별 절차 (ADR-075 결정 5·6, ~30M행 → rewrite/STORED 금지)
----------------------------------------------------------------
1. **DEDUP FIRST** — UNIQUE 빌드는 기존 중복이 있으면 실패하므로 먼저 제거한다.
   keep-rule(ADR-072 "새 known_at/issued_at이 이긴다"): 같은 semantic tuple 내에서
   ``collected_at``(=시스템이 알게 된 known_at proxy) 최신, 동률이면 ``updated_at``
   최신, 그래도 동률이면 ``weather_value_key`` 내림차순으로 1건만 남기고 삭제한다.
   운영자 pre-count(삭제 대상 loser 수):

       SELECT count(*) AS duplicate_losers
       FROM (
           SELECT row_number() OVER (
               PARTITION BY feature_id, provider, weather_domain,
                            forecast_style, metric_key,
                            issued_at, valid_at, observed_at
               ORDER BY collected_at DESC NULLS LAST,
                        updated_at DESC NULLS LAST,
                        weather_value_key DESC
           ) AS rn
           FROM feature.feature_weather_values
       ) t
       WHERE t.rn > 1;

2. **CREATE UNIQUE INDEX CONCURRENTLY** — 트랜잭션 밖(autocommit_block)에서
   ``NULLS NOT DISTINCT``로 만든다. writer는 같은 PR에서 ON CONFLICT 대상을 이
   index tuple로 전환한다(``weather_repo._INSERT_SQL`` / ``_WEATHER_CONFLICT_TARGET``).
   INVALID index 복구: CONCURRENTLY가 실패하면 INVALID index가 남는다. 탐지·제거:

       SELECT c.relname, i.indisvalid
       FROM pg_class c JOIN pg_index i ON i.indexrelid = c.oid
       WHERE c.relname = 'uq_weather_value_identity';
       -- indisvalid=false 이면:
       DROP INDEX CONCURRENTLY IF EXISTS feature.uq_weather_value_identity;

   본 revision은 CREATE 전에 ``DROP INDEX CONCURRENTLY IF EXISTS``를 실행해
   실패 후 재실행(alembic이 0060을 stamp하기 전 재시도)에서도 leftover INVALID
   index를 지우고 다시 만든다.

3. **range/payload CHECK + source FK** — ``NOT VALID``로 추가(메타데이터만, 즉시
   완료, 짧은 SHARE UPDATE EXCLUSIVE) 후 별도 ``VALIDATE CONSTRAINT``(테이블 스캔
   하되 SHARE UPDATE EXCLUSIVE라 write 비차단, rewrite 없음). 운영자 pre-count로
   VALIDATE 실패를 사전 확인할 수 있다:

       SELECT count(*) FILTER (
           WHERE valid_from IS NOT NULL AND valid_until IS NOT NULL
                 AND valid_from > valid_until
       ) AS range_violations,
       count(*) FILTER (WHERE jsonb_typeof(payload) <> 'object')
           AS payload_violations,
       count(*) FILTER (
           WHERE source_record_key IS NOT NULL
             AND NOT EXISTS (
                 SELECT 1 FROM provider_sync.source_records sr
                 WHERE sr.source_record_key
                     = feature.feature_weather_values.source_record_key
             )
       ) AS orphan_source_records
       FROM feature.feature_weather_values;

이 revision은 컬럼 추가·타입 변경·STORED 추가·테이블 rewrite를 하지 않는다.
weather는 아직 SQLAlchemy ``models.metadata``에 모델링되지 않으므로(T-VN-38 소유)
autogenerate/``alembic check`` 비교 대상이 아니다 — 본 제약은 migration으로만 둔다.

DOWNGRADE는 제약·index를 되돌리지만 DEDUP으로 삭제한 loser 행은 복구하지 않는다
(파생/중복 데이터라 원본 이력에서 재적재로 복원한다, ADR-072).

source-record FK 지원 index: price(0034)는 ``idx_price_values_source_record``
(partial, source_record_key)를 두어 source_record 삭제 시 ON DELETE SET NULL의
참조행 조회를 인덱스화한다. weather의 동등 index는 index 감사 lane(T-VN-18)이
소유하므로 여기서는 만들지 않는다 — source_records는 immutable lineage라 삭제가
드물어 즉시 위험은 낮다(리뷰 판단 필요).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0060_weather_integrity"
down_revision: str | Sequence[str] | None = "0059_public_features_view"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_TABLE = "feature.feature_weather_values"
_UNIQUE_INDEX = "uq_weather_value_identity"


def upgrade() -> None:
    # 1) DEDUP FIRST — semantic tuple 중복 제거 (NULLS는 PARTITION BY에서 동일 그룹).
    #    keep: collected_at(known_at proxy) 최신 → updated_at 최신 → key 내림차순.
    op.execute(
        f"""
        WITH ranked AS (
            SELECT weather_value_key,
                   row_number() OVER (
                       PARTITION BY feature_id, provider, weather_domain,
                                    forecast_style, metric_key,
                                    issued_at, valid_at, observed_at
                       ORDER BY collected_at DESC NULLS LAST,
                                updated_at DESC NULLS LAST,
                                weather_value_key DESC
                   ) AS rn
            FROM {_TABLE}
        )
        DELETE FROM {_TABLE} AS w
        USING ranked
        WHERE w.weather_value_key = ranked.weather_value_key
          AND ranked.rn > 1
        """
    )

    # 2) semantic UNIQUE — CONCURRENTLY + NULLS NOT DISTINCT, 트랜잭션 밖.
    #    재실행 안전: leftover INVALID index를 먼저 CONCURRENTLY drop한다.
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS feature.{_UNIQUE_INDEX}")
        op.execute(
            f"""
            CREATE UNIQUE INDEX CONCURRENTLY {_UNIQUE_INDEX}
            ON {_TABLE} (
                feature_id, provider, weather_domain, forecast_style, metric_key,
                issued_at, valid_at, observed_at
            )
            NULLS NOT DISTINCT
            """
        )

    # 3) range CHECK — valid_from <= valid_until (둘 중 NULL이면 통과). NOT VALID→VALIDATE.
    op.execute(
        f"""
        ALTER TABLE {_TABLE}
        ADD CONSTRAINT ck_weather_value_range
        CHECK (
            valid_from IS NULL
            OR valid_until IS NULL
            OR valid_from <= valid_until
        )
        NOT VALID
        """
    )
    op.execute(f"ALTER TABLE {_TABLE} VALIDATE CONSTRAINT ck_weather_value_range")

    # 4) payload object CHECK (price 미러 — payload는 JSON object). NOT VALID→VALIDATE.
    op.execute(
        f"""
        ALTER TABLE {_TABLE}
        ADD CONSTRAINT ck_weather_value_payload_object
        CHECK (jsonb_typeof(payload) = 'object')
        NOT VALID
        """
    )
    op.execute(
        f"ALTER TABLE {_TABLE} VALIDATE CONSTRAINT ck_weather_value_payload_object"
    )

    # 5) source-record FK (price 미러 — ON DELETE SET NULL). NOT VALID→VALIDATE.
    op.execute(
        f"""
        ALTER TABLE {_TABLE}
        ADD CONSTRAINT fk_weather_value_source_record
        FOREIGN KEY (source_record_key)
        REFERENCES provider_sync.source_records(source_record_key)
        ON DELETE SET NULL
        NOT VALID
        """
    )
    op.execute(
        f"ALTER TABLE {_TABLE} VALIDATE CONSTRAINT fk_weather_value_source_record"
    )


def downgrade() -> None:
    op.execute(
        f"ALTER TABLE {_TABLE} "
        "DROP CONSTRAINT IF EXISTS fk_weather_value_source_record"
    )
    op.execute(
        f"ALTER TABLE {_TABLE} "
        "DROP CONSTRAINT IF EXISTS ck_weather_value_payload_object"
    )
    op.execute(
        f"ALTER TABLE {_TABLE} DROP CONSTRAINT IF EXISTS ck_weather_value_range"
    )
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS feature.{_UNIQUE_INDEX}")
