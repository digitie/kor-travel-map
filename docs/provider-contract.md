# provider-contract.md — Provider 계약과 wrapper 금지 원칙

## 1. 핵심 원칙 (ADR-006)

본 라이브러리는 **provider client에 대한 wrapper/adapter/gateway를 새로 만들지
않는다**. `python-*-api` 라이브러리의 안정된 public client와 typed model을 그대로
사용하고, 결과를 `Feature`/`SourceRecord`/`SourceLink`/`WeatherValue`/`PriceValue`/
`FeatureFileSource`로 정규화하는 **순수 함수**만 둔다.

### 1.1 허용

- `python_visitkorea_api.AsyncVisitKoreaClient`를 그대로 import.
- 그 client를 호출해서 받은 typed model을 인자로 받는 변환 함수
  (`providers.visitkorea.festival_to_bundles(items)`).
- 변환 함수는 모듈 함수 또는 `@staticmethod`. 인스턴스 상태 없음.

### 1.2 금지

- `class VisitKoreaWrapper`, `class KmaGateway`, `class OpiNetAdapter` 같은 layer.
- "단순 전달용" alias 모듈 (`from python_visitkorea_api import ... as VKAPI`).
- provider client 메서드의 시그니처를 바꾸는 facade.
- pagination/cursor를 라이브러리 안에서 재구현 (provider 라이브러리 책임).

### 1.3 부족한 endpoint/model

provider 라이브러리에 부족한 endpoint, typed model, raw payload 보존이 발견되면
**해당 `python-*-api` 저장소에서 먼저 고친다**. 본 라이브러리/TripMate에 임시
facade를 만들지 않는다.

### 1.4 로컬 우선 조회 + 데이터 정합성 책임 (ADR-044)

