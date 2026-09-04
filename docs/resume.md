# resume.md — 현재 진척도와 다음 한 작업

## 2026-09-04 — 사이클을 태우던 원인이 제거됐다, 다음은 barrier 판정

map task가 오래 진전하지 못한 직접 원인은 코드 결함이 아니라 **재시도 불가**였다.
격리 e2e가 봉인된 핀 소스 worktree를 오염시켜, 통과하든 실패하든 같은 pinset을 다시
돌릴 수 없게 만들었다(2026-09-03·04 연속, 각 약 1.5시간). Manager #315가 실행 루트를
일회용 체크아웃으로 옮겨 이것을 끝냈고, `e2e025`가 통과한 뒤에도 봉인 트리는 깨끗하다.

| 항목 | 상태 |
|---|---|
| pinset | **`e6b52db4`** = Map `8078b110` + PinVi `357da189` |
| Manager 설치본 | `b3217edc` (execution identity `148f76b1`) |
| 격리 M04/M05 live E2E | **passed** (`e2e025`) — m04 `f08620a9…`, m05 `37320bb5…`, provenance `25a80946…` |
| 봉인 트리 | 실행 후에도 `_validate_immutable_tree` ACCEPT (pinvi/map) — **같은 pinset 재실행 가능** |
| Map #1142 프로덕션 Dockerfile CI 빌드 | 머지 `cac35134` (job 13분 55초 pass) |
| Map #1144 T-CI-DOCKERFILE-BUILD 종결 | 머지 `f549fc28` |
| Manager #315·#316 | 머지 `b3217edc`·`a326d066` |

### 다음 한 작업

**`T-VN-FINAL-REBUILD`의 B4 재판정** — 이것이 열리기 전에는 `T-VN-41F1D-D1`을 닫을 수
없다. D1의 해제 조건이 "barrier가 현재 candidate를 유지한다고 판정한 뒤 실행"이라고
명시하고, D1이 요구하는 일곱 image ID·schema head 대조는 격리 e2e attestation이 아니라
**generation attestation**의 산출물이기 때문이다. 이번 실행은 그 판정을 대신하지 않는다.

barrier가 열리면 순서는 `T-VN-41F1D-D1` → `D2` → `T-VN-41C` → `T-VN-41F1D-E`다.
`GM-17`(Manager production compose required-set 완화)은 소유자 지시로 **가장 마지막**이다.

### 열려 있는 소유자 판정 (원장 중복)

착수 전 정리가 필요한 중복이 넷 있다. 전부 보고했고 고치지 않았다 — 어느 쪽을 정본으로
둘지가 판정이기 때문이다.

- `T-VN-M04` ↔ `T-VN-41C`
- `T-VN-M05` / `T-VN-41C` / `T-VN-M05-ACTIVATION` 삼중 계상
- `T-VN-H49` 부모/자식 이중 계상
- `T-VN-H49-OFFBOX` ↔ `T-VN-H43`


## 2026-09-03 — 침묵사 셋을 걷어내고 e2e가 본문까지 갔다, 다음은 계약 재핀

격리 e2e 두 번과 pinned rebuild 한 번이 **로그 0바이트**로 사라지던 것을 걷어냈다.
관측(`systemd-run` + journald)과 실행권 소각(claim 재취득)을 고치자 e2e21이 처음으로
Map 9 + PinVi 7 컨테이너를 모두 띄우고 M04/M05 본문까지 갔다. 거기서 만난 것이 다음
벽이고, 그 벽은 이제 고쳐졌다 — 상세는 `docs/journal.md` 최신 항목.

| 항목 | 상태 |
|---|---|
| Map #1137·#1138·#1139 | 머지 완료 — main이 며칠 만에 완전 green |
| Map #1140 `/v1/debug` 표면 제거 | CI 대기 |
| PinVi #522~#524 | 머지 완료 |
| PinVi #525 계약 생성기 봉투 보존 | CI 대기 |
| Manager #308·#309·#310 | 머지 완료 |
| pinset | **`03562bba`** = Map `f58de9f4` + PinVi `170636f9` (rebuild 완료, generation `match`) |

