# python-krtour-map

`python-krtour-map`은 TripMate의 하부 라이브러리로, 여러 공공 API 라이브러리에서 올라오는 여행 지도 데이터를 하나의 feature 계약으로 모으고 저장/조회/수정/삭제할 수 있게 하는 핵심 패키지입니다.

예를 들어 weather feature는 `python-kma-api`, `python-airkorea-api`, `python-krex-api`, `python-krairport-api`, `python-khoa-api`의 안정된 public API에서 얻은 값을 provider별 wrapper/adapter 없이 공통 `WeatherValue`와 `Feature`에 연결합니다. 앱은 provider 원문 대신 정규화된 feature와 source trace를 사용합니다.

## 책임

- 공통 feature DTO: `place`, `event`, `notice`, `price`, `weather`, `route`, `area`
- 결정적 ID: provider, source type, source natural key, kind, category, legal dong code, payload hash 기반
- provider 명칭 표준화: `pykma`, `kma`, `opinet` 같은 짧은 alias를 표준 provider name으로 정규화
- source trace: `SourceRecord`, `SourceLink`, `SourceRole`로 원천 row와 feature 연결
- KRMOIS 인허가 feature: raw/localdata는 `python-krmois-api` source DB에 두고, 이 라이브러리는 영업중 여행 row만 feature로 승격
- 국가유산 feature: `python-krheritage-api` public model을 provider wrapper 없이 직접 읽어 `place`, `area`, `event` feature로 정리
- 공공데이터포털 표준데이터 5종: 별도 provider 라이브러리로 분리하지 않고
  `krtour_map.standard_data`의 제한된 asyncio client와 ETL로 `route`, `place`, `event` feature 생성
- 산림/고속도로 feature: `python-krforest-api`, `python-krex-api` async public client 결과를
  provider wrapper 없이 feature/source/weather/price 계약으로 정규화
- kind별 detail: `PlaceDetail`, `EventDetail`, `RouteDetail`, `NoticeDetail`로 장소/행사/경로/공지 공통 필드 구조화
- place 전화번호 보강: Kakao Local, Naver Search Local, Google Places Text Search(New)
  검색 결과를 source trace와 함께 `PlaceDetail.phones` 보강에만 제한적으로 사용
- 공통 주소/좌표/category: `python-kraddr-base`의 `Address`, `AddressRegion`, `PlaceCoordinate`, `PlaceCategoryCode`를 직접 사용
- 주소 보강: `python-kraddr-geo` 기반 reverse geocoder callable 결과를
  `kraddr.base.Address`로 병합하고 `AddressMatchReport`로 매칭 수준을 검토
- feature DB: `krtour_map.db`의 SQLAlchemy Core schema, row 변환 함수, staged load helper가 표준 저장소 계약
- feature 파일: 이미지/파일 바이너리는 RustFS에 저장하고 `FeatureFile`/`feature_files`에 1:N 메타데이터 저장
- feature CRUD: 테스트/디버그용 `InMemoryFeatureStore`
- weather 병합: KMA timeline을 기준으로 provider별 weather context를 최신 view로 합침
- weather 분류: `forecast_style`은 관측/예보/지수 성격을 보존하고 `timeline_bucket`은 KMA식 `ultra_short`, `short`, `mid` 조회 축을 담당
- fixture replay: 첨부 문서 기준의 JSON fixture 저장, 민감정보 마스킹, pytest replay 실행기 지원

## 하지 않는 일

- provider별 TripMate 전용 adapter/wrapper/gateway를 만들지 않습니다.
- provider 호출을 감추는 새 facade를 만들지 않습니다. 부족한 endpoint, typed model, pagination, cursor, exception, raw payload 계약은 해당 `python-*-api` 라이브러리에서 먼저 안정화합니다.
- 외부 API 관련 작업은 이 원칙을 먼저 반영한 뒤 feature 계약, 저장, 문서화를 진행합니다.
- Streamlit에 의존하지 않습니다. 디버그 UI는 별도 `python-krtour-map-debug-ui` 패키지의
  stdlib HTTP server 기반 로컬 개발 도구이며, 운영 Admin UI는 TripMate가 소유합니다.
- TripMate의 FastAPI 라우터, Admin UI, Alembic migration을 직접 소유하지 않습니다. 이 라이브러리는 그 구현들이 공유할 계약과 순수 함수를 제공합니다.
- 사용자, 여행계획, POI를 관리하지 않습니다. 이들은 TripMate 제품 도메인이고, 필요한 경우 `feature_id`로 이 라이브러리의 feature를 참조합니다.
- TripMate가 별도 feature DB를 복제하지 않습니다. TripMate는 `python-krtour-map`의 DB schema와 함수를 import해 feature/weather/source 저장소를 사용합니다.
- 외부 API를 테스트 기본 경로에서 직접 호출하지 않습니다. fixture replay와 통합 테스트를 분리합니다.

## 기본 구조

