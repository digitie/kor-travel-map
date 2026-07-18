# ADR-062 — 공개 Weather API와 3년 이력 보존

- 상태: accepted
- 날짜: 2026-07-09
- 결정자: user + codex
- 관련: ADR-072 — bitemporal 시간 의미·무결성·batch/current projection

## 컨텍스트

외부 시스템은 kor-travel-map REST API를 통해 현재 날씨뿐 아니라 단기/중기 예보,
과거 발표 예보, 기상특보 이력을 조회해야 한다. 같은 `valid_at`에 대해 현재 발표와
3시간 전/1일 전 발표를 비교하려면 `issued_at`별 예보 snapshot이 삭제되지 않아야 한다.

기존 문서에는 `weather_values` 30일 보존이 남아 있었고, `/features/{feature_id}/weather`
카드 API는 최신값 요약이라 외부 시스템의 timeline 비교에 충분하지 않았다.

## 결정

1. `feature.feature_weather_values`는 기본 3년 보존으로 운영한다.
2. 예보/관측값은 `issued_at`, `valid_at`, `observed_at`을 보존한 timeline row로 공개한다.
3. 외부 시스템용 공개 API는 별도 `/v1/weather/*`가 아니라 feature API 하위에 둔다.
   - 좌표 기준 forecast: `GET /v1/features/weather/forecast`
   - feature 기준 forecast: `GET /v1/features/{feature_id}/weather/forecast`
   - KMA 기상특보 이력: `GET /v1/features/weather/alerts`
4. KMA 중기예보(`forecast_style=mid`)는 weather forecast timeline의 1차 공개 대상에 포함한다.
5. KMA 기상특보 이력은 별도 alert table을 만들지 않고 `provider_sync.source_records`
   이력을 공개 projection으로 조회한다.
6. 지도 weather marker는 zoom 14 이상 개별 feature marker에서 예보 보유 weather feature도
   라벨을 표시한다.

## 근거

- 기존 `WeatherValue` identity가 `issued_at + valid_at + metric_key`를 포함하므로,
  발표 시점이 다른 예보 snapshot을 새 테이블 없이 보존할 수 있다.
- 외부 시스템은 feature_id를 모를 수 있으므로 좌표 기반 nearest weather anchor 조회가 필요하다.
- source_record는 payload hash 기반 이력 구조라 기상특보 재발표/등급 변경 이력에 적합하다.

## 결과

- `weather_values` 30일 purge 문서 정책은 폐기한다.
- 3년 범위 조회를 위한 보조 인덱스를 추가한다.
- 기존 `/v1/features/{feature_id}/weather` 카드 API는 호환성을 위해 유지한다.
- weather는 독립 리소스가 아니라 feature의 공용 속성/시계열로 다루므로, 공개 REST 표면도
  `/v1/features` 아래에서 관리한다.
- 3년을 넘는 장기 기후 분석은 본 API의 1차 범위가 아니다.

## 개정 (2026-07-18, ADR-072)

3년 보존과 feature 하위 공개 weather 표면은 유지한다. `issued_at`/`valid_at`/`observed_at`
나열만으로 시간 의미를 정의하던 부분은 ADR-072의 `target_at`/`known_at` bitemporal 계약으로
확장하며, 공개 원문 payload 대신 typed projection을 사용한다.
