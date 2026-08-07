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

물화 범위 — notice scope만, 그리고 왜 NOT NULL이 아닌가
--------------------------------------------------------

계보 규칙이 있는 scope는 krex 교통공지와 kma 특보 둘뿐이고, 그 밖의 record는
``source_entity_id``가 그대로 계보다. 그래서 컬럼에는 **규칙이 적용된 값만**
저장하고(그 밖은 NULL), 읽는 쪽은
``COALESCE(lineage_key, source_entity_id)``로 유효 계보를 만든다.

처음에는 전 행을 채우고 NOT NULL로 못박았다. 근거는 "``COALESCE``로 물러나게
두면 인덱스가 안 쓰인다"였는데 **틀렸다**: 인덱스를 **같은 ``COALESCE`` 식**에
걸면 된다. 두 인자가 모두 저장 컬럼이라 그 식은 IMMUTABLE이다. 인덱스를 막는
것은 ``concat_ws``(STABLE)가 든 재계산 CASE 쪽이고, 그 둘을 한동안 혼동했다.
적대 리뷰가 실측으로 잡았다.

차이는 크다. prod 732,678행 중 규칙 적용 대상은 **744행(0.10%)**이다.

| | 전 행 backfill | notice scope만 |
| --- | --- | --- |
| backfill | 124초 | 0.42초 |
| heap | 822MB → **1,700MB 영구** | 822 → 823MB |
| 기존 인덱스 | 432MB → **861MB** | 변화 없음 |
| ACCESS EXCLUSIVE | ~124초(모든 source_records 접근 차단) | 인덱스 생성 시간만 |

부풀어난 heap은 `VACUUM`으로도 OS에 반환되지 않는다(FSM으로만 회수).
`pg_repack`/`VACUUM FULL` 창을 따로 잡아야 한다. 그 비용을 0.10%짜리 이득을
위해 낼 이유가 없다.

파생은 DB가 강제한다 — 트리거
------------------------------

값이 **틀린** 경우는 제약으로 못 막는다. 잘못된 계보 key는 밀려난 공지를 공개
표면에 되살린다. 애플리케이션이 식을 들고 있는 한 그 위험은 사본 수만큼 남는다
(종전에 read·writer·migration 세 벌이었다).

그래서 파생을 DB로 옮겼다: ``provider_sync.notice_lineage_key`` 함수를
BEFORE INSERT/UPDATE 트리거가 호출한다. ``concat_ws``가 STABLE이라 generated
column은 못 쓰지만 트리거 본문에는 그 제약이 없다. 결과:

- 식의 정본이 **한 곳(DB)**뿐이다. 애플리케이션은 읽기만 한다.
- 어떤 writer든 — 애플리케이션 SQL, 테스트 픽스처, 수동 SQL — 값이 자동으로
  맞는다. ``UPDATE OF`` 목록에 ``lineage_key`` **자신**이 들어 있어 파생 컬럼만
  직접 쓰는 문장도 되돌려진다.
- ``ENABLE ALWAYS``라 ``session_replication_role = replica``에서도 돈다.
- writer SQL에서 계보 식이 사라져, 같은 bind 파라미터를 두 타입으로 쓰다 나는
  ``AmbiguousParameterError`` 부류가 아예 생길 수 없다.

비용 실측: 순수 INSERT 100,000행에서 트리거 5,840ms vs 비활성 5,996ms(차이
없음). **다만 ``INSERT ... ON CONFLICT DO UPDATE``는 충돌로 UPDATE가 되더라도
후보 행마다 BEFORE INSERT arm이 돈다** — 100,000행 전부 충돌하는 upsert에서
``calls=100000``, 281ms(행당 2.8µs, 문장 시간의 약 4%). ``UPDATE OF``는 BEFORE
UPDATE arm만 제한하므로 이 경로를 줄이지 못한다. 순수 ``UPDATE ... SET
last_seen_at``은 정상적으로 트리거를 타지 않는다.

비용 (prod 732,678행 실측)
--------------------------

전체 **3.1초**다.

- ``ADD COLUMN`` 8ms(metadata-only) · 파생 함수 13ms
- backfill UPDATE **744행 0.42초** — heap 822 → 823MB
- 트리거 함수·트리거·``ENABLE ALWAYS`` 각 10ms 미만
- ``CREATE INDEX`` 1.90초(72MB) · ``ANALYZE`` 0.76초

alembic 한 트랜잭션이라 ACCESS EXCLUSIVE lock이 이 3.1초 동안 ``source_records``
접근을 막는다. entrypoint의 ``alembic upgrade head``가 api 기동을 그만큼 막는다.

인덱스 72MB는 상시 비용이다 — ``source_records`` 인덱스 총량 436 → 508MB.
**``last_seen_at``이 두 번째 열이라 폴링 경로가 특히 더 낸다**(그 컬럼만 갱신하는
UPDATE 10만 행에서 WAL record +24%). 부분 인덱스(``WHERE lineage_key IS NOT
NULL``)로 줄이려면 read 술어를 in-scope/out-of-scope 두 갈래로 쪼개야 한다
(planner가 부분 인덱스 술어를 증명할 수 있어야 한다). 계보 규칙 없는 provider가
notice를 내보내는 순간 조용히 느려지는 구조라, 지금은 단일 술어를 택했다.

재검증·복구 경로
----------------

