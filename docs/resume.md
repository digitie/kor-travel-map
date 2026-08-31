# resume.md — 현재 진척도와 다음 한 작업

## 2026-08-31 — head 값 고정 해제 (Map PR #1124 / Manager PR #276), `301`은 분리

`application_head = "300"` 리터럴 Map 6곳 + Manager 11곳을 파생값으로 바꿨다. `300`은
`BASELINE_ROOT_REVISION`으로만 남는다 — head가 아니라 `0236 → 300` handoff의 stamp
목적지다. Manager는 head를 **두 독립 출처가 일치할 때만** 받는다(ADR-42).

게이트 규칙을 **"비교에 쓰였나"에서 "존재하나"로** 바꿨다. 리터럴과 비교를 다른 줄에 두는
것은 우회가 아니라 평범한 코드이므로, 비교를 탐지하는 규칙은 원리적으로 완결될 수 없다.
적대 리뷰가 실행으로 뚫은 14가지를 되짚어 전부 막히는 것을 확인했다.

### 다음 한 작업

**`chain/301-carrier`를 PostGIS 통합으로 검증한다.** 계약 확장은 구현이 끝났다.

#### 구현된 것

| 갈래 | 무엇이 문제였나 | 어떻게 풀었나 |
|---|---|---|
| facet | `application-destination-alembic-version.sql`이 `alembic_version = ARRAY['300']`을 담고 있었다. 이 SQL의 산출물은 성공/실패 두 문자열뿐인 **단일 boolean**이고 기대 digest는 성공 sentinel의 sha256이라, head가 움직이면 영원히 `mismatch`가 되고 **옮겨갈 digest가 없었다.** | 술어를 제거했다. 기대 digest는 **한 글자도 바뀌지 않는다** — 바뀌는 것은 SQL 바이트와 reference manifest뿐이라 PostGIS oracle 없이 재봉인했다. revision 동등성은 배포 executable 넷이 파생 head로 이미 대조한다. |
| catalog | `application-catalog.sql`은 객체마다 한 행을 내므로 digest가 **진짜 상태 의존**이다. | 봉인값은 `300` 도달 순간에만 대조한다. `command.upgrade`를 `300`에서 끊고 exact 대조를 끝낸 뒤 head까지 올려 관측값을 receipt에 남긴다. 그 이후의 정본은 receipt다. |

```
baseline digest ──(300 체크포인트)── root receipt ──(pre-ACL)── finalize receipt
                                                                    │
                                                          (post-ACL) └── final permit
```

`300`에서의 엄격함은 **하나도 잃지 않는다.** 세 지점 모두 head == baseline root일 때
종전과 동일한 봉인값 대조를 한다. 근거가 옮겨가는 것은 그 너머뿐이다(Manager ADR-43).

형제 저장소: `kor-travel-docker-manager` 브랜치 `chain/head-state-receipt`
(root result v3 필드 + permit의 head 인지 catalog 기대값). n150 CI-parity 초록.

#### 남은 것

1. **PostGIS 통합 실행.** `301`이 실제로 적용되고 fresh 설치 → finalize → final permit이
   완주하는지는 통합 job만 답할 수 있다. `feat/m03-import-child-commands`가 머지되면
   이 브랜치를 main 위로 rebase하고 PR을 연다.
2. 통합에서 드러날 fixture 갱신 — 특히 `tests/integration/test_alembic_upgrade.py`의
   `_TVN40_RAW_SQL_CATALOG_SHA256`(`uq_curation_import_plan_claims_plan_sha256`이 catalog를
   바꾼다)과 새 표의 exact-catalog 핀.
3. 그 뒤에야 `T-VN-M03`의 child command 발급 증분(`feat/m03-child-command-issuance`가
   provenance 반환 확장까지 담고 있다).

#### 확인하지 않은 것

- 실 프로덕션 rebuild.
- baseline을 다시 cut할 때 `build-baseline.sh`가 새 facet SQL과 정합한지.

## 2026-08-30 — provider 핀 동기화 완료, task 원장 무결성 복구

PR #1123이 provider 핀 전수 동기화, Protocol 적합성 게이트, 페이지네이션 절단 보정,
task 해제 조건 복원을 담는다. 핀 11개 상향 / 2개 보류(datagokr·krheritage — provider가
종료 조건을 휴리스틱으로 바꿔 조용한 절단을 만든다).

