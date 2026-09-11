# ADR-098: provider Feature identity는 `(dataset, kind, 자연키)`다 — source entity가 아니다

- 상태: accepted
- 날짜: 2026-09-09
- 결정자: human, AI agent
- 관계: [ADR-068](068-feature-uuid-identity.md)이 정본 PK를 UUID surrogate로
  옮기면서 **무엇이 그 UUID를 결정하는지**는 정하지 않았다. 이 ADR이 그 빈자리를 채운다.
  [ADR-083](083-nonderived-uuid-generator-and-value-cutover.md)의 비파생 UUIDv7 generator를 되돌리지 않는다.
  [ADR-096](096-catalog-identity-is-the-natural-key.md)이 경고한 "대리키는 계약이 아니다"를
  이 표에도 적용한다. [ADR-009](009-deterministic-feature-id.md)의 `make_feature_id`는 identity 결정자에서
  **alias 생성기**로 역할이 바뀐다.

## 컨텍스트

T-VN-39가 `feature.features.feature_id`를 legacy TEXT 업무키에서 UUID surrogate로 물리
재키한다. 그런데 **오늘 provider 적재의 멱등을 지탱하는 유일한 축이 바로 그 업무키다.**

- writer는 매 호출 새 UUIDv7 후보를 만든다
  (`src/kortravelmap/infra/feature_repo.py`의 `_feature_params`).
- 프로시저는 `ON CONFLICT (feature_id) DO NOTHING`이고, 그 `feature_id`는
  `make_feature_id(...)`가 만든 결정적 `f_*`다.

재키 후 둘 중 하나가 **반드시** 일어난다. provider가 계산한 `f_*`를 그대로 보내면 22P02이고,
새 UUIDv7을 보내면 충돌이 **영원히 걸리지 않아** 매 ETL마다 중복 Feature가 생긴다. 후자는
DDL 오류도 타입 오류도 내지 않는다 — 1회 적재만 하는 테스트는 전부 초록이고, 증상은
**두 번째 ETL**에서 처음 나타난다.

따라서 identity 해석 재설계는 재키의 부수 효과가 아니라 **본체**다.

ADR-068은 결정 1에서 "애플리케이션이 생성하는 UUID surrogate"를, 결정 2에서 "provider
identity는 `(provider_dataset_id, source_entity_type, source_entity_id)`의 UNIQUE로
보장한다"를 정했다. 그러나 결정 2는 **source entity의 identity**를 말한 것이고, 그 entity와
Feature의 대응 관계(1:1인지 N:1인지)는 어디에도 없다. 그 빈자리가 아래 두 번의 실패를 낳았다.

## 두 번의 실패 — 축을 두 번 틀렸고 두 번 다 실측이 잡았다

### 1차 (2026-09-08) — `source_links`의 primary link를 축으로 삼았다

`provider_sync.source_links`에 `UNIQUE (source_entity_key) WHERE source_role = 'primary'`를
재키 **앞에** 심었다. 단위 게이트 24건은 통과했다. **통합 1179건 중 17건이 빨개졌다.**

이유를 테스트가 스스로 적어 뒀다 — `tests/integration/test_notice_lifecycle.py`:

> identity 이행 중 하나의 current source entity가 **구/신 feature 양쪽에 primary link로
> 남은 실제 형태**를 재현한다.

`make_feature_id`가 `bjd_code`·`category`를 해시 입력에 쓰므로, 재분류나 행정구역 변경이
일어나면 새 Feature가 주조되고 같은 entity가 구·신 양쪽의 primary가 된다. 즉 "한 entity →
한 primary Feature"는 **오늘의 불변식이 아니다.**

### 2차 (2026-09-09) — 축 자체가 틀렸다

되돌린 뒤 조사가 `src/kortravelmap/providers/opinet.py`를 찾았다:

```python
source_entity_id   = f"{item.uni_id}:{prodcd}"   # 제품별 N개
source_natural_key = item.uni_id                 # 주유소별 1개
```

그리고 그 경로의 공개 함수 docstring이 명시한다 — "그 단일 제품 가격을 **같은 price anchor
feature에 누적**해, 전국 저가 주유소 분포를 쿼터 안에서 표시하기 위한 보조 적재다."

즉 **entity → Feature는 정당하게 N:1이다.** entity를 identity 축으로 삼으면 새 제품코드가
등장할 때마다 새 price Feature가 주조된다 — 재키가 고치려던 중복을 재키가 만든다.

## 결정

**1. provider 원천에서 온 Feature의 identity는 `(provider_dataset_id, feature_kind,
natural_key)`가 결정한다.**

