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
