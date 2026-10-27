# Common 최신 제품의 pair 배포·공개 UI 수용 (2026-10-27)

## 결론과 범위

PR #1420의 Common Python `aa232ad5`·UI `dev9`를 포함한 검증 source
`0d60cd0b5ae4e4d54e064a24fdbe3716214789ea`를 공식 Manager의 Map·PinVi pair로 배포했다.
운영 전환·기존 일정 복원은 통과했고, 공개 HTTPS UI는 첫 전체 실패를 보존한 뒤
관측 필드만 보강한 같은 예산의 두 번째 실행에서 Map7+PinVi6을49.27초에 통과했다.

이 문서 PR은 운영 이력만 정산한다. 제품·의존성·SQL·테스트·설정은 변경하지 않는다.
부모 #1421/후속 #1422의 제한 시험과 별개로 일반 coordinator·전 writer 전환,
상위 T-CWRITE-01–09와 운영 CPU/RSS 저감 효과는 여전히 미완이다.
이번 배포에서 동시 쓰기 프로필을 새로 활성화하지 않았다.

## 고정 릴리스와 공식 전환

| 항목 | 실제 값 |
|---|---|
| Manager | `aeb2d34ce276e5e219761a62cd4b1c8f39cad72a` |
| Map | `0d60cd0b5ae4e4d54e064a24fdbe3716214789ea` |
| PinVi | `9ebb588ae425e5b09b613f0fed69b94eb1f34592` |
| pair pinset | `13159efb013b91baf5d761d7fcb08c34e40a0f3f29c9c2ebde6eae49136df68a` |
| committed transaction | `300195f6-dc20-43b2-acb4-3d5b62370338` |
| DB head | Map `432_rest_snapshot_atomic` / PinVi `20260917_0102` |

Map source는 정확 CI10개와 두 독립 리뷰를 통과한 #1421 merge tree다.
뒤의 #1422·#1423은 시험/문서만 추가하므로 runtime source를 임의 최신 main으로 바꾸지 않았다.
PinVi source는 유지했지만 공식 배포 단위가 pair이므로 Map3·PinVi3 이미지를 함께 다뤘다.

설치된 Manager의 공식 `pin rotate-pair`와 `pinvi-pair rebuild-pinned --confirm --json`을
각1회만 실행했다. pin 회전의 명령 exit0 뒤 stdout을 단일 JSON으로 읽지 못한 한계는
원장에 남겼고, 재실행 대신 새 pin의 공식 verify·frozen plane dry-run으로 상태를 확인했다.
공용 plane은 current/zero drift/healthy였으며 직접 Compose 교체·강제 재시도는 없었다.

17:04:19 KST에 공식 rebuild를 시작해17:19:37 KST에 operating 수용을 기록했다.
CLI는 `deployed`·`committed`·exit0·warnings0, 별도 supervisor는 정상 종료/exit0이었다.
실제11개 runtime은 모두 healthy, 제품6개 immutable image ID는 committed images 전집과
일치했다. Valkey·공용 plane3개·공용 PG의5개 보호 대상은 ID/image/start/bind까지 보존됐다.
운영 명령은 공용 pair 호스트에만 보냈고 Weather·Transport·Odroid의 이미지는 변경하지 않았다.

## 일정·worker·DB의 별도 수용

새 baseline은 전체67개의 ID/상태를 저장했다. Map38 RUNNING/13 STOPPED,
PinVi13 RUNNING과 외부 위치3 RUNNING이었다. 두 대상의 원래 RUNNING51개만 일시 정지하고
STARTED tick·queued/active run·실제 run/step worker를 자연 종료까지 확인했다.
원 STOPPED나 외부 위치를 덮지 않았고 강제 수집·worker 종료는 하지 않았다.

전역 active 목록은 cursor로 마지막 페이지까지 읽고 상한/늦은 응답은 불완전 실패로 처리했다.
두 번의 안정 관찰과 전환 직전 재확인, 별도 PG read-only 조회로 열린 TX/잠재 write lock/
prepared TX를 확인했다. 이 관찰을 미래의 수동 실행·writer가 절대 없다는 보장으로 확대하지 않는다.
두 DB의 OID/system ID와 head를 보존했고 조회는 statement3초/lock0.5초 등 기존 상한을 유지했다.

공식 canonical smoke는 이번 transaction의 c6c job1개를 만들어 failed/finalized 이력으로 남긴다.
따라서 전체 before==전체 after라는 초기 가정을 운영 전에 바로잡았다.
정확한 새 transaction→fixture1→job1의 최종 cancellation/member receipt를 검증하고,
그1개만 제외한 기존 집합45개의 count/정렬 row-SHA가 그대로임을 확인했다. 배포 후 total은46이었다.
기존 이력을 삭제하거나 상태를 고치지 않았다. 과거의 running4 부분집합과 전체45는 다른 범위다.

