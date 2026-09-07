# resume.md — 현재 진척도와 다음 한 작업

## 2026-09-06 — D2 lane이 api-audit까지 완주했다

| 항목 | 상태 |
|---|---|
| pinset | Map `631f1abc` + PinVi `b9637375` |
| `T-VN-D2-API-AUDIT` | **완료** — `ktdm-d2-008` `phase: passed`, runner exit 0 |
| lifecycle | 56 = 7 operation × 8 phase (`helper-api-audit` 8개) |
| evidence | `phase: evidence-validated`, 파일 집합 exact, FK 제약 18, 리포트 2 |
| api-audit | counts 3·1·7·3, FK 18/8, `feature_ids`·`feature_uuids` 각 1건 |
| 선행 축 | ACL preflight 55/55, D1 11 passed |

`feature_id` 규칙은 서로 다른 실행이 만든 Feature **셋**으로 배포 DB에서 확인했다 —
새 규칙(uuid 재현) 3/3 일치, 구 규칙(run_id 재계산) 3/3 불일치.

### 다음 한 작업

**`T-VN-PAIR-V2` §6 — 회전 → rebuild → 격리 M05 e2e.** §1~§4는 닫혔고 §5는 정적으로
성립한다(Map main이 pinned에서 4커밋 앞섰는데 세 표면 blob이 바이트 동일 — v1이었다면
71분 rebuild가 따라왔을 자리다). 남은 것은 실행 증명 하나다.

**머지 순서가 강제된다**: `kor-travel-docker-manager#321` → Manager 배포 →
`pinvi#539` → 회전. Manager main이 P0-2 결함을 갖고 있어 PinVi가 먼저 머지되면 71분
rebuild 뒤 PinVi가 기동에 실패한다. 근거는 `docs/tasks-acceptance.md` §T-VN-PAIR-V2.

