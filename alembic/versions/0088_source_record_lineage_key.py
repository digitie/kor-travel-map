"""notice 계보 key를 source record에 저장하고 인덱스를 만든다 (T-VN-37, ADR-087).

무엇이 문제였나
---------------

공개 notice read마다 붙는 "같은 계보에서 밀려난 notice 숨김" 판정이 계보 key를
``source_records.raw_data`` JSON에서 **매 행 재계산**했다. 런타임 표현식이라
인덱스가 붙을 수 없고(``concat_ws``가 STABLE이라 표현식 인덱스도 불가), 그 결과
경쟁자 탐색이 매번 notice 전수 스캔이 됐다 — 3,045 notice 규모에서 목록 21.2초,
같은 판정을 쓰는 reconcile(``_supersede_stale_notice_sql``)은 128초.

왜 ``source_records``인가
-------------------------

계보는 **record의 속성**이다. 두 가지가 여기서만 성립한다:

1. **불변성** — ``raw_data``는 record별로 불변이다(ADR-063 이후 payload 이력은
   새 record로 접힌다). 저장한 값이 낡을 수 없다. 반면
   ``source_entities.current_source_record_key``는 폴링마다 재랭크되는 가변
   포인터라, entity나 feature에 두면 그 포인터가 움직일 때 값이 낡는다.
2. **축 일치** — read의 계보 축은 feature당이 아니라 **(feature, primary link)당**
   이다. 한 feature는 primary link를 여럿 가질 수 있고 각각 다른 계보에 속한다
   (``models.py`` 명시, ``idx_source_links_primary``는 non-unique). feature 단위
   컬럼에 두면 그 계보들이 뭉개져 **활성 공지가 사라지거나 밀려난 공지가
   되살아난다** — 실제로 그렇게 만들었다가 적대 리뷰와
   ``test_features_in_bbox_hides_stale_notice_revisions``가 잡았다.

read SQL에는 ``sr``(source_records) alias가 **이미 스코프에 있으므로** 새 조인이
필요 없다.

NOT NULL인 이유 — 저장값은 계약이다
-----------------------------------

읽는 쪽이 ``COALESCE(lineage_key, <재계산>)``으로 물러날 수 있게 두면 컬럼에
인덱스를 걸어도 쓰이지 않는다. 그래서 이 revision은 **모든 record**를 채우고
NOT NULL로 못박는다. CASE의 ELSE 분기가 ``source_entity_id``(NOT NULL)이므로 값이
없을 수 있는 행 자체가 없다 — notice scope 밖 record도 자기 entity id를 계보로
갖는다. 그 덕에 read는 분기 없이 컬럼 등식 하나만 쓰고, 인덱스가 그것을 받는다.

값이 **틀린** 경우는 fallback으로 막을 수 없다는 점도 같이 봤다(``COALESCE``는
NULL만 막는다). 그래서 갈릴 수 있는 사본을 줄이는 쪽을 택했다: 애플리케이션은
``feature_repo._notice_lineage_expr`` 한 함수에서 read·writer SQL을 **모두**
만들고, 마이그레이션만 동결 artifact로서 아래 사본을 갖는다. 두 벌이 같은지는
``tests/integration/test_notice_lineage_key.py``가 고정한다.

비용
----

prod 규모(732,678행) 실측: backfill UPDATE 74초, SET NOT NULL 1.6초, CREATE INDEX
2.6초. entrypoint의 ``alembic upgrade head`` 안에서 한 번 지불한다.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0088_source_record_lineage_key"
down_revision: str | Sequence[str] | None = "0087_route_area_subtypes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: ``feature_repo._notice_lineage_expr(alias='sr')``과 **같은 식**이어야 한다.
#: 마이그레이션은 동결 artifact라 import하지 않고 사본을 둔다 — 계약 테스트가
#: 두 벌의 일치를 고정한다.
_LINEAGE_EXPR = """
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
    """


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE provider_sync.source_records
          ADD COLUMN lineage_key varchar
        """
    )
    op.execute(
        f"""
        UPDATE provider_sync.source_records AS sr
        SET lineage_key = ({_LINEAGE_EXPR})
        """
    )
    op.execute(
        """
        ALTER TABLE provider_sync.source_records
          ALTER COLUMN lineage_key SET NOT NULL
        """
    )
    # 계보 탐색은 (scope 3열 + 계보 key) 등식이다. 정렬·범위가 아니라 등식이므로
    # 이 순서면 index-only probe가 된다.
    op.execute(
        """
        CREATE INDEX idx_source_records_lineage
          ON provider_sync.source_records (
            provider, dataset_key, source_entity_type, lineage_key
          )
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS provider_sync.idx_source_records_lineage")
    op.execute(
        "ALTER TABLE provider_sync.source_records DROP COLUMN IF EXISTS lineage_key"
    )
