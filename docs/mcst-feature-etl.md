# mcst-feature-etl.md — 문체부(KCISA/ODCloud) place ETL

`python-mcst-api`의 16 dataset을 place `Feature`로 적재하는 ETL 정본(T-220,
계획 `docs/reports/kma-mcst-provider-plan-2026-06-11.md` §3).

## 1. 문서 정보

| 항목 | 값 |
|------|----|
| provider | `python-mcst-api` (`@d06e8d2`, origin/master) |
| dataset_key | `mcst_<slug>` 16종 — 메타표 `krtour.map.providers.mcst.MCST_{CULTURE,LIBRARY}_DATASETS` |
| Feature.kind | place |
| 코드 entrypoint | `krtour.map.providers.mcst` / `krtour.map_dagster.mcst_features` |
| 키 | `DATA_GO_KR_SERVICE_KEY` 공유 (`docs/external-apis.md` §3.14) |
| marker | `P-12` 단일색 (문화 계열 1색) |

## 2. dataset 16종

KCISA 14종은 공통 `CultureRecord` 스키마(name/address/tel/url/lon/lat/category)
— **변환 함수 1개**(`culture_records_to_bundles(slug=...)`)가 slug 메타표로
전부 커버한다. ODCloud 도서관 2종은 한국어 CSV 컬럼 raw row →
`library_records_to_bundles`(컬럼 방언 관대 조회).

category는 전부 **기존 코드**(T-220a 실측 — 신설 불요), dataset 세부 구분은
`place_kind`:

| slug | category | place_kind |
|---|---|---|
| media_famous_places | 01000000 | media_famous_place |
| barrier_free_places | 01040000 | barrier_free_place |
| pet_friendly_culture_facilities | 01040000 | pet_friendly_culture_facility |
| leisure_activity_facilities | 01080400 | leisure_activity_facility |
| leisure_camping_facilities | 03060000 | leisure_camping_facility |
| leisure_classes | 01080000 | leisure_class |
| family_infant_culture_facilities | 01040000 | family_culture_facility |
| multilingual_guide_culture_facilities | 01040000 | multilingual_culture_facility |
| world_restaurants | 02010000 | world_restaurant |
| small_theaters | 01040300 | small_theater |
| meeting_seminar_facilities | 05000000 | meeting_facility |
| independent_bookstores | 01040000 | independent_bookstore |
| cafe_bookstores | 01040000 | cafe_bookstore |
| recommended_travel_destinations | 01000000 | recommended_destination |
| public_libraries (ODCloud) | 01040500 | public_library |
| small_libraries (ODCloud) | 01040500 | small_library |

## 3. 변환 규칙

- 자연키 `name::address`(정규화 후, ADR-009 `::`) — 안정 id 부재.
- 좌표가 있으면 reverse로 bjd 보강(ADR-046), 없으면 provider 주소 텍스트를
  `raw_address` 위치 단서로 보존. 이름이 없거나 좌표·주소가 모두 없는 row는
  건너뛴다(asset이 제외 수 경고).
- 원천 분류/연락처는 `PlaceDetail.facility_info`(`source_category`/`tel`/`url`,
  도서관은 `library_type`)에 보존.

## 4. Dagster (T-220b)

record resource가 `(slug, record)` 튜플을 stream하고 asset이 **slug별 분리
`_load`** — dataset_key 단위 import job/sync state 유지.

| asset | resource | schedule |
|---|---|---|
| `feature_place_mcst_culture` | `mcst_culture_records` (KCISA 14) | `30 4 * * 2` |
| `feature_place_mcst_libraries` | `mcst_library_records` (ODCloud 2) | `50 4 * * 2` |

dataset당 1 run 상한 `KRTOUR_MAP_MCST_MAX_ITEMS_PER_DATASET`(기본 5000).

## 5. ETL preview fixture (T-220c)

admin `/v1/etl/preview`: `python-mcst-api` × `mcst_independent_bookstores`
(KCISA 공용 변환 대표) / `mcst_public_libraries`(도서관 공용 변환 대표).

## 6. dedup pair 검토 (T-220c 결정)

MOIS PROMOTED 슬러그와 교차 가능성이 있는 dataset: `world_restaurants`(식당
인허가), `independent_bookstores`/`cafe_bookstores`(서점/휴게음식점),
`leisure_camping_facilities`(야영장업). **즉시 등록하지 않는다** — 자연키
체계(`name::address`)가 MOIS 관리번호 체계와 달라 실데이터의 이름/좌표 근접
매칭 품질을 본 뒤(T-212e full reload 이후) `DEFAULT_DEDUP_SCOPE_PAIRS` 후보로
재검토한다.

## 7. 백로그

- KCISA `meeting_seminar_facilities` category 전용 코드(Tier2 신설) 재검토.
- mcst 카탈로그의 비-place dataset(마라톤 대회 등 event성) 추가 검토.
