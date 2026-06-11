# KMA·MCST provider 상세구현 계획 (T-219/T-220, 2026-06-11)

> **목적**: 사용자 지시 "kma, mcst provider 빠짐없이 상세구현(Dagster 코드 포함)"의
> 실행 청사진. 4-방향 실측(python-kma-api `ab1a0b8` · python-mcst-api origin/master
> `d06e8d2` · krtour 기존 KMA 구현 · provider 풀스택 패턴) 기반.
> **상태**: 계획 정본 — 구현은 T-219a~c / T-220a~c PR로 진행.

## 1. 현황 갭 요약

| | 변환 함수 | Dagster | 비고 |
|---|---|---|---|
| **KMA** | **100%** — 5종(초단기실황/초단기예보/단기/중기 land+ta/특보) 1,133줄 + 57+ 테스트, `WeatherValue`/notice 적재 모델·admin weather 카드 완비 | **0%** — fetch/resource/asset/schedule 전무 | 갭 = 파이프라인 + LGT 메타 + 격자→feature 매핑 |
| **MCST** | 전무 (신규 provider) | 전무 | python-mcst-api: KCISA 14종 place dataset(`CultureRecord` 정규화 — name/address/tel/url/**lon/lat**/category) + ODCloud 도서관 2종(`RawRecord`) |

## 2. KMA 설계 결정 (T-219)

### 2.1 격자→feature 매핑 = 옵션 B (기존 결정 유지, `docs/kma-weather-etl.md` §3)

place feature의 `coord`로 격자를 계산해 같은 격자의 weather를 매핑(N:1). 단
**전 place 대상은 호출량/행 폭발**(distinct 격자 수천 × 30분 cron × 메트릭)이므로
**1차 대상 한정**:

- 대상 격자 = ① **활성 `poi_cache_targets` 좌표**의 distinct 격자(TripMate 등 외부
  시스템이 등록한 관심 지점 — 수요가 증명된 곳) + ② 설정
  `kma_weather_extra_points`(명시 추가 좌표, 기본 빈 목록).
- run당 격자 상한 설정(`kma_weather_max_grids_per_run`, 기본 50) — data.go.kr 일일
  한도 보호.
- 격자 내 feature 매핑: 해당 격자에 속하는 active place feature(coord 기준 grid
  일치)에 적재. 전 place 확장은 운영 측정(T-212e 이후) 후 별도 결정.
- 격자 변환은 **python-kma-api가 담당**(client가 `location={lat,lon}` 수용, LCC DFS
  변환 내장) — krtour에 grid 모듈을 두지 않는다(ADR-006 정합).

### 2.2 키/credential

단기예보 계열(VilageFcst)·중기(DataGoKr)·특보 모두 **data.go.kr 키** —
기존 `settings.data_go_kr_service_key` 공유(신규 settings 필드는 extra_points/상한만).
APIHub(`KMA_APIHUB_KEY`) 표면은 1차 범위 외(백로그 비고).

### 2.3 Dagster 구조 (record-resource 패턴 변형)

nowcast/forecast는 "대상 좌표"가 DB(poi targets)에서 나오므로 표준
record-resource(좌표 무관 스트림) 패턴이 안 맞는다 →
- **asset이 직접**: `krtour_map_client`로 대상 격자/feature 매핑 조회 → lazy import
  `kma` client로 격자별 호출 → 변환 → `load_weather_values`. credential guard는
  asset 시작부에서 `ProviderCredentialMissing`(기존 fetcher와 동일 예외).
- **특보(alerts)는 표준 패턴 가능**(전국/지역 조회, 좌표 무관) → record resource
  `kma_weather_alerts` + notice FeatureBundle `_load`.
- cursor: `provider_sync_state`에 base_datetime 저장(같은 base 중복 호출 회피,
  `docs/kma-weather-etl.md` §6).

### 2.4 PR 분해

- **T-219a** (기반): `weather_repo`(또는 feature_repo)에 대상 격자/feature 매핑 조회
  + settings 2필드 + **LGT 메트릭 메타 등록** + 단위/통합 테스트.
- **T-219b** (실황·예보): Dagster asset 3종(nowcast 매시·ultra_short 30분·short
  3h base 8회/일) + schedule + credential guard + 테스트(fake client).
- **T-219c** (중기·특보): mid(region 107 — 1차는 **광역시도 area/대표 feature 매핑
  테이블 settings 주입**, 미설정 region skip) + alerts record resource→notice 적재
  asset(일 cron) + 테스트.

특보 region→좌표 enrichment, ASOS/해수욕장(beach_*) 시리즈, APIHub 470 endpoint는
**백로그 비고**로만(1차 범위 외 — beach_*는 khoa_beaches와 결합 가치 있음).

