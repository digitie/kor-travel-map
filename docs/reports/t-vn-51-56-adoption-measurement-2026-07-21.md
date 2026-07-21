# T-VN-51~56 — Wave 3 도입-조건 측정 결과 (2026-07-21)

## 목적

`performance.md` §8.3은 "MVT, 범용 batch, cursor HMAC, weather partition/hypertable,
물리 listener, 대규모 fixture 주기는 T-VN-51~56에서 먼저 채택 기준을 측정하며,
'확장 가능해 보인다'는 이유만으로 구현하지 않는다"고 못박았다. 본 리포트는 그 여섯
항목의 **채택 기준(budget/threshold)** 과 **현재 근거(측정·구조)** 를 고정하고, 각각을
`구현 task 개방` 또는 `명시적 트리거로 유예` 로 판정한다.

측정 실행 환경: n150(4코어·466G) CI-parity docker(`python:3.13`, testcontainers PostGIS),
정본 근거 문서는 `performance.md` §8(3단 성능·DDL gate)·§9(캐싱/MV) 및
`docs/reports/t-212d-perf-baseline-2026-06-08.md`. 코드 근거는 커밋
`integration/t-vn@5a525f52` 기준이다.

각 항목의 판정 요약은 `performance.md` §8.4에 정본으로 반영했고, 본 리포트는 근거·수치의
상세 부록이다.

---

## T-VN-51 — MVT tile 도입 조건

### 무엇을 측정/검토했나
전국 low-zoom 지도 응답의 **응답 byte** 와 현재 cluster 계약(`GET /v1/features/in-bounds`
rollup)의 구조를, MVT가 개선할 budget 대비 검토했다.

### 근거
- 현재 low-zoom 계약은 **개별 point가 아니라 cluster rollup**이다. `in-bounds`는 viewport
  bbox 안 feature를 `GROUP BY sido_code|sigungu_code|legal_dong_code`로 집계한
  `ClusterSummary`(행정구역별 count) 배열 + `truncated` 플래그를 반환한다
  (`performance.md` §9.3.1/§9.3.2, `features.py` `max_items ≤ 2000`).
- 즉 low-zoom 응답 크기는 **화면상 feature 수가 아니라 viewport 안 행정구역 수**로 상한이
  잡힌다. 전국 zoom-out은 sido 17개 수준, 시군구 zoom은 수십~수백 개다. 응답은 좌표·형상
  없이 `{code, name, count, 대표점}` 수준의 작은 payload다.
- MVT(Mapbox Vector Tile)는 **개별 vertex/point를 타일 단위로 인코딩**할 때(수천~수만 point를
  한 화면에 그릴 때) byte·렌더 비용을 크게 줄인다. 현재 계약은 개별 point를 low-zoom에
  내려보내지 않으므로 MVT가 줄일 raw point payload 자체가 존재하지 않는다.
- tier-2 harness(`perf_tier2_release_harness.py`)의 "전국 low-zoom cluster" viewport가 이미
  `returned_rows`·응답 bytes·p95를 release마다 기록하도록 설계돼 있어, 트리거 측정의 정본
  경로가 존재한다.

### 채택 기준(budget)
MVT는 다음이 **동시에** 참일 때만 구현 task를 연다.
1. low-zoom(예: sido/시군구 zoom)에서 **개별 point rendering 요구**가 신규 발생(cluster
   rollup으로 충족 불가한 제품 요구), 그리고
2. 해당 요구를 cluster+개별 point 혼합 GeoJSON으로 냈을 때 tier-2 harness 측정
   응답이 **>256 KiB(gzip 후)** 또는 **p95 > 200 ms(n150 기준)** 를 초과.

### 판정: **유예(defer)**
현재 cluster rollup 계약이 low-zoom byte를 이미 상한 짓고, 내려보내는 개별 point가 없어
MVT가 절감할 대상이 없다. 위 budget 트리거가 관측되기 전에는 구현하지 않는다. 트리거
측정은 release tier-2 harness "전국 low-zoom cluster" viewport 결과로 상시 감시한다.

---

## T-VN-52 — 범용 feature-context batch 도입 조건

### 무엇을 측정/검토했나
weather 전용 batch(T-VN-16)를 넘어선 **범용 feature-context batch**(여러 feature의
weather/price/notice 등 부가정보를 1회 왕복으로)가 필요한지, 실제 consumer round-trip과
query count 기준으로 검토했다.

