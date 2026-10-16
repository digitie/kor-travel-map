# tasks-acceptance 아카이브 — `T-GR-00-LEDGER` (완료)

> `T-GR-00-LEDGER`의 해제 조건 원문이다. 절은 닫혔고, live 문서
> [`../tasks-acceptance.md`](../tasks-acceptance.md)가 220 KiB(225,280 bytes)
> 상한에 닿아 `docs/tasks-rule.md` §8대로 분리했다(2026-10-16).
>
> **본문은 바이트 단위로 보존했다** — 옮기기만 했고 한 글자도 고치지 않았다
> (파일 끝 빈 줄만 하나로 정규화).
>
> **분리 전에 쟀다.** `scripts/archive_task_ledger_section.py`가 확인한 것:
> 이 절의 fence 마커 0개(짝), 시작·끝 경계 모두
> fence 밖, 그리고 옮긴 뒤 두 파일의 `parse_checkboxes` 결과 합이 옮기기 전과
> **다중집합으로 같음**. 2026-09-13에 제목 기준으로 원장을 통째로 쪼개려다
> 되돌린 적이 있는데, 그때 깨진 것이 바로 이 성질이다.
>
> 과거 검색은 `rg <패턴> docs/archive/`.

## T-GR-00-LEDGER

journal·tasks-done 다음 경계 분리(doc-only, PR-1 선행). 2026-10-13 실측 `journal.md` **≈224,0xx B**(ADR-110 doc PR
`docs/adr-110-geo-transport-on-odroid` 3차 리뷰 반영 뒤 — 커밋 전 측정 223,970 B; T-GR-00 PR-0 시점 208,660 = HEAD 202,686
+ PR-0 항목)·`tasks-done.md` 200,699 B — 상한 225,280 B까지 각각 **≈1.3 KB**·24,581 B라 journal 항목 한 건(≈7~12 KB)은
물론 한 문단만 더해도 `tests/unit/test_every_docs_markdown_stays_within_readable_limit`가 빨개진다. **T-GR-01·T-MAP-02
어느 코드 PR보다도, 그리고 어느 doc-only PR보다도 먼저 선행한다(여유 ≈1.3 KB) — tasks.md·resume의 T-MAP-02 의존도 같은
말이다.** `tasks-rule.md` §8의 "200 KB 근접" 분리
기준을 둘 다 이미 넘었다. 의존: T-GR-00 머지. 규모 S. T-GR-00·T-MAP-01의 `[x]` 전환·tasks-done 이관을 함께 싣는다.

- journal 현행 창(2026-09-14~)에서 가장 오래된 묶음을 `docs/archive/journal-2026-09c.md`(이름은 §8 규약)로, `tasks-done.md`
  가장 오래된 절 묶음을 `docs/archive/tasks-done-*.md`로 옮기고 각 파일 상단 "과거 기록 아카이브" 인덱스 표를 갱신한다.
- 바이트 보존 검산(이동 전 원본 바이트 == 이동 후 잔여 + 아카이브 - stub)을 PR 본문에 적는다; 두 파일 모두 분리 뒤
  ≤ 200,000 B.
- `tests/unit/test_docs_archive_links.py`·`scripts/check_journal_update.py`·docs 크기 lint 초록. 즉시 머지(doc-only).
- 실행(2026-10-15, 브랜치 `docs/t-gr-00-ledger`): journal 2026-09-20~25 8건 → `archive/journal-2026-09e.md`(위 첫 조문의
  `09c`는 이미 쓰였고 09d도 #1319가 썼다 — 규약 §8의 다음 글자), tasks-done 2026-08-04~05 2절 → `archive/tasks-done-2026-08a.md`.
  검산 journal 209,356 = 182,096 + 27,260, tasks-done 200,699 = 89,636 + 111,063(아카이브 본문 = 이동 바이트, 예외는 상대 링크
  4개 `../` 재기준화 +12 B와 끝 빈 줄 1 B — journal 2026-10-15). T-GR-00·T-MAP-01 `[x]`·tasks-done 이관을 실었다.
- 실측(커밋 직전 `wc -c`, 이 PR의 journal·resume 항목 포함): `journal.md` 184,071 B · `tasks-done.md` 91,029 B — 둘 다
  ≤ 200,000 B. 이 절의 `[x]`·이관은 머지가 조건이라 다음 doc-only PR(ADR-110 사실 갱신)이 싣는다.
