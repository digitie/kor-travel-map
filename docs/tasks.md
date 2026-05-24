# tasks.md — 백로그

이 문서는 작업 백로그다. 우선순위 순. 각 작업은 `T-NNN` 번호로 식별한다.

## 진행 중

- [ ] T-002 — `docs/weather-feature-normalization.md` 작성 (v1 → v2 정리)
  - v1 docs를 v2 기준으로 ADR-010 정합되게 옮긴다
  - provider별 weather_domain / forecast_style / timeline_bucket 매핑 표
  - metric_key 표준화 표 (T1H, TMP, REH, WSD, RN1, PTY, SKY, FIRE_RISK, ...)

## 다음 (우선순위 순)

- [ ] T-003 — `docs/feature-files-rustfs.md` (v1 → v2)
  - boto3 S3 호환 API 사용 (RustFS 1차, MinIO/Ceph/R2 swap)
  - `FeatureFileSource` → `FeatureFile` 흐름
  - 다운로드 + 업로드 + 메타 생성

- [ ] T-004 — `docs/feature-opening-hours.md` (v1 → v2)
  - DTO와 DB 테이블 (`feature_opening_periods`, `feature_special_days`)
  - 24/7 표기 규약
  - duration_minutes 계산 (자정 넘는 period)

- [ ] T-005 — `docs/kraddr-base-types.md` + `docs/address-geocoding.md` (v1 → v2)
  - `python-kraddr-base` DTO 사용 기준
  - `python-kraddr-geo` `AsyncAddressClient` 주입 패턴
  - `AddressMatchReport.match_level` 표

- [ ] T-006 — provider별 ETL 문서 골격 작성 (각 provider 1개씩)
  - `docs/<provider>-feature-etl.md` — 표준 10섹션 구조
  - 대상: visitkorea-event, krmois-license, opinet-place-price,
    khoa-beach-info, krheritage-feature, krforest-feature, krex-rest-area,
    standard-data, kma-weather, notice (4개 합본)
  - v1 docs를 v2 기준으로 정리해 옮기되, wrapper 금지 + 함수 라이브러리
    패턴으로 재작성

- [ ] T-007 — `docs/dagster-boundary.md` (v1 → v2)
  - 라이브러리 책임 (collect/load 순수 함수, EtlJobSpec dataclass)
  - TripMate 책임 (asset/op/job, schedule, resource 주입)
  - 1차 자산 목록 (raw_kma_short_forecast, raw_opinet_prices, ...)

- [ ] T-008 — `docs/postgres-schema.md` (v1 → v2)
  - `docs/data-model.md`의 표 형식 reference
  - Alembic migration 예시
  - SET/RESET pattern, search_path

- [ ] T-009 — `docs/debug-fixture-workflow.md` (v1 → v2)
  - fixture 저장 helper + 민감정보 마스킹
  - replay runner 패턴

- [ ] T-010 — `docs/feature-db-initialization.md` (v1 → v2)
  - schema 부트스트랩 절차
  - `KrtourMapSettings.from_object(...)` 패턴
  - geocoder resource 주입

- [ ] T-011 — `docs/tripmate-integration.md` (v1 → v2)
  - TripMate가 본 라이브러리를 import하는 방법
  - engine/file_store/provider 주입 예시
  - 1차 사용 시나리오 (조회 + 적재)
  - SPEC V8 layer 정합

- [ ] T-012 — ADR-020+ 후속 결정 (필요 시)
  - 캐시 전략 (라이브러리 레벨 cache 도입 여부)
  - OpenAPI export 정책 (디버그 API 라우터 노출 시점)
  - 단위 테스트 coverage 단계적 상향 계획

- [ ] T-013 — `CHANGELOG.md` 초기 엔트리

- [ ] T-014 — 코드 작성 단계 진입 검토
  - 모든 문서 검토 완료
  - 사용자 승인
  - Sprint 계획 (`SPRINT-1.md` 또는 `docs/sprints/`?)

## 보류 (v2 1차 범위 외)

- [ ] T-100 — 디버그 UI 별도 Next.js 패키지 분리 (`krtour-map-debug-ui`)
- [ ] T-101 — Materialized View 도입 검토 (feature + detail flatten)
- [ ] T-102 — pg_prewarm 부팅 후 warm-up
- [ ] T-103 — 별도 streaming ETL (Kafka/Redpanda) 대응

## 완료

- [x] T-000 — git v1 보존 + main orphan 재시작 (완료: 2026-05-24)
- [x] T-001 — v2 핵심 docs 작성 (완료: 2026-05-24)
  - AGENTS.md, README.md, SKILL.md, CLAUDE.md
  - .env.example, pyproject.toml, .gitignore, .gitattributes, LICENSE
  - docs/architecture.md
  - docs/decisions.md (ADR-001 ~ ADR-019)
  - docs/data-model.md
  - docs/performance.md
  - docs/test-strategy.md
  - docs/backend-package.md
  - docs/agent-guide.md
  - docs/dev-environment.md
  - docs/windows-reinstall-recovery.md
  - docs/feature-model.md
  - docs/provider-contract.md
  - docs/external-apis.md

## 우선순위 가이드

- **즉시** — v2 코드 작성 단계 진입 전 필수: T-002 ~ T-011
- **이후** — 코드 작성 단계 진입 후 점진적 도입: T-012 ~ T-014
- **장기** — v2 1차 안정화 후: T-100 ~ T-103
