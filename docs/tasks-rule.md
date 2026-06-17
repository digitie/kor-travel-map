# tasks-rule.md — task 문서 작성·유지 규칙

`docs/tasks.md` / `docs/tasks-done.md` 의 작성 규약 정본. (구 `agent-guide.md` §6 대체.)

## 1. 세 문서의 역할

| 문서 | 역할 |
|------|------|
| [`docs/tasks.md`](tasks.md) | 열린 `[ ]`(진행/예정/외부추적/보류) 백로그 + 상단 인덱스 |
| [`docs/tasks-done.md`](tasks-done.md) | 완료 `[x]`·폐기·머지 history 아카이브 |
| [`docs/resume.md`](resume.md) | 현재 진척 + "다음 한 작업" (진척 **정본**) |

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

- 모든 backlog 항목은 `[ ]` 체크박스를 단다(상단 인덱스 포함).
- task당 상세 위치는 하나 — 인덱스는 참조만 하고 본문을 중복하지 않는다.

## 6. 인덱스/상세 정합

- 상단 "진행 중인 작업 인덱스"의 열린 `[ ]`와 하위 상세 섹션은 일치해야 한다.
- 외부 저장소 작업은 본 저장소에서 직접 실행하지 않는 한 "외부 추적"으로만 둔다.
- 보류 항목은 도입 조건이 충족되기 전까지 Sprint 잔여로 계산하지 않는다.

## 7. 완료 처리 워크플로

완료 → `tasks-done.md` 상단에 요약 아카이브 + `journal.md` 엔트리 + `resume.md` 갱신. 정본 리포트가 있으면 `docs/reports/...`로 링크.
