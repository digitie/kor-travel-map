# PinVi admin Feature 전용 읽기 scope

## 문제와 구현 범위

PinVi의 Feature 목록·단건은 공개 DTO가 아닌 기존 admin DTO를 필요로 한다. 기존
legacy ServiceToken은 admin BFF의 secret·trusted peer·actor 권한을 부여하지 않으므로,
그 값을 재사용하는 요청은 정상적으로 거부된다. 별도 digest principal
service:pinvi:admin-features:read에 pinvi:admin-features:read만 부여한다.

새 표면은 GET /v1/service/admin-features와
GET /v1/service/admin-features/{feature_id} 두 개다. 기존 admin endpoint 함수를
그대로 등록해 전체 필터·페이지·alias 해석·source/issue/override/비공개 curation DTO를
공유한다. 새 DTO나 조회 구현은 없다. POST/PATCH/PUT/DELETE 및 revision·state·가격
하위경로는 추가하지 않는다. 기존 admin BFF/write와 ops/legacy 정책은 유지한다.

## 자격증명·철회 계약

Map은 KOR_TRAVEL_MAP_API_PINVI_ADMIN_FEATURES_READ_TOKEN_SHA256에 별도 raw token의
lowercase SHA-256 digest만 저장한다. 기본 미설정과 빈 값은 두 GET을 fail-closed한다.
PinVi의 PINVI_KOR_TRAVEL_MAP_ADMIN_FEATURES_READ_TOKEN은 별도 SecretStr이며 목록·단건에만
ServiceToken 헤더로 전송한다. 실제 provision은 Manager의 명시적 설정 작업과 최종
compatible pair 검토 이후 수행한다. 이 소스 작업은 운영 자격증명을 만들거나 배포하지 않는다.

기존 scoped digest·cache registry·admin/legacy/ops/metrics 등 보호된 자격증명과
중복되면 설정 검증에서 거부한다. 다른 정상 scope의 token은 403, 누락/미확인 token은
401이며 다른 scope로 fallback하지 않는다. bare digest 방식에 새 만료 시계는 없다.
철회는 digest 제거 또는 교체로 수행하며 원 token 재사용 거부를 시험한다. 이 권한은
admin write나 다른 scoped service 권한을 추가하지 않는다.

## 검증과 한계

DB 없는 실제 ASGI 요청으로 두 GET의 인증·철회·잘못된 scope·필터·기존 전체 DTO·
identity resolver·404/422 및 쓰기 405를 검증한다. 기존 auth/admin/route-policy/
curation/OpenAPI 회귀도 함께 실행한다. 첫 새 시험에서 OPS 3종 설정 누락·짧은 시험
token과 TestClient DELETE 인자 오류를 확인했고 원 로그를 보존한 뒤 fixture만 정정했다.

정본 exporter로 admin/service/user OpenAPI와 openapi-typescript 7.13.0 타입을 갱신한다.
기존 모든 path/model 의미는 동일하고 service GET 두 개만 추가한다. user spec은
바이트까지 동일하다. 관련 7개 모듈 실행은 238 PASS/2 FAIL(새 route 목록·dependency 기대값 누락)이었고,
기존 단언을 유지한 채 exact GET 두 개와 해당 enforcement를 기대 목록에 추가했다.
새 21개 ASGI 회귀와 위 두 원 실패를 묶은 재검증은 23 PASS/18.69초다.
단일 240 PASS 실행으로 합산하지 않는다. 독립 두 리뷰·최종 CI·
실제 provision/새 compatible pair UI 인수는 별도 gate다. 이 단계 PG·운영 변경은 없다.
