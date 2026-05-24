# Sprint 계획 디렉토리

`python-krtour-map` v2 코드 작성 단계 Sprint 계획. 각 Sprint는 별도 markdown
으로 박혀 있고, Sprint 진입 시 체크리스트와 함께 검토한다.

| Sprint | 파일 | 상태 | 목표 |
|--------|------|------|------|
| Sprint 1 | [SPRINT-1.md](./SPRINT-1.md) | proposed | 코드 작성 단계 진입 + scaffolding + category 코드 이전 (provider 없음) |
| Sprint 2 | [SPRINT-2.md](./SPRINT-2.md) | proposed | MOIS-독립 작은 provider 4건 (축제·날씨·유가·휴게소) + 디버그 UI backend 첫 라우터 (ADR-031) |
| Sprint 3 | [SPRINT-3.md](./SPRINT-3.md) | proposed | 국립공원/트래킹 (KNPS+krforest_trails) + 국가유산 (krheritage) + 정합성 Phase 1 (F1~F3, ADR-033) |
| Sprint 4 | [SPRINT-4.md](./SPRINT-4.md) | proposed | **MOIS 인허가** bulk (4단계 lifecycle) + dedup queue 운영 시작 (Coverage 80% 도달, ADR-032) |
| Sprint 5 | [SPRINT-5.md](./SPRINT-5.md) | proposed | MOIS-sibling (휴양림/수목원/박물관/표준데이터) + 정합성 Phase 2 (F4~F8 + Dagster 게이트) + 운영 직전 T-200~T-204 |

## 9단계 구현 순서 (ADR-034)

사용자 명시 + ADR-034로 박힌 provider 적재 순서:

```
Sprint 2:  ① 축제 → ② 날씨 → ③ 유가 → ④ 휴게소     (MOIS-독립, 작은 dataset)
Sprint 3:  ⑤ 국립공원/트래킹 → ⑥ 국가유산           (MOIS-독립, 중간 dataset + area/route)
Sprint 4:  ⑦ MOIS 인허가                            (가장 큰 bulk, dedup 룰 본격 검증)
Sprint 5:  ⑧ 휴양림/수목원 → ⑨ 박물관/미술관         (MOIS-sibling, 이미 검증된 룰로 진입)
```

핵심 통찰: MOIS-독립 provider를 먼저 적재 → dedup 룰을 작은 dataset에서
검증 → MOIS bulk 진입 시점에 정합성 게이트 안정 → MOIS-sibling provider는
검증된 룰로 진입. 자세한 근거는 `../decisions.md` ADR-034.

## Sprint 진입 게이트 (공통)

각 Sprint 진입 PR은 다음을 확인:
- 이전 Sprint의 DoD 모두 충족
- ADR-032 Coverage bar가 이전 Sprint 수준에 도달
- 신규 Sprint의 ADR들이 `proposed` → `accepted` 전환 (시기 의존 ADR만 해당)
- 직전 Sprint에서 발견된 회귀/burndown 정리 완료
- ADR-034 9단계 순서 준수 (Sprint별 provider 매핑)

## 관련 ADR

- **ADR-021** — PR-only workflow (Sprint 진입은 PR로만)
- **ADR-027** — forest 카테고리/notice_type 확장 (Sprint 1 코드 적용)
- **ADR-028** — `python-knps-api` provider 등록 (Sprint 3에서 사용)
- **ADR-029** — `@krtour/map-marker-react` npm 패키지 (Sprint 2부터)
- **ADR-030** — 라이브러리 캐시 금지 + import-linter 계약 (Sprint 1 활성화)
- **ADR-031** — 디버그 패키지 OpenAPI export (Sprint 2 첫 라우터부터)
- **ADR-032** — Coverage 단계적 상향 일정 (Sprint 1~5 schedule)
- **ADR-033** — `feature_consistency_reports` 단계적 도입 (Phase 1 = Sprint
  3, Phase 2 = Sprint 5)
- **ADR-034** — Provider 구현 순서 (9단계, MOIS-독립 → MOIS → MOIS-sibling)

## 참조

- Backlog 전체: `../tasks.md`
- 진척도: `../resume.md`
- 작업 일지: `../journal.md`
- ETL 사양: `../<provider>-feature-etl.md` (각 provider별)
- Dagster 매핑: `../dagster-boundary.md`
- 정합성: `../test-strategy.md` + ADR-033
