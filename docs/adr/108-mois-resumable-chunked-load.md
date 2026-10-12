# ADR-108 — MOIS 인허가 적재는 원천 내용을 재개 키로 하는 chunk commit 적재다

- 상태: proposed (소유자가 2026-10-12 재구성을 승인했다. 아래 "열린 결정"은 소유자 판단 대기)
- 날짜: 2026-10-12
- 결정자: human(승인), Claude
- 관계: ADR-099(curation seal fold — 크기 한계는 이미 해소), ADR-087/088(source head·membership),
  ADR-011(`import_jobs`), ADR-034 7단계(MOIS bulk)

## 컨텍스트

prod `1a3c4673` 기준 MOIS(행안부 LOCALDATA 인허가) 적재는 42개 업종 약 98만 행이다
(`general_restaurants` 원천만 213만 행). 이 적재는 구조적으로 끝날 수 없었다.

1. **시간.** 좌표 역지오코딩을 행마다 순서대로 부른다(kor-travel-geo 왕복 약 130ms).
   98만 행 × 130ms ≈ 35시간인데 run 상한은 6시간(`RecoveryPolicy` 21,600초)이다.
2. **원자성.** 전 행이 transaction 하나였다. 늦은 실패 하나가 전부를 되감았고,
   `FEATURE_LOAD_RETRY_POLICY`(3회 재시도)는 매번 처음부터 다시 지오코딩했다.
3. **원천 보존.** Phase A SQLite(약 5GB)가 `/tmp/mois_source.db` — 컨테이너 overlay — 에
   있어 재생성마다 사라졌다.
4. **큐 경로.** 큐 runner는 asset의 모든 client 호출을 executor transaction 하나에
   결박한다. MOIS fetcher는 scope를 보지 않으므로 반경 하나짜리 PinVi 요청도 전국 적재를
   한 transaction으로 시작할 수 있었다.

kor-travel-geo에는 batch endpoint가 없다(`POST /v2/reverse`·`/v2/geocode`는 한 건씩, geo
origin/main `02a3c2e` 확인). n150은 디스크 대기로 포화돼 있고 geo ReadTimeout은 그 증상이다.

## 결정

### 1. 재개 키는 원천 내용이다 — 새 상태표·cursor를 두지 않는다

chunk마다 각 record의 `source_entity_id`(`{slug}::{mng_no}`)와 `raw_payload_hash`를 지오코딩
**전에** 계산한다(`license_record_payload_hash` — `_raw_data`는 원천 필드만 담는다). 그리고
DB에 한 번 묻는다: "head의 current record가 같은 payload hash이고 primary feature가 active인가".

그 조건은 `load_bundle`이 같은 record를 다시 받았을 때 **관측 시각 말고는 아무것도 바꾸지
않는** 조건과 같다(`became_current=False` → feature 본문 미기록, active → lifecycle 전이 없음).
그래서 그런 record는 변환·지오코딩을 건너뛰고 관측만 전진시키고(`reobserve_unchanged_source_entities`),
나머지만 변환·적재한다. 두 일은 **chunk 하나(최대 500행, 한 업종)의 transaction 하나**에서 끝난다.

- 중단 뒤 재실행은 commit된 chunk를 전부 건너뛰고 이어 간다 — 중복도, 반쯤 쓰인 chunk도 없다.
- 원천 snapshot이 바뀐 뒤의 run은 바뀐 행만 지오코딩한다. 월간 갱신이 사실상 증분이 된다.
- 확인과 기록 사이에 entity가 바뀌면 `ProviderEntityReobservationConflict`로 그 chunk를 되돌린다.
- 재관측 시각은 Phase A marker의 `synced_at`(원천 snapshot 시각)이다. 같은 snapshot을 다시 돌린
  run은 이미 그 뒤에 관측된 행을 다시 쓰지 않는다(n150 디스크 대기 — 백만 행 재기록을 피한다).
