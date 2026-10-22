# ADR-113 — 스트리밍 snapshot 적재는 먼저 다 받아 두고, 쓰기 transaction은 그 뒤에 짧게 연다

- 상태: proposed (2026-10-22, `T-LOAD-LOCK-WAIT` 2안. 소유자가 "쓰기 묶음 나누기/잠금 쥐는 시간 줄이기"로 승인한 방향의
  설계 — 머지 때 accepted로 고친다)
- 날짜: 2026-10-22
- 결정자: Claude (방향은 소유자 승인)
- 관계: ADR-111(전역 fence와 잠금 순서 §2, 후속 1안), ADR-109(geo 관측 토큰), ADR-108(MOIS 재개형 chunk), ADR-107(Dagster
  client 연결 1개)

## 컨텍스트

`AsyncKorTravelMapClient.load_feature_bundle_batches`는 async batch stream을 **한 transaction**으로 적재한다. transaction을
먼저 열고 `async for batch in batches`로 stream을 당기므로, stream이 하는 일 — upstream 페이지 fetch, 변환, 역지오코딩,
주소 검증 — 이 전부 열린 transaction 안에서 돈다. 첫 batch의 `load_bundles`가 전역 `feature-curation-write`
(`pg_advisory_xact_lock`)를 잡으면 그 fence는 **나머지 fetch·지오코딩이 끝나 commit할 때까지** 쥔 채다.

2026-10-22 prod(읽기 전용 실측, PR #1348 본문·journal 같은 날): `feature_place_standard_parking_lots`(run `71f21b6a`,
상류 약 18,883건 = 1,000건 × 19쪽)이 06:06Z부터 08:38Z 넘어서까지(>9,141초) fence를 쥐었고 대부분이 `idle in
transaction`이었다. batch 사이 공백은 최대 약 85초였고 DB 쓰기는 batch마다 몇 초였다. 같은 경로를 8개 asset이 쓴다
(krforest 휴양림·수목원, 표준데이터 박물관·관광지·주차장·특화거리, khoa 해수욕장, transport 공항). 그 동안
`finalize_provider_curation_root`는 30초마다 55P03이었고 다른 적재는 900초(1안)를 기다리다 실패했다.

큐 경로(`feature_update_runner`)는 같은 run 함수를 executor transaction에 결합한 client로 부른다. fence는 거기서도
`load_bundles`의 첫 호출에서 잡히므로 같은 병이다 — 원인은 하나(stream을 transaction 안에서 당김)다.

나머지 적재 경로는 이미 이 모양이 아니다: `_load` 계열은 bundle을 먼저 다 만든 뒤(`list(bundles)`) transaction을 연다.
MOIS는 chunk마다 지오코딩을 끝낸 뒤 chunk transaction을 연다(ADR-108). 이 둘은 바꾸지 않는다.

## 결정

### 1. stream은 transaction 밖에서 끝까지 당겨 임시 파일에 쌓는다(spool), 그 뒤 한 transaction으로 쓴다

`load_feature_bundle_batches`는 두 단계다.

1. **받기(잠금 없음).** stream을 끝까지 당긴다. 각 batch는 그대로 `pickle`해 프로세스 전용 임시 파일
   (`tempfile.TemporaryFile`)에 덧붙인다. 이 단계에는 DB session이 없다. stream이 던지면(주소 검증 strict 실패·소실 하한·
   빈 답 가드·fetch 실패) transaction은 열리지도 않는다.
2. **쓰기(fence).** `_feature_load_transaction` 하나를 열고 파일을 처음부터 batch 순서대로 읽어 `load_bundles`에 넣는다.
   `curation_dataset`이 있으면 같은 transaction 끝에서 `capture_provider_curation_input`(seal)을 읽는다 — 종전과 같은
   문장, 같은 순서다.

