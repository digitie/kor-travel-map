# ADR-105: Map에서 날씨 feature와 날씨 notice 기능을 지운다 — 정의는 남긴다

- 상태: accepted (2026-10-01, 소유자 결정) · 확장 대상: ADR-104(Map은 KMA를 적재하지 않는다)
- 관련: ADR-010(weather 두 축, 이관 문서), ADR-068(날씨는 kor-travel-weather가 소유), ADR-088(operation 카탈로그
  정본), ADR-089(weather fact·summary receipt), ADR-102(migration 전진 배포)

### 소유자 결정(원문 요지)

- "map에서 kma를 포함한 weather feature, 날씨 notice feature 기능 삭제. ui에서도 삭제. 단, feature 정의는 남겨둘 것."
- "기존 db 데이터와 관련 스키마도 삭제."
- "notice 중 weather 관련만 삭제해." — `notice` kind 자체와 비-날씨 notice는 남는다.
- "백업도 하지마." — 이 삭제 migration에는 배포 전 백업 단계가 없다. **삭제는 되돌릴 수 없다.** 정기 백업은
  이 결정과 무관하며 바꾸지 않았다.

### 결정

1. **기능을 지운다.** `weather` kind feature의 모든 출처(KMA·AirKorea·KREX 휴게소 기상·산림청 산악기상·
   산림청 산불위험예보)와 **날씨 출처 notice**(KMA 기상특보, provider `python-kma-api`)의 적재 경로·Dagster
   asset/job/schedule/sensor·provider 변환·REST 경로와 응답 필드·operation key·큐 경로·UI를 지운다.
   weather current summary를 매분 재평가하던 `current_weather_summary_refresh_minutely_schedule`도 날씨 전용이라
   지운다.
2. **남기는 notice.** KREX 교통공지, 산림청 산사태 예보(산림청 재해 notice — 날씨 출처가 아니다)와 그 밖의
   비-날씨 notice는 적재·API·UI·데이터가 그대로다. notice 공용 스키마(`feature.feature_notices`,
   `provider_sync.notice_*`)도 남는다.
3. **정의는 남긴다.** kind/category enum(`weather` 포함), DTO·타입(`WeatherValue`, `WeatherDomain`,
   `ForecastStyle`, `TimelineBucket` 등), category 정의, `make_feature_id`, marker icon 카탈로그, DB의 kind 허용값
   (`kind IN (..., 'weather', ...)` CHECK). enum 값을 지우는 것 자체가 스키마 변경이므로 정의로 취급한다.
4. **데이터와 날씨 전용 스키마를 지운다** — migration `402`(아래 "이 저장소에서 바뀐 것"). 날씨 feature와 KMA
   특보 notice 행과 그 의존 행을 지우고, 날씨 전용 표·함수·인덱스를 DROP하며, 날씨·KMA 특보 dataset의 모든
   operation을 끄고 dataset을 비활성화한다. 카탈로그 행은 이력 FK 때문에 남긴다.
5. **재도입 방지 검사**는 이름이 아니라 kind(카탈로그 `capabilities.produces`)·provider 정체성과 효과(client
   import, weather 적재 함수 호출)에 결박한다.

### 결과

- Map은 날씨를 읽지도 쓰지도 않는다. 날씨 소비자는 kor-travel-weather를 쓴다(PinVi는 T-365에서 이미 옮겼다).
- 2026-10-01 prod(읽기 전용 실측)에는 지울 feature 행이 없다 — `feature.features` 0, weather fact·summary 0,
  notice 0. 실제로 지워지는 것은 `ops.current_summary_runs`의 weather 행 2,875건(매분 schedule의 receipt)과
  카탈로그 상태 변경뿐이다.
- 공유 plane에서 Map location의 RUNNING schedule이었던 `current_weather_summary_refresh_minutely_schedule`이
  다음 pinned pair 배포 뒤 사라진다. Map의 나머지 instigator(sensor 10)는 그대로다.

### 이 저장소에서 바뀐 것