- 판정이 읽는 표·열은 `load_bundle`이 이미 읽는 것과 같다. 새 권한·마이그레이션이 없다.

`provider_sync_state` cursor(업종·mng_no 위치)도 검토했다. 그것은 원천 DB가 바뀌면 무효화해야
하고(순서·행이 바뀐다), 무효화 규칙이 또 하나의 정본이 된다. 내용 키는 그 문제가 없다.

### 2. 지오코딩 — bounded 동시성 선조회 + run 수명 캐시

`PrefetchingReverseGeocoder`가 chunk의 역지오코딩 좌표(원천 `legal_dong_code`가 있으면 제외 —
변환과 같은 조건, `license_reverse_geocode_coordinate`)를 중복 없이 모아 최대
`KOR_TRAVEL_MAP_MOIS_GEOCODE_CONCURRENCY`(기본 **2**, 1~8)개까지 동시에 조회해 캐시한다.
캐시는 run 수명·LRU 5만 좌표다. 이미 적재된 행은 앞 단계에서 빠지므로 지오코딩하지 않는다.
선조회 실패는 캐시하지 않는다 — 변환이 한 번 더 실시간으로 시도하고, 그래도 실패하면 예외가
올라간다(빈 bjd로 조용히 적재하지 않는다).

### 3. run 크기 — 시간 상한 + 이어 달리기 sensor

run 하나는 `KOR_TRAVEL_MAP_MOIS_LOAD_RUN_BUDGET_SECONDS`(기본 14,400초=4시간, 최대 19,800초)까지만
새 chunk를 시작한다. 시작한 chunk는 끝까지 commit하고, 첫 chunk는 언제나 시작한다(run마다 최소
한 chunk 전진). 상한에 닿으면 정상 종료하고 run tag `kor_travel_map.mois_load.outcome=budget_exhausted`를
남긴다. `feature_place_mois_licenses_continuation_sensor`(기본 STOPPED)가 가장 최근 run 하나만
보고, 성공·`budget_exhausted`면 **같은 run_config**로 다음 run을 띄운다. 실패한 run은 잇지
않는다 — 사람이 원인을 본 뒤 다시 띄우면 그 자리부터 이어진다. 월간 schedule은 활성 run과
겹치면 tick을 합친다(`coalesce_active_runs`).

업종별 Dagster partition도 검토했다. partition은 asset 정체성·operation membership·큐 runner·
schedule 표·admin UI가 모두 의존하는 축을 바꾼다. 시간 상한 + 내용 재개는 그 축을 그대로 두고
같은 효과(6시간 안의 run, 업종 하나씩)를 낸다.

retry는 1회·5분 뒤로 줄인다(`MOIS_LOAD_RETRY_POLICY`). 재시도도 이어 가기 때문이다.

**시간은 run 시작부터 잰다**(적대 리뷰 MED-3). 기준은 Dagster run record의 `start_time`이다 —
step 시작으로 재면 resource init의 Phase A sync(약 24분)와 step 재시도가 쓴 시간이 빠져 run 상한
6시간을 넘을 수 있다. 실제 상한은 `min(plan 상한, run의 dagster/max_runtime tag - 30분)`이다(30분 =
`RUN_FINAL_MARGIN_SECONDS`, 마지막 chunk·봉인 질의·sync 기록 여유). settings 최대값 19,800초는 이
job의 run 상한 21,600초 - 30분이고, 둘이 갈라지면 테스트가 빨개진다.

**이어 달리기 방어**: sensor는 미종료 MOIS run이 하나라도 있으면 띄우지 않고(schedule tick과의 경합),
마지막 run이 새 행을 0건 적재하고 상한에 닿았으면(tag `kor_travel_map.mois_load.records_converted=0`)
멈춘다 — 같은 자리에서 영원히 멈추는 고리를 막는다. 단 그 run이 **상한의 절반 이상을 받고 시작했을
때만**이다(tag `…budget_seconds`·`…budget_available_seconds`). 늦은 실패 뒤의 step 재시도는 run 시작
기준 상한이 이미 지나 한 chunk(대개 미변경)만 하고 멈추는데, 그것을 "전진 불가"로 보면 다음 월간
tick까지 정체된다(델타 리뷰 MED-1). tag가 없거나 깨졌으면 이어 달린다. 둘이 겹쳐 떠도 GEO_HEAVY pool(limit 1, run
단위)이 실행을 직렬화하고, 재개형이라 뒤 run은 건너뛰기만 한다.

