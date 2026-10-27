# 두 독립 OS worker의 snapshot 원자성 시험

## 범위와 상태

2026-10-27, 기준 main `0324cab3`에서 Airport1/Rest2의 저장된 관측을 적용하는
실제 `multiprocessing` spawn worker 2개의 제한 시험을 추가한다. 생산 Python/SQL,
스키마432, 운영 설정·새 profile OFF, 30초 원자 구간·reader3초·lock1초를 바꾸지 않는다.
상위 **T-CWRITE-01–09는 모두 미완료**다. 정확 시험 source `6307ec63`의 두 리뷰와 제한 실제 PG는 통과했다. 상위 Common 변경을
합성한 `e23c277d`도 두 리뷰와 CI10개를 통과해 PR #1421의 main `0d60cd0b`로 병합됐다.

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
- 정확 `6307ec63`은 두 독립 source 리뷰와 같은 상한의 실제 owned PG 양방향2개를 통과했다.
  이 단계에서는 최종 CI를 기다렸다. 아래 최종 CI·병합 기록이 현재 상태다. 운영 전체 동시 쓰기 완료나 CPU/RSS 효과로 확대하지 않는다.

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
수정본 `6307ec63`은 두 리뷰와 같은 상한 실제 PG를 통과했다. 이 단계에서는 최종 CI를 기다렸다. 아래 최종 CI·병합 기록이 현재 상태다.


## 정확6307의 실제 제한 수용

owned r3는 두 case 모두 PASS, skip0(27.88초)다. 각 case는 서로 다른 spawn PID2개의
PID/starttick 쌍, 독립 pool1·PG backend/XID, 미commit source lifetime overlap, 정확
`transactionid` topic blocker, 두 원 commit ACK, 후처리의 원 물리 connection/PID/XID,
commit 후 marker NULL, 원 counter/receipt와 이후 별도seal을 확인했다. starttick 값 자체는
동시에 생성된 두 process에서 같을 수 있으며 서로 다른 PID와 함께 식별한다.

정확 source2580개와 선택한 project import56개·SDK source53개를 검산했고 SDK53은 시험 뒤에도
동일했다. schema432·정본 runtime role·loopback만 공개된 owned PG와 기존 자원/시간 상한을
유지했다. 정확 CID와 anonymous volume1개를 회수했고 최종 scalar label0/cleanup PASS다.
별도 감사 원장 `map-os-worker-pair-owned-r3-3a66f6f5b9504141b63a22766e783a87/result.json`의
SHA256은 `e08a071c95abf015c29d54b42f36843664188e67dbe5d33391cb78b78bede12a`다.

원 r1 SDK import 실패(PG0)와 r2 marker 기대값 오류의2실패는 그대로 보존한다. 원 초안
`4b742950` CI의 Python3종은 모두 task ledger 본문의300자 상한 위반으로 실패했다.
`T-CWRITE-04` 본문은 중복 수용 설명 대신 이 원장의 link를 남겨 상한 안으로 단축한다.
상한·테스트를 바꾸지 않는다. 이 수정은 문서뿐이며 실제 PG를 통과한6307의 시험 source는
변하지 않는다. 최종 CI 통과 전에는 머지하지 않는다.


## 원 head의 CI 완료와 상위 main 제품 변경 합성

원 head `3e962183`은 Python3.11/3.12/3.13의 unit·lint·API·Dagster와 PostGIS alpine/glibc를
포함한 CI10개를 모두 통과했다. 그동안 상위 main에는 Common 반영 PR #1420이
`980e0458`로 병합됐다. 해당 정확 head `dedcbe70`도 CI10개 성공을 직접 확인했다.

상위 변경은 문서만이 아니다. API/Dagster의 Common Python pin은 `e746e4b8`에서
`aa232ad5`로 올랐다. Python source19개 중18개 mode/blob은 같고 `daemon_pool.py`의
workspace 갱신 주기 opt-in만 추가됐다. Map entrypoint는 이 daemon entry를 사용하지 않지만,
의존성이 바뀌었으므로 합성본 검토·필요 focused PG·정확 새 CI로 검증한다.

UI는 dev.7에서 dev.9의 정규 tgz로 바뀐다. SHA256은
`b738d8824e36eb6e58d8cc6b78af7dc31233b6763248d634286044def795b403`(27파일)이며
기존 Common 수용 산출물과 같다. MapWorkspace 등은 opt-in이고 Map은 채택하지 않는다.
로그인 hydration 전 native disabled 경계와 해당 Map 회귀18줄이 포함된다.
상위 PR의 공개 records에는 독립2리뷰 원장이 없으므로 그 완료를 추정하지 않고 새 합성본을
두 사람이 검토한다. 상위 작성자가 보고한 SSR13·Feature17은 이 작업자가 재실행한 결과가 아니다.

