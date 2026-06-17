# ADR-011: 작업 큐는 `import_jobs` 영속화 + advisory lock + SKIP LOCKED

- **상태**: accepted
- **날짜**: 2026-05-24
- **결정자**: 사용자 + Claude (kor-travel-geo ADR-011 미러)
- **컨텍스트**: ETL 적재 작업 상태를 메모리에만 두면 프로세스 재시작 시
  진행 상황을 잃는다. SPEC V8 M-14의 `import_jobs` 테이블이 표준.
- **결정**:
  - `import_jobs(job_id UUID PK, kind, payload JSONB, state, progress,
    current_stage, source_checksum, error_message, started_at, finished_at,
    heartbeat_at, created_at)` 영속 테이블.
    ADR-045 T-205d 이후 batch DAG 연결용 `load_batch_id`, `parent_job_id` self-FK를
    추가했다.
  - 상태 전이: `queued → running → done | failed | cancelled`.
  - lifespan startup 복구: `state='running'` 잔존 행 → 무조건 `failed` (heartbeat
    만료 가정). `state='queued'` → 자원 있으면 재큐잉, 없으면 `failed`.
  - 다중 워커 직렬: `pg_try_advisory_lock(ADVISORY_SLOT_IMPORT_QUEUE)` +
    `SELECT ... FOR UPDATE SKIP LOCKED`.
- **근거**: kor-travel-geo ADR-011 운영 검증.
- **결과 (긍정)**: 재시작 안전성. 중복 실행 방지.
- **결과 (부정)**: Dagster도 자체 내부 queue(RunRequest/asset materialization)를
  가질 수 있으나, **ADR-045 모델에서 `ops.import_jobs`가 1차 영속 큐이고 kor-travel-map
  소유 Dagster sensor가 이를 폴링·claim한다**(ADR-045 §5). (이전 "ADR-016에서 분리"
  표현은 오참조 — ADR-016은 Record Linkage.)
- **후속**: `infra/jobs_repo.py` + Alembic migration + 통합 테스트 (완료). ADR-045
  feature-update 큐(`ops.feature_update_requests`)가 import_jobs 위에 얹힌다
  (`docs/adr045-standalone-plan.md` §2).
