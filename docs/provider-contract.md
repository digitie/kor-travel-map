# Provider 계약

## Canonical provider name

문서, DB, API 응답에는 canonical provider name만 사용합니다.

| Provider | 역할 |
| --- | --- |
| `python-kraddr-base` | 주소, 좌표, 카테고리 공통 타입 |
| `python-kraddr-geo` | Juso/주소 TXT/PostGIS 주소점, reverse geocoding |
| `python-vworld-api` | VWorld 검색, geocoder, 경계, OGC |
| `python-visitkorea-api` | KTO 관광지, 숙박, 행사/축제, 이미지, 증분 동기화 |
| `python-krmois-api` | 지방행정 인허가 데이터. place feature의 1차 원천 |
| `python-opinet-api` | 주유소와 유가 source |
| `python-krex-api` | 고속도로, 휴게소, 휴게소 날씨와 유가 source |
| `python-kma-api` | 초단기/단기/중기/특보, DFS grid |
| `python-krairport-api` | 공항 운항, 주차, 혼잡, 공항/도시 날씨 |
| `python-khoa-api` | 해수욕장, 해양지수, 조석, 파고, 수온 |
| `python-airkorea-api` | PM10, PM25, CAI, 예보/경보 |
| `python-mcst-api` | 문화/여가/숙박/도서관 위치 데이터 |
| `python-krforest-api` | 휴양림, 숲길, 국립공원, 산림 안전 |

`pykma`, `kma`, `opinet`, `krex` 같은 alias는 입력 편의로만 받아들이고 저장 전에 canonical name으로 바꿉니다.

## Adapter 금지

TripMate 내부와 `python-krtour-map` 내부에 provider별 adapter/gateway/wrapper를 새로 만들지 않습니다.

외부 API 관련 작업을 시작할 때는 이 원칙을 제일 먼저 반영합니다. 안정된 provider public client와 typed model을 직접 사용하고, 부족한 인터페이스는 TripMate 임시 계층이 아니라 해당 `python-*-api` 저장소에서 먼저 보강합니다.

허용되는 경계:

- provider public client 직접 호출
- provider typed model을 `Feature`, `SourceRecord`, `WeatherValue`, `PriceValue`로 바꾸는 순수 함수
- DB 저장 repository

부족한 endpoint, pagination, typed model, cursor, exception, raw payload 보존 규칙은 해당 provider 라이브러리에서 빠르게 안정화합니다.

금지되는 경계:

- 안정된 public API를 단순 전달하는 `KmaWrapper`, `VWorldAdapter`, `OpiNetGateway` 같은 중간 계층
- 기존 호출부 수정을 피하기 위한 장기 호환 alias/facade
- provider별 예외와 응답 모델을 TripMate 안에서 다시 정의하는 임시 계층

## Source role

`SourceRole`은 하나의 source row가 feature에 어떤 역할로 붙었는지 나타냅니다.

| Role | 의미 |
| --- | --- |
| `primary` | feature 생성의 1차 원천 |
| `base_address` | 주소 보정 원천 |
| `base_coordinate` | 좌표 보정 원천 |
| `enrichment` | 부가 정보 보강 |
| `correction` | 운영자 또는 더 신뢰도 높은 원천으로 보정 |
| `duplicate_candidate` | 중복 후보 판단 근거 |
| `media` | 이미지/미디어 원천 |
| `weather_context` | 날씨/대기질/해양 context 원천 |

## Dataset key

`dataset_key`는 provider 안의 수집 단위를 식별합니다.

예:

- `fuel_lowest_station`
- `fuel_avg_price`
- `rest_area_weather`
- `weather_short_term`
- `weather_mid_term`
- `forest_mountain_weather`
- `forest_fire_risk`
- `forest_landslide_risk`
- `air_quality_sido_measurement`
- `beach_marine_index`

Weather source는 provider public client를 직접 호출한 뒤 `WeatherValue`로 정규화한다. `forecast_style`에는 관측/예보/지수/특보 성격을 남기고, KMA식 초단기/단기/중기 분류는 `timeline_bucket`에 둔다. 세부 mapping은 `docs/weather-feature-normalization.md`를 따른다.

Feature/source/weather/price 저장소는 `python-krtour-map`의 DB 계약이다. TripMate는 별도 feature DB를 정의하지 않고 `krtour_map.db` schema와 함수를 import해 사용한다.

provider cursor와 실패 상태는 `ProviderSyncState(provider, dataset_key, sync_scope)` 단위로 저장합니다.