이것은 `make_feature_id` 입력
(`bjd_code | kind | category | source_type | source_natural_key`)에서 **ADR-068 결정 2가
identity 입력이 아니라고 못 박은 `bjd_code`·`category`만 뺀 것**이다. 남는 셋이 축이다.

**2. 그 결박은 `provider_sync.provider_feature_identities`가 물화한다.**

PK가 위 세 컬럼이고 `feature_id uuid`를 돌려준다. **`feature.features`로 가는 FK를 두지
않는다** — claim이 Feature보다 먼저 서야 하기 때문이고, manual 경로의
`feature.manual_feature_identity_claims`가 정확히 같은 이유로 같은 모양이다. provider가
네 번째 형제를 갖는다.

**3. `f_*`는 identity가 아니라 alias다.**

`make_feature_id`의 함수 본문은 바뀌지 않는다. 바뀌는 것은 **계약**이다 — 그 산출물은
`feature.feature_aliases`에 실리는 legacy 주소이지 Feature를 결정하는 값이 아니다.
`Feature.provider_natural_key`가 축의 세 번째 성분을 나른다.
`FeatureBundle.source_record.source_entity_id`로 **대신할 수 없다**(위 opinet).

**4. `source_entity_key`는 provenance 축으로 남는다.**

`uq_source_entities_provider_identity`는 그대로 옳다 — 그것은 **source entity의** identity다.
`source_links`는 "이 Feature가 어떤 원천에서 왔는가"를 기록하는 N:M 관계이고, identity
해석에 쓰지 않는다. `UNIQUE (source_entity_key) WHERE source_role='primary'`는 넣지 않는다.

**5. `provider_dataset_id`는 이 표 안에서만 뜻이 있다.**

ADR-096이 경고한 그대로다 — 대리키는 DB-local이고 실제로 baseline seed와 prod에서 값이
갈린 이력이 있다(69 vs 73). 그러므로 이 표의 행을 **migration에 리터럴로 적지 않고**,
DB 사이에서 비교하지 않는다. 이식이 필요하면 `(provider, dataset_key)`로 풀어서 옮긴다.
`uq_source_entities_provider_identity`가 이미 같은 규율로 산다.

**6. `feature_aliases`는 "모든 Feature의 두 번째 이름"이 아니라, 바깥에서 이 Feature를
가리킨 적이 있는 주소의 등록부다.**

재키(`309`) 뒤 alias를 발급하는 주체는 둘뿐이다 — 이전 세대가 실제로 발행했던 `f_*`를
옮겨 싣는 backfill과, provider 생성 경로 `create_provider_feature_with_initial_state`.
**admin 수동·요청 승인·큐레이션·core 네 경로가 만든 Feature는 alias를 갖지 않으며 그것이
정상 상태다** — 결손이 아니다.

근거는 정보량이다. provider `f_*`는 `sha1(bjd|kind|category|source_type|natural_key)`라
provider 레코드를 가진 제3자가 Map을 한 번도 본 적 없어도 계산해 들고 오는 주소이고,
결정 1 아래에서 재분류로 그 값이 바뀌어도 옛 주소가 alias로 남아 구 URL이 산다. manual
`f_*`는 `sha1(…|manual::{서버가 방금 발급한 UUIDv7})`라 **정본 키의 순수 함수**다 — 밖에서
계산할 수 없고, 계산할 수 있는 사람은 이미 정본 키를 쥐고 있으며, uuid는 드리프트하지
않으므로 "재분류마다 alias가 한 행 는다"는 이득이 원리적으로 발생하지 않는다. 등록부에
실을 **바깥 주소가 애초에 없다.**

ADR-068 결정 3 원문은 "**기존** `f_*` 값은 … 보존한다"로 **보존 규칙이지 발급 규칙이
아니다.** "모든 Feature가 alias를 갖는다"는 보편 명제는 원문에 없었고, 사라진 트리거
`trg_features_legacy_alias`와 `consumer-rollout-v1.json` 32B 문안이 만든 산물이었다. 이
결정은 그 원문의 범위로 되돌리는 것이지 ADR-068을 개정하는 것이 아니다.

