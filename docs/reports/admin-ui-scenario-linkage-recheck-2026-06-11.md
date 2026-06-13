# admin UI/UX 시나리오·연계·실시간성 재점검 (2026-06-11)

## 1. 점검 범위

사용자 지시에 따라 `docs/debug-ui-admin-workflows.md`,
`docs/openapi-admin-contract.md`, `docs/admin-ui-modernization-gap-audit.md`,
`docs/runbooks/admin-ui-screen-checklist.md`, `packages/kor-travel-map-admin/frontend/src/app`,
`packages/kor-travel-map-admin/frontend/src/api`, `packages/kor-travel-map-api/src/kortravelmap/api/routers`,
`packages/kor-travel-map-api/openapi*.json`, TripMate `docs/tasks.md` T-130 및
`docs/kor-travel-map-requirements.md` §6을 대조했다.

현재 프론트엔드 페이지는 17개다.

- `/`, `/features`, `/etl`
- `/admin/features`, `/admin/features/change-requests`, `/admin/issues`,
  `/admin/dedup-reviews`, `/admin/enrichment-reviews`,
  `/admin/feature-update-requests`, `/admin/poi-cache-targets`,
  `/admin/offline-uploads`, `/admin/backups`, `/admin/dagster`
- `/ops/import-jobs`, `/ops/providers`, `/ops/consistency`, `/ops/logs`

현재 admin OpenAPI 경로는 `/v1/admin/*`, `/v1/ops/*`, `/v1/debug/etl/*`,
`/v1/features/*`, `/v1/categories`, `/v1/providers*`로 정리되어 있고, 사용자
OpenAPI는 `/v1/features/*`, `/v1/categories`, `/v1/providers*`만 노출한다.

## 2. 결론

T-218 이후 화면 수와 기본 e2e/a11y 커버는 충분히 성숙했다. 빠진 것은 "목록 화면
존재"가 아니라 운영 시나리오의 마지막 연결부다. 특히 상세 추적, 작업 이벤트
타임라인, provider 정책/실행 유도, 공개 해수욕장/축제 뷰가 아직 1급 화면/계약으로
분리되지 않았다.

현재 구현은 TanStack Query 폴링에 크게 의존한다.

- 실행 중인 `import_jobs`, `feature_update_requests`, `offline_uploads`: 2초 폴링.
- Dagster summary/run detail, 홈 메트릭: 10초 폴링.
- logs, consistency, provider freshness: 수동 새로고침 또는 긴 캐시 유지 시간.

T-212e 같은 전체 재적재, offline upload 적재, feature update request run-now, Dagster run
실패 상세 추적에는 이벤트/로그 tail이 필요하다. 단일 상세 job은 SSE로도 충분하지만,
home/dashboard와 여러 목록을 동시에 갱신하는 admin 콘솔에는 다중화 WebSocket을
도입하는 편이 낫다.

## 3. 빠진 페이지 / 보강이 필요한 페이지

