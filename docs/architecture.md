# python-krtour-map 아키텍처

## 목적

TripMate에는 지도 위에 올라가는 데이터가 여러 출처에서 들어옵니다. OpiNet 유가, KMA 날씨, KREX 휴게소, KHOA 해양지수, AirKorea 대기질, KTO 관광지, KRMOIS 인허가 데이터는 생김새가 다르지만 앱에서는 결국 지도 feature, feature weather, feature price, source trace로 써야 합니다.

`python-krtour-map`은 이 수렴 지점을 TripMate 밖의 작은 라이브러리로 분리합니다. provider SDK는 그대로 직접 사용하고, 반복되는 정규화와 저장 계약만 이 라이브러리가 맡습니다.

## 레이어

```text
python-*-api provider libraries
  -> provider typed model
  -> krtour_map parser/normalizer pure function
  -> Feature / SourceRecord / FeatureFile / PlaceDetail / EventDetail / AreaDetail / RouteDetail / NoticeDetail / WeatherValue / PriceValue
  -> krtour_map.db load helper
  -> RustFS objects + python-krtour-map feature DB or InMemoryFeatureStore
  -> TripMate API/Admin/UI
```

TripMate 전용 provider adapter는 만들지 않습니다. provider public client와 typed model이 부족하면 해당 `python-*-api` 라이브러리에 endpoint/model/cursor/helper를 upstream합니다.

`python-krtour-map`은 DTO만 제공하는 보조 계층이 아니라 feature/source/weather/price 저장소 schema의 소유자입니다. TripMate는 별도 feature DB를 만들지 않고 `krtour_map.db`의 schema와 함수를 사용해 앱 API와 화면 조립만 담당합니다. 사용자, 여행계획, POI는 TripMate 제품 도메인에 남기고, 필요한 경우 `feature_id`로 이 라이브러리의 feature를 참조합니다.

TripMate의 기존 feature 설계 문서는 [Feature model](feature-model.md)로 이관했습니다. TripMate 문서에는 제품 DB, API, Admin, 운영 runbook만 남기고 feature DTO/source/weather/price 저장 계약은 이 저장소를 canonical로 둡니다.

## 핵심 모델

| 모델 | 용도 |
| --- | --- |
| `Feature` | 지도에 올릴 공통 객체. `place`, `event`, `notice`, `price`, `weather`, `route`, `area`를 표현 |
| `SourceRecord` | provider 원천 row와 payload hash 보존 |
| `SourceLink` | feature와 source record의 관계. `primary`, `enrichment`, `weather_context` 등 역할 포함 |
| `FeatureFile` | RustFS에 저장된 이미지/동영상/문서/파일의 1:N 메타데이터 |
| `PlaceDetail` | 장소 상세. 전화, 리뷰 링크, 운영시간, 시설, 인허가 보조 정보를 구조화 |
| `EventDetail` | 축제/행사 기간, VisitKorea content id, 지역 코드, venue 정보를 구조화 |
| `AreaDetail` | 국가유산/국립공원/해변 같은 권역 geometry와 경계 출처 구조화 |
| `RouteDetail` | 등산로/무장애산책길/트래킹 같은 경로 세부 타입과 거리/시간/geometry 상태 구조화 |
| `NoticeDetail` | 산사태/통제/폐쇄 같은 지도 공지의 유효 구간과 심각도 구조화 |
| `WeatherValue` | feature 기준 날씨/대기질/해양 값을 provider, domain, forecast style, time axis로 저장 |
| `PricePoint`, `PriceValue` | 가격이 붙는 지점과 시계열 가격값 분리 |
| `ProviderSyncState` | provider+dataset+scope별 cursor, 성공/실패 상태 |

구현된 provider ETL:

- VisitKorea 축제: `Feature(kind="event")`, `EventDetail`, source trace, DB staged load
- VisitKorea 축제 이미지: `first_image`, `first_image2`를 RustFS에 적재하고 `FeatureFile` metadata 저장
- OpiNet 주유소 상세: `Feature(kind="place")`, `PlaceDetail`, `PricePoint`, `PriceValue`, source trace, DB staged load

## Feature ID

`feature_id`는 멱등 upsert를 위해 deterministic하게 생성합니다.

구성 요소:

- canonical provider name
- source type
- source natural key
- feature kind
- category
- `legal_dong_code` 또는 `global`
- content/payload hash

같은 원천 row가 반복 수집되어도 같은 feature ID가 만들어져야 합니다. payload가 달라졌지만 같은 장소/지점이면 source record hash는 바뀌어도 feature ID는 유지되도록 `source_natural_key`를 신중하게 잡습니다.

## Weather 병합

날씨 표시는 KMA timeline을 기준으로 합니다.

| provider | domain | 기준 |
| --- | --- | --- |
| `python-kma-api` | `kma_ultra_short_nowcast`, `kma_ultra_short_forecast`, `kma_short_forecast`, `kma_mid_forecast` | 전체 시간축 기준 |
| `python-krex-api` | `rest_area_weather` | 휴게소 feature의 관측/단기 context |
| `python-krairport-api` | `airport_weather` | 공항 feature context |
| `python-visitkorea-api` | `tourist_spot_weather` | 관광지 상세 날씨 보강 |
| `python-airkorea-api` | `air_quality` | 측정소/시도 단위 대기질 |
| `python-khoa-api` | `beach_marine` | 해수욕장/해양 지수 |

동일 `feature_id + provider + domain + forecast_style + metric_key + issued_at + valid_at + observed_at` 조합은 하나의 weather value로 upsert합니다.
`forecast_style`은 관측/예보/지수/특보 같은 원천 성격을 보존하고, KMA식 초단기/단기/중기 조회 축은 `timeline_bucket`(`ultra_short`, `short`, `mid`)에 별도로 둡니다. 상세 기준은 [Weather feature normalization](weather-feature-normalization.md)을 따릅니다.

## CRUD 경계

현재 구현된 `InMemoryFeatureStore`는 다음 목적입니다.

- provider debug UI에서 API 응답을 feature로 바꾸는 dry-run
- pytest fixture replay
- `python-krtour-map` DB 함수가 따라야 할 CRUD 의미 검증

운영 feature 저장소는 `python-krtour-map`의 DB schema를 기준으로 초기화하고, TripMate의 SQLAlchemy/PostGIS 코드는 사용자, 여행계획, POI 같은 제품 도메인과 API 조립을 맡습니다.
ETL이 만든 DTO 묶음은 `load_feature_rows` 또는 provider별 적재 helper로 열린 feature DB session에 staged write하고, TripMate가 트랜잭션 commit/rollback을 결정합니다.

## 테스트 전략

- 기본 테스트는 외부 API를 호출하지 않습니다.
- meaningful response는 JSON fixture로 저장합니다.
- pytest 공통 runner가 fixture를 읽어 parser, processor, assertion을 실행합니다.
- live/integration test는 별도 marker로 분리합니다.

## 후속 확장

- SQLAlchemy repository adapter는 TripMate DB 계약이 안정된 뒤 별도 모듈로 추가합니다.
- route/area geometry는 Shapely/PostGIS 경계가 필요하므로 현재 Pydantic DTO에서는 geometry payload를 강제하지 않습니다.
- Debug Web UI는 별도 패키지에서 `DebugRun`과 `save_fixture`를 사용합니다.