### 다음 한 작업

**Map #1140을 머지한 뒤 PinVi 재벤더 → pinset 회전 → rebuild → e2e** 순서다.
순서를 건너뛰면 e2e가 정확히 어디서 죽는지까지 적대 리뷰가 예측해 뒀다:

1. Map #1140 머지 → 새 Map revision.
2. PinVi 재벤더 — `apps/api/tests/contract/kor-travel-map-openapi-admin.json`,
   `apps/api/tests/unit/_kor_travel_map_snapshot_pin.py`의 `UPSTREAM_COMMIT`·
   `SNAPSHOT_SHA256`, `test_kor_travel_map_admin_contract.py`의 중복 리터럴,
   그리고 `contracts/kor-travel-map-m05-pair-provenance-v1.json`의 `admin`·`full`
   10개 필드.
3. `rotate-pinned-pair <새 Map> <새 PinVi> "<사유>"` → `run-pinned-rebuild-once`
   → `run-m05-isolated-e2e-once`.

**`generate_m05_pair_contract.py --write`는 #525 머지 전에는 쓰지 말 것** — 그 전
버전은 v2 봉투를 쓰고, PinVi API는 `version == 1`을 모듈 스코프에서 요구하므로
71분짜리 rebuild를 태운 뒤 컨테이너가 뜨지 않는다.

**긴 원격 작업은 `systemd-run --unit=...`으로 띄울 것.** `python -I`가 `-E`를
함의해 `PYTHONUNBUFFERED`가 무효이고 런처가 stdout을 따로 돌리므로, 로그인 세션에
매달아 두면 죽었을 때 아무 기록도 남지 않는다(2026-09-03 침묵사 3회).

---
## 2026-09-02 — rebuild 재실행 중, 다음은 e2e17

보류가 풀려 실행에 들어갔다. 첫 rebuild가 실패했고 그 실패가 결함 두 개를
드러냈다 — 상세는 `docs/journal.md` 최신 항목.

| 항목 | 상태 |
|---|---|
| Manager #302 `ec27f65d` | 머지·설치·3단계 검증 완료 |
| PinVi #518 `448f6a3e` | 머지 완료(`docker-image` job 신설, required) |
| pinset | **`4516a107`** = Map `f58de9f4` + PinVi `448f6a3e` |
| `pin verify` | `execution_binding: current`, `pair_rotation: idle` |
| rebuild | 12:34 UTC 시작, 진행 중 |

### 다음 한 작업

rebuild 성공 확인 → `run-m05-isolated-e2e-once ec27f65d… /root/m05-once-017`.

실패하면 `result.json`의 `stage`(+ `candidate_compose_build`면 `service`)가
지점을 짚는다. **원문을 캐려고 플래그 없는 `rebuild-pinned --confirm`을 돌리지
말 것** — 그건 진단이 아니라 전체 destructive 재시도이고 원장에 claim을 남기지
않는다(Manager `docs/runtime-pin-registry.md` §9).

---

## 2026-09-02 — e2e17 사전조치 완료, 실행은 보류(소유자 지시)

소각 경로 수리를 마치고 n150 재설치까지 끝냈다. **실행(rotate-pair → rebuild →
e2e17)은 소유자 지시로 보류** — PinVi·Manager의 신규 PR 머지가 끝난 뒤 진행한다.

### 이번에 닫은 소각 경로 (Manager #297/#298)

적대 리뷰 2인 + `tasks.md` 후속 조사가 같은 결함 클래스의 인스턴스를 다섯 개 더
찾았다. 원칙 하나로 정리했다 — **launcher는 실행권이 소비됐다는 양성 증거가 있을
때만 태운다.**

