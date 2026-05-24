# Sprint 계획 디렉토리

`python-krtour-map` v2 코드 작성 단계 Sprint 계획. 각 Sprint는 별도 markdown으로
박혀 있고, Sprint 진입 시 체크리스트와 함께 검토한다.

| Sprint | 파일 | 상태 | 목표 |
|--------|------|------|------|
| Sprint 1 | [SPRINT-1.md](./SPRINT-1.md) | proposed | 코드 작성 단계 진입 + scaffolding + category 코드 이전 |
| Sprint 2 | (미작성) | — | core/ + 첫 provider 4건 + 디버그 UI backend 첫 라우터 |
| Sprint 3 | (미작성) | — | provider 절반 + infra + Phase 1 정합성 (F1~F3, ADR-033) |
| Sprint 4 | (미작성) | — | 나머지 provider + integrity + edge cases (Coverage 80% 도달, ADR-032) |
| Sprint 5 | (미작성) | — | 운영 진입 직전 — Phase 2 정합성 (F4~F8 + Dagster 게이트, ADR-033) + Sprint 5 운영 직전 T-200~T-204 |

## Sprint 진입 게이트 (공통)

각 Sprint 진입 PR은 다음을 확인:
- 이전 Sprint의 DoD 모두 충족
- ADR-032 Coverage bar가 이전 Sprint 수준에 도달
- 신규 Sprint의 ADR들이 `proposed` → `accepted` 전환 (시기 의존 ADR만 해당)
- 직전 Sprint에서 발견된 회귀/burndown 정리 완료

## 관련 ADR

- **ADR-021** — PR-only workflow (Sprint 진입은 PR로만)
- **ADR-032** — Coverage 단계적 상향 일정 (Sprint 1~5 schedule)
- **ADR-033** — `feature_consistency_reports` 단계적 도입 (Phase 1 = Sprint
  3~4, Phase 2 = Sprint 5)
- **ADR-014** — 테스트 4단계 + Coverage 목표

## 참조

- Backlog 전체: `../tasks.md`
- 진척도: `../resume.md`
- 작업 일지: `../journal.md`
