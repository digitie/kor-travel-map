# python-krtour-map

`python-krtour-map`은 TripMate의 하부 라이브러리로, 여러 공공 API 라이브러리에서 올라오는 여행 지도 데이터를 하나의 feature 계약으로 모으고 저장/조회/수정/삭제할 수 있게 하는 코어 패키지입니다.

예를 들어 weather feature는 `python-kma-api`, `python-airkorea-api`, `python-krex-api`, `python-krairport-api`, `python-khoa-api`에서 얻은 값을 provider별 wrapper 없이 공통 `WeatherValue`와 `Feature`에 연결합니다. 앱은 provider 원문 대신 정규화된 feature와 source trace를 사용합니다.

## 책임

- 공통 feature DTO: `place`, `event`, `notice`, `price`, `weather`, `route`, `area`
- deterministic ID: provider, source type, source natural key, kind, category, bjd code, payload hash 기반
- provider 명칭 표준화: `pykma`, `kma`, `opinet` 같은 짧은 alias를 canonical provider name으로 정규화
- source trace: `SourceRecord`, `SourceLink`, `SourceRole`로 원천 row와 feature 연결
- feature CRUD: 테스트/디버그용 `InMemoryFeatureStore`
- weather 병합: KMA timeline을 기준으로 provider별 weather context를 latest view로 합침
- fixture replay: 첨부 문서 기준의 JSON fixture 저장, 민감정보 마스킹, pytest replay runner 지원

## 하지 않는 일

- provider별 TripMate 전용 adapter/wrapper를 만들지 않습니다.
- Streamlit에 의존하지 않습니다. 디버그 Web UI는 별도 프로젝트에서 이 라이브러리를 import합니다.
- TripMate의 FastAPI 라우터, Admin UI, Alembic migration을 직접 소유하지 않습니다. 이 라이브러리는 그 구현들이 공유할 계약과 순수 함수를 제공합니다.
- 외부 API를 테스트 기본 경로에서 직접 호출하지 않습니다. fixture replay와 integration test를 분리합니다.

## 기본 구조

```text
src/krtour_map/
  enums.py       # feature kind, source role, weather domain/style
  models.py      # Pydantic v2 DTO
  ids.py         # deterministic feature/source ID
  providers.py   # canonical provider name policy
  store.py       # in-memory CRUD repository
  weather.py     # weather latest merge helper
  parser.py      # fixture replay parser boundary
  processor.py   # fixture replay processor boundary
  debug.py       # DebugRun
  fixtures.py    # fixture save/replay/assertion helpers
tests/
  fixtures/      # replay 기반 회귀 fixture
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
    bjd_code="1111010100",
    content_hash="payload-hash",
)

store = InMemoryFeatureStore()
store.upsert_feature(
    Feature(
        feature_id=feature_id,
        kind=FeatureKind.PRICE,
        name="Sample Fuel Station",
        coord=Coordinate(longitude=127.0001, latitude=37.5001),
        address=Address(bjd_code="1111010100"),
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

## 문서

- [아키텍처](docs/architecture.md)
- [Provider 계약](docs/provider-contract.md)
- [Postgres 스키마 기준](docs/postgres-schema.md)
- [Debug fixture workflow](docs/debug-fixture-workflow.md)
- [TripMate 통합 가이드](docs/tripmate-integration.md)
