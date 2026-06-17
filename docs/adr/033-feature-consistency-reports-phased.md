# ADR-033: `feature_consistency_reports` 단계적 도입 (Sprint 3~4: F1~F3, Sprint 5: F4~F8 + 게이트)

- **상태**: accepted (T-014 Sprint 1 진입과 동시 확정 — Phase 1은 Sprint 3, Phase 2는 Sprint 5에 코드 적용, 2026-05-25)
- **날짜**: 2026-05-25
- **결정자**: claude 제안 + 사용자 결정 (2026-05-29 승인 확정)
- **컨텍스트**: `kor-travel-geo` ADR-017 미러로 `ops.feature_consistency_reports`
  + batch DAG 게이트가 T-201로 잡혀 있음 (`docs/architecture/dagster-boundary.md §12`).
  F1~F8 케이스는 `kor-travel-map-spec.docx` B.18에 정의. 도입 시점이
  미정 — Sprint 5 운영 진입 직전에 몰아넣으면 게이트 자체가 Sprint 5 일정
  리스크, 너무 일찍 도입하면 schema가 미성숙 상태에서 굳어짐. 그러나
  정합성 검증 없이 Sprint 5 운영 진입은 silent data corruption 후 발견 비용
  폭증.

- **결정 (두 단계로 분할)**:

  **Phase 1 (Sprint 3~4, T-201a)** — 스키마 + critical 3건:
  - `ops.feature_consistency_reports` 테이블 마이그레이션:
    ```sql
    CREATE TABLE ops.feature_consistency_reports (
      report_id UUID PRIMARY KEY DEFAULT x_extension.gen_random_uuid(),
      batch_id UUID NOT NULL,
      started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      finished_at TIMESTAMPTZ,
      severity_max TEXT NOT NULL CHECK (severity_max IN ('OK','WARN','ERROR')),
      cases JSONB NOT NULL,         -- case별 결과 array
      summary JSONB NOT NULL        -- 집계: total/by_severity/by_kind
    );
    CREATE INDEX idx_reports_batch ON ops.feature_consistency_reports (batch_id);
    CREATE INDEX idx_reports_started ON ops.feature_consistency_reports (started_at DESC);
    ```
  - **F1**: `SourceRecord`가 있는데 `Feature`가 없음 (orphan source — ETL
    transform 실패 누수). severity=ERROR.
  - **F2**: `Feature.kind='place'` 인데 `PlaceDetail` 행 없음 (detail 누락 —
    ADR-018 위배). severity=ERROR. 다른 kind도 동일 패턴.
  - **F3**: `Feature.coord_5179 ≠ ST_Transform(coord, 5179)` (CRS drift —
    ADR-012 위배 / generated column 신뢰 손상). severity=ERROR.
  - Dagster 게이트는 **미적용** — 검증만 하고 mv_refresh swap은 차단 안 함.
    Phase 1은 "보이게 만들기" 목적.

  **Phase 2 (Sprint 5 운영 진입 직전, T-201b)** — 나머지 + Dagster 게이트:
  - **F4**: `dedup_review_queue` 미해소 N건 초과. severity=WARN.
  - **F5**: provider별 `last_success`가 SLA(예: 24h) 초과. severity=WARN.
  - **F6**: `opening_hours` 모순 (start > end, ADR-019 위배). severity=ERROR.
  - **F7**: cross-provider dedup mismatch (record linkage 점수 회귀 — Sprint
    별 baseline 대비 N% 이상 하락). severity=WARN.
  - **F8**: `file_object` orphan (RustFS object 존재 + DB feature 없음 / 그
    반대). severity=WARN.
  - **Dagster 게이트 적용** (`dagster-boundary.md §12`): root → child 적재 →
    `consistency_check` 실행 → `severity_max != ERROR` 시 `mv_refresh
    strategy='swap'`. ERROR 시 알림 + swap 차단.

- **근거**:
  - **스키마 비용 cheap**: 테이블 정의 + 인덱스 2개 → 초기 마이그레이션에
    함께 박는 게 alembic revision 비용 절감.
  - **F1~F3는 cheap + critical**: 단순 SQL이고 high-value. 첫 부트스트랩에서
    잡힘 — 누락 시 며칠 후 dedup 검토 큐에서 발견 = too late.
  - **F4~F8은 비용 더 큼**: cross-provider dedup score baseline 필요 (F7),
    file_object orphan 검사는 RustFS 스캔 비용 (F8) — Sprint 5에 묶는 게
    구현 비용 정직.
  - **Dagster 게이트는 Phase 2로**: Phase 1에서 게이트까지 박으면 첫 ERROR가
    swap 차단 → 운영 학습 곡선이 너무 가파름. Phase 1은 "관측", Phase 2는
    "차단".

- **결과 (긍정)**:
  - Sprint 5 운영 진입 시점에는 F1~F8 + 게이트 완성 → silent corruption 0.
  - F1~F3을 Sprint 3~4에 박아 두면 코드 작성 단계 내내 회귀 감지.
  - 스키마는 Sprint 3 초기에 박혀 있으므로 F4~F8 추가는 행 추가만 — alembic
    revision 1개로 끝.

- **결과 (부정)**:
  - Phase 1 시점에는 게이트 미적용 → 검증 결과를 운영자가 직접 확인해야
    함 (디버그 UI `/integrity` 페이지 또는 `feature_consistency_reports`
    direct SQL).
  - Phase 2에서 게이트 켤 때 첫 운영 batch가 F4~F8 위반으로 일제히 fail
    가능 — Phase 2 도입 PR은 반드시 dry-run report 첨부 후 점진 enable.

- **후속**:
  - `docs/test-strategy.md`에 F1~F8 케이스별 통합 테스트 매트릭스 추가.
  - `docs/architecture/dagster-boundary.md §12`에 본 ADR 링크 + Phase 1/Phase 2 분할 명기.
  - `docs/architecture/postgres-schema.md`에 `ops.feature_consistency_reports` 테이블
    정의 추가 (Phase 1 마이그레이션 시점).
  - 코드 작성 단계 진입 결정(T-014) PR에 본 ADR을 묶어 `proposed` →
    `accepted` 전환 + T-201을 T-201a (Phase 1) / T-201b (Phase 2)로 분할.

- **Amendment (2026-05-29, Sprint 3) — Phase 1 (T-201a) 구현 완료**:
  - `alembic 0003_feature_consistency_reports` — `ops.feature_consistency_reports`
    테이블 + `idx_reports_batch` / `idx_reports_started` (PK
    `x_extension.gen_random_uuid()`; T-RV-13에서 schema-qualified default로 정정).
  - `infra/models.py` `FeatureConsistencyReportRow` (Alembic target_metadata).
  - `infra/consistency.py` — F1~F3 raw SQL(ADR-004) + `build_report`(순수 집계) +
    `run_consistency_checks(session, *, batch_id, persist)`. **Dagster 게이트
    미적용** (Phase 1 = 관측). 케이스 추가는 `CONSISTENCY_CASES`에 선언만 추가.
  - **schema 현실 반영**: 본 저장소는 detail을 별도 테이블이 아닌 `features.detail`
    JSONB로 보관(ADR-018)하므로, F2는 "PlaceDetail 행 없음"이 아니라 "detail-bearing
    kind(place/event/notice/route/area)인데 `detail` JSONB 비어있음"으로 구현.
    price/weather는 detail 미보유(DETAIL_MODELS 제외)라 F2 대상 아님.
  - 테스트: `tests/unit/infra/test_consistency.py`(집계 5건) +
    `tests/integration/test_consistency_reports.py`(F1/F2 검출 + OK + 영속화, 2건).
