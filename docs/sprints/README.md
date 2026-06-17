# Sprint 계획 디렉토리

`kor-travel-map` v2 코드 작성 단계 Sprint 계획. 각 Sprint는 별도 markdown
으로 박혀 있고, Sprint 진입 시 체크리스트와 함께 검토한다.

| Sprint | 파일 | 상태 | 목표 |
|--------|------|------|------|
| Sprint 1 | [SPRINT-1.md](./SPRINT-1.md) | ✅ **완료** (PR#17~#27, 2026-05-25) | 코드 작성 단계 진입 + scaffolding + category 코드 이전 (provider 없음) |
| Sprint 2 | [SPRINT-2.md](./SPRINT-2.md) | ✅ **완료** (PR#28~#59, 2026-05-26~28) | MOIS-독립 작은 provider 4건 (축제·날씨·유가·휴게소) + visitkorea enrichment + KMA mid_forecast + 디버그 UI backend 라우터 + ETL live 11/11 dataset + coverage 65 |
| Sprint 3 | [SPRINT-3.md](./SPRINT-3.md) | ✅ **완료** (PR#60~#95, 2026-05-28~30) | KNPS + krheritage(+area_square_meters/file_sources) + ADR-033 Phase 1(F1~F3, 관측만) + `/features/*` 라우터 + `feature_repo.py` + `core/dedup` + `ops.dedup_review_queue` + `AsyncKorTravelMapClient` 오케스트레이터 + geocoding REST 도입(후속 PR#123에서 v2 `POST /v2/*` 정본화) + `/features` 지도 페이지 + Windows Playwright e2e + frontend CI 게이트 + coverage 75 |
| Sprint 4 | [SPRINT-4.md](./SPRINT-4.md) | ✅ **완료** (PR#133~#142, 2026-05-31~06-01, 4a/4b 분할) | **MOIS 인허가** Step A~D lifecycle(bulk/incremental/closed/detail) + dedup-merge + `feature_merge_history` + dedup 운영 통계 + ADR-033 F4 + Place phone enrichment + coverage 80%(실측 94.12%) |
| Sprint 5 | [SPRINT-5.md](./SPRINT-5.md) | 🟢 마무리 (잔여: `T-229-buildx` arm64 buildx 배포 검증 — 배포 시점) | MOIS-sibling (휴양림/수목원/박물관/표준데이터) + 정합성 Phase 2 (F5~F8 + Dagster 게이트) + ADR-045 Docker 독립/admin OpenAPI/독립 Dagster + 운영 직전 T-200~T-204 |

> **진척의 단일 정본은 `../resume.md`("다음 한 작업") + 백로그 `../tasks.md`다.**
> 이 표/문서에는 자주 바뀌는 PR 번호를 박지 않는다(반복 drift 회피 —
> `../reports/docs-consistency-audit-2026-06-06.md` DA-D-01). 기준값: coverage gate
> `fail_under=80`, geocoding 로컬 `http://127.0.0.1:12501`(v2 `POST /v2/*`), frontend
> Next.js 16 + `maplibre-vworld-js#v0.1.3`, 운영 모델 ADR-045(Docker 독립 + 독립
> DB/Dagster + PinVi OpenAPI, 구 모델 호환 shim 금지 ADR-046). Sprint 5의 본
> 저장소 잔여는 `T-229-buildx`(arm64 multi-arch buildx 배포 검증, `GITHUB_TOKEN`
> 필요)뿐이다 — `T-225`/`T-229` closure는 완료됐다(상세는 `../resume.md`/`../tasks.md`).
> PinVi 쪽 후속과 `T-101`/`T-103`은 외부 추적 또는 보류 항목으로 별도 관리한다.

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
- **ADR-029** — `@kor-travel-map/map-marker-react` npm 패키지 (Sprint 2부터)
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