`T-VN-FINAL-REBUILD`가 해제 조건 B1~B4가 **삭제된 뒤** 완료 처리된 것을 확인해 열린
상태로 되돌렸다. B3/B4는 generation `8eedf171` 이후 5개 pinset 재빌드로 반복 false다.
열린 16개 task의 해제 조건을 `docs/tasks-acceptance.md`로 복원하고, 조건 없는 task를
막는 게이트를 뒀다(첫 실행에서 5건 적발).

### 다음 한 작업

`T-VN-M03` import child-command의 다음 증분. linkage migration(`301`)은
`feat/m03-import-child-commands`에 있고, child를 **실행**하려면 preview가 행마다 좌표를
포함한 typed `manual_feature` payload와 canonical SHA를 plan에 저장해야 한다(설계 §6.1).
현재 `ResolvedCurationImportRow`에 좌표가 없고 §7이 주소 기반 추정 생성을 금지하므로
**import 포맷 확장 결정이 선행**이다. 그 결정 없이 repo/route를 먼저 쓰면 좌표를
추론하는 경로가 생긴다.

## 2026-08-29 — M05 execution identity v6로 terminal 반복 제거

같은 Map·PinVi pair에서 Docker Manager 코드만 고쳤을 때 v5 `pinset_sha256` terminal block이 그대로 남아 문서
전용 source revision을 바꿔 새 후보를 만드는 반복을 확인했다. 이를 우회하지 않는다. Map·PinVi source
materialization identity인 v5 pinset은 과거 registry/history/block 증거와 함께 보존하고, trusted Manager release
revision을 추가로 결박한 v6 execution identity를 새 execution ledger·terminal block·generation binding의 정본으로
도입한다.

Manager revision은 operator CLI·환경 입력이 아니라 trusted installer의 `.ktdm-source-revision`과
`.ktdm-release-manifest.json`이 exact match할 때만 인정한다. Map attestation과 PinVi isolated admission은 Map/PinVi
source SHA·v5 pinset·Manager revision·v6 execution digest를 모두 exact 대조한다. 따라서 Manager-only fix는 새
immutable execution candidate가 되지만, 동일 v6 execution은 계속 한 번만 실행할 수 있다. terminal raw output은
완주 전까지 gitignored local forensic 문서에만 상세 기록한다.

## 2026-08-29 — M05 `9b6eab1e…` terminal과 Map health transport 보정

Map `86d38d469dacfc74ca7c2cf811e5296ed3aead82`·PinVi
`3b9d60261ea69318270392291103b88ff9ed0a6e`·Manager
`1dbd7cc2b71cb7eb70bcc069330f8c9db61fb06d`·pinset
`9b6eab1eeb04bae4d96d4d738bfa2600bd86e5c83adf58307350c0eccfbc6a85`는 trusted `ktdctl`의 atomic pair
rotation, 단발 rebuild와 공개 generation `match` 뒤 새 root-owned leaf에서 M04/M05 E2E를 정확히 한 번
실행했다. root registry의 exact terminal phase는 `map_health_transport_failed`이며 cleanup은 통과했다.

서로 다른 후보 `41be91fe…`·`5512ce12…`·`b46743ea…`도 PinVi/M04/M05 이전의 같은 Map host loopback
health transport 단계에서 종료했다. Manager `bc99ce1…`은 container 내부 health와 host publish socket의
짧은 경합만 같은 immutable candidate 안에서 최대 6회 재시도한다. HTTP status·응답 계약 오류는 재시도하지
않는다. 새 Manager exact-head CI·전문 적대 리뷰 두 건·새 Map/PinVi provenance가 모두 충족될 때만 fresh
`ktdctl pin rotate-pair` 후보를 만들며, 이 pinset과 output leaf는 재실행하지 않는다.

## 2026-08-29 — M05 후보 동결과 Docker Manager 단일 실행 경계

M05 runtime candidate는 Map `86d38d469dacfc74ca7c2cf811e5296ed3aead82`, PinVi runtime source
`3b9d60261ea69318270392291103b88ff9ed0a6e`, Docker Manager `03a3300…`을 한 번 확정해 동결한다. 이후
문서 전용 Map/PinVi/Manager PR은 즉시 병합하되 Map/PinVi provenance, `ktdctl pin rotate-pair`, pinset을
재결박하지 않고 동결된 candidate만 참조한다. 코드·Compose·계약·빌드 입력 변경만 새 candidate와 한 번의
CI·전문 리뷰·one-shot을 소비한다.