| 결함 | 결과 |
|---|---|
| 디렉터리 fsync 실패가 전파돼 **통과한 실행**이 무조건 소각 | 파일은 이미 durable한데 driver가 1을 반환해 Tier 1이 걸렸다. `_unlink_private` 쪽은 launcher를 거치지도 않고 driver가 직접 소각 |
| 관측 실패가 receipt를 읽지도 않고 소각 | 첫 수정은 "읽지도 않고 **안** 태운다"로 방향만 바꿔 본문 이중 실행을 열었다(리뷰 blocker). 최종: 게이트만 무효화하고 receipt는 항상 읽는다 |
| `{0,3,4,5}` 외 **모든 값**이 소각 (126/127/137/미포착 예외) | `case`로 통합. receipt를 못 읽으면 driver가 claim 직후 남기는 root 0600 마커로 소비 여부를 판정 |
| ktdctl 딸꾹질이 "기록 없음"으로 접혀 scoped 차단을 무조건 소각으로 승격 | 두 헬퍼를 tri-state로(있음/없음/판독 불가) |
| `pin block-execution` 실패가 `set -e`에 먹혀 fallback 봉투에도 도달 못 함 | 상태 포착 + 명시 진단 |

### GM 트랙 신규 기능 조사 (소유자 지시)

`secure_state_file.fsync_directory`(GM-10)가 정본화한 규칙을 채택했다 —
"이 단계의 실패로 이미 끝난 파일 교체를 실패로 되돌리면 안 된다". 함수를 직접
쓰지는 **않았다**: driver 쪽 open이 `O_DIRECTORY|O_NOFOLLOW`로 더 강해 바꾸면
하향 평준화다(그 모듈 자신의 docstring이 세운 잣대).

**13건은 "하지 말 것"으로 닫았다.** 특히 `compose_service` 채택은 소각을 부를
뻔했다 — `registry.py`가 import 시점에 `docker-targets.yml`을 여는데 driver는
ktdctl shim을 거치지 않아 **phase도 receipt도 없이 import에서 죽는다**.

### e2e17 사전조치 (완료)

1. Manager `1e2c49fa` 재설치 — origin/main → clone → 설치본 3단계 모두 grep 검증
2. 백업 크론과 시간 충돌 없음(03:15/03:55 UTC, 실행 직전 재확인)
3. Map python base `57cd7c3a` · Playwright runner `dcc5531e` 둘 다 n150에 존재
4. `pin verify`는 `manager_drift` — 예상된 상태이고 `rotate-pair`가 해소.
   stale rotation intent 없음, execution `terminal: False`
5. output leaf는 `/root/m05-once-017` — STATE_ROOT 아래 두면 off-box rsync가
   forensic leaf와 미정리 credential을 원격에 영구 복제한다

### 다음 한 작업

**PinVi·Manager 신규 PR 머지 완료 대기.** 그 뒤 `pin rotate-pair`(Map `d325f541` +
새 PinVi revision) → `run-pinned-rebuild-once` → **e2e17**.


## 2026-09-02 — 공허 게이트 차단 + 참조 짝 불변식, e2e17은 아직 이르다

하네스 3종이 선 뒤 "이제 태워도 되는가"를 점검하다 **e2e를 태워도 핵심을 증명하지
못한다**는 것을 발견했다. 격리 fixture가 Map 쪽 provider feature만 만들고 PinVi에
참조 행을 한 줄도 만들지 않아 `impact_count`가 구조적으로 0이고, 그러면 live spec의
중심 단언 `expect(impacts).toHaveLength(0)`이 공허하게 참이 되어 **per-impact 단언
본문이 한 줄도 실행되지 않는다.** 배관이 도는 것만 증명하고 pinset 하나를 태우는
셈이었다.

### 머지 (Manager #296 · PinVi #513/#514)

- **#296**: Map decision 커밋 직전에 PinVi에 참조를 심는다. 일부러 일상적인 사용자
  경로(`POST /trips` → `POST .../pois`)를 써서 `feature_uuid`가 NULL인 행을 만든다 —
  리바인드가 legacy 축만 있는 행을 처리하는지까지 같이 증명된다. `impact_count`가
  심은 수보다 적으면 `m05_pinvi_impact_missing`으로 죽는다.
