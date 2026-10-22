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
| absent-row retire | 이 경로는 하지 않는다(asset 8개 모두 `retire_absent_from_snapshot` 없음) — root 완결의 membership/seal이 맡는다 | 같음 |
| 멱등성 | `load_bundle`의 payload hash 비교·upsert | 같음(같은 bundle을 같은 순서로) |
| `provider_run_lock` | 받기·쓰기 전체를 session-level lock이 덮음 | 같음 — 같은 provider의 두 실행은 여전히 겹치지 않는다 |
| 잠금 순서(ADR-111 §2) | `feature-curation-write`는 첫 `load_bundles`에서 | 같음. 새 잠금 없음 |
| receipt·root·sync cursor | 적재 뒤 별도 transaction | 같음 |
| 대기 상한(1안) | 첫 fence 획득만 900초 | 같음 |

달라지는 것은 둘이다.

- **fence 보유 = 쓰기 시간.** 받기 동안 이 적재는 fence도 transaction도 쥐지 않는다. 다른 적재·root 완결·단건 writer가
  그 사이에 들어간다.
- **geo 관측 토큰은 받기가 끝난 뒤 한 번에 본다(ADR-109).** `GeoLoadContext.observed_data_tokens`는 run의
  `GeoCallStats` 집합을 가리키므로, 종전에는 앞 batch가 "그때까지 본 토큰"으로 스탬프됐고 뒤에서 전환을 만나면 뒤 batch만
  스탬프를 건너뛰었다. 이제 모든 batch가 run 전체의 관측을 본다 — 전환을 가로지른 run은 어떤 batch도 새 토큰으로 봉인하지
  않는다. ADR-109의 의도(옛 데이터로 해석한 행이 새 토큰으로 봉인되지 않게)와 같은 쪽으로 더 엄격해진다.

### 3. 쓰기를 묶음으로 쪼개 fence를 중간에 놓지는 않는다

쓰기 단계도 길면 묶음마다 commit하고 fence를 놓는 설계를 검토했고 **하지 않는다.**

- 묶음 commit은 "snapshot 하나 = 한 DB image" 계약을 깬다. 중간 상태가 보이고, 다른 writer가 묶음 사이에 끼면 마지막
  묶음 뒤의 seal이 섞인 image를 봉인한다(etl의 기존 주석이 이 이유로 한 transaction을 고집한다). 이를 지키려면 staging
  표·세대 번호·재개 지점 같은 장치가 필요하고, 그것이 ADR-108이 MOIS 하나에만 감수한 복잡도다.
- 필요가 없다. 이 경로의 가장 큰 dataset(주차장 약 1.9만 건)의 쓰기는 batch 190개 × 몇 초 = 분 단위로 예상되고(구현 뒤
  n150 일회용 PostGIS 실측을 "결과"에 적는다), 이미 한 transaction으로 쓰는 다른 경로(유가·주유소 각 1.18만 건,
  `_load`)와 같은 크기다. 1안의 900초 대기 상한 안에 들어온다.
- jsonb seal 천장(등산로 5.7만 건, 256 MB)은 seal 계산의 문제이고 이 경로를 쓰지 않는다 — 쪼개기로 풀리지도 않는다.

다시 볼 조건: 이 경로의 쓰기 단계가 실측으로 900초에 가까워지면(dataset이 수만 건으로 커지면) ADR-108식 재개형 chunk로
옮긴다. 그때까지는 가장 단순한 모양을 둔다.

### 4. 큐 경로

`_bind_client_to_session`이 만든 client도 같은 메서드를 부르므로 받기 동안 fence를 쥐지 않는다. 다만 executor의 scope
transaction(heartbeat·요청 행 갱신)은 runner 호출 전체를 덮고 있으므로 **열린 transaction 자체**는 종전처럼 받기 동안에도
열려 있다 — 그 transaction이 쥔 것은 요청·job 행 잠금과 rate gate이고 전역 fence는 아니다. 그 transaction을 쪼개는 것은
executor의 원자성(scope 결과와 적재를 한 commit에) 설계를 바꾸는 일이라 이 ADR 범위가 아니다.

## 결과

- 스트리밍 snapshot 8개 asset의 fence 보유가 "fetch + 지오코딩 + 쓰기"(실측 2.5시간+)에서 "쓰기"로 준다. `idle in
  transaction`인 fence 보유가 없어진다.
- 실패한 받기는 DB에 아무것도 남기지 않고 transaction도 열지 않는다.
- migration 없음, OpenAPI·PinVi 계약 변경 없음, 설정 추가 없음. 배포는 Map Dagster code location 재배포.
- 검사: 통합 — 느린 stream이 받기 중에 멈춰 있는 동안 다른 연결이 fence를 몇 초 안에 잡는다, 그 연결이 fence를 쥐는 동안
  쓰기는 기다린다, 적재 결과·seal은 commit된 image의 seal과 같다, 큐 경로 결합 client도 같다. 단위 — stream이 끝나기 전에
  transaction이 열리지 않는다.

### 되돌릴 때

코드만 되돌리면 된다(스키마·데이터 변경 없음).
