# runtime attestation harness 보강 독립 원문

작성: 2026-10-06. 범위: ignored map-pinvi-runtime-attest.py 한 파일의 수정과 직접 검증.
제품 코드·운영 설정·DB 데이터는 수정하지 않았다. 이전 제품 FULL 원문과 판정은 그대로 보존하며, 이번 결과를 새 제품 FULL 검증이나 운영 성공으로 집계하지 않는다. peer 원문/스크래치는 열람하지 않았다.

## 고정 harness와 변경

직접 계산한 최종 harness SHA256:
74e89f7c79d5c410cc2d019b7df6c7be1398382f254b65800db36bab3f2a6d16
크기: 15,252 bytes.

설치된 manager의 정본 strict deploy-status reader를 사용한다. legacy v6 active_generation은 읽거나 승격하지 않는다. committed 상태, 고정 제품 revision, application schema heads, 6개 서비스의 committed image ID와 실제 container image·healthy·source revision label을 대조한다. source hash와 소비자별 실제 Common Git pin도 검증한다. 기대 pin은 고정 pyproject에서 직접 읽으며 Map 두 소비자는 a960, PinVi API는 1f8, PinVi ETL은 73e3이다.

source hash 조회의 importlib.util.find_spec를 부모 실행 없는 PathFinder path walk로 교체했다. 제품 namespace의 sys.modules 전후 검사도 추가했다. 실제 파일을 읽어 hash를 계산하며 부모·대상 제품 모듈을 실행하지 않는다.

실제 euid 0을 명시적으로 요구한다. lstat로 root 소유 0700 디렉터리와 0600 regular deploy 파일을 확인하고 symlink를 거부한다. 초기와 첫 read 후, 최종 bytes read 전후에 소유권·권한·type·inode identity를 다시 확인한다. deploy bytes와 container ID/image/healthy도 마지막에 재검증한다.

Dagster head는 legacy 필드나 선언에서 가져오지 않는다. 실제 shared metadata DB를 canonical DSN identity guard, READ ONLY transaction, statement timeout 4초·lock timeout 1초로 읽는다. public.alembic_version 단일 행의 실제 head가 기대값과 일치해야 한다. 실패 예외·stderr·DSN을 공개하지 않으며 실패 시 새 PASS receipt를 생성하지 않는다.

## 본인 직접 검증

Python/helper 및 remote/DB program compile을 통과했다.

최종 remote 로컬 mock 18개를 직접 수행했다. 정상 사례와 다음 반례의 기대 결과가 모두 일치했다: legacy source revision, committed image 누락, image ID 불일치, revision label 불일치, unhealthy, Common 설치 commit 불일치, DB head 불일치, deploy bytes 변경, container 교체, euid 1000, 최종 파일 권한/UID/symlink 변경, 최종 디렉터리 권한/UID/symlink 변경, 파일 inode 교체. 정본 후보/필수 image/root 조건이 실패한 사례는 container 조회 이전에 거부했다.

source 조회 fixture 5개를 직접 수행했다: namespace Map API, eager Dagster parent, editable app WORKDIR, editable pinvi WORKDIR, PEP660 plain-path .pth. 부모 및 대상 파일에 실행 시 예외를 발생시키는 내용을 넣고 실제 source hash 프로그램을 실행했다. 모든 경우 hash가 예상 bytes와 일치했고 제품 모듈 실행이 없었다. 임시 fixture는 본인 cache에 생성하고 해당 임시 범위만 정리했다.

별도 실제 읽기 전용 probe:
- 설치된 manager strict reader가 현재 old committed deploy 구조를 정상 파싱함을 확인했다. 현재 revision은 기대 새 pair와 달랐으며 root/0700/0600 metadata는 실제 확인했다.
- 기존 actual PinVi API는 WORKDIR /app, source /app/app/services/admin_etl.py, editable .pth의 plain path 1개/import hook 0개였다.
- 기존 actual PinVi ETL은 WORKDIR /opt/pinvi/apps/etl, source pinvi/etl/definitions.py, editable .pth의 plain path 1개/import hook 0개였다.
- 두 컨테이너에서 새 source_path 함수만 실행하여 제품 namespace import 0을 확인했다. 이는 old 이미지의 경로 지원 검증이며 새 후보 source 일치나 새 서비스 성공 증명이 아니다.
- 실제 dagster_shared DB의 readonly 조회에서 schema head 29b539ebc72a를 관측했고 transaction_read_only=on을 확인했다. 기대 head를 manifest에 만들어 넣지 않았다.

모든 실제 probe는 읽기 전용이었다. 주소·DSN·자격정보·private helper 내용은 이 원문에 포함하지 않는다.

## 판정과 미실행 경계

이번 harness 보강의 직접 targeted 검증은 PASS이다. 앞선 제품 FULL 판정은 변경하지 않는다.

새 6개 서비스 전체 성공 attestation은 실행하지 않았고 새 성공 receipt를 생성하지 않았다. 새 운영 rebuild와 live E2E도 본인 NOT_RUN이다. old PinVi source-path probe와 shared DB head 확인을 새 pair 성공으로 승격하지 않는다. CI/운영 빌드/peer 검증 수치는 본인 수행 결과에 합산하지 않는다.
