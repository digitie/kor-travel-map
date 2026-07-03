"""notice 중복 일회성 정리 (#632).

notice feature identity가 발표/스냅샷 단위에서 **사건 단위**로 바뀌었다:

- KMA 특보: ``{alert_id(tm_fc/seq)}::{region}`` → ``{region}::{현상 토큰}`` +
  해제는 feature 생성 대신 열린 feature의 ``valid_end_time``을 채운다.
- KREX 교통 돌발: feature_id에서 reverse-geocoded ``bjd_code`` 제거(이동하는
  정체가 동 경계를 넘을 때 재키잉되던 버그).

구세대 identity로 적재된 active notice는 새 스킴이 다시 upsert할 수 없어
영구 잔존한다 — 본 마이그레이션이 일회성으로 정리한다(ADR-017 soft-delete):

1. KMA ``kma_weather_alerts`` active notice **전부** soft-delete — 발표 단위
   identity(43건, 발표·해제 공존)는 재현 불가, 다음 특보 적재가 사건 단위로
   재생성한다.
2. KREX ``krex_traffic_notices`` active notice 중 **계보별 latest가 아닌 것**
   soft-delete — 계보 판정은 read 필터(``_notice_lineage_sql``)와 동일하게
   ``source_records.raw_data``의 사건 단서로 재구성(구세대 raw-hash 키도 원문
   단서로 같은 계보에 합류). latest 1건은 남겨 연속성을 유지하고, 이후 적재의
   write-시점 reconcile이 신세대 feature 등장 시 이어서 정리한다.

soft-delete만 수행(원문 source_records 이력은 ADR-017대로 보존).
downgrade는 no-op — 어떤 row가 본 마이그레이션으로 삭제됐는지 구분할 수 없다.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0040_notice_dedup_cleanup"
down_revision: str | Sequence[str] | None = "0039_expand_curated_theme_sets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. KMA 특보 — 구세대(발표 단위) identity 전부 soft-delete.
    op.execute(
        """
        UPDATE feature.features AS f
        SET status = 'inactive', deleted_at = now(), updated_at = now()
        WHERE f.kind = 'notice'
          AND f.deleted_at IS NULL
          AND COALESCE(f.data_origin, 'provider') <> 'user_request'
          AND EXISTS (
            SELECT 1
            FROM provider_sync.source_links AS sl
            JOIN provider_sync.source_records AS sr
              ON sr.source_record_key = sl.source_record_key
            WHERE sl.feature_id = f.feature_id
              AND sl.is_primary_source
              AND sr.provider = 'python-kma-api'
              AND sr.dataset_key = 'kma_weather_alerts'
              AND sr.source_entity_type = 'weather_alert'
          )
        """
    )

    # 2. KREX 교통 돌발 — 계보별 latest 1건만 남기고 soft-delete.
    #    계보 재구성은 infra.feature_repo._notice_lineage_sql의 KREX 분기와 동일
    #    (마이그레이션은 앱 코드를 import하지 않고 SQL을 고정 복사한다).
    op.execute(
        """
        WITH lineage AS (
            SELECT
                f.feature_id,
                COALESCE(
                    NULLIF(
                        concat_ws(
                            '::',
                            NULLIF(lower(btrim(sr.raw_data->>'occurred_date')), ''),
                            NULLIF(lower(btrim(sr.raw_data->>'occurred_time')), ''),
                            NULLIF(lower(btrim(sr.raw_data->>'route_no')), ''),
                            NULLIF(lower(btrim(sr.raw_data->>'direction')), ''),
                            NULLIF(lower(btrim(sr.raw_data->>'point_name')), ''),
                            NULLIF(
                                lower(btrim(sr.raw_data->>'incident_type_code')), ''
                            )
                        ),
                        ''
                    ),
                    sr.source_entity_id
                ) AS lineage_key,
                max(
                    COALESCE(sr.last_seen_at, sr.imported_at, sr.fetched_at)
                ) AS seen_at,
                max(sr.source_record_key) AS tiebreak
            FROM feature.features AS f
            JOIN provider_sync.source_links AS sl
              ON sl.feature_id = f.feature_id
             AND sl.is_primary_source
            JOIN provider_sync.source_records AS sr
              ON sr.source_record_key = sl.source_record_key
            WHERE f.kind = 'notice'
              AND f.deleted_at IS NULL
              AND COALESCE(f.data_origin, 'provider') <> 'user_request'
              AND sr.provider = 'python-krex-api'
              AND sr.dataset_key = 'krex_traffic_notices'
              AND sr.source_entity_type = 'traffic_notice'
            GROUP BY f.feature_id, 2
        ),
        ranked AS (
            SELECT
                feature_id,
                row_number() OVER (
                    PARTITION BY lineage_key
                    ORDER BY seen_at DESC, tiebreak DESC
                ) AS rn
            FROM lineage
        )
        UPDATE feature.features AS f
        SET status = 'inactive', deleted_at = now(), updated_at = now()
        FROM ranked AS r
        WHERE f.feature_id = r.feature_id
          AND r.rn > 1
          AND f.deleted_at IS NULL
        """
    )


def downgrade() -> None:
    # soft-delete 일회성 정리는 되돌릴 수 없다(어떤 row가 본 마이그레이션
    # 대상이었는지 구분 불가). 원문 source_records는 보존돼 재적재로 복원 가능.
    pass
