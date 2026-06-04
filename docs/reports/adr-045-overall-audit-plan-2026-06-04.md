# ADR-045 전체점검 실행 계획 (T-212)

이 문서는 ADR-045 독립 프로그램화 관련 잔여 task가 끝난 뒤 진행할 전체점검 task의
정본이다. 전체점검은 범위가 넓으므로 `T-212a`~`T-212e`로 나누고, 각 task는 별도
브랜치/PR로 진행한다.

## 1. 시작 조건

- T-208i까지 offline upload API/UI/Dagster 경로가 main에 머지되어 있어야 한다.
- T-205d, T-200, T-201b처럼 batch/root job과 정합성 gate에 직접 영향을 주는 ADR-045
  잔여 task를 먼저 끝낸다.
- 최근 PR의 GitHub Actions 실패는 해당 PR에서 원인 확인과 수정을 완료해야 다음
  task로 넘어간다.

## 2. 점검 관점

### Admin UI

- table 기반 CRUD: features, feature update requests, POI cache targets, offline
  uploads, import jobs, dedup review, integrity issues.
- 지도뷰: bbox/검색/상세/nearby/by-target, 지도 선택과 테이블 선택의 상태 동기화,
  좌표/주소/bjd 결측 표시.
- 이슈 처리: dedup accept/reject/ignore, integrity issue resolve/ignore/reopen,
  geocode/reverse retry, kraddr-geo 주소 채택, 수동 override.
- API debug/test: endpoint별 request builder, response/error 표시, dry-run과 실제
  실행 결과 비교.
- Dagster 운영: 자체 summary UI, webserver embed, schedules/sensors/jobs/runs/assets
  상태, scraping 실패, failure sensor 이벤트.
- 로그: import job event, provider/API error log, system log, offline upload validation
  issue, Dagster failure message.

### API Endpoint

- admin/user OpenAPI profile 분리 유지.
- admin endpoint는 운영자가 보는 상세 정보와 mutation 결과를 충분히 반환한다.
- TripMate/user endpoint는 내부 필드 누출 없이 envelope와 pagination shape가 일관되어야
  한다.
- 에러 응답은 가능하면 `{error:{code,message}}` 계열로 정렬한다. 기존 FastAPI
  `detail` 고착은 T-RV-06과 함께 정리한다.
- debug/test endpoint는 운영 DB를 변경하는 경로와 read-only/dry-run 경로를 명확히
  분리한다.

### DB/API/Frontend 성능

- PostGIS 공간 쿼리는 입력 좌표를 CTE에서 한 번만 변환하고, predicate는
  `coord_5179`/GIST 인덱스를 그대로 사용한다.
- `features/search`, `features/in-bounds`, `/admin/features`, by-target nearby,
  dedup refresh, offline upload load, import jobs 목록은 EXPLAIN 결과를 남긴다.
- 튜닝 전/후는 같은 데이터셋, 같은 파라미터, 같은 반복 횟수로 측정한다.
- krtour-map 코드/DB 인덱스/쿼리로 해결 가능하면 즉시 수정한다. provider API나
  kraddr-geo/rustfs/Dagster 외부 병목이면 원인과 재현 커맨드를 문서화한다.
- frontend table/map은 긴 목록에서 렌더링 지연, hydration/console error, layout shift를
  Playwright와 React Doctor로 확인한다.

### 실데이터

- provider 실데이터 적재는 `.env`의 실제 서비스키와 독립 DB를 사용한다.
- offline upload는 실제 확보 파일을 우선 사용한다. 데이터가 부족하면 실데이터와 같은
  컬럼/값 분포를 가진 증분 CSV/TSV/JSONL 샘플을 만들어 테스트한다.
- `bjd_code`가 없는 행은 `KRTOUR_MAP_KRADDR_GEO_BASE_URL=http://127.0.0.1:9001`
  기준 kraddr-geo REST v2 geocode/reverse로 보강되는지 확인한다.
- 마지막 task에서는 DB를 비우고 처음부터 다시 로드한 뒤 API/UI/Dagster/Playwright까지
  통과 여부를 기록한다.

## 3. T-212 하위 task

### T-212a — Inventory + e2e gap matrix

- 최신 main 기준 route/API/job/sensor/schedule/resource/DB query 목록을 작성한다.
- admin UI route별 필수 workflow와 현재 Playwright coverage를 표로 만든다.
- 빠진 backend endpoint, frontend UI, e2e case, 실데이터 fixture를 task로 쪼갠다.

### T-212b — Admin UI 완결성 보강

- table CRUD와 지도뷰를 운영자가 반복 사용할 수 있는 밀도로 정리한다.
- dedup/integrity/offline validation 이슈의 승인/거절/ignore/reopen 흐름을 화면에서
  직접 테스트한다.
- Dagster 자체 summary UI와 embed를 함께 유지하되, scraping 실패와 run failure message를
  krtour-map UI 안에서 확인할 수 있어야 한다.

### T-212c — API endpoint/error/log contract

- OpenAPI admin/user drift를 먼저 확인한다.
- endpoint shape, error envelope, dry-run, mutation idempotency, route mount 정책을
  점검한다.
- system log/import job event/error log API가 부족하면 구현한다.

### T-212d — 성능 튜닝

- DB 규모별 baseline을 만든다.
- 쿼리별 `EXPLAIN (ANALYZE, BUFFERS)` 결과를 저장하고, index/query 변경 전후를 같은
  조건으로 비교한다.
- PR 본문과 문서에 튜닝 전/후 latency, buffer hit/read, plan 변화, 부작용을 기록한다.

### T-212e — full reload + 실데이터 최종 검증

- 독립 DB를 초기화하고 migration부터 다시 실행한다.
- provider 실데이터 적재, offline upload 실데이터 적재, 증분 데이터 재적재를 수행한다.
- API smoke, admin UI Playwright, Dagster status, DB row count/consistency report,
  kraddr-geo bjd 보강 결과를 최종 리포트에 남긴다.

## 4. 완료 기준

- 각 PR은 GitHub Actions green 후 머지한다.
- Playwright e2e는 admin 핵심 workflow를 route smoke 이상으로 촘촘히 검증한다.
- React Doctor 결과를 확인하고, 새로 만든 화면에서 발생한 경고는 수정하거나 근거를
  남긴다.
- 성능 튜닝 PR은 반드시 측정 전/후 기록을 포함한다.
- 마지막 T-212e는 DB 초기화 후 full reload와 실데이터 테스트 결과를 문서로 남긴다.
