# Feature model

이 문서는 TripMate의 기존 `map-feature-schema.md`에 있던 feature 설계 내용을 `python-krtour-map` 기준으로 정리한 canonical 문서다.

TripMate 안의 사용자, 여행계획, POI 문서는 TripMate에 남긴다. 지도 위에 올릴 수 있는 공통 객체, provider source trace, weather/price context, feature 저장 계약은 이 라이브러리가 소유한다.

## 책임 경계

`python-krtour-map`이 가진다:

- `Feature`, `FeaturePatch`, `SourceRecord`, `SourceLink`, `WeatherValue`, `PricePoint`, `PriceValue`, `ProviderSyncState` DTO
- `features`, `source_records`, `source_links`, `feature_weather_values`, `price_points`, `price_values`, `provider_sync_state`, `feature_overrides`, `dedup_review_queue`, `data_integrity_violations` 같은 feature DB metadata
- provider canonical name, `feature_id`, `source_record_key`, weather value key 생성 규칙
- provider typed model을 feature/source/weather/price 계약으로 바꾸는 순수 정규화 함수
- record linkage blocking/scoring, 중복 후보 검수 queue payload, data integrity violation payload
- debug fixture 저장, masking, replay helper

TripMate가 가진다:

- 사용자, 여행계획, POI, 권한, 알림, API serving 제품 테이블
- FastAPI endpoint, 인증/인가, Admin UI, 사용자 화면 응답 조립
- Dagster process, schedule, resource 주입, 운영 runbook
- 사용자가 저장한 여행/POI snapshot 보존 정책

TripMate는 feature DB를 복제하지 않는다. TripMate 제품 테이블은 필요한 경우 feature id 값을 참조하지만, feature table/column 정의는 이 라이브러리 문서를 따른다.

## Feature와 content

`Feature`는 지도에 실제로 올릴 수 있는 객체다. 좌표가 없거나 지도 객체가 아닌 설명형 콘텐츠는 feature가 아니다.

| 구분 | 기준 |
| --- | --- |
| `place` | 장소, 시설, 상점, 주차장, 화장실, 충전소, 전망 지점 |
| `event` | 축제, 공연, 전시, 장터, 체험처럼 기간성이 있는 지도 객체 |
| `route` | 산책로, 등산로, 자전거길, 드라이브 코스 |
| `area` | 국립공원, 해변, 관광특구, 시장 권역, 제한 구역 |
| `notice` | 폐쇄, 공사, 교통통제, 혼잡, 기상특보처럼 지도상 위치나 구역에 붙는 공지 |
| `weather` | weather layer나 weather-only marker가 필요한 경우의 feature |
| `price` | 주유소/충전소처럼 가격 시계열이 붙는 지점 feature |
| content | 기사, 큐레이션 목록, 여행 템플릿, 가이드. feature가 아니며 TripMate 제품 도메인이나 별도 content 도메인에서 관리한다. |

기상특보 전체, ETL 실패, 관리자 시스템 알림은 기본적으로 `notice` feature가 아니다. 특정 장소, 경로, 구역에 지도상으로 표현할 geometry와 사용자 의미가 있을 때만 `notice`로 승격한다.

## Core DTO

`Feature`의 핵심 필드:

- `feature_id`: provider, source type, source natural key, kind, category, legal dong code 또는 `global`, payload hash 기반 deterministic id
- `kind`: `place`, `event`, `notice`, `price`, `weather`, `route`, `area`
- `name`: 지도와 목록에 표시할 대표 이름
- `coord`: `kraddr.base.PlaceCoordinate`를 그대로 사용하는 대표 좌표. VisitKorea 축제처럼 provider 응답에 좌표가 없는 event는 `None`을 허용한다.
- `address`: `kraddr.base.Address`
- `category`: `python-kraddr-base` category code
- `urls`: 홈페이지, SNS, 리뷰 URL
- `marker_icon`, `marker_color`: 지도 표현 기본값
- `parent_feature_id`, `sibling_group_id`: 상위/형제 feature grouping
- `detail`: kind별 세부 payload
- `raw_refs`: provider source trace 요약
- `status`: `draft`, `active`, `inactive`, `hidden`, `broken`, `deleted`

TripMate의 과거 feature 문서는 구현 관점의 분리안이었다. 이 라이브러리의 현재 canonical 계약은 공통 `Feature` DTO와 `features` table이며, kind별 세부값은 우선 `detail` payload에 둔다. 별도 typed detail DTO나 table이 필요해질 때는 이 라이브러리에서 먼저 추가한다.

## Tree와 sibling

feature는 직접 부모 하나만 가진다. 다단계 tree는 `parent_feature_id`와 recursive CTE로 조회한다.

형제, 대체 후보, 같은 시설의 여러 표현처럼 같은 부모 아래에서 묶어야 하는 객체는 `sibling_group_id`를 공유한다. 이 값은 TripMate의 POI 순서나 사용자 저장 순서를 의미하지 않는다.

## Source trace

외부 provider row는 `SourceRecord`로 보존한다.

핵심 식별자:

- `provider`: canonical provider name. 예: `python-kma-api`, `python-krex-api`
- `dataset_key`: provider 안의 수집 단위
- `source_entity_type`: 원천의 타입
- `source_entity_id`: provider 안정 ID 또는 내부 natural key
- `raw_payload_hash`: 재처리와 drift 감지를 위한 payload hash
- `source_record_key`: 위 값으로 만든 deterministic key

feature와 source row의 관계는 `SourceLink`로 남긴다.

