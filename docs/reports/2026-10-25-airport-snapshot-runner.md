# Airport 예약 asset의 SDK0 배선

## 첫 작은 checkpoint

Root 수용 native apply078ba765와 gateway60565·관측7410·후처리6304를 포함한
부모ab10989 위에 client 전용 TX 파일과 순수 시험을 추가했다. 현재 source는
복구 read/register/claim/seal의 작은 I/O 경계만 구현한다. 실제 Airport entry,
plan/apply/postprocess 연결은 아직 없으며 수집 경로를 바꾸거나 활성화하지 않는다.

모든 새 함수는 원 unbound client만 받는다. queue executor에 결합된 client는
session을 열기 전에 거부한다. client가 READ COMMITTED TX의 시작·commit·rollback을
소유하고 Dagster/infra가 commit하지 않는다. 전체30초, statement30초/lock1초를
상한으로 두며 기존 더 짧은 서버 설정을 보존한다. lease는300초 한 값이다.
RR read-only 준비용 내부 경계는 statement3초를 사용한다.

runtime pins가 없는 경우에도 먼저 canonical member SD에서 실제 부재를 확인한다.
등록 존재/비정상 반환은 오류이며 legacy 적재로 바꾸지 않는다. 정상 pins의 읽기는
기존 gateway를 재사용하여 원 artifact/context/result와 정확한 상태를 한 번 읽는다.
등록/claim/seal은 기존 typed SD를 그대로 호출한다. duplicate 등록·lease 시각을
새 권위로 승격하지 않는다. commit 응답 유실·DB 오류·취소는 그대로 전파하며
내부 자동 재시도나 candidate 결과 반환은 없다.

독립 순수16개가5.53초에 통과했고 Ruff2파일/strict mypy1파일을 통과했다.
실제 Task.cancel, commit 응답 오류, 각 단계 오류, bound client의 SQL0,
명시 runtime 부재의 등록 존재/부재를 대조했다. DB와 session은 대역이며
실제 rollback/서버 lock 해제·PG/권한 수용은 아니다.

## 런타임 pin과 다음 배선

기존 Docker build는 `KOR_TRAVEL_MAP_GIT_COMMIT`을 OCI revision과
`KOR_TRAVEL_MAP_IMAGE_REVISION`으로 공급한다. 현재 WT HEAD를 런타임에서 읽는
fallback은 두지 않는다. Python `uv.lock`이나 SDK inventory runtime 정본 파일은
현재 없고 provider surface manifest는 실제 installed inventory가 아니다.
Root가 실제 image revision/installed dependency·source inventory receipt를 검증해
명시 typed runtime으로 공급하는 경계를 맡는다. 누락된 hash를 상수로 대신하지 않는다.
새 등록 opt-in은 기본 OFF이며 기존 등록의 SDK0 복구 판단과 별개다.

첫 구현은 실제 tracked scheduled Airport만 대상으로 한다. 예약 run의 canonical
root/child/member는 guard의 실제 ensure mutation에서 고정한다. Airport run 첫
분기에서 SDK generator 소비보다 먼저 읽고, 미등록만 한 번 bounded EOF를 수집한다.
등록 전 미지원은 같은 입력으로 기존 EX를 사용한다. 등록 뒤에는 implicit EX/refetch가
없다. 실제 Root backend와 plan/apply/후처리/봉인 source 합성 후 독립 검토가 필요하다.

queue direct context에는 D root/child/member·run/retry guard가 없고 executor가
request/job을 잠근 외부 TX에 client를 결합한다. 첫 scope에서는 queue를 legacy EX로
유지하며 이를 SH 수용으로 세지 않는다. typed atomic seal commit 후 예약 wrapper는
기존 fresh member done→noop을 사용하므로 별도 완료 bool/외부 DTO를 추가하지 않는다.

신규 파일과 기존 Airport entry의 signature 불변 범위여서 Codegraph signature
영향도 평가 예외에 해당한다. 기존 converter/DTO/shared client/schema는 수정하지 않는다.
공유 journal/resume·설정·build·whole430 wrapper는 Root 소유다. 별도 PR·운영 변경은 없다.
실제 PG/전체430 설치·ACL·unknown commit 재개·원 run worker 종료·collector 배선/CI 및
운영 동시 쓰기 수용은 모두 미완이다.
