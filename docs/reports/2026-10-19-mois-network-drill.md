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
없어 표준 asyncio로 소유 task를 회수한다. 관련 prefetch/MOIS 회귀89개 PASS.

실제 owned namespace SYN DROP과 native retry를 포함한500행 합성 수용은 준비 중이다.
provider 전체 fetch·운영 namespace·실호스트 전원 차단은 실행하지 않는다.
