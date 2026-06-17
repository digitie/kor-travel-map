# ADR-040: Backup/Restore + 핫스왑 UI

- **상태**: accepted (PR#33, 2026-05-27)
- **날짜**: 2026-05-27
- **결정자**: 사용자

### 컨텍스트

운영 단계에서 다음 시나리오 필요:

- **백업**: PostgreSQL `feature.*` + `provider_sync.*` + `ops.*` schema + RustFS
  `feature-files` 버킷을 한 번에 dump → 외부 저장소(NTFS / R2 / S3) 보관.
- **복원**: 위 dump를 새 환경에 hot-swap. 운영 DB를 멈추지 않고 staging DB로
  먼저 복원 후 atomic switch (DNS / connection pool 재설정).
- **운영 UI**: 백업 schedule 보기 + 실행 / 복원 큐 보기 + 진행률 / failed
  엔트리 retry.

이 기능은 ADR-035의 "프로덕션 admin UI"의 한 갈래.

### 결정

- **Backup 단위**:
  - PostgreSQL: `pg_dump --format=custom --schema=feature --schema=provider_
    sync --schema=ops` (extension schema는 별도, `x_extension`은 복원 시
    `CREATE EXTENSION ... SCHEMA x_extension`만 수동).
  - RustFS: `rclone sync rustfs:feature-files <backup-target>:feature-files-
    <YYYYMMDD-HHMMSS>` 또는 RustFS native snapshot.
- **저장 위치**: 1차 NTFS의 `data/backups/<YYYYMMDD-HHMMSS>/`, 2차 외부
  (S3/R2) — `KOR_TRAVEL_MAP_BACKUP_TARGETS` settings로 multi-target.
- **Restore 패턴**: hot-swap 권장 — staging DB에 복원 → smoke test (디버그
  API ping + count check) → connection pool DSN 교체 → 구 DB 제거.
- **운영 UI 라우터** (ADR-035):
  - `GET /admin/backups` — 목록 (날짜 / 사이즈 / status)
  - `POST /admin/backups` — 즉시 백업 실행 (ADR-039 mutex `backup`)
  - `POST /admin/restore/{backup_id}` — staging DB로 복원 (ADR-039 mutex
    `restore`)
  - `POST /admin/restore/{backup_id}/swap` — atomic switch
- **스케줄**: daily full + hourly WAL(추후). Sprint 5 진입 시 cron 또는
  Dagster schedule.

### 근거

- PostgreSQL `pg_dump --format=custom` + RustFS snapshot이 industry-standard.
- hot-swap은 비용이 비싸지만 운영 downtime 0 — 본 라이브러리는 TripMate에
  실시간 의존하므로 downtime cost가 크다.

### 결과 (긍정)

- 운영자가 콘솔에서 백업/복원 가능 — DB shell 진입 불필요.
- staging 복원으로 PIT(point-in-time) 검증 후 switch.

### 결과 (부정)

- hot-swap을 위한 dual DB 환경이 필요 — 운영 인프라 비용 증가.
- 완화: 초기 단계는 cold restore(downtime 허용)로 시작, Sprint 5에 hot-swap
  도입.

### 후속

- `docs/adr/README.md` ADR-035 amendment — admin 라우터 표에 backup/restore
  prefix 추가.
- `docs/backup-restore.md` 신설 (Sprint 4~5 prep PR).
- `src/kortravelmap/infra/backup.py` (Sprint 5).
- `packages/kor-travel-map-api/src/kortravelmap/api/routers/admin_backups.py`.
- `KOR_TRAVEL_MAP_BACKUP_TARGETS` settings + Pydantic validator.
