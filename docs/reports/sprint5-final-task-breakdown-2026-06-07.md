# Sprint 5 운영 진입 잔여 task 상세화 — 2026-06-07

## 1. 기준

- 기준 브랜치: `origin/main` after PR#273
  (`docs: record opinet provider enhancement (python-opinet-api#8) + T-RV-04b status`).
- Sprint 5 종료 정의: `docs/sprints/SPRINT-5.md` §4 운영 진입 게이트를 모두
  충족해 TripMate가 krtour-map을 production 연동 대상으로 사용할 수 있는 상태.
- 본 문서는 구현을 새로 끝낸 것이 아니라, 남은 작업을 1-PR 단위로 바로 실행할 수
  있게 상세화한 백로그 정본이다. 실제 완료 여부의 단일 정본은 계속
  `docs/resume.md`와 `docs/tasks.md`다.

## 2. 완료된 기반

- ADR-045 독립 프로그램화의 핵심 DB/API/Dagster/Docker/backup-restore 기반은
  구현 완료.
- T-200, T-201b, T-202, T-203, T-204, T-209, T-212a, T-212c, T-213a~h는 완료.
- T-RV-04b provider live fetcher wiring은 `opinet_stations` krtour-side wiring만
  남았다. `python-opinet-api#8`은 merged(v0.2.0)되어 bounded bbox enumeration을
  제공한다.

## 3. 권장 PR 순서

### S5-1. T-RV-04b-opinet-krtour-wiring

**목표**: `opinet_stations`를 krtour Dagster provider live resource로 연결한다.

**결정할 것**:
- 기본 운영 scope는 전국 nightly가 아니다. OpiNet public API가 `aroundAll` 반경
  5km 중심이라 전국 bbox enumeration은 호출량이 과도하다.
- 1차 구현은 둘 중 하나로 고정한다.
  - bounded bbox: 운영자가 settings/env로 bbox와 grid radius를 명시한다.
  - POI-target scope: active `ops.poi_cache_targets` 주변만 opinet station refresh
    대상으로 삼는다.

**수정 후보**:
- `packages/krtour-map-dagster/src/krtour/map_dagster/provider_fetchers.py`
- `packages/krtour-map-dagster/src/krtour/map_dagster/resources.py`
- `packages/krtour-map-dagster/src/krtour/map_dagster/definitions.py`
- `packages/krtour-map-dagster/tests/test_provider_fetchers.py`
- 필요 시 `src/krtour/map/providers/opinet.py` Protocol 재정렬

**DoD**:
- provider `Station` shape에 맞춰 `OpinetStationItem` Protocol을 ADR-044 기준으로
  재정렬한다. `tel`/`lpg_yn`처럼 bbox enumeration에 없는 값은 detail N+1을 할지,
  nullable/미적재로 둘지 PR 안에서 명시한다.
- bbox 또는 POI-target scope가 설정되지 않으면 guard가 명확한 메시지로 실패한다.
- fake `python-opinet-api` client 기반 단위 테스트와 Dagster resource wiring 테스트를
  추가한다.
- 실 API 호출 검증은 T-212e live reload 리포트로 넘기되, PR 본문에 그 한계를 적는다.

### S5-2. T-212b-admin-ui-completion

**목표**: 운영자가 admin UI만으로 feature 검토, 이슈 처리, 로그 확인, Dagster 상태
확인을 수행할 수 있게 한다.

**권장 분리**:
- `T-212b-1`: `/admin/features` table/detail/map review + weather panel.
- `T-212b-2`: `/admin/issues` resolve/ignore/reopen/retry/manual override workflow +
  `/ops/logs` system/API call log 화면.
- `T-212b-3`: `/admin/dagster` schedule/sensor tick/failure drilldown 보강 +
  offline upload/POI cache target 주요 mutation e2e.

**DoD**:
- 모든 신규 화면은 `openapi.json`/frontend generated type 또는 기존 typed hook을
  사용한다.
- table/list 화면은 keyset cursor와 empty/error/loading 상태를 갖는다.
- Playwright는 smoke를 넘어서 최소 1개 happy path와 1개 error/empty path를 검증한다.
- React Doctor, `npm run type-check`, `npm run build`, 관련 Playwright 결과를 PR에
  기록한다.

### S5-3. T-212d-perf-baseline-and-tuning

**목표**: 운영 진입 전 hot path의 SQL/API/frontend 성능 기준선을 문서화하고, 명백한
인덱스/쿼리 병목은 같은 PR에서 고친다.

