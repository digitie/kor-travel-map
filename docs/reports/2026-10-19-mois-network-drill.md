# MOIS Geo 연결 실패의 조기 전파와 격리 수용

500행 chunk의 선조회가 typed GeoRequestError를 삼키면 동시성2·connect4초에서
약1000초 동안 모든 행을 기다린 뒤 변환이 다시 실패한다. retry1회+300초를 포함한
추정2308초는 run budget14400초의10%(1440초)를 넘을 수 있다. 추정은 운영 실측이 아니다.

500행 typed 오류 fixture는 기존 코드에서 실패를 전파하지 않아 RED였다. typed I/O 오류는
대기행 시작을 중단하고 실행중 요청을 취소·회수해 바로 전파하도록 보강한다. 정상 후보
없음은 오류가 아니며 기존 빈 답 판정과 일반 예외의 변환 재시도는 유지한다.
DB commit·원천·chunk500·동시성2·native retry1+300초는 변경하지 않는다.

codegraph 인덱스·callers 조회를 실행했으나 Python caller가0으로 나와 rg로 보완했다.
production 사용처는 MOIS chunked loader1개다. common에 대응하는 async 취소 helper가
없어 표준 asyncio로 소유 task를 회수한다. 관련 REST adapter/prefetch/MOIS 회귀173개 PASS(4.70초).
400/404/429/500/503/read timeout은 typed 실패로 전파하고 HTTP200 NOT_FOUND는
정상 빈 후보로 캐시함을 확인했다. 부모 취소 시 sibling drain과 일반 예외 기존 경로도
유지한다. namespace 동일성/소유 UID mapping 반례4개 PASS(0.09초).

실제 owned namespace SYN DROP과 native retry를 포함한500행 합성 수용 PASS.
기본 retry1회+300초를 실제 기다린 Dagster FAILURE까지308.365초로1440초 이내였다.
DROP16패킷, 실패 chunk commit0, 회복 commit1/고유500행, 동일 원천 재수집 HTTP0이다.
[정산 JSON](2026-10-19-mois-network-drill.json)에 raw 로그 SHA와 제품 SHA를 남겼다.

실제 HTTP와 native Dagster retry/최종상태, 실제 MOIS loader/변환기를 썼다. 입력은
고정 합성500행이며 저장소는 기존 transaction-semantics DB fixture이다. PostgreSQL 또는
전체 production MOIS job/모든 service의 벽시계 검증이라고 주장하지 않는다.
최초 smoke는 harness가 SecretStr 대신 문자열을 전달해 provider 호출 전에 실패했고,
타입을 수정한 smoke는4.025초에 실패 전파·복구 PASS였다. 제품 회귀로 세지 않는다.
실행 중 적용한 후속 harness 편집은 Ruff의 import/서식 및 with 병합이고 제품 SHA는
동일하다. 현재 서식본은 namespace guard4개와 lint를 다시 확인했다.

재현: Dagster와 Map 의존성이 있는 Linux 비root 환경에서
`python scripts/acceptance/mois_network_drill.py` (약5분).
`--smoke`는 native retry 없이 연결 실패/복구만 확인한다. iproute2/iptables/unshare가
필요하며 부모와 다른 user/net namespace 및 비root UID mapping을 먼저 검증한다.
host namespace·host iptables는 변경하지 않고 loopback 합성 서버의 SYN만 차단한다.
provider 전체 fetch·운영 namespace·실호스트 전원 차단은 실행하지 않는다.