runtime pinning, pair 결박, public generation 복사, rollback, rebuild/E2E는 Docker Manager `ktdctl`만 수행한다.
`init`, `publish-generation`, `rotate`, `rotate-pair`, `apply-pending`, `rollback`, `block` 전체는 active global
mutation에서 write 전에 거절되고 trusted launcher의 검증된 inherited-lock terminal fallback만 예외다. 관측자는
lock 해제 뒤 공개 `pin verify`를 읽어 판정하며 terminal pinset·원문 artifact는 재실행·열람하지 않는다.

## 2026-08-29 — M05 `3d8d63e1…` rebuild 완료 뒤의 제어면 terminal 보존

Map `0cb126fc…`·PinVi `9372137e…`·Manager `712ae8c…`·pinset `3d8d63e1…`은 모든 CI와
exact-head 전문 적대 재리뷰 두 건의 GO 뒤 clean trusted Manager release, root 원자
`ktdctl pin rotate-pair`, 공개 registry·generation `pending_rebuild` gate를 통과했다. 새 root-owned
leaf의 pinned rebuild는 시작 뒤 root-global mutation lock이 유지되는 동안 원격 호출의 즉시 종료 상태만으로
실패처럼 보였다. raw leaf를 열지 않고 lock 해제 뒤 공개 `pin verify`만 다시 확인한 결과 generation은
`match`였다. 그러나 lock 보유 중에 이미 root registry에 unconditional terminal block을 기록했으므로 이
pinset은 M04/M05 launcher를 실행하지 않고 영구 재시도 금지로 보존한다.

이는 Map·PinVi runtime 계약의 실패 증거가 아니다. 반복 방지 규율은 launcher/rebuild의 원격 호출 결과가
즉시 확정되지 않으면 root-global mutation lock이 해제될 때까지 기다리고, 그 뒤 공개 `pin verify`의
exact pair·`current` generation을 확인한 다음에만 terminal을 분류한다. 외부 root `pin block`은 active
global mutation에서 코드로 거절하며, trusted launcher의 inherited-lock fallback만 예외다. private leaf·
stdout/stderr·HTTP·container·환경 원문은 읽지 않는다.

### 다음 한 작업

문서 전용 PR은 즉시 병합하되 동결된 runtime candidate provenance에는 영향을 주지 않는다. Docker Manager는
모든 runtime pin mutation을 active global mutation과 코드로 직렬화해 거절하고, trusted launcher의 inherited-lock
fallback만 허용하도록 보정한다. 이 새 Manager source와 동결된 PinVi runtime source의 CI·exact-head 전문 적대 재리뷰
두 건이 GO일 때만 fresh pair를 만든다. 새 후보에서만 trusted `ktdctl` atomic rotation,
단발 rebuild/public generation gate, 새 root-owned M04/M05 one-shot을 순서대로 실행한다. `3d8d63e1…`과
기존 terminal pinset·source pair·Manager source·leaf는 재실행하지 않는다.

## 2026-08-29 — M05 `7035b0b1…` terminal 보존과 admission 보정

Map `3916ebfd…`·PinVi `73870e52…`·Manager `291bd161…`·pinset `7035b0b1…`은 CI·전문 적대 재리뷰 두
건의 GO 뒤 trusted `ktdctl pin rotate-pair`, 단발 pinned rebuild, public generation `match`를 통과했다.
새 root-owned leaf의 n150 isolated M04/M05 launcher는 정확히 한 번 실행되어 terminal로 차단됐고, 공개
registry의 raw-free fixed phase는 `runtime_setup_admission`이다. HTTP·container·환경·output leaf·private
receipt 원문은 열거나 재사용하지 않는다.

### 다음 한 작업

이 Map 문서 PR을 즉시 병합하고 merge revision을 PinVi admin·full provenance에 재결박한다. Manager는
private admission 생성·전달·no-follow consumer verification 경계에서 원문 없이 fixed phase를 보존할 수 있게
정적으로 보정한다. 새 Manager source·새 PinVi provenance의 CI와 exact-head 전문 적대 재리뷰 두 건이 GO일
때만 atomic `ktdctl pin rotate-pair`, 단발 rebuild/public generation gate, 새 root-owned M04/M05 one-shot을
순서대로 진행한다. 모든 terminal pinset·source pair·Manager source·output leaf는 재실행하지 않는다.