| 우선 | 화면/기능 | 현재 상태 | 보강 |
|---|---|---|---|
| P0 | `/features/[feature_id]` 1급 상세 | `/features` 지도 패널과 `/admin/features` 인라인 검사 패널만 있음 | 상세 경로를 만들고 SourceLink, raw payload, files, issues, overrides/history, nearby, weather를 한 화면에 연결 |
| P0 | `/features/new` 또는 `/admin/features/new` | change request 화면 안의 생성 form만 있음 | 수동 feature 작성 흐름을 별도 경로로 분리. 지도 좌표 선택, geocode/reverse, detail kind별 form, 중복 후보 결과를 연결 |
| P0 | `/ops/import-jobs/[job_id]` | 목록만 있고 프론트엔드 `useImportJob` hook도 없음. 백엔드 단건 GET은 있음 | job 상세 경로, stage 타임라인, payload, error, linked request/upload/Dagster run, cancel, 이벤트 스트림 연결 |
| P0 | job event/error 타임라인 | `/ops/system-logs`, `/ops/api-call-logs`는 있으나 job stage event 테이블/표면 없음 | `ops.import_job_events` + `/v1/ops/import-jobs/{job_id}/events` + 실시간 스트림 |
| P1 | provider 상세 | `/ops/providers`는 bounded freshness list만 있음 | provider 행 클릭 상세. dataset별 sync state, 최근 jobs/errors, 관련 refresh policy, "provider_dataset scope로 update request 생성" 상세 링크 |
| P1 | provider refresh policy UI | DB/repo는 있음, REST/UI 없음 | `/v1/admin/provider-refresh-policies*` 또는 provider detail 내 편집 표면. rate-limit 초과 422 검증 |
| P1 | `/ops/metrics` 단독 화면 | 홈 dashboard에서만 소비 | 운영 상세 분석용 단독 화면은 낮은 우선. 홈 위젯 상세 링크만 먼저 가능 |
| P1 | `/debug/explain`, `/debug/fixtures` | 문서 계획은 있으나 활성 OpenAPI는 ETL preview와 MOIS detail만 있음 | 개발자 진단 화면이 필요하면 debug gate 아래 별도 task로 복원. 운영 admin 핵심은 아님 |
| P1 | T-130 공개 해수욕장/축제 뷰 | 사용자 OpenAPI에 전용 해수욕장/축제 뷰 없음 | `docs/public-views-api.md`의 제안 계약을 바탕으로 `/v1/public/*` 또는 동등 뷰 구현 |

오래된 gap 문서 정정:

- `docs/admin-ui-modernization-gap-audit.md`의 "일반 좌표 기준 `/features/nearby` 없음"은
  현재 OpenAPI 기준으로 해소됐다. 단, feature 상세 경로가 없어 UI에서 아직 충분히
  소비하지 않는다.
- offline upload CSV/TSV preview/validation/load는 현재 프론트엔드 hook과 화면에 연결되어
  있다. 남은 것은 live event/cancel, 대용량 실행 중 진행률 체감이다.
- `/admin/providers/{provider}/datasets/{dataset_key}/runs`는 T-207b에서 취소됐고,
  provider 강제 실행은 `/v1/admin/feature-update-requests`의 `provider_dataset` scope로
  유도하는 것이 정본이다. 중복 run 엔드포인트를 되살리지 않는다.

## 4. 기능별 연계 상태

잘 연결된 흐름:

- Feature 변경: `/admin/features/change-requests`가 `POST/PATCH/DELETE /v1/admin/features*`
  및 approve/reject를 한 화면에서 처리한다.
- POI target: upsert/delete 후 `/v1/features/nearby/by-target` 조회와 cache invalidation이
  연결되어 있다.
- Offline upload: upload → preview → validation → load가 연결되어 있고 tabular mapping
  UI도 있다.
- Dedup/enrichment review: 목록, 결정 mutation, cache invalidation이 연결되어 있다.
- Dagster: summary, run detail, NUX seen, iframe embed가 연결되어 있다.
- Logs: system log와 API call log가 `/ops/logs`에서 분리 tab으로 연결되어 있다.

보강할 연계:

- Feature 상세는 상세 경로가 없어 원천/source/file/issue/history와 nearby가 흩어져 있다.
- Import job은 목록 row가 단건 detail이나 Dagster run으로 이어지지 않는다.
- Feature update request, offline upload, import job, Dagster run이 같은 작업을 가리켜도
  화면 간 상세 링크가 약하다.
- Provider freshness row에서 해당 provider/dataset의 최근 jobs, policy, run-now 요청 생성으로
  이어지는 경로가 없다.
- `/ops/logs`는 job stage event가 아니라 system/API log라, provider load 실패 원인을
  단계별로 따라가기 어렵다.

## 5. WebSocket / SSE 도입 기준