- **#514**: PinVi reconciliation이 "UUID shadow가 NULL"을 "값이 어긋났다"로 읽어
  평범한 행 하나가 피드를 영구히 세우던 결함. 적대 리뷰 2인이 **정반대 방향의 결함을
  하나씩** 잡았다 — 한쪽은 미검증 client 문자열로 canonical UUID를 주조하던 것,
  다른 쪽은 canonical UUID 일치를 conflict로 막던 것. 최종 규칙: UUID 일치 → 리바인드
  (주조 없음) · UUID NULL → legacy 축 판정(주조 없음) · UUID가 다른 feature → block.
- **#513**: playwright image 도메인이 세 선언 중 하나만 tag 필수였던 것.

### 하네스가 값을 했다

#296을 넣자 full-path 시뮬레이션이 **즉시 17건 실패**로 잡았고, 고치는 과정에서 제
`phase` 대입이 본문 phase를 강등시켜 무조건 소각 표면을 깨뜨린다는 것까지 드러났다.
전부 실행 없이 잡혔다.

### 다음 한 작업

**남은 이중 선언 결박 → Manager release 재설치 → `pin rotate-pair` → rebuild → e2e17.**
PinVi 활성화 게이트는 별건으로 분리했다(impact before-image 정직성·blocked 상세 평문
보존은 DB 컬럼이 필요해 alembic 핀에 걸린다. worker는 꺼져 있고 prod 세 테이블은
실측 0행).


## 2026-09-01 — 시뮬레이션 하네스 3종 도입, e2e 없이 blocker 5건 선적발

M05 isolated one-shot 1회가 pinset 소각 + 1~2시간이라, **실행 없이 코드 레벨에서
계약을 검증하는 하네스 3종**을 세워 소각 전에 결함을 잡는 체제로 전환했다.

