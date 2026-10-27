# 두 독립 OS worker의 snapshot 원자성 시험

## 범위와 상태

2026-10-27, 기준 main `0324cab3`에서 Airport1/Rest2의 저장된 관측을 적용하는
실제 `multiprocessing` spawn worker 2개의 제한 시험을 추가한다. 생산 Python/SQL,
스키마432, 운영 설정·새 profile OFF, 30초 원자 구간·reader3초·lock1초를 바꾸지 않는다.
상위 **T-CWRITE-01–09는 모두 미완료**다. 이 문서는 구현·검증 중 원장이다.

기존 동일 프로세스의 두 PG session 시험을 대체하지 않는다. 기존 등록·claim·정적
원 입력/후처리 helper를 재사용하고, 부모의 engine/client를 제거한 불변 case와 자체
격리 fixture DSN을 256KiB 상한의 private Pipe로만 보낸다. child마다 새 pool1을 만들며
DSN·원문은 argv/env/log로 내보내지 않는다. 외부 SDK·Geo·운영 접속은 수행하지 않는다.

## 검증할 동작

- 실제 spawn PID·부모 PID·Linux starttick을 검산하고, 별도 backend start와 XID를 확인한다.
- leader는 실제 적용·필수 후처리 뒤 미commit 상태를 hold한다. 이 상태에서 follower의
  실제 source apply가 반환해야 한다. leader를 Airport/Rest 양 방향으로 검사한다.
- follower가 정본 begin-postprocess SQL에서 leader XID를 기다리고, 정확 blocker가
  leader 하나이며 leader가 global topic relation을 잠근 사실을 확인한 뒤 hold를 해제한다.
- 두 정본 coordinator의 commit ACK 뒤 원 결과·receipt·counter 증가를 대조한다.
  source의 public AsyncSession과 SQLAlchemy connection event로 실제 후처리 SQL 전체가
  같은 물리 connection에 있고 그 전후 PID/XID가 같음을 확인한다. commit 후 apply TX는
  원 worker XID이며 임시 postprocess marker는 NULL이어야 한다. child seal은 이후 별도 TX다.
- 시작 직후 identity/pidfd 저장 실패도 회수 경로에 포함한다. 자기 PID/starttick 및 pidfd만
  사용하며, 전체 자식2 회수에 공유15초를 둔다. 한 자원 정리 오류가 다른 자식·Pipe·FD
  정리를 건너뛰지 않고 원 primary 예외를 보존한다. foreign PID에는 신호를 보내지 않는다.

프로세스 주소공간/CPU 개별 제한은 합산 메모리·호스트 CPU 제한이 아니다. 기존 owned PG의
CPU2·RAM1536MiB·swap 동일·PID256, 외부 phase150초/parent160초/cleanup15초 상한을
늘리지 않는다. 부모와 두 child의 합산 CPU/RSS 및 운영·ARM 비용 감소는 아직 측정하지 않았다.

## 현재 검증 결과

- 원 초안 `e4f501ae`의 통합2 node collection은 21.77초에 통과했지만 실제 fixture
  closure를 확인하지 못했다. 두 번째 독립 리뷰가 `rest_catalog` 누락 P1을 발견했다.
  의도한 다른 이름 import가 Ruff 자동 수정으로 제거된 것이며, 같은 이름 재export로
  수정한다. 원 collection 결과를 실제 fixture 설정·통합 성공으로 해석하지 않는다.
- IPC 상한·child 오류/잘못된 profile·foreign identity 거부·시작 중간 실패 회수·개별 close
  오류의 순수 회귀6개: PASS, 6.68초. 외부 호출·Docker·PG 실행0.
- 신규 두 시험 파일 Ruff: PASS.
- 수정 후 두 item의 fixture dependency closure 전체 미해결0·`rest_catalog` module fixture
  해결을 실제 pytest 수집 plugin으로 확인했다(2개, 6.52초). fixture setup/DB 호출0이다.
- `mypy --strict src`: 196 source files PASS, import-linter: 4 kept/0 broken.
- CI 범위 Ruff check(src/tests/API/Dagster 전체): PASS. 신규2파일 format check: PASS.
- `ruff check .` 전체는 기존 main의 무관한 문서 handoff script와 journal 검사 script에서
  7개 오류가 나왔다. 전체 `ruff format --check src tests`는 기존416파일 drift로 실패했다.
  무관한 기존 파일은 자동 수정하지 않았으며 새 파일의 통과와 구분한다.
- 두 독립 적대 리뷰, 같은 상한의 실제 owned PG, 전체 CI는 아직 대기다.
  이 결과를 실제 두 worker 성공이나 운영 동시 쓰기 완료로 해석하지 않는다.

## 후속과 제외

최종 source 두 리뷰 → 같은 상한의 단독 owned PG → 최종 CI 순으로 검증한다.
실제 Dagster worker 감독·SIGKILL·wire 단절·shared Feature 양성 경합·지역 분할·전체 writer
확대·215개/실 upstream·운영 활성화·CPU/RSS 효과는 별도 수용 항목이다.
이 PR은 시험/문서만 추가하므로 API/UI/운영 배포 변경은 없다.

## 실제 시험에서 발견한 검증 계약 교정

첫 owned r1은 원 임시 SDK dependency 디렉터리 삭제로 fixture 전에 `tenacity` import가
실패했다(pytest exit3, PG생성0, cleanup PASS). SDK source53개는 원 `e1b346f7`에 고정해
복원했고, 정본 pyproject의 `tenacity>=8.2`·`lxml>=5.1` 두 누락 의존성만 private target에
`9.1.2`·`5.4.0`으로 복원했다. 공유 venv/global 패키지는 바꾸지 않았다. 같은 plugin의
실제 프로젝트56 module/SDK import·fixture closure2개는 socket connect 전체 거부 조건에서
통과했다. 이는 SDK 네트워크 호출이나 실제 수집을 의미하지 않는다.

owned r2의 실제 양방향 시험은 spawn/source overlap/topic blocker/두 commit ACK·topic counter까지
도달했지만, commit 후 임시 marker가 XID로 남아야 한다는 새 시험의 기대값 때문에 두 건 모두
실패했다(27.90초). schema432 정본 SQL `finish_provider_snapshot_postprocess`의236–238줄은
`postprocessed` 상태·원 receipt를 저장하면서 `postprocess_txid`와 intent marker를 NULL로 회수한다.
이것은 생산 코드의 실패가 아니다. 원 result/XML/log·정확 CID/volume 회수·cleanup PASS를 보존한다.

시험은 marker 기대값만 지우지 않고, 정본 public Session/connection event를 이용한 실제
후처리 SQL의 물리 connection 동등성·전후 backend PID/XID를 추가하고 commit 후 NULL 회수를
검증하도록 교정한다. 예산·생산 코드·SDK 가드·원 receipt·별도seal 검증은 유지한다.
수정본의 두 리뷰·같은 상한 실제 PG·최종 CI는 아직 대기다.