<!-- 아래는 2026-09-07 §3 선행 조사 기록이다 -->
**종전: `T-VN-PAIR-V2` §3의 선행 — attestation의 Map revision 생산자 배선.** §1·§2는
2026-09-07에 닫혔다(PinVi #538, pinset `78cad481…`에서 배포 컨테이너로 실증). §3은
해제 조건이 적지 않은 선행 하나에 걸려 있다: `m05_activation_attestation.py`가
`source_revision`을 `git show`의 revision 인자로 쓰므로, 계약에서 그 필드를 빼려면 그
값을 줄 생산자가 먼저 있어야 한다. **대체 생산자는 이미 존재한다** — 격리 envelope의
`map.source_revision`(Manager가 pin registry에서 만든 값)이고, 배선만 없다.
자세한 순서는 `docs/tasks-acceptance.md` §T-VN-PAIR-V2의 "진행 상황"이 갖는다.

<!-- 아래는 이 항목을 고른 근거다 -->
**`T-VN-PAIR-V2`** — PinVi의 M05 pair 계약을 v2로 올려 **Map revision의 이중 선언을
없앤다.** 41C는 2026-09-07 소유자 판정으로 **보류**다(실 production 전환까지 enable 유예 —
현 lifecycle에서 enable과 pinned rebuild가 상호배타라 rebuild 능력을 잃는 값이 맞지 않다).

PAIR-V2를 다음으로 두는 이유는 **비용을 이미 값으로 치렀기 때문**이다. 2026-09-01 이후
Map 변경으로 강제된 PinVi 재핀은 **12건**이고 **12건 전부가 rebuild를 끌고 왔다**. 그중
**10건은 상류 admin OpenAPI가 바이트 동일한 채 revision 라벨만 옮긴 것**이다(상류 blob
sha256이 12개 핀에 걸쳐 두 값뿐이었다). 2026-09-06 하루만 봐도 4건이다 — 이 줄이 종전에
"두 번"이라 적었던 것은 오기다(2026-09-07 실측 정정).

Manager는 이미 v1·v2를 dual-read하고 **그것이 n150에도 배포돼 있다**. PinVi 생성기도 이미
v2를 계산하지만 `_in_committed_envelope`가 커밋된 v1 봉투로 되돌린다 — 그 되돌림은 커밋된
JSON이 v2가 되는 순간 **스스로 무장해제**되므로 생성기 변경은 순서상 마지막이다.

막고 있는 것은 **소비자 셋**이다(원장이 종전에 하나라고 적었다):
`apps/api/app/core/config.py`(모듈 스코프 `version == 1` — 계약만 뒤집으면 컨테이너가
**기동에 실패**한다, 실측 재현), `scripts/m05_activation_attestation.py`,
`scripts/m05_activation_receipt.py`.

`GM-17`은 소유자 지시로 **가장 마지막**이다.

### 이번에 배운 것

- **흔적을 남기지 않는 실패는 진단을 한 겹 멀게 한다.** supervisor의 argparse
  `--helper-action` choices에 새 action이 빠지면 exit 2로 죽는데, 그것은 lifecycle도
  출력 파일도 쓰기 **전**이다. lane 실패는 "owned fixture cleanup left residue"라는
  엉뚱한 곳을 가리켰고 실제 잔여물은 0이었다. 이제 CI 게이트가 그 다섯째 결선 지점을
  러너 호출부에서 유도해 결박한다.
- **pinned rebuild는 application DB를 새로 만든다.** 이전 실행이 남긴 Feature는 다음
  rebuild에 사라진다 — "suppressed 행이 쌓인다"는 종전 debt 서술은 사실이 아니었다.


## 2026-09-06 — D2 통과, receipt 승격

| 항목 | 상태 |
|---|---|
| `T-VN-M01` 활성화 | **완료** — ACL 55/55(rebuild 앞뒤 두 번) · 거부 축 4/4 403 · witness 8관계 zero-write · 성공 축 201 |
| kill-switch | `KOR_TRAVEL_MAP_API_ADMIN_MANUAL_FEATURE_CREATE_ENABLED=true` (2026-09-05T20:27:59Z) |
| D2 스펙 | **in-lane 통과** — main·recovery 각 `{"counts":{"passed":2},"result":"passed"}` |
| `T-VN-41F1D-D2` | **통과** — `phase: passed` / `status: complete` (2026-09-06T01:47:03Z, runner exit 0, 1분 43초) |
| D2 증거 | `phase: evidence-validated` — 파일 집합 exact(10), lifecycle 48, FK 제약 18, 리포트 2 |
| D2 잔여물 | 독립 측정으로 0 — acceptance 소유 row 0, 라벨 컨테이너 0, BLOCKED/ACTIVE/RESULT 없음 |
| 선행 축 | 같은 pinset에서 ACL preflight 55/55 · D1 11 passed(29.9초) |
| 게이트 | 결함마다 `tests/lint/` 탐지기, 전부 변이로 red 확인 |
| pinset | Map `ab3640f8` + PinVi #535 — rebuild `48166bd2…`, generation `56d331a7…` |

### 다음 한 작업

**`T-VN-41C`의 구조적 순환에 대한 소유자 판정.** 선행 배리어는 전부 닫혔다 — D1·D2·
`T-VN-41F1D-E`·`T-VN-M01` 완료. 41C의 relay·reconciliation은 **구현이 끝나 있다**(2026-09-06
재조사가 종전 서술을 정정했다). 남은 셋 중 앞의 둘은 셋째가 풀리기 전에는 착수할 수 없다:

1. **런타임 결선** — 배포 Map 컨테이너에 `..._CACHE_TARGET_SERVICE_PRINCIPALS`가 없어 service
   표면이 401이고 relay 관계 19개가 전부 0행이다.
2. **enable 경계 구현** — PinVi가 production에서 sync enable을 거부하며, 그 조문이 기다리는
   "root-owned final C7 enable boundary"가 Manager에 없다.
3. **구조적 순환** — 켜면 `environment_sha256`이 바뀌어 rebuild가 필요한데, Manager
   `require_rebuildable_mode`는 cache-target 값이 inert여야 rebuild를 허용한다. **현
   lifecycle(rehearsal/rebuildable)에서 enable과 pinned rebuild는 상호배타다.**

셋 중 하나를 골라야 한다 — (a) lifecycle을 옮긴다, (b) Manager가 cache-target 축을
`environment_sha256` 결박에서 분리한다, (c) enable을 실 production 전환 시점까지 미룬다.
(a)는 rebuild 능력을 잃고, (b)는 Manager 계약 변경이며, (c)는 41C를 그때까지 여는 것이다.
`docs/tasks.md`의 41C 줄과 `tasks-acceptance.md` §T-VN-41C가 정본이다.

`GM-17`은 소유자 지시로 **가장 마지막**이다.

그 뒤 순서는 **`T-VN-41F1D-E` → `T-VN-41C`**다(2026-09-06 정정 — 이 줄이 순서를 뒤집어
적고 있었다). `GM-17`은 소유자 지시로 **가장 마지막**이다.
`T-VN-D2-API-AUDIT`(helper의 `api-audit`/`purge` 경로가 한 번도 실행된 적 없음)은 D2 완주와
분리했다 — 고치려면 clone lane의 content digest 계약까지 함께 판단해야 한다.

### 이번에 확인된 운영 사실

- **증거 계약 위반은 스펙이 통과한 뒤에야 드러난다.** `_validate_evidence`가 정확한
  파일명 집합과 action별 키를 요구하는데 그 검증이 스펙 통과 뒤에 돌기 때문이다. 그래서
  결함이 병렬로 안 보이고 배포 스택 실행 한 번에 하나씩 직렬로 나온다 — 열두 번을 그렇게
  썼다. 게이트를 로컬에서 유도해 미리 깨뜨리는 것이 그 비용의 유일한 대안이다.
- **executor 이미지를 같은 `:local` 태그로 다시 빌드하면 핀이 가리키던 이미지가 사라진다.**
  live attestation이 image ID를 exact로 들고 있어 재빌드 순서를 지켜야 한다.
- **`rolinherit=false`라 privilege 확인에 `::regclass`를 쓸 수 없다.** Map 역할 전부가
  NOINHERIT이므로 preflight는 catalog join으로만 판정한다.


## 2026-09-05 — 새 pinset에서 D1 통과, D2는 helper 결함 셋을 고치고 재실행 대기

`af6d7061`(Map `c72456f6` + PinVi `f4401659`)로 rebuild를 마쳤고, attestation을 재발행해
verifier가 PASS했다. D1은 통과했다. D2는 seed에서 죽었고 원인 셋을 전부 고쳐 실 DB에
대고 seed → cleanup → audit을 통과시켰다.

| 항목 | 상태 |
|---|---|
| pinset | **`af6d7061`** = Map `c72456f6` + PinVi `f4401659` |
| rebuild | 성공 (`2acd8e97…`, generation `31622c79…`) |
| host attestation v4 | 재발행 `10ad0f0f…` — **verifier PASS** |
| C7 executor image | `sha256:f760bf6c…` (라벨 `c72456f6`) |
| `T-VN-41F1D-D1` | **통과** — 데이터 비의존 live UI 11/11, 33.2초, 핀 자신의 스펙 바이트로 실행 |
| `T-VN-41F1D-D2` | helper 결함 셋 수정 완료, 실 DB 사이클 통과. **재실행 대기** |
| D2 lane 상태 | `BLOCKED` 해제 — 잔여물 0 실측 후 `clear-blocked`, 증거는 `adjudicated-…`에 보존 |

### 다음 한 작업

**helper 수정을 머지한 뒤 pinset을 한 번 더 돌린다.** 설치 스냅샷 디렉터리 이름이
`E2E_C7_EXPECTED_GIT_COMMIT`에 결박돼 있고 그것이 attestation의 `repository_commit`·
generation의 `map_source_revision`과 exact여야 하므로, Map revision이 바뀌면
rotate-pair → rebuild → attestation 재발행 → 스냅샷 재설치 → executor 이미지 재빌드 →
D1 → D2가 따라온다. 전 과정이 이번에 스크립트로 남았다.

그 뒤 순서는 **`T-VN-41F1D-E` → `T-VN-41C`**다(2026-09-06 정정). `GM-17`(Manager production compose
required-set 완화)은 소유자 지시로 **가장 마지막**이다.

### 이번에 확인된 운영 사실

- **out-of-band DB 패치는 다음 rebuild에 증발한다.** 어제 배포 DB에 손으로 준
  `GRANT SELECT ON public.alembic_version TO ktm_feature_migrator`가 rebuild로 사라졌고,
  그래서 helper의 진짜 결함이 드러났다. DB가 선언된 계약으로 수렴하는 건 좋은 성질이지만
  그런 패치에 기댄 green은 근거가 되지 못한다.
- **rebuild가 `BLOCKED` lane을 가로지르면 `recover`가 구조적으로 불가능하다.**
  `begin-recovery`가 BLOCKED의 execution identity와 현재 identity의 일치를 요구하는데
  rebuild가 여섯 필드를 전부 바꾼다. 이때의 정본 경로는 잔여물을 직접 측정해 0임을 확인한
  뒤 `clear-blocked`로 정리하고 증거를 남기는 것이다.

### 남아 있는 소유자 판정

- `docker/*.py` 여섯 파일이 `mypy --strict` clean인데도 검사 밖이다(n150 실측). 프로덕션
  기동을 막는 `application-schema-final-permit.py`가 그중 하나다. 편입 비용은 0이지만
  `application-schema-fresh-finalize.py`(5건)·`dagster-storage-migrate.py`(4건)는
  정리가 필요해 경계를 어디에 둘지가 판단이다.
- CI의 mypy는 핀이 없다(`mypy>=1.10`). 새 mypy 릴리스가 검사를 조이면 무관한 PR에서
  `lint` job이 붉어질 수 있다 — 기존 세 스텝도 같은 노출을 갖는다.
