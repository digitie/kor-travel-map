# Feature DB 초기화

TripMate는 별도 feature DB를 만들지 않고 `python-krtour-map`의 DB schema와 초기화 함수를 사용한다.

## 설정 주입

`krtour_map.db.initialize_feature_db(...)`는 아래 입력을 받을 수 있다.

- `FeatureDbSettings`
- DB URL 문자열
- `{"database_url": "..."}` mapping
- `database_url` 속성이 있는 settings 객체

TripMate의 `Settings` 객체도 이 방식으로 바로 전달한다.

```python
from krtour_map.db import initialize_feature_db

context = initialize_feature_db(tripmate_settings)
try:
    with context.session_factory() as session:
        ...
finally:
    context.dispose()
```

`create_schema=True`가 기본값이며 `metadata.create_all()`을 실행한다. Alembic이나 별도 migration 단계에서 schema를 이미 관리하는 실행 경로는 `create_schema=False`로 engine/session factory만 초기화할 수 있다.

## 책임 경계

- `python-krtour-map`: `FeatureDbSettings`, `FeatureDbContext`, engine/session factory 생성, feature schema 초기화
- TripMate: settings 생성, 운영 DB URL 관리, 실행 시점 결정, 사용자/여행계획/POI 제품 테이블 관리

TripMate 쪽 wrapper/adapter를 만들지 않는다. TripMate는 `database_url` 설정을 이 라이브러리에 넘기고, 이후 feature/source/weather 저장은 `krtour_map.db` table과 row helper를 사용한다.

## ETL 적재

ETL 정규화 결과를 저장할 때는 TripMate가 만든 feature DB session을 이 라이브러리의 적재 helper에
넘긴다.

```python
from krtour_map.events import VisitKoreaFestivalLoadResources, load_visitkorea_festival_events

with context.session_factory() as session:
    resources = VisitKoreaFestivalLoadResources(
        client=visitkorea_client,
        session=session,
        rustfs_store=rustfs_store,
    )
    result = load_visitkorea_festival_events(resources, run)
    session.commit()
```

TripMate는 transaction boundary와 운영 로그를 담당하고, `python-krtour-map`은 어떤 table에 어떤
순서로 staged write할지 담당한다.

## DB 적재 geocoding

provider normalize 단계에서 좌표나 법정동코드를 채우지 못한 feature는 DB 적재 직전에 보강할 수
있다. `load_feature_rows()`는 아래 optional 인자를 받는다.

- `address_geocoder`: `Address -> Coordinate` callable
- `reverse_geocoder`: `Coordinate -> Address` callable
- `geocoder_resource`: `reverse_geocoder`, `address_geocoder`, `kraddr_geo_store`,
  `kraddr_geo_database_path`, `kraddr_geo_store_kwargs` 등을 담은 resource

`geocoder_resource`에 `kraddr_geo_store` 또는 `kraddr_geo_database_path`가 있으면
`python-kraddr-geo` 기반 geocoder를 만든다. 이때 VWorld fallback이 필요하면
`python-kraddr-geo` store 설정에 둔다. `python-krtour-map`은 `python-vworld-api`를 직접
import하지 않는다.

```python
from krtour_map.db import load_feature_rows

load_feature_rows(
    session,
    feature_items=features,
    source_record_items=source_records,
    geocoder_resource={
        "kraddr_geo_database_path": "data/juso/kraddr_geo.sqlite",
        "kraddr_geo_store_kwargs": {"vworld_api_key": "..."},
    },
)
```

보강 결과는 `features.address`, `features.latitude`, `features.longitude`,
`features.legal_dong_code` 등에 반영되고, match report는 `features.detail.address_enrichment`
아래에 남긴다. 이 단계는 `feature_id`를 다시 계산하지 않는다. ID 안정성은 provider normalize
단계에서 정한 source natural key와 기존 feature id를 따른다.

## DB 적재 place 전화번호 보강

`load_feature_rows()`는 `place_phone_searchers` 또는 `place_enrichment_resource`가 있을 때
`Feature(kind="place")`에 대해 전화번호 보강을 수행할 수 있다.

- `place_phone_searchers`: `Feature -> PlaceSearchCandidate iterable` callable 목록
- `place_enrichment_resource`: `place_phone_searchers`, `place_searchers`,
  `place_enrichment_env`, `kakao_rest_api_key`, `naver_client_id`,
  `naver_client_secret`, `google_places_api_key` 등을 담은 resource

전화번호는 `feature_place_details.phones`에 최대 3개까지 추가하고, 사용한 검색 결과는
`source_records(dataset_key="place_phone_enrichment")`와
`source_links(source_role="enrichment")`에 남긴다. provider 검색 결과가 불확실하거나 전화번호가
없으면 기존 detail을 그대로 둔다. 세부 기준은 [장소 전화번호 보강](place-phone-enrichment.md)을
따른다.

이미지/파일이 있는 ETL은 RustFS resource를 함께 주입한다. 파일 바이너리는 RustFS에 저장하고,
DB에는 `feature_files` metadata만 저장한다.