값이 낡거나 틀어졌다면(예: ``session_replication_role = replica``로 트리거를
우회해 UPDATE한 경우) 아래 한 문장이 점검과 복구를 겸한다 — 0행이면 전부 맞다.

    UPDATE provider_sync.source_records AS sr
       SET lineage_key = provider_sync.notice_lineage_key(sr)
     WHERE lineage_key IS DISTINCT FROM provider_sync.notice_lineage_key(sr);
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
      ELSE NULL
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
        CREATE FUNCTION provider_sync.notice_lineage_key(
            sr provider_sync.source_records
        ) RETURNS text
        LANGUAGE sql STABLE
        AS $fn$ SELECT ({_LINEAGE_EXPR}) $fn$
        """
    )
    # backfill은 **notice 규칙이 있는 scope만** 돈다. 실측 prod 732,678행 중
    # 744행(0.10%)이다. 전 행을 채우면 heap이 822MB → 1,700MB로 영구히 부풀고
    # (VACUUM도 OS에 반환하지 않는다) 2분짜리 ACCESS EXCLUSIVE lock이 걸린다.
    # WHERE 절은 scope 3열을 **직접** 건다. ``notice_lineage_key(sr) IS NOT NULL``로
    # 쓰면 STABLE 함수라 planner가 안을 못 보고 73만 행 Seq Scan이 된다(실측
    # 1,457ms / 105,181 buffers, 추정 728,979행 대 실제 744행). 같은 744행을
    # ``uq_source_records`` + ``idx_source_records_kma_alert_history`` BitmapOr로
    # 집으면 561 buffers다 — I/O 187배 차이.
    op.execute(
        """
        UPDATE provider_sync.source_records AS sr
        SET lineage_key = provider_sync.notice_lineage_key(sr)
        WHERE (sr.provider, sr.dataset_key, sr.source_entity_type) IN (
            ('python-krex-api', 'krex_traffic_notices', 'traffic_notice'),
            ('python-kma-api', 'kma_weather_alerts', 'weather_alert')
        )
        """
    )
    op.execute(
        """
        CREATE FUNCTION provider_sync.set_source_record_lineage_key()
        RETURNS trigger LANGUAGE plpgsql AS $tg$
        BEGIN
            NEW.lineage_key := provider_sync.notice_lineage_key(NEW);
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
    # 순수 ``UPDATE ... SET last_seen_at``은 이 목록 밖이라 트리거를 타지 않는다.
    # 단 ``INSERT ... ON CONFLICT DO UPDATE``는 충돌해도 BEFORE INSERT arm이
    # 후보 행마다 돈다(위 docstring 참조) — ``UPDATE OF``로는 줄일 수 없다.
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
    # ``ENABLE ALWAYS`` — ``session_replication_role = replica``에서도 돈다.
    # 백업 복원 드릴이 fence 우회에 그 role을 쓰는데(``docs/backup-restore.md``),
    # 기본 ``ENABLE ORIGIN``이면 그 세션의 쓰기에서 파생이 통째로 빠진다.
    op.execute(
        """
        ALTER TABLE provider_sync.source_records
          ENABLE ALWAYS TRIGGER trg_source_record_lineage_key
        """
    )
    # 인덱스는 read가 쓰는 식 그대로다. 두 인자가 모두 저장 컬럼이라
    # ``COALESCE``는 IMMUTABLE이고 표현식 인덱스가 성립한다.
    #
    # 뒤의 두 열이 순서 규칙(``last_seen_at`` → ``source_record_key``)이고
    # **DESC**다. read가 "나보다 나은 행이 있나"를 행 비교 하나로 묻기 때문에
    # 계보 등식 + 이 두 열이 통째로 Index Cond가 된다.
    #
    # DESC여야 하는 이유가 핵심이다. 한 계보에서 실제로 조인되는 행은 **현재
    # record 뿐**이고 그것은 그 계보의 ``last_seen_at`` **최댓값**이다. ASC로 두면
    # 패자의 스캔 범위(``> 나``)에서 그 행이 **맨 끝**에 놓여 ``EXISTS``가 이력을
    # 전부 소비한다 — 50,002 record 계보에서 패자 단건 조회 158.7ms(같은 조건
    # DESC 25.0ms, ``origin/main`` 29.1ms). DESC면 첫 항목에서 끊긴다.
    #
    # 패자가 다수라는 점이 중요하다 — 이 필터의 존재 이유가 패자를 거르는 것이다
    # (prod 145건 중 98건). 승자만 재면 ASC도 빨라 보인다(적대 리뷰가 잡았다).
    #
    # scope 3열은 넣지 않는다. read가 scope를 entity쪽에서 거르므로 인덱스가
    # 그것을 묶지 못하고, 넣으면 ``idx_source_records_provider_dataset_entity``와
    # 선행 열이 겹쳐 planner가 갈린다(무관한 dedup 질의가 새는 것을
    # ``test_t212d_perf_explain``이 잡았다).
    op.execute(
        """
        CREATE INDEX idx_source_records_lineage
          ON provider_sync.source_records (
            (COALESCE(lineage_key, source_entity_id)),
            last_seen_at DESC, source_record_key DESC
          )
        """
    )
    # 표현식 인덱스는 ANALYZE 전까지 자기 통계가 없다. 계획 모양은 같지만 비용
    # 추정이 나빠 prod 규모 notice 목록이 221.9ms 대 2.0ms(110배)다. 배포 직후
    # 그 창이 열리지 않도록 여기서 만들어 둔다. 복원·REINDEX 뒤에도 같다 —
    # pg_restore는 planner 통계를 복원하지 않는다(docs/backup-restore.md §함정).
    op.execute("ANALYZE provider_sync.source_records")


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
        "DROP FUNCTION IF EXISTS provider_sync.notice_lineage_key"
        "(provider_sync.source_records)"
    )
