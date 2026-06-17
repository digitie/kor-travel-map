# ADR-046: 정본 방향 전환은 호환 shim 없이 하고 주소는 kor-travel-geo REST v2로 통일

- **상태**: accepted
- **날짜**: 2026-06-02
- **결정자**: 사용자
- **관련**: ADR-041, ADR-045

### 컨텍스트

ADR-045로 kor-travel-map 운영 모델이 Docker 독립 프로그램 + 독립 DB/Dagster +
외부 경계 OpenAPI로 바뀌었다. 또한 ADR-041로 `python-kraddr-base` 의존을
제거하고 좌표는 `Coordinate`, 주소는 `Address`로 본 저장소가 소유한다. 문서와
일부 예시에는 여전히 다음 구 모델 표현이 남아 있었다.

- `kor-travel-map-admin`, `map_debug_ui`, `KOR_TRAVEL_MAP_DEBUG_UI_*` 같은 구 패키지명/env.
- 외부 소비자가 `kor-travel-map`을 직접 import하거나 같은 DB를 공유하는 흐름.
- provider 주소 문자열이나 자체 행정코드를 그대로 `features.address`/행정코드로
  저장하는 흐름.
- kor-travel-geo v1 `/v1/address/*` 또는 `PlaceCoordinate`/`kraddr.base.Address` 예시.

사용자는 "호환성 신경 안쓰고 올바른 방향으로 검토"와 "kraddr geo rest api는 v2로
다 바꿔"를 지시했고, provider 주소도 kor-travel-geo를 통해 얻은 주소로 통일하며
결측값과 주소/좌표 불일치도 admin UI에서 수동 처리할 수 있어야 한다고 확정했다.

### 결정

1. **구 모델 호환 shim 금지**
   - 구 패키지 경로 `packages/kor-travel-map-admin/`, Python namespace
     `kortravelmap_debug_ui`, env prefix `KOR_TRAVEL_MAP_DEBUG_UI_*` 호환 shim을 만들지
     않는다.
   - 외부 소비자 직접 import, 공유 DB를 유지하기 위한 adapter도 만들지 않는다.
   - 문서와 코드의 정본은 `kor-travel-map-admin`, `kortravelmap.api`,
     `KOR_TRAVEL_MAP_API_*`, OpenAPI, 독립 DB/Dagster다.

2. **kor-travel-geo REST v2만 사용**
   - 주소/좌표 보강은 `POST /v2/reverse`, `POST /v2/geocode`만 정본으로 문서화한다.
   - `/v1/address/*`는 역사 기록 외 실행 문서에서 사용하지 않는다.
   - health check 같은 운영 endpoint는 이 ADR의 주소 정/역지오코딩 계약 범위 밖이다.
     주소 기능 문서와 kor-travel-map 구현 지시는 kor-travel-geo REST v2만 기준으로 삼는다.

3. **주소 정본은 kor-travel-geo 결과**
   - provider가 제공하는 주소 문자열, 시군구명, 자체 행정코드는 raw/provenance다.
   - `features.address`, `legal_dong_code`, `sigungu_code`, `sido_code`,
     `road_name_code`, `road_address_management_no`, `zipcode`의 정본은 kor-travel-geo
     REST v2 결과로 만든 `kortravelmap.dto.Address`다.
   - 좌표가 있으면 좌표 기준 `POST /v2/reverse` 결과를 정본 주소로 삼는다.
   - 좌표가 없고 주소 문자열이 있으면 `POST /v2/geocode`로 좌표 후보를 얻고,
     다시 `POST /v2/reverse`로 주소를 정규화한다.
   - 좌표와 주소가 모두 있으면 좌표 기준 reverse 결과와 provider 주소를 비교해
     `AddressMatchReport`를 남긴다.

4. **결측/불일치는 admin issue로 수동 처리**
   - kor-travel-geo 호출 실패, 결과 없음, confidence 미달, provider 주소와 좌표 기준 주소
     불일치, 법정동코드 충돌은 `ops.data_integrity_violations` 또는 후속 주소 검토
     큐에 올린다.
   - Admin UI는 `provider_address_mismatch`, `provider_address_partial_match`,
     `geocode_failed`, `reverse_geocode_failed`, `missing_address`, `missing_bjd_code`
     issue를 지도/테이블에서 보여준다.
   - producer 상태(F-02 구현, 2026-06-16): `reverse_geocode_failed`는
     `validate_feature_bundle_address`가 **좌표-있음+bjd-없음**(reverse 호출이 bjd를 못 냄)
     케이스에서 발행한다. 함께 `missing_address`/`provider_address_mismatch`/
     `provider_address_partial_match`도 발행. `geocode_failed`(forward, 주소→좌표)는 적재
     경로에 forward-geocode가 없어 **미발행**(정의만 존재).
   - 운영자는 admin UI에서 kor-travel-geo 재시도, 좌표 수정, 주소 수정, kor-travel-geo 주소
     채택, 수동 override, ignored/reopen 처리를 할 수 있어야 한다.
   - 수동 override는 `ops.feature_overrides`와 audit log에 기록하고 provider 재적재가
     덮어쓰지 않도록 한다.

### 근거

- 호환 shim은 이행 기간을 길게 만들고 에이전트가 구 경로를 계속 복붙하게 만든다.
- provider 주소와 행정코드는 형식·정밀도·의미가 provider마다 달라 정본으로 삼기 어렵다.
- kor-travel-geo는 주소/좌표/행정구역 정규화 전용 서비스이므로 정본 책임을 한 곳에 모으는
  편이 운영상 명확하다.
- 주소와 좌표가 동시에 있을 때는 좌표가 지도 feature의 실제 위치를 결정하므로, 좌표
  기준 reverse 결과를 우선하고 provider 주소는 검증 대상으로 쓰는 편이 일관적이다.

### 결과 (긍정)

- 문서와 코드 경계가 단순해진다. 새 구현자는 하나의 이름/환경/API만 따른다.
- feature 주소와 행정코드 품질이 provider별 편차에 덜 흔들린다.
- 주소/좌표 오류가 운영 큐로 표면화되어 admin UI에서 수정 가능하다.

### 결과 (부정)

- 구 env/import/path를 쓰는 로컬 스크립트는 깨질 수 있다. 의도된 결과다.
- kor-travel-geo 장애 시 provider 적재의 주소 품질이 떨어지고 issue가 증가한다.
- 좌표가 잘못된 provider row는 주소도 잘못 정규화될 수 있으므로 admin 검토와
  manual override 흐름이 필수다.

### 후속

- 실행 문서의 `/v1/address/*`, `PlaceCoordinate`, `kraddr.base.Address` 표현을 정리한다.
- `docs/architecture/address-geocoding.md`에 주소 정본 정책과 `AddressMatchReport`/admin issue
  흐름을 명시한다.
- `docs/debug-ui-admin-workflows.md`와 `docs/architecture/openapi-admin-contract.md`에 주소 검토
  issue action을 추가한다.
- `ops.data_integrity_violations` 구현 시 주소/좌표 issue payload shape를 포함한다.
