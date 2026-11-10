# runbook — ADR-121 R4 MCST 테마 전환(운영 창)

정본 설계는 [`docs/architecture/place-theme-attributes.md`](../architecture/place-theme-attributes.md) §8,
결정은 [ADR-121](../adr/121-mcst-theme-lists-as-place-attributes.md)이다. 이 문서는 운영 창의 순서와
되돌림만 적는다.

## 0. 무엇이 되돌릴 수 없나

- `ktmctl mcst-theme-transition --execute`: MCST Feature를 master로 병합(attach·collapse)하거나
  퇴역(retire, 반려 업종)시킨다. 퇴역한 `feature_id`는 재사용하지 않고 lifecycle override가 provider
  재활성화를 막는다. PinVi M05 사건이 batch마다 남고, 사건 표는 append-only다.
- `KOR_TRAVEL_MAP_MCST_THEME_ATTACH_MODE=apply`: 이후 MCST 적재가 붙임 경로로 돈다. 전환 뒤 `off`로
  되돌리는 것은 롤백이 **아니다**(옛 목록 앵커가 퇴역 Feature를 다시 claim한다).

그 밖의 단계(계획·리허설·perf EXPLAIN)는 읽기 전용이거나 transaction을 되감는다.

## 1. 전제

- Map에 alembic 447(`447_mcst_theme_transition`)까지 배포. 붙임 모드는 아직 `off`.
- PinVi 재vendor 불필요 — 447은 OpenAPI·사건 payload 모양을 바꾸지 않는다(사건 표에 열·FK만 더한다).
- 국가유산 367쌍 큐 적용과 **겹치지 않는다**(같은 병합 경로·protocol EX를 쓴다).

## 2. 순서

| # | 누가 | 무엇 | 되돌림 |
|---|---|---|---|
| 1 | deploy | Map 447 포함 SHA로 회전(attach mode `off`) | 회전 규칙대로 |
| 2 | deploy | **동결**: 모든 feature 적재 operation·queue와 `consistency_dedup_refresh_daily_schedule` 정지, STARTED run 0 확인 | 해제 |
| 3 | deploy | map DB 백업(pg_dump) — 되돌림 기준점 | — |
| 4 | R4 | 새 계획 `ktmctl mcst-theme-plan --samples 50 --ids-out … --plan-out plan.json`(읽기 전용) → 목록별 action 수·정밀도 표본·PinVi 참조 수 보고 | 없음(읽기) |
| 5 | coordinator | 표본 승인, `plan_sha256` 확정 | — |
| 6 | R4 | 표본 리허설 `ktmctl mcst-theme-transition plan.json --sample-per-action 200`(되감음) → stale·error 0 확인 | 없음(되감음) |
| 7 | R4 | **실행** `ktmctl mcst-theme-transition plan.json --execute --confirm-plan-sha256 <sha> --batch-size 500` | §3 |
| 8 | deploy | `KOR_TRAVEL_MAP_MCST_THEME_ATTACH_MODE=apply`(Map Dagster code-server·worker env) 회전 | `off`는 롤백 아님 |
| 9 | deploy | 동결 해제, MCST 적재 1회(`feature_place_mcst_culture_job`) | — |
| 10 | R4 | 적재 metadata `theme_attach` 상태 수 확인(owner·sticky·redirected·matched·created), 속성 필터 운영 EXPLAIN | — |
| 11 | admin | 촬영지 rule `c09e1efd…`의 `place_kind`를 비우는 `PATCH /v1/admin/curated-source-rules/{rule_id}`(If-Match) | 다시 PATCH |

실행기(7)는 n150에서 Map API 컨테이너의 DSN(`ktm_feature_service`)으로 돈다 — 사건 writer가 그 로그인과
admin executor membership을 요구한다. batch 하나가 transaction 하나이고 protocol EX를 쥔다. 중간에
끊기면 같은 명령을 다시 돌린다 — commit된 batch는 건너뛰고(`(plan_sha256, batch_index)`), 이미 전환된
Feature도 건너뛴다(`feature_id` UNIQUE).

계획과 실행 사이에 Feature가 바뀌면 그 Feature는 `stale_revision`·`stale_target`으로 건너뛴다(아무것도
쓰지 않는다). 동결 중에는 0이어야 한다.

## 3. 되돌림

- **전체**: 3의 백업으로 map DB를 복원한다(그 뒤의 쓰기는 잃는다 — 동결 중이므로 전환뿐이다). PinVi가
  그 사이 M05 사건을 ACK했다면 PinVi 참조도 함께 되돌려야 한다 — PinVi 소비자가 꺼져 있으면(기본) 없다.
- **부분**: `ops.mcst_theme_transition_items.before_state`에 퇴역 전 상태·link(역할 포함)·curation item이
  있다. 개별 Feature를 되살리려면 관리자 재활성화(lifecycle override 해제 → active)와 link 재지정을 손으로
  한다. 사건은 지우지 않는다 — 되살린 Feature를 가리키는 새 사건이 필요하면 별도 결정이다.

## 4. PinVi

- 사건은 `ops.feature_reference_reconciliation_events`에 `origin_kind = 'mcst_theme_transition'`으로 쌓인다.
  payload 모양은 manual dedup 사건과 같고 `case_id`·`resolution_id`에 batch·item id가 들어간다.
- PinVi 운영 M05 소비자는 기본 꺼짐이다. 꺼져 있는 동안 퇴역 id를 참조하는 PinVi 행(R2 실측
  `trip_day_pois` 1,020행·161 Feature, 전부 attach/collapse)은 batch 응답 `retired`와 저장된 card
  snapshot으로 보인다. 소비자를 켜면 쌓인 사건을 순서대로 `rebind`한다.