- **하네스 A**(Manager `test_m05_isolated_e2e_full_path.py`, #294) — mini Compose
  렌더러 + fake docker/HTTP로 driver 전 경로를 실행. launcher heredoc을 추출해
  receipt 검증기까지 같은 프로세스에서 재현한다.
- **하네스 B**(Map `test_tvn_m05_provider_bundle_dedup_scenario.py`, #1132 머지됨)
  — CI PostGIS job에서 M05 DB 시나리오 전체를 실 DB로 재생한다.
- **하네스 C**(PinVi `test_m05_attestation_map_contract_simulation.py`, #512 머지됨)
  — attestation ↔ Map 계약을 실행 없이 대조한다.

셋 다 mutation testing으로 비-vacuous를 확인했다(A는 과거 결함 13건, C는 34개
mutation 중 11건 적발).

### 이번에 선적발한 결함

`AGENTS.md`가 쫓는 **이중 선언**(같은 사실이 두 곳에 따로 선언되고 둘을 잇는
기계가 없음) 클래스가 대부분이었다.

| 결함 | 소각 여부 |
|---|---|
| `PINVI_M05_LIVE_E2E` 미주입 → spec이 `beforeAll`에서 중단 | 소각 |
| isolated에서 `reviews.json`/`restore.json` 강요 → UI green 후 봉인 실패 | 소각 |
| receipt 단발 GET → worker polling 창에서 404 | 소각 |
| pre-claim phase 집합이 driver/launcher에서 갈라짐 | 소각 |
| `map_fresh_init_reason` 자유형 진단 → launcher 검증 ValueError → pinset 소각 | 소각 |
| playwright image 도메인이 세 선언 중 하나만 tag 필수 | 잠재 |

### 다음 한 작업

**Manager #295·#294 머지 → Manager release 설치 → `pin rotate-pair` → rebuild →
e2e17.** 별건으로 PinVi identifier 짝 불변식(`trip_day_pois`/`curated_plan_pois`/
`feature_suggestions`에 pair CHECK 부재)과 isolated `impact_count` 구조적 0
(리바인드 증명이 공허) 조사 중.


## 2026-09-01 — e2e16: m04 UI 완주 + dedup 계약 비정합 적발 → 303

식별자 축 짝 수정(#291/#509) 검증 완료 — e2e16이 m04 Playwright UI 흐름을
재완주하고 한 층 더 깊은 Map 스키마 결함(사본 hash 도메인)을 적발했다.

### 다음 한 작업

**#1131(303) 머지 → PinVi pair revision 재핀 → rotate → rebuild →
e2e17.** 남은 미지 표면: m05 rebind UI 흐름 + receipt 서명.

## 2026-09-01 - e2e13 본문 진입, runner 이미지 소각 후 새 pinset 준비

M05 isolated one-shot이 역대 최초로 본문에 진입했다(journal 참조). body
실패는 무조건 소각이므로 새 pinset이 필요하다 - 이 문서 커밋이 새 Map
revision을 만든다.

### 다음 한 작업

rotate-pair(Map=이 커밋 머지, PinVi c402a80b) -> run-pinned-rebuild-once
-> run-m05-isolated-e2e-once(e2e14). Manager는 #289(runner digest claim 전
보장)까지 설치/rebind.

## 2026-08-31 — M05 rebuild 연쇄 수리 2건: #1128(packaging) → #1129(permit)

pinset 재회전(Map 58158472 / PinVi e0750505) 후 rebuild가 candidate·계약 단계를
전부 통과하고 fresh finalize까지 완주했으나, permit 검증기의 반쪽 head-인지
(evidence 블록)로 API/Dagster 기동이 거부됐다. #1129(head-인지 정렬 + beyond-root
테스트)가 draft로 떠 있고 적대 리뷰 2인 approve, 반영 완료.

### 다음 한 작업

**#1129 CI green → 머지 → 새 Map revision으로 `pin rotate-pair` → rebuild →
`run-m05-isolated-e2e-once` 1회.** 후속(리뷰 유래): head별 destination catalog
재컷으로 봉인 대조 복원, Manager 쪽 evidence↔receipts 교차 검사 대칭.

## 2026-08-31 — M05-ACTIVATION 재개: 회전 완료, rebuild는 packaging에서 실패 → #1128

Manager trusted release(main 5f70770d) 설치 + `ktdctl pin rotate-pair`(Map 13407ba9 /
PinVi e0750505, 이전 pinset block) 완료 — `pin verify` rc=0. `run-pinned-rebuild-once`가
`application_builder`에서 prejournal 실패했고, 근본원인은 `_provider_surface.json`
package-data 미등록(wheel 누락)이다. #1128(fix + sealed runtime tree 선적 lint)이
draft로 떠 있다. n150에서 sealed builder를 fix 커밋으로 재실행해 green을 확인한다.

### 다음 한 작업

**#1128 머지 → 새 Map revision으로 `pin rotate-pair` 재회전 → `run-pinned-rebuild-once`
재실행 → 성공 시 `run-m05-isolated-e2e-once` 1회 실행.** infra 실패는 phase-scoped
record로 남으니 같은 pinset으로 재시도 가능하다. one-shot green이면 T-VN-M05-ACTIVATION
승격 조건(최신 CI·적대 리뷰 2건·비-terminal)을 판정한다.

## 2026-08-31 — M03 child 발급(302) 구현·실 DB green, 다음은 격리 live acceptance

`chain/301-carrier`(#1125)와 Manager `chain/head-state-receipt`(#277)를 live e2e
green(8/8, prod build) 후 함께 머지했다. 그 위에서 `feat/m03-child-command-issuance`가
CSV category 열 → 302 migration → repo/route 결선 → 통합 테스트 완주까지 담는다.

### 다음 한 작업

**M03 격리 live acceptance** — manual 행이 든 CSV를 admin UI(또는 BFF 경로)로
preview→plan→commit까지 실제 스택에서 한 번 완주시키고, linkage/summary를 증거로
남긴다(사상 첫 manual-create 격리 harness — n150 ~/ktm-live-301 스택과 c7-playwright
이미지를 재사용할 수 있다). 그 전에 적대 리뷰 2인(opus5·xhigh)이 302/발급 경로를
다각도로 친다.

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
