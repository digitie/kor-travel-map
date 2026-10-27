# ADR-117 — SH 스냅샷·스칼라 정책 경로(411~432)를 퇴역하고, P는 배타 전용 bulk gate로 남긴다

- 상태: **proposed** (2026-10-27 소유자 승인 "권장대로" — 측정에서 실제 경합 효익이 나오지 않으면 퇴역. 측정 결과는
  아래 §1이고 효익은 0이다. 구현은 진행 중인 통합 PR #1426(433) 머지 뒤 별도 PR, 머지 때 accepted)
- 날짜: 2026-10-27
- 결정자: human(DC-2 방향 승인), Claude(측정·설계)
- 관계: **ADR-115를 부분 대체한다**(§2 표 참고). ADR-111(전역 gate·순서)은 유지하되 순서 맨 앞의 P를 배타 전용으로
  고정한다. ADR-112(reconcile)·ADR-113(spool)·ADR-116(geo 재사용)은 그대로다. 근거 정리는 Codex PR 46건 통합 리뷰의
  DC-2 항목(리드 보관)과 PR #1426의 ADR-115 §11(동결 기록)이다.

## 컨텍스트

ADR-115의 첫 구현(alembic 411~432, Codex PR #1358~#1419)은 전역 쓰기 잠금 P(`ops.lock_scoped_feature_write_protocol`,
advisory `(1369104691,115)`)에 공유(SH) 모드를 두고, 그 위에 다음을 쌓았다.

- scope·attempt·manifest 커널(411), provider 스칼라 후보 정책·epoch·projection guard(412·420·421),
- Airport·Rest 스냅샷 artifact·control·quota·executor lease·GC·후처리(430·432)와 그 bounded reader(427·431),
- 국가유산 bounded reader(422)와 국가유산 배타 opt-in(420·423),
- strict SH data guard와 정책 활성화 때 설치되는 statement barrier(429·430).

목적은 ADR-115 §9의 수용 기준 — 독립 두 작업의 실제 DML이 겹쳐 직렬보다 빨리 끝난다 — 이었다. 그런데 구조상
그 겹침이 일어날 수 없다(리뷰 DC-2, origin/main 원문 확인).

1. runner는 `trigger_kind == "schedule"`일 때만 SH 경로를 쓴다(`airport_snapshot_runner.py`, Rest도 같은 구조).
2. 두 asset이 같은 `GEO_HEAVY_POOL`을 쓴다(`assets.py`). 저장소 `docker/dagster.yaml`은 `default_limit: 1`이다.
3. 바뀌지 않은 입력만 적격이다. 그런 재적재를 싸게 하는 효익은 legacy의 no-op(`became_current`)과 ADR-116이 이미 준다.
4. legacy 적재가 쓰기 transaction 내내 P를 배타로 쥐어 SH를 막는다.

반면 정책 활성화(`activate_provider_field_policy`)는 되돌리는 경로가 없고, 활성화 뒤에는 33개 행 trigger가 모든 writer의
행마다 `pg_locks`를 읽는다. 국가유산 배타 opt-in은 실제 크기(약 4,000행)가 상한 2,730에 걸려 켜는 순간 실패한다
(`exclusive_provider_refresh.py`). 국가유산 native 경로와 422 reader의 production caller는 0이다.

## 1. 측정 (2026-10-27, n150 prod 읽기 전용)

적재를 새로 일으키지 않았다. 아래는 모두 기존 이력과 통계다(`BEGIN READ ONLY`, 공용 PG `kor_travel_map`·
`dagster_shared`, Map API·code-server 컨테이너 env).

| 항목 | 값 |
|---|---|
| alembic head | `432_rest_snapshot_atomic` |
| flag `KOR_TRAVEL_MAP_{AIRPORT,REST}_SNAPSHOT_ENABLED`·`KRHERITAGE_EXCLUSIVE_SNAPSHOT_ENABLED`·shadow scope | Map 컨테이너 어디에도 설정 없음 → 기본값 OFF |
| `feature.provider_field_active_policies` / policy epoch | 0행 / `epoch=0` |
| `ops.feature_write_attempts`·`provider_snapshot_controls`·`provider_snapshot_artifacts`·`provider_snapshot_quota_reservations` | 모두 0행 |
| `feature.provider_field_shadow_candidates`·`provider_field_shadow_policies` | 0행 / 0행 |
| SH 경로 관련 표 전체 크기 | 160 kB |
| Airport·Rest 적재 run 이력(Dagster 전체) | 전부 `manual`. **schedule로 시작한 run은 0건**(`run_tags`의 `dagster/schedule_name` 없음) |
| 427 expression index 3개 | `ix_source_entity_heads_bounded_evidence_key` 40 MB, `ix_source_links_bounded_evidence_key` 40 MB, `ix_source_records_bounded_evidence_key` 20 MB — **`idx_scan`=0**. 대상 표는 생성 뒤 쓰기 약 87만·87만·37만 건(`pg_stat_user_tables`)으로 그때마다 index를 갱신한다 |
| 2026-10-27 08:18Z 재기동 뒤 API·code-server 로그의 `55P03`/`LOCK_TIMEOUT` | 0건 |

legacy(EX) 적재 실측 — 쓰기 transaction은 step 안에 있으므로 P 보유 시간은 step 시간 이하다. 적재 단계별 시간이나
lock wait를 남기는 metadata는 없다(materialization 키 확인).

| run | dataset | 행 | step 시간 | 비고 |
|---|---|---:|---:|---|
| `0752f4f3` 2026-10-22 | `transport_airports` | 15 | 29.79 s (run 34.6 s) | geo 경계 호출 30건 포함 |
| `7757aa40` 2026-10-22 | `transport_rest_areas` | 215 | 4 m 1 s (run 247.4 s) | geo 경계 호출 215건 포함 |
| `174d1745` 2026-10-12 | `transport_rest_areas` | 215 | 2 m 14 s (run 227.8 s) | geo 호출 215건(1건 실패) |

P를 다른 작업과 다툰 증거는 없다. 두 dataset을 동시에 적재한 run 이력도 없다. P 보유 시간의 상한은 Airport 30 s,
Rest 4 min이고, 실제 쓰기 구간은 geo 호출(ADR-113 spool: 쓰기 transaction 밖)을 뺀 나머지라 이보다 짧다. 이 크기의
작업을 SH로 나눠 얻을 수 있는 이득은 많아야 수십 초에서 몇 분이다. 그런데 위 1~4 때문에 그 겹침은 일어날 수 없다.
**측정된 경합 효익은 0이다.** 남는 것은 비용이다. 쓰기마다 갱신되는 100 MB의 미사용 index와, 411~432 migration만 약 1.6만 줄(본문 SQL 1.1만 줄 포함)인 SQL과
그 Python·시험이 모든 잠금 변경에서 함께 검토돼야 하는 부담이다.

정밀 P 보유 시간(쓰기 transaction만)을 재려면 Airport 적재 한 번(15행, 35 s)을 일으키고 `pg_locks`를 표본하면 된다.
결론을 바꾸지 못하므로 하지 않았다. 퇴역 PR의 n150 통합 시험에서 같은 값을 격리 DB로 잰다(§4 시험 6).

## 2. 결정

### 2.1 퇴역한다

다음을 forward-only alembic 한 개(번호는 PR #1426의 433 다음 — 434 예정)와 같은 PR의 Python·Dagster·CI 정리로 없앤다.

| 묶음 | DB 객체(migration) | Python·Dagster·CI |
|---|---|---|
| scope 커널 | 411의 `ops.*scoped_feature_write*` 13개 루틴, 표 `feature_write_{attempts,manifests,dataset_scopes,region_scopes}`와 index | `infra/scoped_feature_writes.py`, `infra/scoped_provider_batch.py`, `client`의 `cancel_scoped_feature_write` 호출 |
| 스칼라 정책 | 412의 활성 정책·epoch·projection guard·statement barrier·scalar winner·`record_scoped_*`·`recompute_*`·`activate_provider_field_policy`, 표 `provider_field_active_policies`·`provider_field_policy_epoch`, trigger `trg_scalar_epoch`·`trg_scalar_unsupported`·`trg_feature_base_field_values_validate`(활성 정책 전용 분기) | `infra/scoped_provider_refresh.py`, `provider_field_candidates`의 정책·epoch 함수 |
| 배타 opt-in | 420·423 `_exclusive_provider_refresh_context`·`validate_exclusive_provider_snapshot`·`reject_unsupported_active_*`·`validate_active_*` | `infra/exclusive_provider_refresh.py`, `resources.py`·`client`의 opt-in 분기, env `KOR_TRAVEL_MAP_KRHERITAGE_EXCLUSIVE_SNAPSHOT_ENABLED` |
| SH stamp SD | 421 `upsert_provider_geocode_stamps_ex`·`lock_/reobserve_/_validate_scoped_provider_geocode_stamps`·`guard_stamp_writer_entry`와 그 trigger·inventory | legacy stamp 경로(`_421_legacy_stamp_upsert`가 대체한 본문)는 남긴다 — §3 주의 2 |
| reader | 422 국가유산, 427 Airport, 431 Rest의 bounded reader와 helper 15개, 427 index 3개 | `infra/heritage_evidence_reader.py`, `transport_{airport,rest}_evidence_reader.py`, `providers/kor_travel_{transport,rest}_{apply,evidence}.py` |
| strict guard | 429·430의 strict SH data guard·설치기·inventory 6개 | — |
| 스냅샷 복구 | 430·432의 artifact·control·quota·executor lease·plan bind/reset·apply·postprocess·GC 루틴과 표 4개(`provider_snapshot_{artifacts,controls,quota_limits,quota_reservations}`), trigger `trg_provider_snapshot_immutable_input` | Dagster `{airport,rest}_snapshot_{backend,observation,postprocess,runner,runtime}.py`, `definitions.py` 결선, `assets.py`의 `run_*_snapshot_if_supported`, `client/_{airport,rest}_snapshot.py`·`_snapshot_atomic.py`·`_snapshot_postprocess.py`, `infra/provider_snapshot_{artifact,postprocess_repo,recovery_repo}.py`, `infra/rest_area_snapshot_artifact.py`, env 두 개 |
| 측정·CI | — | `scripts/measure_scoped_native_scalar.py`(PR #1426이 옮김)와 그 단위 시험, `test_scoped_write_baseline.py`, 위 모듈의 단위·통합 시험(약 60개 파일) |

없애는 것은 **flag OFF·정책 0행에서 도달할 수 없는 코드와 그 저장소**다. prod의 해당 표는 모두 0행이라 데이터
이관은 없다.

### 2.2 P는 배타 전용 bulk gate로 남긴다 (ADR-111 모델로 완전 복귀는 하지 않는다)

검토한 두 안:

- **(A) P를 배타 전용으로 남긴다.** SH 모드와 regime(PR #1426의 `ops.lock_single_feature_writer_protocol()` — epoch>0이면
  P EX) 분기를 없앤다. epoch 표가 사라지므로 단건·관리 writer는 P를 잡지 않는다. 414 이전과 같이 행 잠금과
  ADR-111 gate만 쓴다. 이것은 #1426의 epoch=0 동작과 같다. P를 잡는 것은 대량 적재(`lock_feature_curation_write`),
  권위 finalize·seal의 tracking prefix(P EX → L), provider patch 재진입, curation import, 유지보수·DDL만 남는다.
  `lock_scoped_feature_write_protocol(false)`는 23514로 거부한다. 남는 공유 호출자가 없음을 lint로 센다.
- **(B) P를 없애고 ADR-111 모델로 완전히 돌아간다.** 기각한다. 430은 seal·finalize를 SERIALIZABLE에서
  READ COMMITTED로 바꿨다. 그 근거가 "P EX 아래에서는 큐레이션 입력이 바뀌지 않는다"는 것이다.
  `seal_provider_curation_snapshot_receipt`처럼 `feature-curation-write`·`feature-write-all` 없이 P만 잡는 확정 루틴이
  있다. P를 빼려면 그 격리를 다시 증명하거나 SERIALIZABLE로 되돌려야 한다. 이것은 퇴역이 아니라 재설계이고,
  측정된 효익도 없다.

**(A)를 채택한다.** 정확성 증명을 새로 하지 않고 바꿀 수 있는 가장 단순한 안이다. 남는 중복(P EX와
`feature-curation-write`를 함께 잡는 경로, 리뷰 A2-06)은 알려진 잔여로 기록한다. 이 중복을 없애는 일은 seal 격리를
다시 증명하는 별도 ADR의 몫이다. ADR-111 §2의 순서는
`P(EX 전용) → curation-import → feature-curation-write → feature-write-all → feature-write:<id> → curation-catalog-write`이다.
L(pipeline-lineage)은 확정 경로에서 P 뒤, 장부 경로에서는 P 없이 잡는다(PR #1426 WI-1).

### 2.3 남기는 것

- 410 shadow(`provider_field_shadow_*`, `record_provider_field_candidates`의 shadow capture). 리뷰 WI-5 범위이고 운영
  OFF·0행이지만 ADR-115 §3의 후보 원장 기록이라 이 ADR 범위 밖이다. 412가 그 capture와 정책 경로를 한 루틴에
  섞어 두었으므로 migration은 shadow 분기만 남기고 다시 쓴다.
- 424·433 tracking prefix, 425·426 provider patch의 P 진입, 428 bounded curation capture(seal 공통). 430이 고친
  finalize·seal·`refresh_curated_source_observation`·`sync_concierge_theme_catalog`·tracking 명령의 본문에서는
  스냅샷 분기만 빼고 다시 쓴다.
- 413 legacy SQL 진입(P EX 첫 줄). 배타 전용 P와 그대로 맞는다.

### 2.4 ADR-115와의 관계

ADR-115 중 다음은 **이 ADR이 대체한다**. §3의 정책 cutover·active revision, §5.1 지역 scope 계층, §5.2(3)의 공유 진입,
§7의 scope epoch·lease, §8 4~5단계(opt-in 확대), §9의 "독립 2작업 동시 완료" 수용 기준이다. T-CWRITE-03·04·05·07·
09는 이 ADR 머지 때 "ADR-117로 대체"로 닫는다. ADR-115의 문제 정의(§1·§2 불변식·§4 winner·retire·병합 규약)는
살아 있다. 동시 쓰기를 다시 추진하려면 **먼저 실제 경합을 측정해** 효익을 보인 뒤 새 ADR로 시작한다. 측정 없는
성능 전용 마이그레이션은 하지 않는다(리뷰 A2-05의 프로세스 규칙).

## 3. 마이그레이션 규칙 (434)

424·426·433과 같은 틀을 따른다.

1. 선행 head가 PR #1426의 433인지 확인한다. 다시 쓰는 모든 보존 루틴은 433 시점의 시그니처·소유자·종류·
   SECURITY DEFINER·`prosrc` SHA-256을 고정한다. 하나라도 다르면 아무것도 바꾸지 않고 실패한다.
   DROP 대상도 시그니처와 소유자를 확인한다.
2. **prod 사전 조건을 migration이 확인한다.** `provider_field_active_policies` 0행, epoch 0, `feature_write_attempts`·
   스냅샷 표 0행이어야 한다. 아니면 23514로 실패한다(활성화된 DB를 조용히 끊지 않는다).
3. `lock_timeout` 1 s / `statement_timeout` 30 s 상한 아래에서 P EX → L을 먼저 잡는다.
4. 보존 루틴을 다시 쓴 **뒤에** 대상 루틴·trigger·표·index를 의존 순서대로 DROP한다. CASCADE는 쓰지 않는다.
   남은 의존이 있으면 실패해야 한다.
5. 다시 쓴 본문이 계획과 같은지, 메타데이터(oid·소유자·ACL·config)가 보존됐는지 재검증한다. receipts head CHECK,
   `_application_migration_graph.json`, `runtime_privileges` 목록을 갱신하고 `head-schema.sql`을 재생성한다.
6. 마지막 문장은 `SET ROLE ktm_feature_schema_owner`다. **RESET ROLE은 쓰지 않는다.**

주의:
1. 427 index 3개 DROP은 각 표에 ACCESS EXCLUSIVE를 잠깐 건다. 1 s lock_timeout 아래에서 실패하면 재시도로 처리한다.
   CONCURRENTLY는 transaction 안에서 쓸 수 없으므로 쓰지 않는다. 배포 runbook은 ADR-114 419와 같다. 대상
   schedule을 멈추고 in-flight 0을 확인한 뒤 실행한다.
2. 421은 legacy stamp upsert의 본문도 바꿨다. legacy 경로가 SD 함수를 거치는지 먼저 확인한다. 거치면 legacy
   본문으로 되돌린 뒤 SD를 지운다.

## 4. 시험

1. migration-only DB에서 434 뒤 `head-schema.sql`과 정확히 같다(기존 oracle 시험).
2. 선행 본문 hash가 하나라도 다르면 실패하고, 활성 정책 1행·attempt 1행 fixture에서는 23514로 실패한다.
3. `lock_scoped_feature_write_protocol(false)`는 23514다. lock-order lint(PR #1426 WI-4)는 공유 P 호출자 0과
   regime 함수 부재를 센다. 일부러 공유 호출을 심은 fixture로 빨개지는지 확인한다.
4. 기존 legacy 적재·finalize·seal·tracking·단건 writer 통합 시험이 그대로 초록이다. Airport·Rest·국가유산 asset은
   flag 없이 legacy 경로만 탄다. 지운 env를 설정해도 무시하지 않고 기동을 거부한다(오설정 탐지).
5. 단건 writer는 P EX holder 뒤에서 기다리지 않는다(#1426 epoch=0 시험을 epoch 표 없이 유지).
6. n150 격리 DB에서 Airport fixture 적재 한 번의 P 보유 시간을 `pg_locks` 표본으로 기록한다. 퇴역 뒤 legacy 경로의
   P 보유 시간이 퇴역 전과 같다(±10 %, 3회).

검증은 n150 `~/gate-slot.sh`로 Map CI의 네 세션과 같은 경계에서 돌린다.

## 5. 결과

- 긍정: 미사용 index 100 MB와 행마다의 갱신 비용, 되돌릴 수 없는 정책 활성화 위험, 약 35건의 미해결 결함(리뷰 DC-2
  차단 조건 표)이 사라진다. 이후 잠금 변경의 검토 범위가 줄어든다.
- 부정: ADR-115식 동시 쓰기를 다시 하려면 처음부터 시작한다. 지운 코드는 git 이력(432 head)에 남는다.
- 진행 중인 Codex draft PR #1424(스냅샷 stale 재계획 복구, 433 추가)는 이 ADR이 지우는 경로를 고친다. 머지 전에
  소유자가 정리할지 정해야 한다. 433 번호도 #1426과 겹친다.

## 6. 구현 순서

1. (완료) 측정과 이 문서. 소유자 승인 2026-10-27.
2. PR #1426 머지를 기다린다. 그 뒤 이 브랜치를 rebase한다. 433의 최종 본문 기준으로 보존 루틴 목록과 hash를 다시
   만든다(codegraph로 caller를 먼저 평가한다).
3. 434 migration과 Python·Dagster·CI 삭제를 한 PR로 낸다. 커밋은 DB, Python·Dagster, 시험·CI, 문서(ADR-115 머리말·
   README 색인·tasks 대체 표시·journal·resume·CHANGELOG)로 나눈다.
4. n150 CI-parity 게이트, CI 초록, 적대 리뷰 2인. 머지와 배포는 소유자가 한다(배포는 419 runbook과 같은 정지 순서).