- **Dagster**: weather asset 넷(AirKorea 대기질·KREX 휴게소 기상·산림청 산악기상·산불위험예보)과 job·schedule·
  resource·fetcher·큐 runner spec·handler binding(33 → 29), `current_weather_summary_refresh` job/op/schedule을 지웠다.
  run-completion gate의 기본 probe job은 DB 전용 `cache_target_snapshot_gc`로 바꿨다.
- **라이브러리**: `infra/weather_repo.py`·`core/weather.py`·`providers/kma.py`·`providers/airkorea.py` 삭제, `providers/krex.py`
  휴게소 기상·`providers/krforest_safety.py` 산악기상/산불위험 변환 삭제, client의 `load_weather_values`·
  `materialize_current_weather_summary`·`load_air_quality`·`build_weather_card` 삭제. 정의(`dto/weather.py`,
  `dto/_enums.py`, `core/ids.make_weather_value_key`, `NOTICE_TYPE_WEATHER_ALERT`)는 남겼다.
- **API**: weather 경로 8개와 `weather_summary`(FeatureSummary·AdminFeatureMapItem)·`latest_weather`(BeachPublicView) 필드,
  weather·KMA 특보 preview fixture를 지웠다. 세 OpenAPI를 다시 뽑았다. PinVi는 T-365부터 이 경로를 부르지 않지만 계약
  스냅샷의 선택 필드 `latest_weather`가 사라지므로 PinVi vendor 스냅샷을 다음 짝에서 다시 떠야 한다(rollout receipt는
  pending으로 재핀했다).
- **DB**: `402_remove_map_weather_data` — 대상은 이름이 아니라 정체성(`capabilities.produces ∋ "weather"`, 또는 notice이면서
  provider `python-kma-api`)으로 고른다. preflight(남는 데이터의 lineage를 끊거나 불변 증거를 지우게 되면 중단) → 대상
  operation 전부 off → `feature_weather_values`·`current_weather_summary`·`reject_weather_value_mutation()`·
  `idx_features_public_weather_coord_5179_gist` DROP(각각 head-schema 전수 검색으로 weather 전용임을 확인) → 대상
  feature 삭제(선언된 FK 동작이 의존 행 처리) → identity claim·source lineage·KMA notice lifecycle 삭제 →
  `ops.current_summary_runs` weather 행 삭제(불변 트리거는 0236 선례대로 트랜잭션 안에서만 끄고 되켠다)와
  `projection_kind` CHECK를 `price`로 좁힘 → dataset 비활성. 카탈로그 행·append-only 이력은 남긴다. KMA 분기를 가진
  공용 함수 `provider_sync.notice_lineage_key`는 남겼다(입력이 다시 생길 수 없다). 백업 단계 없음.
- **UI**: weather 패널·kind 토글·marker 분기·fetcher 삭제, 지도 기본 kind `["notice"]`, 타입 재생성.
- **C7/D2**: C7 러너에서 KMA spec 넷과 KMA 상태 저널·Dagster 직접 호출을 걷어내고, read-auth·schedule-write
  (`feature_place_krairport_airports_monthly_schedule` — 번들 정적 데이터라 upstream 호출 0)·POI `@c7-causal`로
  돌린다. D2 fixture는 price feature 하나만 심는다.
- **재도입 방지**: `packages/kor-travel-map-dagster/tests/test_map_dagster_has_no_weather.py`,
  `packages/kor-travel-map-api/tests/test_api_serves_no_weather.py`,
  `packages/kor-travel-map-admin/frontend/src/app/map-ui-has-no-weather.test.ts`,
  `tests/integration/test_weather_removal_migration.py`, `tests/integration/test_provider_catalog.py::test_head_serves_no_weather_dataset`.

### 후속

- `pyproject.toml`의 `python-kma-api`·`python-airkorea-api` 의존 핀과 `_provider_surface.json` 항목 제거.
- `.env.example`의 `KMA_API_KEY`·`AIRKOREA_API_KEY`, Manager compose의 `KOR_TRAVEL_MAP_KMA_WEATHER_*` env 제거.
- `feature_repo`의 KMA notice 분기와 `provider_sync.notice_lineage_key`의 KMA 분기를 다음 migration에서 함께 제거.
- n150 `/root/.d2-live.env`의 `E2E_C7_SCHEDULE`을 새 allowlist로 바꾼다(운영자).
