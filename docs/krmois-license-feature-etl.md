# KRMOIS 인허가 feature ETL

`python-krmois-api`는 MOIS localdata/raw row의 source-of-record다. 영업중, 폐업, 취소,
상태 미상 row를 자체 source DB에 보존한다. `python-krtour-map`은 KRMOIS raw row를
`source_records`에 중복 저장하지 않는다. 안정된 `python-krmois-api` public model인
`PlaceRecord`를 읽고, 여행자에게 의미 있는 영업중 row만 feature table로 승격한다.

## 문서 정보

| 항목 | 값 |
| --- | --- |
| provider | `python-krmois-api` |
| dataset key | `krmois_license_features` |
| feature kind | `place` |
| source type | `license_place` |
| detail table | `feature_place_details` |
| 코드 entrypoint | `krtour_map.krmois` |

## 책임

- `python-krmois-api`: localdata 파일 다운로드, MOIS source DB 갱신, raw/localdata detail 보존,
  영업중/폐업 row iterator 제공.
- `python-krtour-map`: 영업중 `PlaceRecord` row를 `Feature`와 `PlaceDetail`로 변환하고,
  전체 갱신에서 오래된 KRMOIS feature를 삭제하며, Dagster job metadata를 제공.
- TripMate: Dagster 실행, MOIS source DB session, feature DB session, 선택적 reverse geocoder,
  transaction/alert 정책 제공.

이 package 사이에 wrapper, adapter, gateway를 추가하지 않는다. 누락된 endpoint, cursor,
pagination, raw 보존, status filtering 동작은 `python-krmois-api`에서 먼저 안정화한다.

## 주간 전체 갱신

`krmois_license_feature_full_update_job_spec`는 TripMate Dagster job을 설명한다.

- schedule: 주 1회
- source DB sync kind: `localdata_full`
- source DB updater: `python-krmois-api.sync_localdata_source_db(...)`
- 영업중 row reader: `python-krmois-api.iter_open_place_records(...)`
- feature loader: `load_krmois_license_feature_result(..., prune_existing=True)`
- 폐업/취소 처리: 폐업 feature는 보존하지 않고, 최신 영업중 snapshot에 없는 오래된 KRMOIS feature
  row를 제거한다.

증분 관리나 검수 도구가 필요하면 `python-krmois-api.iter_closed_place_records(...)`가 source DB의
폐업/취소 row를 반환한다. `python-krtour-map`은
`delete_krmois_license_features_for_records(...)`도 노출하므로, TripMate는 필요할 때 폐업 전용
record stream을 기준으로 feature를 제거할 수 있다.

## Feature 상세 계약

KRMOIS 전용 물리 컬럼은 의도적으로 만들지 않는다. 아래 값은 `Feature.detail`에 저장한다.

- `selected_source`: provider, source DB, dataset key, service slug, 관리번호, title,
  local authority code
- `selected_coordinate`: 선택된 WGS84 좌표와 원본 EPSG:5174 X/Y
- `category_confidence`: service slug를 `python-kraddr-base` category로 mapping한 confidence
- `match_level`: `AddressMatchReport`의 주소/geocoding match level
- `visible_status`: 승격된 KRMOIS row는 항상 `visible`
- `visible`: 승격된 row는 `true`
- `license_status`: source 상태 코드/이름과 detail 상태
- `license_dates`: 인허가/지정/갱신 시각
- `address_codes`: 원본 법정동/도로명/건물 코드와 보강된 법정동 match 결과

`Feature.raw_refs`에는 MOIS service slug와 관리번호에 대한 가벼운 source reference만 둔다.
전체 raw/localdata payload는 `python-krmois-api` source DB에 남긴다.

## 제외 service slug

아래 row는 MOIS source DB에 남기지만 지도 feature로 승격하지 않는다.

- `beauty_salons`, `barber_shops`
- `laundries`, `medical_laundry`
- `oil_retailers`, `petroleum_alt_fuel_retailers`, `lpg_equipment_manufacturers`
- `animal_hospitals`, `animal_pharmacies`, `pet_grooming`, `animal_boarding`
- `billiard_halls`, `video_viewing_rooms`, `karaoke_rooms`, `golf_practice_ranges`
- `dance_halls`, `dance_academies`, `film_screenings`, `pc_bangs`
- `optical_shops`, `over_the_counter_medicine_stores`

이 ETL에서는 이전에 논의한 반려동물, 도시 여가, MICE, 생활서비스 gap을 위해 새
`python-kraddr-base` category를 추가하지 않는다.

## 승격 feature별 상세

`PlaceDetail.facility_info`는 feature group별로 구성한다.

- medical: 병상/입원실 수, 의료인 수, 병실 수, 기관 유형, 진료 과목
- food: 위생업 상태, 급수시설 유형, 업종/세부 업종, 면적
- lodging: 시설 규모, 면적, 층수, 건물 용도, 다중이용 여부
- culture/leisure/activity: 문화체육 세부 유형, 지정일, 면적/층수 값
- retail: 판매 방식과 시설 규모

영업시간은 향후 안정된 provider model이 DTO 호환 opening-hours 필드를 노출하기 전까지 KRMOIS
인허가 row에서 추론하지 않는다. 이미지/파일 asset도 KRMOIS에서는 기대하지 않는다. media가 있는
provider는 계속 RustFS에 바이너리를 저장하고 `feature_files` metadata를 남긴다.

## 보류

관리번호 공백 row fingerprint 제안은 보류한다. 현재 feature identity는 `python-krmois-api`가
제공하는 안정된 `PlaceRecord.mng_no`를 사용한다. 관리번호 공백 row의 재동기화가 실제 데이터
문제가 되면 `python-krmois-api`에서 fingerprint를 먼저 구현하고 문서화한 뒤, 이 라이브러리가 그
public field를 소비한다.
