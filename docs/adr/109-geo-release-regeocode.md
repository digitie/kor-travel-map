# ADR-109 — geo 주소 데이터셋 릴리스는 데이터 토큰으로 감지하고, 적재 경로를 재사용해 다시 지오코딩한다

- 상태: proposed (설계 2026-10-13, 2차 적대 리뷰 반영. **미구현** — 구현 task는 `T-GR-01`~`T-GR-08`,
  아래 "열린 결정"은 소유자 판단 대기)
- 날짜: 2026-10-13
- 결정자: human(승인 대기), Claude
- 관계: **kor-travel-geo ADR-069**(데이터 토큰 `dd1-` = 서빙 내용 지문, 네 v2 응답의 `dataset` 필드 —
  geo 저장소의 ADR이며 본 저장소의 ADR-069와 다르다), ADR-080(finding generation), ADR-081(cache target
  generation), ADR-098(provider identity는 claim), ADR-106(transport export), ADR-108(MOIS 재개형 적재 —
  본 ADR이 표식 조건·재시도 규칙·이어 달리기를 amend한다)
- amended by: **ADR-110**(proposed, 2026-10-13) — `GEO_HEAVY_POOL` 유지 근거('n150 디스크 대기' → 'odroid geo CPU
  보호')와 geo 호스트 플립(odroid 풀로드) 직후 센서가 만드는 전량 재계획 비용·센서/재지오코딩의 LAN 키 경로. 본 ADR의
  결정 자체는 바뀌지 않는다. 2026-10-15 갱신: geo 플립은 2026-10-14~15 실행됐고 본 ADR의 센서(T-GR-05)가 미배포라
  전량 재계획은 생기지 않았다(ADR-110 "사실 갱신 (2026-10-15)" 절 5항 (ㄹ)). **소유자 결정(2026-10-15)**: geo `data_token`이 '없음'에서 첫
  토큰으로 바뀌는 것(n150 geo는 토큰이 없었고 odroid dump 복원 뒤 처음 생겼다)은 **기준선**이지 재계획 사유가 아니다 —
  감지 규칙(결정 5)에 이 분기를 더하는 것은 T-GR-04/05 구현 몫이다.
- 코딩용 상세(표·판정 표·run_key·테스트 목록): [`docs/etl/address-geocoding.md`](../etl/address-geocoding.md)

## 컨텍스트

Map은 kor-travel-geo가 유도한 값을 저장한다 — `feature.features`의 `address` jsonb·`legal_dong_code`·
`road_name_code`·`road_address_management_no`·`admin_dong_code`·`sido_code`·`sigungu_code`
(`src/kortravelmap/infra/models.py:408-419`). 그런데 **어느 geo 데이터로 해석됐는지는 어디에도 없다.**
geo가 주소 DB를 새 릴리스로 바꿔도 Map은 알지 못하고, 알아도 다시 맞출 길이 없다.

1. **unchanged는 다시 쓰지 않는다.** `load_bundle`은 `became_current or feature_missing`일 때만
   `upsert_feature`를 부른다(`src/kortravelmap/infra/feature_repo.py:3085-3095`). 비-MOIS 변환기는 좌표가
   있으면 payload 변경과 무관하게 reverse를 부르지만(`providers/knps.py:284-285` 패턴) 그 결과는 payload가
   같으면 버려진다. MOIS는 payload hash가 같은 행의 변환·지오코딩 자체를 건너뛴다
   (`feature_repo.py:3199-3231` `_UNCHANGED_ACTIVE_ENTITIES_CTE`, ADR-108 §1).
2. **prod는 cron이 아니라 큐로 돈다.** 모든 feature load schedule이 STOPPED라 "다음 적재가 고친다"는
   자동으로 일어나지 않는다(memory `map-prod-runs-on-the-queue-not-cron`).
3. **geo의 `version_token`은 데이터의 함수가 아니다.** 릴리스 행마다 바뀌어 같은 데이터의 재빌드도
   "변경"으로 읽힌다 — 소비자가 그것으로 전량 재처리를 돌리면 헛돈다. geo ADR-069가 서빙 내용 지문
   `data_token`(`dd1-` + 32 hex)을 네 v2 응답과 `POST /v2/dataset/version`에 실어 이를 푼다(geo 측,
   proposed).
4. **값이 안 바뀐 재해석이 `row_revision`을 흔들면 안 된다.** 프로시저 `apply_provider_feature_field_patch`
   (`alembic/head-schema.sql:677`)는 값이 같아도 `row_revision + 1`이다(`:738`). `row_revision`은 ETag·`If-Match`
   412·curation seal·PinVi cache target generation의 입력이다.
5. **좌표가 있다고 geo를 쓴 것이 아니다.** `feature_price_transport_fuel_stations`·`…_rest_areas`는 transport
   좌표를 그대로 싣고 reverse를 부르지 않으며(`dagster/assets.py:410-432`, `:533-`), `feature_notice_transport_highway_incidents`는
   `reverse_geocoder=None`이다(`assets.py:643`). MOIS는 payload에 `legal_dong_code`가 있으면 reverse를
   부르지 않고(`providers/mois.py:716-720`), reverse가 비면 `/v2/geocode`(`address_resolver`)로 간다
   (`mois.py:721-730`; `standard_data.py:294-299`, `dagster/offline_uploads.py:62-63`도 같은 꼴).
6. **큐 runner는 dataset 전체를 transaction 하나로 묶고 pool을 claim하지 않는다**
   (`dagster/feature_update_runner.py:490-518`; `GEO_HEAVY_POOL`은 asset 경로만, `assets.py:184`). 모든
   feature 쓰기는 전역 advisory xact lock `lock_feature_curation_write`를 지난다(`feature_repo.py:146-156`).

## 결정

### 1. 지오코딩 스탬프는 별도 표다 — `feature.feature_geocode_stamps`

행마다 `(geo_version_token, geo_data_token, reverse_outcome, stamped_at)`를 `features`와 **분리된 표**에 둔다
(migration `407_feature_geocode_stamps`, `feature_id uuid PK FK ON DELETE CASCADE`, `OWNER TO
ktm_feature_schema_owner`, `SET ROLE` 아래 DDL·RESET ROLE 없음). `features` 컬럼이나 `address` jsonb 키로
두면 스탬프 갱신이 `row_revision`을 전진시킨다(컨텍스트 4). 표 1개·마이그레이션 1개가 그 대가다.

`reverse_outcome`은 **세 값**이다.

| 값 | 뜻 | 토큰 비교 |
|---|---|---|
| `called` | 좌표로 reverse를 불렀다 — geo가 이 행의 주소에 기여했다(빈 답이어도 시도가 있으면 여기; 그 행은 결정 4의 빈 답 가드가 막는다) | 대상 |
| `geocoded` | 좌표가 없어 reverse 없이 주소 문자열 `address_resolver`(`/v2/geocode`, VWorld fallback 포함)로 코드를 받았다 | 대상 |
| `not_called` | provider 코드만 썼고 geo 유도 값이 0개다(MOIS payload-bjd 행, 좌표 없는 concierge payload 코드 행, 좌표·주소 둘 다 없는 행, 좌표 없이 geocode를 시도했으나 코드를 못 받은 행) | **대상 아님** |

VWorld fallback으로 받은 코드는 로컬 데이터셋의 함수가 아니지만 `Address` DTO로는 출처를 구별할 수 없으므로
`geocoded`로 두고 릴리스마다 다시 geocode한다(안전 방향, DTO 불변). geo HTTP 실패는 예외로 올라가 run이
죽는 run 단위 사건이므로 행 단위 "unavailable" 스탬프는 없다. **NULL 토큰 스탬프는 만들지 않는다** — 두 토큰
열은 `NOT NULL`이고, run의 현재 토큰이 없으면(결정 2) 스탬프를 쓰지도 덮지도 않는다. **스탬프 부재가 stale**이다.
좌표 없이 geocode를 시도해 실패한 행은 `not_called`로 두고 릴리스 재해석 대상에서 뺀다(④의 결과 기준과 ②를
같게 맞춘 것 — 열린 결정 1과 같은 부류).

### 2. 현재 토큰은 run 단위다 — 행 단위 토큰은 포기한다

행마다 응답 `dataset`을 bundle까지 실으려면 `ReverseGeocoder` 콜백 타입(`src/kortravelmap/geocoding.py:201`)·
`ReverseGeocodeObservation`·`FeatureBundle`·`reverse_geocoder=`를 받는 provider 모듈 12개를 전부 바꿔야
한다 — 이 트랙 최대의 숨은 범위다. 대신 run 시작에 `POST /v2/dataset/version`을 **한 번** 읽어
`DatasetRef{version_token, data_token | None}`을 run-scoped "현재 토큰"으로 쓴다(Dagster resource
`kor_travel_geo_dataset`; 큐 runner·offline upload·CLI도 같은 팩토리). 실패·`available=false`면 `None`
+ 경고 1건이고 run은 **계속**된다 — `None`이면 stale 분기가 꺼져 오늘의 unchanged 판정과 **동일**해진다
(fail-to-current; geo 장애가 전량 재변환으로 번지지 않는다). **`DatasetRef`는 있는데 `data_token`만 None인
run**(지문 backfill 전·fail-open 창)도 같은 취급이다 — stale 분기 없음, 스탬프 쓰기·덮기 없음(결정 1). 그렇지
않으면 토큰 A로 찍힌 스탬프가 NULL로 덮여 지문 복구 뒤 전량 재변환이 돈다. 응답 본문의 `dataset`은 선택 파싱해
run-scoped 값과 다른 토큰이 관측되면 WARNING + op 메타 `geo_dataset_mismatch=true`만 남긴다 — 그 run의
스탬프는 옛 토큰이므로 다음 센서 tick이 다시 계획한다(안전 방향).

**현재 토큰은 첫 지오코딩 전에 읽는다(2026-10-16, #1327 최종 리뷰 — T-GR-03 구현).** run 도중 geo가 데이터셋을
바꿨을 때 옛 데이터로 해석한 행이 **새** 토큰으로 봉인되면 다시 계획되지 않는다(위험한 방향). 그래서 asset의
역지오코더는 처음 불릴 때 run-scoped handle을 먼저 읽고, MOIS·concierge는 run 시작에 읽는다. 덧붙여 응답에서 run
토큰과 다른 `data_token`을 보면 그 적재는 stale 분기·스탬프를 하지 않는다(`GeoLoadContext.effective_token()`) —
위의 "그 run의 스탬프는 옛 토큰"보다 한 걸음 더 보수적이다(스탬프 없음 = stale이라 다음 계획이 고른다).

`DatasetRef`·`GeoApplied`는 **`src/kortravelmap/dto/geo_dataset.py`**에 둔다. `infra`가 import하므로
`geocoding` 층에 두면 `infra → geocoding` 역행이다(`CLAUDE.md` §5 4항, `lint-imports`).

### 3. outcome은 호출자의 run 신호로 정한다 — 좌표 유무가 아니다

`load_feature_bundles(bundles, *, current_dataset, geo_applied: GeoApplied{reverse, geocode})`로 호출자가
"이 run이 `reverse_geocoder=`/`address_resolver=`를 실제로 넘겼는가"를 넘긴다(컨텍스트 5). 행 규칙은
**순서가 규칙이다** — 처음 맞는 것이 답이다: ① `geo_applied` 둘 다 False인 run(price/notice)은 **스탬프를
쓰지 않는다**; ② MOIS는 **행별** 변환 evidence로 outcome을 정하고 chunk commit 안에서 bulk upsert한다(구현은
모든 적재 경로의 `load_bundles`가 chunk 단위다 — stale 판정·저장값 읽기 각 한 문장, 스탬프 한 문장)
(`AdminEvidence.reverse_attempted`(`dto/admin_evidence.py:102`, `mois.py:817`) → `called`, 아니고 geocode로
`bjd_code`를 **받았으면**(`GeoAttemptEvidence.geocode_obtained_code`, T-GR-01) → `geocoded`, 그 외 `not_called` —
④와 같은 결과 기준; '받았다'가 '시도했다'를 함의하므로 시도 여부 필드는 두지 않는다);
③ `reverse and coord IS NOT NULL → called`(payload 코드를 썼어도 — geo가 빈칸을 채웠으므로
비교 대상); ④ `geocode and coord IS NULL and legal_dong_code IS NOT NULL and provider 코드 없음 → geocoded`;
⑤ 그 외 `not_called`. 좌표가 있고 reverse가 비어 geocode로 코드를 받은 행은 ③에서 `called`다 — 둘 다 토큰
비교 대상이라 stale 판정은 같고, ②의 "reverse 시도가 있으면 `called`"와 같은 규칙이다. "provider 코드 있음"은
bundle의 source_record payload에 `legal_dong_code`가 있는가로 본다. Dagster asset·큐 runner는 어느 것도
`address_resolver=`를 넘기지 않으므로(`dagster/assets.py` 0건) 그 경로의 `geocode`는 MOIS를 포함해 전부 False이고
`geocoded`는 offline upload·CLI(`offline_uploads.py:62-63`, `cli/main.py:557-558`)에서만 난다. provider 변환
**로직** 변경은 `mois.py` evidence 1필드와 결정 6의 `kor_travel_concierge.py` 2곳이고, 공개 시그니처 변경은 concierge
1개뿐이다 — `kor_travel_concierge_items_to_bundles(…, current_data_token: str | None = None)`(`:125-131`, additive
kwarg·기본 None = 옛 동작)를 유일한 호출처 `dagster/assets.py:1508`이 `kor_travel_geo_dataset` resource의
`data_token`으로 채우고 `_item_to_bundle` → `_address`로 전파한다(결정 6(a)의 비교값).

**geo 의존 여부의 런타임 정본은 core 상수다.** `src/kortravelmap/core/feature_operation.py`의
`GEO_DEPENDENT_OPERATION_KEYS`(`DEDICATED_JOB_ONLY_OPERATION_KEYS` `:33-41`과 같은 꼴)를 센서(Dagster 프로세스)와
`/detect`(API 프로세스 — `kortravelmap.dagster`를 import하지 않는다)가 같이 읽는다. 상수가 사실과 같다는 것은
`tests/lint/test_geo_heavy_assets_declare_the_pool.py`의 AST 유도와의 **집합 동등**으로 고정한다 — 런타임 AST
파싱도, `tests/` import도 없다. 현재 그 lint의 술어 `_passes_reverse_geocoder`(`:81-87`)는 `reverse_geocoder`
키워드의 **존재**만 보고(`assets.py:643`의 `=None`도 포함), `_geo_heavy_assets()`(`:101-132`)는 asset **이름**을
돌려주며 run 함수와 `@asset`이 같은 모듈에 있을 때만 잇는다. pool 술어는 **그대로 두고**(pool 필요 집합과 geo 의존
집합은 다른 물음 — 과결박 회피) T-GR-04가 별도 술어 `_passes_geo_callable`(`reverse_geocoder=` 또는
`address_resolver=`에 `None` 상수가 아닌 값) + asset → `FEATURE_LOAD_SCHEDULE_SPECS.job_name` 매핑을 더해 동등을
단언한다. 새 geo 의존 operation이 상수 없이 생기면 lint가 빨갛다.

### 4. 재지오코딩은 "새 엔진"이 아니라 적재 경로의 unchanged-skip 보강이다

독립 재지오코딩 job(저장 행을 읽어 주소 필드를 직접 패치)은 기각한다 — provider별 코드 우선순위(MOIS
네이티브 우선, concierge payload 우선, knps 등 `Address` 전체, 코드만 취하는 provider)가 12 모듈에 있어
그것을 두 번째로 구현하는 것이고, 저장 값만으로는 `address` jsonb의 어느 필드가 geo 산물인지 복원할 수
없다. 비-provider feature(user_request·curation)용 **코드 전용** 변형만 열린 결정 2로 남긴다.

- **MOIS**(`_UNCHANGED_ACTIVE_ENTITIES_CTE`): `find_unchanged_active_source_entities(…, current_data_token)`
  인자를 더하고, 값이 있을 때만 `unchanged`에 "스탬프가 `not_called`이거나 `geo_data_token = current`"
  조건을 더한다. payload-bjd 행은 평소처럼 skip되고, 토큰 변경으로 다시 도는 행은 geo를 실제로 쓴
  행뿐이다. 스탬프가 **없는** 행은 unchanged가 아니다 → 롤아웃 뒤 첫 run이 전 행을 1회 변환해 스탬프를
  채운다(ADR-108 재개형 chunk로 흡수).
- **그 외 provider**(`load_bundle`): `stale = current.data_token is not None and outcome ∈ (called, geocoded)
  and (stamp is None or (stamp.outcome != not_called and stamp.geo_data_token IS DISTINCT FROM current))`.
  `became_current or feature_missing or stale`이면 적재 경로를 탄다. 비-MOIS는 unchanged에도 reverse를
  이미 돌리므로 추가 geo 비용은 0이다.
- **값 동일 시 무쓰기 — override 열은 비교에서 뺀다.** stale이지만 `became_current`가 아니면
  `get_feature_address_snapshot`(`infra/feature_address_repo.py:120`)으로 주소 유도 컬럼 **6개**(컨텍스트) +
  `address` jsonb를 비교한다 — 현재 `FeatureAddressSnapshot`(`:104-117`)은 `road_name_code`·`admin_dong_code`를
  담지 않으므로 T-GR-03이 두 열을 더한다(빠지면 그 열만 바뀐 행이 "값 동일"로 오판된다). **구현(T-GR-03)은
  `FeatureAddressSnapshot`을 넓히지 않고** 6열 + `address` + active override를 한 번에 읽는 전용 함수
  `read_stored_geo_columns`(`infra/feature_geocode_load.py`, chunk 판 `_many`)를 썼다. 비교에서
  `feature.has_active_feature_override(feature_id, 'core.<col>')`(정의 `head-schema.sql:5147`, patch의 masking
  호출 `:829-883`)가 참인 열은 **제외**한다 — 그 열은 patch가 어차피 건너뛰므로 비교에 넣으면 "항상 다름"이
  되어 값은 그대로인데 매 릴리스 `row_revision + 1`이다. 남은 열이 전부 같으면 features UPDATE를 생략하고
  스탬프만 upsert한다(ETag·seal·cache target 보호).
- **빈 답 가드.** 릴리스 직후 geo가 200에 빈 `candidates`를 돌려주는 부분장애에서 stale 분기가 주소 열을
  NULL로 덮고 현재 토큰으로 봉인하면 다음 릴리스까지 고정된다. `load_bundle`은 변환기 안의 reverse 결과를 보지
  못하고 `bundle.feature.address`만 보므로(`feature_repo.py:3035`) **판정 필드 집합이 곧 가드의 정확성**이다.
  집합은 모든 provider에서 **geo에서만** 오는 필드다: `address.sido_name/sigungu_name/admin_dong_code/road_name_code/zipcode`
  + `legal_dong_code`·`sigungu_code`(단 bundle의 source_record payload에 코드가 있는 provider 행은 두 코드 열 제외).
  `address.road/legal/admin`은 krheritage(`krheritage.py:483`)·standard_data(`standard_data.py:296-297`)·concierge
  (`kor_travel_concierge.py:548`)·khoa·krairport·mcst가 provider 원문으로 채우므로 **넣지 않는다** — 넣으면 그
  provider에서 가드가 영구히 발화하지 않는다. 행 규칙: 저장된 그 집합에 non-NULL이 있는데 새 bundle의 같은 집합이
  전부 None이면 features UPDATE·스탬프 모두 쓰지 않고 `reverse_geocode_failed` finding 1건만 남긴다
  (`became_current`인 행도 주소 열만은 보존하고 나머지 패치만 적용). run 규칙: MOIS에만 있던
  `GEOCODE_RATIO_MIN_SAMPLE=50`·`geocode_degraded_ratio`(`dagster/mois_chunked_load.py:131, 663-678`)의
  **상수·비율 계산만** 공통 모듈로 올려 `dagster/etl.py:436-439` 공통 chunk 루프에서도 쓴다. 비-MOIS의 분자·분모는
  **한 곳**에서 잰다 — `GeoCallStats`(`geocoding.py:1112`)에 `empty[endpoint]`(응답이 예외 없이 끝났는데 `Address`
  None 또는 `bjd_code` None) 카운터를 더해 `ObservedReverseGeocoder`(`:1405`)가 기록하고, 공통 루프는 분모
  `calls['reverse']`·분자 `empty['reverse']`를 chunk 간 누적한다(현재 `GeoCallStats`는 `calls`/`failures`(전송
  실패)만 센다 `:1140-1146`; 좌표 없는 행은 분모에 들지 않는다). **구현(T-GR-03)에서 분자를 바꿨다** — endpoint 빈 답
  `empty['reverse']`가 아니라 **행 단위 최종 빈 답** `empty['reverse_result']`(region fallback까지 거친 최종 답이 비었을
  때)다. reverse가 늘 비고 fallback이 채우는 dataset(산악 centroid)이 정상 run에서 실패하지 않게. 행동은 호출처가 정한다 — 비-MOIS(공통 루프)는
  문턱을 넘으면 run을 **실패**로 끝내고(그 chunk의 스탬프는 commit 전이라 남지 않는다), MOIS는 자기 chunk
  루프에서 ADR-108 §3a-2의 **degraded(실패 아님)** 의미를 그대로 둔다(영구 정지를 다시 만들지 않는다; ADR-108은
  이 점에서 amend되지 않는다). 규칙이 둘이 아니라 행동이 둘이다 — 판정은 한 곳.
- **geo-release run 한정 timeout 1회 재시도(열린 결정 6 — 승인 전에는 적용하지 않는다).**
  `KorTravelGeoRestClient`는 건별 재시도가 없고(`geocoding.py`에 retry 경로 없음) ADR-108 §2는 선조회 실패 뒤
  실시간 1회만 허용한다. 전용 job run에서만 reverse timeout에 1회 재시도(backoff 1건)를 허용한다 — timeout 1건으로
  run 전체가 죽고 재실행이 dataset reverse 전량을 다시 부르기 때문이다. 판별자는 결정 5.4의 run 태그
  `kor_travel_map.geo_release_plan_id`다 — `kor_travel_map.trigger_kind=sensor`는 MOIS 이어 달리기 run에도 이미
  붙어 있어(`mois_chunked_load.py:1071-1075` `_CONTINUATION_TAGS`) 전용 run을 식별하지 못한다. ADR-108의 예외로 적는다.

**overrides**(`ops.feature_overrides`)는 사람의 결정이라 자동으로 바꾸지 않는다. 새 geo 값과 **다르면**
finding `address_override_geo_stale`(info, payload `{override_values, geo_values, geo_data_token}`)을
`(feature_id, geo_data_token)`로 dedupe해 남긴다 — 같은 토큰에서는 1건. 해소 수단은 기존 admin 이슈 액션
`apply_kor_travel_geo_address`(`packages/kor-travel-map-api/src/kortravelmap/api/routers/admin_issues.py:576`),
신규 액션 없음.

**MOIS 표식**(ADR-108 §3a-3): 표식 payload에 `geo_data_token`을 더하고 `_known_unresolvable`
(`mois_chunked_load.py:853-882`)이 `find_fresh_open_findings(expected_payload_fields={"geo_data_token": current})`
(신규 인자, `infra/integrity_violation_repo.py:399`)로 "알려진 불가" 조건에 토큰 일치를 더한다. `current`가
None이면 인자를 생략한다. 30일 만료는 backstop으로 유지한다.

### 5. 재처리 기동 = 릴리스 센서 → 전용 job RunRequest (큐가 아니다; 열린 결정 11)

`kor_travel_geo_release_sensor`(300 s, **`default_status=STOPPED`**(구현 T-GR-05 — 소유자 지시: odroid geo 스케줄을
mv_refresh 실측 뒤 켜고 Map 센서도 그 뒤에 켠다; 열린 결정 3의 권장안 RUNNING을 대체), `jobs=` `FEATURE_LOAD_SCHEDULE_SPECS`
(`dagster/schedules.py:208`)의 전 job)가 in-process client로 DB를 읽고 쓴다 — Map API를 호출하지 않는다
(큐 센서 `dagster/sensors.py:123-147`과 같은 패턴). 큐(`feature_update_requests`)를 쓰지 않는 이유: 큐 run은
dataset 단위 all-or-nothing 한 transaction이고 pool을 claim하지 않으며(컨텍스트 6) 재시도 때 reverse를 전량
다시 부른다.

1. **감지.** `dataset_version()` → `current`. HTTP 실패·`available=false` → `SkipReason`(커서 불변).
   **`data_token`이 None이면 계획을 만들지 않고 빨간 사유로 Skip한다**(geo 지문 backfill/복구 필요).
   `version_token` 대체 비교는 두지 않는다 — 그 계획은 결정 4의 `stale` 규칙상 행을 하나도 고르지 않아
   쿼터·시간만 쓴다. 커서 = 마지막으로 계획했거나 기준선으로 기록한 `data_token`; 같으면(재빌드) 계획 0건.
   **소유자 결정(2026-10-15) — 첫 토큰은 기준선이다.** 소비자가 `data_token`이 '없음'에서 **첫** 토큰으로
   바뀌는 것을 보면(커서가 비어 있다 — n150 geo는 토큰을 가진 적이 없고, odroid는 n150 dump 복원 뒤 처음
   토큰을 저장했다; ADR-110 "사실 갱신 (2026-10-15)" 절 5항 (ㄹ)) 그 토큰을 커서에 **기준선**으로 기록하고 계획을 만들지 않는다.
   재계획은 기준선 이후 토큰이 **바뀔 때**만이다. 스탬프 없는 행은 평소 적재가 채운다(결정 4 — 스탬프 부재 =
   stale은 적재 경로의 규칙이고 센서 계획의 근거가 아니다). 구현은 T-GR-04/05.
   **구현(T-GR-04)**: 기준선은 계획 표의 `state='baseline'` 행이다(항목 없음) — 센서 커서가 없는 `/detect`도 같은
   판단을 하게. 그 행이 **최신 행**일 때만 "계획 없음"이고, 그 뒤 다른 토큰 계획이 있었으면 일반 규칙(잔여 판정)을 탄다.
2. **계획 identity = `plan_id` surrogate + `(data_token, plan_seq)`.** 표 `ops.kor_travel_geo_releases`
   (+ `ops.kor_travel_geo_release_items`, migration `408_kor_travel_geo_releases`, owner role·receipt CHECK).
   같은 토큰에 `planned|running` 계획이 있으면 그것(부분 UNIQUE, 멱등); 없으면 `plan_seq = max+1` 새 행 —
   롤백·재활성화(A→B→A)에서 두 번째 A도 새 계획이 되어 다시 돈다. 계획을 만들지 않는 경우는 둘이다 —
   (가) **계획 표 전체의 최신 행이 이 토큰의 `done` 행**이면 잔여가 남았어도 계획하지 않는다(그 토큰은 이미 한
   사이클을 돌았고 남은 것은 `residual_stale`로 기록됐다 — 다시 돌리는 것은 운영자 `replan`이다; 이 규칙이
   없으면 감지·tick마다 MOIS·replay 쿼터를 다시 쓴다, #1331 리뷰). A→B→A의 두 번째 A는 B가 더 새 행이라
   여기 걸리지 않는다. (나) 이 토큰의 이전 행이 있고 `coverage(token, 비-skipped datasets).stamped_other +
   unstamped == 0`이면 계획하지 않되, **다른 토큰의 활성 계획을 먼저 `superseded`로 닫는다**(B 계획이 돌기 전에
   geo가 A로 롤백된 경우 — B가 활성으로 남지 않게). `replan`은 `plan_seq+1`의 새 행이고 **최신 관측 토큰의,
   기준선이 아닌 계획만** 허용한다(그 외 409). 진행 중 옛 계획은 `superseded`.
3. **항목 입력은 DB 정본이다.**(구현 T-GR-04: kind는 `refresh` — `feature_load` 행은 DB에 없고 job을 dataset에 결박하는
   kind가 `refresh`다. job 없는 operation은 `skipped(queue_only)`.) `provider_sync.provider_dataset_operations WHERE operation_kind='feature_load'
   AND is_enabled` ⋈ `provider_datasets.is_active`(`head-schema.sql:18458-18470`) → `(operation_key,
   provider_dataset_id)` 쌍(**항목 모양 — 구현 T-GR-04 결정**: 항목 1행 = Dagster run 1개다.
   `(operation_key, run_config)`가 같은 dataset은 `provider_dataset_ids` 배열 하나로 묶인다 — MCST는
   dataset 13개가 run 1개, KNPS는 dataset마다 run_config가 달라 항목 5개. `attempt_seq`는 같은 행에서
   단조 증가하고 UNIQUE에 넣지 않는다 — 시도 이력은 Dagster run tag가 갖는다; 단순성). geo 의존 여부는 `GEO_DEPENDENT_OPERATION_KEYS`(결정 3 — pool lint의 AST 유도와 집합
   동등으로 고정된 core 상수)로 본다.
   KNPS처럼 job 1개에 dataset 5개가 결박된 operation은 dataset마다 항목 1개 + **run_config를 dataset마다**
   (`knps_schedule_binding`의 꼴, `schedules.py:158-165`). 쿼터 민감 dataset은 `source_mode=replay`(결정 7).
   `DISABLED_FEATURE_LOAD_OPERATION_KEYS`(`schedules.py:556-560`)는 `skipped(disabled)` — 센서·수동 `/detect`
   모두 같은 함수.
4. **직렬 진행, tick당 최대 1건.** Skip 조건이 먼저다 — 활성 `feature_update_request_worker` run이 있으면
   이번 tick Skip(큐 run이 dataset 전체를 transaction 하나로 쥐는 동안 전용 job의 첫 chunk가 전역 잠금
   대기로 `GEO_HEAVY_POOL`을 점유한 채 멎어 21,600 s에 죽을 수 있다, 컨텍스트 6); 같은 `operation_key`의
   run이 돌면 Skip(`map_owned_runs_filter`, `dagster/run_scope.py:80`; MOIS `mois-continue:*` run 포함).
   `RunRequest(job_name=operation_key, run_key=geo_release/{data_token}/{plan_seq}/{operation_key}/{position}/{attempt_seq},
   run_config, tags={"kor_travel_map.trigger_kind": "sensor", "kor_travel_map.geo_release_plan_id": str(plan_id)})`
   — `"sensor"`는 `TRIGGER_KIND_VALUES`에 이미 있다(`core/feature_operation.py:52-59`); `geo_release_plan_id`는
   전용 run의 유일한 판별자다(MOIS 이어 달리기 run도 `trigger_kind=sensor`를 쓴다, 결정 4). `attempt_seq`는 단조
   증가·리셋 없음(Dagster run_key 영구 dedupe와 충돌하지 않는다). 새 pool·새 limit 태그 없음 → Manager
   `dagster.yaml` 변경 없음(배포 순서의 Manager 단계는 concierge ADR-49 refresh job lane이지 Map 변경이 아니다).
5. **전이 규칙.** FAILURE/CANCELED → `failed`(비-MOIS는 자동 재요청 1회, 그 다음은 운영자). SUCCESS이고 run
   태그 `kor_travel_map.mois_load.outcome=budget_exhausted`(`mois_chunked_load.py:99-103`)면 **`done`이
   아니라** `mois_load_continuation_decision(last)`(`:1132-1154`)를 그대로 호출해 같은 run_config로 다음
   `attempt_seq`를 재요청한다(`converted==0` 정지 규칙까지 단일 정본; 정지면 `failed(no_progress)`; MOIS 상한
   12). 그 외 SUCCESS → `done`. `requested`인데 3 tick(15 min) 뒤에도 run이 없으면 `failed(run_not_launched)`.
   **릴리스 센서가 MOIS 이어 달리기를 대신한다** — 계획이 활성인 동안 continuation sensor(기본 STOPPED)를
   켤 필요가 없다. **켜져 있으면 이중 체인이 된다** — 이어 달리기 센서는 마지막 MOIS run만 보고 같은 판정을
   하므로, 그 run이 릴리스 run이면 두 센서가 각자 다음 run을 낸다(Skip 조건은 진행 중 run만 막는다). 그래서 이어 달리기
   센서는 마지막 run에 `kor_travel_map.geo_release_plan_id` tag가 있으면 Skip한다(구현 T-GR-05). CANCELED는 재요청하지
   않고 `failed(canceled)`다(운영자의 취소 존중); 계획이 `superseded`될 때 그 계획의 `requested` 항목은
   `failed(superseded)`다(migration 409 — 진행 중 고아가 없어야 한 번에 run 1개가 성립).
6. **완료 판정은 비-skipped dataset만.** 모든 항목 terminal이면 `coverage(current, provider_dataset_ids=비-skipped)`의
   `stamped_other + unstamped(provider 기원) == 0`이면 완료 단계. 아니면 잔여가 있는 dataset마다 **1회
   sweep** 뒤 잔여 수를 `residual_stale`로 기록하고 완료 단계(비율 문턱 없음, 두 번째는 운영자 `replan`).
   `excluded_by_skip`·`unstamped_non_provider`는 표시만. **완료 단계**: 활성 cache target 전부에
   `sync_poi_cache_target_feature_links`(`infra/poi_cache_target_repo.py:862`) 1회 → `done`. 이유: 그 함수의
   유일한 호출처가 큐 executor(`infra/feature_update_executor.py:612`)라 prod(schedule STOPPED)에서는
   `sigungu_code`가 바뀐 feature의 `same_sigungu` 링크가 저절로 따라오지 않는다.

### 6. concierge payload의 `geo_data_token` — 신뢰 조건과 해시 제외 (열린 결정 12)

concierge export `place.address.geo_data_token`(concierge ADR-49, 계획)은 Map에서 두 규칙으로 읽는다.
(a) `providers/kor_travel_concierge.py:523-556` `_address`는 payload 토큰이 있고 run-scoped `data_token`과
**같을 때만** payload 코드를 신뢰한다; 다르거나 없으면 geo `bjd_code` 우선, geo None일 때만 payload fallback.
스탬프는 결정 3의 순서 그대로다 — 좌표가 있어 reverse를 불렀으면 payload 코드를 썼어도 `called`(geo가
`admin/zipcode/road_name_code/명칭` 빈칸을 채우므로 그 값도 릴리스 비교 대상), 좌표 없는 payload 코드 행만
`not_called`. **설계와 다른 점**: 설계 §6.3은 payload 코드 행을 `not_called`로 두었으나 geo가 그 빈칸을 채우므로
1차 문서 리뷰에서 `called`로 바꿨다. concierge refresh가 Map 계획보다 늦어도 stale payload 코드가 현재 토큰으로
봉인되지 않는다.
(b) Map `raw_payload_hash`는 concierge의 `payload_hash`를
채택하는 대신(`:278-290`) `address.geo_data_token`을 뺀 `make_payload_hash`로 자체 계산한다(구현: payload가 토큰을
실어 올 때만; producer가 export 행에 덧붙이는 최상위 `updated_at`·`operation`도 뺀다 — producer는 토큰만 바뀌어도
`updated_at`을 새로 찍는다) — 토큰이
들어가면 릴리스마다 concierge feature 전부가 `became_current`가 되어 값 동일에도 `row_revision + 1`이고
"payload hash는 geo 산출을 제외한다"는 불변식이 깨진다. concierge 쪽 `payload_hash`에는 포함되므로 토큰만
바뀐 장소도 재발행된다.

### 7. 쿼터 민감 dataset은 `source_mode=replay`

geo만 바뀐 릴리스에서 MOIS 50만 행·datagokr 계열을 provider HTTP로 다시 받으면 data.go.kr 오퍼레이션당
일일 한도를 소모한다(memory `data-go-kr-quota-per-operation`). `provider_sync.source_records.raw_data jsonb
NOT NULL`(`head-schema.sql:18591-18600`)에 원문이 있으므로 records resource의 run_config
`{"resources": {"<records_resource>": {"config": {"source_mode": "replay"}}}}`가 HTTP 대신 entity head의
current `raw_data`를 **같은 record 모델**로 되살려 **같은 변환기**에 넣는다(중복 기제 아님). `fetched_at`은
원 값 유지 → `became_current`는 항상 False, stale 분기만 돈다. MOIS의 replay 제외 술어는 **스탬프**다 —
`feature_geocode_stamps.reverse_outcome = 'not_called'`인 entity(결정 4의 unchanged CTE 조건과 같은 술어, 별도
제외 코드 없음; replay 읽기 keyset이 같은 술어로 선필터해도 의미는 같다). `raw_data.legal_dong_code` 유무로 빼면
안 된다 — 스탬프 **없는** payload-bjd 행은 replay에 **포함**되어 reverse 없이 변환되고 `not_called` 스탬프만 받는다
(geo 0회, 비용은 변환뿐). 그래야 롤아웃 첫 run이 그 행에 스탬프를 찍어 결정 5.6의 `unstamped == 0`이 성립한다.
1단계 적용 범위는 MOIS + `datagokr_file_data` + `standard_data`(열린 결정 4).
**가정**: `raw_data → record 모델` 복원이 provider마다 1:1 — golden으로 확인되는 provider만 켠다.
**결과(T-GR-08, 2026-10-16)**: golden 통과 = datagokr 축제·standard_data 4종·fileData 4종(9 operation). **MOIS는
실패** — `raw_data`가 변환기가 쓰는 record 필드 24개(우편번호 2·건물관리번호·업종별 시설 21)를 남기지 않아 되살린
bundle의 `facility_info`·주소가 달라진다. 그래서 MOIS는 replay 목록(`REPLAY_RECORDS_RESOURCES`)에서 빠지고 fetch
run_config로 나간다 — MOIS fetch는 data.go.kr 쿼터를 쓰지 않는다(로컬 SQLite 소스 DB, Phase A 내려받기는 TTL 24h 게이트).
스탬프 없는 payload-bjd 행의 `not_called` 스탬프는 fetch run이 같은 술어로 찍는다(결정 4). replay 적재는 `fetched_at`과
함께 head 관측 시각 입력(`imported_at`)도 저장값으로 되돌려 head를 전진시키지 않고, sync state를 쓰지 않으며, 변환
payload hash가 저장값과 다르면 적재 전에 실패한다.

### 8. 운영 API는 admin 프로필만, 슬래시 동사

`packages/kor-travel-map-api/src/kortravelmap/api/routers/ops_geo_releases.py`(`require_ops_operator`,
`api/auth.py:426`): `GET /v1/ops/geo-releases`(목록 + 현재 geo 토큰 + 센서 Skip 사유; API가 geo를 대신
호출), `GET /v1/ops/geo-releases/{plan_id}`, `POST /v1/ops/geo-releases/detect`(센서와 **같은** core 함수,
멱등), `POST /v1/ops/geo-releases/{plan_id}/items/{position}/skip`, `POST /v1/ops/geo-releases/{plan_id}/replan`.
콜론 동사는 저장소 선례가 없다(`ops_pipeline.py:1483, 1506, 2047, 2216`). 센서가 API를 치지 않으므로
service 프로필에 둘 이유가 없다 → `openapi.user.json`·`openapi.service.json` 불변, `openapi.json`(admin)만
바뀐다. **PinVi 영향**: admin 스냅샷 단일 핀 `apps/api/tests/unit/_kor_travel_map_snapshot_pin.py:16-17`과
`test_kor_travel_map_admin_contract.py` 이중 핀, M05 pair contract digest가 깨지므로 PinVi 재vendor PR이
Map API 배포 **전에** 머지돼야 한다(2026-10-12 t1013b 회전 preflight 거부, memory
`map-admin-openapi-change-needs-pinvi-revendor`). admin UI `/admin/ops/geo-releases`(T-GR-06);
`/admin/issues`는 변경 없음(`violation_type` 원문 표시가 유형 무관).

## 결과

- **긍정.** 재빌드(토큰 동일)는 계획 0건. 값이 바뀐 행만 `row_revision`이 전진해 ETag·seal·cache target
  무효화가 기존 기제로 전파된다. provider 변환이 단일 정본으로 남는다. replay 모드는 provider HTTP 0회.
  새 pool·태그·Manager 변경 없음. `openapi.user/service.json` 불변.
- **부정·비용.** ~~롤아웃 첫 tick은 스탬프가 비어 있으므로 전 geo-의존 dataset의 전량 계획 1회가 반드시
  발생한다~~ — **소유자 결정(2026-10-15)으로 철회**: 커서가 빈 첫 tick은 관측 토큰을 기준선으로 기록할 뿐
  계획을 만들지 않는다(결정 5.1). 스탬프는 평소 적재가 채운다 — 비-MOIS는 unchanged에도 reverse를 이미 부르므로
  추가 geo 비용 0(스탬프 부재 = stale이라 적재 경로를 타되 값이 같으면 무쓰기, 결정 4), MOIS는 다음 run이 스탬프
  없는 행을 1회 변환한다(ADR-108 재개형 chunk). 전량 **계획**은 기준선 이후 토큰이 바뀐 릴리스에서만 생긴다(비-MOIS
  prod 좌표 보유 활성 35,754행 × reverse p50 86 ms ≈ 51 min 순차 하한; MOIS는 replay 수 run). 표 2개·마이그레이션 2개(407·408)·resource 2개·센서 1개·admin
  router 1개가 는다. 전용 job은 fetch 모드 provider의 월간 적재 1회분 쿼터를 더 쓴다(운영자가 항목 `skip`).
  재실행(attempt 2)은 쓰기만 건너뛰고 비-MOIS reverse는 전량 다시 부른다.
- **잃는 것.** 행 단위 "어느 토큰으로 해석됐나"의 정밀도(run 단위로 대체; 불일치는 WARNING·재계획으로
  보상). 큐(`feature_update_requests`)로 재지오코딩을 돌리는 길(큐가 돌린 적재도 스탬프는 찍는다).

## 열린 결정 (소유자)

1. **`not_called` 행(provider 코드만 쓴 MOIS payload-bjd·concierge payload 코드, 좌표 없이 geocode를 시도해
   실패한 행)은 법정동 폐지·geo 데이터 보강 뒤에도 재검증하지 않는다** — 폐지 코드가 공개 필터·클러스터에 남을 수
   있다. 그 전까지 `coverage.not_called_by_kind`
   가 수를 노출한다. phase 2 코드 인벤토리 diff(geo `POST /v2/dataset/changes`)가 생기면 `dead_admin_code`
   finding으로 묶는다 — 착수 여부·시점.
2. **provider 기원이 아닌 feature**(user_request·curation import): (i) 범위 밖 + `unstamped_non_provider`
   노출 + `/admin/issues` `apply_kor_travel_geo_address` 수동(권장) vs (ii) 코드 전용 재지오코딩 job 신규
   task. 규모는 n150 실측.
3. 센서 `default_status=RUNNING`(권장) vs STOPPED(UI "지금 감지"만); 쿼터 민감 dataset만 pending-manual 절충.
4. replay 모드 적용 범위: MOIS + datagokr_file_data + standard_data(권장) vs MOIS만 vs 전 provider.
5. `same_sigungu` 링크 재동기화 = 활성 target 전부 1회(권장, 단순) vs 바뀐 feature를 가진 target만(추적 표).
6. geo-release run 한정 reverse timeout 1회 재시도(ADR-108 예외, 판별자 `geo_release_plan_id` 태그) 승인 vs 재시도
   없이 attempt 2로만 복구 — 승인 전에는 적용하지 않는다.
7. task ID 접두사 `T-GR-NN`(임시 사용 중) vs `T-VN-GR-NN` vs 연번(`docs/tasks-rule.md` §3은 묶음 prefix 허용).
8. ~~롤아웃 첫 tick 전량 1회 비용 승인~~ — **해소(소유자 결정 2026-10-15)**: 첫 토큰은 기준선이다(결정 5.1).
   첫 tick은 계획을 만들지 않고, geo 지문이 없는 동안(`data_token` 없음)은 계획 없이 Skip한다 — 지문이 생긴 뒤
   첫 관측도 기준선이다. 남는 것은 MOIS payload-bjd 행의 `not_called` 선채움(마이그레이션)이 **선택**이라는 점뿐이다 —
   결정 7대로 스탬프 없는 행이 replay에 포함되어 첫 run이 스탬프를 찍으므로, 선채움은 첫 run 시간 단축용일 뿐이다.
9. 완료 판정(비-skipped `stamped_other + unstamped == 0`, 아니면 sweep 1회 뒤 `residual_stale` 기록·done) 승인.
10. override 처리 = finding만(자동 적용 없음) 승인.
11. 재처리 경로 = 전용 job RunRequest(결정 5, 권장) 승인 vs 큐 `feature_update_requests` — 큐는 dataset 단위
    all-or-nothing·pool 미claim·재시도 시 reverse 전량 재호출이라 비권장.
12. concierge payload 토큰을 Map `raw_payload_hash`에서 **제외**(결정 6(b)) 승인 — 넣으면 릴리스마다 concierge
    feature 전부가 `became_current`.
13. 범위 밖 drift를 백로그로 보낼지: `admin_code_stale_*`가 `dual` grade에서만 발화, Map `admin_dong_code`·
    `road_address_management_no`가 전부 NULL, 하드코딩 시도 표 3개(설계 §12 #8).

열린 결정이 미결인 동안 구현 task는 ADR의 권장안을 기준으로 한다 — 결정별 영향 조문은
`docs/tasks-acceptance.md` §T-GR-00.
