# tasks-acceptance 아카이브 — `T-GR-00` (완료)

> `T-GR-00`의 해제 조건 원문이다. 절은 닫혔고, live 문서
> [`../tasks-acceptance.md`](../tasks-acceptance.md)가 220 KiB(225,280 bytes)
> 상한에 닿아 `docs/tasks-rule.md` §8대로 분리했다(2026-11-28).
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

## T-GR-00

2026-10-13 geo 릴리스 재지오코딩 설계(ADR-109, 당시 proposed)에서 열었다. 접두사 `T-GR-`는 임시다(ADR-109
열린 결정 7; 소유자가 다른 접두사를 고르면 `T-GR-00`~`08`을 일괄 재번호하되 journal·acceptance 참조도 함께).
PR 묶음: PR-0 = 이 doc-only PR(T-GR-00·ADR-109·문서) → PR-1(T-GR-01+02+03, 407) → PR-2(T-GR-04+05+08,
408+API+센서+replay) → [PinVi 재vendor] → PR-3(T-GR-06) → PR-4(T-GR-07, doc-only). 리모트 브랜치에 자주 푸시,
PR은 머지 직전.

- 분리 실행(2026-10-13, 이 브랜치): `scripts/archive_task_ledger_section.py --apply`로 닫힌 절 7개
  (`T-VN-41F1D-D1`·`T-VN-41F1D-E`·`T-VN-M01`·`T-VN-M04`·`T-VN-39`·`T-VN-DAGSTER-STORAGE`·
  `T-VN-QUOTA-ARITHMETIC`, 파일 순서로 가장 오래된 movable 절부터)를 `docs/archive/tasks-acceptance-*.md`로
  옮겼다 — 216,950 → 166,931 bytes, 매 이동마다 도구의 다중집합 검산 통과. 거절된 절(`T-VN-41F1D-D2`·
  `T-VN-D2-API-AUDIT`·`T-VN-H34`: 상대 링크, `T-VN-M03`: 349 B라 stub 비용이 더 큼)은 두었다.
- 해제 조건: 이 PR에서 `tests/unit/test_docs_archive_links.py`(아카이브 링크·225,280 B 상한)와
  `tests/lint/test_task_ledger_conventions.py`·`scripts/check_task_ledger_deletions.py`가 초록이고 머지된다.
  T-GR 절 9개를 더한 이 PR 최종 크기는 §T-GR-00 아래 "실측" 줄(ADR-109 설계 수용 기준 ≤ 200,000 B).
  `[x]` 전환·`tasks-done.md` 이관은 머지가 조건이라 이 PR 안에서 할 수 없다 — T-GR-00-LEDGER의 doc-only PR에 함께 싣는다.
- 잔여 바이트 실측(2026-10-13, 이 브랜치): `tasks-acceptance.md`는 2차 리뷰 반영 뒤 §T-GR-00 아래 "최종 실측" 줄;
  `journal.md`·`tasks-done.md`의 분리는 독립 task **T-GR-00-LEDGER**(이 PR 범위 아님)다.
- 최종 실측(2차 리뷰 반영 뒤): 커밋 직전 `stat`으로 잰 값을 journal 2026-10-13 항목에 적는다 — 이 절은
  append-only가 아니므로 PR-1에서 수치를 갱신해도 된다.
- 열린 결정(ADR-109)이 미결이면 각 절은 ADR의 권장안을 기준으로 한다. 결정별 영향 조문: 3 → T-GR-05
  `default_status`; 4 → T-GR-08 적용 범위; 5·9 → T-GR-04 `complete_plan`(sweep·링크 재동기화 범위)과 T-GR-05 완료
  전이; 6 → T-GR-05 timeout 재시도 옵션(T-GR-01에서 뺐다 — T-GR-01은 결정 비의존); 7 → 전 절 ID 재번호; 10 →
  T-GR-03 override finding; 11 → T-GR-05 기동 방식; 12 → T-GR-03 concierge 해시; 13 → 이 묶음 밖 백로그.
- T-GR-07 범위 메모: 설계 §11 T-GR-07의 문서 항목 중 ADR-109·README·integration-map·`address-geocoding.md`·etl
  3문서·ADR-108 각주·원장은 PR-0(이 PR)가 선반영했고, T-GR-07에는 구현 뒤 남는 것(accepted 전환·runbook·CHANGELOG·
  "계획" 표식 제거)만 둔다.
