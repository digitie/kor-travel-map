# 관리 파일 레지스트리 (managed file registry)

> 시스템에 적재되는 파일(Provider 다운로드·백업·오프라인 업로드·MOIS 원본 등)을
> **보고 추적**하기 위한 레지스트리. 단순 파일 리스팅이 아니라 각 파일이 어디에 어떻게
> 연결됐는지(provenance), 사용 중인지 임시인지(status/kind), 언제 받고 마지막으로
> 로드됐는지(시각)를 추적한다. (관리 UI 개편 D, 2026-07-05)

## 1. 왜 필요한가

Provider fetch·백업·오프라인 업로드·MOIS sync 등은 각자 호스트 디스크나 S3 버킷에 파일을
쌓지만, 그 파일이 **지금 쓰이는지·임시인지·언제 마지막으로 로드됐는지**를 한곳에서 볼
방법이 없었다. 잔존(zombie) 파일·유실 파일도 드러나지 않았다. 파일 레지스트리는 이 상태를
DB에 정규화해 관리 UI에서 추적·정리할 수 있게 한다.

## 2. 데이터 모델 (`0040_managed_files`)

- **`ops.managed_files`** — 파일 1건.
  - 식별: `storage_backend`(filesystem/s3) · `location`(논리 키) · `path`.
  - 분류: `kind`(provider_download/backup/upload/feature_file/report/**temp**/other) —
    "임시"는 lifecycle이 아니라 kind로 표현한다.
  - lifecycle: `status`(active/orphan/missing/deleted) + `orphan_reason`.
    `missing`(등록됐는데 실체가 사라짐)과 `orphan`(실체는 있는데 소유 레코드가 없음)은
    정반대 상황이라 분리한다.
  - provenance: `upload_id` · `origin_import_job_id` · `origin_dagster_run_id` ·
    `provider`/`dataset_key`.
  - 시각: `downloaded_at` · `last_loaded_at` · `last_seen_at` · `deleted_at`.
- **`ops.managed_file_events`** — 파일 생애 이벤트(registered/downloaded/loaded/
  marked_orphan/…/purged). `dagster_run_id`가 있으면 run당 1개로 dedupe.

값 정본은 `src/kortravelmap/core/managed_file_states.py`. CHECK 제약·repo·API·dagster·UI가
전부 이 튜플을 공유해 drift를 막는다.

## 3. 계측(hook) — 생산/소비 지점에서 등록

파일을 만들거나 로드하는 지점(백업 artifact 생성, 오프라인 업로드 저장, MOIS source sync,
provider fetch, dagster 적재)에 얇은 hook을 박아 `register_file`/`touch_loaded`/`record_event`를
호출한다. **hook 실패가 host op를 절대 깨뜨리지 않도록** `registry_guard` async
contextmanager로 감싸 예외를 삼킨다(레지스트리는 관측용, 부차적).

## 4. reconcile(scan) — 소유권 분리

hook은 in-band라 놓치는 파일이 있을 수 있어 주기 스캔이 실체와 대조(reconcile)한다.
컨테이너별로 볼 수 있는 스토리지가 달라 **스캐너 소유권을 나눈다**:

| location | 소유 | 트리거 |
| --- | --- | --- |
| `backup_root` | **api** | `POST /v1/admin/files/rescan`(동기) |
| `offline_uploads`(DB backfill) | api·dagster | rescan / scan job |
| `mois_source`, `object_store`(S3 실체) | **dagster** | `managed_file_scan` job(6시간 STOPPED 스케줄 + 수동) |

스캔 orphan rule은 **flag-only**(실체를 지우지 않고 `orphan`으로 표시). 예: e2e 백업이
`file_registry_e2e_backup_ttl_days`를 넘기면 `orphan(e2e_backup_expired)`, `temp`가
`file_registry_temp_ttl_days`를 넘기면 `orphan(temp_expired)`.

## 5. API (`/v1/admin/files`)

`require_admin_frontend` 게이트. 읽기 위주.

- `GET /admin/files` — kind/status/provider/location/registered_by/q/min·max_age_days/sort
  필터 + offset 페이지네이션(+total_count).
- `GET /admin/files/summary` — kind/status/location GROUP BY 요약.
- `GET /admin/files/{id}` — 상세 + **서버 조립 provenance links[]**(import-job/offline-upload/
  backup/provider/dagster-run) + 최근 이벤트 50.
- `GET /admin/files/{id}/events` — 이벤트 페이지네이션.
- `POST /admin/files/rescan` — backup_root 동기 스캔 + offline-uploads DB backfill.
  dagster 소유 location은 `deferred_locations`로 안내(즉시성 필요 시 `managed_file_scan` 수동 실행).
- `POST /admin/files/{id}/purge` — 좁은 gate(**S3 orphan + zombie_object/owner_row_deleted**) +
  파괴적 kill-switch(`require_admin_destructive_enabled`) + 서버측 재검증. 레지스트리 행만
  `deleted(purged)`로 플래그하고, **실체 S3 object 삭제는 S3 자격이 있는 dagster 스캐너가
  reconcile**한다(api 컨테이너에는 S3 삭제 자격을 두지 않는다).

## 6. UI (`/admin/files`, 시스템 그룹)

요약 칩(클릭=해당 필터) + 필터 바 + 목록(공용 `DataTable`) + 상세 provenance 패널
(`DetailList`·연결 항목 딥링크·이력 타임라인·메타 `JsonViewer`·zombie purge). 한국어 + `HelpTip`.

## 7. 관련

- 상태 상수: `src/kortravelmap/core/managed_file_states.py`
- repo: `src/kortravelmap/infra/file_registry.py`
- 스캐너: `src/kortravelmap/infra/file_registry_scan.py`(api-owned) +
  `packages/kor-travel-map-dagster/.../dagster/file_registry_scan.py`(dagster job)
- 라우터: `packages/kor-travel-map-api/.../api/routers/admin_files.py`
