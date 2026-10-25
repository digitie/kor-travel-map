# snapshot 후보의 추적 잠금 fixture 정합

## 원 실패

후보 7f40e95의 전체 PostGIS 검사는 glibc에서 118실패·1768통과·23skip·30error,
alpine에서 118실패·1762통과·29skip·30error였다. 두 lane의 실패·오류 148개
node ID는 같았다. 이 중 배치·취소 테스트의 finally가 canonical tracking 행을
잠금 없이 지우다 23514로 중단되어, 뒤의 목록 검사에 committed 행이 남았다.
이 문서는 전체 실패가 fixture 때문이라고 주장하지 않는다. 공유 scalar projector의
별도 제품 수정과 나머지 전체 CI 검증은 계속 필요하다.

## 수정

관리용 cleanup transaction은 첫 tracking DML 전에 기존
`lock_provider_feature_finalization`으로 P EX→L을 잡는다. projection 테스트가 직접
만드는 provider root·membership fixture도 같은 규약을 지킨다. 4개 테스트 파일에
13줄을 더했으며 제품 SQL·guard·권한·기대 assert·검사 개수는 바꾸지 않았다.

## 실제 검증

75fda905d016a1d50c42b90693623d60371b29fa에서 배치·취소 phase2·취소 repository·
pipeline projection의 100개를 실제 glibc PostGIS에 실행해 33.18초에 전부 통과했다.
오류·실패·skip은 0이다. 테스트 DB는 schema430이며 2CPU·1536MiB·PID256,
pytest150초·부모160초·정리15초 상한 안에서 실행했다. 소스2512개·SDK53개의
전후 해시와 실제 import16개를 대조했다. 종료 뒤 정확한 CID와 임시 volume 1개의
부재를 확인했다. 운영 DB·이미지·스케줄은 변경하지 않았다.

원 실패와 중간 결과도 남겼다. 첫 배치15개는 통과했고, 나머지85개 중84통과·1실패는
직접 만든 root fixture의 누락 prefix였다. 그 한 곳을 추가한 뒤 위100개가 통과했다.
이 결과를 전체 CI 또는 실제 서로 다른 데이터셋 두 worker 동시 쓰기의 증거로
간주하지 않는다. 관련 원 로그·XML·소스/자원 원장은 배포 감사 기록에 보존했다.
