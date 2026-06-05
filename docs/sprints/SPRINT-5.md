# SPRINT-5.md — MOIS-sibling provider + 정합성 Phase 2 + 운영 진입

> **상태**: 🟡 진입 준비 (Sprint 4 종료 2026-06-01). **ADR-045 독립 프로그램화**
> (Docker compose + admin-first OpenAPI + 독립 Dagster)가 Sprint 5 핵심 트랙으로
> 추가됨 — F5~F8 + Dagster 게이트는 ADR-045의 krtour-map-owned Dagster 위에서 구현.
>
> **목적**: ADR-034 9단계의 ⑧⑨ — 휴양림/수목원 (`python-krforest-api`) +
> 박물관/미술관 (`data.go.kr-standard`). MOIS와 sibling 가능한 provider를
> 검증된 dedup 룰로 적재. 정합성 Phase 2 (F5~F8 + Dagster 게이트) + ADR-045
> 독립 프로그램화 + 운영 진입 직전 T-200~T-204.

## 1. 진입 조건 (Sprint 4 DoD) — ✅ 충족 (2026-06-01)

- [x] Sprint 4 모든 DoD 충족 (`SPRINT-4.md §7`, 4a/4b 완료 PR#133~#142)
- [x] MOIS Step A~D lifecycle 적재 안정 (bulk/incremental/closed/detail)
- [x] dedup_review_queue 운영 안정 + F4 WARN baseline 결정 (dedup-merge + 운영
      FP 통계 + F4 provisional 1000)
- [x] Coverage bar 80% pass (실측 94.12%, `fail_under=80`)
- [x] Place phone enrichment 백그라운드 시작 (`krtour.map.enrichment`)

## 2. 산출물

> **ADR-045 독립 프로그램화 트랙(Sprint 5 핵심)**: Docker compose + admin-first
> OpenAPI + 독립 Dagster + TripMate REST 연계. **세분 실행 계획은
> `docs/adr045-standalone-plan.md`**(T-205~T-210), 의사결정 결과는
> `docs/adr045-open-decisions.md`(D-1~D-16 전부 결정 완료), TripMate REST 계약은
> `docs/tripmate-rest-api.md`. 아래 §2.1+ provider 적재는 ADR-045 Dagster asset
> (krtour-map 소유)로 운영 전환된다(T-208c).

### 2.1 Provider ⑧ — 휴양림/수목원 (`python-krforest-api`)

- **datasets**:
  - `krforest_recreation_forests` (place, `03.03 LODGING_RECREATION_FOREST`
    + Tier 3 분기 — 국립 KFS / 공립 LOCAL / 사립 OPERATOR)
  - `krforest_arboretums` (place, `01.03.01 TOURISM_BOTANICAL_GARDEN` +
    Tier 4 국립/공립/사립 분기)
- **MOIS sibling**:
  - 휴양림 ≅ MOIS `condo_resorts` / `tourist_accommodations`
  - 수목원 ≅ MOIS `botanical_gardens` 슬러그
- **dedup 룰**: Sprint 2~4에서 검증된 Record Linkage scoring (ADR-016)
  그대로 가동. MOIS row가 이미 적재되어 있으므로 sibling group 자연
  생성 + `dedup_review_queue` 운영자 검토.
- **fixture**: 6건 (휴양림 3 + 수목원 3 — 모두 MOIS sibling 후보 포함)
- **module**: `src/krtour/map/providers/krforest.py` (Sprint 2의
  `krforest_weather.py`/Sprint 3의 `krforest_trails.py`와 namespace package
  로 통합)

### 2.2 Provider ⑨ — 박물관/미술관 + 표준데이터 (`data.go.kr-standard`)

- **datasets** (5종):
  - `standard_museums` (place, `01.04 TOURISM_CULTURAL_FACILITY` 박물관/
    미술관/공연장/영화관/도서관)
  - `standard_tourist_sites` (place, `01.05 TOURISM_NATURE` 등)
  - `standard_parking_lots` (place, `06010000` `TRANSPORT_PARKING`)
  - `standard_tourism_roads` (route, `01080500` `TOURISM_ACTIVITY_TREKKING`)
  - `standard_cultural_festivals` (event, festival kind)
- **MOIS sibling**:
  - 박물관/미술관 ≅ MOIS `museums_art_galleries` 슬러그
  - 관광지/주차장은 약한 sibling (좌표만 비슷)
- **module**: `src/krtour/map/standard_data/` (bounded asyncio client,
  v1 패턴 재구현 — `docs/external-apis.md §3.12`)
- **dedup**: MOIS sibling 적극 검증.

### 2.3 ADR-033 Phase 2 — F4~F8 + Dagster 게이트 (T-201b)

- **F4** (`dedup_review_queue` 미해소 threshold 초과) — Sprint 4에서 baseline
  결정한 threshold 적용. severity=WARN.
- **F5** (provider `last_success` SLA 초과 — 24h default) — severity=WARN.
- **F6** (`opening_hours` 모순, start > end, ADR-019 위배) — severity=ERROR.
- **F7** (cross-provider dedup score 회귀 — Sprint별 baseline 대비 N% 이상
  하락) — severity=WARN.
- **F8** (`file_object` orphan: RustFS object 존재 + DB feature 없음 / 그
  반대) — severity=WARN.
- 진행 메모(2026-06-05): `F6`는 `run_consistency_checks()`의 정적 SQL 케이스로
  먼저 구현했다. 남은 Phase 2 범위는 F5/F7/F8 + dry-run report다.
- **Dagster 게이트 적용** (`docs/dagster-boundary.md §12`):
  - root → child 적재 → `consistency_check` 실행
  - `severity_max != ERROR` 시 `mv_refresh strategy='swap'`
  - ERROR 시 알림 + swap 차단
- **dry-run report 첨부**: Phase 2 도입 PR은 반드시 첫 dry-run report 첨부
  후 점진 enable (ADR-033 §결과 부정).

### 2.4 T-200 — Batch DAG + 정합성 게이트 (kraddr-geo ADR-017 미러)

- ✅ T-205d: `ops.import_jobs`에 `load_batch_id UUID`, `parent_job_id UUID` 컬럼 추가.
- ✅ T-200: `infra.batch_dag` + Dagster `full_load_batch_consistency_gate` job 구현.
- 기존 실제 source load import job id를 `child_job_ids`로 받아 root batch에 연결하고,
  child가 모두 `done`일 때만 `consistency_check`를 실행한다.
- `severity_max=ERROR`이면 `mv_refresh`를 차단한다. 현재 운영 MV 카탈로그가 없으므로
  OK/WARN 뒤 `mv_refresh` 단계는 `skipped:no_materialized_views`로 명시 기록한다.
- phase별 중단/재개 UI/API(`PLAN_ONLY=1` preflight 포함)는 T-212 admin 전체점검에서
  운영 UX와 함께 보강한다.
- krtour-map Dagster asset 작성. TripMate는 OpenAPI로 update request를 생성하고,
  provider 적재 asset/worker는 krtour-map이 소유한다(ADR-045/046).

### 2.5 T-202 — pre-commit hook 정착

- `src/` 또는 `tests/` 수정 시 `docs/journal.md` 갱신 강제 (`BYPASS=1` 일회
  우회)
- `lint-imports` / `ruff format --check` / `mypy --strict` 자동 실행
- (Sprint 5 진입 시점에 코드 base가 안정 → pre-commit hook 정착 적절)
- 완료 기준: `.pre-commit-config.yaml` local hook + `scripts/check_journal_update.py`
  + `scripts/run-precommit-check.sh`. Python code/test 변경에는 journal gate와
  static gate를 pre-commit에서 실행한다.

### 2.6 T-203 — PR CI 워크플로

- `.github/workflows/ci.yml` — unit / integration / fixture_replay 분리 jobs
  (Sprint 1부터 일부 가동 중이지만 Sprint 5에서 full matrix 완성)
- `.github/workflows/openapi.yml` — Sprint 2부터 가동
- `.github/workflows/lint.yml` — Sprint 1부터 가동
- 완료 기준: 기존 `pytest (Python X)` check 이름은 유지하되 unit job으로 좁히고,
  PostGIS integration과 fixture replay를 별도 always-on job으로 분리한다.
  `openapi-drift`와 frontend build check는 path filter를 제거해 모든 PR에서 생성한다.

### 2.7 T-204 — GitHub branch protection 설정 가이드

- main: require PR + 1 approval + status checks + restrict force-push
- ADR-021 §결정의 운영 정책을 별도 매뉴얼로
- Sprint 5 진입 시점에 운영자 매뉴얼로 박음
- 완료 기준: `docs/runbooks/branch-protection.md`. 현재 always-on required check와
  path-filtered `openapi`/frontend check의 T-203 이후 승격 조건을 분리해 문서화한다.

### 2.8 T-101 MV 시범 도입 (선택)

- `docs/performance.md §9.3` 사양 — read >> write 비율 측정 + 시범 도입
- `mv_features_place_with_detail` 1건만 시범 → 1주 운영 + EXPLAIN diff
- 결과에 따라 ADR-035+ 신설 가능성

### 2.9 T-102 pg_prewarm 운영 검토 (선택)

- `docs/performance.md §9.5` 사양 — P99 SLO 측정 후 도입 검토
- 운영 환경 결정 사항

### 2.10 KNPS `visitor_statistics` timeseries 처리 (연기 dataset)

- Sprint 3에서 미루기로 한 경우 Sprint 5에 timeseries 테이블 설계 + 적재
- 본 라이브러리 범위 외라면 raw 보존만 → TripMate 분석 도구로 위임

### 2.11 후속 ADR 검토

- **ADR-035+** 후보:
  - 신규 provider 추가 절차 표준 (체크리스트)
  - `@krtour/map-marker-react` npm 게시 자동화 (release / version sync)
  - `core.feature_consistency_reports` Phase 2 알림 sink
    (Slack/Telegram/Sentry)
  - Sprint 2 SHP/GeoJSON parsing 위치 결정 정식화
  - MV 도입 결정 (T-101)
  - pg_prewarm 도입 결정 (T-102)

## 3. Sprint 5 ADR/T 항목 진척

| 항목 | 상태 (진입 시) | DoD (Sprint 5 종료 = 운영 진입) |
|------|---------------|-------------------------------|
| ADR-033 (정합성 단계 도입) | accepted (Sprint 1) | Phase 2 (F4~F8 + Dagster 게이트) 적용 + swap 차단 동작 |
| ADR-017 (보관 정책) | accepted (Sprint 1) | place 무기한, event +20y, notice +1y, weather +30d purge 동작 |
| T-200 (batch DAG + 게이트) | done (2026-06-04) | Dagster batch + consistency_check + mv_refresh 차단/추적 |
| T-201b (Phase 2) | partial | F4 완료, F6 구현. 남은 F5/F7/F8 + dry-run report |
| T-202~204 | done | T-202 pre-commit hook + T-203 CI full matrix + T-204 branch protection 매뉴얼 완료 |
| ADR-016 (Record Linkage 가중치) | accepted | 5 sprint 전체 검증 후 가중치 조정 PR (필요 시) |

## 4. 운영 진입 게이트 (DoD of Sprint 5)

운영 진입 = TripMate가 본 라이브러리를 production에서 사용. 다음 모두
충족:

- [ ] 14+ provider 모두 적재 안정 (실 fixture 통합 테스트 green)
- [ ] ADR-033 Phase 2 (F4~F8 + Dagster 게이트) 동작
- [ ] T-201b~T-204 모두 완료 (T-200은 완료)
- [ ] Coverage bar 80% 유지 (회귀 0)
- [ ] dedup_review_queue 운영 안정 (운영자 검토 routine)
- [ ] `ops.api_call_log` Grafana 패널 가동 (TripMate 측)
- [ ] 디버그 UI 모든 라우터 + frontend 페이지 동작
- [ ] AGENTS.md / SKILL.md / CLAUDE.md / 모든 ADR이 운영 단계 사용자
      대상으로 갱신
- [ ] `docs/journal.md` Sprint 5 종료 회고 + 운영 진입 entry
- [ ] `docs/resume.md` "현재 상태" → "운영 단계 (Sprint 5 완료)" 갱신

## 5. 비목표 (Sprint 5)

- streaming ETL (T-103) — v2 1차 범위 밖
- 신규 provider (ADR-035+ 검토 후)
- TripMate `apps/web` 측 작업 (T-019, 본 저장소 외)

## 6. 위험 / 차단 사유

- **MOIS sibling dedup 정확도**: Sprint 5에서 첫 진입. Sprint 4에서 검증된
  룰이 sibling provider에서도 통할지 검증 필요. 실패 시 ADR-016 가중치
  조정 PR (필요 시 ADR-035로 supersede).
- **Phase 2 Dagster 게이트 첫 운영**: 첫 batch가 F4~F8 위반으로 일제히
  fail 가능 → dry-run report 후 점진 enable.
- **T-200 Dagster batch DAG**: 본 라이브러리는 helper만 — TripMate 측
  Dagster asset 작성 작업이 본 Sprint 외 일정 추가 risk.
- **운영 진입 일정**: Sprint 5 = v2 1차 최종 sprint. 5개 sprint가 모두
  안정 종료해야 운영 진입. 일정 risk 크면 운영 진입을 PoC 단계로 분할
  (예: TripMate beta).

## 7. 종료 조건 = 운영 진입

위 §4 운영 진입 게이트 모두 충족.

이후:
- v2 1차 운영 안정화 (1~2 sprint 정도 회귀 모니터링)
- v2.1 계획 (ADR-035+ 신규 provider, MV, pg_prewarm, streaming 등)
- 별도 sprints/SPRINT-6.md+로 박음 (필요 시).
