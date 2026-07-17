# admin ops 통합 재작성 플랜 — 파이프라인/데이터셋 2페이지 (2026-07-14 확정)

> 사용자 지시: dagster job·provider 기능이 여러 admin 페이지에 분산되어 상태 확인/조작 동선이
> 불편 → **2페이지로 통합 재작성**. 호환성·기존 문서계약에 매이지 않고 깔끔한 코드/구조,
> 기능적으로 완결되고 직관적인 REST API, 일관되고 조작 용이한 UI를 우선한다.
>
> 본 문서는 초안 v1에 대한 **적대적 설계 리뷰 2인(A: 백엔드·REST·데이터 모델 / B: UX·운영
> 워크플로·e2e·분할)** 의 발견(A: S1 1·S2 6·S3 8, B: S1 3·S2 7·S3 6)을 전량 반영한 확정판이다.
> 결정 요지는 ADR-064, 실행 단위는 `docs/tasks.md`의 `T-ADM-C1`~`C7`.

## 0. 현황 요약 (전수 조사)

관련 기능이 **7개 페이지 + 홈 위젯**(작업 자동화 `/admin/dagster` · Provider 상태 `/ops/providers` ·
적재 작업 `/ops/import-jobs`(+상세) · 갱신 요청 `/admin/features/update-requests`(+레거시 별칭) ·
ETL 미리보기 `/etl` · 운영 로그 `/ops/logs`의 Job events 탭)과 **6개 라우터 + 4개 인증
게이트/피처플래그 그룹**(무인증 ops / public-key features / admin frontend / debug)에 분산.
같은 갱신요청 큐를 두 화면이 다른 액션 세트로 노출, `useImportJobEvents` 훅 이름 충돌,
dagster run↔import job 관계는 외부 Dagster UI 링크로만 연결. 상세 조사는 본 플랜 수립 시
전수 조사 결과(§4 재배선 체크리스트에 반영)를 따른다.

## 1. 목표 상태 — 2페이지

### 페이지 ① `/ops/pipeline` — 파이프라인 (실행·작업 중심)

"무엇이 돌고 있고, 무엇이 실패했고, 무엇을 실행/중지할 수 있나"의 단일 화면.

- **상단 상태 스트립**: Dagster 연결 상태·run 카운트·실행중 적재작업·대기 갱신요청·최근 24h 실패
  + **sensor 상태**(큐 sensor `feature_update_request_queue_sensor`·failure sensor — sensor가
  꺼지면 갱신요청 큐가 침묵 정지하는 실장애 모드를 상단에서 즉시 노출).
- **실행 타임라인(메인, DB 스파인)**: `ops.import_jobs` ∪ `ops.feature_update_requests`의
  **DB-only UNION** 목록 — 공유 keyset cursor `(created_at DESC, id DESC)` + `kind`
  discriminator. Dagster run은 목록 cursor에 **섞지 않는다**(GraphQL은 cursor 없는 휘발 소스 —
  이종 병합은 페이지 경계 중복/구멍·Dagster 다운 시 cursor 파손). 연결된 dagster run은
  실컬럼(`dagster_run_id`)으로 행 속성/딥링크에 병합. 필터: kind/상태/provider/기간.
  행 확장 drawer = 이벤트 로그(cursor 전진 페이지네이션 승계), 실패 원인, 연결 개체,
  요청 payload, Dagster UI 외부 링크(GraphQL degrade 시 탈출구 — 유지).
- **Dagster runs 패널(보조)**: GraphQL 최근 run N건(limit, cursor 없음) — import job을 만들지
  못하고 죽은 순수 Dagster 실패의 가시성 담당. `status=unavailable` graceful degrade 계약 유지.
- **전역 이벤트 뷰**: 기존 `/ops/logs` Job events 탭의 전역 스트림(level/provider/dataset 필터,
  "어느 job인지 모르는 상태에서 최근 error 훑기")을 페이지 ①의 이벤트 탭으로 승계.
- **스케줄 패널**: 목록(cron·다음 실행·상태·override 병합) + 조작(즉시 실행/시작/중지/cron 수정).
  cron 수정의 지연 반영(코드위치 reload) 안내 문구 유지. `default` 명령은 제거 —
  `PATCH {cron_schedule: null}` = override 삭제로 통합.