### 근거
- 이미 `POST /v1/features/batch`(service read, ServiceToken)가 존재하고 **max 200 feature_id**를
  1회 요청으로 받는다. tier-1 perf gate가 item 50→100에도 발생 SQL statement가 **1건으로
  일정**함(N+1 없음)을 매 PR 검증한다(`test_perf_gate_tier1.py`, "query 수 ≠ batch item 수").
- 부가정보 중 알려진 N+1은 **weather**이며, T-VN-16이 set-based weather batch +
  `target_at`/`known_at`으로 이를 제거한다(부모 404 구분 포함). price는 detail 응답에
  이미 인라인/LATERAL로 붙는다.
- 따라서 현재 알려진 consumer(PinVi)의 per-row 왕복 병목은 weather 하나이며, 그 해소는
  weather batch로 이미 계획돼 있다. "범용" batch(임의 context kind 조합)의 두 번째 실수요는
  아직 측정된 바 없다.

### 채택 기준(response shape·최대 크기 고정)
범용 batch를 열 때의 계약을 미리 고정한다.
- **최대 크기**: 기존 batch와 동일 **200 id/요청**(응답 상한·N+1 가드 계약 일관).
- **응답 shape**: `{ feature_id → { requested_context_kind → payload | null } }` 형태로,
  존재하지 않는 parent는 빈 결과가 아니라 **명시적 null/404 의미**를 유지(T-VN-16 규약 승계).
- **개방 조건**: weather 외 **두 번째** per-row 부가정보 왕복이 실제 consumer trace에서
  측정될 때(같은 요청 세트에 대해 왕복 수 > 1이 반복 관측).

### 판정: **유예(defer)**
현행 200-id batch + N+1 가드 + weather batch(T-VN-16)가 알려진 병목을 덮는다. 위 "두 번째
per-row 왕복" 트리거 전에는 범용 batch를 구현하지 않는다. 트리거 측정은 PinVi 결합
(T-VN-08/11/12/16) 배포 후 consumer round-trip 로그로 수행한다.

---

## T-VN-53 — cursor signing key rotation 운영 측정

### 무엇을 측정/검토했나
T-VN-15가 search cursor를 HMAC-SHA256 fingerprint keyset의 clean-cut으로 채택했으므로,
**도입 여부 측정은 폐기**한다(task 원문). 남은 것은 (a) key **rotation 주기**, (b) rotation 시
**진행 중 cursor 무효화율**, (c) **다중 key grace window** 필요성이다.

### 근거
- 현재 계약(T-VN-15): 단일 server-only secret의 HMAC로 versioned payload(query/filter/sort/page
  fingerprint + keyset)를 보호하고, 변조·query mismatch·unknown version·malformed를 DB 전에
  서로 다른 typed RFC7807 422로 거부한다. 즉 rotation은 **버전 필드가 이미 존재**해 clean-cut
  교체가 가능하다.
- cursor는 **단명(pagination 세션 내)** 이다. rotation 시 무효화되는 것은 "그 순간 페이지를
  넘기는 중"인 진행 cursor뿐이고, 클라이언트는 422를 받아 **처음부터 재조회**하면 된다(데이터
  손실 없음, 재요청 1회).
- rotation은 **정상 운영 이벤트가 아니라 사고/정책 이벤트**(secret 유출·주기적 강제 교체)다.
  빈도는 연 단위 이하로 예상된다.

### 채택 기준(grace window)
다중 key **grace window**(구/신 key를 window 동안 동시 허용)는 다음일 때만 구현 task를 연다.
- 실제 rotation 이벤트에서 **진행 cursor 무효화로 인한 사용자 체감 오류율**이 측정돼
  단순 clean-cut(422→재조회)보다 grace window가 명백히 우월함이 입증될 때.

### 판정: **유예(defer, clean-cut 유지)**
cursor 단명성 + 이미 존재하는 버전 필드 + 낮은 rotation 빈도로, clean-cut rotation이 충분하다.
grace window는 위 트리거(실측 무효화 통증) 전에는 구현하지 않는다. 운영 절차로 "secret
compromise 또는 정기(예: 분기) 교체 시 단일 활성 key를 clean-cut 교체, 진행 cursor는 422로
재조회"를 `performance.md` §8.4에 고정한다.

---

## T-VN-54 — weather partition·hypertable·event clock 측정

### 무엇을 측정/검토했나
`feature.feature_weather_values`의 3년 데이터량, ingest/update 비율, retention query를
추정해 native partition 또는 hypertable(TimescaleDB) 후보와 event clock 직렬화의 채택 기준을
문서화했다.