REST는 계속 정본이다. WebSocket은 admin UI에서 "지금 변하는 것"을 델타로
받아 TanStack Query cache를 invalidate하거나 patch하는 용도다. mutation은 REST로
유지한다.

### 5.1 적극 도입할 엔드포인트

| 엔드포인트 | 목적 | 구독 topic / payload |
|---|---|---|
| `WS /v1/ops/live` | admin dashboard와 여러 목록의 공통 실시간 버스 | `import_jobs`, `feature_update_requests`, `offline_uploads`, `dagster_runs`, `provider_sync`, `ops_logs`, `review_queues` |
| `WS /v1/ops/import-jobs/{job_id}/events` | job 상세 진행률/로그 tail | `job.status`, `job.progress`, `job.stage`, `job.event`, `job.error`, `job.finished` |
| `WS /v1/admin/feature-update-requests/{request_id}/events` | request→job→Dagster 진행 연결 | `request.status`, `scope.resolved`, `job.linked`, `job.event`, `request.finished` |
| `WS /v1/admin/offline-uploads/{upload_id}/events` | upload validation/load 진행 | `upload.status`, `validation.issue`, `job.linked`, `job.event`, `load.finished` |
| `WS /v1/ops/dagster/runs/{run_id}/events` | Dagster run 실패 상세 추적 | `run.status`, `run.event`, `run.error`, `run.finished` |

### 5.2 SSE로 충분한 대체 경로

- 단일 job 상세의 단방향 log tail은 `GET /v1/ops/import-jobs/{job_id}/events?cursor=...`
  페이지네이션 + `GET /v1/ops/import-jobs/{job_id}/stream` SSE로도 충분하다.
- WebSocket을 먼저 구현하더라도 SSE 또는 cursor 기반 events API는 장애/테스트/CLI
  소비를 위해 같이 둔다.

### 5.3 지금은 폴링 유지가 나은 표면

- `/v1/categories`, `/v1/providers` freshness list의 idle 상태.
- `/v1/features/search`, `/v1/features/in-bounds`, `/v1/features/nearby` 같은 조회 쿼리.
- dedup/enrichment/change request 목록의 idle 상태. 단, 새 pending count는
  `WS /v1/ops/live`의 `review_queues` topic으로 badge만 갱신한다.

## 6. T-130 관련 추가 확인

TripMate T-130은 비로그인 `/public/*` 구현이며, 현재 차단 사유는 kor-travel-map
`openapi.user.json`에 해수욕장/축제 전용 뷰와 닫힌 detail 스키마가 없다는 점이다.
별도 사양은 `docs/public-views-api.md`에 추가했다.

구현 전 확인할 drift:

- 해수욕장 category가 문서(`01050100` `TOURISM_NATURE_BEACH`)와 현재 provider 코드
  (`01020300` `TOURISM_NATURAL_LANDSCAPE_COAST_ISLAND`, `place_kind="beach"`)에서 다르다.
  공개 뷰는 1차 판별을 `detail.place_kind="beach"`로 두고, category 정렬은 별도
  migration/데이터 보정 task에서 판단한다.
- KHOA 해수욕장 폭/길이 필드는 ETL 문서에는 있으나 현재 provider Protocol/변환은
  `beach_kind`, `image_url` 중심이다. 공개 뷰 구현 전에 상류 모델과 변환 필드를
  다시 맞춘다.
- 축제 `EventDetail`은 `starts_on`, `ends_on`, `venue_name`, `tel`, `payload.organizer_name`,
  `payload.provider_org_name`까지는 담고 있다. TripMate public 상세가 요구하는
  `festival_content`, `auspc_instt_name`, `suprt_instt_name`, `reference_date`는
  datagokr/visitkorea enrichment 매핑을 확정해야 한다.

## 7. 후속 task

본 점검의 실행 task는 `docs/tasks.md`의 T-221(admin UI linkage/realtime)와
T-222(TripMate T-130 공개 뷰 API)로 등록한다.
