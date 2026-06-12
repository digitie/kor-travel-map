# mcst-feature-etl.md — 문체부 파일데이터(CSV) place ETL

`python-mcst-api`의 파일데이터 CSV 13 dataset을 place `Feature`로 적재하는 ETL
정본(T-220 재배선 #395 + T-223b). 구 KCISA OpenAPI/ODCloud 경로(T-220a~c)는 provider
재편(provider #6/#7/#9/#11)으로 폐기됐다 — KCISA OpenAPI(`api.kcisa.kr`)는 공인
DNS로 해석되지 않고 KCISA 전용 발급키가 필요해 명세 참고용으로 강등, ODCloud
도서관 디렉토리 dataset은 카탈로그에서 소멸.

## 1. 문서 정보

| 항목 | 값 |
|------|----|
| provider | `python-mcst-api` (`@c011f6e`, origin/master) |
| client | `mcst.FileDataClient` — **keyless**(다운로드 페이지 스크레이핑 → 최신 CSV) |
| dataset_key | `mcst_<slug>` 13종 — 메타표 `kortravelmap.providers.mcst.MCST_FILE_DATASETS` |
| Feature.kind | place |
| 코드 entrypoint | `kortravelmap.providers.mcst` / `kortravelmap.dagster.mcst_features` |
| 키 | **불요** (`docs/external-apis.md` §3.14) |
| marker | `P-12` 단일색 (문화 계열 1색, T-220a 결정 유지) |

dataset_key는 `mcst_<slug>` **클린 컷** — 구 키(`mcst_independent_bookstores`
등 슬러그 무접미)와의 하위호환 shim은 두지 않는다(빈 DB 재적재 중, ADR-046
이행 원칙과 동일).

## 2. 적재 13 dataset — 컬럼 방언 4종

변환 함수 1개(`file_rows_to_bundles(slug=...)`)가 slug 메타표의 방언으로 컬럼
추출을 분기한다. 컬럼/형식은 2026-06-12 live 전수 CSV 다운로드 실측 기준.

| slug | 방언 | category | place_kind |
|---|---|---|---|
| world_restaurants_csv | kcisa_common | 02010000 | world_restaurant |
| pet_friendly_culture_facilities_csv | kcisa_common | 01040000 | pet_friendly_culture_facility |
| barrier_free_places_csv | kcisa_common | 01040000 | barrier_free_place |
| leisure_activity_facilities_csv | kcisa_common | 01080400 | leisure_activity_facility |
| family_infant_culture_facilities_csv | kcisa_common | 01040000 | family_culture_facility |
| leisure_camping_facilities_csv | kcisa_common | 03060000 | leisure_camping_facility |
| leisure_classes_csv | kcisa_common (좌표 컬럼 없음) | 01080000 | leisure_class |
| media_famous_places_csv | kcisa_common (`PLACENAME`/`MEDIATITLE`) | 01000000 | media_famous_place |
| independent_bookstores_csv | cntc_resrce | 01040000 | independent_bookstore |
| cafe_bookstores_csv | cntc_resrce | 01040000 | cafe_bookstore |
| children_bookstores_csv | split_coord | 01040000 | children_bookstore |
| used_bookstores_csv | split_coord | 01040000 | used_bookstore |
| golf_courses_status | korean_address | 01080100 | golf_course |

- **kcisa_common** (8종): `TITLE`(media는 `PLACENAME`)/`ADDRESS`/`TEL`/`URL`/
  `COORDINATES`/`CATEGORY1-3` 대문자 컬럼. `CATEGORY1-3`은 ` > `로 합쳐
  `facility_info.source_category`. `leisure_classes_csv`는 좌표 컬럼이 없어
  주소 단서 경로만 탄다.
- **cntc_resrce** (2종): `CNTC_RESRCE_ID`/`TITLE`/`ADDRESS`/`CONTACT_POINT`/
  `COORDINATES`. `CNTC_RESRCE_ID`는 안정 id처럼 보이나 명세 보증이 없어
  자연키로 쓰지 않고 `facility_info`에 보존만.
- **split_coord** (2종): `FCLTY_NM`/`FCLTY_ROAD_NM_ADDR`/`FCLTY_LA`(위도)/
  `FCLTY_LO`(경도)/`TEL_NO`.
- **korean_address** (1종): `지역`/`이름`/`사업자`/`소재지`/`구분`/`홀` 한국어
  컬럼, 좌표 없음 — `지역`+`소재지` 합성 주소 단서.

category는 전부 **기존 코드**(T-220a 결정 재사용 — 신설 불요). 신규 3종도
기존 코드로 흡수: 아동서점/중고서점은 서점류와 동일 계열(01040000), 골프장은
01080100(TOURISM_ACTIVITY_GOLF).

### COORDINATES 파서 (`parse_kcisa_coordinates`)

실측 2형식 + 공백 변형:

- `"N37.545904, E126.92094"` — N/E 접두, lat-lon 순.
- `"35.86561079 , 128.6083915"` / `"37.54497283 126.9676467"` — 평문 lat-lon 순
  (콤마/공백 구분자 변형).

결과 `(lon, lat)`은 한국 bbox(lon 124~132, lat 33~43)로 검증하고 평문 순서
뒤집힘은 bbox로 감지해 교정한다. 파싱 실패/범위 밖이면 좌표 없음 처리(주소
단서 경로). `FCLTY_LA`/`FCLTY_LO` 분리좌표도 같은 bbox 검증을 거친다.

## 3. 제외 3 dataset (사유)

`kortravelmap.providers.mcst.MCST_EXCLUDED_FILE_DATASETS`에 코드로도 보존:

| slug | 제외 사유 |
|---|---|
| tourism_attractions_csv | 서지형 42컬럼(PUBLISHER/COLLECTIONDB/UCI 등) — POI가 아닌 기사/자료 레코드 혼재(실측 64,194행) |
| recommended_travel_destinations_csv | 정책브리핑 기사형(DESCRIPTION이 본문 HTML) — POI 아님 |
| public_libraries | 도서관 **통계**(장서수/대출자수/자료구입비) — 시설 디렉토리 아님 |

구 `mcst_public_libraries`/`mcst_small_libraries`(ODCloud 도서관 디렉토리)는
provider 재편으로 경로 자체가 소멸 — **도서관 디렉토리 재적재는 후속 과제**
(§6 백로그).

## 4. 변환 규칙

- 자연키 `name::address`(정규화 후, ADR-009 `::`) — 안정 id 부재.
- 좌표가 있으면 reverse로 bjd 보강(ADR-046), 없으면 provider 주소 텍스트를
  `raw_address` 위치 단서로 보존. 이름이 없거나 좌표·주소가 모두 없는 row는
  건너뛴다(asset이 제외 수 경고).
- 원천 분류/연락처는 `PlaceDetail.facility_info`(`source_category`/`tel`/`url`,
  media는 `media_title`, 골프장은 `operator`/`hole_count`)에 보존. placeholder
  값(`정보없음`/`-`)은 제외. CSV row 원본은 `raw_data`에 전량 보존.

## 5. Dagster

record resource 1개(`mcst_culture_records`)가 `(slug, row)` 튜플을 stream하고
asset이 **slug별 분리 `_load`** — dataset_key 단위 import job/sync state 유지.
fetcher는 keyless `FileDataClient`로 credential guard 없음(knps/krheritage
items 패턴).

| asset | resource | schedule |
|---|---|---|
| `feature_place_mcst_culture` | `mcst_culture_records` (파일데이터 13) | `30 4 * * 2` |

구 `feature_place_mcst_libraries` asset/`mcst_library_records` resource는 제거.

dataset당 1 run 상한 `KOR_TRAVEL_MAP_MCST_MAX_ITEMS_PER_DATASET`(기본 50000 — 실측
최대 leisure_activity_facilities_csv 24,537행의 약 2배 여유).

## 6. ETL preview fixture

admin `/v1/debug/etl` preview: `python-mcst-api` × 방언 대표 3종 —
`mcst_world_restaurants_csv`(공통 A) / `mcst_independent_bookstores_csv`
(CNTC_RESRCE) / `mcst_children_bookstores_csv`(분리좌표).

## 7. dedup pair 검토 (T-220c 결정 유지)

MOIS PROMOTED 슬러그와 교차 가능성이 있는 dataset: `world_restaurants_csv`
(식당 인허가), `independent_bookstores_csv`/`cafe_bookstores_csv`(서점/
휴게음식점), `leisure_camping_facilities_csv`(야영장업), `golf_courses_status`
(골프장업). **즉시 등록하지 않는다** — 자연키 체계(`name::address`)가 MOIS
관리번호 체계와 달라 실데이터의 이름/좌표 근접 매칭 품질을 본 뒤(T-212e full
reload 이후) `DEFAULT_DEDUP_SCOPE_PAIRS` 후보로 재검토한다.

## 8. 백로그

- 도서관 **디렉토리**(위치/운영) 재적재 — 구 ODCloud 경로 소멸로 보류. 국가
  도서관통계 외의 디렉토리성 원천을 provider에 추가한 뒤 재배선.
- 카탈로그 LINK dataset(전통사찰/등록공연장/공공체육시설 등 — 연결 원천)의
  적재 가능성 검토.
- CSV 갱신주기(파일 페이지 표기 월간/연간)에 맞춘 schedule 세분화.
