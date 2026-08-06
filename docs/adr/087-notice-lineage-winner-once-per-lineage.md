# ADR-087: notice 계보 승자는 계보당 1회로 판정한다

- 상태: accepted
- 날짜: 2026-08-06
- 결정자: human, AI agent

## 컨텍스트

공개 notice read마다 `_latest_notice_only_sql`이 붙는다. 그것이 하는 일은 "같은
계보에서 밀려난 notice를 숨긴다"이고, 승자는 **계보당 하나**다.

그런데 구현은 그 판정을 **feature 행마다** correlated `NOT EXISTS`로 다시 했다 —
`DISTINCT ON`으로 자기 계보를 고르고 `LATERAL`로 "나보다 나은 게 있나"를 훑는
형태다. notice 수에 대해 **제곱으로** 커진다. 게다가 계보 key를
`source_records.raw_data` JSON에서 매 행 재계산했고(같은 CASE가 한 질의에 7번
전개), 런타임 표현식이라 인덱스가 붙지 않았다.

## 결정

### 1. 승자 판정을 계보당 1회로 (핵심)

같은 규칙을 `ROW_NUMBER()`로 한 번에 표현하고, 패자 집합을 **비상관**
`ARRAY(SELECT ...)`로 뽑는다. 비상관이므로 쿼리당 1회 평가되는 InitPlan이 되고,
본 질의는 `feature_id <> ALL(...)`이 된다. 이 저장소가 bbox geometry 후보에서
이미 쓰는 패턴이다.

순서 규칙은 종전과 같다 — `seen_at` → `source_record_key` → 현재 identity →
`feature_id` 안정 tie-break. 경쟁자 후보를 `deleted_at IS NULL`로만 거르는 것도
그대로다.

**불변식 하나가 함정이다**: 한 feature는 primary link를 여럿 가질 수 있어 **여러
계보 파티션에 나타난다**. 종전 `HAVING bool_and(...)`의 뜻이 "한 계보라도 이기면
보존"이므로, 패자는 `GROUP BY feature_id HAVING bool_and(rank > 1)` — **모든
계보에서 밀린** feature뿐이다. 처음에 이걸 빠뜨려 활성 공지가 사라졌고
`test_notice_lifecycle` 3건이 잡았다.

### 2. 계보 key는 `provider_sync.source_records`에 저장한다

**계보는 record의 속성이다.** 두 성질이 여기서만 동시에 성립한다.

1. **불변** — `raw_data`는 record별로 불변이라(`ON CONFLICT`는 `last_seen_at`만
   갱신하고, payload가 바뀌면 새 record key가 된다) 저장값이 낡지 않는다. 반면
   `source_entities.current_source_record_key`는 폴링마다 재랭크되는 **가변
   포인터**라, entity나 feature에 두면 그 포인터가 움직일 때 값이 낡는다.
2. **축 일치** — 계보 축은 feature당이 아니라 (feature, primary link)당이다.
   feature 단위 컬럼은 그 계보들을 뭉갠다.

read SQL에 `sr` alias가 이미 있어 **새 조인이 없다**.

### 3. 인덱스는 만들지 않는다

계보 값으로 **probe하는 질의가 없다**. 계보는 `ROW_NUMBER()`의 PARTITION 축이자
정렬 키이고, `source_records`는 `current_source_record_key`를 통해 PK로 도달한다.
인덱스를 만들어 실측해도 `idx_scan = 0`이었다.

(초기 판단 근거였던 "`COALESCE(col, expr)`라서 인덱스가 못 받는다"는 **틀렸다** —
표현식 인덱스를 막는 것은 `concat_ws`가 STABLE이라는 것이고, 그건 종전 재계산
식에도 똑같이 걸린다. 결론은 같지만 이유가 달랐다.)

### 4. 저장값은 최적화이지 계약이 아니다

NULL이면 read가 재계산으로 물러난다. 정확성이 "write 경로가 돌았는지"에
의존해서는 안 된다. notice scope **밖은 저장하지 않는다** — CASE의 ELSE 분기가
`source_entity_id`라 제한하지 않으면 73만+ record에 읽히지도 않는 사본이 남고,
notice scope만 채우는 backfill과도 어긋난다. scope 집합은
`core.notice_lineage_scopes`가 정본이고 writer가 런타임에 그것을 쓴다.

## 근거 (실측)

| 규모 | 종전 | 현재 |
| --- | --- | --- |
| 3,045 notice | 23.7초 | **0.35초** |
| 145행 (현행 prod) | 448ms | **4.8ms** |

결과 집합은 두 규모 모두 **145 = 145, 양방향 차집합 0**.

계보 key 저장만으로는 3,045 notice에서 27.5→19.9초(약 25%)였고 **현행 규모에서는
차이가 측정되지 않았다**. 병목이 JSON 추출이 아니라 **형태**였기 때문이다.
인덱스를 붙여도 24.6→20.6초에 그쳤다. 형태를 바꾸자 두 자릿수 배가 나온다.

## 폐기한 설계 3건

- **`validity tstzrange` 승격** — GiST가 구조적으로 안 쓰이고(단일행 PK + 부정
  술어), 시작 시각을 보는 술어로 바꾸면 미래 발효 KMA 특보가 발효 전까지 숨어
  사전 경고가 사라진다.
- **승자 물화(`superseded_at`)** — 승자는 `seen_at` 등 가변 입력의 함수라 write
  경로 밖 변경에 낡는다. `test_notice_lifecycle` 5건이 잡았다.
- **`feature_notices.lineage_key`** — 축 불일치(위 결정 2). 조인이 늘어 21배
  규모에서 오히려 2배 느렸다.

## 결과

- alembic `0088`: `source_records.lineage_key` + notice scope 한정 backfill(실측
  208ms). 인덱스 없음.
- writer는 record INSERT에서 함께 계산한다. bind 파라미터가 INSERT 값(varchar)과
  CASE(text) 양쪽에 쓰이므로 **양쪽 모두 명시 `CAST(... AS text)`**가 필요하다 —
  없으면 Parse 단계에서 `AmbiguousParameterError`로 **모든 provider의 모든 record
  쓰기**가 죽는다(실제로 그렇게 나갔다가 적대 리뷰가 잡았다).
- H35 고정 세대(0063~0079) replay는 재계산을 쓴다 — 그 세대엔 컬럼이 없다.
- 계약 테스트(`tests/integration/test_notice_lineage_key.py`)가 writer 실행·scope
  경계·저장값과 재계산값의 일치를 고정한다. 같은 CASE가 read/writer/migration 세
  벌로 흩어져 있으므로, 갈리면 공개 표면과 admin/reconcile이 다른 계보로 묶인다.
- 응답 계약 무변경.
- 배포: `KOR_TRAVEL_MAP_MIGRATION_EXPECTED_HEAD`를
  **`0088_source_record_lineage_key`**로 선행 갱신(api 먼저, dagster/daemon 재빌드).