## 2026-08-28 — M05 `82850711…` terminal 보존과 runtime setup 세분화

Map `35a43317…`·PinVi `fed16a5c…`·Manager `eed1920…`·pinset `82850711…`은 필수 CI·전문
적대 재리뷰 두 건의 GO와 trusted `ktdctl pin rotate-pair`, 단발 pinned rebuild, registry/public
generation `match` 뒤 n150 isolated M04/M05 launcher에서 정확히 한 번 실행되어 terminal로 차단됐다.
공개 registry의 raw-detail 없는 고정 phase는 `runtime_setup`이며, HTTP·container·환경·output leaf·private
receipt 원문은 열거나 재사용하지 않는다.

### 다음 한 작업

이 Map 문서 PR을 즉시 병합하고 merge revision을 PinVi `admin`·`full` provenance에 재결박한다. Manager는
isolated runtime setup 내부의 ordinary exception을 안전한 세부 allowlist phase로 수렴하도록 보정한다. 그 새
Manager source와 새 PinVi head의 CI·exact-head 전문 적대 리뷰 두 건이 GO일 때만 새 atomic
`ktdctl pin rotate-pair`, pinned rebuild/public generation gate, 새 root-owned M04/M05 one-shot을 순서대로
진행한다. terminal pinset·source pair·output leaf는 열거나 재실행하지 않는다.

## 2026-08-28 — M05 `5592a1d4…` terminal 보존과 다음 Docker Manager phase 수렴

Map `75762397…`·PinVi `358f607a…`·Manager `a4d60d1…`·pinset `5592a1d4…`은 모든 CI·전문
적대 재리뷰 두 건의 GO와 trusted `ktdctl pin rotate-pair`, 단발 pinned rebuild, registry/public
generation `match` 뒤 n150 isolated M04/M05 launcher에서 정확히 한 번 실행되어 terminal로 차단됐다.
공개 registry에는 raw detail 대신 `driver_contract_failed` fixed phase만 있고, HTTP·container·환경·output
leaf 원문은 열거나 재사용하지 않는다.

### 다음 한 작업

이 Map 문서 PR을 즉시 병합하고 merge revision을 PinVi `admin`·`full` provenance에 재결박한다. Manager는
unexpected ordinary exception을 현재 allowlist phase로만 수렴하도록 보정한다. 그 새 Manager source와
새 PinVi head의 CI·exact-head 전문 적대 리뷰 두 건이 GO일 때만 새 atomic `ktdctl pin rotate-pair`, pinned
rebuild/public generation gate, 새 root-owned M04/M05 one-shot을 순서대로 진행한다. terminal pinset·source
pair·output leaf는 열거나 재실행하지 않는다.

## 2026-08-28 — M05 terminal 보존과 다음 Docker Manager 결박

Map `053904ce…`·PinVi `1b29bfea…`·Manager `8f41a9bd…`·pinset `5ad3b08c…`은 trusted
`ktdctl pin rotate-pair`와 `run-pinned-rebuild-once`, registry/public generation `match` 뒤 n150 isolated
M04/M05 launcher에서 정확히 한 번 실행되어 terminal로 차단됐다. HTTP·container·환경·output leaf 원문은
열거나 재사용하지 않는다. Manager `a4d60d1…`은 다음 terminal registry 기록을 raw detail 대신 allowlist
fixed phase로 수렴시킨다.

### 다음 한 작업

이 Map 문서 PR을 즉시 병합하고 그 merge revision을 PinVi `admin`·`full` provenance에 재결박한다. Manager
`a4d60d1…`과 새 PinVi head의 CI·exact-head 전문 적대 리뷰 두 건이 GO일 때만 trusted release, atomic
`ktdctl pin rotate-pair`, pinned rebuild/public generation gate, 새 root-owned M04/M05 one-shot을 순서대로
진행한다. 기존 terminal pinset·source pair·Manager source·output leaf는 열거나 재실행하지 않는다.

## 2026-08-28 — M05 Manager isolated admission 경계 보강