임시 파일은 이 호출 안에서 열리고 닫힌다(정상·예외 모두). 메모리는 종전처럼 batch 하나만큼만 쓴다 — 이 경로가 batch
stream인 이유(snapshot 전체를 메모리에 두지 않음)는 그대로 지킨다. 파일 크기는 대략 dataset의 bundle pickle 합(주차장
약 1.9만 건에서 수십~백수십 MB)이고 n150 Dagster 컨테이너 `/tmp`는 overlay(여유 115 GB, 2026-10-22 실측)다. 같은 함수가
이미 주소 검증 finding을 같은 방식으로 spool한다(`etl.load_feature_bundle_batches_for_dagster`).

spool을 client에 두는 이유: stream을 transaction 안에서 당기는 곳이 client 한 곳이고, Dagster asset 경로와 큐 경로가 모두
그 메서드를 부른다. 호출자(etl·asset 8개)를 고치지 않고 두 경로가 같이 고쳐진다. 직렬화가 pickle인 이유: 이미 검증된
pydantic 객체를 **다시 검증하지 않고** 바이트 그대로 되살린다 — JSON 왕복은 validator를 다시 돌려 "적재되는 값이 같다"는
보장을 하나 더 증명해야 한다. 파일은 이 프로세스가 방금 쓴 것만 읽는다(외부 입력 아님).

### 2. 지키는 것 — snapshot 계약

| 계약 | 종전 | 이 결정 뒤 |
|---|---|---|
| 원자성 | stream·쓰기 중 어디서 실패해도 전부 rollback | 받기 실패는 transaction 없음(쓴 것 없음), 쓰기 실패는 rollback — 둘 다 "아무것도 commit 안 됨" |
| 한 DB image에 대한 seal | seal을 같은 transaction 끝에서 읽음 | 같음. 쓰기·seal 사이에 다른 writer가 끼지 못한다(fence를 쓰기 시작부터 commit까지 쥠) |
| absent-row retire | 이 경로는 하지 않는다(asset 8개 모두 `retire_absent_from_snapshot` 없음) | 그대로 — 이 결정과 무관하다 |
| 멱등성 | `load_bundle`의 payload hash 비교·upsert | 같음(같은 bundle을 같은 순서로) |
| 같은 dataset의 동시 실행 | 이 8개는 `provider_run_lock`을 쓰지 않는다(고속도로 돌발만 쓴다). 예약·수동 run은 `GEO_HEAVY_POOL`(1)이 묶고, 큐 경로는 pool을 거치지 않는다. 겹치면 둘째가 첫 batch에서 fence에 막혀 실패했다 — 우연한 직렬화 | 둘 다 끝까지 받은 뒤 차례로 쓴다(결정 5) |
| 잠금 순서(ADR-111 §2) | `feature-curation-write`는 첫 `load_bundles`에서 | 같음. 새 잠금 없음 |
| receipt·root·sync cursor | 적재 뒤 별도 transaction | 같음 |
| 대기 상한(1안) | 첫 fence 획득만 900초 | 같음 |

달라지는 것은 둘이다.

- **fence 보유 = 쓰기 시간.** 받기 동안 이 적재는 fence도 transaction도 쥐지 않는다. 다른 적재·root 완결·단건 writer가
  그 사이에 들어간다.
- **geo 관측 토큰은 받기가 끝난 뒤 한 번에 본다(ADR-109).** `GeoLoadContext.observed_data_tokens`는 run의
  `GeoCallStats` 집합을 가리키므로, 종전에는 앞 batch가 "그때까지 본 토큰"으로 stale 판정·스탬프됐고 뒤에서 전환을 만나면
  뒤 batch만 건너뛰었다. 이제 모든 batch가 run 전체의 관측을 본다 — 전환을 가로지른 run은 **어느 batch에서도** stale
  재정렬(`stale_among(..., None)`은 빈 집합)과 스탬프를 하지 않는다. 그 행들은 다음 run이나 geo 릴리스 계획이 다시 고른다.
  ADR-109의 의도(옛 데이터로 해석한 행이 새 토큰으로 봉인되지 않게)와 같은 쪽으로 더 엄격해진다(단위 검사가 이 순서를 센다).

### 3. 쓰기를 묶음으로 쪼개 fence를 중간에 놓지는 않는다

쓰기 단계도 길면 묶음마다 commit하고 fence를 놓는 설계를 검토했고 **하지 않는다.**

