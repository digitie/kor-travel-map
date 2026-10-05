# builtin retry1 실제 build terminal 독립 읽기 전용 원문

작성: 2026-10-06 KST. 최종 terminal 직접 확인: 2026-10-05 17:26:59 UTC.
범위: 작성자가 launch한 동일 pair retry1의 단계·정본 결과·deploy/컨테이너 metadata를 읽기 전용으로 관측했다. 본인은 launch/build/rotation/cleanup/ledger 변경/제품 또는 운영 mutation을 수행하지 않았다.

## 판정과 terminal 원문

**실제 build/deploy terminal 및 읽기 전용 metadata 연결: PASS.**
이 판정에는 installed source-byte/DB/child CLI attestation, native recovery, UI/live/chain gate가 포함되지 않는다.

정본 retry1 result.json:
- SHA256: 4a7ff2e853959507e8fcf0406fd324fa874c5ebcd83550258abaaecd9b4ed9a4
- 원본 478 bytes, root/0600 regular file.
- 정확히 10개 key: generation_sha256, outcome, phase, pinset_sha256, resumed, returncode, schema_heads, success, transaction_id, warnings.
- success is True / returncode는 int 0 / resumed=False / outcome=deployed / phase=committed.
- warnings는 list[str]이고 개수 0. raw warning 내용은 공개하지 않는다.
- transaction_id: 360afa9e-a50b-4968-bc63-0111153d5bfe
- generation_sha256: 31a3557d5b679d95ab56614d4bd2f9e80896de96963c4b2cbeb6703c10391a64
- pinset_sha256: 54de39d1be7a3539fb016565212e6182999ec195b9938d813b5e7801d728aa25
- schema_heads: Map 404_transport_provider_identity / PinVi 20260917_0102.

정상 설치된 CLI는 status=success를 추가하지 않는다. 이번 정상 파일도 status/stage key가 없으며 installed canonical 10-field 계약을 직접 검증했다. systemd Result나 exit만으로 성공을 추론하지 않았다. generation 값은 정본 기록에서 읽었으며 후보 구조 전체로 독립 재산출한 값이라고 주장하지 않는다.

## 정본 deploy와 실제 컨테이너 metadata 연결

설치된 strict deploy-status reader를 사용하여 같은 읽기에서 다음을 확인했다:
- state=committed.
- Map 1ba6ef4c52f64200e3bc3e9a4fee1dd5f8d4e77e.
- PinVi 0058369c778f8c3357ee393e12e3447d7975cc1f.
- manager e2a1a5b42fec207fc6c5e0638c652de04e5694d4.
- result.transaction_id == actual deploy.run_id.
- result.pinset_sha256와 schema_heads가 actual deploy와 일치.
- deploy 원문 SHA256: c46e460a18ffca68963a871afd2390ca33347bbae2328b7e46315a5a3963eb1d.
- 모든 검증 후 result/deploy bytes를 다시 읽어 동일함을 확인.

6개 실제 컨테이너를 docker inspect로 읽어 image ID가 committed deploy와 일치하고 running=True, health=healthy, image revision label이 해당 고정 제품 SHA와 일치함을 직접 확인했다.

| 서비스 | 실제 image ID |
| --- | --- |
| Map API | sha256:43809da2706bbb0eb938fbd359d21a9c6152c37c21add43f61b139d70765e3f7 |
| Map code-server | sha256:5ded0abe5dc4deddfc1e7ccc5353cffa8ecab001449abeb3f606267d0348ad9f |
| Map UI | sha256:14dfab450a5a0bf7f00794ee6bcab390e5258f268d4013081a8403f2a0baf355 |
| PinVi API | sha256:354cbf0f63868998c35c19d117de647e5d43802612181b376aff09deece22eca |
| PinVi code-server | sha256:cebcfb60ef5e41fd2d96c095dca8790c0d20fe2e5c5b4e66d36da7918b4df128 |
| PinVi web | sha256:ac30b1b823f3e433857bc949ca959154baf84a0ad39408b4f06efb1858fc3314 |

metadata/label 연결은 installed 파일 hash 검증을 대신하지 않는다. Common a960 제품은 고정 기대 source이며 이번 monitor에서 actual installed Common commit/source bytes를 검증한 것으로 집계하지 않는다.

## retry claim과 관측 단계

현재 ordinal 1 claim을 별도로 직접 읽었다:
- SHA256: 53b91ed45c9688259405984a129f1ad52f386f497ef8a9fd530099c2bcf1e95f.
- root/0600 regular/link1, key 정확히 manager_source_revision/output_directory/pinset_sha256.
- manager e2a, pinset 54de 및 retry1 출력 대응 일치.
- claim/기존 원문 삭제·수정 없이 읽기만 수행.

직접 관측한 흐름:
1. 첫 poll은 PinVi ETL compose build (전체 경과 약2:34).
2. compose run (약5:33).
3. exact 새 pair/pinset의 deploy in_progress 및 기존 runtime 정지 (약7:20).
4. exact pair committed, 6개 healthy이나 result 미생성 상태 (약11:17).
5. retry1 terminal result 생성, canonical success contract 확인, unit inactive/dead.

active ETL build argv에서 BUILDKIT_SYNTAX override 문자열이 없었다. 실제 generated compose/Dockerfile bytes의 전체 재확인은 수행하지 않았다. 이전 source FULL hash 검증과 active argv의 제한된 검사 범위를 유지한다. 모니터 시작 이전의 cached 빌드 단계도 본인이 개별 실행/검증한 것으로 주장하지 않는다. 약45–60초 간격의 readonly phase/status 관측을 사용했고 단계 변화·실패·결과 준비만 부모에게 전달했다.

## 불변 원문과 미실행 범위

이전 제4회 FAIL 원문과 retry-admission 원문은 수정하지 않았다.
- map-pinvi-builtin-operating-build-recovery.md: 31a76790f184456bf241c3989052c4827c70b9e630398920c4cae58fe8eb8759
- map-pinvi-builtin-retry-admission-recovery.md: 82dc309a504c9feaf2ea3be59e0967e1b84c40127d4ece2da2d41145b320be06

본인 NOT_RUN: fresh preflight 실행, launch/build/회전/삭제/ledger mutation, reviewed runtime attestation helper, 실제 installed source-byte 검증과 post-rebuild DB head/child CLI 조회, native fault probe, UI/live/chain E2E. 작성자·peer 결과는 본인 수행에 합산하지 않았다. private 주소·DSN·자격정보·raw warnings/private helper 내용은 포함하지 않는다.

실제 retry1 canonical terminal 성공과 정확한 deploy/image metadata 연결은 확인됐다. 후속 runtime/native/UI gate는 별도 증거가 필요하다. 이전 실패가 재시도 성공 때문에 성공 기록으로 바뀌지 않는다.
