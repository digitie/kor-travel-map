# feature-id-determinism.md — UUID 정본과 legacy feature ID 전환

Feature identity의 정본은 ADR-068의 **UUID surrogate**다. provider identity는
`(provider_dataset_id, source_entity_type, source_entity_id)` 자연키 UNIQUE로 따로 보장하며
`bjd_code`, `category`, 이름, 좌표는 Feature ID를 만들지 않는다. 아래 구 `make_feature_id`
규칙은 T-VN-32 전환 전 현행 동작과 legacy alias의 유래를 설명하기 위해서만 보존한다.

## 1. vNext UUID 정본과 legacy alias

- 신규 Feature PK는 애플리케이션 generator가 만드는 UUID다. REST와 consumer는 이를 opaque
  string으로 취급하며 prefix·순서·provider를 파싱하지 않는다.
- 기존 `f_*` 값은 `feature.feature_aliases`에서 UUID를 가리키는 `legacy_feature_id` alias로
  강등한다. 신규 row의 정본 ID를 `make_feature_id`로 생성하지 않는다.
- provider 재수집 멱등성은 Feature UUID hash가 아니라 provider dataset FK와 source-native
  identity UNIQUE, source entity→Feature 연결로 보장한다.
- T-VN-32는 UUID shadow column/FK와 alias map을 backfill하고 PinVi를 consumer-first로 전환한다.
  soak 전에는 alias를 제거하지 않으며 rollback은 alias projection으로 수행한다(ADR-075).

## 2. legacy 문제: 늦은-바인딩 식별자

`make_feature_id`는 모든 provider 공통으로 `bjd_code`·`category`를 식별자 입력에 넣는다
(ADR-009 결정성). 대부분 provider는 둘 다 안정적이다 — bjd는 provider가 주는 주소/좌표에서
한 번 정해지고, category는 데이터 종류로 고정된다. 그러나:

- **bjd를 reverse geocoder로 채우는 provider**(opinet/krex/knps/krheritage/khoa/krairport/
  airkorea/standard_data/krforest/mcst/datagokr_file_data 등)는 geocoder 유무·버전·출력에
  따라 같은 record가 `f_global_…`↔`f_<bjd>_…`로 갈린다.
- **category를 enrich 후 채우는 export provider**(kor-travel-concierge)는 category가
  None(→fallback)→실제 8자리로 바뀌면 같은 후보가 새 feature로 갈린다.

두 경우 모두 멱등 upsert가 깨지고 dedup이 단절된다. reject/tombstone→inactive 라이프사이클
경로는 `source_entity_id` 매칭이라 면역이지만, upsert 경로가 비멱등이었다.

## 3. legacy concierge 완화: 안정 candidate.id에 고정 (구 ADR-057)

kor-travel-concierge export는 `place.address.{legal_dong_code,sido_code,sigungu_code}`를
항상 None으로 보내고(bjd는 소비자가 reverse geocoding으로 채우는 계약), `category_code_suggestion`은
Gemini enrich 전 None이라 채워지면 payload 변경 upsert로 재export된다. 따라서 bjd/category가
모두 늦게 바인딩돼 같은 후보가 재export마다 새 feature로 갈렸다.

**결정**: concierge feature_id는 producer가 보장하는 **안정 식별자**에만 고정한다 —
`(kind=place, source_type=provider/dataset 상수, source_natural_key=candidate.id)`.
feature_id 파생에서 `bjd_code`(→`bjd_code=None`, prefix `f_global_`)와 category(→고정
`_FEATURE_ID_IDENTITY_CATEGORY`= provider TOURISM 상수)를 **뺀다**. 실제(가변) bjd·category는
식별자가 아니라 **표시·공간 속성**으로 `Address.bjd_code`·`Feature.category`에 싣고, 재import마다
같은 feature_id에 in-place 갱신한다. 정보 손실 없음 — 공간 쿼리(`coord_5179`)·표시·dedup
후보 비교에 그대로 쓰인다. 이 정책은 **concierge 한정**이다(다른 provider는 bjd/category가
안정적이라 기존 동작 유지). 정본 구현은 `src/kortravelmap/providers/kor_travel_concierge.py`
`_item_to_bundle`(`_FEATURE_ID_IDENTITY_CATEGORY` 상수 + `bjd_code=None`),
회귀 테스트는 `tests/unit/test_providers_kor_travel_concierge.py`(geocoder 유무·category
None↔8자리 동일 feature_id). 검증 정본: `docs/reports/concierge-loader-verify-2026-06-15.md`
(C-01/C-02). (구 ADR-057)

## 4. legacy geocoder 완화: geocoder 필수화 (F-01, 구 ADR-058)

concierge 외 ~11개 geocoder-의존 provider는 bjd를 Dagster `reverse_geocoder` resource에서
얻는데, 이 resource가 `kor_travel_geo_base_url` 미설정 시 조용히 None을 yield해 같은 record가
`f_global_…`↔`f_<bjd>_…`로 갈리는 비멱등을 일으켰다(정합성 감사 F-01).

**결정(B 채택, re-key 없음)**: `reverse_geocoder_resource`가 base URL 미설정 시 silent-None
대신 **즉시 실패**(RuntimeError)한다. geocoder를 운영 필수로 강제해 좌표 보유 record의 bjd가
항상 resolve되도록 함으로써 같은 run/재import에서 feature_id 결정성을 확보한다. bjd/category는
기존대로 식별자에 둔다(전 feature DB re-key 회피). 좌표 없는 record는 bjd None=`global`로 일관.
직접 `reverse_geocoder=None` override(테스트의 weather/offline 등 bjd-비의존 경로)는 영향 없다.
근거: re-key 없는 최소 변경으로 운영 결정성을 확보 — geocoder는 place provider에 어차피 필수
이고, silent-None은 "geocoding 미구성" 운영 실수를 비멱등 데이터로 숨겼으므로 fail-fast가 옳다.
정본 구현: `packages/kor-travel-map-dagster/src/kortravelmap/dagster/resources.py`
`reverse_geocoder_resource`(+ `test_resources.py` 회귀). 정본 리포트:
`docs/reports/full-consistency-audit-2026-06-16.md` F-01. (구 ADR-058)

**잔여(약한 보장)**: geocoder 필수화는 좌표→bjd가 항상 채워지게만 보장한다. geocoder가 같은
좌표에 다른 bjd를 주면(버전 drift) 여전히 분기 가능하다. 완전 결정성은 식별자에서 bjd를 제거하는
방식(=concierge에 적용한 §3 방식의 일반화, 선택지 A)이 필요하나, 전 feature_id 재키 + provider별
natural_key 전역유일성·collision 분석이 동반돼 실데이터 운영 중에는 보류한다(후속 `T-AUDIT-0616`).
"안정적"이 진짜 보장되는 케이스는 MOIS의 source-native `legal_dong_code`처럼 provider가 직접
제공하는 행정코드 케이스에 한정된다.
