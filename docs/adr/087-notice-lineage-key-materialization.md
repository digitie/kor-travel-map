# ADR-087: notice 계보 key를 source record에 저장한다

- 상태: accepted
- 날짜: 2026-08-06
- 결정자: human, AI agent

## 컨텍스트

공개 notice read마다 붙는 `_latest_notice_only_sql`이 계보 key를
`source_records.raw_data` JSON에서 **매 행 재계산**한다(`_notice_lineage_sql`의
CASE). 같은 CASE가 한 질의에 7번 전개되고, 런타임 표현식이라 인덱스가 붙지 않는다.

## 결정

계보 key를 **`provider_sync.source_records.lineage_key`**에 저장하고, read는
`COALESCE(sr.lineage_key, <CASE>)`로 읽는다.

### 왜 source record인가 — 다른 자리는 전부 틀렸다

**계보는 record의 속성이다.** 두 성질이 여기서만 동시에 성립한다.

1. **불변** — `raw_data`는 record별로 불변이므로 저장값이 낡지 않는다. 반면
   `source_entities.current_source_record_key`는 폴링마다 재랭크되는 **가변
   포인터**라, entity나 feature에 두면 그 포인터가 움직일 때 값이 낡는다.
2. **축 일치** — read의 계보 축은 feature당이 아니라 **(feature, primary link)당**
   이다. 한 feature는 primary link를 여럿 가질 수 있고 각각 다른 계보에 속한다
   (`idx_source_links_primary`는 non-unique). feature 단위 컬럼은 그 계보들을
   뭉개 **활성 공지를 숨기거나 밀려난 공지를 되살린다**.

또 read SQL에 `sr` alias가 **이미 스코프에 있어 새 조인이 없다**. 조인을 더하면
subtype 결측 같은 이상 상태에서 결과가 조용히 바뀌고, 무엇보다 이미 quadratic한
correlated `NOT EXISTS`의 안쪽에 relation을 더하는 비용이 아끼는 것보다 크다.

### 폐기한 설계 3건 (실측 근거)

- **`validity tstzrange` 승격** — GiST가 구조적으로 안 쓰이고(단일행 PK + 부정
  술어), 시작 시각을 보는 술어로 바꾸면 **미래 발효 KMA 특보가 발효 전까지 숨어**
  사전 경고가 사라진다.
- **승자 물화(`superseded_at`)** — 승자는 `seen_at` 등 가변 입력의 함수라 write
  경로 밖 변경에 낡는다. `test_notice_lifecycle` 5건이 잡았다.
- **`feature_notices.lineage_key`** — 위 축 불일치. 적대 리뷰와
  `test_features_in_bbox_hides_stale_notice_revisions`가 잡았고, 21배 규모 실측에서
  조인 추가 탓에 **오히려 2배 느렸다**.

### 인덱스는 만들지 않는다

`COALESCE(col, expr)`는 인덱스가 받을 수 없는 식이다(실측: 200k행 probe에서
`col = x`는 Bitmap Index Scan 0.15ms, `COALESCE(col, y) = x`는 Seq Scan 9.97ms).
인덱스를 만들어 21배 규모로 돌려도 `idx_scan = 0`이었다. 쓰이지 않을 인덱스는
쓰기 비용만 남기므로 만들지 않는다(ADR-086 선례).

### 저장값은 최적화이지 계약이 아니다

NULL이면 read가 재계산으로 물러난다. 정확성이 "write 경로가 돌았는지"에
의존해서는 안 된다. `COALESCE`는 좌항이 NULL일 때만 우항을 평가한다.

## 근거

이 변경의 이득은 **인덱스가 아니라 per-row JSON 추출 제거**다. 실측(3,045 notice):
**21.7초 → 17.2초, 약 21%**. 현행 prod 규모(145행)에서는 차이가 측정되지 않는다
(207.7ms vs 209.2ms) — 병목은 anti-join의 quadratic 형태 자체이고, 이 revision은
그 형태를 바꾸지 않는다.

물화의 판정 기준은 "값이 불변인가"이지 "값이 비싼가"가 아니다. 비싸다고 물화하면
무효화 책임이 따라오고, 그 책임은 코드 규율로만 지킬 수 있다.

## 결과

- alembic `0088`: `source_records.lineage_key` + notice scope 한정 backfill.
  인덱스 없음.
- writer는 record INSERT에서 함께 계산한다(불변이라 ON CONFLICT 갱신 불필요,
  별도 UPDATE 왕복 없음).
- **H35 고정 세대(0063~0079) replay는 재계산을 쓴다** — 그 세대엔 `lineage_key`
  컬럼이 없다. `_latest_notice_only_sql(..., frozen_h35_schema=True)`가 분기한다.
- 응답 계약 무변경.
- 배포: `KOR_TRAVEL_MAP_MIGRATION_EXPECTED_HEAD`를
  **`0088_source_record_lineage_key`**로 선행 갱신(api 먼저, dagster/daemon 재빌드).