정상 main 병합의 journal/resume 충돌은 양쪽 최신 항목과 공통 이전 본문을 모두 보존한다.
같은 task 단락 충돌은 기존 제한 수용과 새 worker 원장을 함께 가리키는203자 설명으로 해결한다.
시험 source6307은 그대로이며 생산 Python/SQL을 새로 수정하지 않는다. 합성본의 정확 CI와
focused 검증이 끝나기 전에는 PR을 머지하지 않는다. 이는 MD CI 면제 대상이 아니다.
PR #1420 자체는 이미지3개에 영향을 주고 아직 배포하지 않았다고 명시돼 있다. 시험/문서만의
추가 무배포 원칙과 그 상위 제품의 운영 미반영을 구분한다. 이 작업은 운영을 바꾸지 않았다.


## 최종 합성본의 CI·정상 병합 수용

PR #1421은 2026-10-27 06:44:24 UTC에 정상 병합됐다. 정확 검증 head는
`e23c277d0cfd31e1a58f7bc79779e473b289deda`, main merge는
`0d60cd0b5ae4e4d54e064a24fdbe3716214789ea`다. merge tree
`b49826cd96a2b027e1e79c502c85b5c701ad4a32`는 검증 head tree와 같고, 부모는
main `980e0458`과 검증 head다. 강제 병합·관리자 우회·브랜치 삭제는 하지 않았다.

최종 head의 CI10개는 모두 성공했다. Python3.11/3.12/3.13, fixture replay,
PostGIS glibc/alpine, lint, OpenAPI, frontend build, production Docker build를 확인했다.
workflow `40456454576`의 glibc는1934 PASS/23 skip(1344.03초), alpine은1928 PASS/29 skip
(1718.66초)다. 양쪽 API/Dagster editable 설치 로그의 Common VCS pin은 정확
`aa232ad5f255233184de80eceaab2e9b6ccb00c9`이며 전체 `pytest tests/integration -q`가
성공했다. skip 사유 전체에는 새 worker pair 파일이 없다. 기존 Geo live·선택 Heritage SDK·
이전 fence와 alpine collation 시험만 skip됐다. quiet 로그에 각 성공 node 이름이 출력된
것으로 주장하지 않으며, 정확 수집2개·필터 없는 전체 실행·skip 사유·정상 종료를 함께
검산해 새 두 case의 실행을 수용한다.

외부 접속을 모두 거부한 별도 import/collection 검산은 Common 실제6 module과 전체 source19개,
Map API/Dagster 실제 transitive49개가 정확 합성본과 같고 fixture 미해결0임을 확인했다.
이는 실제 PG 시험과 구분한다. 원6307의 owned PG2 PASS와 정확 새 의존성을 설치한 전체 CI를
함께 근거로 쓰며, 중복 local r4 PG는 실행하지 않았다. 기존 실패·cleanup 및 두 source/문서/
합성 리뷰 원장은 보존한다.

별도 감사 원장 `map1421-normal-main-merge-acceptance-r1.json` SHA256은
`0cf84da2baae6c39211890d63e88c0505661be87cc70afd311061cc91d46d063`이다.
양 PostGIS 로그 검산 원장 `map1421-e23-actual-PostGIS-log-proof-r1.json`은
`c87e3f123e9dfd83ae694b61ed285394a9aab3480e0a1bf735081016c8b7ca98`,
전체 skip 사유 원장 `map1421-e23-actual-PostGIS-skip-reasons-r1.json`은
`bc66f58c81fb0fe48bff5fca48e71e066abc2c8236f2393d833c5e86371e2999`다.

이 정산은 문서만 바꾸며 제품·시험·설정은 변경하지 않는다. PR #1421 자체는 시험/문서 추가라
API/UI를 새로 배포하지 않았다. 상위 #1420 제품의 운영 반영은 별도 공식 배포·공개 UI 수용
작업이며 이 원장은 그 완료를 뜻하지 않는다. 운영 CPU/RSS 개선은 미측정이고
T-CWRITE-01–09는 모두 미완료다. shared Feature 경합·저장 artifact 재계획의 후속 PR #1422도
이 제한 OS worker proof와 구분하며, 이 정산을 작성한 시점에는 아직 머지 전이다.
