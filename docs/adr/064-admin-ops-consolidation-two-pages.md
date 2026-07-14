# ADR-064 — admin ops 표면을 파이프라인/데이터셋 2페이지로 통합 재작성한다

- 상태: accepted
- 날짜: 2026-07-14
- 결정자: human + Claude
- 관련: `docs/reports/admin-ops-consolidation-plan-2026-07-14.md`(상세 설계 정본),
  `docs/tasks.md` `T-ADM-C1`~`C7`

## 컨텍스트

Dagster job·provider 운영 기능이 admin UI 7개 페이지 + 홈 위젯(작업 자동화 ·
Provider 상태 · 적재 작업(+상세) · 갱신 요청(+레거시 별칭) · ETL 미리보기 · 운영
로그 Job events 탭)과 백엔드 6개 라우터 · **4개 인증 게이트/피처플래그 그룹**(무인증
ops / public-key features / admin frontend / debug)에 분산되어 있다. 같은 갱신요청
큐를 두 화면이 서로 다른 액션 세트로 노출하고, provider 실패 하나를 추적하는 데
3~4개 화면 이동이 필요하며, dagster run과 적재 작업의 관계는 외부 Dagster UI
링크로만 이어진다. 사용자 지시로 호환성·기존 문서계약에 매이지 않는 통합 재작성을
결정했다.

## 결정

1. **2페이지 IA**: `/ops/pipeline`(실행·작업 — 상태 스트립+sensor, DB 스파인 실행
   타임라인, Dagster runs 보조 패널, 전역 이벤트 뷰, 스케줄 패널, 갱신요청 조작)과
   `/ops/datasets`(상태·정책 — provider×dataset×sync_scope 그리드, 정책 편집, ETL
   미리보기 흡수, "지금 갱신" 인라인 폐루프). 구 6개 라우트는 redirect 없이 폐기.
2. **실행 타임라인은 DB-only UNION**: `ops.import_jobs` ∪ `ops.feature_update_requests`,
   공유 keyset cursor `(created_at, id)` + `kind`. Dagster run(GraphQL, 휘발·cursor
   없음)은 목록 cursor에 섞지 않고 실컬럼 연결 속성 + 보조 패널로만 노출 —
   Dagster 다운 시에도 타임라인 cursor가 깨지지 않는다.
3. **신규 REST 2그룹 + 단일 게이트**: `/v1/ops/pipeline/*`·`/v1/ops/datasets/*`를
   `ops_routes_enabled` + `require_admin_frontend` 의존성으로 마운트(조작 포함 —
   기존 무인증 ops 패턴 승계는 현행 admin 게이트 대비 다운그레이드라 배제).
   `/ops/health-deep`·`/metrics`는 게이트 밖, `/v1/ops/live` WS는 BFF 프록시 불가로
   무게이트 유지하되 읽기전용 스냅샷 한정.
4. **공용 계약 보존**: `GET /v1/providers`·`/v1/providers/{p}/last-sync`는 PinVi
   read 표면(openapi.user.json + integration-map)이므로 존치(소형 public 라우터로
   분리). "호환성 무시"는 admin 표면 한정이다.
5. **데이터 모델 보강**: `ops.import_jobs.dagster_run_id` 실컬럼 + payload 백필 +
   인덱스(현 WS hot path의 payload JSONB 풀스캔 제거).
6. **ETL preview는 datasets 그룹의 fixture-only 기능으로 흡수**: 현행
   `/v1/debug/etl/*`의 raw live HTTP 경계는 ADR-044의 provider public client/typed
   model 규칙을 만족하지 않으므로 신규 제품 API에서 제거한다. 요청은
   `source=fixture`와 `max_items`만 받으며 외부 호출 budget은 0이다.
7. **datasets 시간·상태 의미를 분리**: provider backoff/rate-limit의
   `eligible_after`, Dagster definition tag와 RUNNING future tick의
   `next_scheduled_at`, 명시적 `stale_after_minutes`로 계산한 freshness를 서로
   추론하지 않는다. SLA 미설정 freshness와 Dagster 조회 실패 schedule은
   `unknown`으로 노출한다.
8. **실행 규율**: PR 단위 task(T-ADM-C2~C7)로 agent A(datasets 축)/B(pipeline 축)
   병렬, OpenAPI/types 생성물은 각 백엔드 PR에서 재생성(rebase 충돌은 재생성으로
   해소), 구 표면 제거는 링크 재배선(C6a) 후 삭제(C6b) 순. live e2e는 기존 게이트
   체계(SAFE provider·finally 복원·쿼터-민감 provider 금지)를 승계한다.

## 근거

- 조작 동선: "stale 발견→원인→재실행→확인"이 현재 3~4 화면 → datasets drawer 안에서
  폐루프로 닫힌다.
- 이종 소스 병합의 구조적 위험(cursor 파손·성능·degrade)을 목록 설계에서 원천 배제.
- 인증 4그룹 혼재는 통합 페이지에서 유지 불가능 — 단일 admin 게이트가 현행 대비
  보안을 낮추지 않는 유일한 통일점.

## 영향

- admin frontend 관련 페이지 7개·훅 4파일·mock e2e 19파일 재작성/삭제,
  entity-link 단일 URL 테이블 재매핑(14개 화면 전파).
- 백엔드 라우터 삭제 ~30 endpoint, 신규 2그룹 ~16 endpoint, alembic 1건.
- OpenAPI(admin)·user-client는 admin 표면만 변경(공용 read 표면 불변).
