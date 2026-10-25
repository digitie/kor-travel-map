# PinVi admin Feature 전용 읽기 scope

## 최종 공개 R7과 원 일정 복원

최종 공개 TLS 읽기 R7은 Map7·PinVi6, 총13단계를 통과했다. 운영의 실제 기존 행 목록·선택·
동일 ID 상세/성공 DOM·인증 reload·지도와 lineage를 확인했으며 synthetic 취소/create/approve 등
업무 쓰기는 실행하지 않았다. 성공 실행에서 양쪽 로그인·로그아웃 POST는 각각1회다.
Map은 로그인200·인증 읽기200·logout200·보호401, PinVi는 로그인200·logout204·보호401을
확인했다. PinVi의 실제 지도 tile21개·오류0, 목록 GET2004회·단건 GET2002회다.

Map 하네스는 routing의 native cache 비활성화와 구분하여 같은 origin의 허용된 불변 정적 파일만
첫 실제 public 응답의 status/header/body를 RAM에 보관해 재사용했다. 인증/API/HTML/provider는
이 캐시의 대상이 아니다. 첫 응답의 유효 freshness175초 이상·항목4MiB/합16MiB·192개/동시4를
검증하고 실제 네트워크 상한256은 유지했다. 실제 허용204·cache miss71/hit80·retained peak
3,682,149B·동시4를 관측했다. hit80은 실제 HTTP80회나 새 서버 응답 검증으로 세지 않으며,
이 bytes 지표를 전체 브라우저/Node RSS 상한으로 쓰지 않는다. 원blocked0/13단계/reload를
유지했고 최종 차단·page/hydration/cache/late 오류0·route 정산 완료다.

이번 실행의 원 env·7개 runtime identity와 브라우저 inventory106개는 전후 같았고 소유 process와
profile을 제거했다. 새 두 테스트 세션의 미철회 가능성False는 이번 성공 실행의 결과이며,
아래 원3 FAIL과 R4의 possible_unrevoked=True를 고치지 않는다. Map 인증은 stateless cookie
경계이고 폐기된 원 R4 cookie를 복원하거나 계정 전체 철회·키 회전을 하지 않았다.

원 Map instigator는47개/RUNNING38개였고 최종51개/RUNNING37·STOPPED14를 확인했다.
새 항목은 모두OFF이며 퇴역한 feature_notice_transport_highway_incidents_ten_minute_schedule은
복원하지 않았다. 전체 수집·신규 schedule 활성화나 W/T opt-in 완료를 뜻하지 않는다.
전용 읽기 자격은 Map API digest만·PinVi API raw만 유지하며 PinViWeatherOFF도 유지했다.

이 정산은 배포된 현재 pair의 읽기/auth와 원 일정 복원에 한정된다. Rest431/432 영속 연결,
물리 두writer·전체 수집 CPU/메모리 개선·상위 전체1commit은 별도 미완이다.
공개 원본 SHA-256 c2f8b77347606329485730d650e52ef227731b920bf4e5022466f98ef93523d7,
독립 수용 b8c77588de604d95b522092756c71b131ae6905ef01afe4d277ff59c932cc6e7,
일정 복원 수용 168bf634847cffc56013c4e6aea5921129642b7b0b7ba621dbf0e70a19866735.

## 2026-10-26 · 머지·후보·최종 배포 완료, 공개 읽기·일정 복원 수용

Map #1414의 merge는6e273cb, #1411을 포함한 기준 main은5f3506a다. PinVi #602는
8f1b998f로 머지됐다. Map29f1과 PinVi830260 후보의 tree는 각 머지 tree와 같다.
이하 구현·검증 절의 미완 표기는 당시 checkpoint 기록으로 보존한다.

별도 격리 pair의 최종 성공 실행은6단계를 통과했다. 비인증401, 실제 로그인·HttpOnly
cookie·reload, 실제 지도 canvas/tile, 목록 필터·admin DTO, 같은 source의 상세 lineage,
로그아웃204·보호401을 확인했다. 해당 성공 실행의 로그인·로그아웃 POST는 각각1회,
실제 Map 목록 GET200은2회·단건 GET200은1회, provider tile은16개이며 테스트 세션1개는
철회됐다. 임시 DB·role·브라우저 profile·실행 프로세스와 정확 PG 자원을 정리했다.

앞선3 FAIL은 managed migration fence 준비 누락, Node 진입점 미호출,
로그인·reload 단계 실패로 각각 보존한다. 세 번째 실행은401만 통과했고 상세 상태가
기록되지 않아 실제422를 관측했다고 쓰지 않는다. 이 실패들을 최종 성공 수에 합산하지 않는다.
Map 취소·replay14판정은 별도 후보 실행이며 이 pair에서 다시 실행한 결과가 아니다.

후보는 격리 HTTP 실행이며 운영 TLS·실데이터 공개 읽기 인수와 구분한다. 배포 전 새 Map·PinVi
백업의 공식 격리 복원 리허설은 모두 verified로 통과했다. Map은 복원 scratch의 소유권·ACL·
routine 보안 속성 차이에 대한 비차단 REHEARSAL_CATALOG_DRIFT 경고를 보존한다. schema revision
수용이며 catalog 전체 동등성 수용은 아니다. 첫 운영 단계의
Map99fe742c/schema418+기존 PinVi commit 뒤 새 token1키의 정식 CAS provision과 최종
Map5f3506a/PinVi8f1b998f rotate·공식 rebuild가 완료됐다. 최종 영수증은 committed·경고0이며
새 readback은 Map schema430·PinVi schema0102와7개 healthy·runtime identity 일치를 확인했다.
읽기 자격은 Map API digest만·PinVi API raw만 전달됐고 같은 CAS 원천 일치와 WeatherOFF도 확인했다.