수용 후 원래 RUNNING51개만 복구했고 전체67개 ID/상태가 baseline과 정확히 같음을 재조회했다.
완료된 자기 supervisor의 MainPID0·커널 cgroup 부재·원 process identity 부재를 확인했다.
`TasksCurrent=[not set]`를 측정0으로 바꾸지 않았으며, 정상 종료 증빙을 보존한 뒤 자기 unit만 정리했다.
이전 이미지 식별자와 준비 source·비추적 운영 원장은 보존했다.

## 공개 HTTPS UI: 첫 실패와 후속 통과

첫 실행 `ef7a058a44c24ffd87120ad078c4da8d`는56.39초에 **전체 실패**했다.
Map7은 실제 SSR script hold·hydration·로그인·지도·목록/상세·로그아웃을 통과했으나,
PinVi는3개 단계 뒤 `admin_list_filter_and_dto`에서 `TimeoutError`였다.
관측 카운터는 목록200이2회·상세200이0회였다. 초기 seed의 상세 read는 seed 할당 전에
끝나 카운터에 누락될 수 있으므로, 상세 요청 자체가0회였다고 해석하지 않는다.
정확한 하위 단계·원인은1차 기록만으로 확정하지 못했다. 자기 세션·process·profile은 회수했다.

원인을 구분하려고 PinVi의 기존 조회/화면 동작 사이에 안전한 `admin_substage` 관측 값만 추가했다.
HTTP·assertion·timeout·budget·Map 코드·운영 이미지는 바꾸지 않았다.
정확 source 두 리뷰 후 두 번째 실행 `790bfac096fa4f0ea5b55256f46ff002`는
49.27초/SSH exit0으로 Map7+PinVi6, 전체13개 단계를 통과했다.
첫 시간 초과의 원인은 확정하지 못했으며 제품 버그를 고쳤거나 재발을 막았다는 주장은 하지 않는다.

두 번째 실행의 Map은12개 script를 실제 응답 변조 없이 보류한 상태에서 native 입력/버튼3개
비활성·로그인 POST0을 확인하고, 실제 hydration 뒤 활성화를 확인했다. hold 만료는 없었다.
PinVi는 `admin_substage=complete`, 목록200은4회·상세200은2회였고 실제 지도 tile·DTO·lineage를 확인했다.
각 서비스는 매 실행 own login1/logout1, 보호 조회401과 세션 회수를 확인했다.
Map WebSocket 중단·자기 browser process0/profile 제거·runtime/env 불변도 수용했다.
Map의 known 인증 입력은 숨김 TTY/RAM/stdin 경로와 로그인 전 오프라인 검증을 통과했다.
PinVi는 기존 정본의 bootstrap 인증값을 RAM에서만 읽어 사용했다. UI 검증에서는
인증값을 추측·초기화하거나 인증 상태를 보존하지 않았다.

이13개 공개 read-only UI 수용은 cancellation14개·전체 수집·모든 장애 조건·CPU/RSS 저감의
증명이 아니다. 문서 전용 정산으로 runtime 이미지를 다시 빌드하지 않는다.

## 증거 식별자

아래 원장은 비추적 운영 보관소의 immutable 파일이다. 원문 운영 데이터·접속 정보는 이 문서에 싣지 않는다.

| 원장 | SHA256 |
|---|---|
| `map1420-official-pair-actual-runner-result-w-r1.json` | `1d6ee982e0ecb4f872da9414ccd5a31e5be29ba83af07cc4316b3208160cb872` |
| `map1420-official-pair-actual-pg-before-w-r1.json` | `9b8d1e27ec4f8c7343e5302f02ff5178193c9c516a84693aa37ad620551342d7` |
| `map1420-official-pair-actual-pg-after-w-r1.json` | `b0344f255e425ca154a80e0dc740258e0ce1f7c810802d4643082e8f58feb3ba` |
| `map1420-official-pair-actual-restore-w-r1.json` | `4c1abae51bdc014efdc964adc06211fc1e462191a6f7c820885c3b08338a3296` |
| `map1420-official-pair-actual-own-unit-cleanup-w-r1.json` | `cffa6c45dadf41c8d16b6d438954502dc7263e1da1054e2d1ac2f8bfd8d3ab01` |
| 첫 UI `map1420-dev9-public13-root-ef7a058a44c24ffd87120ad078c4da8d.json` | `5f3bba20e58ad938f8f1477b363e6694911eeddc5b3a587297823fbbde295ea9` |
| 후속 UI `map1420-dev9-public13-root-790bfac096fa4f0ea5b55256f46ff002.json` | `fae8f622c932fb749f16f170ecb7e0625a14dff1ad0c81866297a15f0e5fe297` |

배포/복원 독립 수용 `0ac1acd6…`와 후속 UI 독립 수용 `8fc66492…`는 별도로 검산했다.
준비 중의 fixture 전체 불변 오가정·최종 event 실패의 fail-open·source 조립/오프라인 검증 import
오류는 실제 실행 전에 차단·수정하고 원 이력을 보존했다. 실제 첫 UI 실패 역시 후속 통과로 덮지 않았다.
