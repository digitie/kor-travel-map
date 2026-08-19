# T-VN-41S snapshot streaming·material/receipt 분리 설계

- 기준일: 2026-08-18
- 이슈: #922
- 정본: ADR-081
- 상태: streaming/admission/관측/API typed error 구현, 물리 compaction migration 대기

## 1. 이번 branch에서 닫는 범위

snapshot capture는 `AsyncSession.stream()`의 server cursor와 `yield_per=1,000`을 사용한다. 첫 번째
scan은 item을 보관하지 않고 Merkle level stack만 유지해 count, canonical leaf byte 수, Merkle v1
root를 계산한다. item 1,000,000개 또는 canonical material 512 MiB를 넘으면 header/item INSERT 전에
각각 `snapshot_item_limit_exceeded`, `snapshot_byte_limit_exceeded`로 fail-close한다.

admission을 통과한 두 번째 scan은 1,000행씩 INSERT하고 첫 응답 page만 최대 요청 `limit`만큼
보관한다. 두 scan은 같은 transaction의 stream row `FOR SHARE` barrier 아래 실행되므로 source writer가
중간에 membership을 바꿀 수 없다. 그래도 두 번째 scan의 count/byte/root를 첫 scan과 다시 비교해
불일치하면 transaction 전체를 rollback한다. PostgreSQL server cursor의 `statement_timeout`은 각
`FETCH`마다 다시 적용되므로 그것만으로 전체 작업 시간을 제한하지 않는다. 1M급 scan을 수용하는
statement timeout 5분과 별도로, generic의 첫 barrier 또는 seal/request의 첫 stream `FOR UPDATE`부터
두 scan과 모든 INSERT·최종 receipt 조회가 끝날 때까지 단일 `asyncio.timeout()` 누적 5분 deadline을
적용한다. 첫 lock은 별도 5초 lock timeout으로 `snapshot_barrier_timeout`을 구분하며, 누적 deadline
초과는 cursor를 닫고 transaction 전체를 `snapshot_build_timeout`으로 rollback한다.

Merkle accumulator는 이미 NFC UTF-8 unsigned byte 순서로 들어오는 leaf만 받는다. level별 미결
subtree 하나만 유지하므로 추가 메모리는 `O(log N)`이고, 마지막 낮은 level부터 합치는 방식으로
ADR-081의 홀수 leaf 승격 규칙을 보존한다. 기존 list 기반 `snapshot_merkle_root()`와 0~16개 모든
크기에서 root가 같은 회귀 테스트를 둔다.

현재 스키마에서 가능한 공유는 먼저 만들어지고 75분 넘게 남은 generic snapshot 또는 request가 이미 참조하는
snapshot을 reconciliation seal이 같은 `snapshot_id`로 결박하는 것이다. exact
`(external_system, restore_epoch, material_high_watermark_relay_order)`만 재사용하고 header를 `FOR SHARE`로
잠근다. 만료·미참조 snapshot은 foreground/background GC가 일부 item을 지웠을 수 있으므로 재사용하지
않는다. true generic/reconciliation receipt 분리와 양방향 material 공유는 아래 migration 뒤에만
가능하다.

hourly GC 종료 관측에는 snapshot 두 relation의 table/TOAST bytes, index bytes,
`pg_stat_user_tables.n_dead_tup`, 두 relation 중 가장 긴 vacuum lag를 추가한다. 한 relation이라도 아직
manual/autovacuum 이력이 없으면 lag를 추정하지 않고 `snapshot_vacuum_not_observed` 관측 품질 reason과
별도 warning을 낸다. Dagster run config의 각 ceiling 초과는 exact reason과 warning으로 남기되 GC 성공
자체를 실패시키지 않는다.

API는 미래 compaction 뒤 request-bound page에 사용할
`410 SNAPSHOT_MATERIAL_COMPACTED`를 미리 고정한다. details는 `snapshot_id`, `item_count`,
`merkle_root`, `compacted_at`을 필수로 유지하며 retryable 응답이 아니다. item/byte admission의 두 413도
각 code와 details를 typed OpenAPI schema로 내보내 codegen이 generic map 없이 판독할 수 있게 한다.

## 2. 0225 예약과 migration barrier

T-VN-40C가 Alembic revision `0225`를 예약 중이다. 따라서 이 branch는 revision 번호를 만들거나
migration-bearing PR을 병합하지 않는다. terminal item compaction은 현재
`poi_cache_target_snapshots` header가 material과 receipt 역할을 동시에 하고 item FK도 직접
`snapshot_id`를 가리켜 안전하게 구현할 수 없다.

