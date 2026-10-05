# 제4회 builtin paired build 읽기 전용 독립 결과

작성: 2026-10-06 KST. 최종 확인 시각: 2026-10-05 17:06:27 UTC.
범위: 이미 시작된 실제 제4회 paired build의 단계·결과·기존 운영 상태를 읽기 전용으로 관측했다. 빌드 launch/stop/override/rotation/삭제/제품 또는 운영 설정 변경은 하지 않았다.

## 결과

**실제 운영 build gate: FAIL / 후속 성공 gate 미실행.**

설치된 result.json을 직접 읽어 확인한 terminal 값:
- status: failed
- stage: candidate_compose_build
- top-level key 목록: stage, status (정확히 2개)
- 원본 크기: 63 bytes
- 원본 SHA256: 11644d556ca5ea19dc3766d3e23a271f199cc5021605faffc0c443efd86a3cad

이 result에는 source/image/transaction/error 상세 필드가 없다. 따라서 이 파일만으로 실패의 구체 원인이나 새 후보 source binding을 판단하지 않는다. 실패 뒤 두 systemd unit은 inactive/dead, Result=success였으나 이를 실제 rebuild 성공으로 해석하지 않았다. 정본 terminal status가 failed이므로 성공 gate를 통과하지 못했다.

## 고정 기대 source와 실제 유지된 deploy

기대 후보: Map 1ba6ef4c52f64200e3bc3e9a4fee1dd5f8d4e77e / PinVi 0058369c778f8c3357ee393e12e3447d7975cc1f / Common a960bdb114d99a2ac1b9608a77b240635806e551.

실패 뒤 직접 관측한 deploy-status는 **old committed**였다.
- Map: 13f87577acfc1b7f6eca81a4b7e4b38babd59f81
- PinVi: 80c92b6c4f45a4087844efa00ee67c07e9f18142
- deploy run_id: 80047110-f67d-401d-9688-814758d3fdb0
- pinset SHA256: 78acce4566d44217c10c111275ddcde183aab631a992df2eff90a646fced7c7a
- application schema heads: Map 404_transport_provider_identity / PinVi 20260917_0102

기존 6개 컨테이너는 마지막 직접 docker ps 조회에서 모두 healthy였다. 아래는 유지된 deploy의 image ID이며 새 후보 이미지로 승격하지 않는다.

| 기존 서비스 | committed image ID |
| --- | --- |
| Map API | sha256:9414c05f18dbb9ddf69cd5965cd6f078170cd3a271555e048a148131e523bf06 |
| Map code-server | sha256:7d13cced25ae125ffe26576f84eadac7b3c114a90cd061aefabb435a995ffe85 |
| Map UI | sha256:6b8879d38cfcebcb7973973fd5e3205cca788d74ef46081c218b5e49d4a1251e |
| PinVi API | sha256:91fec1e81c310d966c25841229e9afdc4c71614f059ae6554c28e5ffcc382ef4 |
| PinVi code-server | sha256:5dee0690f69d8eecf5558be1592cded24b421c58ba2e153650f2570f6f8d2929 |
| PinVi web | sha256:e8af8fe8ed1a3cae932428775bc91c7354ba96081f2b05a5c9074bb12f090efc |

## 직접 관측한 단계와 범위

기존 readonly phase/status helper의 remote 읽기 코드를 추출하여 실행했다. 원래 helper의 로컬 private log 파일을 덮어쓰지 않았다. 반복 관측은 약 45–60초 간격을 기준으로 하되 네트워크 read 지연이 있었다. sleep은 45초 이하였고 단계 변화·구체 실패·결과 준비만 부모에게 전달했다.

직접 관측한 compose build 이동:
1. Map UI (전체 경과 52:40에서 관측)
2. PinVi API (53:44)
3. PinVi web (61:38)
4. PinVi Dagster code-server (91:57)
5. result status failed / stage candidate_compose_build

단계 이동은 실제 프로세스의 서비스 식별자로 확인했다. 이전 단계의 모든 이미지/검증 성공을 개별 attestation한 것으로 주장하지 않는다. 모니터 시작 이전 API·Dagster candidate validation 성공은 작성자 전달 정보이며 본인 수행 결과로 합산하지 않는다.

관측한 active docker build argv에 BUILDKIT_SYNTAX override 문자열이 없었다. 실제 generated compose 입력 bytes를 추가 읽으려 했지만 참조 파일이 읽기 시점에 없어 완료하지 못했다. relative 참조는 실제 CLI process cwd를 기준으로 해석했다. pipe/fd를 소비하지 않았고 추가 무한 탐색을 하지 않았다. **실제 generated compose/Dockerfile bytes 및 buildarg 전체 입력은 NOT_VERIFIED**로 남긴다. 고정 source Dockerfile/body의 이전 독립 hash 검증과 active argv의 제한된 부재 검증을 이 미확인 범위와 구분한다.

1회 SSH readonly poll은 40초 transport timeout이었다. 이를 build 실패로 추론하지 않았고 이후 정상 관측으로 돌아왔다. 실제 build 실패 판정은 terminal result.json에서 확인했다.

## 설치된 manager 결과 ID 계약의 직접 source 확인

설치된 compose_service.py 4458–4478의 _pinned_runtime_result는 정확히 10개 key를 반환한다:
success, returncode, resumed, outcome, transaction_id, phase, generation_sha256, pinset_sha256, schema_heads, warnings.

상수는 success=True, returncode=0, resumed=False, phase=committed이다. transaction_id=status.run_id이고 outcome은 호출자가 전달한다. 새 전체 배포 경로는 deployed, 같은 pair 수렴 경로는 converged이다. 이 함수 자체에는 status/stage key가 없다. CLI/wrapper terminal result 및 historical journal schema와 구분해야 한다.

동일 source의 4793–4811은 fresh UUID로 begin_deploy하고, deploy_status.py 318–320의 commit_deploy는 status.run_id를 유지한다. compose_service.py 4854–4864는 committed deploy를 저장한 뒤 outcome=deployed result를 반환한다. 따라서 실제 성공 때 result.transaction_id와 deploy.run_id는 같은 값이어야 한다. 다만 convergence 4720–4751은 previous.run_id를 재사용한다. 현재 legacy journal은 정본 관계로 사용하지 않는다. 이번 failed terminal result에는 해당 성공 result/transaction ID가 없으므로 성공 equality를 만들어 넣지 않았다.

## 최종 증거 경계

본인 직접: 실제 진행 프로세스/서비스 단계, active argv의 override 부재, terminal 63-byte result status/stage/keys/hash, 기존 6개 healthy와 old deploy revision/image/head/ID, 설치된 manager result ID callsite를 읽기 전용으로 확인했다.

본인 NOT_RUN: 새로운 운영 성공 attestation, native fault probe, UI/live/chain gate, 빌드 재실행·재구축·운영 mutation. 이 단계에서 새 성공 receipt를 생성하지 않았다. private 주소·DSN·자격정보·private helper 내용을 이 원문에 포함하지 않는다.

이전 제품 소스 FULL PASS는 그대로 유지되지만 실제 제4회 운영 build는 failed이다. 후속 operating gate는 성공 증거가 확보될 때까지 통과한 것으로 표시할 수 없다.
