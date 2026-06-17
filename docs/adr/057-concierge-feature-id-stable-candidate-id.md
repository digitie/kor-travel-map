# ADR-057: kor-travel-concierge feature_id는 bjd/category가 아닌 안정 candidate.id에 고정한다

### 상태

Accepted (2026-06-15) — concierge provider loader 검증(5-에이전트 conformance 감사,
정본 `docs/reports/concierge-loader-verify-2026-06-15.md`)에서 발견된 feature_id
결정성 갭(C-01/C-02) 해소. 로더 자체는 계약 정합(필드명·중첩·스케일·lifecycle 모두 OK)
이나, feature_id가 늦게 바인딩되는 좌표(bjd)·category에 의존해 같은 후보가 재export마다
새 feature로 갈리는 비멱등 문제를 수정한다.

### 배경

`make_feature_id`는 모든 provider 공통으로 `bjd_code`·`category`를 식별자 입력에 넣는다
(ADR-009 결정성). 대부분 provider는 이 둘이 안정적이다 — bjd는 provider가 주는 주소/좌표
에서 한 번 정해지고, category는 데이터 종류로 고정된다.

그러나 kor-travel-concierge export는 다르다 (origin/main `backend/ktc/services/
feature_export_service.py` 실측):

- `place.address.{legal_dong_code,sido_code,sigungu_code}`를 **항상 None**으로 보낸다 —
  bjd는 소비자(kor-travel-map)가 좌표 reverse geocoding으로 채우는 게 계약이다
  (`docs/feature-export-api.md` 기본 원칙). 따라서 bjd는 **선택적 reverse_geocoder
  resource**(Dagster, 기본 None)에만 의존한다.
- `place.category_code_suggestion`은 Gemini enrich 전 **None**이고, 채워지면 payload 변경
  upsert로 **재export**된다("upsert = 검수 통과 후보 또는 payload 변경 후보").

결과: 같은 후보(candidate.id 동일)라도 (a) geocoder 유무/출력이 바뀌면 bjd가
`global`↔`<코드>`, (b) category가 None(→TOURISM fallback)→실제 8자리로 바뀌면 — feature_id
가 달라져 **새 feature로 갈린다**(중복·dedup 단절, 멱등 upsert 깨짐). reject/tombstone→
inactive 라이프사이클 경로는 `source_entity_id`로 매칭해 **면역**이지만 upsert 경로가
비멱등이었다.

### 결정

- kor-travel-concierge feature_id는 **안정 식별자**에만 고정한다:
  `(kind=place, source_type=provider:dataset 상수, source_natural_key=candidate.id)`.
  concierge는 `source_record.source_entity_id = str(candidate.id)`를 모든 operation에 동일
  하게 보내므로 이 키는 후보 수명 동안 불변이다.
- feature_id 파생에서 `bjd_code`와 `category`를 **뺀다**: `bjd_code=None`(prefix
  `f_global_`), category는 고정 `_FEATURE_ID_IDENTITY_CATEGORY`(= provider TOURISM 상수).
  `source_type`도 payload가 아닌 provider/dataset **상수**로 고정한다.
- 실제(가변) bjd·category는 식별자가 아니라 **표시·공간 속성**으로 싣는다 —
  `Address.bjd_code`(reverse geocoder가 채움)·`Feature.category`(실제 8자리 or fallback)는
  그대로 두고, 재import마다 같은 feature_id에 **in-place 갱신**된다.
- 이 정책은 **kor-travel-concierge provider 한정**이다. 다른 provider는 bjd/category가
  안정적이라 기존 `make_feature_id`(bjd/category 포함) 동작을 유지한다.
  - 단, "안정적"이 진짜 보장되는 경우는 **source-native legal_dong_code(MOIS) 또는
    provider가 직접 제공하는 행정코드** 케이스에 한정된다. knps·krheritage·mcst·
    krforest·datagokr_file_data·khoa·airkorea·krairport·opinet·standard_data처럼 bjd를
    **reverse-geocode로 채우는** provider는 feature_id 결정성이 여전히 geocoder
    출력/버전에 조건부다(known gap F-01, `docs/reports/full-consistency-audit-2026-06-16.md`).

### 근거

- 멱등 upsert는 안정 feature_id를 전제로 한다. concierge는 producer가 보장하는 안정 키
  (candidate.id)가 이미 있으므로, 식별자를 거기에 고정하면 늦은-바인딩 분기를 원천 제거한다.
- bjd/category를 식별자에서 빼도 정보 손실이 없다 — 둘 다 Feature/Address에 그대로 남고
  공간 쿼리(`coord_5179`)·표시·dedup 후보 비교에 쓰인다.
- 대안(geocoder 필수화)은 약하다 — geocoder 출력이 좌표/버전에 따라 바뀌면 여전히 분기하고,
  category 분기는 못 막는다.

### 결과

- `src/kortravelmap/providers/kor_travel_concierge.py` `_item_to_bundle`이 정본 구현이다
  (`_FEATURE_ID_IDENTITY_CATEGORY` 상수 + `bjd_code=None` 파생).
- 회귀 테스트: geocoder 유무 동일 feature_id, category None↔8자리 동일 feature_id
  (`tests/unit/test_providers_kor_travel_concierge.py`). producer가 admin 코드를 None으로
  보내는 계약을 픽스처가 반영한다(C-03 교정).
- **이행**: concierge 실데이터가 이미 적재돼 있으면 구 파생(bjd/category 포함) feature_id가
  남는다. 구 파생은 이미 비멱등이었으므로 1회성 교정 — 다음 full `/features/snapshot`
  재import가 안정 `f_global_` feature를 만들고, 구 행은 기존 inactive/dedup 도구로 정리한다.
  alembic 불필요(feature_id는 import 시 재파생). 현 시점 concierge live 적재 전이면 무영향.
- 잔여 하드닝(C-04 inactivate 키 일관성, C-05 operation 분류 폐쇄화, C-06/C-08 테스트,
  C-07 base_url 문서, concierge측 P-01)은 검증 리포트에 후속으로 기록한다.
