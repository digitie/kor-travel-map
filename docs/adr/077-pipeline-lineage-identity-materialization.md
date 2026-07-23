# ADR-077: pipeline lineage identity를 쓰기 시 materialize

- **상태**: proposed
- **날짜**: 2026-07-24
- **결정자**: 사용자 + Claude
- **출처**: C7 detail 504 근본원인 분석 + PR #832 2-reviewer 적대 리뷰(robustness residual) + 재설계 제안 `docs/reports/c7-kma-active-write-gate-redesign-2026-07-24.md` §C

## 컨텍스트

ops pipeline 조회(dataset detail·run-history·snapshot·overview counts·executions
list)는 모두 `src/kortravelmap/infra/pipeline_lineage.py`의 lineage CTE를 공유한다.
이 CTE는 **매 read마다** 다음을 전체 히스토리에 대해 재계산한다:

- `pipeline_jobs AS MATERIALIZED (… FROM ops.import_jobs WHERE quarantined_at IS NULL)`
  — 전 import_job을 materialize.
- `job_ancestry` — **RECURSIVE**로 모든 job의 부모 체인을 최상위까지 순회.
- `cycle_roots`/`terminal_roots`/`job_component_roots`/`job_components` — 각 job의
  weakly-connected-component root 재구성.
- `job_anchor_candidates`(window)/`job_owners` — 각 job의 소유 request 배정.
- `ranked_member_pairs`(window)/`canonical_provider_datasets` +
  `roots_with_identity`의 per-root 상관 서브쿼리 3개 — canonical
  `(provider, dataset_key, sync_scope)` pair·projected status 산출.

즉 **각 pipeline root의 identity**(component_root_id, owner_request_id,
anchor_depth, canonical pair, projected status)는 **immutable·append-only 엣지**
(`import_jobs.parent_job_id`, `feature_update_requests.job_id`)의 순수 함수인데도
저장되지 않고 **전 히스토리 그래프 순회로 매번 파생**된다.
`feature_update_request_idempotency`는 append-only + RESTRICT FK라 prune도 불가.

결과: 조회 비용이 누적 이력에 비례해 증가한다. 특히 `roots_with_identity`의
per-root 상관 서브쿼리는 O(roots × members)로 악화해 detail이 server timeout(504)을
냈다. #829(recency 시간창), #832(dataset-scoped)는 상관 서브쿼리가 도는 **root
집합만** 줄여 즉시 504를 없앴으나(2-reviewer clean), **planner-independent robustness
리뷰가 명시했듯** 상위 lineage CTE(`job_ancestry` 재귀·`ranked_member_pairs`
window·`canonical_provider_datasets` build)는 scoping과 무관하게 계속 전 히스토리에
돌며 무한 증가한다. C7처럼 단일 hot dataset은 k≈R이라 query 패치가
**constant-factor 개선일 뿐 asymptotic이 아니다.** 즉 query layer로는 이 성장률을
없앨 수 없다 — 스키마가 근본이다.

## 결정

lineage identity를 **쓰기 시 1회 계산·저장**하고, 조회는 파생 대신 저장값을 읽는다.
엣지가 immutable·append-only이므로 identity는 안정적이라 증분 유지가 가능하다.

1. **`ops.import_jobs`에 파생 컬럼 추가**: `component_root_id`(+ `owner_request_id`,
   `anchor_depth`). insert 시 채운다 — child는 **부모의 저장값 승계**(부모가 FK로
   먼저 존재), root job은 자기 자신. O(1)/insert. 이로써 `job_ancestry` 재귀와
   `job_components` 블록이 조회에서 사라진다.
2. **`ops.pipeline_root_dataset` projection 테이블**:
   `(root_kind, root_id, provider, dataset_key, sync_scope, operation_member_id,
   status, created_at)`, `(provider, dataset_key, created_at DESC)` 인덱스. detail·
   run-history·snapshot을 **인덱스 lookup**(O(log n))으로 만든다.
3. **CTE를 reference 정의로 유지**하고, `저장값 == CTE-파생값`을 seed 그래프
   (cycle·multi-request component·standalone job·quarantine 포함)에 대해 단정하는
   **일관성 테스트**를 게이트로 둔다 — drift를 배포가 아니라 CI에서 잡는다.
4. **DDL·cutover는 ADR-075 규율**을 따른다: 컬럼/테이블 추가는 `NOT VALID`/
   `CREATE INDEX CONCURRENTLY`, 1회 backfill(기존 이력 재귀 1-pass), 빈 PostGIS
   `alembic upgrade head && alembic check`·단일 head·rollback 절차. 읽기 전환 전
   **shadow-read**(저장값 + CTE 동시 계산·비교·alert)로 soak하고, soak·reconciliation
   후에야 CTE 파생 경로를 제거한다(legacy 제거는 별도 최종 단계).
5. 쿼리는 ADR-004대로 raw SQL `text()`를 유지한다(ORM 매핑 전용).

## 구현 단계 (phased, ADR-075 준수)

- **P0** ADR freeze + `저장값==CTE` 일관성 테스트 harness 작성(reference 게이트).
- **P1** migration: 컬럼(`component_root_id` 등) + `pipeline_root_dataset` 추가
  (`NOT VALID`/`CONCURRENTLY`), 1회 backfill.
- **P2** write-path 증분 유지: insert 경로(`feature_update_repo`·import job 생성)에서
  부모 승계로 채움.
- **P3** shadow-read soak: 조회는 여전히 CTE로 답하되 저장값을 병렬 계산·비교·alert.
- **P4** 읽기를 저장 컬럼/projection으로 전환(ops 쿼리 재작성). #829/#832 query 변형
  불필요해짐.
- **P5** soak 통과 후 legacy CTE 파생 경로 제거(최종 단계).

## 근거

identity가 immutable 엣지의 순수 함수이므로 "한 번 계산해 저장"이 정확성 손실 없이
가능하고, 조회의 성장률 자체를 O(history 순회)에서 O(log n) lookup으로 바꾼다.
query-level 패치(#829/#832)는 상수만 줄여 hot dataset에서 재발한다 —
"ops 쿼리가 또 느려졌다" 부류 전체를 근절하는 유일한 지점이 스키마다.

## 결과

- **긍정**: detail·run-history·snapshot·overview가 누적과 무관하게 빠름(인덱스 lookup).
  #829/#832의 scoped/recency 변형과 재설계 §B의 부하 압력이 대부분 무의미해진다.
- **부정**: write-path 증분 유지 로직, migration+backfill, 일관성 테스트/shadow-read
  soak가 필요하다. 저장 identity가 틀리면 ops UI가 오답을 보이므로 일관성 게이트가
  필수다.
- **전환/rollback**: 각 단계 독립 rollback(P1~P2는 컬럼/테이블 미사용이라 무해,
  P4 읽기 전환은 CTE 경로로 즉시 되돌림, P5만 비가역). shadow-read 불일치 시 P4 보류.

## 기존 결정과의 관계

- ADR-011(`import_jobs` 큐)·ADR-004(raw SQL) 위에서, lineage **파생을 저장으로** 옮긴다.
- ADR-075(cutover·DDL 규율)·ADR-074(write-safety)를 그대로 준수한다.
- #829(recency)·#832(dataset-scoped)는 **interim query 패치**였고, 본 결정이 durable
  대체다 — P4 이후 두 변형은 제거 대상. 재설계 제안 §C의 정식(durable) 형태다.
