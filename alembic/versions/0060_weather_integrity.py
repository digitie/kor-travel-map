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
1. **WRITER LOCK FIRST** — migration transaction이
   ``SHARE ROW EXCLUSIVE`` table lock을 먼저 얻는다. 이 lock은 SELECT는 허용하지만
   INSERT/UPDATE/DELETE의 ``ROW EXCLUSIVE``와 충돌하므로, dedup부터 UNIQUE commit까지
   semantic duplicate가 다시 들어오는 틈을 DB에서 닫는다. lock 획득은 5초 안에
   끝나지 않으면 migration 전체를 rollback한다. 운영 절차도 API mutation, Dagster
   schedule/sensor/manual/backfill, daemon/code location을 먼저 fence하고 active writer
   0건을 확인해야 하며 DB lock은 마지막 불변식이다.

2. **DEDUP** — UNIQUE 빌드는 기존 중복이 있으면 실패하므로 lock 아래에서 제거한다.
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

3. **TRANSACTIONAL UNIQUE** — dedup과 같은 transaction에서 non-concurrent
   ``CREATE UNIQUE INDEX ... NULLS NOT DISTINCT``를 실행한다. writer는 같은 cutover
   image에서 ON CONFLICT 대상을 이 index tuple로 전환한다
   (``weather_repo._INSERT_SQL`` / ``_WEATHER_CONFLICT_TARGET``). 실패하면 dedup과 index가
   함께 rollback되므로 이 migration은 INVALID index를 만들지 않는다. 과거 0060 시도에서
   남았을 수 있는 같은 이름의 index와 validation 실패 뒤 미stamp된 제약은 lock 아래
   먼저 정리해 재시도 입력을 단일화한다.
   preflight 확인:

       SELECT c.relname, i.indisvalid, i.indisready, i.indisunique
       FROM pg_class c JOIN pg_index i ON i.indexrelid = c.oid
       WHERE c.relname = 'uq_weather_value_identity';

4. **range/payload CHECK + source FK** — 세 제약을 **먼저 전부 ``NOT VALID``로
   추가**한 뒤(메타데이터만; 각 ADD는 짧은 sub-second ACCESS EXCLUSIVE를 잡는다),
   **별도 autocommit_block 안에서** ``VALIDATE CONSTRAINT`` 세 개를 순차 실행한다.
   순서가 중요하다: ``ADD ... NOT VALID``의 ACCESS EXCLUSIVE는 PG가 트랜잭션 끝까지
   보유하므로, ADD와 VALIDATE가 같은 트랜잭션이면 그 lock이 VALIDATE 전체 스캔
   내내 유지돼 ~30M행 테이블을 통째로 막는다. autocommit_block 진입이 ADD들을 먼저
   commit해 ACCESS EXCLUSIVE를 풀고, 각 VALIDATE는 자기 statement에서
   SHARE UPDATE EXCLUSIVE만 잡아(전체 스캔이지만 read/write 비차단, rewrite 없음)
   돈다. 운영자 pre-count로 VALIDATE 실패를 사전 확인할 수 있다:

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

   migration도 writer lock을 얻은 직후 같은 세 위반을 한 번에 검사한다. 하나라도
   있으면 dedup/index/제약을 바꾸기 전에 전체 transaction을 실패시킨다. 각
   ``VALIDATE``는 앞 transaction commit 뒤 별도 statement로 실행되므로 session-level
   ``lock_timeout=5s``를 다시 설정하며, 성공·실패와 무관하게 ``RESET``한다.

이 revision은 컬럼 추가·타입 변경·STORED 추가·테이블 rewrite를 하지 않는다.
weather는 아직 SQLAlchemy ``models.metadata``에 모델링되지 않으므로(T-VN-38 소유)
autogenerate/``alembic check`` 비교 대상이 아니다 — 본 제약은 migration으로만 둔다.

DOWNGRADE는 지원하지 않는다. dedup loser와 새 writer의 semantic ``ON CONFLICT`` 계약을
동시에 되돌릴 수 없으므로 0060 이전 복구는 maintenance fence 아래 검증된 backup/PITR을
복원하고 구 writer image를 함께 되돌리는 절차만 허용한다.

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
_LOCK_TIMEOUT = "5s"