- 묶음 commit은 "snapshot 하나 = 한 DB image" 계약을 깬다. 중간 상태가 보이고, 다른 writer가 묶음 사이에 끼면 마지막
  묶음 뒤의 seal이 섞인 image를 봉인한다(etl의 기존 주석이 이 이유로 한 transaction을 고집한다). 이를 지키려면 staging
  표·세대 번호·재개 지점 같은 장치가 필요하고, 그것이 ADR-108이 MOIS 하나에만 감수한 복잡도다.
- 실측으로는 필요가 없다 — "결과"의 쓰기 처리량(n150 일회용 PostGIS)으로 이 경로의 가장 큰 dataset(주차장 약 1.9만 건,
  batch 189개)의 쓰기 단계를 추정했다. 다만 prod n150은 디스크 대기가 커서(load가 CPU가 아니라 I/O) 일회용 실측보다 느릴
  수 있다. 그래서 숫자를 단정하지 않고 **재는 장치**를 둔다: 쓰기 단계 시간(= 이 적재의 fence 보유 상한)과 spool 크기를
  client가 매 적재 INFO 로그로 남긴다. 배포 뒤 8개 asset의 첫 실측을 journal에 남기고, 그때 이 ADR을 accepted로 올린다.
- jsonb seal 천장(등산로 5.7만 건, 256 MB)은 seal 계산의 문제이고 이 경로를 쓰지 않는다 — 쪼개기로 풀리지도 않는다.

실측(n150 일회용 PostGIS, 2026-10-22, 축제 bundle 3,000건, 100건 batch, Dagster와 같은 엔진 설정): **첫 적재(전부
insert) 32.4건/초, 같은 snapshot 재적재(변경 없음) 140건/초.** 주차장 1.9만 건으로 옮기면 쓰기 단계는 첫 적재 약 580초,
정상 주기 재적재(대부분 변경 없음) 약 135초다. 첫 적재는 dataset마다 한 번(주차장은 prod에서 아직 성공한 적이 없어 다음
run이 그것이다)이고, 그 한 번도 종전 2.5시간+보다 짧고 900초 대기 상한 안이다. 나머지는 공항 15·휴양림 182·해수욕장 275·특화거리 403·관광지
897·박물관 1,076건(`docs/etl/upstream-quota.md`·prod 실측)이라 첫 적재도 1분 안쪽이다(수목원 SHP 건수는 미측정 — 로그로 본다).

다시 볼 조건: **재적재**(첫 적재가 아닌) 쓰기 단계 로그가 **300초**를 넘으면(1안 대기 상한 900초의 1/3 — 적재 셋이 줄을
서면 셋째가 상한에 닿는다) ADR-108식 재개형 chunk나 쓰기 재시도(결정 6)를 다시 연다. 그때까지는 가장 단순한 모양을 둔다.

### 4. 큐 경로 — fence는 고쳐지고, `idle in transaction`은 남는다

`_bind_client_to_session`이 만든 client도 같은 메서드를 부르므로 받기 동안 fence를 쥐지 않는다. 그러나 executor의 scope
transaction은 runner 호출 전체를 덮으므로(`_execute_feature_update_request_locked`) 받기 동안에도 `idle in transaction`으로
열려 있다. 그 transaction은 `_guard_execution_phase`·`_heartbeat_request_job`이 갱신한 요청·job 행을 잠근 채라 그 요청의
취소·종결 writer를 막고, 그 heartbeat는 commit 전이라 다른 연결에는 낡아 보이고, vacuum xmin을 붙든다. 이것은 종전부터의
성질이고 전역 fence와 달리 **그 요청 하나**에 국한된다. 고치려면 받기를 `session.begin()` 앞으로 옮겨야 하는데, 그것은
executor의 원자성(scope 결과와 적재를 한 commit에) 설계를 바꾸는 일이라 이 ADR 범위가 아니다 — 후속 항목으로 남긴다
(`docs/tasks.md` T-LOAD-LOCK-WAIT 아래 기록). 따라서 "`idle in transaction`인 fence 보유가 없어진다"는 두 경로 모두 참이고,
"`idle in transaction` 자체가 없어진다"는 Dagster asset 경로에서만 참이다.

