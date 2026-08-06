# ADR-087: notice 계보 key를 물화하고 인덱스로 찾는다

- 상태: accepted
- 날짜: 2026-08-07
- 결정자: human, AI agent

## 컨텍스트

공개 notice read마다 `_latest_notice_only_sql`이 붙는다. 하는 일은 "같은 계보에서
밀려난 notice를 숨긴다"이고, 승자는 계보당 하나다.

느렸다 — 3,045 notice 규모에서 목록 21.2초, 같은 판정을 쓰는
reconcile(`_supersede_stale_notice_sql`)은 124.8초.

**원인 진단을 한 번 틀렸다.** 처음에는 "판정이 feature 행마다 correlated로
반복되니 제곱"이라고 보고 비상관 `ROW_NUMBER()` + `ARRAY(SELECT ...)` InitPlan으로
바꿨다. 목록은 60배 빨라졌지만 적대 리뷰 2인이 독립적으로 무너뜨렸다:

- `<> ALL(ARRAY(...))`는 **Param 배열이라 해시되지 않고** 행마다 선형 스캔이다.
  복잡도는 그대로 O(notice × 패자)였고 상수만 줄었다(실측: 10k에서 2.2초,
  30k에서 18.0초로 복귀).
- InitPlan은 바깥 질의가 1행을 찾든 전수를 훑든 **notice 전체를 랭킹한다**.
  단건 조회가 3,045 규모에서 1.76ms → 63.3ms로 **회귀**했다. 상세 페이지와
  service batch가 프로덕션의 흔한 경로다.

진짜 원인은 상관성이 아니라 **계보를 찾는 방법**이었다. 계보 key를
`source_records.raw_data` JSON에서 매 행 재계산했고, 런타임 표현식이라 인덱스가
붙을 수 없어(`concat_ws`가 STABLE이라 표현식 인덱스도 불가) 경쟁자 탐색이 매번
notice 전수 스캔이 됐다. correlated 형태 자체는 옳다 — 자기 계보만 보면 되고 그
계보는 보통 한 자릿수 행이다.

## 결정

### 1. 계보 key를 `provider_sync.source_records`에 물화한다

**계보는 record의 속성이다.** 두 성질이 여기서만 동시에 성립한다.

1. **불변** — `raw_data`는 record별로 불변이라(`ON CONFLICT`는 `last_seen_at`만
   갱신하고, payload가 바뀌면 새 record key가 된다) 저장값이 낡지 않는다. 반면
   `source_entities.current_source_record_key`는 폴링마다 재랭크되는 **가변
   포인터**라, entity나 feature에 두면 그 포인터가 움직일 때 값이 낡는다.
2. **축 일치** — 계보 축은 feature당이 아니라 (feature, primary link)당이다.
   feature 단위 컬럼은 그 계보들을 뭉갠다.

read SQL에 `sr` alias가 이미 있어 **새 조인이 없다**.

### 2. 물화 범위는 notice scope뿐이다

계보 규칙이 있는 scope는 krex 교통공지와 kma 특보 둘뿐이고, 그 밖의 record는
`source_entity_id`가 그대로 계보다. 그래서 컬럼에는 **규칙이 적용된 값만** 넣고
(그 밖은 NULL), 읽는 쪽은 `COALESCE(lineage_key, source_entity_id)`로 유효 계보를
만든다. 인덱스는 **그 식 그대로** 건다.

처음에는 전 행을 채우고 NOT NULL로 못박았다. 근거는 "`COALESCE`로 물러나게 두면
인덱스가 안 쓰인다"였는데 **틀렸다**: 인덱스를 같은 `COALESCE` 식에 걸면 된다. 두
인자가 모두 저장 컬럼이라 그 식은 IMMUTABLE이다. 인덱스를 막는 것은 `concat_ws`
(STABLE)가 든 **재계산 CASE** 쪽이고, 그 둘을 한동안 혼동했다. 적대 리뷰가 실측으로
잡았다.

차이는 크다. prod 732,678행 중 규칙 적용 대상은 **744행(0.10%)**이다.

| | 전 행 backfill | notice scope만 |
| --- | --- | --- |
| 마이그레이션 전체 | 124초 | **3.1초** |
| heap | 822MB → **1,700MB 영구** | 822 → 823MB |
| 기존 인덱스 | 432MB → **861MB** | 변화 없음 |
| ACCESS EXCLUSIVE | ~124초(모든 `source_records` 접근 차단) | 3.1초 |

부풀어난 heap은 `VACUUM`으로도 OS에 반환되지 않는다(FSM으로만 회수) — `pg_repack`
창을 따로 잡아야 한다. 0.10%짜리 이득에 낼 비용이 아니다.

### 3. 파생은 DB가 강제한다 — 트리거

제약으로는 값이 **틀린** 경우를 못 막는다. 잘못된 계보 key는 밀려난 공지를
공개 표면에 되살린다. 애플리케이션이 식을 들고 있는 한 그 위험은 사본 수만큼
남는다(종전에 read·writer·migration 세 벌이었다).

