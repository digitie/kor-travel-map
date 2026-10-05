# 실제 UI canonical retry1 영수증·8개 화면의 독립 리뷰
실행 ID: J-UI-TICKS-RETRY1-ACTUAL-20261006-B.
판정: **PASS — 실제 4case 영수증 연결 및 8PNG visual/privacy 검토**.
실제 UI 테스트 실행자는 root다. 본인은 영수증·이미지를 읽고 실제 Docker metadata를 read-only 대조했으며 4case 테스트를 직접 재실행하지 않았다.

## 고정 연결
- 실제 receipt map-pinvi-ui-operating-ticks-retry1-evidence.json SHA256: 38db579f14def71172965a3a7e8ba8e0f3469469d815392fcf814692f330a9c8
- launch identity SHA256: e79b516cc5c53a3a22e1e5ee2a081eaf216fce29d9f386a7d46a671948b3191f
- runtime ticks attestation SHA256: 8d998cecf435d270b704b5bb20912004d3143ce89b62a0dbe3710cefd737db99
- 실제/current mounted MJS SHA256: 7e4b9d49ac8739787f267fad16b53b02cca87930289823a8550f12c4aa554f78
- Map source: 1a3c4673790f51daa1a2f5ccf803d4e31673bad6
- PinVi source: 0058369c778f8c3357ee393e12e3447d7975cc1f
- actual container ID: 18b32f547ce1652ebc92ed923fc3dbdad229141d352653a08eb2a46d9d366b23
- browser image: sha256:9bd26ad900bb5e0f4dee75839e957a89ae89c2b7ab1e76050e559790e946b948
- fresh run nonce: b579716c-80e4-4b26-843d-ad47d62bd74c

actual read-only docker inspect에서 위 ID/image와 exited/Running false/ExitCode0/OOMKilled false 및 launch 환경의 run nonce·attestation digest 일치를 확인했다. 실제 mount의 live.mjs도 동일 SHA다.
컨테이너 UTC 구간은 2026-10-05T19:40:14.053549488Z~19:40:53.605171376Z다. receipt는 그 안의 시작/종료와 같은 신규 run을 기록한다. 이전 failed namespace 영수증을 사용하지 않는다.

## 실제 receipt 수용 범위
Chromium/Firefox × Map/PinVi의 정확한 4조합을 확인했다.
각 case의 session cookie/Set-Cookie/Secure+HttpOnly/소유 repository/session clear boolean은 실제 true이고 로그인 status200이다. Map UI logout200, PinVi API test-session cleanup204로 구분돼 있다. PinVi 관리자 셸의 UI logout button을 검증했다고 주장하지 않는다.
Map 39jobs/PinVi 9jobs와 최근30runs, selected identity, browser summary abort 후 last-good 및 recovery, mobile width/document390, keyboard focus-arrow scroll을 기록한다. 공용 daemon/worker/service 중단 검증은 이 receipt의 범위가 아니다.

## 8PNG 직접 검토
map-pinvi-operating-ticks-retry1-screenshots의 아래 파일을 모두 view_image로 직접 읽었다. 일부 긴 PNG는 도구가 높이6000으로 표시 축소했으며 원본 bytes/SHA 비교는 별도로 수행했다.

| 파일 | SHA256 |
| --- | --- |
| map-chromium-desktop.png | 16e1874b5fc4e9266bb67a309adcd72cce1e926330cef81f379454a103b229e9 |
| map-chromium-mobile.png | d7c8d31235bc90bfa773e5583fb91999afc8522cdee66450abd227fd74e8b959 |
| map-firefox-desktop.png | a3578128b6a21dc9c8a37197c81914beacb6ef129e6dc479af837c009e81d3b1 |
| map-firefox-mobile.png | add38846d51578c3d0d2f9745a20427d78cbae8953d50b78d228879715f6dfce |
| pinvi-chromium-desktop.png | 86c8d17130c238b6605650d27355ea717cd028d145b85906c52435321b3dd6d5 |
| pinvi-chromium-mobile.png | 91afd1d6442d6d9cecbdbc9770bdebd790bf6278ed4583f4acc8bce955a54f80 |
| pinvi-firefox-desktop.png | f0d7d11299a80da0613624b8906e18d8f80d0deb1270d99a60694b474f5d899d |
| pinvi-firefox-mobile.png | c21f8fbb58f1dda3ef44eda7714f47083b8d014f36aaae2de9f32016e6970aa4 |

PNG signature·byte length·SHA가 receipt의 8capture 모두와 일치한다. summary 카드/검색/실행 목록/스케줄·센서 및 PinVi selected detail은 읽을 수 있다. 모바일 표의 좌우 열 일부가 viewport 밖인 화면은 keyboard ArrowRight 후 내부 가로 스크롤 상태다. page overflow의 근거로 취급하지 않으며 receipt의 document390 확인과 함께 수용한다.
Map의 selected detail은 캡처 시 닫힌 상태이고 실제 상세 선택 assertion은 receipt가 제공한다. 화면만으로 미표시 상세를 검증했다고 주장하지 않는다.

privacy: 패널 crop에 계정 이름/이메일/비밀번호/token/cookie/실제 URL·host·주소·raw 오류 stack 노출을 발견하지 않았다. 표시된 job/location 이름과 run UUID·실행 시각은 운영 identity 증거이며 개인 계정 데이터가 아니다. 브라우저 chrome와 로그인 입력 값은 캡처에 없다. 새로운 visual/privacy 차단 finding은 없다.

## EXECUTED / NOT_RUN
EXECUTED: local receipt/identity/attestation/source digest 및 strict case fields, 8PNG signature/length/hash 비교, 8파일 direct view, 허가된 actual container metadata와 current mounted source의 read-only 확인.
NOT_RUN: 본인의 4case 인증/로그아웃 반복, provider/domain write, 서비스/DB 변경, 새 배포/재구축/native/D1/D2. root actual 결과와 본인 검토를 구분한다. peer 원문은 읽지 않았고 제품·증거·이미지 bytes 또는 이전 원문을 수정하지 않았다.

초기 404 operating negative/diagnosis와 하니스 BLOCK/수정 PASS 원문은 모두 불변이다. 이번 actual receipt는 canonical target 수정 뒤의 별도 fresh run 성공이며 이전 실패를 소급 성공으로 바꾸지 않는다.

검토/보존 시각(UTC): 2026-10-05T19:44:53.492759+00:00