| `source_role` | 의미 |
| --- | --- |
| `primary` | feature 생성의 1차 원천 |
| `base_address` | 주소 보정 원천 |
| `base_coordinate` | 좌표 보정 원천 |
| `enrichment` | 부가 정보 보강 |
| `correction` | 운영자 또는 더 신뢰도 높은 원천으로 보정 |
| `duplicate_candidate` | 중복 후보 판단 근거 |
| `media` | 이미지/미디어 원천 |
| `weather_context` | 날씨, 대기질, 해양 context 원천 |

TripMate의 과거 provider/source 추적 문서는 이 source trace 계약으로 흡수한다. 중복 후보 검수 저장소가 필요할 때도 TripMate에 별도 feature 저장소를 만들지 않고 `python-krtour-map`의 `dedup_review_queue`를 사용한다.

## Record linkage

서로 다른 provider가 같은 장소나 구역을 가리키는지 판단할 때는 먼저 PostGIS 공간 blocking을 적용한다.

기본값:

- blocking 반경: 100m
- score weight: 이름 0.45, 공간 0.35, category 0.20
- 자동 병합: 85점 이상
- 검수 queue: 65점 이상 85점 미만
- 65점 미만: link하지 않고 source record만 보존

자동 병합 또는 검수 결과는 source trace가 남아야 한다. 운영자가 보정한 값은 `feature_overrides`에 남기고, provider payload 불일치나 필수 값 누락은 `data_integrity_violations`에 남긴다.

## Event와 opening hours

기간성이 있는 축제, 공연, 전시, 행사 feature는 `Feature(kind="event")`와 `EventDetail`을
함께 사용한다. `EventDetail`은 `starts_on`, `ends_on`, VisitKorea `content_id`,
`content_type_id`, 지역 코드, 전화번호, venue 정보를 담는다.

VisitKorea 축제 ETL은 `python-visitkorea-api`의 public client를 직접 사용한다. full scan은
`iter_pages(client.search_festival, ...)`로 모든 페이지를 순회하며, 기본 주기는 1일 1회다.

영업시간/운영시간 공통 자료는 [Feature opening hours](feature-opening-hours.md)를 따른다.
정규 구간은 `FeatureOpeningHours.periods`와 `feature_opening_periods`, 날짜별 예외는
`SpecialOpeningDay`와 `feature_special_days`를 사용한다.

## Weather와 price

Weather context는 `WeatherValue`와 `feature_weather_values`에 저장한다. KMA식 조회 축은 `timeline_bucket`, provider 원천 성격은 `forecast_style`로 분리한다.

예:

- KMA 초단기실황: `forecast_style="nowcast"`, `timeline_bucket="ultra_short"`
- 한국도로공사 휴게소 최신 날씨: `forecast_style="observed"`, `timeline_bucket="ultra_short"`
- 산불위험/산사태 위험: `forecast_style="index"` 또는 `advisory`, `timeline_bucket="short"`

세부 mapping은 [Weather feature normalization](weather-feature-normalization.md)을 따른다.

가격 정보는 지점 feature와 시계열 price value를 분리한다. OpiNet 주유소/충전소, KREX 휴게소 유가처럼 가격이 붙는 위치는 `Feature(kind="price")` 또는 장소 feature에 price context를 연결하는 방식으로 다룬다. 지점성은 `price_points`, 시계열 값은 `price_values`에 저장한다.

## 보존 정책

- event: 종료 후 20년
- notice: 종료 후 1년
- weather: 30일
- price: `price_points.retention_days`
- source raw payload: 재처리와 schema drift 감지를 위해 feature 보존 기간보다 짧게 잡지 않는다.

## Provider 사용

TripMate와 `python-krtour-map`은 provider별 wrapper/adapter/gateway를 만들지 않는다.

허용되는 경계:

- provider public client 직접 호출
- provider typed model을 `Feature`, `SourceRecord`, `WeatherValue`, `PriceValue`로 바꾸는 순수 함수
- 이 라이브러리의 DB metadata와 row helper 사용

부족한 endpoint, typed model, pagination, cursor, exception, raw payload 보존 규칙은 해당 `python-*-api` 저장소에서 먼저 보강한다.

## TripMate 문서에서 이관된 결정

TripMate의 feature 관련 문서는 이 라이브러리의 canonical 계약으로 옮긴다.

- 공통 지도 객체: `Feature` DTO와 `features`
- feature 종류: `Feature.kind`
- provider source 원천: `SourceRecord` DTO와 `source_records`
- feature/source 관계: `SourceLink` DTO와 `source_links`
- weather context: `WeatherValue` DTO와 `feature_weather_values`
- price context: `PricePoint`, `PriceValue`, `price_points`, `price_values`
- provider cursor: `ProviderSyncState`와 `provider_sync_state`
- 중복 검수/운영 보정/무결성 위반: `dedup_review_queue`, `feature_overrides`, `data_integrity_violations`
- 사용자, 여행계획, POI snapshot, content/article/itinerary template: TripMate 제품 도메인

## 테스트 기준

feature 관련 변경은 최소한 아래를 확인한다.

- `Feature` DTO validation: kind, category, 한국 지도 좌표 bounds
- deterministic `feature_id`와 `source_record_key`
- provider alias가 canonical provider name으로 저장되는지
- `SourceLink` role과 confidence 범위
- weather value identity와 latest 병합
- fixture replay가 외부 API 없이 동일 결과를 내는지
- TripMate가 별도 feature DB/table을 만들지 않고 `krtour_map.db` metadata와 helper를 import하는지