## 3. MCST 설계 (T-220, 신규 provider)

### 3.1 정체성

- canonical provider name: **`python-mcst-api`** / marker_color: **`P-12`**(미사용
  색 P-03/04/12/14 중 — 문화 계열 1색, krforest P-05 단일색 패턴).
- 키: `DATA_GO_KR_SERVICE_KEY` 공유(KCISA·ODCloud 동일 키, mcst lib 실측).

### 3.2 dataset 전수 (16종) — slug 메타테이블 1곳에서 관리

KCISA 14종은 공통 `CultureRecord`이므로 **`providers/mcst.py`에 단일 변환 함수 +
`MCST_CULTURE_DATASETS` 메타표**(slug → dataset_key/category/place_kind/설명)로
"빠짐없이" 커버. dataset_key는 `mcst_<slug>`.

| slug | category(안) | place_kind |
|---|---|---|
| media_famous_places | 01070000 계열→**01010000(관광명소)** 부적합 시 신설 검토 | media_famous_place |
| barrier_free_places | 01040000(문화시설) 하위 | barrier_free_place |
| pet_friendly_culture_facilities | 01040000 하위 | pet_friendly_culture_facility |
| leisure_activity_facilities | 01050000(레저) 계열 — 구현 시 enum 실측 후 확정/신설 | leisure_activity_facility |
| leisure_camping_facilities | 03(숙박) 캠핑 계열 | leisure_camping_facility |
| leisure_classes | 레저 계열 | leisure_class |
| family_infant_culture_facilities | 01040000 하위 | family_culture_facility |
| multilingual_guide_culture_facilities | 01040000 하위 | multilingual_culture_facility |
| world_restaurants | **02(음식)** 계열 | world_restaurant |
| small_theaters | **01040300**(공연장) | small_theater |
| meeting_seminar_facilities | 05(편의) 또는 신설 | meeting_facility |
| independent_bookstores | 01040000 하위(서점 신설 후보) | independent_bookstore |
| cafe_bookstores | 〃 | cafe_bookstore |
| recommended_travel_destinations | 01(관광) 대표 | recommended_destination |
| public_libraries (ODCloud) | **01040500**(도서관) | public_library |
| small_libraries (ODCloud) | 01040500 | small_library |

> category 최종값은 T-220a에서 `category/_definitions.py` 실측 후 확정 — 기존 코드
> 우선, 부재 시 Tier3/4 신설(표는 방향만 고정). 자연키 = 안정 id 부재 시
> `name::address`(KCISA 방언 정규화 후), 좌표 없으면 reverse_geocoder 보강
> (krforest `_resolve_address` 패턴).

### 3.3 Dagster 구조

- fetch 2종: `fetch_mcst_culture_records(settings)` — 14 slug 순회하며
  `(slug, CultureRecord)` 튜플 스트림(`iter_items`, slug별 max_items 가드) /
  `fetch_mcst_libraries(settings)` — ODCloud 2 slug `(slug, RawRecord)`.
- resource 2종(`mcst_culture_records`/`mcst_library_records`) + asset 2종
  (`feature_place_mcst_culture`/`feature_place_mcst_libraries`) — asset이 slug별로
  분리 `_load`(dataset_key 단위 import job/sync state 유지, 결과 합산).
- schedule: 주 1회(저빈도 시설 데이터).
- dedup: MOIS PROMOTED 슬러그와 식당/도서관 교차 가능성 — T-220c에서
  `DEFAULT_DEDUP_SCOPE_PAIRS` 후보 검토(즉시 등록 아님).

### 3.4 PR 분해

- **T-220a**: `providers/mcst.py`(메타표 16종 + 공용 변환 + 도서관 변환) +
  category 신설분 + 단위 테스트.
- **T-220b**: Dagster fetch/resource/asset/schedule/definitions + 테스트
  (spec/REQUIRED_RESOURCE_KEYS 카운트 단언 갱신 포함).
- **T-220c**: ETL preview fixture + 문서(external-apis §3.N, provider-contract
  §2~4, `docs/mcst-feature-etl.md` 신규, CHANGELOG) + dedup pair 검토.

## 4. 공통 게이트

각 PR: `pytest`(unit + 해당 dagster/admin) + `ruff` + `mypy --strict`(krtour.map +
dagster) + `lint-imports` + CI green 후 머지. 변환 함수는 Protocol 입력
(mypy frozen-dataclass 함정 — `Sequence[Any]` 우회 패턴 준수), provider lib import는
Dagster fetcher의 lazy import만(ADR-006).