### 근거(스키마·적재 구조)
- 테이블: `feature_weather_values`(TEXT PK, `feature_id` FK, `metric_key`, `value_number`
  NUMERIC(14,4), `valid_at` TIMESTAMPTZ, `collected_at` TIMESTAMPTZ). valid_at BRIN + `(feature_id,
  forecast_style, metric_key, valid_at DESC)` index 존재(alembic 0017/0029/0060).
- 적재원: KMA 4종(초단기실황·초단기예보·단기예보·중기예보). 대상 좌표는
  `ops.poi_cache_targets`로 상한되는 **캐시 대상 POI 집합**이며 전체 feature가 아니다.
- **semantic UNIQUE(0060)** 로 (feature, forecast_style, metric_key, valid_at) 중복은 upsert
  수렴한다 — 즉 무한 append가 아니라 **valid_at 격자에 수렴하는 semantic upsert**다.

### 3년 볼륨 추정(파라미터화)
행 수 ≈ `대상 POI 수 × forecast_style별 metric_key 수 × valid_at 격자점 수(보존 기간 내)`.
- 대상 POI: `poi_cache_targets` 규모(현재 운영상 수백~수천 순으로 상한). 보수적 상한 10,000 가정.
- metric_key: forecast_style별 5~10종(T1H/REH/RN1/WSD/SKY/PTY 등) → 합 ~30.
- valid_at 격자: 단기예보 시간격자 최대 3일치·초단기 6h 등 — semantic upsert로 **미래
  격자에 수렴**하고 과거는 retention으로 정리 → 정상상태 활성 행은 **POI×metric×활성 격자**로
  상한. 정상상태 활성 행 ≈ 10,000 × 30 × (수십 격자) ≈ **수천만 이하**.
- 과거 이력을 보존(append-only)하면 3년 = POI×metric×(격자 갱신 빈도×기간)으로 증가하나,
  현재 계약은 **semantic upsert(수렴)** 이지 시계열 append가 아니다.

### 채택 기준(threshold)
native RANGE partition 또는 hypertable(TimescaleDB)은 다음 중 하나가 실측될 때 구현 task를 연다.
1. `feature_weather_values` 활성 행 수 **> 50M**, 또는
2. valid_at 범위 retention/조회 query p95가 **> 100 ms**(n150, 정상 index 하), 또는
3. 계약이 semantic upsert에서 **시계열 append(이력 보존)** 로 전환(T-VN-38 current summary가
   원본 이력을 보존하도록 바뀌면 append 축이 생겨 재측정 필요).
event clock 직렬화는 collected_at 단조성 위반(T-VN-H09)이 **동시 writer 경쟁**으로 재발할 때만
검토한다.

### 판정: **유예(defer, 명시 트리거)**
현재 semantic-upsert 계약 + POI 상한으로 정상상태 행 수는 partition/hypertable 임계 아래로
추정된다. 위 3개 트리거(특히 T-VN-38로 append 축이 생기는 경우) 전에는 구현하지 않는다.
Wave 2 T-VN-38(current summary) 확정 후 **이력 보존 여부**가 정해지면 본 항목을 재측정한다.

---

## T-VN-55 — 물리 listener/process 분리 측정

### 무엇을 측정/검토했나
단일 app(API + 부가 listener/background)의 resource contention과 장애 격리를 측정해, 세
listener를 물리 프로세스로 분리하는 것이 배포 복잡성보다 큰 이득을 주는 조건을 문서화했다.

### 근거
- 현재 배포는 API(FastAPI, 포트 12701)와 Dagster(12702)가 **이미 별 프로세스**이며, DB는 단일
  PostgreSQL(5432)이다. "세 listener 분리"는 API 프로세스 내부의 논리적 listener(HTTP read /
  service write / ops-live WS)를 물리 분리하자는 후보다.
- read >> write가 확정됐고(§9.3), ops-live WS는 #725 HMAC ticket으로 저빈도 operator 표면이다.
  즉 세 listener의 부하 프로파일이 크게 비대칭(read 지배)이라, 물리 분리의 주된 이득은
  **부하 격리보다 장애 격리**(한 listener OOM/hang이 다른 listener를 죽이지 않음)다.
- 배포 복잡성 비용: 프로세스 3개 → 헬스체크·배포 orchestration·connection pool 3배 관리·
  포트/네트워크 정책 증가(docker-manager 형상 변경 동반).

### 채택 기준(threshold)
물리 listener 분리는 다음 중 하나가 실측될 때 설계 task를 연다.
1. 단일 app에서 **connection pool 또는 CPU saturation**이 read 부하로 관측돼 write/ops-live
   latency를 침해(예: p95 상호 간섭 > 20%), 또는
2. **장애 결합 인시던트**(한 listener 장애가 타 listener 가용성 저하로 전파)가 운영에서 실제 발생.