그래서 파생을 DB로 옮겼다: `provider_sync.notice_lineage_key` 함수를
BEFORE INSERT/UPDATE 트리거가 호출한다. `concat_ws`가 STABLE이라 generated
column은 못 쓰지만 트리거 본문에는 그 제약이 없다. 결과:

- 식의 정본이 **한 곳(DB)**뿐이다. 애플리케이션은 읽기만 한다.
- 어떤 writer든 — 애플리케이션 SQL, 테스트 픽스처, 수동 SQL — 값이 자동으로 맞고,
  컬럼을 빠뜨려 NOT NULL에 걸리지도 않는다. `UPDATE OF` 목록에 `lineage_key`
  **자신**이 들어 있어 파생 컬럼만 직접 쓰는 문장도 되돌려진다 — 이게 빠지면
  트리거가 NOT NULL 이상의 일을 하지 못한다(적대 리뷰가 실증했다).
- `ENABLE ALWAYS`라 `session_replication_role = replica`에서도 돈다(백업 복원
  드릴이 fence 우회에 그 role을 쓴다). **단 `pg_restore --disable-triggers`가
  내보내는 `DISABLE TRIGGER ALL` → `ENABLE TRIGGER ALL` 쌍을 지나면 `ENABLE
  ORIGIN`으로 조용히 강등된다** — 복원 절차가 되돌려야 한다
  (`docs/backup-restore.md` §함정). 값이 의심되면
  `provider_sync.notice_lineage_key`로 **재계산·복구할 수 있다** — 같은 문장이
  정합성 점검도 겸한다. `docs/backup-restore.md` §함정에 적어 뒀다.
- writer SQL에서 계보 식이 사라져, 같은 bind 파라미터를 두 타입으로 쓰다 나는
  `AmbiguousParameterError` 부류가 **생길 수 없다**(실제로 그렇게 나갔다가 적대
  리뷰가 잡은 적이 있다 — 그 오류는 모든 provider의 모든 record 쓰기를 죽인다).

비용 실측: 순수 INSERT 100,000행에서 트리거 5,840ms vs 비활성 5,996ms(차이 없음).
**다만 `INSERT ... ON CONFLICT DO UPDATE`는 충돌로 UPDATE가 되더라도 후보 행마다
BEFORE INSERT arm이 돈다** — 전부 충돌하는 100,000행 upsert에서 `calls=100000`,
281ms(행당 2.8µs, 문장 시간의 약 4%). `UPDATE OF`는 BEFORE UPDATE arm만 제한하므로
이 경로를 줄이지 못한다. 순수 `UPDATE ... SET last_seen_at`은 트리거를 타지 않는다.
(직전 판에는 "hot path는 트리거를 타지 않는다"고 적었는데 **틀렸다** — 적대 리뷰가
`calls=100000`으로 실증했다.)

### 4. 인덱스 열 순서는 계보 식이 앞이다

탐색은 4열 전부가 등식이라 btree 열 순서는 자유롭다. scope 3열을 앞세우면
`idx_source_records_provider_dataset_entity`·`uq_source_records`와 **선행 3열이
겹쳐** planner가 갈린다 — 무관한 dedup 질의가 이 인덱스로 새는 것을
`test_t212d_perf_explain`이 잡았다. 그래서 선택도가 가장 높은 계보 식을 앞에 둔다.

표현식 인덱스는 `ANALYZE` 전까지 자기 통계가 없다. 계획 **모양**은 그대로지만
비용 추정이 나빠 3,045 규모에서 214.8ms 대 104.2ms(2.1배)였다. 그래서
마이그레이션이 `ANALYZE provider_sync.source_records`로 끝난다. (직전 판에는
"인덱스를 무시하고 종전 형태로 돈다"고 적었는데 **재현되지 않았다** — 적대 리뷰가
통계 없는 DB 두 개를 만들어 확인했다. autovacuum의 평범한 `ANALYZE`도 표현식
통계를 만들므로 배포 후 열화 위험은 없다.)

### 5. read 필터는 correlated를 유지한다

바뀐 것은 계보 key를 재계산 대신 컬럼에서 읽는다는 점뿐이다. 순서 규칙
(`seen_at` → `source_record_key` → 현재 identity → `feature_id`)도, 경쟁자 후보를
`deleted_at IS NULL`로만 거르는 것도 종전과 같다. 그래서 결과 집합이 바뀔 수 있는
표면이 없다.

reconcile도 같은 인덱스를 쓴다. 거기엔 원인이 하나 더 있었다 —
`out_of_scope_feature_lineages` CTE가 갱신 대상 feature마다 재실행됐다
(loops=2,900). 계보 승패는 질의당 한 번이면 되는 집합 연산이라 `MATERIALIZED`
장벽을 세웠다.

H35 고정 세대(0063~0079) replay는 그 세대에 컬럼도 함수도 없으므로 **0079 당시
SQL을 바이트 그대로** 유지한다(`_frozen_h35_latest_notice_only_sql`). 생성해
`origin/main`과 byte-identical임을 확인했다.