### 3a. 소실 하한과 geo 장애 (적대 리뷰 MED-1)

종전 drop 모드 소실 하한(버린 비율 > 50%)을 chunk마다 재면 1~3행 꼬리 chunk의 한 행이 100%
소실이 되어 run이 실패하고, 재시도도 같은 자리에서 실패해 이어 달리기가 영구히 멈춘다. 그래서
chunk 적재 함수의 하한은 끄고(`enforce_loss_guard=False`) 적재기가 직접 잰다.

- **데이터 무효**(`missing_address` 등 위치 단서 없음)는 **업종 누적**으로 재고, 관측 200행
  (`LOSS_GUARD_MIN_SAMPLE`) 이상일 때만 판정한다. 넘으면 그 chunk를 commit하기 **전에** 멈춘다.
  작은 업종의 drop은 행 단위 finding으로만 남는다.
- **지오코더 원인**(`reverse_geocode_failed`)은 따로 센다. 이런 행은 적재되지 않으므로 다음 run이
  다시 변환한다 — 영구 손실이 아니다. 대신 **geo 장애**는 run 장애로 다룬다: 최근 50건 조회 중
  20건 이상이 모였고 그 80% 이상이 법정동코드 없이 돌아오면, **알려진 좋은 좌표를 캐시 없이
  다시 묻는다** — 고정 내륙 기준점과 이 run에서 법정동코드를 받은 마지막 좌표 **둘 다**. 기준점은
  서울시청(경도 126.9779692, 위도 37.5662952, `GEO_PROBE_REFERENCE`)이다 — 내륙이고 행정 경계에서
  멀어 정상 geo라면 언제나 법정동이 풀리는 좌표다.
  하나라도 빈 답(또는 예외)이면 그 chunk를 적재하기 전에 upstream 장애로 실패한다(행을 버리며
  진행하지 않는다). 둘 다 답하면 geo 전체는 건강하다 — 창을 비우고 계속한다.
  비율만으로 판정하면 재개 run이 영구히 막힌다(델타 리뷰 HIGH-1): 바다·경계처럼 빈 답이 정상인
  좌표의 행은 적재되지 않아 매 run 다시 변환되고, 적재된 행은 건너뛰므로 재개 run의 조회는 거의
  전부 그 빈 답이 된다. 표식 표를 두어 그 행을 건너뛰는 안도 검토했으나, 새 저장소·무효화 규칙 없이
  probe 한 번(최대 50조회마다 1회)으로 같은 판정이 된다. 대가로 그런 행은 매 run 다시 지오코딩된다
  (소수이고 run 캐시가 중복을 막는다).

### 3a-2. 지역 장애는 실패가 아니라 degraded run이다 (최종 델타 리뷰 MED-1)

probe는 다른 지역의 좋은 좌표를 묻으므로 시·도 하나의 layer만 빈 **지역 장애**는 가리지 못한다.
`mng_no`가 발급 지자체 순이라 그 지역의 행이 한 업종 안에서 연속으로 오고, 문턱 초과 → probe 통과 →
창 비움이 끝없이 반복되며 그 지역이 통째로 빠진 채 run이 `complete`·봉인될 수 있었다. 그래서:

- **빈 답 행은 어느 검증 모드에서도 적재하지 않는다.** drop은 적재 함수가 버리고, off는 적재기가
  뺀다(off에서 빈 bjd로 commit하면 같은 payload는 다음 run에 "그대로"로 건너뛰고, 같은 payload의
  재적재는 feature 본문을 다시 쓰지 않아 빈 bjd가 영원히 남는다). strict는 원래대로 run을 멈춘다.
  그래서 그 행은 다음 run이 언제나 다시 시도한다.
- **비율 상한**: 업종 하나 또는 run 전체에서 **지오코더로 보낸 행** 대비 빈 답 행이
  `KOR_TRAVEL_MAP_MOIS_GEOCODE_DEGRADED_RATIO`(기본 5%, 0 초과)를 넘으면 degraded다. 분모는 조회한 행이고
  최소 표본은 조회 50행(`GEOCODE_RATIO_MIN_SAMPLE`)이다 — 이미 적재돼 건너뛴 행으로 희석하면 정상 상태의
  지역 장애가 보이지 않는다(델타 리뷰 LOW-1). 업종마다 표본이 모자라도 run 전체 판정이 잡는다.
- **K회 통과 판정**: 같은 업종에서 "문턱 초과 + probe 통과"가 3회(`GEO_PASSING_TRIPS_DEGRADE`) 쌓이면
  degraded로 표시한다.
- degraded run은 **실패시키지 않는다**(영구 정지를 다시 만들지 않는다). 대신 authoritative가 아니다 —
  봉인·provider sync 성공을 남기지 않는다. run tag `kor_travel_map.mois_load.geocode_degraded`(업종 목록),
  metadata `mois_geocode_degraded`·`mois_geocode_degraded_slugs`·`mois_reverse_geocode_empty`·
  `mois_geo_probes`·`mois_geo_probe_passes`·`mois_geocoded_rows`·`mois_known_unresolvable`, 경고 로그를
  남긴다. outcome은 `complete`라 sensor는 잇지 않고, 다음 schedule·수동 run이 빈 행만 다시 한다.
- **붉게 드러낸다**: 이번 run이 끝까지 본 전체 run(`outcome=complete`·`full_coverage=true`)이고 degraded일
  때, 직전 완료 전체 run까지(포함) 거슬러 올라간 **이어 달리기 사슬의 어느 전체 run**(`budget_exhausted`
  포함)이라도 degraded였으면 이번 run은 **FAILURE**(재시도 없음)로 끝나며 두 run의 degraded 업종을 적는다.
  사슬 중간의 degraded run을 빼고 마지막 완료 run만 비교하면 두 번째 degraded를 놓친다(최종 리뷰 MED-1).
  tag는 실패 전에 남기므로 다음 판정의 근거가 되고, outcome이 이미 `complete`라 사슬을 막지 않는다.
- **overdue로 드러낸다**: migration `405_mois_freshness_sla`가 MOIS bulk dataset policy에
  `stale_after_minutes=57600`(40일 = 월간 schedule + 여유)을 심는다. 봉인·sync 성공이 40일 넘게 없으면
  `/v1/ops/datasets`가 overdue로 보인다. 운영자가 이미 정한 값은 바꾸지 않는다.

### 3a-3. 역지오코딩 불가 행을 기억한다 (델타 리뷰 MED-1·MED-2의 공통 원인)

해상·매립지·잘못된 TM 좌표처럼 **정상 geo에서도 늘 빈 답**인 행은 적재되지 않으므로 매 run 다시 조회된다.
정상 상태에서는 그 행들이 조회 창과 비율을 지배해, 건강한 업종이 매달 degraded가 되고 다시는 봉인되지
않는다. 그래서 그런 행을 기억한다.