PinVi의 isolated Compose 허용이 호출자 환경변수만으로 열리지 않도록, trusted Docker Manager
`ktdctl`가 transaction·pinset·Manager/Map/PinVi revision에 결박한 private `0600` admission
receipt를 만들고 PinVi가 no-follow로 검증하는 paired 계약을 추가했다. legacy environment marker와
수동 Compose는 명시적으로 거절한다. Map은 이 계약의 소비자 문서를 같은 정본으로 맞추며,
PinVi #500과 Docker Manager #256은 이 admission 계약을 서로 검증한다.

### 다음 한 작업

이 Map 문서 PR을 CI green 뒤 즉시 병합하고, 병합 revision을 PinVi `admin`·`full` provenance에
재결박한다. 그 뒤 PinVi #500과 Manager #256의 최신 CI 및 exact-head 전문 적대 리뷰 두 건이 모두
GO일 때만 새 atomic `ktdctl pin rotate-pair` candidate를 만들 수 있다. 기존 terminal pinset·raw
artifact·output leaf는 열거나 재실행하지 않는다.

## 2026-08-28 — M05 Docker Manager 공개 generation 계약 정렬

M05 runtime pinning, Map·PinVi source pair 결박, one-shot 실행의 유일한 운영 정본을 trusted
Docker Manager `ktdctl`로 명시했다. 후속 candidate는 atomic `pin rotate-pair` 뒤 인증된
`/api/v1/runtime-pins` 및 `/api/v1/pinned-runtime/generation` 공개 사본에서 완전한 이전
committed generation 또는 registry가 exact로 차단한 terminal generation의 `pending_rebuild` 또는
`match`를 확인해야 한다. 새 launcher 뒤에는
`pinset_binding=match`를 다시 요구한다. private manifest/journal·raw launcher output은 소비하지
않으며, Map C7의 v6/v8 exact schema 변경은 Manager와 paired PR로만 진행한다.
이번 paired 변경은 v8 journal 16키와 committed PinVi role extension의 의미까지 같은 strict
validator로 고정한다.

### 다음 한 작업

Manager 공개 generation 계약 PR이 CI와 exact-head 전문 적대 리뷰 두 건을 통과해 병합되면, 이
Map revision을 PinVi `admin`·`full` provenance와 함께 새 Manager `rotate-pair` candidate로 결박한다.
그 전에는 기존 terminal pinset을 열거나 재실행하지 않는다.

## 2026-08-28 — M05 `b46743ea…` terminal 보존 후 대기

Map `6bfa4703…`·PinVi `340717de…`·Manager `00c33ad…`·pinset `b46743ea…`은 trusted clean release의
registry/public-copy 검증과 atomic pair rotation 뒤 n150 isolated M04/M05 launcher에서 정확히 한 번 실행됐다.
권위 있는 고정 결과는 `launcher_safe_result_unavailable`이었다. 원문 HTTP·컨테이너·환경 출력과 output leaf는 읽지
않았으며, 후속 gate가 exact unconditional terminal 차단과 public copy를 확인했다. 이 pinset·source pair·Manager
source·output leaf는 앞선 모든 terminal candidate와 함께 절대 재시도하지 않는다.

### 현재 상태

사용자 지시에 따라 이 terminal 기록까지 문서화한 뒤 대기한다. 새 source·pair·pinset 생성, PR ready·merge, n150
실행은 명시적 재개 지시 전까지 수행하지 않는다.

## 2026-08-28 — M05 finalization receipt 경계 보강

전문 data-contract 적대 재리뷰가 Manager `862e8bf…`의 cleanup·terminal block ordinary exception은 fixed driver
receipt 없이 전파될 수 있는 P1을 발견했다. terminal `41be91fe…`는 열거나 재실행하지 않았다. Manager `00c33ad…`는
main·cleanup·terminal block의 ordinary exception을 모두 원문 없이 `driver_contract_failed` fixed terminal receipt로
수렴시키며, cleanup 및 terminal block 오류 주입 회귀로 경계를 고정한다.

### 이 변경의 다음 한 작업

이 기록을 포함한 새 Map revision과 PinVi `admin`·`full` provenance revision을 Manager `00c33ad…` source와 새 atomic
pinset으로 만든다. 최신 CI, 전문 적대 리뷰 두 건, registry/public-copy 무결성이 모두 정합할 때만 새 root-owned
output leaf에서 n150 M04/M05 isolated E2E를 정확히 한 번 실행한다.