번호 없는 DDL 초안은
[`tvn41s/snapshot-material-schema.sql.draft`](tvn41s/snapshot-material-schema.sql.draft)에 둔다.
`0225`가 main에 착지한 뒤에만 실제 revision을 `0226+`로 배정한다. draft는 Alembic graph나 application
migration graph에 포함하지 않으며 실행 대상이 아니다.

## 3. 목표 물리 모델

`ops.poi_cache_target_snapshot_materials`는 exact source membership 하나를 소유한다. identity는
`external_system`, `restore_epoch`, `material_high_watermark_relay_order`이고, safe lower replay cursor,
item count/bytes, Merkle root, materialized/compacted 시각을 보존한다.

`ops.poi_cache_target_snapshots`는 immutable receipt다. 새 `snapshot_id`마다 `material_id`, receipt kind,
created/expiry를 가지며 generic page와 reconciliation request는 각자 receipt를 만든다. 같은 material을
가리키므로 generic/reconciliation/terminal audit가 item을 복사하지 않는다.
`ops.poi_cache_target_snapshot_items`의 PK/FK는 `(material_id, row_number)`로 옮긴다.

compactor는 material row를 `FOR UPDATE SKIP LOCKED`로 잡고 다음 조건을 모두 만족할 때만 처리한다.

1. 미만료 generic receipt가 없다.
2. `preparing|running` reconciliation이 없다.
3. 연결된 모든 reconciliation은 terminal이며 `completed_at`이 설정된 retention보다 오래됐다.
4. `compacted_at IS NULL`이고 실제 item count가 receipt count와 일치한다.

같은 transaction에서 material을 `compacted_at`으로 표시하고 item을 bounded batch로 삭제한다. page
reader는 material row `FOR SHARE` 뒤 item을 읽으므로 정상 full page 또는 typed 410 중 하나만 보고
부분 page를 보지 않는다. header/root/count/safe cursor와 reconciliation terminal receipt는 삭제하지
않는다.

## 4. upgrade/downgrade 원칙

upgrade는 먼저 material/receipt 관계를 만들고 기존 snapshot을 일대일 material로 backfill한 뒤,
동일 identity의 root/count/item이 정확히 같은 그룹만 deterministic material 하나로 합친다. 검증 전에는
기존 item FK를 제거하지 않는다. API/runtime role에는 receipt/material/item SELECT와 필요한 named
command만 최소 부여하고 Dagster compactor는 별도 command 경계를 사용한다.

compaction 뒤에는 item을 header/root에서 복원할 수 없다. 따라서 명시적 downgrade는
`compacted_at IS NOT NULL` material이 하나라도 있으면 fail-close한다. compaction 실행 전 상태에서만
receipt를 legacy snapshot/item 형태로 되돌릴 수 있다. 서비스 전 단계라 destructive reset을 선택할
수는 있지만, migration 함수가 조용히 audit item을 발명하거나 유실한 채 downgrade하지 않는다.

## 5. 검증 상태와 남은 gate

- 단위/API/Dagster 집중 테스트: 231개 통과.
- PostGIS: cache-target stream repository 37개 통과. 실제 1,005행의 1,000+5 bounded INSERT와 두 번째
  scan에서 1,000 item INSERT 뒤 누적 timeout이 header/item을 전량 rollback하고 대기 writer를 푸는
  회귀를 포함한다.
- synthetic accumulator: 1,000,001 leaf, traced peak 약 0.003 MiB, 약 64,700 leaf/s(현재 WSL 측정).
- strict mypy(변경 source 6개)와 Ruff 변경 파일 통과.
- 남음: `0225+` 실제 migration upgrade/downgrade, true receipt/material 양방향 공유, atomic terminal
  compaction repository/job, 실제 410 repository 경로, migration catalog/ACL/EXPLAIN, n150 DB 1M
  materialization·concurrent writer·compaction·vacuum soak.

synthetic 수치는 Python accumulator의 메모리 상한 증거이며 DB server cursor/INSERT 처리량이나 n150
운영 SLO를 대신하지 않는다. 최종 acceptance는 실제 PostGIS 1M admitted case, 1,000,001 item 또는
512 MiB+ rejection의 zero partial row, 동시 source mutation의 fixed membership/safe lower cursor,
compaction 전후 relation bytes/dead tuple/vacuum 추세를 같은 evidence receipt에 기록해야 한다.
