# agent-failure-patterns — 반복 실패 패턴과 회피·복구

본 repo에서 AI 에이전트가 **실제로 반복한** 실패와 그 회피/복구법. 모든 에이전트
(Claude/Codex/Antigravity) 공용 — 새 세션이 같은 함정을 다시 밟지 않게 한다.
출처: 세션 transcript + `MEMORY.md`(WSL venv, Playwright e2e) + PR 회고.

> 사용법: 게이트가 깨지거나 이상하면 먼저 여기서 증상을 찾는다. 각 항목은
> **증상 → 원인 → 회피/복구**.

## A. CI ↔ 로컬 괴리

### A1 — 로컬 mypy/pytest green인데 CI lint red

- **증상**: WSL에서 4 게이트 통과했는데 CI `lint`(mypy --strict)만 red.
- **원인**: WSL 테스트 venv에는 debug-ui 설치(`pip install -e packages/...`)로 들어온
  **전이 의존성**(`httpx`/`alembic` 등)이 깔려 있다. CI lint는 `pip install -e ".[dev]"`
  만 하므로, 메인 패키지가 TYPE_CHECKING-only로 쓰는 stub 패키지가 `[dev]`에 없으면
  로컬은 통과·CI는 실패. (PR#113에서 httpx를 `[dev]`에 추가해 해결.)
- **회피/복구**: 새 `TYPE_CHECKING` import를 추가하면 그 stub을 `[dev]` extra에도
  넣었는지 확인. lint 의심 시 로컬을 믿지 말고 `gh run view <id> --log-failed`로
  실제 step 확인. (`MEMORY.md` wsl-test-venv-masks-dev-extras.)

### A2 — 돌리지 않은 게이트 결과를 보고

- **증상**: "테스트 통과"라고 적었는데 실제로는 실행이 취소/뒤섞여 안 돌았음.
- **원인**: 한 메시지에서 병렬 tool 호출이 취소되거나 출력이 섞일 수 있다.
- **회피**: 검증 명령은 **한 번에 하나씩**, 결과를 실제로 읽고 나서 보고. 길거나
  불안하면 결과를 파일로 남겨 Read로 확인. **안 본 수치는 적지 않는다** — 커밋/PR
  본문 수치는 전부 실측만.

### A3 — Python 버전별 CI 실패 (3.11 only 등)

- **증상**: 로컬(3.12) green, CI `pytest (3.11)`만 red.
- **원인**: 버전 한정 API 사용. 실제 사례: `typing.Protocol.__protocol_attrs__`는
  **3.12+ 전용** — 3.11엔 없어 AttributeError.
- **회피**: 버전 비의존 코드. Protocol 멤버 열거가 필요하면 `__protocol_attrs__`
  대신 **명시 필드 집합**을 쓴다. CI는 3.11/3.12/3.13 모두 green 확인 후 머지.

### A4 — OpenAPI drift 게이트 red (debug-ui 라우터 변경)

- **증상**: 라우터/DTO 추가 후 CI `openapi-drift` red.
- **회피/복구**: `scripts/export_openapi.py --output ...openapi.json` 재생성 →
  `--check`로 EXIT=0 확인 → **재생성본을 NTFS로 복사**해 커밋. WSL에서 재생성했으면
  그 파일을 NTFS로 cp 해야 커밋에 들어간다.

## B. Git / worktree / 브랜치

### B1 — `sandbox/<agent>`에 직접 커밋해 버림

- **증상**: feature 브랜치를 안 만들고 작업 → 커밋이 `sandbox/<agent>`에 얹힘.
- **복구**(force-push 불필요): 커밋을 feature 브랜치로 옮기고 sandbox를 되돌린다.
  ```
  git branch feat/<topic>            # 현재 HEAD(커밋 포함)에 브랜치 생성
  git reset --hard origin/main       # sandbox/<agent>를 main으로 되돌림
  git switch feat/<topic>
  git push -u origin feat/<topic>
  ```
- **회피**: 작업 시작 시 `git switch -c feat/<topic> main` 먼저.

### B2 — WSL 미러가 main보다 뒤처짐

- **증상**: WSL `~/dev/python-krtour-map` HEAD가 머지된 main보다 옛 커밋.
- **복구**: `cd ~/dev/python-krtour-map && git fetch origin && git reset --hard
  origin/main`. WSL은 실행 샌드박스라 hard reset 안전(원본은 NTFS).

### B3 — 무관 파일이 커밋에 섞임

- **증상**: `claude.json` 등 세션 파일이 staged.
- **회피**: `git add`에 **관련 파일만 명시**(`git add -A` 지양). 커밋 전 `git status -sb`
  확인.

## C. 도메인 계약 (자연키 / 스키마 / upstream)

### C1 — 자연키에 `|` 사용 → make_feature_id 거부

- **증상**: `make_feature_id`/`make_source_record_key`가 `|` 포함 성분을 거부.
- **회피**: 자연키 구분자는 **`::`**(ADR-009). 예: `{slug}::{mng_no}`,
  `{alert_id}::{region}`. provider 라이브 테스트의 합성 키도 `::`.

### C2 — raw SQL에서 스키마 미한정

- **증상**: `relation "features" does not exist`.
- **원인**: 테이블은 스키마에 격리됨(ADR-008). raw SQL은 스키마 한정 필요:
  `feature.features`, `provider_sync.{source_records,source_links,provider_sync_state}`,
  `ops.{dedup_review_queue,import_jobs,feature_merge_history,feature_consistency_reports}`.
- **참고**: ORM(`FeatureRow`)은 스키마 인지하지만 `text()` 쿼리는 직접 써야 함.

### C3 — `source_role` / `status` CHECK 위반

- **증상**: `violates check constraint "ck_source_links_..."` 등.
- **회피**: `source_role`는 `primary/base_address/base_coordinate/enrichment/correction/
  duplicate_candidate/media/weather_context`만(‘secondary’ 없음). feature `status`는
  `draft/active/inactive/hidden/broken/deleted`. dedup queue status는
  `pending/accepted/rejected/merged/ignored`.

### C4 — upstream provider 필드 drift (본 lib 책임 아님)

- **증상**: provider 라이브러리 파싱 에러(예: krex `restAreaNm/serviceAreaName is
  required` — data.go.kr이 `entrpsNm`으로 rename).
- **분계(ADR-044)**: 데이터 정합성 1차 책임은 **각 provider 라이브러리**. 본 lib는
  신뢰·미러하고, 불일치 시 그 라이브러리를 고친다(필요 시 upstream PR) — 본 lib에
  방어 코드를 넣지 않는다. 로컬 체크아웃이 뒤처졌으면 `git -C F:\dev\python-<p>-api
  pull`부터.

### C5 — 증분(Step B)에서 snapshot prune 하면 오삭제

- **증상**: 증분 적재가 "사라진" record를 비활성화 → 멀쩡한 feature 삭제.
- **원인**: 증분은 전체 snapshot이 아니라 delta. Step A(bulk)만 prune한다. 폐업은
  Step C(closed)의 책임. 증분 loader는 upsert만.

## D. Python / 타입 / 테스트 함정

### D1 — `normalize_phone_number`는 무효 입력에 원본 반환

- **증상**: 쓰레기 전화번호가 `None`이 아니라 그대로 통과.
- **원인**: 정규화는 provenance 보존용이라 숫자 부족 시 원본을 돌려줌(None 아님).
- **회피**: 품질이 필요한 경로(enrichment)는 **자릿수≥9** 등 자체 검증 추가.

### D2 — `runtime_checkable` Protocol isinstance가 불안정

- **증상**: 모든 멤버 `hasattr`=True인데 `isinstance(obj, SomeProtocol)`=False.
- **원인**: Protocol이 `@property`와 일반 method를 섞어 선언 + 대상이 `__getattr__`
  동적 객체일 때 isinstance 결과가 신뢰 불가.
- **회피**: 변환 코드는 isinstance가 아니라 **attribute 접근**으로 duck-type. 테스트도
  isinstance 대신 대표 필드 접근으로.

### D3 — `Result.rowcount` mypy --strict 에러

- **증상**: `"Result[Any]" has no attribute "rowcount"`.
- **회피**: 코드베이스 컨벤션 — UPDATE/DELETE에 `RETURNING <id>` 붙이고
  `len(result.fetchall())`(또는 `bool(result.fetchall())`)로 영향 행 카운트.

### D4 — commit하는 테스트가 다른 테스트를 오염

- **증상**: 단독 실행은 green, 전체 실행 시 fail(예상 0건인데 이전 테스트가 남긴 행).
- **원인**: `migrated_session`은 rollback 격리지만, **CLI/엔진을 직접 만드는 테스트는
  commit**한다 → 행이 잔존.
- **회피**: commit하는 테스트는 teardown에서 관련 테이블 `TRUNCATE ... RESTART
  IDENTITY CASCADE`. 새 테이블 적재 시 TRUNCATE 목록에 **추가**(예: cursor 테스트면
  `provider_sync.provider_sync_state`도).

### D5 — ruff E501: CJK(한글) 폭

- **증상**: 한글 포함 라인이 100자 이하로 보이는데 E501.
- **회피**: 한글 라인은 더 짧게. 긴 type alias 주석은 추론에 맡겨 제거. 자동수정
  가능한 건 `ruff check --fix`(WSL) 후 NTFS로 동기.

### D6 — `from __future__ import annotations`와 forward-ref

- module-level 변수 주석도 PEP 563로 지연 평가되므로, 뒤에 정의된 타입을 따옴표 없이
  참조해도 된다(ruff UP037이 따옴표 제거 요구). 단 런타임에 그 주석을 evaluate하는
  코드가 없을 때만.

## E. 검증 우선순위 (요약)

1. 게이트는 **WSL에서 실제로** 돌린다(로컬 green ≠ CI, §A1).
2. 결과는 **읽고 나서** 보고한다(§A2).
3. 머지 전 CI **3 버전** green(§A3) + drift(§A4).
4. provider 데이터 이슈는 **그 provider 라이브러리**에서 고친다(§C4).