def upgrade() -> None:
    # 1) DB-level writer fence. SELECT는 허용하되 모든 weather DML을 dedup 이전부터
    #    UNIQUE commit까지 차단한다. lock을 빨리 얻지 못하면 전체 transaction rollback.
    op.execute(f"SET LOCAL lock_timeout = '{_LOCK_TIMEOUT}'")
    op.execute(f"LOCK TABLE {_TABLE} IN SHARE ROW EXCLUSIVE MODE")

    # VALIDATE 실패가 dedup/UNIQUE commit 뒤에야 드러나지 않도록 기존 오염을
    # writer lock 아래 한 번에 검사한다. 신규 row는 NOT VALID 제약 추가 시점부터
    # 제약을 적용받으므로 이 precheck와 이어지는 VALIDATE 사이에 오염될 수 없다.
    op.execute(
        f"""
        DO $migration$
        DECLARE
            range_violations bigint;
            payload_violations bigint;
            orphan_source_records bigint;
        BEGIN
            SELECT
                count(*) FILTER (
                    WHERE valid_from IS NOT NULL
                      AND valid_until IS NOT NULL
                      AND valid_from > valid_until
                ),
                count(*) FILTER (WHERE jsonb_typeof(payload) <> 'object'),
                count(*) FILTER (
                    WHERE source_record_key IS NOT NULL
                      AND NOT EXISTS (
                          SELECT 1
                          FROM provider_sync.source_records AS sr
                          WHERE sr.source_record_key = w.source_record_key
                      )
                )
            INTO range_violations, payload_violations, orphan_source_records
            FROM {_TABLE} AS w;

            IF range_violations <> 0
               OR payload_violations <> 0
               OR orphan_source_records <> 0 THEN
                RAISE EXCEPTION
                    'weather integrity preflight failed: range=%, payload=%, orphan=%',
                    range_violations, payload_violations, orphan_source_records
                    USING ERRCODE = '23514';
            END IF;
        END
        $migration$
        """
    )

    # 과거 0060의 validate 실패는 앞선 autocommit 경계에서 NOT VALID/일부 VALID
    # 제약을 commit했을 수 있다. 미stamp 재시도를 위해 exact 세 제약을 정규화한다.
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

    # 과거 concurrent 0060 시도의 leftover valid/INVALID index도 같은 lock 아래 제거한다.
    op.execute(f"DROP INDEX IF EXISTS feature.{_UNIQUE_INDEX}")

    # 2) semantic tuple 중복 제거 (NULLS는 PARTITION BY에서 동일 그룹).
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

    # 3) semantic UNIQUE — writer lock과 dedup의 같은 transaction. 실패하면 모두
    #    rollback되며 INVALID index가 남지 않는다.
    op.execute(
        f"""
        CREATE UNIQUE INDEX {_UNIQUE_INDEX}
        ON {_TABLE} (
            feature_id, provider, weather_domain, forecast_style, metric_key,
            issued_at, valid_at, observed_at
        )
        NULLS NOT DISTINCT
        """
    )

    # 4) range/payload CHECK + source FK를 **먼저 전부 NOT VALID로 추가**한다.
    #    ADD CONSTRAINT ... NOT VALID는 메타데이터 검증(제약 정의 기록)만 하지만
    #    ACCESS EXCLUSIVE lock을 잡고 PG는 이를 트랜잭션 끝까지 보유한다. 따라서
    #    ADD와 VALIDATE를 한 트랜잭션에 두면 ADD의 ACCESS EXCLUSIVE가 이어지는
    #    VALIDATE 스캔 내내 유지돼 ~30M행 테이블의 읽기·쓰기를 전부 막는다(S2).
    #    세 ADD는 각각 짧은(sub-second, 메타데이터 전용) ACCESS EXCLUSIVE만 잡는다.
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
    op.execute(
        f"""
        ALTER TABLE {_TABLE}
        ADD CONSTRAINT ck_weather_value_payload_object
        CHECK (jsonb_typeof(payload) = 'object')
        NOT VALID
        """
    )
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

    # 5) VALIDATE는 autocommit_block에서 실행한다. block 진입이 writer lock,
    #    dedup, UNIQUE와 위 ADD들을 원자 commit하고 ACCESS EXCLUSIVE를 푼다. 각
    #    VALIDATE는 자기 statement에서 SHARE UPDATE EXCLUSIVE만 잡아(전체 스캔이지만
    #    read/write 비차단) 순차 실행된다. SET LOCAL은 앞 commit에서 소멸하므로
    #    session-level timeout을 다시 설정하고 성공/실패 양쪽에서 반드시 RESET한다.
    with op.get_context().autocommit_block():
        op.execute(f"SET lock_timeout = '{_LOCK_TIMEOUT}'")
        try:
            op.execute(
                f"ALTER TABLE {_TABLE} VALIDATE CONSTRAINT ck_weather_value_range"
            )
            op.execute(
                f"ALTER TABLE {_TABLE} "
                "VALIDATE CONSTRAINT ck_weather_value_payload_object"
            )
            op.execute(
                f"ALTER TABLE {_TABLE} "
                "VALIDATE CONSTRAINT fk_weather_value_source_record"
            )
        finally:
            op.execute("RESET lock_timeout")


def downgrade() -> None:
    raise RuntimeError(
        "0060 is forward-only: restore the pre-cutover backup/PITR under a writer "
        "fence and roll back the writer image as one operation"
    )
