# C7 완료 receipt 및 실제 image 읽기 전용 독립 대조

검토일: 2026-10-06. 실제 조회시각2026-10-05 18:42:20Z. 판정은 완료 receipt의 구조·scope 및 실제 artifact 일치 PASS이다. 본인이 실행하거나 terminal 순간을 직접 관측한 build 성공으로 집계하지 않는다.

보존 receipt: map-c7-final-build-evidence.json SHA2567c11bdc51596c91207923de32f39e127d716e34ada019c318b507737d85b2280.
고정 source: Map1a3c4673790f51daa1a2f5ccf803d4e31673bad6.
실제 image ID: sha256:02e52584dbd583e250573ad64fddcbbb84909c084bd943c0eeb9ad1b21185c47.

보존 receipt 직접 검사: statusPASS, ActiveStateactive/SubStateexited/Resultsuccess/ExecMainStatus0의 네 terminal 조건과 source revision을 확인했다. 기록된 시작18:18:27Z/종료18:37:58Z, 약19분31초다. scope는 exact Git archive C7 executor build이며 domain ACL/D1/D2나 여섯 service rollout 성공이라고 표시하지 않는다. 이 terminal snapshot은 root가 collector로 수집한 작성자 증거이며 본인의 당시 unit 관측은 아니다.

본인 실제 read-only 확인:

- receipt의 image ID를 직접 docker image inspect하여 실제 존재를 확인했다.
- kor-travel-map-c7-playwright:local tag의 현재 ID가 receipt와 동일했다.
- 실제 image의 repository-commit label이1a3이고 Playwright base label이 고정9bd26ad900bb5e0f4dee75839e957a89ae89c2b7ab1e76050e559790e946b948 digest와 일치했다.
- 해당 base image도 실제 inspect했다. RepoDigest가9bd와 같고, baseRootFS4개 layer가 C7RootFS20개 layer의 앞4개와 byte digest상 정확히 같았다. label 주장만으로 base 확인을 끝내지 않았다.
- image Created는18:24:19.535761564Z였다. 이는 image config 생성시각이며 export/load가 그 순간 끝났다는 의미는 아니다.

unit 재조회 경계: collector가 receipt를 남긴 뒤 unit을 stop했으므로 현재 LoadStatenot-found/ActiveStateinactive/SubStatedead이고 start/exit timestamps는 빈 값이었다. 현재 Resultsuccess/Exec0은 초기·기본값일 수 있어 완료 근거로 사용하지 않았다. 현재 unit에서 보존 terminal timestamp/rc를 독립적으로 다시 대조할 수 없음을 명시한다. 첫 strict 조회는 이 timestamp 일치 조건에서 실패했고, 후속 safe checks는 실제 image 일치와 unit metadata 소멸을 분리해 기록했다. artifact consistency와 보존 terminal receipt의 검증이 서로 다른 근거다.

추가 inventory 시도: 승인된 docker buildx history ls 및 docker system df를 짧은 제한 시간으로 조회하는 한 호출은 SSH35초 제한 내 결과를 얻지 못했다. 이를 actual build 실패나 network stall로 판단하지 않았다. 따라서 당시 stage-specific BuildKit history는 NOT_VERIFIED이며 조회를 계속 확장하거나 build를 건드리지 않았다.

이전 진행 원문 map-c7-final-build-progress-recovery.md SHA16cd457afb4dfdf0ebe27a8ee4a637adfc6922606b810317b903f53097ad0bdd는 bytes/hash 불변을 직접 확인했다. 당시activating/daemonIO 관찰은 역사적 진행 증거이며 새 완료 결과로 덮어쓰지 않는다. 새 source FULL113853c와 helper static443a 원문도 별도 gate이다.

실행 범위: 승인된 실제 image/unit read 및 로컬 보존 receipt 읽기만 수행했다. 실제 build/stop/restart/prune/rotation/attestation/deploy/DB 변경 또는 성공 receipt 생성은0회다. root가 시작한 새 paired rebuild는 검토·실행 대상에 섞지 않았다. 새 pair의 runtime/native/UI/ACL/D1/D2 성공 판정은 이 C7 artifact 대조의 범위 밖이다. URL·환경·DSN·credentials·raw BuildKit/NPM 로그는 저장하지 않았다.