## 근거 (실측 — jit=off, 교차 반복 최소값)

| 형태 | 3,045 notice | 145행(현행 prod) |
| --- | --- | --- |
| notice 목록 | 20.4초 → **0.19초** | 60.8ms → **5.2ms** |
| 전체 feature | 20.1초 → **0.67초** | 614ms → **520ms** |
| 단건 조회(노출) | 15.6ms → **3.7ms** | 6.4ms → **3.4ms** |
| reconcile | 118.4초 → **0.36초** | 26.2ms → **23.5ms** |

**현행 prod 규모에서 이득은 작다** — 145행은 어느 형태로도 빠르다. 이 변경이
실제로 사는 곳은 규모가 커질 때다. 적대 리뷰가 만든 20,059 계보 / 26,811 notice
feature(KMA 특보 Phase 2의 현실적 형태)에서 **종전은 13분 42초에도 끝나지 않아
중단**됐고 현재는 508ms다. payload 이력을 계보당 10벌로 늘려 96만 record를 만들어도
508 → 559ms로 선형을 유지한다.

**모든 형태가 개선되고 회귀가 없다**는 것이 폐기한 InitPlan 안과의 차이다.
결과 집합은 두 규모 모두 양방향 차집합 0이고, reconcile 종료 상태
(`features` status/deleted + `feature_notices`)도 `close_missing` 양쪽에서 동일하다.

read 필터 SQL은 15,675자 → 6,695자로 줄었다 — 같은 CASE가 한 질의에 7번 전개되던
것이 컬럼 참조로 바뀌었기 때문이다.

## 폐기한 설계 4건

- **`validity tstzrange` 승격** — GiST가 구조적으로 안 쓰이고(단일행 PK + 부정
  술어), 시작 시각을 보는 술어로 바꾸면 미래 발효 KMA 특보가 발효 전까지 숨어
  사전 경고가 사라진다.
- **승자 물화(`superseded_at`)** — 승자는 `seen_at` 등 가변 입력의 함수라 write
  경로 밖 변경에 낡는다. `test_notice_lifecycle` 5건이 잡았다.
- **`feature_notices.lineage_key`** — 축 불일치(위 결정 1). 조인이 늘어 21배
  규모에서 오히려 2배 느렸다.
- **비상관 InitPlan(`<> ALL(ARRAY(...))`)** — 위 컨텍스트. 목록만 빠르고 단건은
  최대 36배 느려진다. 복잡도도 그대로다.

## 결과

- alembic `0088`: `lineage_key` 컬럼(nullable) + notice scope 한정 backfill(744행) +
  파생 함수·트리거(`ENABLE ALWAYS`) + 표현식 인덱스 + `ANALYZE`.
- 배포 비용(prod 732,678행 실측): **전체 3.1초** — backfill 744행 0.42초 + 인덱스
  1.90초(91MB) + `ANALYZE` 0.76초. heap 822 → 823MB. alembic 한 트랜잭션이라
  ACCESS EXCLUSIVE lock이 그 3.1초 동안 `source_records` 접근을 막는다.
- record쪽 scope 3열 등식을 한때 더했다가 **되돌렸다**. 인덱스 선행 컬럼은 계보
  식 하나이므로 그 3열은 probe에 기여하지 않는다(같은 계획·같은 rows=4, 123 대
  128ms). 대신 `source_records.(provider, dataset_key, source_entity_type)`가 자기
  `source_entities` 행과 일치한다는 **제약 없는 가정**을 정확성의 전제로 만들었다.
  세 줄을 지워 그 위험을 없앴다 — 그 결과 이 필터는 `origin/main`의 술어 집합과
  계보 비교만 다르다.
- 알려진 잔여: 인덱스 91MB의 99.9%는 `idx_source_records_provider_dataset_entity`와
  같은 값을 열 순서만 바꿔 담은 중복이다(out-of-scope 행에서 계보 식 =
  `source_entity_id`). 744행을 위한 값이고, 부분 인덱스로 8kB까지 줄이려면 read
  술어를 두 갈래로 쪼개야 해서 지금은 택하지 않았다 — 마이그레이션 docstring에 근거.
- 알려진 잔여: 계보 key에 시간 성분이 없어 계보당 인덱스 항목이 payload 이력만큼
  단조 증가한다(현재 것은 하나뿐인데도). 50,011 record 계보에서 단건 조회가
  3.3 → 12.5ms였다. `last_seen_at`이 NOT NULL이라 정렬 2열을 인덱스에 덧붙이면
  범위 스캔으로 끊을 수 있다 — 순서 규칙을 건드리므로 별도 변경으로 분리한다.
- 응답 계약 무변경.
- 배포: `KOR_TRAVEL_MAP_MIGRATION_EXPECTED_HEAD`를
  **`0088_source_record_lineage_key`**로 선행 갱신(api 먼저, dagster/daemon 재빌드).
