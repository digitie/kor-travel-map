"""notice 계보 key를 source record에 저장한다 (T-VN-37, ADR-087).

무엇이 문제였나
---------------

공개 notice read마다 붙는 ``_latest_notice_only_sql`` 안에서 계보 key를
``source_records.raw_data`` JSON에서 **매 행 재계산**한다(``_notice_lineage_sql``
의 CASE). 런타임 표현식이라 인덱스가 붙지 않고, 같은 CASE가 한 질의에 7번
전개된다.

왜 ``source_records``인가
-------------------------

계보는 **record의 속성**이다. 두 가지가 여기서만 성립한다:

1. **불변성** — ``raw_data``는 record별로 불변이다(ADR-063 이후 payload 이력은
   새 record로 접힌다). 저장한 값이 낡을 수 없다.
2. **축 일치** — read의 계보 축은 feature당이 아니라 **(feature, primary link)당**
   이다. 한 feature는 primary link를 여럿 가질 수 있고 각각 다른 계보에 속한다
   (``models.py`` 명시, ``idx_source_links_primary``는 non-unique). feature 단위
   컬럼에 두면 그 계보들이 뭉개져 **활성 공지가 사라지거나 밀려난 공지가
   되살아난다** — 실제로 그렇게 만들었다가 적대 리뷰와
   ``test_features_in_bbox_hides_stale_notice_revisions``가 잡았다.

read SQL에는 ``sr``(source_records) alias가 **이미 스코프에 있으므로** 새 조인이
필요 없다. 조인을 더하면 subtype 행 결측 같은 이상 상태에서 결과가 조용히
바뀌는데, 그 위험도 함께 피한다.

fallback
--------

저장값은 **최적화이지 계약이 아니다**. NULL이면 read가 재계산으로 물러난다
(``COALESCE``). 정확성이 "write 경로가 돌았는지"에 의존해서는 안 된다.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0088_source_record_lineage_key"
down_revision: str | Sequence[str] | None = "0087_route_area_subtypes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE provider_sync.source_records
          ADD COLUMN lineage_key varchar
        """
    )
    # notice 계보를 쓰는 scope만 backfill한다 — 전체 record(73만)를 훑을 이유가 없다.
    op.execute(
        """
        UPDATE provider_sync.source_records AS sr
        SET lineage_key = (
    CASE
      WHEN sr.provider = 'python-krex-api'
       AND sr.dataset_key = 'krex_traffic_notices'
       AND sr.source_entity_type = 'traffic_notice'
      THEN COALESCE(
        NULLIF(
          concat_ws(
            '::',
            NULLIF(lower(btrim(sr.raw_data->>'occurred_date')), ''),
            NULLIF(lower(btrim(sr.raw_data->>'occurred_time')), ''),
            NULLIF(lower(btrim(sr.raw_data->>'route_no')), ''),
            NULLIF(lower(btrim(sr.raw_data->>'direction')), ''),
            NULLIF(lower(btrim(sr.raw_data->>'point_name')), ''),
            NULLIF(lower(btrim(sr.raw_data->>'incident_type_code')), '')
          ),
          ''
        ),
        sr.source_entity_id
      )
      WHEN sr.provider = 'python-kma-api'
       AND sr.dataset_key = 'kma_weather_alerts'
       AND sr.source_entity_type = 'weather_alert'
      THEN COALESCE(
        NULLIF(
          concat_ws(
            '::',
            NULLIF(btrim(sr.raw_data->>'region_code'), ''),
            NULLIF(
              btrim(
                COALESCE(
                  sr.raw_data->>'phenomenon',
                  sr.raw_data->>'alert_type'
                )
              ),
              ''
            )
          ),
          ''
        ),
        sr.source_entity_id
      )
      ELSE sr.source_entity_id
    END
    )
        WHERE (sr.provider, sr.dataset_key, sr.source_entity_type) IN (
            ('python-krex-api', 'krex_traffic_notices', 'traffic_notice'),
            ('python-kma-api', 'kma_weather_alerts', 'weather_alert')
        )
        """
    )
    op.execute(
        """
        CREATE INDEX idx_source_records_lineage
            ON provider_sync.source_records
               (provider, dataset_key, source_entity_type, lineage_key)
            WHERE lineage_key IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS provider_sync.idx_source_records_lineage")
    op.execute(
        "ALTER TABLE provider_sync.source_records DROP COLUMN IF EXISTS lineage_key"
    )
