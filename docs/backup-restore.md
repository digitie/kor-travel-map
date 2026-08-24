# 백업 보존·감사 정책

`300` Alembic baseline부터 kor-travel-map의 백업은 **보존·감사·사고 분석용
artifact**다. 현재 배포물에는 이를 복원하거나 이전 revision으로 되돌리는 지원 경로가
없다. 이 문서는 현재 운영 계약만 설명하며, 과거 restore 절차는 실행 지침이 아니다.

## 현재 지원 범위

지원되는 쓰기 동작은 cold backup 생성뿐이다.

- Admin UI `/admin/backups`는 artifact 목록과 backup command만 노출한다.
- `POST /v1/admin/backups`는 기본적으로 plan을 만들고, 서버의 backup command 기능이
  명시적으로 켜진 경우에만 `execute=true`로 cold backup을 생성한다.
- standalone 개발 환경에서는 `scripts/docker-backup.sh`가 application DB, Dagster
  metadata DB, RustFS 데이터와 canonical manual-feature evidence를 하나의 artifact로
  남긴다.
- n150의 운영 backup 보존 위치·권한·실행 주체는 Docker Manager runbook이 정본이다.
  Map 저장소의 standalone compose 명령을 운영 환경에 대입하지 않는다.

백업 생성은 기본적으로 writer가 멈춘 상태를 요구한다. 의도적인 best-effort snapshot은
명시 opt-in으로만 남길 수 있지만, 그것도 recovery point나 cutover rollback 근거가 되지
않는다.

## Artifact 의미와 읽기 전용 검증

현재 `scripts/docker-backup.sh`가 만든 `meta/manifest.json`은
`schema_version: 4`, `recovery_status: "audit_only_no_restore"`를 기록한다. 이 값은
artifact가 존재해도 현 배포물로 DB·볼륨을 되살릴 수 없다는 명시적인 증거다.

artifact는 감사 시점을 함께 읽을 수 있도록 다음 세 부분을 포함한다.

- application DB `kor_travel_map`의 `postgres/kor_travel_map.dump`
- Dagster metadata DB `kor_travel_map_dagster`의
  `postgres/kor_travel_map_dagster.dump`
- RustFS 상태의 `rustfs/rustfs-data.tar.gz`, 그리고
  `meta/manifest.json`·`meta/SHA256SUMS`

이 경로와 파일명은 backup bundle의 식별·무결성 확인용이다. 어떤 파일도 현재 restore
명령의 입력 계약을 뜻하지 않는다.

외부 서비스의 상태·자격증명·별도 DB는 이 bundle에 포함하지 않는다. 그 보존 범위와
감사 절차는 해당 서비스의 운영 계약을 따른다.

Artifact에서 허용되는 작업은 다음처럼 읽기 전용이다.

1. `SHA256SUMS`와 manifest를 대조해 손상·누락 여부를 확인한다.
2. evidence JSONL의 행 수와 SHA-256 root를 manifest의 값과 비교한다.
3. 운영 사건의 범위, 당시의 command receipt, manual feature evidence를 감사한다.
4. 보존 기간·접근 권한·외부 사본 여부를 Docker Manager의 운영 정책으로 점검한다.

DB dump에는 민감한 운영 데이터가 들어갈 수 있다. artifact와 manifest는 최소 권한으로
보관하고, 실제 운영 host·계정·주소·비밀은 추적 문서에 기록하지 않는다.

## 명시적으로 지원하지 않는 동작

다음은 모두 현재 정책상 금지되어 있으며, 실행해도 지원되는 recovery가 되지 않는다.

- `scripts/docker-restore.sh`, `scripts/docker-restore-swap.sh`,
  `scripts/docker-restore-verify.sh`
- live E2E backup runner의 restore/swap entrypoint
- 이전 `/v1/admin/restore/{backup_id}` 및 hot-swap URI
- 관리자 화면의 Restore/Swap action
- `write-restore-swap-env.py`를 통한 env 생성
- 수동 `pg_restore`, `createdb`, DB rename, volume 교체
- archive Alembic replay, 과거 revision downgrade, `public.alembic_version` 직접 편집

위 shell entrypoint는 어떠한 `SKIP_*`, recovery, apply 환경변수보다 먼저 exit code `2`로
끝난다. retire된 HTTP URI는 `410 RESTORE_UNSUPPORTED`를 반환한다. 이 fail-closed
동작을 우회하기 위해 DB나 Docker volume을 직접 변경해서는 안 된다.

## `0236 → 300` handoff와의 구분

기존 production application DB의 `0236_tvn41s_compaction_drained → 300` 전환은
backup restore가 아니다. Docker Manager가 writer fence와 고정 candidate image를 결박한
상태에서 실행하는 한 번의 Alembic metadata handoff다. DDL, data rewrite, dump restore,
일반 `alembic stamp`, 직접 version-table SQL은 그 전환의 대안이 아니다.

Manager가 handoff receipt를 Map image에 전달할 때 receipt는 secret이 없는 integrity
evidence이며, root 소유 mode `0444` read-only mount여야 한다. API image는 non-root
`appuser`로 실행되므로 root 소유 `0600` 파일은 허용되지 않는다. Map helper는 receipt의
소유자·mode·symlink·candidate image·DB identity·만료 시각을 fail-close로 확인한다.

## 향후 recovery를 설계하려면

`300`용 recovery가 필요해지면 별도 설계와 별도 PR에서 처음부터 정의한다. 최소한 다음을
함께 제공해야 한다.

- 현재 schema/seed/role 계약에 맞는 recovery artifact format과 독립 verifier
- fresh target과 source artifact의 명시적 identity·checksum·권한 검증
- 불변 데이터와 mutable runtime projection의 복구 의미
- Docker/DB/volume mutation 전후의 writer fence와 auditable receipt
- 격리된 disposable target에서의 restore acceptance 및 live UI의 안전한 노출 방식

그 설계와 검증이 merge되기 전에는 이 문서의 backup artifact를 recovery에 사용하지
않는다.
