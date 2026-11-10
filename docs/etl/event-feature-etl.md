# event-feature-etl.md — TourAPI 축제·공연·행사 ETL

축제/행사 데이터를 `event` Feature로 정규화하는 ETL이다. 국가유산 행사(`krheritage_event_list`)는
`docs/etl/krheritage-feature-etl.md`가 다룬다.

## 0. 결정 (2026-11-10, 소유자) — 구 ADR-042 축제 부분 대체

> "datagokr 축제데이터는 로드 끄고 다른 소스 쓰자." → "datagokr 축제 소스는 아예 쓰지마."

- **축제 원천은 TourAPI(KorService2 `searchFestival2`, contentTypeId 15) 하나다.** 그 적재가
  1차 `event` Feature를 만든다.
- data.go.kr 전국문화축제표준데이터(`tn_pubr_public_cltur_fstvl_api`, dataset
  `datagokr_cultural_festivals`)는 **쓰지 않는다**. 키가 403
  `SERVICE_KEY_IS_NOT_REGISTERED_ERROR`(마지막 성공 2026-10-31)이 된 뒤 소유자가 원천을 바꾸기로
  했다. 코드(변환기·fetcher·asset·job·schedule·큐 spec·handler·preview fixture)를 지웠고,
  migration 447이 카탈로그 operation을 끄고 dataset을 비활성으로 내렸다.
- 종전 구조(구 ADR-042, 2026-05-27): 표준데이터가 1차, TourAPI는 표준데이터 축제에 **이름으로**
  붙는 2차 enrichment(`visitkorea_festival_events`, `feature_event_visitkorea_enrichment_job`)였다.
  그 enrichment도 함께 퇴역했다 — 붙일 1차가 없다. 이름 매처·검토 분류 코드도 지웠다.
- 기존 표준데이터 축제 Feature(2026-11-10 prod 1,296건)는 **병합하지 않고 퇴역**한다(447,
  `transition_kind=system`, reason `festival_source_moved_to_tourapi`). "그 원천을 쓰지 않는다"이므로
  표준데이터 값(본문·주관기관)을 TourAPI Feature로 옮기지도 않는다. TourAPI 쪽 같은 축제는 새 적재가
  자기 Feature로 만든다(이름이 맞는 행 314/1,296).
- PinVi 참조(같은 날 읽기 전용 실측): `trip_day_pois` 45행은 전부 고정 시험 계정의 삭제·보관된
  여행이고 `curated_plan_pois` 0행, `weather_location_links` 33행은 지점 캐시다 — 살아 있는 참조가
  0이라 M05 rebind/detach 사건을 남기지 않는다. 퇴역 id는 PinVi에서 `retired`/404 +
  `feature_snapshot` 대체 표시가 된다.
- 공개 축제 API(`/v1/public/festivals/*`, PinVi 월별 축제)는 **계약이 그대로다** — 술어가
  `event_kind IN ('festival','cultural_festival')`이고 TourAPI 행도 `festival`이다. 응답 필드 중
  표준데이터에만 있던 것(`auspc_instt_name`·`suprt_instt_name`·`reference_date`·`organizer_name`·
  `provider_org_name`)은 null이 된다(원래 nullable). OpenAPI 변경 없음.

## 1. 문서 정보

| 항목 | 값 |
|------|----|
| provider | `python-visitkorea-api` |
| dataset_key | `visitkorea_festivals` (migration 447) |
| Feature.kind | `event` |
| source_entity_type | `festival` |
| source_role | `primary` |
| natural key | TourAPI `contentid` |
| 상세 테이블 | `feature_events` |
| 코드 entrypoint | `kortravelmap.providers.visitkorea.tourapi_festivals_to_bundles` |
| fetcher | `kortravelmap.dagster.provider_fetchers.fetch_visitkorea_festivals` |
| asset / job | `feature_event_visitkorea_festivals` / `feature_event_visitkorea_festivals_job` |
| schedule | `feature_event_visitkorea_festivals_daily_schedule` `35 4 * * *` (관광지 04:45보다 먼저) |
| 갱신 | 매일, `retire_absent_from_snapshot` |

## 2. 수집 창

`searchFestival2`의 `eventStartDate`는 **그날 이후에 끝나는** 행사를 준다(2026-11-10 실측:
`20251101`로 879건, 그 전에 시작해 진행 중인 2건 포함, 종료일이 창 앞인 행 0). 창 시작은
`festival_window_start(today)` = **한 해 전 그달 1일**(KST)이다 — 공개 축제 API가 요청 달과 앞뒤
한 달을 세므로 지난 한 해를 덮는다. 창에서 밀려나거나 원천 목록에서 빠진 행사는 다음 적재에서
**부재 퇴역**한다. TourAPI는 지난 행사를 오래 두지 않는다(실측 2026-01~03 시작분 48건) — 지난 달의
월별 축제는 표준데이터 시절보다 적다(소유자 결정의 비용).

목록은 1,000행 페이지라 한 sweep이 1호출이다. 은퇴 적재이므로 목록이 완전해야 한다:
`totalCount` 부재·순회 중 선언 변화·빈 목록·고유 contentid < 선언이면
`VisitKoreaFestivalSnapshotIncomplete`로 실패한다(관광지 fetcher와 같은 규칙). 0행이면 asset도
은퇴 전에 실패한다.

## 3. 매핑

