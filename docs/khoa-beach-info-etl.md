# KHOA 해수욕장정보 장소 ETL

TripMate의 해수욕장 장소 feature는 `python-khoa-api`가 제공하는
`KhoaClient.oceans_beach_info()` / `KhoaClient.iter_oceans_beach_info_pages()`를
직접 사용한다. 중간에 `KhoaBeachWrapper`, `BeachInfoAdapter` 같은 전달 계층을
두지 않는다. 해당 public API가 부족하면 먼저 `python-khoa-api`에서 endpoint,
typed model, pagination, raw payload 보존을 안정화한 뒤 이 라이브러리의 feature
정규화로 연결한다.

## 문서 정보

| 항목 | 값 |
| --- | --- |
| provider | `python-khoa-api` |
| `dataset_key` | `khoa_oceans_beach_info` |
| `Feature.kind` | `place` |
| `source_entity_type` | `beach` |
| 상세 테이블 | `feature_place_details` |
| 코드 entrypoint | `krtour_map.beaches` |

## Provider 엔드포인트

- 공공데이터포털 상세: <https://www.data.go.kr/data/15058519/openapi.do>
- 요청 URL:
  `http://apis.data.go.kr/1192000/service/OceansBeachInfoService1/getOceansBeachInfo1`
- 필수 파라미터: `ServiceKey`, `SIDO_NM`
- 페이지 파라미터: `pageNo`, `numOfRows`
- 결과 형식: `resultType=JSON`

응답 row는 `python-khoa-api`의 `OceanBeachInfo` DTO로 변환한 뒤 사용한다.

## Feature 매핑

`khoa_oceans_beach_info` dataset은 해수욕장을 `place` feature로 적재한다.

- provider: `python-khoa-api`
- dataset key: `khoa_oceans_beach_info`
- `source_entity_type`: `beach`
- source natural key: `시도|구군|정점명`
- `Feature.kind`: `place`
- category: `python-kraddr-base`의 `TOURISM_NATURE_BEACH` (`01050100`)
- marker icon: `beach`
- marker color: `#0077B6`

원문 필드는 아래처럼 보존/정규화한다.

- `sidoNm`, `gugunNm`, `staNm`: feature 이름, natural key, facility payload
- `lat`, `lon`: `kraddr.base.PlaceCoordinate(lat, lon)`
- `beachWid`, `beachLen`, `beachKnd`: `feature_place_details.facility_info`
- `linkAddr`: `features.urls.homepage`
- `linkNm`: detail payload
- `linkTel`: `PlaceDetail.phones`
- `beachImg`: RustFS 적재 후보 `FeatureFileSource`
- 전체 row: `source_records.raw_data`

주소는 provider row에 시도/구군 수준만 있으므로 기본 `Address(address="시도 구군")`
를 만들고, `reverse_geocoder` callable 또는 `kraddr_geo_*` resource가 있으면 좌표 기준
법정동코드와 도로명/지번 주소를 보강한다. 역지오코딩 구현은 `python-kraddr-geo`
public API를 사용한다. VWorld fallback이 필요하면 `python-kraddr-geo` store 설정으로
처리하고, 이 라이브러리는 `python-vworld-api`를 직접 로드하지 않는다.

## RustFS

`beachImg`가 `http://` 또는 `https://` URL이면 ETL은 `FeatureFileSource`를 만든다.
TripMate가 `rustfs_store` resource를 넘긴 경우 `upload_feature_file_sources_to_rustfs`
가 이미지를 내려받아 RustFS에 저장하고 `feature_files`에 1:N metadata를 남긴다.
상대 경로나 파일명처럼 내려받을 수 없는 값은 raw payload와 detail payload에만
보존한다.

## Dagster 경계

실제 Dagster daemon, schedule, transaction commit/rollback은 TripMate가 담당한다.
이 라이브러리는 아래 순수 loader body와 job spec만 제공한다.

- `collect_khoa_oceans_beach_info`
- `load_khoa_oceans_beach_info_result`
- `collect_and_load_khoa_oceans_beach_info`
- `load_khoa_oceans_beach_info`
- `khoa_oceans_beach_info_full_scan_job_spec`

기본 full scan은 `iter_oceans_beach_info_pages()`가 제공하는 모든 시도/페이지를
순회한다. 운영 schedule은 1일 1회를 기본으로 잡고, 긴급 제한이 필요할 때만
TripMate config에서 `max_pages`를 넘긴다.

## DB 스키마

새 전용 table은 만들지 않는다. 기존 feature DB 계약으로 충분하다.

- `features`: 해수욕장 장소 feature
- `source_records`: 공공데이터포털 원문 row와 payload hash
- `source_links`: feature와 source row의 primary 관계
- `feature_place_details`: 해변 폭/연장, 특징, 비상연락처 등 장소 상세
- `feature_files`: RustFS 이미지 metadata

중복/보강 정책은 krmois baseline 원칙과 충돌하지 않는다. krmois 인허가 데이터가
있는 업종/장소는 krmois source를 기준으로 삼고, 해수욕장정보는 해수욕장 장소의
공식 위치·특성·이미지 보강 source로 연결한다.