- **표식**: 빈 답을 받은 행의 표식은 **run 끝에 한 번** 쓴다. 쓰는 것은 그 업종이 degraded가 아니고, run
  전체도 degraded가 아니며, 그 행이 문턱 초과(probe 통과) chunk에서 나온 것이 아닐 때뿐이다. 문턱을 넘었는데
  probe가 통과했다면 지역 장애와 구별할 수 없고, degraded 업종은 정의상 장애 의심이다 — 그 행에 표식을 남기면
  다음 run이 그 행을 보지 않아 degraded가 사라지고 봉인·sync 성공이 남아 overdue도 울리지 않는다(최종 리뷰
  MED-1). 그런 행은 표식 없이 매 run 다시 조회되므로 geo가 회복될 때까지 degraded가 지속된다.
  run 전체 비율은 다른 업종이 이미 degraded여도 **언제나** 잰다. 그리고 무엇이든 degraded면 조회 행이
  표본(50행)에 못 미쳐 스스로 판정받지 못한 업종에도 표식을 쓰지 않는다 — 큰 업종 하나를 degraded로 만든
  지역 장애가 작은 업종들에도 빈 답을 남겼을 수 있다(narrow 리뷰 MED-1). 연속 degraded 판정은 최근
  500개 run 안에서 직전 완료 run에 닿지 못하면 degraded로 본다(닫힌 쪽, L-3). 다시 풀린 표식 닫기 실패는
  무해하게 경고만 남기되 `transaction_destroyed`면 올린다(L-1).
  표식은 `ops.data_integrity_violations`의 finding 하나다 — `violation_type=mois_reverse_geocode_unresolvable`,
  `severity=info`, dedupe key는 `make_integrity_finding_key(provider, dataset, license_place, slug::mng_no,
  그 type)`, `payload.source_record_key`에 현재 payload의 source record key를 싣는다(payload hash에서
  파생된다). 이미 있으면 upsert가 `last_seen_at`과 payload를 전진시킨다. 표식 기록 실패는 무해하게 경고만
  남기지만, 결합된 transaction까지 되감은 실패(`transaction_destroyed`)는 그대로 올린다(etl과 같은 규칙).
- **다음 run**: 같은 dedupe key의 **열린**(open/acknowledged) 표식이 있고 `payload.source_record_key`가
  현재 payload와 같고 `last_seen_at`이 30일(`UNRESOLVABLE_MARKER_RETRY_DAYS`) 안이면 "알려진 불가 행"이다 —
  조회하지 않고, 조회 창·비율에 넣지 않고, 적재하지도 않는다(`mois_known_unresolvable`로 센다). payload가
  바뀌면 key가 맞지 않아 저절로 다시 조회한다. 30일이 지나면 다시 조회해 geo 데이터 갱신을 반영한다 —
  여전히 빈 답이면 표식이 전진한다. 다시 조회해 **풀리면** 그 행의 열린 표식을 `resolved`로 닫는다 — 열린
  표식이 끝없이 쌓이지 않는다. 운영자가 finding을 닫으면(`resolved`) 다음 run이 다시 조회한다.
- **저장소 선택**: 새 표를 만들지 않고 finding 표를 재사용했다. 필요한 것(엔티티 단위 dedupe key, 열린
  표식 unique 인덱스 `uq_violations_open_dedupe_key`, 관측 시각 `last_seen_at`, payload jsonb, runtime
  쓰기 경로 `record_address_validation_findings`)이 모두 있고, 표식이 `/admin/issues`에 정보 수준 이슈로
  보이는 것이 오히려 운영에 맞다(어느 좌표가 왜 빠지는지). 대가: 표식 수만큼 issue 행이 늘고, finding 정리
  정책이 표식 수명에 영향을 준다(닫으면 재조회 — 안전한 방향).
- **남는 위험·대가**: 문턱을 넘을 만큼 **몰려 있는** 정상 해상 좌표(섬 지자체 행이 `mng_no`로 모인 경우)는
  지역 장애와 구별할 수 없어 표식이 되지 않고 매 run 다시 조회된다. 비율 상한(조회 대비 5%) 아래면 봉인을
  막지 않는다. 위면 그 업종은 매번 degraded이고 두 번째부터 붉다 — 그때는 사람이 좌표를 확인한다(geo
  데이터 문제인지 원천 좌표 문제인지). 낮은 밀도로 흩어진 해상 좌표는 표식이 되어 30일마다 한 번 조회된다.
  거꾸로, probe 문턱을 넘지 않고 어느 업종·run에서도 5% 아래인 지역 장애는 정상 해상 좌표와 구별되지
  않으므로 **여전히 표식이 되어 최대 30일 조회되지 않는다** — 그 행들은 30일 뒤 재조회되거나 finding을
  닫으면 다음 run에 돌아온다. 이것이 5% 상한이 받아들이는 대가다.

