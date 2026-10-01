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

(구현 머지 시점에 채운다 — migration revision, DROP 목록과 각각이 날씨 전용인 근거, 지운 경로·응답 필드,
C7 spec 목록 변경. 상세는 `docs/journal.md` 2026-10-01 항목.)
