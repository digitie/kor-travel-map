# TripMate 통합 가이드

## 경계

TripMate는 feature DB를 별도로 만들지 않는다. 지도 feature, source trace, weather/price 값, provider sync state는 `python-krtour-map`의 DTO, DB schema, helper 함수를 기준으로 저장하고 조회한다.

TripMate가 맡는 책임:

- FastAPI endpoint와 앱 응답 조립
- 사용자, 여행계획, POI, 권한, 알림 같은 TripMate 제품 DB
- Dagster job/schedule과 운영 runbook
- Admin UI와 검수 workflow

`python-krtour-map`이 맡는 책임:

- `Feature`, `SourceRecord`, `SourceLink`, `WeatherValue`, `PricePoint`, `ProviderSyncState` DTO
- `krtour_map.db`의 feature/source/weather/price DB schema
- provider canonical name과 alias 정규화
- feature/source ID 생성
- provider typed model을 feature 계약으로 바꾸는 순수 함수
- debug fixture 저장과 pytest replay helper

TripMate 문서에는 TripMate 제품 DB, API, Admin, 운영 결정을 남기고, feature DB column/table 세부 정의는 이 라이브러리 문서를 canonical로 링크한다.

TripMate의 feature 중심 문서는 [Feature model](feature-model.md)과 [TripMate feature docs migration](tripmate-feature-docs-migration.md)으로 이관한다. TripMate 쪽에는 사용자, 여행계획, POI 제품 문서와 이 라이브러리로 향하는 링크만 남긴다.

## 구현 순서

1. TripMate ETL loader에서 provider public client를 직접 호출한다.
2. provider typed model 또는 raw row를 `python-krtour-map` DTO로 정규화한다.
3. feature/source/weather/price 저장은 `krtour_map.db` schema와 row 변환 함수를 사용한다.
4. TripMate API는 feature DB에서 필요한 값을 읽어 사용자/여행계획/POI 응답에 조립한다.
5. 의미 있는 provider 응답은 `save_fixture`로 저장하고 pytest replay를 추가한다.

## Event ETL 예시

VisitKorea 축제 ETL은 TripMate가 provider client와 Dagster 실행 자원을 주입하고,
`python-krtour-map`의 loader/job spec을 호출하는 방식으로 연결한다.

```python
from krtour_map.events import visitkorea_festival_full_scan_job_spec

result = visitkorea_festival_full_scan_job_spec.loader(visitkorea_client, run)
```

loader 내부에서는 `iter_pages(client.search_festival, ...)`를 사용해 모든 페이지를 순회한다.
TripMate schedule은 이 job spec을 기준으로 1일 1회 실행한다.

## Weather 예시

## Dagster boundary

API 수집 후 feature/source/weather/price로 가공하는 run context, job spec, logical time/config helper는 `krtour_map.dagster`를 사용한다. TripMate는 실제 Dagster process, `Definitions`, schedule 실행, DB session 주입, 실행 로그와 알림만 담당한다.

```python
from krtour_map.db import feature_weather_values, weather_value_to_row
from krtour_map.models import WeatherValue

value = WeatherValue(
    feature_id=feature_id,
    provider="python-kma-api",
    weather_domain="kma_short_forecast",
    forecast_style="short",
    timeline_bucket="short",
    metric_key="TMP",
    source_metric_key="TMP",
    valid_at=valid_at,
    value_number=temperature,
    unit="deg_c",
    payload=raw_item,
)

session.execute(feature_weather_values.insert().values(weather_value_to_row(value)))
```

다른 provider의 날씨성 데이터도 같은 `WeatherValue`로 저장한다. 관측값은 `forecast_style="observed"`를 유지하고, KMA식 조회 카테고리는 `timeline_bucket="ultra_short"`처럼 별도로 채운다.

## TripMate 문서에서 제거할 내용

- TripMate 전용 provider adapter/wrapper 생성 지침
- `py*` alias를 DB/provider 표기명으로 쓰는 예시
- feature DB table/column을 TripMate 문서에 중복 정의하는 내용
- TripMate ORM row를 feature DTO로 다시 내보내는 것을 전제로 한 설명
