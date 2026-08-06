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

### 2. 파생은 DB가 강제한다 — NOT NULL + 트리거

읽는 쪽이 `COALESCE(lineage_key, <재계산>)`으로 물러날 수 있게 두면 인덱스를 걸어도
쓰이지 않는다. 그래서 **모든 record**를 채우고 NOT NULL로 못박는다. CASE의 ELSE
분기가 `source_entity_id`(NOT NULL)이므로 값이 없을 수 있는 행 자체가 없다.

NOT NULL만으로는 값이 **틀린** 경우를 못 막는다. 잘못된 계보 key는 밀려난 공지를
공개 표면에 되살린다. 애플리케이션이 식을 들고 있는 한 그 위험은 사본 수만큼
남는다(종전에 read·writer·migration 세 벌이었다).

그래서 파생을 DB로 옮겼다: `provider_sync.source_record_lineage_key` 함수를
BEFORE INSERT/UPDATE 트리거가 호출한다. `concat_ws`가 STABLE이라 generated
column은 못 쓰지만 트리거 본문에는 그 제약이 없다. 결과:

- 식의 정본이 **한 곳(DB)**뿐이다. 애플리케이션은 읽기만 한다.
- 어떤 writer든 — 애플리케이션 SQL, 테스트 픽스처, 수동 SQL — 값이 자동으로 맞고,
  컬럼을 빠뜨려 NOT NULL에 걸리지도 않는다. `UPDATE OF` 목록에 `lineage_key`
  **자신**이 들어 있어 파생 컬럼만 직접 쓰는 문장도 되돌려진다 — 이게 빠지면
  트리거가 NOT NULL 이상의 일을 하지 못한다(적대 리뷰가 실증했다).
- 값이 낡을 수 있는 유일한 경로는 `session_replication_role = replica`로 트리거를
  끄고 UPDATE하는 것이다(백업 복원 드릴이 fence 우회에 쓴다). 그 경우
  `provider_sync.source_record_lineage_key`로 **재계산·복구할 수 있다** — 같은
  문장이 정합성 점검도 겸한다. `docs/backup-restore.md` §함정에 적어 뒀다.
- writer SQL에서 계보 식이 사라져, 같은 bind 파라미터를 두 타입으로 쓰다 나는
  `AmbiguousParameterError` 부류가 **생길 수 없다**(실제로 그렇게 나갔다가 적대
  리뷰가 잡은 적이 있다 — 그 오류는 모든 provider의 모든 record 쓰기를 죽인다).

비용은 없다: 20,000행 bulk insert 실측 inline 식 1,562ms vs 트리거 1,568ms. hot
path인 `ON CONFLICT DO UPDATE SET last_seen_at`은 `UPDATE OF` 열 목록에 없어
트리거를 타지 않는다.

### 3. 인덱스 열 순서는 `lineage_key`가 앞이다

탐색은 4열 전부가 등식이라 btree 열 순서는 자유롭다. scope 3열을 앞세우면
`idx_source_records_provider_dataset_entity`·`uq_source_records`와 **선행 3열이
겹쳐** planner가 갈린다 — 무관한 dedup 질의가 이 인덱스로 새는 것을
`test_t212d_perf_explain`이 잡았다. 그래서 선택도가 가장 높은 `lineage_key`를
앞에 둔다.

### 4. read 필터는 correlated를 유지한다

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
| notice 목록 | 21.2초 → **0.17초** | 127ms → **7.9ms** |
| 전체 feature | 22.1초 → **0.74초** | 696ms → **540ms** |
| 단건 조회(노출) | 15.6ms → **3.8ms** | 9.0ms → **4.8ms** |
| reconcile | 124.8초 → **0.58초** | 251ms → **24ms** |

**모든 형태가 개선되고 회귀가 없다**는 것이 폐기한 InitPlan 안과의 차이다.
결과 집합은 두 규모 모두 양방향 차집합 0이고, reconcile 종료 상태
(`features` status/deleted + `feature_notices`)도 `close_missing` 양쪽에서 동일하다.

read 필터 SQL은 15,675자 → 6,001자로 줄었다 — 같은 CASE가 한 질의에 7번 전개되던
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

- alembic `0088`: `lineage_key` 컬럼 + 전 행 backfill + NOT NULL + 파생 함수·트리거
  + `idx_source_records_lineage`.
- 배포 비용(prod 732,678행 / heap 1,696MB 실측): backfill 74초 + NOT NULL 1.6초 +
  인덱스 2.6초(신규 91MB). backfill이 **전 행을 다시 쓰므로** 그동안 heap이 최대
  2배로 부풀고 같은 양의 WAL이 나가며 dead tuple 회수는 autovacuum에 남는다.
  전부 alembic 한 트랜잭션 안이고 ACCESS EXCLUSIVE lock이 그 시간 내내 유지된다 —
  entrypoint의 `alembic upgrade head`가 api 기동을 그만큼 막는다. 더 싼 등가물은
  없다(파생값이라 `DEFAULT` metadata-only 경로 불가, generated column도 불가).
- 응답 계약 무변경.
- 배포: `KOR_TRAVEL_MAP_MIGRATION_EXPECTED_HEAD`를
  **`0088_source_record_lineage_key`**로 선행 갱신(api 먼저, dagster/daemon 재빌드).