## 2026-08-28 — terminal `41be91fe…` 보존, fixed driver receipt source 준비

Map `fa55316d…`·PinVi `f9fce72f…`·Manager `cd8b3054…`·pinset `41be91fe…`은 trusted clean release의
registry/public-copy 검증과 atomic pair rotation 뒤 n150 isolated M04/M05 launcher에서 정확히 한 번 실행됐다.
launcher는 exit 1이었고 권위 있는 고정 결과는 `launcher_safe_result_unavailable`이었다. 원문 HTTP·컨테이너·환경
출력과 output leaf는 읽지 않았으며, 후속 gate가 exact unconditional terminal 차단과 public copy를 확인했다. 이
pinset·source pair·Manager source·output leaf는 `a3f6a8f3…`·`22563762…`·`c700bd2e…`·`fa28a6e7…`·`5512ce12…`과 함께
절대 재시도하지 않는다.

### 이 변경의 다음 한 작업

이 terminal 기록을 포함한 새 Map revision과 PinVi `admin`·`full` provenance revision을 Manager `00c33ad…`의
unexpected ordinary exception도 `driver_contract_failed` fixed terminal receipt로 수렴하는 source와 새 atomic
pinset으로 만든다. 최신 CI, 전문 적대 리뷰 두 건, registry/public-copy 무결성이 모두 정합할 때만 새 root-owned
output leaf에서 n150 M04/M05 isolated E2E를 정확히 한 번 실행한다.

## 2026-08-28 — terminal `5512ce12…` 보존, fresh source trio 준비

Map `73150672…`·PinVi `d8dc386d…`·Manager `c31c8448…`·pinset `5512ce12…`은 trusted clean release의
registry/public-copy 검증과 atomic pair rotation 뒤 n150 isolated M04/M05 launcher에서 정확히 한 번 실행됐다.
launcher는 exit 1이었고 권위 있는 고정 결과는 `launcher_safe_result_unavailable`이었다. 원문 HTTP·컨테이너·환경
출력과 output leaf는 읽지 않았으며, 후속 gate가 exact unconditional terminal 차단과 public copy를 확인했다. 이
pinset·source pair·Manager source·output leaf는 `a3f6a8f3…`·`22563762…`·`c700bd2e…`·`fa28a6e7…`과 함께 절대
재시도하지 않는다.

### 이 변경의 다음 한 작업

이 terminal 기록을 포함한 새 Map revision, PinVi `admin`·`full` provenance revision, Manager source를 새 atomic
pinset으로 만든다. 최신 CI, 전문 적대 리뷰 두 건, registry/public-copy 무결성이 모두 정합할 때만 새 root-owned
output leaf에서 n150 M04/M05 isolated E2E를 정확히 한 번 실행한다.

## 2026-08-28 — terminal `fa28a6e7…` 보존, safe-result envelope 보강 준비

Map `f90b7c28…`·PinVi `fdff06ba…`·pinset `fa28a6e7…`은 trusted Manager `b45f54d5…` release의
registry/public-copy 검증 뒤 n150 isolated M04/M05 launcher에서 정확히 한 번 실행됐다. launcher는 exit 1이었고
허용된 durable safe result는 없었다. 원문 HTTP·컨테이너·환경 출력과 output leaf는 읽지 않았으며, 후속 `pin verify`가
terminal 차단을 확인했다. 이 pinset·Manager source·output leaf는 `a3f6a8f3…`·`22563762…`·`c700bd2e…`와 함께
절대 재시도하지 않는다.

### 이 변경의 다음 한 작업

이 terminal 기록을 포함한 새 Map revision과 PinVi `admin`·`full` provenance revision을 먼저 만들고, Manager가
safe result 부재도 원문 없이 고정 enum으로 보존하도록 새 source를 만든다. 최신 CI, 전문 적대 리뷰 두 건,
registry/public-copy 무결성이 모두 정합할 때만 새 atomic pinset과 새 root-owned output leaf에서 n150 M04/M05
isolated E2E를 정확히 한 번 실행한다.

## 2026-08-28 — terminal `c700bd2e…` 보존, fresh source pair 대기

