# TripMate 통합 가이드

## 새 경계

TripMate의 feature 관련 Pydantic 계약, deterministic ID, provider 명칭 정책, source trace, fixture replay 기준은 `python-krtour-map`으로 이동합니다.

TripMate에 남는 책임:

- FastAPI endpoint
- SQLAlchemy/PostGIS 모델과 Alembic migration
- Dagster job/schedule
- Admin UI와 운영 workflow
- 사용자/여행/POI 권한 규칙

`python-krtour-map`으로 옮기는 책임:

- `Feature`, `SourceRecord`, `SourceLink`, `WeatherValue`, `PricePoint`, `ProviderSyncState` DTO
- provider canonical name과 alias 정규화
- feature/source ID 생성
- provider 결과를 feature 저장 계약으로 바꾸는 순수 함수
- debug fixture 저장과 pytest replay helper

## TripMate 문서 수정 기준

TripMate 문서에서 아래 내용은 `python-krtour-map` 문서를 canonical 기준으로 링크합니다.

- feature 공통 DTO
- provider canonical name
- source role
- weather domain/style
- fixture replay workflow

TripMate 문서에 계속 남길 내용:

- 실제 DB migration 파일명
- API endpoint
- Admin 화면
- Dagster schedule과 운영 runbook
- PostGIS 인덱스, retention, RBAC 같은 앱 운영 결정

## 구현 순서

1. TripMate ETL loader에서 provider public client를 직접 호출합니다.
2. provider typed model 또는 raw row를 `SourceRecord`로 만듭니다.
3. feature/price/weather 정규화 함수가 `Feature`, `PriceValue`, `WeatherValue`를 만듭니다.
4. TripMate repository가 SQLAlchemy model로 저장합니다.
5. 의미 있는 provider 응답은 `save_fixture`로 저장하고 pytest replay에 추가합니다.

## Weather 예시

```python
from krtour_map.models import WeatherValue

value = WeatherValue(
    feature_id=feature_id,
    provider="python-kma-api",
    weather_domain="kma_short_forecast",
    forecast_style="short",
    metric_key="temp_c",
    valid_at=valid_at,
    value_number=temperature,
    unit="deg_c",
    payload=raw_item,
)
```

다른 provider의 날씨성 데이터도 `weather_domain`만 다르게 두고 같은 `WeatherValue`로 저장합니다.

## 삭제 또는 축소할 TripMate 문서 내용

- provider별 adapter/wrapper 생성 지침은 삭제합니다.
- `py*` alias를 DB/provider 응답 표기명으로 쓰는 예시는 canonical provider name으로 바꿉니다.
- fixture testcase를 개별 pytest 코드 생성 방식으로 설명한 내용은 공통 runner 방식으로 바꿉니다.
- feature DTO를 TripMate 문서와 라이브러리 문서에 중복 상세 정의하지 않습니다. TripMate 문서는 앱 DB와 API 차이만 설명합니다.
