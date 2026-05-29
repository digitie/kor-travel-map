# 문서 정합성 정리 — 2026-05-29

Sprint 3 코드 머지(PR#69~#73: ADR-030~033 승인 + `feature_consistency_reports`
Phase 1 + `feature_repo` 적재/조회 + `/features` 라우터) 이후, 전체 문서를 다시
읽고 코드와 충돌·drift·누락을 찾아 정리한 결과 요약이다.

> 방법: Explore 에이전트 3대로 문서 클러스터를 병렬 검토한 뒤, **각 발견을 실제
> 소스 파일로 직접 재검증**(에이전트 환각·줄번호 오류 필터링)하고 확정된 항목만
> 수정했다. 코드는 수정하지 않음(문서 정리 전용).

## 1. 수정한 항목 (verified)

| # | 파일 | 문제 | 수정 |
|---|------|------|------|
| 1 | architecture.md / debug-ui-package.md / backend-package.md / standard-data-feature-etl.md / tripmate-integration.md / README.md | debug-ui 기본 포트가 **8600**으로 표기 (실제 `settings.py` 기본은 **8087**) | 8600 → 8087 (16곳, 6파일). journal.md의 역사적 기록은 보존 |
| 2 | architecture.md §4 | 엔드포인트 다이어그램이 미구현 라우터(`/features/nearby` 등)를 구현된 것처럼 나열 | 구현됨(PR#) vs Sprint 3~5 예정으로 구분 표기 |
| 3 | debug-ui-package.md §6 | 엔드포인트 표가 전체 계획인데 구현 현황 불명 | 상단에 "구현 현황" 블록 추가 (실제 노출 엔드포인트 + flag) |
| 4 | debug-ui-package.md §4 | settings 예시가 구식(`reload` 등 미사용, provider key 8종/`features_routes_enabled` 누락) | 실제 `settings.py` 필드로 교정 |
| 5 | data-model.md §9.5 | `ops.data_integrity_violations`를 정합성 테이블로 서술하나 미구현 | "미구현(계획)" 주석 + §9.7로 실제 구현 테이블 안내 |
| 6 | data-model.md §9.7 (신규) | ADR-033 Phase 1으로 실제 도입된 `ops.feature_consistency_reports` 누락 | DDL + 인덱스 섹션 추가 (alembic 0003 정합) |
| 7 | test-strategy.md §5 | e2e 경로를 `tests/e2e/`로 표기 (실제 없음) | `packages/krtour-map-debug-ui/tests/`로 정정 + 실 DB는 메인 `tests/integration/` |
| 8 | backend-package.md §1 | `AsyncKrtourMapClient`를 구현된 API처럼 서술 (미구현) | "구현 현황" 주석 — 현재는 `feature_repo` 직접 호출 단계 |
| 9 | agent-guide.md §1 | "ADR 027~034 proposed" (이미 전부 accepted) | "001~044 전부 accepted, 다음 후보 045"로 정정 |
| 10 | CLAUDE.md §2 / AGENTS.md | ADR 현황 "001~043" + "다음 후보 044" (044 이미 accepted) | "001~044 accepted, 다음 후보 045" + 030~033/033 Phase 1 반영 |
| 11 | README.md | "빠른 시작 (구현 후 사용 예정)" (debug UI 동작) | "Sprint 3 진행 중 — feature 적재/조회 + debug UI 동작" |

## 2. 발견했으나 수정하지 않은 항목 (코드 레벨 — 문서 정리 범위 밖)

### 2.1 `source_role` enum 불일치 (코드 ↔ 코드, **잠재 버그**) — ✅ 후속 PR에서 해소

- **DTO** `dto/_enums.py` `SourceRole` + **data-model.md** + **feature-model.md §3** =
  `primary / base_address / base_coordinate / enrichment / correction /
  duplicate_candidate / media / weather_context` (8종, 서로 일치 — **정본**)
- **ORM** `infra/models.py` + **alembic 0002** CHECK = `primary / enrichment /
  geocoded / phone / media / weather_context / observation / external_link` (8종 — 오류)

→ DTO로 `SourceRole.BASE_ADDRESS`/`CORRECTION`/`DUPLICATE_CANDIDATE`를 만든 뒤
`source_links`에 적재하면 **DB CHECK 제약 위반**이 발생할 수 있었다.

**해소 (후속 PR, 2026-05-29)**: provider/테스트/spec(feature-model §3)가 모두 DTO
enum을 정본으로 쓰고, `geocoded`/`phone`/`observation`/`external_link`는 코드
어디에서도 미사용임을 확인 → **DB CHECK를 정본(DTO)으로 교체**.
- `infra/models.py` `ck_source_links_role` CHECK 값 정정
- alembic `0004_fix_source_links_role_check` — 기존 DB의 CHECK를 ALTER (기존
  데이터는 primary/enrichment만이라 위반 없음)
- 회귀 테스트 `tests/integration/test_source_role_check.py` — 8개 enum 값 전부
  INSERT 가능 확인

### 2.2 `provider_sync_state` 컬럼 설계 차이 — ✅ 문서를 구현에 맞춰 정정

data-model.md §4가 초기 설계(metadata_hash / last_observed_source_version /
last_attempt_at / last_full_scan_at / last_error / last_error_at / extra)를
서술했으나 실제 마이그레이션 0002 / `ProviderSyncStateRow`는 간소화 버전
(last_failure_at / consecutive_failures + status CHECK)으로 적용됨.

**해소(후속 PR, 2026-05-29)**: data-model.md §4 SQL을 **구현 스키마로 교체** +
status CHECK 추가, 제외된 컬럼은 "후속 후보 (미구현)" 주석으로 명시. 컬럼을 실제로
추가할지는 별도 ADR 판단 — 본 정리는 문서를 코드 현실에 정렬만 함.

### 2.3 alembic 파일명 ↔ revision id — ✅ 명명 규약 문서화

`0003_feature_consistency_reports.py`의 revision id는 `0003_consistency_reports`
처럼 파일명과 id가 다른 게 4건 전부의 패턴. 기능상 무해(`down_revision`은 id로
연결).

**해소(후속 PR, 2026-05-29)**: postgres-schema.md §8.4 명명 규약을 실제 컨벤션
(`NNNN_<descriptive>.py`, 파일명≠revision id 허용)으로 갱신. 옛 `YYYYMMDDhhmm`
예시는 미사용이라 제거.

## 3. 결론

- 문서 전용 변경(11개 항목, 코드 무수정). 포트 drift가 가장 광범위했고, 나머지는
  "구현 예정 → 구현됨" 상태 동기화 + 신규 테이블 문서화.
- §2의 코드 레벨 불일치(특히 2.1 source_role)는 본 정리 범위를 벗어나므로 후속
  코드 PR에서 다룬다.
