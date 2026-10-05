# PinVi 공개 로그인 target의 검증된 원인과 최소 수정
실행 ID: J-PINVI-CANONICAL-TARGET-20261006-B.
진단 결론: **하니스 target 불일치 확인**. 올바른 canonical target의 무자격 증명 login form 확인은 PASS다.
제품 113파일 FULL SOURCE PASS는 불변이며 전체 실제 로그인/live UI gate는 아직 PASS가 아니다.

## 읽은 고정 소스
ignored map-pinvi-operating-ui-prepare.py SHA256 2be57695d72176371abc07b0618f7db52132b288c4f1c1454e8c434ee825d72d, 18행 PINVI_UI_URL literal.
PinVi 제품 0058369c778f8c3357ee393e12e3447d7975cc1f, 운영 MJS 7e4b9d49ac8739787f267fad16b53b02cca87930289823a8550f12c4aa554f78.

## 실제 read-only 확인
설치된 trusted Manager .env에서 KTDM_PROD_URL_PINVI와 PINVI_WEB_BASE_URL을 메모리로 읽었다.
두 canonical 값은 서로 같고 현재 하니스 runtime.env의 PINVI_UI_URL과 다르다.
각 canonical base + /admin/login GET은 HTTP200이었다. 현재 literal target은 앞선 독립 진단에서 HTTP404였다.

올바른 고정 Playwright 이미지의 별도 자체 Chromium context에 KTDM_PROD_URL_PINVI만 전달하고 /admin/login을 조회했다.
- document HTTP200, 최종 pathname /admin/login.
- DOMContentLoaded 이후 관찰 시작부터 1080ms에 login-password가 visible이었다.
- password slot1/input2/form1/admin-login testid1.
- 404 및 Application error DOM은 false.
- console error/pageerror/requestfailed 모두0.

계정·비밀번호 입력 또는 로그인 POST는 하지 않았다. 따라서 위 결과는 폼·target 확인이며 실제 인증 성공이나 전체 4case UI PASS가 아니다.

## Concrete next step
J-HARNESS-TARGET-P2-01 / P2 OPEN (검토한 prepare bytes 기준): prepare.py:18의 PINVI_UI_URL literal이 설치된 canonical deployment 설정과 달라 실제 올바른 PinVi 앱 대신404 target을 검사한다.
최소 수정은 PINVI_UI_URL을 이미 읽은 manager['KTDM_PROD_URL_PINVI']로 지정하고 manager['PINVI_WEB_BASE_URL']과 일치하는지 fail-closed assert하는 것이다. 이번 관찰로 proxy 설정이나 제품을 바꿔야 한다는 근거는 없다. locator timeout 증가도 필요 원인으로 확인되지 않았다.
수정된 별도 하니스의 fresh identity/기존 실패 원문 보존 후 실제 전체 UI를 재실행해야 한다.

## 격리 및 범위
설치 .env와 runtime.env의 실제 URL/host/credential 값은 출력하거나 원문에 남기지 않았다. configured canonical endpoint만 조회했고 주소/포트를 추측하거나 스캔하지 않았다.
own --rm diagnostic container/read-only node_modules mount/read-only root/tmpfs만 사용했다. runtime.env 전체를 mount하지 않았고 URL 하나만 전달했다. 기존 test container/evidence, 제품, proxy, 서비스, DB는 수정하지 않았다.
직접 internal GET은 수행하지 않았고 다른 리뷰어 원문도 읽지 않았다. 사전 HTTP/DOM 진단 원문은 불변 보존했다.

NOT_RUN: 로그인 POST·계정 쓰기·전체 suite·배포/재시작·native/D1/D2 mutation 및 corrected actual full UI.

검토/보존 시각(UTC): 2026-10-05T19:34:23.959707+00:00