- **조회**: provider 라이브러리의 client·model·codes·스펙을 확인할 때는
  `F:\dev\` (WSL `~/dev/`) 아래 **로컬 체크아웃을 1차 source**로 본다
  (`F:\dev\python-*-api/src/...`). GitHub 원격 fetch는 로컬에 없을 때만
  fallback — GitHub 404/private는 "미존재" 근거가 아니다.
- **데이터 정합성**: 코드 매핑(예: OpiNet 제품코드 `B027`/`C004`/`K015`),
  필드 의미, 단위, 분류값의 **1차 책임은 각 provider 라이브러리**에 있다. 본
  라이브러리는 그 정의를 **신뢰·미러**하고 재정의·재해석하지 않는다(변환만).
  불일치 발견 시 **provider 라이브러리(+공식 API 스펙) 기준**으로 정렬하고
  필요하면 그 라이브러리에 직접 PR로 수정한다.
- 사례: PR#53에서 본 lib `OPINET_PRODUCT_KEY_MAP`이 upstream `python-opinet-
  api` `codes.py` 및 OpiNet 공식 스펙과 `C004`/`K015`가 뒤바뀌어 있던 것을
  upstream 기준으로 정렬.

## 2. canonical provider name

`core.providers.CANONICAL_PROVIDER_NAMES`:

```
python-kraddr-base
python-kraddr-geo
python-visitkorea-api
python-mois-api
python-opinet-api
python-krex-api
python-kma-api
python-krairport-api
python-khoa-api
python-datagokr-api
python-airkorea-api
python-mcst-api
python-krforest-api
python-krheritage-api
python-knps-api
python-kasi-api
data.go.kr-standard
google-places-api-new
kakao-local-api
naver-search-api
manual
system
```

`normalize_provider_name(value)`가 짧은 alias(`kma`, `opinet`, `visitkorea`,
`pykma`, ...)를 canonical로 변환한다. DB에는 항상 canonical name 저장.

## 3. dataset_key 명명 규약

`{provider_short}_{dataset_name}_{scope?}` 형태. 예:

| dataset_key | provider | 의미 |
|------------|----------|------|
| `visitkorea_festival_events` | python-visitkorea-api | 축제/행사 검색 |
| `visitkorea_tourist_attractions` | python-visitkorea-api | 관광지 |
| `mois_license_features_bulk` | python-mois-api | 인허가 영업중 snapshot (place 승격) |
| `mois_license_features_history` | python-mois-api | 이력조회 기반 incremental |
| `mois_license_features_closed` | python-mois-api | 폐업/취소 처리 |
| `mois_license_detail` | python-mois-api | on-demand detail (캐시만) |
| `opinet_fuel_station_details` | python-opinet-api | 주유소 detail + 가격 |
| `krex_rest_areas` | python-krex-api | 고속도로 휴게소 |
| `krex_rest_area_prices` | python-krex-api | 휴게소 유가 시계열 |
| `krex_rest_area_weather` | python-krex-api | 휴게소 관측 weather |
| `krex_traffic_notices` | python-krex-api | 교통 공지 |
| `kma_short_forecast` | python-kma-api | 단기예보 |
| `kma_ultra_short_nowcast` | python-kma-api | 초단기실황 |
| `kma_mid_forecast` | python-kma-api | 중기예보 |
| `kma_weather_alerts` | python-kma-api | 특보 |
| `khoa_oceans_beach_info` | python-khoa-api | 해수욕장 정보 |
| `khoa_coastal_notices` | python-khoa-api | 해양 공지 |
| `krforest_recreation_forests` | python-krforest-api | 휴양림 |
| `krforest_arboretums` | python-krforest-api | 수목원 |
| `krforest_trails` | python-krforest-api | 숲길/등산로 |
| `krforest_mountain_weather` | python-krforest-api | 산악기상 |
| `krforest_safety_notices` | python-krforest-api | 산림 안전 공지 |
| `krheritage_heritage_features` | python-krheritage-api | 국가유산 search_list |
| `krheritage_gis_spca` | python-krheritage-api | 사적/명승 boundary |
| `krheritage_gis_3070426` | python-krheritage-api | 천연기념물 boundary |
| `krheritage_event_list` | python-krheritage-api | 국가유산 행사 |
| `knps_park_boundaries` | python-knps-api | 국립공원 경계 (area, MultiPolygon, SHP) |
| `knps_trails` | python-knps-api | 국립공원 탐방로 (route, LineString) |
| `knps_linear_facilities` | python-knps-api | 국립공원 선형시설 (route, `route_type='facility_road'`) |
| `knps_visitor_centers` | python-knps-api | 탐방안내소 (place) |
| `knps_hazard_zones` | python-knps-api | 위험지역 (area, `area_kind='hazard_zone'`, ADR-027) |
| `knps_protected_areas` | python-knps-api | 특별보호구역 (area, `area_kind='protected_area'`) |
| `knps_weather_stations` | python-knps-api | 산악 기상관측시설 (weather anchor) |
| `knps_restrooms` | python-knps-api | 국립공원 화장실 (place) |
| `knps_cultural_resources` | python-knps-api | 국립공원 문화자원 (place, RESOURCE_TYPE 분기) |
| `knps_campgrounds` | python-knps-api | 야영장 (place) |
| `knps_shelters` | python-knps-api | 대피소·산장 (place, `LODGING_MOUNTAIN_SHELTER_KNPS`, ADR-027) |
| `knps_basic_statistics` | python-knps-api | 기초통계 (feature 본문 X, timeseries, `needs_verification`) |
| `knps_visitor_statistics` | python-knps-api | 월별 탐방객 통계 (feature 본문 X, timeseries) |
| `knps_lod_table_catalog` | python-knps-api | LOD 메타 카탈로그 (적재 안 함, upstream 보강용) |
| ~~`knps_recommended_courses`~~ | ~~python-knps-api~~ | knps-api PR#3 source 삭제 — visitkorea/scrape로 이전 |
| ~~`knps_park_photos`~~ | ~~python-knps-api~~ | knps-api PR#3 source 삭제 — KNPS web 직접 fetch |
| ~~`knps_access_restrictions`~~ | ~~python-knps-api~~ | knps-api PR#3 source 삭제 — `python-krforest-api`/scrape로 이전 (별도 ADR) |
| ~~`knps_fire_alerts`~~ | ~~python-knps-api~~ | knps-api PR#3 source 삭제 — 소방청/산림청으로 이전 (별도 ADR) |
| `standard_tourism_roads` | data.go.kr-standard | 관광길 표준데이터 |
| `standard_museums` | data.go.kr-standard | 박물관·미술관 표준 |
| `standard_parking_lots` | data.go.kr-standard | 주차장 표준 |
| `standard_tourist_sites` | data.go.kr-standard | 관광지 표준 |
| `standard_cultural_festivals` | data.go.kr-standard | 문화축제 표준 |
| `place_phone_enrichment` | kakao-local-api / naver-search-api / google-places-api-new | 전화번호 보강 |

신규 추가는 ADR + `docs/<provider>-feature-etl.md`.

## 4. provider 카탈로그 (책임 매트릭스)

| provider | FeatureKind | source_role | 갱신 주기 | 비고 |
|----------|-------------|-------------|----------|------|
| provider | FeatureKind | source_role | 갱신 주기 | 비고 |
|----------|-------------|-------------|----------|------|
| **data.go.kr-standard (via `python-datagokr-api`)** | event, place, route | primary | 표준데이터별 (행안부 announce) | **1차 source** for 축제(ADR-042) + 관광지 5종 dataset. Protocol `CulturalFestivalItem` (PR#34) |
| python-visitkorea-api | event, place | **enrichment** (축제, ADR-042 supersede) / primary (그 외) | 일 1회 | 축제는 좌표 nullable 허용. ADR-042 (2026-05-27) 이후 datagokr 1차 + visitkorea 2차 |
| python-mois-api | place | primary | 주 1회 (full) + 일 1회 incremental + on-demand | 영업중 + PROMOTED_SERVICE_SLUGS (42종) 승격, EXCLUDED 제외 — `docs/mois-feature-etl.md` |
| python-opinet-api | place + price | primary | hours (가격), 일 (상세) | PriceValue 시계열 |
| python-krex-api | place + price + weather + notice | primary | 시간/분 단위 | 휴게소 + 교통 공지 |
| python-kma-api | weather | weather_context | 분/시간 | nowcast/short/mid + 특보. Protocol `KmaShortForecastItem` (PR#38) / `KmaUltraShortNowcastItem` (PR#39) |
| python-krairport-api | weather, place | weather_context, enrichment | 시간 | 공항 운항·날씨 |
| python-khoa-api | place, notice, weather | primary, primary, weather_context | 일 / 시간 | 해수욕장, 해양 공지 |
| python-airkorea-api | weather | weather_context | 시간 | PM10/PM2.5/CAI |
| python-krforest-api | place, route, area, weather, notice | primary | 일/시간 | 휴양림/숲길/산악기상/안전공지 |
| python-knps-api | place, route, area, weather | primary | 월/분기/연 (파일 데이터) | keyless file-only. 국립공원 경계·탐방로·선형시설·시설·위험지역·특별보호구역·문화자원·대피소 (`docs/knps-feature-etl.md`, ADR-028 amendment) |
| python-krheritage-api | place, area, event | primary | 주 (place/area), 일 (event) | media → RustFS |
| python-kasi-api | (calendar) | (system) | 주 1회 | 공휴일/달력 (TripMate utility) |
| python-datagokr-api (data.go.kr-standard) | event, place, route | primary | 표준데이터별 | 5종 dataset bounded. 본 lib에서 직접 사용 (ADR-042) — 위 첫 행 참조 |
| python-mcst-api | place | enrichment | 일 | 독립서점/북카페/도서관 — MOIS에 enrichment |
| kakao-local-api | place | enrichment | on-demand | 전화번호 보강 |
| naver-search-api | place | enrichment | on-demand | 전화번호 보강 |
| google-places-api-new | place | enrichment | on-demand | 전화번호 보강 (Text Search New) |
| python-kraddr-geo | (geocoder) | base_address, base_coordinate | on-demand | 주소·좌표 보강. `krtour.map.geocoding.KraddrGeoRestClient`가 REST `/v1/address/*` 호출. 로컬 FastAPI 기본 `http://127.0.0.1:8888` |
| ~~python-kraddr-base~~ | — | — | — | **ADR-041 (PR#37, 2026-05-28) 흡수 완료**. `Address` DTO + `core/address.py` utility는 본 lib로 이전. `PlaceCoordinate`는 명시적 제외 (좌표는 `Coordinate` 단일). archive 후보. |

## 5. provider 모듈 표준 구조

`src/krtour/map/providers/<name>.py`:

```python
"""<provider> 변환 모듈.

라이브러리는 <python-NAME-api>의 public client/typed model을 직접 사용하고,
본 모듈에서 raw → DTO 변환만 수행한다 (ADR-006).
"""
from __future__ import annotations

from krtour.map.dto import (
    Feature, FeatureKind, FeatureStatus,
    PlaceDetail,  # or EventDetail / ...
    SourceRecord, SourceLink, SourceRole,
    RawDataRef, FeatureBundle,
)
from krtour.map.core.ids import make_feature_id, make_source_record_key, make_payload_hash
from krtour.map.core.providers import normalize_provider_name

PROVIDER: Final[str] = "python-<NAME>-api"
DATASET_KEY: Final[str] = "<short>_<dataset>"
SOURCE_ENTITY_TYPE: Final[str] = "<entity_type>"
CATEGORY: Final[str] = "<PlaceCategoryCode value>"
MARKER_ICON: Final[str] = "<maki>"
MARKER_COLOR: Final[str] = "P-NN"
FULL_SCAN_INTERVAL_DAYS: Final[int] = 7  # 또는 1, 30 ...


def <entity>_to_bundle(item: <ProviderTypedModel>, *, fetched_at: datetime) -> FeatureBundle:
    """provider typed model → FeatureBundle.
    
    순수 함수. 부수효과 없음. DB/HTTP/파일시스템 의존 없음.
    """
    raw = item.model_dump()                      # provider model이 pydantic이라면
    payload_hash = make_payload_hash(raw)
    source_record_key = make_source_record_key(
        provider=PROVIDER,
        dataset_key=DATASET_KEY,
        source_entity_type=SOURCE_ENTITY_TYPE,
        source_entity_id=str(item.id),
        raw_payload_hash=payload_hash,
    )
    feature_id = make_feature_id(
        bjd_code=_extract_bjd(item),             # provider 모델에서 추출
        kind=FeatureKind.PLACE,
        category=CATEGORY,
        source_type=SOURCE_ENTITY_TYPE,
        source_natural_key=str(item.id),
    )
    feature = Feature(
        feature_id=feature_id,
        kind=FeatureKind.PLACE,
        name=item.name,
        coord=_coord(item),
        address=_address(item),
        category=CATEGORY,
        marker_icon=MARKER_ICON,
        marker_color=MARKER_COLOR,
        raw_refs=[RawDataRef(
            provider=PROVIDER,
            dataset_key=DATASET_KEY,
            source_entity_id=str(item.id),
            source_role=SourceRole.PRIMARY,
            fetched_at=fetched_at,
            payload_hash=payload_hash,
        )],
    )
    detail = PlaceDetail(
        feature_id=feature_id,
        place_kind="...",
        phones=[item.tel] if item.tel else [],
        # ...
    )
    feature.detail = detail
    source_record = SourceRecord(
        provider=PROVIDER, dataset_key=DATASET_KEY,
        source_entity_type=SOURCE_ENTITY_TYPE, source_entity_id=str(item.id),
        raw_payload_hash=payload_hash,
        raw_data=raw,
        fetched_at=fetched_at,
        source_record_key=source_record_key,
    )
    source_link = SourceLink(
        feature_id=feature_id,
        source_record_key=source_record_key,
        source_role=SourceRole.PRIMARY,
        match_method="natural_key",
        confidence=100,
        is_primary_source=True,
    )
    return FeatureBundle(
        feature=feature,
        source_record=source_record,
        source_link=source_link,
    )


def <entity>_to_bundles(items: Iterable[<ProviderTypedModel>],
                        *, fetched_at: datetime | None = None) -> Iterator[FeatureBundle]:
    ts = fetched_at or kst_now()
    for item in items:
        yield <entity>_to_bundle(item, fetched_at=ts)
```

## 6. 변환 함수 검증 룰

각 provider 변환 함수는 다음을 만족해야 한다:

- **결정성** — 같은 입력 → 같은 `feature_id`, `source_record_key`, `payload_hash`.
- **순수성** — DB/HTTP/파일시스템 의존 없음. 시간은 인자로 받음.
- **idempotent** — 결과 bundle을 두 번 적재해도 row 1개 (`ON CONFLICT DO
  UPDATE`).
- **좌표 검증** — 한국 영역 밖이면 `coord=None` + `data_integrity_violations`에
  `violation_type='F1_coord_outside_bjd'` 또는 `'coord_outside_korea'` 기록.
- **payload 보존** — `SourceRecord.raw_data`에 provider 원문 dict 전체.
  `raw_payload_hash`가 다르면 새 source_record (schema drift 감지).
- **media URL** — PR#26 최소 `FeatureBundle`에는 포함하지 않는다.
  `FeatureFileSource` DTO가 구현되는 후속 PR에서 리스트로 모으고, 실제 업로드는
  `client.upload_feature_files(sources)`가 별도 단계에서 수행.

## 7. 적재 흐름

```python
# TripMate 측 (Dagster asset)
async with AsyncKrtourMapClient(engine=engine, file_store=store, providers={...}) as client:
    # 1. provider 호출 (provider 라이브러리 직접 사용)
    items = list(visitkorea_client.search_festival(...))
    
    # 2. 변환 (라이브러리 facade)
    bundles = list(client.providers.visitkorea.festival_to_bundles(items))
    
    # 3. DB 적재
    result = await client.load_feature_bundles(bundles)
    
    # 4. sync state 갱신
    await client.upsert_sync_state(ProviderSyncState(
        provider="python-visitkorea-api",
        dataset_key="visitkorea_festival_events",
        last_success_at=kst_now(),
        cursor={"last_pageNo": items[-1].pageNo if items else None},
    ))
```

## 8. enrichment provider 처리

`kakao-local-api`, `naver-search-api`, `google-places-api-new`,
`python-mcst-api`는 enrichment 전용. 다음 규약:

- 새 feature를 만들지 않는다 — 기존 feature를 찾아서 `SourceLink
  (source_role='enrichment')` + 필드 보강.
- 보강 대상은 명시적으로 제한 (예: place 전화번호만, 리뷰 링크만).
- 자체 좌표/주소는 신뢰도 낮음 — 기존 `coord`/`address`를 덮어쓰지 않는다
  (`source_role='correction'`로 명시 시에만 가능).
- `match_method`는 `'place_phone_search'`, `'mcst_natural_key'` 등 구체적으로.

## 9. weather provider 처리

KMA를 본축으로 두고 다른 weather provider는 같은 `valid_at`의 부가 source.
WeatherValue로 일관 적재.

| provider | weather_domain | forecast_style | timeline_bucket |
|----------|----------------|----------------|----------------|
| python-kma-api | `kma_ultra_short_nowcast` | nowcast | ultra_short |
| python-kma-api | `kma_short_forecast` | short | short |
| python-kma-api | `kma_mid_forecast` | mid | mid |
| python-krforest-api | `forest_mountain_weather` | observed | ultra_short |
| python-krforest-api | `forest_fire_risk` | index | short |
| python-krex-api | `rest_area_weather` | observed | ultra_short |
| python-khoa-api | `beach_marine` | index | short |
| python-airkorea-api | `air_quality` | observed | ultra_short |
| python-krairport-api | `airport_weather` | observed | ultra_short |
| data.go.kr-standard (농업기상) | `agri_weather` | observed | ultra_short |
| data.go.kr-standard (k-water sluice) | `hydro_weather` | observed | ultra_short |

상세 metric_key 매핑은 별도 문서(`weather-feature-normalization.md`,
코드 작성 단계에서 v1 docs를 v2 기준으로 정리해 옮긴다).

## 10. provider별 ETL 문서 표준 10섹션

`docs/<provider>-feature-etl.md`는 다음 10섹션 구조를 따른다:

1. 문서 정보: provider, dataset_key, FeatureKind, source_entity_type, 갱신 주기,
   entrypoint
2. 범위: 책임 분리 (provider 라이브러리 vs 본 라이브러리 vs TripMate)
3. Provider 경계: public client/typed model 직접 사용, wrapper 금지 재확인
4. Dataset 매핑: natural key, FeatureKind, detail table, source_role
5. 주소/좌표: 본 저장소 DTO (`Address`, `Coordinate`) + `core/address.py`
   utility, `python-kraddr-geo` REST geocoding, match report
6. 파일: RustFS 적재 대상, FeatureFileSource 매핑
7. DB 적재: collect/load 함수, transaction owner, prune 정책
8. Dagster: TripMate가 정의하는 asset 이름, schedule
9. 검증: unit/integration/fixture 케이스
10. 후속: provider 라이브러리에서 먼저 할 일

기존 v1 docs(`docs/event-feature-etl.md` 등)는 코드 작성 단계 진입 시 v2
기준으로 일괄 정리해 옮긴다 (`v1` 브랜치에서 참고).

## 11. wrapper 금지 자동 검증 (제안)

`tests/unit/test_no_provider_wrapper.py` (코드 작성 단계):

```python
def test_no_provider_wrapper_classes():
    # providers/ 모듈에는 class가 facade 외에는 정의되지 않는다.
    # 단순 함수와 dataclass만 허용.
    forbidden_class_names = (
        # *Wrapper, *Gateway, *Adapter, *Facade(except top facade)
        re.compile(r".*(Wrapper|Gateway|Adapter)$"),
    )
    for path in Path("src/krtour/map/providers").rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for pat in forbidden_class_names:
                    assert not pat.match(node.name), f"forbidden wrapper class: {node.name} in {path}"
```

상기 룰은 ADR-006의 자동 강제 수단으로 코드 작성 단계에서 도입.

## 12. provider 라이브러리 git URL + commit sha 핀 (status 표)

`pyproject.toml`의 `providers` extra. 특정 sha 핀은 reproducible build를
보장한다 — 업그레이드는 ADR + journal 기록. 현재 상태:

| provider | pyproject 핀 | 본 lib Protocol | 활성 PR | 메모 |
|----------|--------------|-----------------|---------|------|
| python-kraddr-base | **제거** | — | — | ADR-041 (PR#37) 흡수 완료. archive 후보 |
| python-kraddr-geo | REST 서비스(직접 의존 없음) | `KraddrGeoRestClient` + `ReverseGeocoder`/`AddressGeocoder` 콜러블 | PR#90/#123 | on-demand geocoder. 최신 로컬 FastAPI 포트 `8888` 기준 |
| python-datagokr-api | placeholder | `CulturalFestivalItem` (PR#34) | PR#34 | ADR-042 1차 축제 source |
| python-kma-api | placeholder | `KmaShortForecastItem` (PR#38), `KmaUltraShortNowcastItem` (PR#39) | PR#38/39 | ADR-010 두 축. 후속: ultra_short_forecast/mid/alerts |
| python-airkorea-api | placeholder | (후속 PR) | — | PM10/PM2.5/CAI |
| python-khoa-api | placeholder | (후속 PR) | — | 해수욕장, 해양 공지 |
| python-krforest-api | placeholder | (후속 PR) | — | 산악기상 (Sprint 2) + trails (Sprint 3) 양쪽 사용 |
| python-opinet-api | placeholder | (후속 PR) | — | Sprint 2 §2.3 PriceValue |
| python-krex-api | placeholder | (후속 PR) | — | Sprint 2 §2.4 multi-kind |
| python-visitkorea-api | placeholder | (후속 PR — enrichment) | — | ADR-042: 축제는 enrichment 2차 |
| python-knps-api | `@06da125f` (PR#25 시점) | (Sprint 3 PR) | PR#25 | keyless file-only, ADR-028 amendment 2026-05-25 |
| python-krheritage-api | placeholder | (Sprint 3 PR) | — | media → RustFS |
| python-krairport-api | placeholder | (Sprint 3 PR) | — | 공항 운항·날씨 |
| python-mois-api | placeholder | (Sprint 4 PR) | — | ADR-024 canonical name 정정. 4단계 lifecycle |
| python-kasi-api | placeholder | (Sprint 4 PR) | — | KASI 영업주기 |
| python-mcst-api | placeholder | (Sprint 5 PR) | — | 독립서점/북카페 — MOIS enrichment |

**최신 sha 갱신 절차**:
1. provider 저장소에서 안정 commit sha 확인 (사용자 모니터링).
2. `pyproject.toml` `[providers]` extra의 해당 라인 주석에 sha 박음.
3. 변환 함수 Protocol shape이 그 sha와 정합하는지 본 lib 측에서 검증.
4. `docs/journal.md`에 sha 갱신 entry.
5. 큰 schema breaking이면 ADR 작성.

운영 환경은 `pip install -e ".[providers]"`로 git URL을 fetch — `[providers]`
extra는 optional이므로 본 라이브러리 자체 install (`pip install -e .`)에는
영향 없음.
