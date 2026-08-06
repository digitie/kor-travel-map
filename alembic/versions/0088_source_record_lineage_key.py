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

NOT NULL + 트리거인 이유 — 파생을 DB가 강제한다
-----------------------------------------------

읽는 쪽이 ``COALESCE(lineage_key, <재계산>)``으로 물러날 수 있게 두면 컬럼에
인덱스를 걸어도 쓰이지 않는다. 그래서 **모든 record**를 채우고 NOT NULL로
못박는다. CASE의 ELSE 분기가 ``source_entity_id``(NOT NULL)이므로 값이 없을 수
있는 행 자체가 없다 — notice scope 밖 record도 자기 entity id를 계보로 갖는다.

그런데 NOT NULL만으로는 값이 **틀린** 경우를 못 막는다. 계보 key가 잘못 저장되면
밀려난 공지가 공개 표면에 되살아나는데, 값은 write-once라 재검증 경로가 없다.
애플리케이션이 식을 들고 있는 한 그 위험은 사본 수만큼 남는다.

그래서 파생을 **DB로 옮겼다**: BEFORE INSERT/UPDATE 트리거가 ``raw_data``에서
값을 계산해 넣는다. ``concat_ws``가 STABLE이라 generated column은 쓸 수 없지만,
트리거 본문에는 그 제약이 없다. 결과적으로

- 식의 정본이 **한 곳(DB 함수)**뿐이다. 애플리케이션은 읽기만 한다.
- 어떤 writer든 — 애플리케이션 SQL, 테스트 픽스처, 수동 SQL — 값이 자동으로
  맞는다. writer가 컬럼을 빠뜨려 NOT NULL에 걸리는 일도 없다.
- writer SQL에서 계보 식이 사라져, 같은 bind 파라미터를 두 타입으로 쓰다 나는
  ``AmbiguousParameterError`` 부류가 아예 생길 수 없다.

비용은 없다: 20,000행 bulk insert 실측 inline 식 1,562ms vs 트리거 1,568ms.
hot path인 ``ON CONFLICT DO UPDATE SET last_seen_at``은 ``UPDATE OF`` 열 목록에
없어 트리거를 타지 않는다.

비용 — 정직하게
---------------

prod 규모(732,678행 / heap 1,696MB / 기존 인덱스 979MB) 실측:

- backfill UPDATE 74초. **전 행을 다시 쓴다** — 그동안 heap이 최대 2배로 부풀고
  같은 양의 WAL이 나가며, 732k dead tuple이 남아 autovacuum이 나중에 회수한다.
- SET NOT NULL 1.6초(전 행 스캔), CREATE INDEX 2.6초(신규 인덱스 91MB).
- 이 전부가 alembic의 **한 트랜잭션** 안이고 ``ALTER TABLE``이 잡는 ACCESS
  EXCLUSIVE lock이 그 시간 내내 유지된다. entrypoint의 ``alembic upgrade head``가
  api 컨테이너 기동을 그만큼 막는다.

더 싼 등가물은 없다. 값이 다른 열에서 파생되므로 ``ADD COLUMN ... DEFAULT``의
metadata-only 경로를 탈 수 없고(상수가 아니다), generated column도 불가하다
(``concat_ws``가 STABLE). 배치 backfill은 트랜잭션을 쪼개야 하는데 그러면 중간
상태에서 NOT NULL을 걸 수 없다.

재검증·복구 경로
----------------

값이 낡거나 틀어졌다면(예: ``session_replication_role = replica``로 트리거를
우회해 UPDATE한 경우) 아래 한 문장이 점검과 복구를 겸한다 — 0행이면 전부 맞다.

    UPDATE provider_sync.source_records AS sr
       SET lineage_key = provider_sync.source_record_lineage_key(sr)
     WHERE lineage_key IS DISTINCT FROM provider_sync.source_record_lineage_key(sr);
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0088_source_record_lineage_key"
down_revision: str | Sequence[str] | None = "0087_route_area_subtypes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: 계보 key 파생의 **정본**. 애플리케이션은 이 식을 갖지 않고 컬럼을 읽기만 한다
#: (H35 고정 세대 replay만 예외 — 그 세대엔 컬럼이 없어 재계산한다).
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
    # STABLE로 선언한다 — ``concat_ws``가 STABLE이라 IMMUTABLE은 거짓말이 된다.
    # (그래서 표현식 인덱스는 불가능하고, 값을 컬럼에 물화하는 이 설계가 필요하다.)
    op.execute(
        f"""
        CREATE FUNCTION provider_sync.source_record_lineage_key(
            sr provider_sync.source_records
        ) RETURNS text
        LANGUAGE sql STABLE
        AS $fn$ SELECT ({_LINEAGE_EXPR}) $fn$
        """
    )
    op.execute(
        """
        UPDATE provider_sync.source_records AS sr
        SET lineage_key = provider_sync.source_record_lineage_key(sr)
        """
    )
    op.execute(
        """
        ALTER TABLE provider_sync.source_records
          ALTER COLUMN lineage_key SET NOT NULL
        """
    )
    op.execute(
        """
        CREATE FUNCTION provider_sync.set_source_record_lineage_key()
        RETURNS trigger LANGUAGE plpgsql AS $tg$
        BEGIN
            NEW.lineage_key := provider_sync.source_record_lineage_key(NEW);
            RETURN NEW;
        END
        $tg$
        """
    )
    # ``UPDATE OF`` 목록 = 계보 입력 5열 + **``lineage_key`` 자신**.
    #
    # 자신을 빼면 파생 컬럼만 직접 쓰는 문장이 트리거를 타지 않아 거짓 값이 그대로
    # 남는다 — 밀려난 공지가 공개 표면에 되살아난다. NOT NULL은 "비어 있지 않다"만
    # 보장하지 "맞다"를 보장하지 않으므로, 이 항목이 없으면 트리거가 NOT NULL 이상의
    # 일을 하지 못한다. 적대 리뷰가 실증했다.
    #
    # hot path인 ``ON CONFLICT DO UPDATE SET last_seen_at``은 이 목록에 없는 열만
    # 건드리므로 여전히 트리거를 타지 않는다.
    op.execute(
        """
        CREATE TRIGGER trg_source_record_lineage_key
          BEFORE INSERT OR UPDATE OF
            raw_data, provider, dataset_key, source_entity_type, source_entity_id,
            lineage_key
          ON provider_sync.source_records
          FOR EACH ROW
          EXECUTE FUNCTION provider_sync.set_source_record_lineage_key()
        """
    )
    # 계보 탐색은 4열 전부가 등식이라 btree 열 순서는 자유롭다. 그래서 선택도가
    # 가장 높은 ``lineage_key``를 앞에 둔다 — scope 3열을 앞세우면
    # ``idx_source_records_provider_dataset_entity``/``uq_source_records``와
    # **선행 3열이 겹쳐** planner가 둘 사이에서 갈리고, 실제로 무관한 dedup 질의가
    # 이 인덱스로 새는 것을 ``test_t212d_perf_explain``이 잡았다.
    op.execute(
        """
        CREATE INDEX idx_source_records_lineage
          ON provider_sync.source_records (
            lineage_key, provider, dataset_key, source_entity_type
          )
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_source_record_lineage_key"
        " ON provider_sync.source_records"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS provider_sync.set_source_record_lineage_key()"
    )
    op.execute("DROP INDEX IF EXISTS provider_sync.idx_source_records_lineage")
    op.execute(
        "ALTER TABLE provider_sync.source_records DROP COLUMN IF EXISTS lineage_key"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS provider_sync.source_record_lineage_key"
        "(provider_sync.source_records)"
    )