```text
src/krtour_map/
  enums.py       # feature kind, source role, weather domain/style enum
  models.py      # Pydantic v2 DTO
  ids.py         # 결정적 feature/source ID 생성
  providers.py   # 표준 provider name 정책
  store.py       # 메모리 기반 CRUD repository
  files.py       # RustFS feature file 메타데이터/업로드 헬퍼
  rustfs.py      # TripMate와 공유 가능한 RustFS 설정/presign/list 헬퍼
  addressing.py  # kraddr-base 주소 코드 정규화와 geocoding match report
  weather.py     # weather 최신값 병합 헬퍼
  standard_data/ # data.go.kr 표준데이터 5건 제한 asyncio client + ETL
  forest.py      # krforest 휴양림/수목원/숲길/산악기상 정규화
  highways.py    # krex 휴게소/휴게소 유가/휴게소 날씨 정규화
  krmois.py      # KRMOIS 인허가 source DB 기반 place feature 승격과 주간 전체 갱신 계약
  events.py      # VisitKorea festival/event ETL 정규화와 DB 적재 헬퍼
  heritage.py    # 국가유산 place/area/event ETL 정규화와 DB 적재 헬퍼
  opinet.py      # OpiNet station place/price 정규화와 DB 적재 헬퍼
  notices.py     # traffic/weather/safety/coastal notice 정규화
  places.py      # Kakao/Naver/Google place search 전화번호 보강
  parser.py      # fixture replay parser 경계
  processor.py   # fixture replay processor 경계
  debug.py       # DebugRun
  fixtures.py    # fixture 저장/replay/assertion 헬퍼
tests/
  fixtures/      # replay 기반 회귀 fixture
packages/
  krtour-map-debug-ui/
    pyproject.toml
    src/krtour_map_debug_ui/  # stdlib 로컬 디버그 UI/API 패키지
```

## 빠른 사용 예

```python
from krtour_map import (
    Address,
    Coordinate,
    Feature,
    FeatureKind,
    InMemoryFeatureStore,
    make_feature_id,
)

feature_id = make_feature_id(
    provider="opinet",
    source_type="fuel_station",
    source_natural_key="A0010207",
    kind=FeatureKind.PRICE,
    category="fuel",
    legal_dong_code="1111010100",
    content_hash="payload-hash",
)

store = InMemoryFeatureStore()
store.upsert_feature(
    Feature(
        feature_id=feature_id,
        kind=FeatureKind.PRICE,
        name="Sample Fuel Station",
        coord=Coordinate(lat=37.5001, lon=127.0001),
        address=Address.from_mapping({"legal_dong_code": "1111010100"}) or Address(),
        category="fuel",
        marker_icon="fuel",
        marker_color="P-04",
    )
)
```

## 검증

```bash
python -m pytest
```

현재 기본 테스트는 외부 API를 호출하지 않고 fixture replay와 순수 모델/저장소 계약만 검증합니다.

## 로컬 디버그 UI

표준데이터 raw item 미리보기/적재, feature table 브라우저, 스키마 요약은 별도 디버그 UI 패키지로 확인할 수 있습니다.

```bash
python -m krtour_map_debug_ui.server
```

기본 URL은 `http://localhost:8600`입니다. 프론트엔드는 `8600`, 로컬 API는 `8601`을
사용하며 Kakao map, Dagster ETL 실행, RustFS 설정/파일 목록 확인을 제공합니다. 라이브 API
호출은 `DATAGOKR_API_KEY`, `DATA_GO_KR_SERVICE_KEY`, `PUBLIC_DATA_SERVICE_KEY`, `SERVICE_KEY`
또는 debug API payload의 `api_key`가 필요하며, 테스트 경로에서는 외부 API를 호출하지 않습니다.

## 문서

이 저장소의 문서는 한국어를 기본 언어로 작성합니다. 코드 식별자, DB 컬럼, enum, provider 공식명,
API endpoint, 환경변수는 원문을 유지하며, 세부 기준은 [Feature 문서 작성 가이드](docs/feature-docs-guide.md)를
따릅니다.

- [아키텍처](docs/architecture.md)
- [Provider 계약](docs/provider-contract.md)
- [python-kraddr-base 자료형 사용 기준](docs/kraddr-base-types.md)
- [주소 geocoding과 매칭 리포트](docs/address-geocoding.md)
- [Feature 모델 기준](docs/feature-model.md)
- [Feature 파일과 RustFS](docs/feature-files-rustfs.md)
- [Feature 운영시간](docs/feature-opening-hours.md)
- [장소 전화번호 보강](docs/place-phone-enrichment.md)
- [Feature 문서 작성 가이드](docs/feature-docs-guide.md)
- [행사 feature ETL](docs/event-feature-etl.md)
- [KRMOIS 인허가 feature ETL](docs/krmois-license-feature-etl.md)
- [표준데이터 feature ETL](docs/standard-data-feature-etl.md)
- [KHOA 해수욕장정보 장소 ETL](docs/khoa-beach-info-etl.md)
- [국가유산 feature ETL](docs/krheritage-feature-etl.md)
- [산림·등산 feature ETL](docs/outdoor-feature-etl.md)
- [OpiNet 장소/가격 ETL](docs/opinet-place-price-etl.md)
- [날씨 feature 정규화](docs/weather-feature-normalization.md)
- [공지 feature ETL](docs/notice-feature-etl.md)
- [Dagster 경계](docs/dagster-boundary.md)
- [Postgres 스키마 기준](docs/postgres-schema.md)
- [디버그 fixture 흐름](docs/debug-fixture-workflow.md)
- [디버그 UI 패키지](docs/debug-ui-package.md)
- [WSL ext4 작업 흐름](docs/wsl-ext4-workflow.md)
- [TripMate 통합 가이드](docs/tripmate-integration.md)
- [TripMate feature 문서 이관](docs/tripmate-feature-docs-migration.md)