**측정 대상**:
- `/features/search`
- `/features/in-bounds`
- `/features/nearby`
- `/admin/features`
- `/ops/import-jobs`
- dedup refresh
- consistency F6/F8

**권장 범위**:
- 1차 PR은 seeded PostGIS/testcontainers로 재현 가능한 EXPLAIN baseline을 수집한다.
- 실 운영 규모 또는 live provider full reload 뒤의 측정은 T-212e 최종 리포트로 넘긴다.
- frontend는 긴 목록, 지도 marker/list 동기화, hydration/console error, layout shift를
  Playwright와 React Doctor로 기록한다.

**산출물**:
- `docs/reports/t-212d-perf-baseline-YYYY-MM-DD.md`
- 필요 시 인덱스/쿼리 변경 migration 또는 repo SQL 수정
- 변경 전/후 EXPLAIN 요약과 남은 병목 목록

### S5-4. T-212e-live-full-reload-final-verification

**목표**: 깨끗한 DB/RustFS 상태에서 실제 provider와 offline upload를 끝까지 적재해
운영 진입 가능 여부를 판정한다.

**검증 흐름**:
1. standalone stack 기동 전 고정 포트와 기존 container/volume 상태 확인.
2. app DB, Dagster metadata DB, RustFS test volume을 초기화하거나 staging 환경으로 분리.
3. alembic head 적용.
4. provider asset full reload 실행.
5. offline upload CSV/TSV/JSONL happy/error path 실행.
6. kraddr-geo REST v2 bjd 보강 확인.
7. consistency gate와 dedup queue 상태 확인.
8. admin/user API smoke와 Windows Playwright e2e 실행.
9. backup/restore smoke 또는 최근 backup artifact 검증.

**산출물**:
- `docs/reports/t-212e-live-full-reload-final-YYYY-MM-DD.md`
- provider별 성공/실패/skip 표
- import job/Dagster run id 목록
- consistency report id와 severity summary
- known issue와 운영 전 반드시 막아야 할 blocker 목록

### S5-5. T-210-tripmate-integration-cleanup

**목표**: krtour-map이 HTTP/OpenAPI 독립 프로그램이라는 경계를 TripMate 쪽에도
반영한다.

**분리 기준**:
- `T-210a`: krtour-map repo에서 `docs/tripmate-rest-api.md`와 generated OpenAPI 정합
  확인.
- `T-210b`: TripMate repo 문서에서 직접 import, 공유 DB, TripMate-owned Dagster 문구를
  ADR-045 모델로 supersede.
- `T-210c`: TripMate `apps/etl`에 남은 krtour-map Dagster skeleton 이관 또는 삭제.
- `T-210d`: TripMate backend `httpx` client 추가. 운영 코드는 `python-krtour-map`을
  import하지 않는다.
- `T-210e`: TripMate frontend TypeScript client/codegen과 CI drift gate.

**DoD**:
- TripMate 운영 코드에 `from krtour.map` import가 없다.
- TripMate DB에서 krtour-map DB로 직접 연결하는 설정이 없다.
- krtour-map user OpenAPI와 TripMate generated type이 같은 commit 기준임을 문서화한다.

### S5-6. Sprint 5 closure

**목표**: 운영 진입 선언에 필요한 문서와 gate를 닫는다.

**체크리스트**:
- `docs/sprints/SPRINT-5.md` §4 운영 진입 게이트를 실제 결과 기준으로 `[x]` 갱신.
- `docs/journal.md`에 Sprint 5 종료 회고 + 운영 진입 entry 추가.
- `docs/resume.md` 상단을 "운영 단계 (Sprint 5 완료)"로 갱신.
- `AGENTS.md`, `SKILL.md`, `CLAUDE.md`, ADR index가 운영 단계 사용자 대상으로
  맞는지 최종 스윕.
- coverage 80 유지, CI green, OpenAPI drift green을 확인.

## 4. 지금 바로 집기 좋은 작업

현재 `origin/main` 기준 가장 작은 다음 PR은 **T-212d seeded perf baseline**이다.
이유:
- T-RV-04b-opinet은 운영 scope 결정이 먼저 필요하다.
- T-212b는 admin UI 변경 폭이 크고 기존 로컬 작업과 충돌 가능성이 높다.
- T-212e는 실 provider key와 live stack이 필요하다.
- T-210은 T-212b/d/e 결과가 안정된 뒤 TripMate repo와 맞추는 편이 낫다.

T-212d는 실데이터 없이도 seeded PostGIS와 현재 SQL로 시작할 수 있고, 이후 T-212e
리포트의 측정 항목을 줄여 준다.