첫 공개13flow 실행은 Map 비인증401만 통과한 뒤 로그인 POST401로 실패했다. PinVi는
미도달이며 공개 UI 인수로 세지 않는다. finally logout 요청1회 뒤 소유 브라우저·profile 제거,
원 env 불변·미철회 테스트 세션 없음은 확인했다. 원 실패를 보존하며 이 첫 시점에는 공개 읽기 재검증과 원 일정
복원이 미완이었다. 이 문서 변경 자체는 운영 env·자격·DB·컨테이너를 변경하지 않는다.
최종 배포 수용 readback SHA-256은
e0b0a119123c4211c4e7f33809d9e9d3dfa31e86ff8d44c1db754297e51089cf,
첫 공개 실패 영수증은
efe30f095d98783451d0b52a8da169a96f58f65ddf558db59d1c6ed6be2926ec다.

두 번째 공개 실행도 별도 실패로 보존한다. Map 비인증401·로그인200/보안 HttpOnly cookie·
hydration·지도/목록 기본 표시의 첫4단계 뒤 기존 행 상세 단계에서 TimeoutError가 발생했다.
차단 요청25개·provider tile40개가 관측됐지만 상세 성공이나 PinVi 단계 통과로 세지 않는다.
로그아웃 POST0으로 테스트 세션 철회는 미확정이다. 소유 브라우저/profile 제거와 원 env 불변만
확인했으며 원인 분리는 별도 후속으로 진행했다. 이 실행의 미확정은 그대로 남긴다. 원 실패 SHA-256은
1886316e23b2e6b5c904ce049aaa3fc1e449fb4cc786842431333f04ab79aaac다.

세 번째 공개 실행은 Map 실상세까지5단계를 통과한 뒤 명시 reload의 요청 예산 소진으로 실패했다.
허용256/시도281·예산 차단25개이며 다른 범위 차단0이었다. logout1·보호401·이번 실행의
미철회 가능성False와 정확 정리를 확인했지만 PinVi는 미도달이다. 원 두 실패·두 번째 실행의
미확정 표기는 그대로 보존한다. 이 세 번째 실패를 공개13flow 완료로 세지 않는다.
세 번째 원 실패 SHA-256은
2ecff5b22193e3d0bdb360e5e067692e76c890f0e5af1f789b592aba767fd244다.


첫 단계 commit readback SHA-256은
`63f51b27f44da72ce3301746d3676a7676efb36831f8faa03b1c892510d51ee9`다.

선별 증거 SHA-256: 최종 pair 수용
`a75474bd6185d8e83062e5b7768af198eb48f4b2286f55a129c5ffae9e61cb65`,
독립 검산
`0300cfd1c56b0811fee2e88a8b973b3c027da43b7fd2b025cb73eb00940e0d2b`.

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


## read/create 자격 중복 P2 정정

8555 source의 독립 리뷰에서 새 read digest와 admin_feature_create_token_sha256을
같게 설정해도 수용하는 누락을 확인했다. 원 source와 초기 검증 결과는 HOLD 이력으로
보존한다. 수동 생성 자격의 정본 검사 함수에 새 read digest 비교 한 항목만 추가했다.
이 함수는 정상 Settings 생성과 create_app의 런타임 재검증에서 함께 사용된다.

설정 입력 순서 두 가지·생성 flag true/false·검증을 우회한 model_copy의 런타임 확인은
수정 전6 FAIL이었다. 별도 정상 BFF를 가진 read token의 실제 생성 요청 거부는 수정
전에도 PASS였으며 그대로 유지한다. 수정 뒤 새7개를 포함한 read/settings/auth 관련
227 PASS/27.90초를 확인했다. 기존 admin body·권한·DTO와 OpenAPI bytes는 유지한다.
이 정정의 독립 두 리뷰·새 CI·운영 provision과 pair/UI 인수는 별도다.


## 동결 소비 계약과 CI 원 실패 정산

488d의 Python3.11/3.12/3.13 CI는 각각 3826 PASS/7 SKIP/3 FAIL이었다.
실패 세 개는 정본 OpenAPI를 갱신한 뒤 남은 vnext baseline·consumer rollout·현재
pending receipt의 구 service hash였다. 원 로그를 보존하고 openapi-diff의
admin/service baseline·새 GET2의 applied 항목 및 counts, pending receipt의 Map 대상
hash와 변경 이유만 정렬했다. user bytes·기존 목표 계약·과거 PinVi vendor 필드와
detached candidate 증거는 유지한다. 두 receipt는 여전히 pending이며 새 실제
수용을 선언하지 않는다. 해당 artifact의 두 byte-pin은 실제 계산값으로 갱신했다.
제품/API/DTO/권한·OpenAPI 변경 없이 동결 계약 모듈 전체18 PASS/1.31초다.
새 정확 CI와 이 metadata delta의 독립 리뷰는 별도로 확인한다.