Map `bbb29d177…`·PinVi `663e21b4…`·pinset `c700bd2e…`은 trusted Manager `4a6e1b0…` release의
registry/public-copy 검증 뒤 n150 isolated M04/M05 launcher에서 정확히 한 번 실행돼
`map_health_http_failed` terminal로 차단됐다. cleanup은 통과했고 원문 HTTP·컨테이너·환경 출력은 읽지 않았다.
이 pinset·Manager source·output leaf는 `a3f6a8f3…`·`22563762…`와 함께 절대 재시도하지 않는다.

### 이 변경의 다음 한 작업

새 Manager source와 이 terminal 기록을 포함한 새 Map revision·새 PinVi `admin`·`full` provenance revision을
atomic pinset으로 함께 회전한다. 최신 CI, 전문 적대 리뷰 두 건, registry/public-copy 무결성이 모두 정합할
때만 새 root-owned output leaf에서 n150 M04/M05 isolated E2E를 정확히 한 번 실행한다.

## 2026-08-28 — terminal `22563762…` 보존, HTTP 단계 분류 candidate 준비

Map `b8d108bd…`·PinVi `50c875f5…`·pinset `22563762…`은 registry/public-copy gate 뒤 n150 isolated
M04/M05 launcher에서 정확히 한 번 실행돼 `runtime_http_failed` terminal로 차단됐다. cleanup은 통과했고
원문 HTTP·컨테이너·환경 출력은 읽지 않았다. 해당 pinset·Manager source·output leaf는 절대 재시도하지 않는다.

### 이 변경의 다음 한 작업

Manager #253의 호출 단계별 고정 HTTP 분류 보정과 이 Map 기록 revision, PinVi 후속 `admin`·`full`
provenance revision을 새 atomic pinset으로 회전한다. PinVi 최신 CI와 전문 적대 재리뷰 두 건,
registry/public-copy 무결성이 모두 정합할 때만 새 root-owned output leaf에서 n150 M04/M05 isolated E2E를
정확히 한 번 실행한다.

## 2026-08-28 — terminal a3 candidate 보존, 새 immutable pair 준비

Map `e6c08e25…`·PinVi `932fb140…`·pinset `a3f6a8f3…`은 n150 isolated launcher의 installed-wheel
project-root preflight에서 terminal 처리됐다. Docker·Compose·DB·driver ledger 전이었지만 해당 one-shot
candidate와 output leaf는 root registry에 차단됐고 절대 재시도하지 않는다.

### 이 변경의 다음 한 작업

Manager #253의 trusted `python -I` `sys.prefix` 회귀 보정과 이 Map 기록 revision·PinVi 후속 provenance
revision을 새 atomic pinset으로 회전한다. PinVi CI, 두 전문 적대 재리뷰, registry/public-copy 무결성이 모두
정합할 때만 n150 M04/M05 isolated E2E를 정확히 한 번 실행한다.

## 2026-08-28 — M05 Manager runtime pin registry 순서 반영

Docker Manager #251은 Map·PinVi source revision과 terminal candidate lifecycle을 source 상수가 아니라
trusted release 밖 root-owned runtime pin registry로 이관했다. 이후 보안 재리뷰 P1을 반영한 Manager
PR #253 source `02cc8de…`에서 Map `e6c08e25…`와 PinVi `932fb140…`은 read-only seed를 수정하지 않고 `pin init` 뒤
atomic `pin rotate-pair` 한 번으로 재결박한다. seed의 `cbb577d3…`은 terminal historical evidence로 보존하고, final pinset
`a3f6a8f3…`만 새 `(Manager revision, pinset)` one-shot ledger candidate가 된다.

### 이 변경의 다음 한 작업

Manager PR #253의 exact source를 trusted n150 isolated 환경에 설치한 뒤 registry의 root/공개 사본
무결성과 final pinset을 확인한다. 그때만 M04/M05 live E2E를 정확히 한 번 실행한다. source의 seed,
static image digest, terminal candidate는 수정·추측·재실행하지 않는다.

## 2026-08-28 — M05 PostGIS digest 고정 병합과 다음 provenance 회전

