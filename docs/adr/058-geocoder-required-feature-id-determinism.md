# ADR-058: geocoder-의존 provider의 feature_id 결정성은 geocoder 필수화로 보장한다 (F-01)

### 상태

Accepted (2026-06-16) — 2026-06-16 전체 정합성 감사 F-01. ADR-057이 concierge에만 적용한
feature_id 비멱등 문제(geocoded bjd가 식별자에 박혀 geocoder 유무로 갈림)를, 나머지
geocoder-의존 provider에 대해 **re-key 없는 경량 방식(geocoder 필수화)**으로 해소한다
(사용자 결정 B).

### 배경

`make_feature_id`는 `bjd_code`를 식별자에 embed한다. MOIS만 source-native `legal_dong_code`
를 쓰고, ~11 provider(opinet/krex/knps/krheritage/khoa/krairport/airkorea/standard_data/
krforest/mcst/datagokr_file_data)는 bjd를 **reverse_geocoder**(Dagster `reverse_geocoder`
resource)에서 얻는다. 그런데 이 resource는 `kor_travel_geo_base_url` 미설정 시 **조용히
None**을 yield했다. geocoder가 None이면 같은 record가 `f_global_…`↔`f_<bjd>_…`로 갈려
재import 시 중복(비멱등)이 난다 — 정합성 감사 F-01.

두 선택지: **A** ADR-057 일반화 — feature_id에서 geocoded bjd 제거(안정 source key 고정).
robust하나 **전 feature DB re-key**(1M+ feature) + provider별 natural_key 전역유일성 검증
필요. **B** geocoder 필수화 — bjd가 항상 채워지도록 강제해 결정성 보장, re-key 없음. 단
geocoder 출력이 버전/좌표에 따라 바뀌면 여전히 분기(약한 보장).

### 결정

- **B 채택(re-key 없음)**: `reverse_geocoder_resource`가 `kor_travel_geo_base_url` 미설정 시
  조용히 None을 주지 않고 **즉시 실패**(RuntimeError)한다. geocoder를 운영 필수로 강제해,
  좌표 보유 record의 bjd가 항상 resolve되도록 한다 → 같은 run/재import에서 feature_id 결정성.
- bjd/category는 기존대로 식별자에 둔다(re-key 회피). 좌표 없는 record는 bjd None=`global`로
  일관(좌표 유무는 record 고정 속성).
- 직접 `reverse_geocoder=None` override(테스트의 weather/offline 등 bjd-비의존 경로)는 영향
  없다 — 본 결정은 default resource의 silent-None만 제거한다.

### 근거

- re-key 없는 최소 변경으로 운영 결정성을 확보한다(geocoder는 place provider에 어차피 필수).
  silent-None은 "geocoding 미구성" 운영 실수를 비멱등 데이터로 숨겼다 — fail-fast가 옳다.
- 더 강한 A(식별자에서 bjd 제거)는 전 feature_id 재키 + collision 분석이 필요해 실데이터 운영
  중 시점에 보류한다(아래 후속).

### 결과

- `packages/kor-travel-map-dagster/src/kortravelmap/dagster/resources.py`
  `reverse_geocoder_resource`가 base URL 미설정 시 raise. `test_resources.py` 회귀 갱신.
- 잔여(약한 보장): geocoder가 같은 좌표에 다른 bjd를 주면(버전 drift) 여전히 분기 가능 —
  완전 결정성은 A(식별자에서 bjd 제거)가 필요. A는 `T-AUDIT-0616`에 re-key 동반 후속.
- 정본: `docs/reports/full-consistency-audit-2026-06-16.md` F-01.
