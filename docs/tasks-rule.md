# tasks-rule.md — task 문서 작성·유지 규칙

`docs/tasks.md` / `docs/tasks-done.md` 의 작성 규약 정본. (구 `agent-guide.md` §6 대체.)

## 1. 세 문서의 역할

| 문서 | 역할 |
|------|------|
| [`docs/tasks.md`](tasks.md) | 열린 `[ ]`(진행/예정/외부추적/보류) 백로그 + 상단 인덱스 |
| [`docs/tasks-done.md`](tasks-done.md) | 완료 `[x]`·폐기·머지 history 아카이브 |
| [`docs/resume.md`](resume.md) | 현재 진척 + "다음 한 작업" (진척 **정본**) |
| [`docs/archive/`](archive/) | `resume.md`·`journal.md`에서 분리한 과거 기록(읽기 전용) |

## 2. tasks.md ↔ tasks-done.md 분리 규칙 (2026-06-09 확립)

- 블록(섹션/Phase) 단위로 라우팅: 열린 `[ ]`가 하나라도 있으면 `tasks.md`, 전부 닫혔으면 `tasks-done.md`.
- 완료 task를 `tasks.md`에 길게 남기지 않는다 — 완료 확인 후 `tasks-done.md`로 옮긴다(이동 시 열린 항목 count 보존).
- 진척 서술은 `resume.md`가 정본 — `tasks.md`에 상태 스냅샷을 중복하지 않는다.

## 3. task ID 스킴

- 기본: `T-NNN` 연번 (예: `T-218`).
- 하위 작업: `T-NNN<letter>` (예: `T-216a`~`g`).
- 잔여/파생: `T-NNN-<slug>` (예: `T-229-buildx`).
- 묶음 prefix 변형 허용 (예: `T-RV-NN`).
- 주제 ID(`T-ADMIN-TANSTACK`, `T-AUDIT-0616`)는 backlog 한정 — 정식화 시 `T-NNN` 부여 권장. 이미 journal/tasks-done에서 참조 중인 ID는 재번호하지 않는다.

## 4. status 마커

- `[ ]` 미완료 · `[x]` 완료 · `[~]` 부분완료(하위 일부 완료).
- 완료 항목 내 해소/철회 표기: `✅`(해소) · `~~취소선~~`(철회).

## 5. 표준 entry 형식

```markdown
- [ ] T-NNN[<letter>|-<slug>] — **<짧은 제목>** (<범위/저장소 표시, 선택>)

  <1~3문장: 무엇을·완료 조건·정본 리포트 링크.>
```

- 모든 backlog 항목은 `[ ]` 체크박스를 단다.
- task당 위치는 하나 — `docs/tasks.md`에 한 줄, 해제 조건은
  `docs/tasks-acceptance.md`에 한 절. 본문을 중복하지 않는다.

## 6. 원장/해제 조건 정합

- **2026-08-27 `6d671ef1`이 `docs/tasks.md`를 평면화하면서 "진행 중인 작업 인덱스"와
  하위 상세 섹션이 함께 사라졌다.** 지금 구조는 한 줄짜리 backlog + 별도 해제 조건
  파일이며, 이 절이 요구하던 인덱스/상세 정합은 대상이 존재하지 않는다. 규약이 없는
  대상을 요구하면 읽는 사람이 규약 전체를 신뢰하지 않게 되므로 현행으로 고쳐 적는다.
- 열린 모든 task는 `docs/tasks-acceptance.md`에 **자기 절**을 갖거나, 상위 task 절이
  자기 ID를 **명시**해야 한다. 이름 접두사만으로 덮였다고 보지 않는다 —
  `tests/lint/test_task_ledger_conventions.py`가 강제한다.
- 외부 저장소 작업은 본 저장소에서 직접 실행하지 않는 한 "외부 추적"으로만 둔다.
- 보류 항목은 도입 조건이 충족되기 전까지 Sprint 잔여로 계산하지 않는다.

## 7. 완료 처리 워크플로

완료 → `tasks-done.md` 상단에 요약 아카이브 + `journal.md` 엔트리 + `resume.md` 갱신. 정본 리포트가 있으면 `docs/reports/...`로 링크.

## 8. resume/journal 아카이브 규칙 (2026-07-28 도입)

`resume.md`·`journal.md`는 역시간순 누적 문서라 방치하면 무한히 커진다(도입 시점 실측:
journal **1046 KB**, resume **287 KB** — 단일 파일이 에이전트 read 한도 256 KB를 넘어 통째로
읽히지 않았다). 아래 규칙으로 **현행 문서를 작게 유지**한다.

- **분리 경계**: 백로그 구조가 새로 성립한 시점(현재 기준 **2026-07-26 전면 감사**) 이전 기록은
  `docs/archive/`로 옮긴다. 그 이후 기록만 `resume.md`/`journal.md`에 남긴다.
- **아카이브 파일명**: `archive/{resume,journal}-YYYY-MM[a|b|c].md`. 한 파일이
  **220 KiB(225,280 bytes)**를 넘으면 같은 달 안에서 `a`/`b`/`c`로 더 쪼개
  **모든 파일이 단독으로 읽히게** 한다.
- **인덱스 필수**: live 문서 상단 "과거 기록 아카이브" 표에 파일·기간·엔트리 수·크기를 남긴다.
  과거 내용을 찾을 때는 `rg <패턴> docs/archive/`.
- **새 엔트리는 항상 live 문서 상단에** 추가한다. 아카이브 파일은 원칙적으로 읽기 전용 이력이다.
  예외는 분리 과정에서 깨진 상대 링크를 원래 repo-root 대상을 가리키도록 재기준화하는 복구와,
  220 KiB(225,280 bytes) 경계 초과를 해소하는 섹션 단위 경계 재조정뿐이다. 이 경우 섹션
  본문은 그대로 보존하고 변경 근거를 live 문서에 기록한다.
- 아카이브의 Markdown 상대 링크는 `docs/archive/` 기준으로 실제 파일에 도달해야 한다.
  `tests/unit/test_docs_archive_links.py`가 모든 archive Markdown 링크를 상시 검사하며,
  아카이브를 새로 만들거나 경계를 옮긴 PR은 이 게이트를 반드시 통과시킨다.
- live 문서가 다시 200 KB에 근접하면 같은 방식으로 다음 경계를 잡아 분리한다. 분리 시 섹션 본문이
  **바이트 단위로 보존**됐는지(누락·변경 0건) 확인한 근거를 PR에 남긴다.
