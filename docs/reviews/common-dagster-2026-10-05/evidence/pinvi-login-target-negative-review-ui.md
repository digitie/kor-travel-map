# 실제 PinVi 로그인 UI 실패의 독립 읽기 전용 진단
실행 ID: J-PINVI-OPERATING-LOGIN-20261006-B.
결론: **운영 UI gate 실패 확인, 원인 분류는 route/proxy target 방향 OPEN**.
제품 113파일 FULL SOURCE PASS는 변경하지 않는다. 로그인 성공 또는 전체 live UI PASS를 주장하지 않는다.

검토 소스: PinVi 0058369c778f8c3357ee393e12e3447d7975cc1f의 AdminLoginPage 및 ignored 운영 UI MJS SHA256 7e4b9d49ac8739787f267fad16b53b02cca87930289823a8550f12c4aa554f78, 실패 locator 33행.

## 직접 관찰
private runtime.env의 PINVI_UI_URL을 메모리에서 읽고 공개 경로 /admin/login만 GET했다. 응답은 HTTP404였다.
올바른 고정 Playwright 이미지의 새 자체 Chromium context에서 같은 경로를 조회했다. 계정·비밀번호 입력은 하지 않았다.

- document HTTP404, 최종 pathname은 /admin/login 그대로였다.
- 15초 관찰 후 login-password slot/input/form/admin-login testid 모두 0.
- DOM의 Next404 문구 존재, Application error 문구 없음.
- console error 분류는 HTTP404 한 건, pageerror 0, requestfailed 3.
- 추가 public /admin·/login은404, /는200이었다. 원문 HTML은 출력하지 않았다.
- read-only PinVi web route manifest에는 /(admin)/admin/login/page를 포함한 65개 route가 있고 config basePath는 빈 값이었다. 이 조회는 부모의 중복 회피 요청이 도착하기 전에 수행했다. 직접 내부 서버 GET은 수행하지 않았다.
- runtime.env의 PinVi UI와 Map UI는 값·origin·host 모두 서로 다르며 두 URL 모두 basepath가 없었다. 실제 값은 출력/보고서 저장하지 않았다.

따라서 단순 locator의 5초 timeout을 늘려 고칠 실패라는 근거는 없다. 배포된 Next route는 manifest에 존재하지만 공개 target은404를 반환한다. 외부 라우팅 대상·proxy 매핑과 직접 web 응답을 구분해야 하며, 현재 관찰만으로 제품 빌드/라우팅 설정 중 단일 원인을 확정하지 않는다.

## 수행 및 격리
허가된 read-only HTTP, Docker exec의 Node fs route metadata 조회와 새 own --rm diagnostic container만 사용했다. 고정 Playwright image digest 9bd26ad900bb5e0f4dee75839e957a89ae89c2b7ab1e76050e559790e946b948, host node_modules는 read-only mount, tmpfs 및 read-only root를 사용했다. runtime.env를 diagnostic container에 mount하지 않고 URL 하나만 메모리 전달했다. 기존 테스트 container/evidence 및 운영 계정/DB를 변경하지 않았다.

최초 보조 browser 호출은 stdin 연결이 없어 실행 자료가 없었다. -i 연결을 보강한 별도 호출에서 위 실제 DOM 관찰을 얻었다. 이에 대해 최초 exit0을 성공 증거로 사용하지 않았다.

NOT_RUN: 로그인 POST, 계정 입력/쓰기, 전체 suite, source 수정, 서비스 재구축/재시작, 운영 DB·D1/D2 mutation. 직접 internal GET과 trusted deployment/proxy mapping 원인 확정은 아직 미수행이다. 다른 리뷰어 원문은 읽지 않았다.

민감한 URL·host·환경값·로그인 값·HTML/로그 원문을 이 보고서에 포함하지 않았다.

검토/보존 시각(UTC): 2026-10-05T19:27:19.205641+00:00