### 3b. 재관측 충돌은 run 안에서 그 chunk만 다시 (적대 리뷰 MED-2)

확인과 기록 사이에 dedup·관리자 변경이 끼면 `ProviderEntityReobservationConflict`로 chunk가 통째로
되돌아간다. 적재기는 그 chunk만 다시 확인·변환·적재한다(최대 2회, 지오코딩은 run 캐시에서 나온다).
그래도 충돌하면 run이 실패한다.

### 4. 완료와 봉인

**선택 업종을 한 run 안에서 끝까지 본 run**만 `complete`다. 그것이 PROMOTED 전 업종이고 본
record가 1건 이상이면 그 run은 snapshot의 모든 행을 확인한 것이므로(건너뛴 행도 "그대로
있다"를 확인했다) 빈 transaction에서 curation seal을 읽어 membership을 authoritative로 닫고
provider sync 성공을 남긴다. 부분 run·업종 선택 run은 non-authoritative로 닫고 sync 성공을
남기지 않는다. 매 run은 앞 업종을 다시 훑지만 건너뛰기 질의뿐이라 짧다.

미관측 finding의 stale close는 **하지 않는다.** 건너뛴 행은 다시 검증하지 않으므로 "이번 run이
보지 못했다"가 "고쳐졌다"를 뜻하지 않는다.

### 5. 큐 경로는 MOIS를 실행하지 않고, 그 사실을 숨기지 않는다 (적대 리뷰 MED-4)

정본은 `kortravelmap.core.feature_operation.DEDICATED_JOB_ONLY_OPERATION_KEYS` 하나다. MOIS 적재는
전용 job(schedule·sensor·수동 launch)만 한다. 큐 요청은 셋으로 갈린다.

- **접수 시 MOIS뿐인 계획**: `POST /v1/ops/pipeline/requests`가 **409 `PROVIDER_DEDICATED_JOB_ONLY`**
  (`details.dagster_jobs`에 전용 job 이름)로 거부한다. 받아 두고 건너뛰면 "접수됐는데 아무것도
  갱신하지 않은" 요청이 된다.
- **섞인 계획**: 받는다. 실행 계획이 MOIS 부분을 `skipped_provider_scopes[].reason=dedicated_job_only`로
  빼고, 나머지를 실행한 뒤 request를 `done`으로 닫으면서 **job `error_message`에** 건너뛴
  dataset·전용 job을 적는다 — `done`이 전부 갱신됐다는 뜻으로 읽히지 않게. 접수 때의 plan 선행조건은
  큐가 실제로 실행할 membership에만 건다. 생성 route는 MOIS source sync precheck를 더 부르지 않고 그
  helper(`ensure_mois_source_sync_*`·`MOIS_SOURCE_PRECHECK_ERROR_RESPONSES`·`MoisSourceSyncRequired`)와 테스트를
  걷어냈다. 그 선행조건은 큐가 MOIS 원천을 읽을 때만 의미가 있는데, 카탈로그(seed)의 MOIS refresh operation
  넷 중 `feature_place_mois_licenses_job`은 전용 job 전용이고 나머지 셋(`mois_license_incremental_update`·
  `mois_license_closed_update`·`mois_license_detail_update`)은 큐 handler가 없어 실행 단계에서 실패한다.
  운영 화면의 MOIS source sync 안내(`/v1/ops/pipeline/prechecks/mois-source-sync`)는 그대로다.
- **skip 사유 순서**: 운영자가 끈 dataset(`policy_disabled`)은 그 사유가 먼저다. policy만으로 비운 계획은
  종전처럼 `done`이다. 실행된 scope가 없고 건너뛴 것에 `dedicated_job_only`가 **하나라도** 있으면 실패다 —
  그 부분은 요청자가 갱신을 기대했으므로 PinVi target을 갱신됐다고 보고하면 안 된다.
- **실행할 것이 MOIS뿐인 요청**(PinVi cache target refresh처럼 enqueue 거부를 거치지 않는 경로 포함):
  기존 실패 어휘로 끝낸다 — request `failed` + error_message, cache target status event `failed` +
  `error_code=PROVIDER_DEDICATED_JOB_ONLY`, target `last_failed_at` 갱신. 새 상태값을 만들지 않았다.
  PinVi는 이미 `failed`를 다루므로 "조용히 갱신 안 됨"이 남지 않는다. 그 target의 MOIS feature는
  전용 job이 적재·갱신한다.

Dagster 큐 runner의 skip은 방어선으로 남는다(정상 경로에서는 실행 계획이 먼저 뺀다).

### 6. 원천 SQLite는 영속 경로에

Dagster 이미지가 `/opt/dagster/state/mois`를 appuser 소유로 만들고
`KOR_TRAVEL_MAP_MOIS_SOURCE_DB_PATH=/opt/dagster/state/mois/mois_source.db`를 기본으로 둔다.
compose는 그 디렉터리에 named volume을 붙인다(새 named volume은 이미지 디렉터리의 소유자를
물려받으므로 appuser가 쓸 수 있다). 운영 compose는 Manager 저장소의 짝 변경이 붙인다.

## 결과

- 장애 지점 하나가 전부를 되감지 않는다. 진행은 행 자체로 보인다(commit된 chunk).
- 최악 추정(전 행 역지오코딩, 동시성 2, geo 130ms): 지오코딩 약 18시간 + DB 적재 —
  run 4시간 × 5~8회, sensor로 이어 달려 약 1~2일. 이후 월간 갱신은 바뀐 행만이다. 원천이
  `legal_dong_code`를 주는 비율만큼 지오코딩이 줄어든다(검증 run이 그 비율을 잰다).
- 잃는 것: MOIS finding의 자동 stale close. 큐(PinVi cache target·admin dataset refresh)로
  MOIS를 갱신하는 길.
- 그대로인 것: 폐업/snapshot 부재 행 retire는 종전 Dagster 경로에도 없었다(열린 결정).

## 열린 결정 (소유자)

1. 이어 달리기 sensor를 켜는 시점 — 검증 run 뒤 첫 전체 적재 때.
2. Phase B freshness TTL(`KOR_TRAVEL_MAP_MOIS_SOURCE_SYNC_TTL_HOURS`, 기본 24h). 캠페인 중
   run이 Phase A를 다시 받지 않게 운영 값으로 168h 이상을 권한다(주간 sync job이 갱신한다).
3. snapshot에서 사라진(폐업) MOIS feature retire — 지금도 하지 않는다. 완료 run에 붙일지.
4. 큐로 오던 MOIS 요청은 지금 409(접수)·`failed`(cache target)로 드러난다. 이를 전용 job launch로
   자동 전환할지.
5. 동시성 기본 2와 상한 4시간 — 검증 run의 geo 지연·n150 IO 압력을 보고 조정.
6. 재관측 쓰기 비용 — 새 원천 snapshot(주 1회)마다 미변경 행 전부의 head `observed_at`·entity
   `last_seen_at`을 한 번 갱신한다(약 98만 × 2행). `load_bundle`의 재관측 의미를 지키기 위한 것이고 같은
   snapshot 재실행은 쓰지 않는다. n150 디스크 대기가 문제면 "관측 시각을 전진시키지 않는다"로 바꿀 수 있다
   (그러면 MOIS의 last-seen은 첫 적재 시각에 머문다).
