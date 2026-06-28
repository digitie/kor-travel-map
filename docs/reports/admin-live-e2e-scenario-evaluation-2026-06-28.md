# Admin UI live E2E 시나리오 평가 (2026-06-28)

## 목적

Admin UI의 주요 기능을 실제 n150 live 환경에서 끝까지 검증하기 위해, route/UI 조작/API 반영/교차 화면 반영을 함께 다루는 시나리오 catalog와 write live spec을 보강했다. catalog의 큰 수치는 실행 커버리지가 아니라 surface taxonomy이며, 실제 실행은 대표 route smoke와 별도 live spec이 담당한다. 데이터 유실 위험보다 실제 반영 확인을 우선하는 요청에 맞춰 feature change request와 Settings API key/audit 흐름에는 실제 write spec도 추가했다.

## 시나리오 범위

- 논리 시나리오 catalog: 13,651건(열거된 surface taxonomy이며, 실행 커버리지 수치가 아님)
- 기준 표면: home, public features/map/detail, admin features/new/change requests, curated features/detail, issues, import jobs/detail, providers, consistency, logs, dedup/enrichment reviews, feature update requests/detail, POI cache targets, offline uploads, backups, dagster, settings, ETL preview
- 교차 반영 축: admin list/detail ↔ public feature detail/map, write API ↔ admin UI, ops logs/import jobs/provider 상태, settings audit/API key 표면
- 실제 write 축(2026-06-29 후속 보강 이후 기본 full run에서는 skip, `E2E_ADMIN_FEATURES_WRITE=1`,
  `E2E_SETTINGS_WRITE=1` 또는 `E2E_ADMIN_WRITE=1` opt-in 필요):
  - `/admin/features/new`에서 add 요청 생성 → approve → admin/public detail 반영 → update approve/reject → deactivate → delete approve → public 404 확인
  - `/admin/settings`에서 public API key 생성 → API list 조회 → UI revoke → API/UI revoked 확인
  - API로 auth audit event 생성 → Settings UI audit table에서 확인
- destructive backup/restore/swap 실행은 기존 opt-in guard가 꺼져 있어 full run에서는 skip했다.
  plan/invalid id/UI command surface는 검증하고, execute 계열은
  `E2E_BACKUP_RESTORE_EXECUTE` 계열 opt-in이 필요하다.

## 발견 및 반영

- 오래된 live fixture의 feature id가 n150 DB에서 404를 내던 문제를 발견했다. `/v1/admin/features` live 응답 기준으로 `e2e/live/_fixtures.ts`의 `FEATURE_IDS`를 현재 active feature id로 갱신했다.
- curated 후보가 0건인 상태에서 empty-state row를 후보 row로 오인하던 live spec을 수정했다. 후보 테이블에 `curated-feature-row` test id를 부여하고, spec은 실제 후보 row만 클릭하도록 바꿨다.
- catalog route smoke는 full suite 동시 실행 시 30초 기본 timeout에 걸릴 수 있어 해당 테스트만 90초로 늘렸다.
- Settings 화면이 admin nav/live route catalog/README/workflow 문서에 누락된 부분을 보강했다.
- 2026-06-29 PR #564 사후 리뷰 반영으로 실제 write spec을 opt-in 게이트 뒤로 옮기고,
  catalog count 단언을 제거했다. route smoke는 이제 `ADMIN_SURFACES`가 아니라 catalog의
  `live_smoke` 항목에서 대표 시나리오를 뽑아 실제 네비게이션으로 검증한다.
- backup artifact 정리용 `DELETE /v1/admin/backups/{backup_id}` 계약을 추가하고, catalog의
  destructive risk 분류를 HTTP method/risk metadata 기반으로 정렬했다.

## n150 평가 결과

- 새 Settings write/API 반영 흐름 + catalog/misc smoke: 180/180 passed
- feature detail fixture 갱신 후 상세 단독 검증: 310/310 passed
- full live suite 1차: 1,826 passed / 6 skipped / 1 failed. 실패 1건은 catalog route smoke 기본 timeout(30초)으로, 기능 실패가 아니라 테스트 시간 예산 문제였다.
- full live suite 수정본: 1,828 passed / 5 skipped / 0 failed (34.1분)

## 남은 판단

- backup/restore/swap 실제 destructive execute는 별도 opt-in이 있어 이번 기본 full run에서는 skip된다. 운영 배포/복구 검증이 목적일 때 별도 세션에서 명시적으로 켜서 수행한다.
- 기능 추가가 필요한 영역은 본 평가에서 발견 즉시 새 기능으로 확장하지 않고, 테스트 안정화와 반영 확인만 수행했다.