| TourItem 필드 | Map |
|---|---|
| `title` | `Feature.name` (정규화 후 비면 skip) |
| `event_start_date`·`event_end_date` (YYYYMMDD) | `EventDetail.starts_on`·`ends_on`. 읽을 수 없거나 역전이면 둘 다 None → 격리 |
| `addr1` + `addr2` | `EventDetail.venue_name`(원천 개최지 주소 — 목록에는 `eventplace`가 없다), `addr1`은 도로명/지번으로 `Address` |
| `map_x`·`map_y` | `Feature.coord`(WGS84, 실측 879/879). 역지오코딩으로 법정동 |
| `l_dong_regn_cd`·`l_dong_signgu_cd` | geo 실패 때만 시군구 fallback |
| `tel` | `EventDetail.tel` |
| `content_id`·`content_type_id` | `EventDetail.content_id`·`content_type_id` |
| `lcls_systm2/3` (EV01 축제·EV02 공연·EV03 행사) | `EventDetail.payload` |
| `overview` (`detailCommon2`) | `EventDetail.payload['content']`(태그 제거) — 공개 view `festival_content` |
| `homepage` (`detailCommon2`) | `Feature.urls.homepage` |
| `first_image`·`first_image2` | `FeatureFileSource`(원본 참조, 공공누리 유형 payload) |

- category는 전부 `01090000` 축제·행사, `event_kind='festival'`, marker `star`/`P-11`(종전과 같은 표시).
- `raw_data` 키는 `TourItem` 필드 이름 그대로다 — replay(`source_mode=replay`)가
  `visitkorea_tour_item_from_raw`로 되살린다.

## 4. 상세 예산 — `detailCommon2`는 관광지와 나눠 쓴다

data.go.kr 한도는 **오퍼레이션마다** 걸린다(`docs/etl/upstream-quota.md`). 관광지(12·14·28)와 축제가
같은 `detailCommon2`를 쓰므로 run 예산을 나눈다.

| 상수 (`dagster/assets.py`) | 값 |
|---|---|
| `VISITKOREA_DETAIL_DAILY_BUDGET` | 900 (오퍼레이션 일일 한도 1,000 − 수동 몫 100) |
| `VISITKOREA_ATTRACTION_DETAIL_BUDGET` | 600 |
| `VISITKOREA_FESTIVAL_DETAIL_BUDGET` | 300 |

합이 900 이하인 것은 테스트가 고정한다. 저장 `raw_data`의 `modified_time`이 목록과 같으면 저장 상세를
이어 쓰고(재요청 없음), 수정된 행을 먼저 받는다(`plan_attraction_details` 재사용). 창 안 879건은 첫
사흘이면 상세가 다 찬다. step 재시도는 상세를 받지 않는다. 목록(`searchFestival2`)은 별도
오퍼레이션이라 이 예산과 무관하다.

## 5. dedup

- 국가유산 행사(`heritage_event`, #1473)와의 쌍 규칙은 두지 않는다 — 2026-11-10 실측에서 TourAPI
  축제 879건과 active 국가유산 행사 사이에 이름이 맞는 쌍이 실질적으로 없었다(§7 참조). 공개 축제
  API는 `heritage_event`를 고르지 않으므로 한 화면에 겹쳐 보이지도 않는다.
- 표준데이터 축제 전용 pair·우선순위 항목은 원래 없었다. `data.go.kr-standard` provider 우선순위(35)는
  박물관·관광지·주차장·전통시장이 계속 쓴다.

## 6. 운영 (배포 뒤)

1. 배포(=migration 447 적용) 직후 preview: `POST /v1/ops/datasets/{id}/preview`
   (`visitkorea_festivals`의 `feature_event_visitkorea_festivals_job.preview`, fixture — 외부 호출 0).
2. 실제 적재: `feature_event_visitkorea_festivals_job` 1회(큐 또는 Dagster). 기대: 목록 1호출, 상세
   ≤300호출, Feature 약 880 생성(대부분 `valid`, 주소 없는 행만 격리).
3. 다음 날부터 schedule이 매일 돈다. 표준데이터 축제 job·보강 job은 카탈로그에서 꺼져 큐·schedule
   어디에서도 실행되지 않는다(Manager env 변경 없음).

## 7. 검증 기록

- 2026-11-10 `searchFestival2` `eventStartDate=20251101`: 879건, contentTypeId 15 전부, 좌표 879,
  법정동 시도·시군구 879, 이미지 873, 날짜 결측 0, 역전 0. lclsSystm2 EV01 527·EV03 269·EV02 83.
- 표준데이터 축제(prod): active 1,296(좌표 없음 240, 종료 1,245, 진행·예정 49).

## #1439 행사 품질 경계

시작·종료일과 행사장 이름이 없거나 기간이 역전되면 새 행을 `quarantined`로 생성한다. 날짜를 수집
연도나 주소로 만들어 채우지 않는다. 종료된 정상 행사는 격리하지 않는다.

중복 후보는 행사 기간·장소를 이름 점수보다 먼저 비교한다. 다른 회차는 제외하고, 근거가 부족하면 자동
병합 제안을 수동 검토로 낮춘다. 실제 병합도 Feature 부모 잠금 뒤 typed 행사 행을 다시 잠가 비교하므로
오래된 검토 큐나 명시 master 요청이 다른 회차를 우회 병합할 수 없다. 날짜 불명 행사의 명시적 수동
판단은 허용한다.

기존 행은 현재 primary 원문을 재관측할 때 최종 표시 정보(관리자 override 포함)를 검사한다. 필수 정보가
비어 있는 `valid` 행만 기존 provider state procedure로 격리한다. 이미 격리된 행을 자동 해제하지 않으며
관리자 격리의 사유·감사도 덮지 않는다.

KHA의 `sn` 없는 legacy fallback 키에는 종료일이 없다. 이 키는 보존하되, 같은 키로 확정된 다른 기간·
장소가 들어오면 field patch 전에 명시적인 identity 충돌로 수집을 거부한다(load rollback). 회차 충돌은
같은 source entity 소유의 provider base 기간·장소와 비교한다.