- **조작**: import job cancel, update request cancel/**run-now(동일 canonical job 우선
  dispatch, 200 멱등)**, 새 갱신 요청 생성 dialog(**6-type scope union 전량**:
  feature_ids/center_radius/sigungu_by_radius/bbox/provider_dataset/
  cache_target_keys + 인증 actor/`reason` 감사 필드 + 별도 preview/priority — API 계약 축소 금지,
  UI 기본 노출은 provider_dataset·center_radius로 하되 전체 scope 선택 가능).
- **실시간**: 기존 `/ops/live` WS 재사용(이미 3개 화면이 `dagster_runs` topic 구독 중 — "미활용"
  아님). 자동 갱신은 1페이지에 한정하고 그 외는 "새 실행 N건" 배지 + 수동 반영(조사 중 목록
  재정렬 방지). 순수 Dagster 실패는 WS로 오지 않으므로(스냅샷이 job-연결 run만 파생) Dagster
  패널은 GraphQL 폴링 유지.
- **NUX**: `/admin/dagster`의 Dagster NUX(seen 마킹)는 페이지 ①로 승계.
- **MOIS 선행작업 안내**: 갱신 요청 dialog에서 provider=mois 계열 선택 시 조건부 경고(소스 sync
  최근 성공 시각 표시)로 이전 — 하드코딩 배너 제거.

### 페이지 ② `/ops/datasets` — 데이터셋 (상태·정책 중심)

"각 provider×dataset이 얼마나 신선하고, 정책이 뭐고, 문제가 뭔가"의 단일 화면.

- **데이터셋 그리드(메인)**: provider×dataset×**sync_scope 3원** 전 행(카탈로그 기반 —
  `never_run` 포함, never_run vs stale 구분 승계) — 신선도(마지막 성공/다음 예정/연속 실패),
  갱신 정책 요약, 최근 실행 결과, 해당 dataset integrity 이슈 카운트 배지. 요약 배지
  (실패/오래됨/미실행).
- **행 상세 drawer**: sync_state·cursor 내역, 최근 실행(→페이지 ① 딥링크), 최근 이벤트,
  갱신 정책 편집(3원 행 → 2원 정책 `{provider}/{dataset}` 매핑 규칙 명시), **ETL 미리보기**
  (기존 `/etl`의 fixture만 흡수 — raw live HTTP preview는 ADR-044 위반으로 신규 제품
  API에서 제거),
  "생성된 Feature 보기"(`/admin/features?provider=&dataset_key=`) 링크, **"지금 갱신" 인라인
  폐루프** — request 생성 후 페이지 이동 없이 drawer에서 `feature_update_request:{id}` WS
  topic으로 상태를 추적하고 완료 시 행 신선도 즉시 갱신(페이지 ①로는 "자세히" 링크만).
- 정합성 리포트/이슈 큐 자체는 `/ops/consistency` 존치(범위 밖).

### 폐기·이동

- 폐기 라우트(redirect 없음): `/admin/dagster`, `/ops/providers`, `/ops/import-jobs`(+상세),
  `/admin/features/update-requests`, `/admin/feature-update-requests`, `/etl`.
- `/ops/logs`: system/api 로그 탭 존치, Job events 탭은 페이지 ①로 흡수 후 제거.
- 홈 위젯: Dagster 카드→`/ops/pipeline`, 적재작업 카드/테이블→`/ops/pipeline`,
  `/ops/metrics`는 존치(홈 지표 소스) — overview와 집계 중복은 홈이 overview를 쓰도록 후속
  판단(T-ADM-C5에서 결정).

## 2. 새 REST API

원칙: 페이지 1개 = 리소스 그룹 1개, **단일 게이트**. 신규 2그룹은 `ops_routes_enabled` 플래그
+ `include_router(..., dependencies=[Depends(require_admin_frontend)])`로 마운트 — 조작(POST/
PATCH/PUT)이 포함되므로 기존 무인증 ops 패턴을 쓰면 **현행 admin 게이트(갱신요청·정책) 대비
다운그레이드**가 된다. admin frontend는 전 호출을 BFF 프록시로 보내므로 프론트 추가 작업 없음.
예외 명문화: `/ops/health-deep`(readiness probe)·`/metrics`는 게이트 밖 존치한다.
`/v1/ops/live`는 C7A에서 same-origin ticket BFF가 로그인 session을 확인한 뒤 발급한
60초 signed WebSocket subprotocol ticket을 FastAPI가 accept 전에 검증한다. 구 무게이트
직결 결정은 이 보강 결정으로 폐기한다. 상세 정본은
`docs/reports/admin-ops-c7a-live-contract-2026-07-17.md`다.

### pipeline 그룹 (`/v1/ops/pipeline/*`)

| 경로 | 메서드 | 역할 |
|---|---|---|
| `/ops/pipeline/overview` | GET | 상태 스트립 집계(dagster 요약+sensor+작업/요청 카운트) |
| `/ops/pipeline/executions` | GET | DB-only UNION 목록(keyset cursor, kind/상태/provider/기간 필터) |
| `/ops/pipeline/executions/{kind}/{id}` | GET | 실행 상세(+이벤트 cursor, 연결 개체) — kind enum `import_job\|update_request` |
| `/ops/pipeline/executions/{kind}/{id}/cancel` | POST | 종류별 cancel 위임 |
| `/ops/pipeline/events` | GET | 전역 job 이벤트 스트림(level/provider/dataset/job 필터) |
| `/ops/pipeline/dagster-runs` | GET | 보조 패널용 최근 run(GraphQL, limit, degrade 허용) |
| `/ops/pipeline/dagster-runs/{run_id}` | GET | 개별 run event/failure 상세(Dagster event cursor 전진 페이지네이션) |
| `/ops/pipeline/schedules` | GET | 스케줄 목록(override 병합) + sensor 상태 |
| `/ops/pipeline/schedules/{name}` | PATCH | cron 수정(`cron_schedule: null` = override 삭제) |
| `/ops/pipeline/schedules/{name}/commands` | POST | `{command: run\|start\|stop\|reset}` 4종 |
| `/ops/pipeline/requests` | POST | 신규 갱신 요청 201 또는 같은 활성 계획 재사용 200 — 6-type scope·카탈로그·geo resolver 계약 |
| `/ops/pipeline/requests/{id}/run-now` | POST | 같은 canonical job 우선 dispatch(200 멱등, terminal 409) |

Dagster 목록·overview는 DB 운영 화면이 Dagster 장애 때문에 사라지지 않도록 기존의
`200` graceful degrade를 유지한다. 반면 선택한 개별 run 상세는 성공한 조회만 `200`이고,
Dagster `RunNotFoundError`는 `404 DAGSTER_RUN_NOT_FOUND`, 연결 실패는
`503 DAGSTER_UNAVAILABLE`, GraphQL/설정/응답 오류는 `502 DAGSTER_QUERY_FAILED`의
RFC7807 `application/problem+json`으로 승격한다. event cursor는 DB timeline cursor와
무관한 Dagster opaque cursor이며 전진 방향으로만 사용한다. `failure_reason`과
`failure_events`는 현재 event page 범위이므로 `event_has_more=true`일 때 전체 run의 실패
원인이 없다고 해석하지 않는다.

새 UI는 Dagster iframe을 쓰지 않으므로 `/ops/pipeline/nux-seen`을 제공하지 않는다.
구 `/ops/dagster/nux-seen`은 구 화면 삭제 PR 전까지만 legacy 경계에 남긴다.

### datasets 그룹 (`/v1/ops/datasets/*`)

| 경로 | 메서드 | 역할 |
|---|---|---|
| `/ops/datasets` | GET | provider×dataset×scope 그리드(서버 freshness+실제 schedule+정책+dataset/provider 이슈+최신 DB 실행 batch join) |
| `/ops/datasets/detail?provider=...&dataset_key=...&sync_scope=...` | GET | 선택한 3원 행 상세 — scope 배열·exact scope 최근 실행, sync states·cursor·이벤트·정책 |
| `/ops/datasets/refresh-policy?provider=...&dataset_key=...` | PUT | canonical catalog 정책 upsert(2원, orphan 409) |
| `/ops/datasets/preview?provider=...&dataset_key=...` | POST | fixture-only typed ETL dry-run(`max_items`, timeout, 외부 호출 budget 0, `truncated`) |

그리드의 시간 필드는 의미를 합치지 않는다. `eligible_after`는 provider 호출 가능
시각, `schedule.next_scheduled_at`은 RUNNING Dagster schedule의 실제 future tick,
`freshness.due_at`은 명시적 정책 `stale_after_minutes`에서 계산한 SLA 시각이다.
Dagster schedule identity는 definition tag 두 개를 exact match한 뒤 provider alias
정본으로 canonicalize하며 schedule 이름으로 추론하지 않는다. 전체 schedule은 요청당
GraphQL 한 번만 읽고 실패 시 DB 그리드는 200을 유지한 채 `unknown`으로 degrade한다.

- "지금 갱신" 별도 숏컷 엔드포인트는 **두지 않는다** — datasets 페이지가
  `POST /ops/pipeline/requests`(provider_dataset scope)를 직접 호출(리소스 생성 중복 제거).

### 존치·삭제 확정

- **존치(공용, PinVi 계약)**: `GET /v1/providers`, `GET /v1/providers/{p}/last-sync` —
  `openapi.user.json` 29 path에 포함 + `docs/integration-map.md` PinVi read 표면 + user-client
  surface assertion CI. "호환성 무시"는 admin 표면 한정이며 별개 시스템의 read 계약은 불변.
  소형 public 라우터로 분리 이동.
- **삭제**: `routers/dagster.py`(9), providers의 `/ops/providers*` 2개,
  `provider_refresh_policies.py`(3), ops의 import-jobs 5개 + `/ops/import-job-events`,
  `feature_update_requests.py` 양 prefix 10개, `etl.py`(3).
- **데이터 모델**: `ops.import_jobs`에 `dagster_run_id TEXT` 실컬럼 + payload 백필 + 부분
  인덱스(alembic 1건, T-ADM-C3) — 현재 WS hot path(기본 2s poll)가 payload JSONB `?` 연산
  풀스캔(전례: feature_id 검색 #639). `ops_live`의 dagster_runs 스냅샷/역조회도 실컬럼으로 전환.
- repo 계층 신규 함수(UNION 목록 등)는 `kortravelmap.infra`(메인 lib — coverage
  `fail_under=80`+mypy strict 범위), 서비스/라우터는 `kortravelmap.api`
  (packages/kor-travel-map-api — 메인 lib fastapi 금지 contract).

## 3. UI 구조(프론트)

- `src/app/ops/pipeline/`·`src/app/ops/datasets/` 신설. 공용 DataTable·drawer·StatusBadge 재사용.
- api 훅: `api/pipeline.ts`·`api/datasets.ts` 신설. 기존 `useImportJobEvents` 이름충돌
  (importJobs.ts vs ops.ts) 해소는 구 훅 삭제로 자연 해결.
- 딥링크: `/ops/pipeline?kind=&status=&provider=&execution={kind}:{id}&schedule={name}
  &load_batch_id=&parent_job_id=` (curated-features의 `?schedule=` 2곳, consistency의
  `load_batch_id`, 자식 job 탐색 `parent_job_id` 승계 — 현행 `/admin/dagster?schedule=`은
  소비 코드가 없는 죽은 파라미터였으므로 재작성에서 실동작하게 구현),
  `/ops/datasets?provider=&dataset=&sync_scope=&panel=policy|preview|history`.
- **진입점 재배선 체크리스트(T-ADM-C6a — 1급 작업)**:
  - `components/entity-link.tsx` — importJob/loadBatch/provider/updateRequest kind **단일 URL
    테이블** 재매핑(14개 화면에 전파).
  - 존치 화면 직접 href: `components/feature-detail-view.tsx`(provider 링크),
    `admin/offline-uploads`(job 링크 3곳), `ops/consistency`(loadBatch), `ops/logs`(job 상세),
    `home-client.tsx`(3곳), `features/features-client.tsx`(3곳),
    `admin/curated-features`(schedule 딥링크 2곳), `admin/features`(provider 링크),
    `admin/feature-update-requests/[requestId]`(job 링크).
  - `api/live.ts` invalidateLiveTopic topic→queryKey 매핑, ops.py HATEOAS `_job_links`의 구
    admin URL.
  - mock e2e: 폐기 라우트 참조 spec 19파일(홈 nav 목록 하드코딩 `home-nav`·
    `home-density-matrix` 포함) 재작성/삭제, `e2e/live/admin-scenario-catalog.ts`
    라우트×API 인벤토리 갱신.

## 4. PR 단위 task 분할 (agent A/B 병렬)

| task | 내용 | 담당 | 의존 |
|---|---|---|---|
| T-ADM-C1 | 본 플랜 확정 + ADR-064 + tasks.md 등록 (문서 PR) | 단독 | — |
| T-ADM-C2 | backend datasets 그룹: 라우터+서비스+infra 조회+테스트 + **OpenAPI/types 재생성 포함** | **A** | C1 |
| T-ADM-C3 | backend pipeline 그룹: 라우터+서비스+UNION 조회+alembic(`dagster_run_id`)+테스트 + **OpenAPI/types 재생성 포함** | **B** | C1 |
| T-ADM-C4 | frontend `/ops/datasets` 페이지+훅+mock e2e | **A** | C2 |
| T-ADM-C5 | frontend `/ops/pipeline` 페이지+훅+mock e2e (+홈 위젯 소스 결정) | **B** | C3 |
| T-ADM-C6a | 존치 화면 링크 재배선(§3 체크리스트) — 구 페이지 제거 **전** 독립 PR | 선착 | C4·C5 |
| T-ADM-C6b | 구 라우트·라우터·훅·mock spec 삭제 + nav/홈 정리 + OpenAPI 재생성(삭제분) | 선착 | C6a |
| T-ADM-C7 | live e2e 재작성 + n150 검증 리포트 | 선착 | C6b |

- **생성물 rebase 규칙(명문)**: `openapi.json`·`openapi.user.json`·admin `src/api/types.ts`는
  각 백엔드 PR에서 재생성해 포함한다(`openapi-drift`·`gen:types:check`가 branch protection).
  rebase 시 생성물 충돌은 **rebase 후 재생성으로 해소**(수동 병합 금지). `app.py`·
  `routers/__init__.py` 충돌은 include 블록 단위로 분리 배치해 최소화.
- 분할 원칙: A=datasets 축, B=pipeline 축. 잦은 rebase(origin/main). task 완료 시 상대 agent의
  2일치 PR(닫힘 무관, 리뷰 반영 PR 제외)을 적대적 리뷰→코멘트→이슈→수정 후 머지.
- 각 구현 PR: 테스트 전 적대적 리뷰어 2명 → live UI e2e(아래 통제) → n150 prod 최종 검증.

## 5. live e2e 통제 (T-ADM-C7 수용 기준 — "파괴적 허용"의 경계)

- 기존 live 게이트 체계 승계: PART A(무게이트 read) / PART B(`E2E_ADMIN_WRITE`·
  `E2E_DAGSTER_WRITE` 게이트, `finally` 원상복구 — 스케줄 start/stop·cron 복원) /
  PART C(`E2E_DAGSTER_RUN=1` + `E2E_DAGSTER_JOB`으로 운영자가 SAFE job 지명).
- 갱신 요청 write는 SAFE provider(`python-kma-api`) + 좁은 `center_radius` + `finally` cancel
  승계. **쿼터-민감 provider(OpiNet 등) live 시나리오 금지 목록** 명시. dry_run 우선.
- ETL live preview e2e는 쿼터 provider 제외.
- n150 4코어 제약: per-file 저부하 실행 순서표를 검증 리포트에 포함(전체 스위트 full-run 금지).

## 6. 닫힌 결정 (초안 v1의 열린 질문)

1. ~~id 스킴~~ → DB-only UNION + `/{kind}/{id}` 경로(§2).
2. ~~ops 인증~~ → 신규 2그룹 admin 게이트 마운트, health/metrics/WS 예외 명문(§2).
3. ~~ETL debug 플래그~~ → datasets 그룹 흡수로 개선(현행 prod 무게이트 노출 해소), live만
   opt-in flag(§2).
4. ~~Dagster degrade~~ → 목록 cursor에서 GraphQL 배제로 구조적 해소, 보조 패널만 degrade(§1).
5. ~~commands 단일화~~ → 4종 enum + PATCH null 통합(§2).
6. ~~파괴적 e2e 범위~~ → §5 통제로 확정.