`29fbcdd…` isolated candidate는 Map fresh-init에서 `baseline_reference_invalid`로 terminal 처리됐으며
재실행하지 않는다. Map `9c64e862…`의 `application-reference.json`과 모든 tracked baseline
sidecar를 다시 정적으로 대조한 결과, manifest·sidecar·SQL artifact byte hash는 정합했다.

원인은 application baseline이 고정한 PostGIS immutable image와 실제 n150 Compose가 사용한 부동
`postgis/postgis:16-3.5-alpine` 태그가 서로 다른 image identity를 가리킨 데 있다. 이 차이는
catalog receipt를 달라지게 할 수 있으며, 이미 통합 fixture가 같은 drift를 방지하려 source digest를
사용하고 있다. Map Compose도 baseline reference의 exact digest를 사용하도록 고정한다.

### 이 변경의 다음 한 작업

전문 적대 리뷰 두 건과 모든 CI를 통과한 Map PR #1099는 `e6c08e2598a6f8b6fda605be271e8d384213de58`로
병합됐다. 이 revision의 paired application candidate를 PinVi `admin`·`full` provenance와 Manager
runtime pin registry의 atomic pair rotation으로 재결박한다. 새 root-owned one-shot candidate에서만 n150 isolated
M04/M05 live mutating E2E를 정확히 한 번 실행하며, 성공 전에는 PinVi·Manager 코드 PR을 merge하지 않는다.

## 2026-08-28 — M05 scoped external membership cleanup generation committed

사용자의 완주 지시에 따라 target 밖 stale membership cleanup은 Manager root-owned v2 permit에
`revoke_external_memberships` scope가 있을 때만 수행한다. permit은 transaction·pinset·PinVi DB identity에 결박되며,
PinVi는 target→external 및 external→target 두 edge를 실제 PostGIS에서 검증해 target membership만 제거하고 external
role은 보존한다. Manager `519edd9…`, PinVi `69a5ac65…`, Map `9c64e862…`의 pinset `030b12fc…`은 trusted n150
release에서 정확히 한 번 실행돼 committed 됐다. seven-runtime generation과 Map application `300`·Map Dagster·PinVi
`20260824_0101` schema head를 함께 확인했다. 이 generation의 exact Map source/image identity를 PinVi
current main rebase를 반영한 PinVi `41a36ee6…`과 Manager pinset `c1ad5a3e…`은 root-owned structured result launcher로 정확히 한 번 실행돼 committed 됐다(generation `8eedf171…`, Map application `300`, Map Dagster `29b539ebc72a`, PinVi `20260824_0101`). `6269138f…`은 durable journal/manifest를 남기지 못한 pre-journal 단회 시도로 보존하며 raw stderr를 읽지 않고 재실행하지 않는다. `53d4639f…`은 installed launcher execute bit 미보존으로 admission 이전에 종료했으므로 durable output·ledger·raw stderr 없이 재실행하지 않는다.

### 이 변경의 다음 한 작업

committed `c1ad5a3e…`의 exact Map/PinVi immutable pair로 isolated M04 승인 → Map `rebind` 결정 → PinVi terminal receipt/Map ACK의 live mutating E2E 및 서명
activation attestation을 실행한다. 이 증적과 두 코드 PR의 최신 CI·승인이 모두 성공하기 전에는 코드를 merge하지 않는다.

## 과거 기록 아카이브

> 현행 작업 창(2026-08-28~) 이전 기록은 아래로 분리했다. 검색은
> `rg <패턴> docs/archive/` 로 한다. 새 엔트리는 항상 이 파일 상단에 추가한다.

| 파일 | 기간 | 엔트리 | 크기 |
| --- | --- | --- | --- |
| [`resume-2026-08a.md`](archive/resume-2026-08a.md) | 2026-08-04 ~ 2026-08-27 | 156건 | 199 KB |
| [`resume-2026-08b.md`](archive/resume-2026-08b.md) | 2026-08-01 ~ 2026-08-04 | 25건 | 36 KB |
| [`resume-2026-07a.md`](archive/resume-2026-07a.md) | 2026-07-26 ~ 2026-07-31 | 52건 | 102 KB |
| [`resume-2026-07.md`](archive/resume-2026-07.md) | 2026-07-01 ~ 2026-07-24 | 128건  | 162 KB |
| [`resume-2026-06.md`](archive/resume-2026-06.md) | 2026-06-13 ~ 2026-06-30 | 76건   | 86 KB  |