계약 층의 착지점도 함께 옮긴다. `target-invariants-v1.sql`의 `[INV-068-01]`을 완전성
불변식("backfill 후 모든 feature는 alias를 1개 이상 가진다")에서 **형태** 불변식("정본
키(uuid) 표기를 alias로 되풀이하지 않는다")으로 교체한다. head에서 같은 규칙을 강제하는
`ck_feature_aliases_legacy_alias_shape`는 309가 되살릴 수 없이 내린
`ck_feature_aliases_legacy_identity`(`alias = feature_id`)의 **구조적 후계자**다.
`uuid = text` 연산자가 없어 값 관계로는 재부착이 영구 불가능해진 자리를, legacy alias의
형태(`f_{bjd|global}_{kind[0]}_{sha1[:16]}`)로 받는다.

## 근거

identity를 **변하지 않는 것**에 매단다. `bjd_code`는 reverse geocoder가 주고 geocoder
revision이나 좌표 보정에 따라 바뀐다. `category`는 분류 정밀화에 따라 바뀐다. 둘 다
Feature가 *무엇인지*를 말하지 않고 *어떻게 보이는지*를 말한다.

`natural_key`는 provider 시스템 안의 그 사물의 이름이다 — 주유소 코드, 휴게소 코드,
특보 구역·현상 쌍. 그것이 바뀌면 그것은 다른 사물이다.

## 결과

- **긍정**: 재분류·행정구역 변경이 **제자리 갱신**이 된다. 오늘은 Feature가 갈라지고
  뒤처리 기계가 필요했지만, 이 축에서는 alias가 한 행 늘 뿐이다 — 구 URL이 영구
  보존되는 것은 손실이 아니라 이득이다.
- **긍정**: `make_price_value_key`/`make_weather_value_key`가 `feature_id`를 해시 입력으로
  받으므로 fact key가 처음으로 진짜 불변이 된다(오늘은 bjd/category 드리프트마다 갈렸다).
- **부정**: 그 fact key가 **전부 달라진다.** 재적재가 필요하고, 소유자가
  "데이터는 나중에 다시 로드해도 됨"으로 그 비용을 승인한 아래에서만 수용 가능하다.
- **부정**: `Feature.provider_natural_key`를 provider 28곳에 손으로 실어야 한다.
  `tests/lint/test_provider_features_carry_their_natural_key.py`가 그 28곳을 결박한다 —
  모듈별 수 대조와 같은 함수 안 쌍의 글자 그대로 일치를 잰다.
- **전환/rollback**: 표는 재키 **이전** revision(`308`)에서 만들고, 백필·wrapper·writer
  전환은 재키와 **같은 트랜잭션**에서 한다. 나누면 "멱등 앵커 없는 head"가 배포 가능해지고
  증상이 두 번째 ETL까지 숨는다.

## 기존 결정과의 관계

- **ADR-068** 결정 1·2를 되돌리지 않고 **빈자리를 채운다.** 결정 2의 UNIQUE는 source
  entity의 identity로 그대로 유효하다. 결정 3도 개정하지 않는다 — 원문이 "기존 `f_*`
  값은 … 보존한다"는 **보존 규칙**이라 결정 6의 발급 규칙과 충돌하지 않는다.
- **ADR-083**의 비파생 UUIDv7 generator를 유지한다. `feature_uuid_from_legacy`(uuid5 파생)로
  되돌리는 안은 기각한다 — ADR-083이 그것을 의도적으로 버렸고,
  `admin_feature_repo`의 `_canonical_uuid7_or_invariant`가 `version != 7`을 거부한다.
- **ADR-009**의 `make_feature_id`는 함수로서 살아 있되 **역할이 바뀐다** — identity
  결정자에서 alias 생성기로. 그 모듈 docstring의 "`bjd_code`가 변경되면 `feature_id`도
  바뀐다 — 이는 의도된 동작. 옛 feature는 soft-delete + 새 feature 생성"은 이 ADR 이후
  **거짓**이므로 함께 고친다.
- **ADR-096**의 "대리키는 계약이 아니다"를 `provider_feature_identities`에 적용한다(결정 5).

## 이 결정이 틀릴 수 있는 지점

`natural_key`가 provider 시스템에서 **재사용**되면(폐업한 주유소 코드를 다른 주유소에
배정하는 식) 서로 다른 사물이 같은 Feature로 합쳐진다. 오늘의 `f_*` 축도 같은 약점을
갖지만, 그쪽은 `bjd_code`가 달라 우연히 갈라졌을 수 있다. 이 축은 그 우연을 없애므로
약점이 드러난다.

측정 방법: `provider_feature_identities`의 한 행이 가리키는 Feature의 좌표·이름이
`bound_at` 이후 **급격히** 바뀌는지 감시한다. 그런 사건이 실제로 관측되면 축에
`source_entity_type`을 더하거나 provider별 재사용 정책을 명시해야 한다.

결정 6은 더 약하다 — 재키 후에도 manual Feature를 `f_*`로 부르는 운영 관행(옛 로그·티켓)이
남아 있다면, 같은 주소로 조회했을 때 provider만 찾히고 manual만 사라지는 비대칭이 운영
문제로 돌아온다. 측정 방법: 전환·복구 경계의 alias lookup에서 `f_*` miss를 세고 manual
계열에 몰리면, 발급 규칙을 되돌리는 대신 정본 키에서 표시용 옛 주소를 만드는 번역기를 둔다.