### 판정: **유예(defer)**
API/Dagster는 이미 물리 분리돼 있고, API 내부 listener는 read 지배 비대칭이라 현재 부하에서
분리 이득이 배포 복잡성을 넘지 못한다. 위 2개 트리거(부하 상호간섭 또는 장애 전파 인시던트)
전에는 분리하지 않는다.

---

## T-VN-56 — 대규모 fixture 실행 주기 측정

### 무엇을 측정했나
"100만+ fixture gate"(= tier-2 release harness)의 **시간·비용·결함 검출률**을 수집해 매 PR /
nightly / release 중 적절한 실행 주기를 확정했다.

### 측정 결과(n150 CI-parity, 2026-07-21)
- **tier-1(매 PR, 소규모 3,200행 seed)**: `test_perf_gate_tier1.py` **12 passed in 28.3s**
  (컨테이너 포함 ~30s). editable 설치 64s는 gate당 상수 오버헤드다. 즉 per-PR 성능 gate 자체는
  **~30s** 로 매 PR 실행에 부담이 없다.
- **tier-2(100만+ 실분포 fixture)**: `perf_tier2_release_harness.py` docstring 기준 fixture seed가
  **수 분~수십 분**, 30 iteration EXPLAIN(ANALYZE) 포함 시 그 이상. CI 시간/자원(대용량 fixture)
  초과가 명시적 설계 전제이며(§8.3), **CI에서 절대 돌리지 않는다**가 정본이다.
- **결함 검출률(이력 근거)**: 실제로 잡힌 성능 결함은 **소규모 tier-1/EXPLAIN 계층**에서
  나왔다 — T-VN-18 GiST 6→partial 정리 write ~1.6× 개선 실측, T-212d planner index 적격성,
  N+1 가드(batch 50→100 statement 1건). 100만+ tier-2는 **회귀 검출기가 아니라 release 시점의
  절대 budget(p95·shared read blocks·bytes) 증거 생성기**로 기능한다(§8.3).

### 채택 기준(주기)
- **매 PR**: tier-1 소규모 fixture(현행). ~30s, planner index 적격성·N+1·response-shape 회귀.
- **release/cutover**: tier-2 100만+ fixture(현행). budget 증거 생성, 수동.
- **nightly(중간 계층)**: **조건부 유예**. 아래 트리거 전에는 신설하지 않는다.

### 판정: **확정(현행 2계층 유지) + nightly 유예**
tier-2(100만 fixture)는 **release 주기가 정확**하다 — 비용(수십 분)이 per-PR/nightly엔 과하고,
결함 검출은 소규모 tier-1이 담당하며, tier-2 역할은 release budget 증거이기 때문이다. nightly
중간 계층은 다음일 때만 신설한다.
- **트리거**: tier-1(소규모)에서 통과했으나 tier-2(대규모)에서만 드러난 **planner 회귀가
  release에서 반복 검출**될 때. 이 경우 nightly에 **축소 규모(예: 10만행)** fixture gate를 두어
  release 전에 대규모 전용 회귀를 앞당겨 잡는다.

---

## 종합 판정표

| Task | 주제 | 판정 | 트리거(재측정/개방 조건) |
|---|---|---|---|
| T-VN-51 | MVT tile | 유예 | low-zoom 개별 point 요구 발생 + tier-2 응답 >256KiB(gzip) 또는 p95 >200ms |
| T-VN-52 | 범용 batch | 유예 | weather 외 2번째 per-row 왕복 실측(PinVi trace) |
| T-VN-53 | cursor key rotation | 유예(clean-cut 유지) | 실 rotation에서 무효화 통증이 grace window 우위 입증 |
| T-VN-54 | weather partition/hypertable | 유예 | 활성 행 >50M, retention p95 >100ms, 또는 T-VN-38 append 전환 |
| T-VN-55 | 물리 listener 분리 | 유예 | read 부하 상호간섭 >20% 또는 장애 전파 인시던트 |
| T-VN-56 | 대규모 fixture 주기 | 확정(2계층 유지) | tier-2 전용 planner 회귀 반복 시 nightly 10만행 신설 |

여섯 항목 모두 **"측정 후 명시 트리거로 유예"** 이거나(51~55) **현행 정책 확정**(56)이다.
"확장 가능해 보인다"만으로 구현하지 않는다는 §8.3 원칙을 위반하는 즉시-구현 항목은 없다.
각 트리거는 이미 존재하는 관측 경로(tier-2 release harness, PinVi consumer trace,
rotation 이벤트 로그)로 감시 가능하다.
