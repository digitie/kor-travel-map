# schema422 API 실제 기동·읽기 관측

2026-10-25. source `e5a31f1acabbe338fb4c3f3e07a83149bdeb3a2d`의 Git archive2370개 blob/실행 mode와 SDK 의존53개 파일을 확인한 별도 소유 lab에서 실행했다. 설치나 운영 변경 없이 정본 fresh300→422 migration·runtime reconcile을 거친 실제 uvicorn factory/lifespan/preflight를 사용했다. dependency override는 없다.

최종 검사1 PASS(19.481초, skip0)에서 service/service runtime, schema422, 공개 SD1/private5의 owner·EXEC, 실제 core/API6개 import와 고정 source bytes를 확인했다. HTTP 수용 요청은 health200, 무인증 admin403, 정본 proxy secret+actor와 trusted loopback peer의 admin200 세 개이며 준비용 health 성공 poll1개는 따로 기록했다. 소유 파일 fixture1개가 정확히 반환됐고 business 행 수/파일 hash·정책0은 변하지 않았다. HTTP 쓰기0이다.

API user transient unit의 1CPU·1536MiB·swap0·Tasks128·Runtime60초와 실제 cgroup/proc listener inode를 검사했다. PG는 2CPU·1536MiB(swap동일)·PID256이었다. 마지막에 정확 unit PID0, 정확 PG CID 및 익명 volume NotFound·UUID label0, lab/private config 삭제를 확인했다. foreign container의 선택 metadata는 전후 같았지만 관측은 비원자적이므로 모든 host 프로세스의 불변을 주장하지 않는다. 원 private 감사는0600으로 보존하며 전체 비밀 폐기를 주장하지 않는다.

앞선 세 실패도 원 기록을 유지했다.

- r1: PostgreSQL 내부 char가 bytes로 반환돼 STABLE 문자열 비교가 실패했다. catalog 관측 SELECT에 명시 text cast만 추가했고 API unit/HTTP 실행 전이었다.
- r2: clean pytest 환경에 user bus의 XDG_RUNTIME_DIR가 없어 systemctl 조회가 실패했다. 현재 UID 소유 directory/socket 검증 뒤 해당 경로 하나만 전달했고 API unit/HTTP 실행 전이었다.
- r3: 실제 API 기동은 통과했으나 테스트의 관리자 actor header가 누락돼 정상403을 받았다. 제품 인증을 완화하지 않고 실제 BFF와 같은 필수 header를 요청에 추가했다. 이것이 첫 actual API/HTTP 실행이며 최종 PASS로 재해석하지 않는다.

최종 원장 `map422-api-startup-smoke-final-acceptance.json` SHA256 `0a050258a1d1e5bde349f550b463f4b5423e8888fa3f8e631a2ca1de7fba8697`, raw 결과 SHA256 `8b7f2fceb3a5bbd8aa009d5dc95383dcaba6b189ade2a610b5fb0aa92b51c294`에9개 증거와 실패 세대별 hash를 보존했다. 두 독립 소스 리뷰와 별도 사실 대조를 거쳤다.

API/UI package·router·DTO·client·lock·compose/env 예시의 제품 tree는 기존19UI 수용 source와 같아 해당 회귀 근거를 별도로 이어받았다. 이번 실행을 새19UI·BFF cookie/login·지도 canvas/tile 또는 reader의 실제 UI caller 검사로 세지 않는다. 외부 HTTP를 요청하지 않았지만 host 전체 네트워크 격리 보장은 아니다. SH collector·worker 복구·운영 배포 수용과도 구분한다.
