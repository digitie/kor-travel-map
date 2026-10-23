# tasks-acceptance 아카이브 — `T-GR-06` (완료)

> `T-GR-06`의 해제 조건 원문이다. 절은 닫혔고, live 문서
> [`../tasks-acceptance.md`](../tasks-acceptance.md)가 220 KiB(225,280 bytes)
> 상한에 닿아 `docs/tasks-rule.md` §8대로 분리했다(2026-10-23).
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

## T-GR-06

ADR-109 결정 8(UI). 수정 파일: `packages/kor-travel-map-admin/frontend/src/app/admin/ops/geo-releases/*`,
`npm run gen:types`(T-GR-04의 admin OpenAPI에 의존), `docs/runbooks/admin-ui-screen-checklist.md`(route 행), Playwright
스펙(n150 우선). 의존: T-GR-04. 규모 M.

- Playwright: 계획 항목 skip 클릭 → badge `skipped`; "지금 감지" 클릭 → `/detect` 호출 정확히 1회·계획 행 표시;
  커버리지 게이지 수치가 API 응답과 일치; `data_token` 없음 → 빨간 상태 + Skip 사유 문구.
- `/admin/issues`·features 목록은 diff 0.
- `admin-ui-screen-checklist.md`에 `/admin/ops/geo-releases` 행과 e2e 매핑이 있다.
- 구현 메모(2026-10-16, `feat/t-gr-06-geo-releases-ui`): nav "수집 파이프라인 › geo 릴리스". gen:types 변경 없음(T-GR-04가
  이미 생성). MOIS 항목은 operation key로 "수동 실행 후 skip 필요"(#1333 재리뷰 Low — enum 불변). 격리 스택(PostGIS·가짜
  geo·API·prod frontend, n150) live 스펙이 기준선 → 새 토큰 감지 → 실제 계획 항목·MOIS 안내·건너뛰기를 확인한다.
