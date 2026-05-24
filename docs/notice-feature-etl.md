# 공지 feature ETL

`notice`는 사용자가 지도에서 즉시 회피하거나 확인해야 하는 짧은 수명의 정보다. 날씨 값 자체는
`WeatherValue`로 저장하지만, 호우/대설/폭염 특보, 도로 사고/공사/통제, 지진/산사태, 해양
갈라짐처럼 지도 마커로 노출해야 하는 항목은 `Feature(kind="notice")`와 `NoticeDetail`로 저장한다.

## 문서 정보

| 항목 | 값 |
| --- | --- |
| provider | `python-krex-api`, `python-kma-api`, `python-krforest-api`, `python-khoa-api` |
| `dataset_key` | `krex_traffic_notices`, `kma_weather_alerts`, `forest_safety_notices`, `khoa_coastal_notices` |
| `Feature.kind` | `notice` |
| 상세 테이블 | `feature_notice_details` |
| 코드 entrypoint | `krtour_map.notices` |

## 공지 유형

`NoticeDetail.notice_type`은 다음 표준 값을 우선 사용한다.

| `notice_type` | 예 |
| --- | --- |
| `traffic` | 일반 교통 알림 |
| `traffic_accident` | 도로공사 사고, 추돌, 고장 |
| `road_closure` | 통제, 차단, 우회 |
| `roadwork` | 도로공사, 작업 |
| `weather_alert` | 범용 기상특보 |
| `heavy_rain_warning` | 호우주의보/경보 |
| `heavy_snow_warning` | 대설/폭설주의보/경보 |
| `heat_wave_warning` | 폭염주의보/경보 |
| `safety` | 범용 안전/재난 알림 |
| `earthquake` | 지진 |
| `landslide_warning` | 산사태 위험/경보 |
| `coastal_isolation` | 바다 갈라짐, 해양 고립 위험 |

한국어/영어 alias는 `normalize_notice_type()`에서 표준 값으로 바꾼다. provider 원문 등급과
문구는 `Feature.detail.notice`와 `NoticeDetail.payload`에 보존한다.

## `dataset_key` 갱신 주기

짧은 수명의 공지성 데이터는 provider rate limit을 넘지 않는 선에서 기존 place/area보다 짧게 갱신한다.

| `dataset_key` | provider | 갱신 주기 | 이유 |
| --- | --- | --- | --- |
| `krex_traffic_notices` | `python-krex-api` | 5분 | 사고/공사/통제는 지도 판단에 즉시 영향 |
| `kma_weather_alerts` | `python-kma-api` | 10분 | 특보 발효/해제 변경이 짧은 시간에 발생 |
| `forest_safety_notices` | `python-krforest-api` | 30분 | 산사태/산불/탐방 위험은 지역 단위로 빈번하지 않음 |
| `khoa_coastal_notices` | `python-khoa-api` | 60분 | 바다 갈라짐/해양 위험은 예보성 데이터가 많아 시간 단위 갱신 |

`notice_job_specs()`는 위 주기를 태그로 노출한다. 실제 provider 호출과 rate limit 세부 제어는
TripMate Dagster resource와 각 `python-*-api` public client가 담당한다. 이 라이브러리는 provider
typed model 또는 이미 수집된 item iterable을 받아 feature/source/detail row로 변환한다.

## 디버그 UI

별도 debug UI 패키지의 로컬 UI는 `krex_traffic_notices`, `kma_weather_alerts`, `forest_safety_notices`,
`khoa_coastal_notices` 샘플 item을 preview/load/Dagster run으로 직접 적재할 수 있다. 지도는 현재
보이는 bounds 기준 조회를 지원하며, notice 마커는 `notice_type`, severity, maki icon 이름을 함께
표시한다.
