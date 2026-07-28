# agent-workflow — 표준 1-PR 작업 흐름

본 repo를 편집하는 **모든 AI 에이전트 공용** 절차. 한 task = 한 feature branch =
한 PR = CI green 후 머지. 에이전트별로 다른 값(worktree, `sandbox/<agent>`)은
[README §2 표](./README.md#2-에이전트별-분기-공유-표)를 본다.

> 요지: **Git/codegraph를 포함한 모든 개발 명령은 Linux/WSL에서
> `/mnt/f/...` 경로로 실행한 뒤 PR로 머지한다.** 단, Playwright e2e는 WSL에서 실행하지
> 않는다. Playwright 브라우저 검증은 n150 Linux가 1순위이고, n150에서 불가할 때만
> Windows 호스트 브라우저로 fallback한다.

## 1. 진입 (5분)

1. 자기 worktree로 이동 (예: Claude → `F:\dev\kor-travel-map-claude`).
2. `CLAUDE.md`/`AGENTS.md` → `SKILL.md` → `docs/sprints/README.md` →
   `docs/resume.md`("다음 한 작업") → `docs/journal.md` 최신 3건 → 관련 ADR.
3. `codegraph sync`(init 아님) — 인덱스 증분 동기. 컴포넌트(특히 `Feature` DTO /
   `make_feature_id` / provider 변환) 수정 전 `codegraph impact`/`callers`로 영향도
   확인.

## 2. 브랜치

```
git -C <worktree> fetch origin
git -C <worktree> switch -c feat/<topic> main      # 또는 origin/main
```

- worktree는 영속, **브랜치만 새로**. 메인 trunk(`F:\dev\kor-travel-map`)는 안 만짐.
- `sandbox/<agent>` 위에서 **직접 작업/커밋하지 않는다** — 반드시 `feat/*`·`fix/*`·
  `docs/*`·`chore/*` 브랜치. (실수로 `sandbox/<agent>`에 커밋했으면
  [failure-patterns §B1](./agent-failure-patterns.md) 복구법.)

## 3. 편집 (Linux/WSL 실행)

- 코드/문서는 agent별 worktree에서 수정한다. `git`/`gh`/`codegraph`/`rg`/`sed`/
  `python`/`uv`/`npm`/`docker` 등 모든 개발 명령은 WSL에서
  `/mnt/f/dev/kor-travel-map-<agent>`로 이동해 실행한다. provider 라이브러리
  (`python-*-api`)는 `/mnt/f/dev/` 로컬 우선 조회(ADR-044) — GitHub 404는
  "미존재" 근거 아님.
- 변경 분류별 동시 갱신 문서(agent-guide.md §2 "결정·기록 5종"):
  코드만 바꾸고 `decisions/resume/journal/tasks/SPRINT` 중 관련된 게 하나도 안 바뀌면
  그 PR은 불완전.

## 4. 검증 (WSL) — 4 게이트

게이트는 WSL에서 실행한다. 기본은 NTFS worktree의 WSL 마운트 경로를 직접 쓰며,
ext4 mirror는 성능·격리 필요 시에만 선택한다.

```bash
cd /mnt/f/dev/kor-travel-map-<agent>
.venv/bin/ruff check .                 # 1) lint/format
.venv/bin/mypy --strict src            # 2) 타입 (필요 시 packages/.../src 도)
.venv/bin/lint-imports                 # 3) 의존 계층 (4 contracts)
.venv/bin/python -m pytest -q          # 4) 전체 테스트 (testcontainers PostGIS)
```

- **debug-ui 라우터/DTO 변경 시** OpenAPI drift 게이트 추가:
  `python packages/kor-travel-map-api/scripts/export_openapi.py --profile all`
  로 admin/user spec을 재생성 후 `--profile all --check`로 EXIT=0 확인 —
  재생성본을 NTFS로 복사해 커밋.
- **Playwright e2e**는 WSL에서 실행하지 않는다. n150 Linux에서 우선 실행하고, n150에서
  실행할 수 없을 때만 Windows host Chromium fallback을 사용한다. fallback 때도 서버
  (backend `:12701` + frontend `:12705`)는 WSL에서 실행한다. `docs/dev-environment.md` §8.1.
- 대용량 migration·실데이터 clone·image build·fixture 준비·Live E2E는 단계별 checkpoint,
  exact code SHA, DB migration head와 fixture identity를 로그에 남긴다. 실패 시 선행 산출물의
  무결성을 확인할 수 있으면 실패 지점부터 재개한다. 재사용 상태를 증명할 수 없거나 수정이
  선행 단계 결과를 바꾸는 경우에만 처음부터 다시 실행한다([failure-patterns §F12](./agent-failure-patterns.md)).
  재개용 격리 DB·dump와 명시적으로 허용한 **redacted immutable checkpoint**는 PR 성공만으로
  즉시 정리하지 않는다. 허용 checkpoint는 migration head·checksum·row count·fixture identity처럼
  session/실데이터가 없는 요약뿐이다. Playwright `storageState`(`admin-state.json` 포함), cookie,
  raw trace, 실데이터 screenshot, 민감 로그, 임시 env·session secret은 재사용 후보가 아니며
  성공·실패와 무관하게 실행 직후 안전하게 폐기한다. PR 머지 후 다음 task 착수 전에 DB migration
  head·schema/fixture 계약·파괴적 실행 잔여물·코드/API 호환성·디스크 여유를 확인해 재사용 가능
  여부를 판정한다. 재사용 가능하면 이름·head·fixture identity를 `docs/resume.md`/
  `docs/journal.md`에 남겨 그대로 이어 쓰고, 불가능할 때만 정확한 격리 resource를 정리한 뒤
  새 checkpoint를 만든다.
- curation Live E2E의 clean fixture 기본값은 공개 membership `486`, 아름다운 등대 미연결
  `15`다. prod clone에서 operator override·최신 Feature 매칭을 의도적으로 보존할 때만
  `E2E_EXPECTED_OFFICIAL_PUBLIC_MEMBERSHIPS`와
  `E2E_EXPECTED_UNLINKED_BEAUTIFUL_LIGHTHOUSES`를 실측값으로 지정한다
  (2026-07-27 검증 baseline `485`/`14`). 연결 건수가 1건 이상이면
  `E2E_EXPECTED_BEAUTIFUL_LIGHTHOUSE_MATCHES`도 쉼표 구분
  `source_item_key=feature_id` 목록으로 지정한다(동 baseline
  `beautiful12=f_3117010300_p_1d6b9e79e9e1163b`). count override는 비어 있지 않은 음이 아닌
  safe decimal integer여야 하고, 원천 총 15건·정확한 연결 identity·operator 상태를 별도
  단언해 같은 합계의 상쇄 오류를 막는다.
- 로컬 green을 맹신하지 말 것 — WSL venv가 누락된 `[dev]` extra를 가릴 수 있다
  ([failure-patterns §A1](./agent-failure-patterns.md)).

## 5. 커밋 + PR

```
git -C <worktree> add <관련 파일만>     # claude.json 등 무관 파일 제외
git -C <worktree> commit -m "<type(scope): summary>" -m "<본문: 무엇/왜/게이트 결과>"
git -C <worktree> push -u origin feat/<topic>
gh pr create --base main --head feat/<topic> --title ... --body ...
```

- 커밋/PR 본문에는 **실제 게이트 결과**(예: `ruff clean / mypy N files / import-linter
  4 kept / M passed`)를 적되, **반드시 실행해서 본 수치만**. 안 돌린 결과를 적지
  않는다([failure-patterns §A2](./agent-failure-patterns.md)).
- 커밋 trailer: `Co-Authored-By:` 한 줄. PR 본문 끝: `🤖 Generated with ...`.
- `git`도 Linux/WSL에서 실행한다. 기존 worktree가 Windows 경로 기반 `.git` 포인터 때문에
  WSL `git`에서 인식되지 않으면 [failure-patterns §B4](./agent-failure-patterns.md)대로
  worktree metadata를 Linux 경로로 고친다.

## 6. CI green → 머지

```
gh pr checks <N> --watch              # lint + pytest unit/integration/fixture + openapi/frontend
gh pr merge <N> --merge --delete-branch
```

- **CI green 전 머지 금지**(ADR-021/038). 3.11/3.12/3.13 모두 통과 확인 — 버전별
  실패가 흔하다([failure-patterns §A3](./agent-failure-patterns.md)).

## 7. 머지 후 동기화

머지 후 자기 worktree의 `sandbox/<agent>`와 WSL 미러를 main에 맞춘다:

```
git -C <worktree> switch sandbox/<agent>
git -C <worktree> fetch origin && git -C <worktree> merge --ff-only origin/main
git -C <worktree> branch -D feat/<topic>
git -C <worktree> push origin sandbox/<agent>
# WSL 미러도 main으로:
#   cd ~/dev/kor-travel-map && git fetch origin && git reset --hard origin/main
```

- WSL 미러가 main보다 뒤처져 보이면 `git reset --hard origin/main`
  ([failure-patterns §B2](./agent-failure-patterns.md)).
- 다음 task를 시작하기 전에 직전 PR의 격리 DB·dump·redacted checkpoint 재사용 가능성을 먼저
  판정한다.
  migration/schema/fixture가 호환되고 파괴적 Live 잔여물이 다음 검증을 오염시키지 않으면
  재사용하며, 판정 근거와 유지·정리한 resource 이름을 `resume`/`journal`에 기록한다.
  인증 상태·cookie·raw trace·실데이터 screenshot·민감 로그·임시 secret은 이 판정까지
  보존하지 않고 Live 종료 직후 폐기한다.

## 8. 1-PR 체크리스트

- [ ] feature 브랜치(`sandbox/*` 아님)에서 작업
- [ ] 4 게이트 WSL에서 실제 실행, 전부 green (DTO/admin/frontend 변경이면 OpenAPI/frontend도)
- [ ] Playwright e2e는 WSL이 아니라 n150에서 실행(불가 시 Windows fallback 사유 기록)
- [ ] 장시간 Live/migration 실패 시 checkpoint 무결성 확인 후 가능한 실패 지점부터 재개
- [ ] Live 종료 직후 인증 상태·raw trace/screenshot·민감 로그·임시 secret 폐기
- [ ] PR 머지 후 다음 task 전에 격리 DB·dump·redacted checkpoint 재사용 가능성 판정 및
      resume/journal 기록
- [ ] 결정·기록 5종 중 관련 문서 갱신 (CHANGELOG는 사용자 가시 변경 시)
- [ ] 무관 파일(claude.json 등) 스테이징 제외
- [ ] PR 본문에 실측 게이트 수치
- [ ] CI 3버전 green 확인 후 머지 → sandbox/<agent> + WSL 동기화