### 5. 같은 dataset이 동시에 돌면 둘 다 받는다 — 받아들인다

종전에는 fence가 우연히 같은 dataset의 두 실행을 직렬화했다(둘째가 첫 batch에서 막혀 싸게 실패). 이제 둘 다 끝까지
받고(upstream 쿼터와 역지오코딩 두 배) 쓰기만 차례로 한다. 결과는 맞다 — 늦게 쓰는 쪽의 관측이 더 오래된 경우에도 head는
뒤로 가지 않는다(`feature_repo` head 갱신의 `WHERE` 가드). 겹침 자체는 드물다: 예약·수동 run은 `GEO_HEAVY_POOL`(1)이 묶고,
큐 경로의 이 8개는 사람이 `provider_dataset` scope로 넣는 일회성이다. 막으려면 `provider_run_lock`을 두 경로에 거는 것이
자연스럽지만(고속도로 돌발이 선례), 그것은 새 잠금·새 실패 모양(둘째가 30초 뒤 55P03)을 들이는 별도 결정이라 하지 않는다.
쿼터 소진이나 geo 과부하로 실제 겹침이 관측되면 그때 건다.

### 6. 쓰기 단계의 fence 대기 실패를 그 자리에서 다시 하지 않는다

1안의 900초 대기가 실패하면 이제 긴 받기 **뒤에** 실패하고, retry policy가 받기부터 다시 한다. spool은 다시 읽을 수
있으므로 쓰기만 다시 하는 것이 가능하지만 하지 않는다 — fence 보유가 쓰기 시간(분 단위)으로 줄어 900초 대기가 실패하려면
큰 적재 여럿이 연달아 줄을 서야 한다. 결정 3의 300초 조건과 함께 다시 본다.

## 결과

- 스트리밍 snapshot 8개 asset의 fence 보유가 "fetch + 지오코딩 + 쓰기"(실측 2.5시간+)에서 "쓰기"로 준다. `idle in
  transaction`인 fence 보유가 없어진다(큐 경로의 executor transaction은 결정 4).
- 실패한 받기는 DB에 아무것도 남기지 않고 transaction도 열지 않는다.
- migration 없음, OpenAPI·PinVi 계약 변경 없음, 설정 추가 없음. 배포는 Map Dagster code location 재배포.
- 기대 fence 보유: 주차장 첫 적재 약 10분, 재적재 약 2~3분(일회용 실측의 환산 — prod 디스크 대기로 더 길 수 있다, 로그로 잰다),
  나머지는 1분 안쪽. 종전 실측 9,141초+.
- 검사: 통합 — 느린 stream이 받기 중에 멈춰 있는 동안 다른 연결이 fence를 몇 초 안에 잡는다, 그 연결이 fence를 쥐는 동안
  쓰기는 기다린다, 적재 결과·seal은 commit된 image의 seal과 같다, 큐 경로 결합 client도 같다. 단위 — stream이 끝나기 전에
  transaction이 열리지 않는다.

### 되돌릴 때

코드만 되돌리면 된다(스키마·데이터 변경 없음).

## 설계 리뷰 반영(2026-10-22, 적대 리뷰 1회)

- H1(쓰기 단계가 900초를 넘을 수 있다, 근거 없는 비교): 결정 3을 실측·로그·300초 재검토 조건으로 바꿨다.
- H2(`provider_run_lock` 행이 사실과 다름): 표를 고치고 동시 실행의 비용을 결정 5로 명시했다(잠금은 걸지 않는다).
- M1(늦은 실패): 결정 6 — 쓰기 재시도는 하지 않고 재검토 조건에 묶었다.
- M2(큐 경로 `idle in transaction`): 결정 4를 고쳐 남는 것을 적었다.
- M3(geo 토큰은 스탬프만이 아니라 stale 재정렬도): 결정 2 문구와 단위 검사.
- L1 etl 주석 갱신, L2 빈 stream도 seal(단위 검사), L4 spool 크기 로그, L5 absent-row 문구.
